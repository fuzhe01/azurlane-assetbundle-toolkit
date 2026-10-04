// 读 .skel 的 **skeleton 级原点偏移**（skeletonData.x/y）—— 各层对齐的真来源。
//
// 为什么用 node + 官方 runtime，而不是在 Python 里手搓二进制解析：
//   本轮手搓过，连错四次（都记在下面 ④ 那段注释里）。项目里已经 vendored 了前端正在用的
//   官方 `spine-all.js`，直接调它读到的就是**前端真正看到的值**，零解析歧义。
//
// 用法: node scripts/diag/skel_header.js <目录|.skel> [...]
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = path.resolve(__dirname, '..', '..');
const VENDOR = path.join(ROOT, 'Output', 'gallery_v2', 'vendor', 'spine', 'spine-all.js');

function loadSpine() {
  const src = fs.readFileSync(VENDOR, 'utf8');
  // spine-all.js 不是 UMD —— 它是 `var spine; (function(spine){...})(spine || (spine={}))`，
  // 即挂在一个全局 `spine` 变量上。尾部给 three.js 的 mesh 做了 `THREE.Mesh` 继承，
  // 所以必须先摆一个 THREE 桩，否则加载就 ReferenceError。
  const stub = new Proxy(function () {}, {
    get: (t, k) => (k === 'prototype' ? {} : stub),
    apply: () => stub,
    construct: () => ({}),
  });
  const g = { THREE: stub };
  g.window = g;
  g.self = g;
  g.document = { createElement: () => ({ getContext: () => stub, style: {} }) };
  g.navigator = { userAgent: 'node' };
  g.window.document = g.document;
  vm.createContext(g);
  vm.runInContext(src, g, { filename: 'spine-all.js' });
  return { spine: g.spine, ctx: g };
}

function main() {
  const { spine, ctx: g } = loadSpine();
  if (!spine || !spine.SkeletonBinary) {
    console.error('[红] 没从 spine-all.js 拿到 SkeletonBinary');
    process.exit(2);
  }
  const targets = process.argv.slice(2);
  if (!targets.length) {
    console.error('用法: node skel_header.js <目录|.skel>');
    process.exit(2);
  }

  const files = [];
  for (const t of targets) {
    const st = fs.statSync(t);
    if (st.isDirectory()) {
      for (const f of fs.readdirSync(t).filter((x) => x.endsWith('.skel')).sort()) {
        files.push(path.join(t, f));
      }
    } else files.push(t);
  }
  if (!files.length) { console.error('[缺] 没找到 .skel'); process.exit(2); }

  // ⚠️ 四个必须照着官方实现来的细节（都能在 spine-all.js 里查到，别凭印象写）：
  //  ① 传给 `readSkeletonData` 的必须是 **Uint8Array 视图**，不是裸 ArrayBuffer ——
  //     `BinaryInput` 写的是 `new DataView(data.buffer)`，传裸 buffer 会让
  //     `data.buffer` 为 undefined，报 "First argument to DataView constructor must be
  //     an ArrayBuffer"。且 ArrayBuffer/DataView **必须同 realm**（vm 内外不通用），
  //     所以整个读取都放在沙箱内闭包里做。
  //  ② 要拿到 x/y 就必须走完整个 `readSkeletonData`，而它需要**配套 atlas** 提供
  //     attachmentLoader。好在 `spine.TextureAtlas` / `spine.FakeTexture` / `spine.Color`
  //     都是导出符号，**不需要真贴图** ⇒ 传同名 .atlas 文本即可。
  //     `FakeTexture` 要的是**一个带 width/height 的对象**（官方 `loadTextureAtlas`
  //     里传的是 `document.createElement('img')` 并设 `image.width=16`），
  //     传空对象会报 "Cannot read properties of undefined (reading 'width')"。
  //     （本轮先试过"假 attachmentLoader"，一路炸在 slot.color / spine.Region 上，
  //       白费两轮 —— 有真 atlas 就别造假。`spine.Region`/`BinaryInput` 不是导出符号。）
  //  ③ 头字段顺序是 **hash → version → x → y → width → height → nonessential**；
  //     `fps/imagesPath/audioPath` **只在 nonessential==true 时才存在**，
  //     无条件去读会读到 bones 表的字节（表现为 fps=1.28e19）。本轮在这上面错过一次。
  //  ④ `readString` 的长度字段是「真实字节数 + 1」（0→null、1→空串），
  //     漏掉这个 +1/-1 会整体错位 1 字节，版本串读成 `.8.99`、后面每个 float 全错。
  //     这条现在由官方 runtime 兜住，不用自己实现 —— **别再凭印象手搓解析器**。
  const mkReader = vm.runInContext(
    `(function () {
       return function (skelBytes, atlasText) {
         const n = skelBytes.length;
         const ab = new ArrayBuffer(n);
         const view = new Uint8Array(ab);
         for (let i = 0; i < n; i++) view[i] = skelBytes[i];
         const atlas = new spine.TextureAtlas(atlasText, function () {
           // 照官方 loadTextureAtlas 的做法：给一个有 width/height 的对象
           return new spine.FakeTexture({ width: 16, height: 16 });
         });
         const sd = new spine.SkeletonBinary(
           new spine.AtlasAttachmentLoader(atlas)
         ).readSkeletonData(view);
         return {
           hash: sd.hash, version: sd.version, x: sd.x, y: sd.y,
           width: sd.width, height: sd.height,
           bones: sd.bones.length, slots: sd.slots.length,
           anims: (sd.animations || []).length,
         };
       };
     })()`,
    g
  );

  let bad = 0;
  console.log(`=== ${files.length} 个 skel（官方 spine-ts 读） ===`);
  console.log(
    '文件'.padEnd(28) + '版本'.padEnd(9) + 'skel.x'.padStart(10) + 'skel.y'.padStart(10) +
    'width'.padStart(9) + 'height'.padStart(9) + '  bones slots anims'
  );
  const rows = [];
  for (const f of files) {
    const ap = f.replace(/\.skel$/, '.atlas');
    if (!fs.existsSync(ap)) {
      bad++;
      console.error(`[红] ${path.basename(f)} 缺配套 atlas（SkeletonBinary 需要它做 attachmentLoader）`);
      continue;
    }
    try {
      const sd = mkReader(fs.readFileSync(f), fs.readFileSync(ap, 'utf8'));
      const r = Object.assign({ file: path.basename(f) }, sd);
      rows.push(r);
      const fmt = (v) => (Math.abs(v) < 1e7 ? v.toFixed(2) : v.toExponential(2));
      console.log(
        r.file.padEnd(28) + String(r.version).padEnd(9) +
        fmt(r.x).padStart(10) + fmt(r.y).padStart(10) +
        fmt(r.width).padStart(9) + fmt(r.height).padStart(9) +
        '  ' + String(r.bones).padStart(5) + String(r.slots).padStart(5) +
        String(r.anims).padStart(5)
      );
    } catch (e) {
      bad++;
      console.error(`[红] ${path.basename(f)} 解析失败: ${e.message}`);
    }
  }

  // 关键判据：各层 skeleton.x/y 若不同 ⇒ 前端必须**逐层**应用这组值，
  // 否则层与层会整体错开（本轮 `tianjinfeng_2` 的现象）。
  if (rows.length > 1) {
    console.log('');
    const nz = rows.filter((r) => r.x !== 0 || r.y !== 0);
    if (!nz.length) {
      console.log(`[绿] 全部 ${rows.length} 层 skeleton.x/y 都是 0 —— 各层共用同一原点，`
        + '错开的原因不在骨架偏移');
    } else {
      console.log(`[有非零骨架偏移] ${nz.length}/${rows.length} 层带原点偏移：`);
      for (const r of nz) {
        console.log(`     ${r.file.padEnd(28)} x=${r.x}  y=${r.y}`
          + '  <= 前端若没逐层应用，这就是错位来源');
      }
      const xs = new Set(rows.map((r) => r.x));
      const ys = new Set(rows.map((r) => r.y));
      console.log(`     （x 取值 ${[...xs].join('/')}；y 取值 ${[...ys].join('/')}）`);
    }
  }
  process.exit(bad ? 1 : 0);
}
main();
