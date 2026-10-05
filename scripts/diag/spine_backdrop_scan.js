// 全库影响面扫描（只读，node 侧不开浏览器）：**哪些皮肤会被"背景巨幕层"剔除判据动到**。
//
// 为什么必须有这一步（2026-10-05）：
//   在这一轮之前，我已经因为"只在 tianjinfeng_2 一张图上改判据、没做影响面取证"
//   连改错三次（DARK 阈值 / RUN 纯色 / 时序），每次都靠用户截图才发现误伤。
//   判据一旦写进取景框，就会**同时**作用于全库 300+ 个 Spine 目录，
//   所以改完必须先把"会剔哪几层"全列出来人工过一遍，再谈部署。
//
// 判据与页面逐字一致（index.html `dropBackdropLayers` / cg_export.html 同名函数）：
//   ① 该层附件数 ≤ 8；② 该层包围盒面积 ≥ 4 × 其余层并集面积；两条 AND，剔完至少剩一层。
//
// 用法: node scripts/diag/spine_backdrop_scan.js [--limit N] [--only dir1,dir2]
//       node scripts/diag/spine_backdrop_scan.js --json > .diag/backdrop_scan.json
const fs = require('fs');
const path = require('path');
const L = require('./spine_skel_lib.js');

const SPINE = path.join(L.ROOT, 'Output', 'Spine_v2');
const argv = process.argv.slice(2);
const arg = (k, d) => { const i = argv.indexOf(k); return i >= 0 ? argv[i + 1] : d; };
const LIMIT = parseInt(arg('--limit', '0'), 10) || 0;
const ONLY = (arg('--only', '') || '').split(',').map(s => s.trim()).filter(Boolean);
const AS_JSON = argv.includes('--json');

/** 与页面逐字一致的判据（index.html `dropBackdropLayers`）；
 *  返回被剔的层名数组。per 元素形如 {name, list, box}，folder 为目录名。 */
function dropBackdropLayers(per, folder) {
  /* "本体"判据：层名===目录名；否则排除 _B/_B2 后缀后取附件最多的。
     ⚠️ 不能按 cov/附件数盲排——前景特效层（2T）的附件数往往比本体还多。 */
  const mainName = (() => {
    const n = per.find(g => g.name === folder);
    if (n) return n.name;
    const nb = per.filter(g => !/[Bb](\d*)$/.test(g.name || ''));
    return (nb.sort((a, b) => (b.list.length - a.list.length))[0] || per[0] || {}).name; })();
  const drop = [];
  for (const g of per) {
    if (g.name === mainName) continue;
    /* 前景特效层（T 后缀）：只渲染，不计取景（tianjinfeng_2 的 2T 把取景框高拉长 52%） */
    if (/[Tt](\d*)$/.test(g.name || '')) drop.push(g);
  }
  for (const g of per) {
    if (!g.box || g.list.length > 8) continue;               // ① 只有"薄层"才可能是背景板
    const others = per.filter(u => u !== g && u.box);
    if (!others.length) continue;                            // 全场只有它一层 → 不判
    const ob = L.unionBox(others.map(u => u.box));
    const ow = ob[2] - ob[0], oh = ob[3] - ob[1];
    if (!(ow > 0 && oh > 0)) continue;
    if (L.areaOf(g.box) >= 4 * ow * oh) drop.push(g);         // ② 面积 4 倍于其余层并集
  }
  if (!drop.length || per.length - drop.length < 1) return [];  // 会剔光 → 不动
  return drop;
}

function main() {
  const dirs = fs.readdirSync(SPINE).filter(d => {
    if (!fs.statSync(path.join(SPINE, d)).isDirectory()) return false;
    if (ONLY.length && ONLY.indexOf(d) < 0) return false;
    return fs.existsSync(path.join(SPINE, d, 'parts.json'));
  }).sort();
  const use = LIMIT ? dirs.slice(0, LIMIT) : dirs;

  const { spine, ctx } = L.loadSpine();
  const probe = L.mkProbe(spine, ctx);

  const hits = [];
  const pad = (s, n) => (s + ' '.repeat(Math.max(0, n - s.length)));
  for (const d of use) {
    const rows = L.layerBoxes(path.join(SPINE, d), '', probe);
    if (!rows) continue;
    const per = rows.map(r => ({ name: r.name, list: new Array(r.n || 0), box: r.box, err: r.err }));
    const drop = dropBackdropLayers(per, d);
    if (!drop.length) continue;
    const names = drop.map(g => g.name);
    const all = L.unionBox(rows.filter(r => r.box).map(r => r.box));
    const keep = L.unionBox(rows.filter(r => r.box && names.indexOf(r.name) < 0).map(r => r.box));
    const gain = (all && keep) ? Math.sqrt(L.areaOf(all) / L.areaOf(keep)) : 0;
    const rec = {
      dir: d, drop: names,
      dropN: drop.map(g => g.list.length),
      dropBox: drop.map(g => g.box && g.box.map(x => Math.round(x))),
      layers: rows.length,
      allBox: all && all.map(x => Math.round(x)), keepBox: keep && keep.map(x => Math.round(x)),
      gain: +gain.toFixed(2),
    };
    hits.push(rec);   // 注意：node 的 console.log **不支持 %-26s 这种左对齐宽度**，用 padEnd
    if (!AS_JSON) {
      console.log('%s 层%d · 剔 %s（附件 %s）· gain %sx'
        , pad(d, 26).slice(0, 26), rows.length, names.join('+'), rec.dropN.join('/'), rec.gain);
    }
  }

  if (AS_JSON) { console.log(JSON.stringify({ scanned: use.length, hits }, null, 1)); return; }

  console.log('\n=== 汇总 ===');
  console.log('扫描目录 ' + use.length + ' 个；**有层被剔** ' + hits.length + ' 个（占 '
    + (100 * hits.length / Math.max(1, use.length)).toFixed(1) + '%）');
  console.log('\n放大倍数 Top10（gain = 去掉被剔层后取景能放大的倍数）：');
  for (const h of hits.slice().sort((a, b) => b.gain - a.gain).slice(0, 10))
    console.log('  ' + pad(h.dir, 26) + ' gain ' + String(h.gain).padStart(5) + 'x  剔 ' + h.drop.join('+'));
  const big = hits.filter(h => h.gain > 1.3).sort((a, b) => b.gain - a.gain);
  console.log('\n⚠️ gain>1.3（画面会明显变化）的目录 ' + big.length + ' 个，逐个核对：');
  for (const h of big)
    console.log('  ' + pad(h.dir, 26) + ' gain ' + String(h.gain).padStart(5) + 'x  剔 ' + h.drop.join('+'));
}
main();
