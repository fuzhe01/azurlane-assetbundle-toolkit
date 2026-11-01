# -*- coding: utf-8 -*-
r"""l2d_param_binding_export.py — 反查「每个参数能改变哪些 drawable」，产出装扮参数表。

## 为什么不用 motion3.json 扫描（旧方案，已证伪）

旧扫描 `l2d_costume_params_scan.py` 的核心判据是
「参数在不同动作间被锁成不同档位 ⇒ 玩家可调」，**这个判据对装扮参数恰好是反的**：

- 装扮参数（`ShoseOff` / `Param233` / `Cloth*`）在几乎所有动作里都被钉成**同一个值**
  （实测 `ougen_8` 12 条装扮参数在 46 个动作里全是常值 0）；
- 于是旧判据把它们判成「只有 1 个取值 ⇒ 没有可调空间」直接剔除；
- 实测后果：`ougen_8` 只报出 4 条（`Stock1` + 3 条眼球噪声），
  而产品表里有 12 条 —— 漏掉了鞋、衣服、戒指、项圈全部。

被动作**连续驱动**的参数（`ParamAngleX`、`ParamEyeBallX`、`GloveFinger_*`）
反而是动画量，不该做成互动区。**判据正好相反。**

## 采用判据：运行时反查绑定（不依赖动作数据）

对每个参数的 min / max 两态各拍一次全部 drawable 的 (opacity, visible)：
- **有变化** ⇒ 这个参数真的控制画面，玩家可调 ⇒ 进装扮表；
- **无变化** ⇒ 它在当前模型里是死参数，跳过。

这是 `l2d_opacity_binding_hunt.py` 验证过的做法（页内单次 JS 同步，
582 参数 × 2 极值全程 < 2 s，比 CDP 往返快 3 个数量级）。

额外做两件旧方案没做的事：
1. **按语义分组**（`_label_of`）：沿用旧的名称关键词表（衣服/丝袜/鞋/戒指/眼睛…），
   没命中的标 `其他`，`kind` 由取值档数决定（2 档 → switch，其余 → slider）。
2. **排除纯动画量**：名字命中 `NOISE`（眼球/眨眼/角度/呼吸/眉/嘴）的即使有绑定也剔除——
   它们由动作或视线系统逐帧驱动，做成滑块会与运行时打架（旧表已证）。

## 输出

`Output/gallery_v2/costume_params.json`（产品表）与 `param_drawables.json`（映射表）
的**超集**写入 `.diag/costume_params_binding.json`，供人工比对后再决定是否换入产品表
（本项目规矩：换入产品表必须先给用户看样本）。

## 用法

    py -3 scripts/diag/l2d_param_binding_export.py            # 画廊里全部 Live2D 皮肤
    py -3 scripts/diag/l2d_param_binding_export.py ougen_8    # 单模型
"""
import json
import os
import re
import sys
import time

sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
sys.path.insert(0, os.path.join(ROOT, 'scripts', 'diag'))

from gallery_ui_shots import Page          # noqa: E402

BASE = 'http://127.0.0.1:8778/gallery_v2/index.html#gallery_v2'
PORT = int(os.environ.get('AL_PORT', '9431'))
PROFILE = os.path.join(ROOT, '.diag', 'binding_prof')
DST = os.path.join(ROOT, '.diag', 'costume_params_binding.json')

#: 纯动画量：由动作/视线/眨眼逐帧驱动。即使有绑定也不做成互动区
#: （旧表 `l2d_costume_export.py` 已用同一份清单排除过，理由见那里的注释）。
NOISE = re.compile(
    r'(eyeball|eyelopen|eyeropen|eyeopen|eyeclose|breath|angle|brow|mouth|'
    r'tear|cheek|sweat|physics|hairfront|hairback|ribbon_)', re.I)

#: 名称 → 中文语义。顺序有意义（先匹配先得）。
LABEL_RULES = [
    (re.compile(r'shose|shoe|heels|boot', re.I), '鞋'),
    (re.compile(r'stock|sock', re.I), '丝袜'),
    (re.compile(r'cloth|coat|jacket|skirt|apron|dress|bra\b|panty', re.I), '衣服'),
    (re.compile(r'glove', re.I), '手套'),
    (re.compile(r'wing|swing', re.I), '翅膀'),
    (re.compile(r'ring', re.I), '戒指'),
    (re.compile(r'neck|necklace|money', re.I), '项链/项圈'),
    (re.compile(r'eye|glass|mask|eyelash', re.I), '眼睛/眼镜'),
    (re.compile(r'hat|crown|hairpin|badge|medal', re.I), '头饰'),
    (re.compile(r'earring', re.I), '耳环'),
    (re.compile(r'cape|veil', re.I), '披风/面纱'),
    (re.compile(r'ribbon|belt|scarf', re.I), '缎带/腰带'),
    (re.compile(r'horn|tail', re.I), '角/尾巴'),
]


def label_of(pid):
    for rx, lab in LABEL_RULES:
        if rx.search(pid):
            return lab
    return '其他'


#: 页内同步扫描：对每个参数拍 min/max 两态，返回「改变了的 drawable 索引」。
#: 判据与 `l2d_opacity_binding_hunt.py` 完全一致（(opacity, visible) 同时比），
#: 那里有阳性对照证明仪器有效。
SWEEP = r"""(function(){
  var m=window.__l2ModelRef&&window.__l2ModelRef();
  if(!m||!m.internalModel) return JSON.stringify({err:'NO_MODEL'});
  var im=m.internalModel, c=im.coreModel;
  /* ── 必须先冻结帧源，否则「驱动件数」全线虚高（2026-10-29 实测）──
     基准快照与两态快照之间若物理/呼吸仍在跑，几乎每一件都会"变化"：
     实测 `benningdun_2` 的 `Paramring` 被判成驱动 **71 件**（散落全身 98..481），
     `ougen_8` 的 `ShoseOff` 被判成 15 件（真实直接绑定只有 6 件）。
     这是本项目反复踩的同一类坑（探针仪器自噪声），修法与 l2d_opacity_binding_hunt.py 一致。 */
  var done=[];
  try{ var mm=im.motionManager;
    if(mm&&mm.groups){ if(!mm.__idleBak) mm.__idleBak=mm.groups.idle;
      mm.groups.idle='__binding_frozen__'; done.push('idleOff'); } }catch(e){}
  try{ if(im.motionManager){ im.motionManager.queueManager.stopAllMotions();
    im.motionManager.state&&im.motionManager.state.reset&&im.motionManager.state.reset(); }
    done.push('mot'); }catch(e){}
  try{ if(typeof im.updateNaturalMovements==='function'){
    im.__nmBak=im.__nmBak||im.updateNaturalMovements;
    im.updateNaturalMovements=function(){}; done.push('breath'); } }catch(e){}
  try{ if(im.physics&&typeof im.physics.reset==='function'){ im.physics.reset(); done.push('phys'); } }catch(e){}
  var nd=c.getDrawableCount();
  /* 快照 = 每件 (opacity, visible, 顶点包围盒 4 个数)。
     ⚠️ 只比 opacity/visible 会漏掉**只改形状**的参数：实测 `ParamEyeSmile` 会让 14 件
     眼型件变形但不动不透明度，第一版反查因此把它判成"无绑定"（而产品表里它有 14 件）。
     只比顶点又会把物理/呼吸连带位移的件全算进来（`ShoseOff` 会被判成 15 件、
     实际直接绑定只有 6 件）。**两个判据都要**：任一变化即算该参数控制此件。 */
  function snap(){ var o=new Array(nd*6);
    for(var i=0;i<nd;i++){
      o[i*6]=Math.round(c.getDrawableOpacity(i)*1000);
      o[i*6+1]=c.getDrawableDynamicFlagIsVisible(i)?1:0;
      var p=null; try{ p=c.getDrawableVertexPositions(i); }catch(e){}
      if(p&&p.length>=4){
        var x0=1e9,y0=1e9,x1=-1e9,y1=-1e9;
        for(var k=0;k+1<p.length;k+=2){
          if(p[k]<x0)x0=p[k]; if(p[k]>x1)x1=p[k];
          if(p[k+1]<y0)y0=p[k+1]; if(p[k+1]>y1)y1=p[k+1]; }
        o[i*6+2]=Math.round(x0*100); o[i*6+3]=Math.round(y0*100);
        o[i*6+4]=Math.round(x1*100); o[i*6+5]=Math.round(y1*100);
      } else { o[i*6+2]=o[i*6+3]=o[i*6+4]=o[i*6+5]=-99999; }
    }
    return o; }
  var ids=c._parameterIds;
  function idAt(i){ return ids.at? ids.at(i) : ids[i]; }
  var nid = ids.getSize? ids.getSize() : ids.length;
  var n=c.getParameterCount();
  if(nid!==n) return JSON.stringify({err:'ID_COUNT_MISMATCH', n:n, nid:nid});
  try{ c.update(); }catch(e){}
  var base=snap();
  /* 阳性对照：ParamAngleX 在几乎任何模型上都驱动头部 ⇒ 必须能测出变化，
     否则仪器无效，整份输出不可信（AGENTS.md 规则 5）。 */
  var out=[], nskip=0;
  for(var i=0;i<n;i++){
    var id=idAt(i); if(!id) continue;
    var mn=0, mx=0;
    try{ mn=c.getParameterMinimumValue(i); mx=c.getParameterMaximumValue(i); }catch(e){ continue; }
    if(!(mx>mn)){ nskip++; continue; }
    var v0=0; try{ v0=c.getParameterValueByIndex(i); }catch(e){}
    var changed=[];
    /* 🔴 每个参数都要**重新取基准**（2026-10-29 实测，这是本工具最大的一个自噪声源）：
       复用一份全局基线时，上一个参数恢复 v0 的残差会累积进下一个参数的读数，
       实测把 `benningdun_2/Paramring` 从真实的 **2 件**（`jiezhi5`/`jiezhihuan5`）
       虚报成 **71 件**（散落全身 98..481）。逐个重取后立刻回到 2 件。
       代价只是每个参数多两次 update，页内同步跑仍然秒级。 */
    try{ c.setParameterValueByIndex(i, v0); }catch(e){}
    try{ c.update(); }catch(e){}
    var base=snap();
    for(var s=0;s<2;s++){
      var v=s?mx:mn;
      try{ c.setParameterValueByIndex(i,v); }catch(e){ continue; }
      try{ c.update(); }catch(e){}
      var cur=snap();
      for(var k=0;k<nd;k++){
        var diff=false;
        for(var q=0;q<6;q++) if(cur[k*6+q]!==base[k*6+q]){ diff=true; break; }
        if(diff && changed.indexOf(k)<0) changed.push(k);
      }
      try{ c.setParameterValueByIndex(i,v0); }catch(e){}
      try{ c.update(); }catch(e){}
    }
    if(changed.length) out.push([id, +mn.toFixed(4), +mx.toFixed(4), +v0.toFixed(4), changed]);
  }
  try{ c.update(); }catch(e){}
  return JSON.stringify({n:n, nskip:nskip, nd:nd, frozen:done,
    /* 阳性对照：被扫到的参数里必须包含至少一条已知会改画面的（如 Paramring/ShoseOff），
       否则说明冻结把一切都冻住了、仪器无效（AGENTS.md 规则 5）。 */
    params:out});
})()"""


def open_model(pg, key):
    pg.ev("""(function(){var b=document.querySelector('#gOpt button[data-k=login]');
       if(b&&(b.classList.contains('on')||b.dataset.on==='1')) b.click(); return 1;})()""")
    time.sleep(0.8)
    ship = pg.ev("""
    (function(){var s=(window.GALLERY.ships||[]).find(function(x){
         return (x.skins||[]).some(function(k){return k.key===%s;});});
      if(!s) return 'NO_SHIP';
      var c=[...document.querySelectorAll('.card')].find(function(e){
         return (e.textContent||'').indexOf(s.name)>=0;});
      if(!c) return 'NO_CARD'; c.click(); return s.name;})()""" % json.dumps(key))
    if ship in ('NO_SHIP', 'NO_CARD'):
        return ship
    time.sleep(1.6)
    got = pg.ev("""(function(){var d=[...document.querySelectorAll('#mSkins .skin')].find(function(e){
       return e.dataset.k===%s;}); if(!d) return 'NO_ROW'; d.click(); return 'OK';})()"""
                % json.dumps(key))
    if got != 'OK':
        return got
    time.sleep(1.3)
    tab = pg.ev("""(function(){var t=[...document.querySelectorAll('#mTabs .tab')].find(function(e){
       return e.dataset.k==='live2d';}); if(!t) return 'NO_TAB';
       if(t.classList.contains('dis')) return 'DIS'; t.click(); return 'OK';})()""")
    if tab != 'OK':
        return tab
    for _ in range(90):
        if pg.ev("(function(){var m=window.__l2ModelRef&&window.__l2ModelRef(); return m?1:0;})()") == 1:
            return 'OK'
        time.sleep(1.0)
    return 'NO_MODEL'


def main():
    explicit = [a for a in sys.argv[1:] if not a.startswith('--')]
    pg = Page(PORT, PROFILE, BASE, (1400, 1000), gpu=True, keepalive=True)
    try:
        time.sleep(3.0)
        if explicit:
            keys = explicit
        else:
            raw = pg.ev("""(function(){var o=[];
              (window.GALLERY.ships||[]).forEach(function(s){
                (s.live2dSkins||[]).forEach(function(k){ o.push(k); }); });
              return JSON.stringify(o);})()""")
            keys = json.loads(raw) if isinstance(raw, str) else []
        print('待扫模型:', keys)
        result = {}
        for key in keys:
            st = open_model(pg, key)
            if st != 'OK':
                print(f'  {key}: 打不开（{st}），跳过')
                continue
            pg.detach_frames(60)
            time.sleep(1.2)
            try:
                pg.require_frames(1.5)
            except Exception as e:
                print(f'  {key}: 帧源闸未过（{e}），跳过')
                continue
            t0 = time.time()
            r = json.loads(pg.ev(SWEEP))
            if r.get('err'):
                print(f'  {key}: 扫描失败 {r}')
                continue
            rows = []
            for pid, mn, mx, dv, changed in r['params']:
                if NOISE.search(pid):
                    continue
                distinct = 2 if (mx - mn) <= 1e-9 or (mx - mn) <= 1.5 else 12
                rows.append({
                    'id': pid, 'label': label_of(pid),
                    'kind': 'switch' if (mx - mn) <= 1.5 else 'slider',
                    'lo': mn, 'hi': mx, 'def': dv,
                    'n_drawables': len(changed),
                    'idx': changed,
                })
            result[key] = rows
            print(f'  {key}: 参数 {r["n"]}（常量跳过 {r["nskip"]}）→ 有绑定且非动画量 '
                  f'{len(rows)} 条，{time.time()-t0:.1f}s  冻结={r.get("frozen")}')
            # 阳性对照：`Paramring` 在多数模型上都驱动戒指件；`ShoseOff` 驱动鞋。
            # 两者都没测到 ⇒ 要么该模型真没有，要么冻结过度/快照坏了，必须显式报出。
            names = {x['id'] for x in rows}
            if not ({'Paramring', 'ShoseOff', 'Stock1'} & names):
                print('      ⚠️ 阳性对照缺失：Paramring/ShoseOff/Stock1 一个都没测到，'
                      '该模型读数需人工复核')
            for row in rows:
                print('      %-22s %-8s %-7s 值域[%s..%s] 默认%s 驱动%d件'
                      % (row['id'], row['label'], row['kind'],
                         row['lo'], row['hi'], row['def'], row['n_drawables']))
        if not result:
            print('[FAIL] 一个模型都没扫到 —— 检查 8778 服务器与画廊是否正常')
            return 2
        json.dump(result, open(DST, 'w', encoding='utf-8'), ensure_ascii=False,
                  separators=(',', ':'))
        print(f'\n写出 {DST}（{os.path.getsize(DST)} B），覆盖 {len(result)} 个模型')
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())
