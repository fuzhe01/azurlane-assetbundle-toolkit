// 量 Spine 多层：**每层附件数 + 顶点数 + 世界包围盒**（不开浏览器，纯数据）
//
// 为什么要有这个工具（2026-10-05 的教训）：
// 这一轮我靠「弹窗截图看起来缺件」连改三次取景判据，三次都改错 —— 因为**截图只能告诉我
// 「看起来不对」，告诉不了我「哪一层出了问题」**。真正能定案的数据是逐层的：
//   附件数（有没有东西）、世界包围盒（画在哪、多大）。
// 有了这两个数，「缺件」立刻分成三种完全不同的病：
//   ① 某层 withAttach=0        → 附件没挂上（skin / 时序问题）
//   ② 各层 worldBox 互不重叠  → 坐标系不同源（取景问题）
//   ③ 各层 worldBox 重叠但仍缺 → 是像素级二次构图把内容裁掉了
//
// ⚠️ 2026-10-05 补：**用这个数还判断不出「某层画的是什么」**。那一轮我拿着 2B2 的
//   7000×7007 世界框就断言「画面里那个菱形就是 2B2」，结果取景已经剔除 2B2、屏幕上菱形
//   照样铺满 —— 因为 2B2 的**贴图本身**就是一块大画布，菱形只是它中间的不透明部分，
//   顶点框 7000 远大于可见内容 3884。
//   ⇒ 「谁画了画面上这块东西」只有一个可靠答案：**逐层隔离截图**，
//     `py -3 scripts/diag/spine_layer_isolate.py <中文名> <key>`。先看它，再谈取景。
//
// 依赖：`spine_skel_lib.js`（读 .skel 的公共库，与 `spine_backdrop_scan.js` 共用）。
//
// 用法: node scripts/diag/skel_layers_report.js Output/Spine_v2/tianjinfeng_2 [动画名]
const fs = require('fs');
const path = require('path');
const L = require('./spine_skel_lib.js');

function main() {
  const dir = process.argv[2];
  if (!dir) { console.error('用法: node skel_layers_report.js <Spine_v2 目录> [动画名]'); process.exit(2); }
  const animArg = process.argv[3] || '';
  const partsPath = path.join(dir, 'parts.json');
  if (!fs.existsSync(partsPath)) { console.error('[缺] %s', partsPath); process.exit(2); }
  const parts = JSON.parse(fs.readFileSync(partsPath, 'utf8')).layers || [];

  const { spine, ctx } = L.loadSpine();
  if (!spine || !spine.SkeletonBinary) { console.error('[红] 没拿到官方 runtime'); process.exit(2); }
  const probe = L.mkProbe(spine, ctx);

  const rows = [];
  for (const p of parts) {
    const sk = path.join(dir, p.layer + '.skel');
    const at = path.join(dir, p.layer + '.atlas');
    if (!fs.existsSync(sk) || !fs.existsSync(at)) {
      rows.push({ layer: p.layer, err: '缺 skel/atlas' }); continue;
    }
    try {
      const r = probe(fs.readFileSync(sk), fs.readFileSync(at, 'utf8'),
        animArg || p.startingAnimation || 'normal', p.localScale);
      rows.push(Object.assign({ layer: p.layer }, r));
    } catch (e) {
      rows.push({ layer: p.layer, err: String(e && e.message || e) });
    }
  }

  // node 的 console.log 不支持 %-22s 这类左对齐宽度，统一手写 padEnd
  const pad = (s, n) => (String(s).length >= n ? String(s) : String(s) + ' '.repeat(n - String(s).length));
  console.log('=== ' + path.basename(dir) + ' 逐层（动画 ' + (animArg || '各层 startingAnimation') + '）===');
  console.log(pad('层', 22) + pad('动画', 9) + '槽位'.padStart(5) + '骨骼'.padStart(5)
    + '附件'.padStart(6) + '顶点数'.padStart(7) + '  世界框 [x0,y0,x1,y1] / 尺寸');
  for (const r of rows) {
    if (r.err) { console.log(pad(r.layer, 22) + '[红] ' + r.err); continue; }
    const b = r.box;
    const dim = b ? (Math.round(b[2] - b[0]) + 'x' + Math.round(b[3] - b[1])) : '-';
    console.log(pad(r.layer, 22) + pad(r.anim, 9) + String(r.slots).padStart(5)
      + String(r.bones).padStart(5) + String(r.withAttach).padStart(6)
      + String(r.verts).padStart(7) + '  ' + (b ? '[' + b.map(x => Math.round(x)).join(',') + ']' : '(空)')
      + ' ' + dim);
  }

  // ---- 定案判据 ----
  console.log('\n=== 定案 ===');
  const empty = rows.filter(r => !r.err && r.withAttach === 0);
  if (empty.length) {
    console.log('[红] ' + empty.length + ' 层附件数为 0 ⇒ 那几层**根本没画东西**（skin/时序问题，与取景无关）：'
      + empty.map(r => r.layer).join('、'));
  }
  const boxes = rows.filter(r => r.box);
  if (boxes.length > 1) {
    const all = L.unionBox(boxes.map(r => r.box));
    console.log('并集框: [' + all.map(Math.round).join(',') + '] = '
      + Math.round(all[2] - all[0]) + 'x' + Math.round(all[3] - all[1]));
    // 与页面同判据的"背景巨幕"名单，直接在这里给出结论，省得再跑一遍扫描脚本
    const per = rows.map(r => ({ name: r.layer, list: new Array(r.withAttach || 0), box: r.box }));
    const drop = [];
    for (const g of per) {
      if (!g.box || g.list.length > 8) continue;
      const others = per.filter(u => u !== g && u.box);
      if (!others.length) continue;
      const ob = L.unionBox(others.map(u => u.box));
      if (L.areaOf(g.box) >= 4 * (ob[2] - ob[0]) * (ob[3] - ob[1])) drop.push(g);
    }
    if (drop.length && per.length - drop.length >= 1) {
      console.log('[取景] 会被当"背景巨幕层"剔除（附件≤8 且面积≥其余并集 4 倍）：'
        + drop.map(g => g.name).join('、'));
    } else {
      console.log('[取景] 没有层命中"背景巨幕"判据 ⇒ 取景框保持全部层的并集。');
    }
    console.log('\n每层与「其余层并集」的交叠（部位层应大幅重叠）：');
    for (const v of boxes) {
      const ob = L.unionBox(boxes.filter(u => u !== v).map(u => u.box));
      const iw = Math.min(v.box[2], ob[2]) - Math.max(v.box[0], ob[0]);
      const ih = Math.min(v.box[3], ob[3]) - Math.max(v.box[1], ob[1]);
      const inter = iw > 0 && ih > 0 ? iw * ih : 0;
      const r = inter / (L.areaOf(v.box) || 1);
      console.log('  ' + pad(v.layer, 22) + (r * 100).toFixed(1) + '%'
        + (r < 0.02 ? '   ★ 几乎不重叠（被摆在画外）' : ''));
    }
  }
  process.exit(empty.length ? 1 : 0);
}
main();
