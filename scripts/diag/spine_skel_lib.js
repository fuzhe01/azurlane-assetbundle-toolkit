// 读 `.skel` 的公共库（node 侧，不开浏览器）：给「逐层报告」和「全库影响面扫描」共用。
//
// ⚠️ 必须复用前端 vendored 的官方 spine-all.js，**不要手搓 .skel 解析**：
//    readString 长度是「真实字节数+1」；fps/imagesPath/audioPath 只在
//    nonessential==true 时存在；读 x/y 必须走完整个 readSkeletonData（需配套 atlas）。
//
// 用法:
//   const L = require('./spine_skel_lib.js');
//   const {spine, ctx} = L.loadSpine();
//   const probe = L.mkProbe(spine, ctx);
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = path.resolve(__dirname, '..', '..');
const VENDOR = path.join(ROOT, 'Output', 'gallery_v2', 'vendor', 'spine', 'spine-all.js');

function loadSpine() {
  const src = fs.readFileSync(VENDOR, 'utf8');
  const stub = new Proxy(function () {}, {
    get: (t, k) => (k === 'prototype' ? {} : stub),
    apply: () => stub,
    construct: () => ({}),
  });
  const g = { THREE: stub };
  g.window = g; g.self = g;
  g.document = { createElement: () => ({ getContext: () => stub, style: {} }) };
  g.navigator = { userAgent: 'node' };
  g.window.document = g.document;
  vm.createContext(g);
  vm.runInContext(src, g, { filename: 'spine-all.js' });
  return { spine: g.spine, ctx: g };
}

/** 在沙箱内跑：读一层 → apply 起始动画 → 统计附件与世界框 */
function mkProbe(spine, ctx) {
  return vm.runInContext(`(function(){
    return function (skelBytes, atlasText, want, localScale) {
      const n = skelBytes.length;
      const ab = new ArrayBuffer(n);
      const view = new Uint8Array(ab);
      for (let i = 0; i < n; i++) view[i] = skelBytes[i];
      const atlas = new spine.TextureAtlas(atlasText, function () {
        return new spine.FakeTexture({ width: 16, height: 16 });
      });
      const data = new spine.SkeletonBinary(
        new spine.AtlasAttachmentLoader(atlas)).readSkeletonData(view);
      const skel = new spine.Skeleton(data);
      const st = new spine.AnimationState(new spine.AnimationStateData(data));
      const an = (data.animations || []).map(a => a && a.name).filter(Boolean);
      const pick = an.indexOf(want) >= 0 ? want
        : (an.indexOf('normal') >= 0 ? 'normal' : an[0]);
      if (pick) { st.setAnimation(0, pick, true); st.update(0); st.apply(skel); }
      if (localScale) { skel.scaleX = localScale[0] || 1; skel.scaleY = localScale[1] || 1; }
      skel.updateWorldTransform();

      let withAttach = 0, verts = 0;
      let x0 = 1e30, y0 = 1e30, x1 = -1e30, y1 = -1e30;
      const byType = {};
      for (const sl of skel.slots) {
        const a = sl.getAttachment();
        if (!a || !sl.bone || !sl.bone.active) continue;
        withAttach++;
        const t = a.constructor && a.constructor.name || 'unknown';
        byType[t] = (byType[t] || 0) + 1;
        let v, c;
        try {
          if (a instanceof spine.RegionAttachment) {
            v = spine.Utils.newFloatArray(8); c = 8; a.computeWorldVertices(sl.bone, v, 0, 2);
          } else if (a instanceof spine.MeshAttachment && a.worldVerticesLength) {
            c = a.worldVerticesLength; v = spine.Utils.newFloatArray(c);
            a.computeWorldVertices(sl, 0, c, v, 0, 2);
          } else continue;
        } catch (e) { continue; }
        verts += c / 2;
        for (let j = 0; j < c; j += 2) {
          if (v[j] < x0) x0 = v[j];
          if (v[j] > x1) x1 = v[j];
          if (v[j+1] < y0) y0 = v[j+1];
          if (v[j+1] > y1) y1 = v[j+1];
        }
      }
      return {
        anim: pick || null,
        slots: skel.slots.length, bones: skel.bones.length,
        withAttach, verts, byType,
        box: (x1 > x0) ? [x0, y0, x1, y1] : null,
      };
    };
  })()`, ctx);
}

/** 方向一致的并集框（世界坐标） */
function unionBox(list) {
  if (!list.length) return null;
  const r = [1e9, 1e9, -1e9, -1e9];
  for (const b of list) {
    if (b[0] < r[0]) r[0] = b[0]; if (b[1] < r[1]) r[1] = b[1];
    if (b[2] > r[2]) r[2] = b[2]; if (b[3] > r[3]) r[3] = b[3];
  }
  return r;
}
const areaOf = b => (b ? Math.max(0, b[2] - b[0]) * Math.max(0, b[3] - b[1]) : 0);

/** 跑一个 Spine_v2 目录，返回每层的 {name, n, box}（n=有附件的槽位数） */
function layerBoxes(dir, animArg, probe) {
  const partsPath = path.join(dir, 'parts.json');
  if (!fs.existsSync(partsPath)) return null;
  const parts = JSON.parse(fs.readFileSync(partsPath, 'utf8')).layers || [];
  const out = [];
  for (const p of parts) {
    const sk = path.join(dir, p.layer + '.skel');
    const at = path.join(dir, p.layer + '.atlas');
    if (!fs.existsSync(sk) || !fs.existsSync(at)) { out.push({ name: p.layer, err: '缺 skel/atlas' }); continue; }
    try {
      const r = probe(fs.readFileSync(sk), fs.readFileSync(at, 'utf8'),
        animArg || p.startingAnimation || 'normal', p.localScale);
      out.push({ name: p.layer, n: r.withAttach, verts: r.verts, box: r.box, anim: r.anim });
    } catch (e) {
      out.push({ name: p.layer, err: String(e && e.message || e) });
    }
  }
  return out;
}

module.exports = { ROOT, VENDOR, loadSpine, mkProbe, unionBox, areaOf, layerBoxes };
