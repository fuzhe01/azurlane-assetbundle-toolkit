// 全库"动画稳定性"扫描（只读）：每个皮肤的主层在动画全程里，可见附件数会不会骤降。
//
// 为什么：实测 `tianjinfeng_2` 的 `normal`（33.3s）在 t≈8s 之后角色主体**整块消失**
// （只剩腿/狐尾 + 光效），弹窗默认播 normal ⇒ 打开 8 秒后看着像"缺件"。
// 到底是这一个皮肤的特殊演出，还是普遍现象，决定修法方向。
//
// 判据（与"渲染可见性"对齐）：每时刻算该层**可见附件**（挂着附件 且 `slot.color.a>0.001`）
// 的世界框面积；稳定性看**面积序列**——
//   ⚠️ 只看"可见附件数"抓不住本病例：`tianjinfeng_2` 的 normal 里附件数只掉到 61%，
//   但**框面积**从 1535×1571 变成 30316×46333（爆炸）或 510×397（骤缩）——角色主体
//   要么被拉到极远、要么被压成一小团，观感就是"缺件"。所以判据必须落在面积上。
//
// 用法: node .diag/anim_stability_scan.js [--limit N] [--only a,b]
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const L = require('./spine_skel_lib.js');

const SPINE = path.join(L.ROOT, 'Output', 'Spine_v2');
const argv = process.argv.slice(2);
const arg = (k, d) => { const i = argv.indexOf(k); return i >= 0 ? argv[i + 1] : d; };
const LIMIT = parseInt(arg('--limit', '0'), 10) || 0;
const ONLY = (arg('--only', '') || '').split(',').map(s => s.trim()).filter(Boolean);

const { spine, ctx } = L.loadSpine();
const mk = vm.runInContext(`(function(){
  return function (bytes, atlasText, animName, samples) {
    const ab = new ArrayBuffer(bytes.length); const v = new Uint8Array(ab);
    for (let i = 0; i < bytes.length; i++) v[i] = bytes[i];
    const atlas = new spine.TextureAtlas(atlasText, function () {
      return new spine.FakeTexture({ width: 16, height: 16 }); });
    const data = new spine.SkeletonBinary(new spine.AtlasAttachmentLoader(atlas)).readSkeletonData(v);
    const a = (data.animations || []).filter(x => x.name === animName)[0];
    if (!a) return null;
    const skel = new spine.Skeleton(data);
    skel.setSlotsToSetupPose(); skel.setBonesToSetupPose();
    const st = new spine.AnimationState(new spine.AnimationStateData(data));
    st.setAnimation(0, animName, true);
    const out = []; const fine = 1 / 30;
    let acc = 0, next = 0; const step = a.duration / samples;
    while (acc <= a.duration + 1e-9) {
      if (acc + 1e-9 >= next) {
        next += step;
        let nvis = 0, x0 = 1e30, y0 = 1e30, x1 = -1e30, y1 = -1e30;
        for (const sl of skel.slots) {
          const at = sl.getAttachment();
          if (!at || !sl.bone || !sl.bone.active) continue;
          if (sl.color && sl.color.a <= 0.001) continue;
          nvis++;
          let vv, c;
          try {
            if (at instanceof spine.RegionAttachment) { vv = spine.Utils.newFloatArray(8); c = 8; at.computeWorldVertices(sl.bone, vv, 0, 2); }
            else if (at instanceof spine.MeshAttachment && at.worldVerticesLength) { c = at.worldVerticesLength; vv = spine.Utils.newFloatArray(c); at.computeWorldVertices(sl, 0, c, vv, 0, 2); }
            else continue;
          } catch (e) { continue; }
          for (let j = 0; j < c; j += 2) {
            if (vv[j] < x0) x0 = vv[j]; if (vv[j] > x1) x1 = vv[j];
            if (vv[j+1] < y0) y0 = vv[j+1]; if (vv[j+1] > y1) y1 = vv[j+1];
          }
        }
        const w = (x1 > x0) ? (x1 - x0) : 0, h = (y1 > y0) ? (y1 - y0) : 0;
        out.push({ t: +acc.toFixed(1), n: nvis, a: Math.round(w * h) });
      }
      st.update(fine); st.apply(skel); skel.updateWorldTransform();
      acc += fine;
    }
    return { dur: a.duration, samples: out };
  };
})()`, ctx);

const dirs = fs.readdirSync(SPINE).filter(d => {
  if (!fs.statSync(path.join(SPINE, d)).isDirectory()) return false;
  if (ONLY.length && ONLY.indexOf(d) < 0) return false;
  return fs.existsSync(path.join(SPINE, d, 'parts.json'));
}).sort();
const use = LIMIT ? dirs.slice(0, LIMIT) : dirs;

let flagged = 0, ok = 0, skipped = 0;
const rows = [];
for (const d of use) {
  const dir = path.join(SPINE, d);
  const parts = JSON.parse(fs.readFileSync(path.join(dir, 'parts.json'), 'utf8')).layers || [];
  // 主层 = setup 附件数最多的那层（用 skel_layers_report 的同一套读法，但只取附件数）
  let best = null;
  for (const p of parts) {
    const sk = path.join(dir, p.layer + '.skel'), at = path.join(dir, p.layer + '.atlas');
    if (!fs.existsSync(sk) || !fs.existsSync(at)) continue;
    try {
      const r = L.mkProbe(spine, ctx)(fs.readFileSync(sk), fs.readFileSync(at, 'utf8'),
        p.startingAnimation || 'normal', p.localScale);
      if (!best || r.withAttach > best.n) best = { layer: p.layer, n: r.withAttach, anim: p.startingAnimation || 'normal', sk, at };
    } catch (e) { }
  }
  if (!best || !best.n) { skipped++; continue; }
  let r = null;
  try { r = mk(fs.readFileSync(best.sk), fs.readFileSync(best.at, 'utf8'), best.anim, 40); } catch (e) { }
  if (!r) { skipped++; continue; }
  const as = r.samples.map(s => s.a).filter(a => a > 0).sort((x, y) => x - y);
  if (!as.length) { skipped++; continue; }
  const med = as[as.length >> 1];
  // 每时刻标记：面积 > 3×中位（爆炸）或 < 中位/3（骤缩）
  // ⚠️ 必须排除面积=0 的采样点（t=0 那一帧还没 apply 动画，所有层都是空的）——
  // 否则每个皮肤都会"首异常=0s"，把真正的问题起点盖掉。
  const badIdx = r.samples.map((s, i) => (s.a > 0 && (s.a > med * 3 || s.a < med / 3)) ? i : -1).filter(i => i >= 0);
  const badSpan = badIdx.length ? (r.samples[badIdx[badIdx.length - 1]].t - r.samples[badIdx[0]].t) : 0;
  const firstBad = badIdx.length ? r.samples[badIdx[0]].t : null;
  const badFrac = badIdx.length / Math.max(1, r.samples.length);
  const rec = { dir: d, layer: best.layer, anim: best.anim, dur: +r.dur.toFixed(1),
                med, ratio: +(as[0] / as[as.length - 1]).toFixed(2),
                firstBad, badSpan: +badSpan.toFixed(1), badFrac: +badFrac.toFixed(2) };
  const isBad = badFrac > 0.1 && badSpan > 2;
  rows.push(rec);
  if (isBad) flagged++; else ok++;
  console.log('%s %s anim=%s dur=%ss 框面积中位=%d 首异常=%ss 异常段=%ss 占比=%d%%',
    isBad ? '[旗]' : '[ok]', d.padEnd(26), String(rec.anim).padEnd(14),
    rec.dur, med, firstBad === null ? '-' : firstBad, badSpan, Math.round(badFrac * 100));
}
console.log('\n=== 汇总 ===');
console.log('扫描 %d 个目录：异常（框面积偏离中位 3 倍以上、占比>10%% 且持续>2s） %d 个，正常 %d 个，跳过 %d 个',
  use.length, flagged, ok, skipped);
const top = rows.filter(r => r.badFrac > 0.1 && r.badSpan > 2).sort((a, b) => b.badFrac - a.badFrac);
console.log('\n最严重的 15 个（按异常时长占比）：');
for (const r of top.slice(0, 15))
  console.log('  %s %s anim=%s 异常占比=%d%% 首异常=%ss 段长=%ss',
    r.dir.padEnd(26), r.layer.padEnd(20), String(r.anim).padEnd(12),
    Math.round(r.badFrac * 100), r.firstBad, r.badSpan);
