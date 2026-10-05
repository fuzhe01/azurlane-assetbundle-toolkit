// 逐层扫描动画整条时间轴：各层的世界框中心/尺寸随时间怎么变（诊断用，可删）
//
// 为什么需要：用户报「normal 下房间和角色分开、touch_body 正常」。`skel_layers_report.js`
// 只量动画第 0 帧（两者逐字相同），浏览器探针只截到 18s，而 normal 长 33.333s ——
// 必须**沿整条时间轴**采样才知道是不是某段运镜把房间拉远了。
//
// 用法: node .diag/anim_timeline.js <Spine_v2 目录> <动画名> [步长秒]
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const L = require('./spine_skel_lib.js');

const dir = process.argv[2];
const anim = process.argv[3] || 'normal';
const step = parseFloat(process.argv[4] || '2');

const { spine, ctx } = L.loadSpine();
const mk = vm.runInContext(`(function(){
  return function (bytes, atlasText, animName, step) {
    const ab = new ArrayBuffer(bytes.length); const v = new Uint8Array(ab);
    for (let i = 0; i < bytes.length; i++) v[i] = bytes[i];
    const atlas = new spine.TextureAtlas(atlasText, function () {
      return new spine.FakeTexture({ width: 16, height: 16 }); });
    const data = new spine.SkeletonBinary(new spine.AtlasAttachmentLoader(atlas)).readSkeletonData(v);
    const a = (data.animations || []).filter(x => x.name === animName)[0];
    if (!a) return null;
    const skel = new spine.Skeleton(data);
    /* ⚠️ 必须先 setToSetupPose：new Skeleton(data) 只把 length==0 的骨骼按 setup 初始化，
       其余骨骼停在"未初始化"状态，随后 apply 动画只驱动**动画里有时间线的**骨骼 ⇒
       没被驱动的骨骼带着 0/未定义变换参与 worldTransform ⇒ 顶点乱飞（实测 2T 层被
       虚报成 29780×15185，实际 1117×2311）。页面里 loadPart 是做了这一步的，脚本漏了。 */
    skel.setSlotsToSetupPose(); skel.setBonesToSetupPose();
    const st = new spine.AnimationState(new spine.AnimationStateData(data));
    st.setAnimation(0, animName, true);
    const out = [];
    /* ⚠️ 必须**小步长**推进（1/60 s），不能几步大跳：AnimationState.update(2.0) 一步 2 秒
       会让带"最短路径旋转/曲线"的时间线跨过若干关键帧，实测得到与逐帧播放**完全不同**
       的顶点（2T 层被算成 29780×15185，而页面里逐帧播到同一秒是 1117×2311）。
       页面帧循环是 ~16ms 一步 —— 采样必须复刻它的步长才叫"量的是用户看到的东西"。 */
    const fine = 1 / 60;
    let acc = 0, next = 0;
    while (acc <= a.duration + 1e-9) {
      if (acc + 1e-9 >= next) {
        next += step;
        let x0 = 1e30, y0 = 1e30, x1 = -1e30, y1 = -1e30;
        for (const sl of skel.slots) {
          const at = sl.getAttachment();
          if (!at || !sl.bone || !sl.bone.active) continue;
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
        let n = 0;
        for (const sl of skel.slots) if (sl.getAttachment()) n++;
        out.push({ t: +acc.toFixed(2), n: n, box: (x1 > x0) ? [x0, y0, x1, y1] : null });
      }
      st.update(fine); st.apply(skel); skel.updateWorldTransform();
      acc += fine;
    }
    return { dur: a.duration, samples: out };
  };
})()`, ctx);

const parts = JSON.parse(fs.readFileSync(path.join(dir, 'parts.json'), 'utf8')).layers || [];
const res = {};
for (const p of parts) {
  const sk = path.join(dir, p.layer + '.skel'), at = path.join(dir, p.layer + '.atlas');
  if (!fs.existsSync(sk)) continue;
  const r = mk(fs.readFileSync(sk), fs.readFileSync(at, 'utf8'), anim, step);
  if (r) res[p.layer] = r;
}
const names = Object.keys(res);
if (!names.length) { console.log('该动画不存在'); process.exit(1); }
console.log('目录 %s · 动画 %s · 时长 %ss · 步长 %ss', path.basename(dir), anim,
  res[names[0]].dur.toFixed(2), step);
const cen = b => (b ? [(b[0]+b[2])/2, (b[1]+b[3])/2] : null);
const sz = b => (b ? [Math.round(b[2]-b[0]), Math.round(b[3]-b[1])] : null);
// 以"除背景层外所有层的并集"为角色基准（这里直接列全部层，人工看）
const hdr = ['t'].concat(names.map(n => n.length > 14 ? n.slice(-14) : n));
console.log(hdr.map((h, i) => i ? h.padEnd(20) : h.padEnd(6)).join(''));
const n0 = res[names[0]].samples.length;
for (let i = 0; i < n0; i++) {
  const row = [String(res[names[0]].samples[i].t).padEnd(6)];
  for (const n of names) {
    const b = res[n].samples[i] && res[n].samples[i].box;
    const c = cen(b), s = sz(b), nn = res[n].samples[i] ? res[n].samples[i].n : 0;
    row.push((c ? (Math.round(c[0]) + ',' + Math.round(c[1]) + ' ' + s[0] + 'x' + s[1] + ' n' + nn) : '(空)').padEnd(24));
  }
  console.log(row.join(''));
}
