# -*- coding: utf-8 -*-
"""装扮热区**可达率基线**（只读，不改产品）：每个热区到底有多少面积真的点得到、被谁抢走。

为什么先做这一支（2026-10-28 用户拍板「B 先做、A 紧跟」）：
  产品当前的嵌套优先级是「**面积最小者胜**」（`costumeHitV`）。这个规则下，被大热区包住的
  小热区（戒指 `Paramring` 只驱动 1 个 drawable）会赢下**整片外层热区**，而外层（丝袜/衣服）
  的自身区域反而点不到 —— 但到目前为止只有零散的个案读数（`__costumeScreenOf` 反解出的点
  命中 Paramring），**没有一张能当基线的表**。改优先级（A）如果拿不出「改前 vs 改后」的
  逐热区数字，就无法证明改动是净收益而不是把别处抢坏了。

  所以本脚本**只测量、不判定产品好坏**：它把现状如实记成一份基线 JSON，
  A 改完后重跑同一脚本逐行对比（判据：所有热区可达率不得下降，且至少一个显著上升）。

测三样东西（都走**产品自己的入口**，不另写一份几何 —— 复算版与产品不一致就会自证）：
  ① **屏幕网格**：视口内按 step 采样，每点调 `__costumeHit(cx,cy)`（与 onUp 完全同一个函数），
     统计每个热区**实际赢下**多少采样点。这回答「用户真的点不点得到」（含相机裁剪/出画）。
  ② **模型坐标网格**：在所有热区包围盒的并集内按 step 采样，每点调 `__costumeHitV(vx,vy)`，
     同时自己按产品**同样的 2% 容差**算「这一点落在哪些热区的盒子里」。
     → 每热区「应得点数(own) / 实得点数(win)」= **可达率**；并输出**谁抢走了谁的多少点**。
  ③ 仪器闸（三条，任一红则整份结论作废，退出码 3）：
     · **守恒**：Σ各热区 win == 有赢家的采样点数（一个点最多只能有一个赢家）
     · **阴性对照**：并集框外的点 `__costumeHitV` 必须返回 null（否则判定函数恒真）
     · **几何稳定**：扫描前后 `__costumeBoxes()` 的盒哈希必须一致（扫描期间几何漂移 ⇒
       每点用的盒子不是同一个，可达率无意义）。扫描前已 `stopAllMotions` 冻住动作。

⚠️ 为什么用「网格采样」而不是解析求面积：热区不是矩形（被内层抢走一块后是环），
   解析面积要复算交并集，等于再写一份几何；采样法与产品判定同源，且能直接给「谁抢谁」。
⚠️ step 越小越准、越慢（每点都要跑一次产品的 `costumeHitV`，它会重算全部热区盒）。
   默认屏幕 step=10、V 空间自适应（目标 ~180×180 网格）；`--step N` 可覆盖。

用法:
  py -3 scripts/diag/l2d_hotzone_reachability.py                 # ougen_8
  py -3 scripts/diag/l2d_hotzone_reachability.py ougen_8 --step 8
输出: .diag/costume_hotzone/reachability_<key>.json + 终端表
退出码：0 基线已记录且仪器有效 / 2 环境故障 / 3 仪器红（结论作废）
"""
import json
import os
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))

from gallery_ui_shots import Page  # noqa: E402

KEY = sys.argv[1] if len(sys.argv) > 1 else 'ougen_8'
STEP = 10
for _i, _a in enumerate(sys.argv):
    if _a == '--step' and _i + 1 < len(sys.argv):
        STEP = int(sys.argv[_i + 1])
BASE = 'http://127.0.0.1:8778/gallery_v2/index.html#gallery_v2'
OUT = os.path.join(ROOT, '.diag', 'costume_hotzone')
os.makedirs(OUT, exist_ok=True)

CLOSE_LOGIN = """(function(){var b=document.querySelector('#gOpt button[data-k=login]');
   if(b&&(b.classList.contains('on')||b.dataset.on==='1')) b.click(); return 1;})()"""
OPEN_SHIP = """(function(){var k=%s;
  var s=(window.GALLERY.ships||[]).find(function(x){
     return (x.skins||[]).some(function(o){return o.key===k;});});
  if(!s) return 'NO_SHIP';
  var c=[...document.querySelectorAll('.card')].find(function(e){
     return (e.textContent||'').indexOf(s.name)>=0;});
  if(!c) return 'NO_CARD'; c.click(); return 'OK:'+s.name;})()"""
PICK_SKIN = """(function(){var d=[...document.querySelectorAll('#mSkins .skin')].find(function(e){
   return e.dataset.k===%s;}); if(!d) return 'NO_ROW'; d.click(); return 'OK';})()"""
TO_L2D = """(function(){var t=[...document.querySelectorAll('#mTabs .tab')].find(function(e){
   return e.dataset.k==='live2d';}); if(!t) return 'NO_TAB';
   if(t.classList.contains('dis')) return 'DIS'; t.click(); return 'OK';})()"""
STOP_MOTIONS = """(function(){var m=(window.__l2ModelRef&&window.__l2ModelRef())||null; if(!m) return 0;
  try{ m.internalModel.motionManager.queueManager.stopAllMotions(); }catch(e){}
  try{ m.internalModel.motionManager.state.complete(); }catch(e){}
  return 1;})()"""

# 冻住姿态：单纯 `stopAllMotions()` **不足以**冻结，首版两次实测都栽在这里。
# 运行时 InternalModel.update 顺序（pixi-live2d-display 0.4.0 源码逐行读到）：
#   motionManager.update → saveParameters → expression → eyeBlink(仅未播动作时)
#   → updateFocus → **updateNaturalMovements(dt,now)** → physics → pose
#   → beforeModelUpdate → coreModel.update → **loadParameters**
# 三个独立的持续写手，都不是 motion：
#   ① **idle 自动重启**：`MotionManager.update` 里 `if(isFinished()) … if(state.shouldRequestIdleMotion())
#      startRandomMotion(groups.idle)` —— 所以 `stopAllMotions()` 之后下一帧 idle **立刻回来**，
#      姿态又变了（实测连采 4 次盒哈希全不同：440763990/-1147885542/-141407062/-404750551）。
#      对策：把 `groups.idle` 改成一个**不存在**的动作组名 ⇒ `definitions[group]` 为空 ⇒
#      `startRandomMotion` 直接返回 false，idle 永不重启（只改探针进程内的运行时对象，不碰产品）。
#   ② **自然摆动**：`updateNaturalMovements` 每帧写 ParamAngleX/Y/Z / ParamBodyAngleX/Y/Z /
#      ParamBreath（呼吸+摆头），驱动全身位移 ⇒ 热区盒逐帧漂移。对策：探针内替换为空实现。
#   ③ eyeBlink 写 ParamEyeLOpen/ROpen（面部），不改装扮部件顶点；不处理。
NEUTRALIZE = """(function(){var m=(window.__l2ModelRef&&window.__l2ModelRef())||null; if(!m) return 'NO_MODEL';
  var im=m.internalModel, mm=im&&im.motionManager, done=[];
  if(mm&&mm.groups){ if(!mm.__idleBak) mm.__idleBak=mm.groups.idle;
    mm.groups.idle='__hz_frozen__'; done.push('idleOff:'+mm.__idleBak); }
  try{ if(mm){ mm.queueManager.stopAllMotions(); mm.state.reset&&mm.state.reset(); } done.push('mot'); }catch(e){}
  if(typeof im.updateNaturalMovements==='function'){
    im.updateNaturalMovements=function(){}; done.push('breath'); }
  if(im.physics&&typeof im.physics.reset==='function'){ try{ im.physics.reset(); done.push('physReset'); }
    catch(e){} }
  return done.join(',');})()"""

# 几何稳定性探针：返回当前盒哈希 + 每个盒的明细（定位「哪个盒在动」时用）
BOX_HASH = """(function(){var b=window.__costumeBoxes()||[]; var s=0, o=[];
  for(var i=0;i<b.length;i++){ var g=b[i].box;
    s=(s*31+Math.round(g.x0*1000)+Math.round(g.y0*1000)*7+
       Math.round(g.x1*1000)*13+Math.round(g.y1*1000)*101)|0;
    o.push([b[i].id, Math.round(g.x0*100), Math.round(g.y0*100),
              Math.round(g.x1*100), Math.round(g.y1*100)]); }
  return JSON.stringify({h:s, d:o});})()"""

# 热区清单快照 + 盒哈希（几何稳定性判据用）
BOXES = """(function(){var b=(window.__costumeBoxes&&window.__costumeBoxes())||[];
  var out=b.map(function(o){return {id:o.id,n:o.n,area:o.area,box:o.box,kind:o.kind};});
  var s=0; for(var i=0;i<out.length;i++){ var g=out[i].box;
    s=(s*31+Math.round(g.x0*1000)+Math.round(g.y0*1000)*7+
       Math.round(g.x1*1000)*13+Math.round(g.y1*1000)*101)|0; }
  return JSON.stringify({n:out.length, hash:s, boxes:out});})()"""

# ① 屏幕网格：每点走产品的 __costumeHit（= onUp 同一函数）
SCREEN_SWEEP = r"""
(function(){
  var t0=performance.now();
  var step=__STEP__;
  var hit=window.__costumeHit, hitV=window.__costumeHitV;
  if(typeof hit!=='function'||typeof hitV!=='function') return JSON.stringify({err:'NO_EXPORT'});
  var w=document.getElementById('l2wrap'); if(!w) return JSON.stringify({err:'NO_WRAP'});
  var r=w.getBoundingClientRect();
  var xa=Math.ceil(r.left)+2, ya=Math.ceil(r.top)+2;
  var xb=Math.floor(r.right)-2, yb=Math.floor(r.bottom)-2;
  var win={}, total=0, nulls=0, n=0;
  for(var y=ya;y<=yb;y+=step){
    for(var x=xa;x<=xb;x+=step){
      n++;
      var b=hit(x,y);
      if(b){ win[b.id]=(win[b.id]||0)+1; total++; } else nulls++;
    }
  }
  return JSON.stringify({step:step, points:n, wins:total, nulls:nulls, win:win,
                         rect:[xa,ya,xb,yb], ms:Math.round(performance.now()-t0)});
})()
"""

# ② 模型坐标网格：每点走 __costumeHitV；"应得"走 __costumeHitAllV（**多边形**口径）
#    ⚠️ 2026-10-28 口径更正：旧版"应得"是"落在几个**包围盒**里"。包围盒是顶点并集的轴对齐
#    外接矩形，会覆盖大片它自己并不占据的边角 ⇒ 用盒算 own、用多边形算 win，比值天然失真。
#    本轮改用产品同一套 inTriV 判出的多边形覆盖集（ov）当 own，盒子虚增部分单列 care（bx），
#    这样"可达率"才是"自己真正占据的面积里点得到多少"。
VS_SWEEP = r"""
(function(){
  var t0=performance.now();
  var target=__TARGET__;
  var bs=window.__costumeBoxes(); if(!bs||!bs.length) return JSON.stringify({err:'NO_BOXES'});
  var hitV=window.__costumeHitV, allV=window.__costumeHitAllV;
  if(typeof hitV!=='function') return JSON.stringify({err:'NO_EXPORT'});
  if(typeof allV!=='function') return JSON.stringify({err:'NO_EXPORT_ALLV'});
  var ux0=1e9,uy0=1e9,ux1=-1e9,uy1=-1e9,i;
  for(i=0;i<bs.length;i++){ var g=bs[i].box;
    if(g.x0<ux0)ux0=g.x0; if(g.y0<uy0)uy0=g.y0;
    if(g.x1>ux1)ux1=g.x1; if(g.y1>uy1)uy1=g.y1; }
  var span=Math.max(ux1-ux0, uy1-uy0, 1e-6);
  var step=Math.max(span/target, 1e-4);
  var nx=Math.floor((ux1-ux0)/step)+1, ny=Math.floor((uy1-uy0)/step)+1;
  var win={}, own={}, ghost={}, steal={}, anom=0, covered=0, n=0,
      outNulls=0, outTested=0, onlyBox=0, multi=0;
  for(var j=0;j<ny;j++){
    var vy=uy1-j*step;
    for(var k=0;k<nx;k++){
      var vx=ux0+k*step; n++;
      var cov=allV(vx,vy);
      if(!cov){ anom++; continue; }
      /* own 口径 = **可见**多边形覆盖（产品第一遍）+ **幽灵**多边形覆盖（第二遍）。
         两者都是「这个热区真正占据的地方」，只是可见/不可见之别；分开记，
         才能看出某热区是不是全靠幽灵区在撑（用户关掉就点不回来）。 */
      var all=cov.ov.concat(cov.gh);
      if(!all.length){
        if(cov.bx.length) onlyBox++;
        else { if(outTested<40){ outTested++; if(hitV(vx,vy)===null) outNulls++; } }
        continue; }
      covered++;
      if(cov.ov.length>1) multi++;
      for(i=0;i<cov.ov.length;i++) own[cov.ov[i]]=(own[cov.ov[i]]||0)+1;
      for(i=0;i<cov.gh.length;i++) ghost[cov.gh[i]]=(ghost[cov.gh[i]]||0)+1;
      var wb=hitV(vx,vy);
      if(!wb){ anom++; continue; }
      win[wb.id]=(win[wb.id]||0)+1;
      for(i=0;i<all.length;i++){ if(all[i]===wb.id) continue;
        var row=steal[wb.id]||(steal[wb.id]={}); row[all[i]]=(row[all[i]]||0)+1; }
    }
  }
  /* 覆盖关系（多边形口径）：A 的每个采样点是否都落在 B 的多边形里 ⇒ 真嵌套。
     用**点集包含**而不是盒包含判：盒包含会被"盒大而形空"骗过去。 */
  return JSON.stringify({step:step, nx:nx, ny:ny, points:n, covered:covered,
                         wins:(function(){var s=0;for(var q in win)s+=win[q];return s;})(),
                         anom:anom, outTested:outTested, outNulls:outNulls,
                         onlyBox:onlyBox, multi:multi, ghost:ghost,
                         win:win, own:own, steal:steal, boxOf:(function(){
                           var o={}; for(var i=0;i<bs.length;i++) o[bs[i].id]=bs[i].box; return o;})(),
                         union:[ux0,uy0,ux1,uy1], ms:Math.round(performance.now()-t0)});
})()
"""


def preflight(url):
    try:
        with urllib.request.urlopen(url.split('#')[0], timeout=6) as r:
            return r.status == 200
    except Exception as exc:  # noqa: BLE001
        print('[FAIL] 服务不可达:', exc)
        return False


def main():
    if not preflight(BASE):
        return 2
    pg = Page(9477, r'D:\azur\.diag\hz_prof', BASE, (1400, 1000), gpu=True, keepalive=True)
    try:
        time.sleep(4)
        pg.ev(CLOSE_LOGIN)
        time.sleep(0.9)
        print('开卡:', pg.ev(OPEN_SHIP % json.dumps(KEY)))
        time.sleep(1.6)
        print('选肤:', pg.ev(PICK_SKIN % json.dumps(KEY)))
        time.sleep(1.3)
        print('切L2D:', pg.ev(TO_L2D))

        MODEL = "(function(){ return (window.__l2ModelRef&&window.__l2ModelRef())?1:0; })()"
        ok = 0
        for _ in range(60):
            # COSTUME/PARAM_DRAWABLES 是脚本内 let（不在 window 上）；用产品出口 + __paramDrawables 判就绪
            ok = pg.ev("(function(){ return (%s && window.__costumeBoxes && window.__costumeHit"
                       " && window.__costumeHitV && window.__costumeHitAllV"
                       " && __costumeBoxes().length) ? 1 : 0; })()" % MODEL)
            if ok == 1:
                break
            time.sleep(1.0)
        if ok != 1:
            print('[FAIL] 模型/热区表未就绪（缺 __costumeHitV 说明前端未部署）')
            return 2

        # 帧源闸：几何来自 core.update，rAF 停摆会让顶点冻在旧姿态（静止基线也要有活帧）
        print('\n帧源:', pg.detach_frames(60))
        time.sleep(3.0)
        print('   闸: %.1f fps' % pg.require_frames(2.0))

        # 冻住动作 + 呼吸（否则盒哈希逐帧变，网格口径自证）+ 冻结几何刷新（扫描期不换快照）
        print('冻结姿态:', pg.ev(NEUTRALIZE))
        time.sleep(1.5)
        pg.require_frames(1.0)
        print('冻结几何:', pg.ev("(function(){window.__costumeGeoFreeze=1;"
                                " return window.__costumeGeoFreeze;})()"))

        # 几何稳定闸：连采 4 次，每次之间**真的等** 0.5 s（背靠背采到同值只是采样错了）
        hs = []
        for _ in range(4):
            hs.append(json.loads(pg.ev(BOX_HASH)))
            time.sleep(0.5)
        hh = [h['h'] for h in hs]
        if len(set(hh)) != 1:
            print('\n[WARN] 冻结后几何仍在漂：%s' % hh)
            print('       各盒 100× 坐标（判断哪个盒在动）：')
            for a, b in zip(hs[0]['d'], hs[-1]['d']):
                d = [abs(b[1] - a[1]), abs(b[2] - a[2]), abs(b[3] - a[3]), abs(b[4] - a[4])]
                print('         %-14s Δ=%-14s %s→%s' % (a[0], max(d), a[1:], b[1:]))
        else:
            print('   几何稳定：哈希 %s 连采 4 次一致' % hh[0])

        b0 = json.loads(pg.ev(BOXES))
        print('\n① 热区 %d 个（盒哈希 %s）:' % (b0['n'], b0['hash']))
        for b in b0['boxes']:
            q = b['box']
            print('   %-16s n=%-3d area=%-8.4f 盒[%.3f %.3f %.3f %.3f]'
                  % (b['id'], b['n'], b['area'], q['x0'], q['y0'], q['x1'], q['y1']))

        scr = json.loads(pg.ev(SCREEN_SWEEP.replace('__STEP__', str(STEP))))
        if scr.get('err'):
            print('[FAIL] 屏幕扫描:', scr['err'])
            return 2
        print('\n② 屏幕网格 step=%d：%d 点，命中 %d，未命中 %d（%.0f ms）'
              % (scr['step'], scr['points'], scr['wins'], scr['nulls'], scr['ms']))

        vs = json.loads(pg.ev(VS_SWEEP.replace('__TARGET__', '180')))
        if vs.get('err'):
            print('[FAIL] V 空间扫描:', vs['err'])
            return 2
        print('③ 模型网格 %dx%d step=%.4f：多边形覆盖点 %d / 采样 %d，命中 %d；'
              '仅盒覆盖(虚增) %d，多重覆盖 %d（%.0f ms）'
              % (vs['nx'], vs['ny'], vs['step'], vs['covered'], vs['points'],
                 vs['wins'], vs['onlyBox'], vs['multi'], vs['ms']))

        b1 = json.loads(pg.ev(BOXES))

        # ---------- 仪器闸 ----------
        print('\n' + '=' * 74)
        gates = []
        if b1['hash'] != b0['hash']:
            gates.append('几何漂移：扫描前后盒哈希 %s→%s（可达率不可信）' % (b0['hash'], b1['hash']))
        if vs['wins'] + vs['anom'] != vs['covered']:
            gates.append('守恒失败：命中 %d + 异常 %d != 多边形覆盖点 %d'
                         % (vs['wins'], vs['anom'], vs['covered']))
        if vs['outTested'] and vs['outNulls'] != vs['outTested']:
            gates.append('阴性对照失败：任何热区都不覆盖的 %d 点里只有 %d 点返回 null'
                         % (vs['outTested'], vs['outNulls']))
        if vs['anom']:
            gates.append('有 %d 个「被多边形覆盖但判定无赢家」的点（口径不一致？）' % vs['anom'])
        for g in gates:
            print('  GATE-RED', g)
        print('  GATE 守恒/阴性对照/几何稳定：%s' % ('PASS' if not gates else 'FAIL'))

        # ---------- 可达率表 ----------
        ids = [b['id'] for b in b0['boxes']]
        print('\n④ 可达率（模型坐标；own=**多边形**覆盖到自己的采样点，win=最终判给自己）')
        print('   口径更正：own 不再是包围盒口径（盒会覆盖自己不占据的边角，比值天然失真）。')
        print('   「被抢」= 该点被多边形同时覆盖它的其它热区抢走（允许多个候选，产品按渲染序取最上层）')
        print('   %-14s %7s %7s %8s %7s %7s  %s'
              % ('热区', 'own', 'win', '可达率', '幽灵', '被抢', '被抢主要来自'))
        print('   own 只算**可见**多边形；幽灵=只被隐藏部件覆盖（产品第二遍仍能点到）。')
        print('   可达率 = win / (own + 幽灵)，即"这个热区真正占据的地方里点得到多少"。')
        rows = []
        for pid in ids:
            own = vs['own'].get(pid, 0)
            gh = vs.get('ghost', {}).get(pid, 0)
            den = own + gh
            win = vs['win'].get(pid, 0)
            rate = (100.0 * win / den) if den else 0.0
            los = max(0, den - win)
            thieves = []
            for who, row in vs['steal'].items():
                c = row.get(pid, 0)
                if c:
                    thieves.append((c, who))
            thieves.sort(reverse=True)
            tdesc = ', '.join('%s×%d' % (w, c) for c, w in thieves[:3]) or '—'
            print('   %-14s %7d %7d %7.1f%% %7d %7d  %s' % (pid, own, win, rate, gh, los, tdesc))
            rows.append({'id': pid, 'own': own, 'ghost': gh, 'win_v': win,
                         'rate_v': round(rate, 2), 'lost': los,
                         'stolen_by': [{'from': w, 'points': c} for c, w in thieves],
                         'win_screen': scr['win'].get(pid, 0)})
        # 屏幕侧（用户视角）：按赢下的采样点排
        print('\n⑤ 屏幕可达点数（视口内 step=%d，含相机裁剪；只能横向比，不是比例）' % scr['step'])
        for r in sorted(rows, key=lambda x: -x['win_screen']):
            share = 100.0 * r['win_screen'] / max(1, scr['wins'])
            print('   %-16s %6d 点（占命中面 %.1f%%）' % (r['id'], r['win_screen'], share))

        # 抽样落点：每个热区"最该点得到"的那一点反解出来，看命中谁（人眼可核）
        print('\n⑥ __costumeScreenOf 反解点（产品自己的取点出口）')
        probes = []
        for r in rows:
            raw = pg.ev("JSON.stringify(window.__costumeScreenOf(%s))" % json.dumps(r['id']))
            sc = json.loads(raw) if raw and raw != 'null' else None
            if not sc:
                print('   %-16s 视口内点不到（null）' % r['id'])
                probes.append({'id': r['id'], 'screenof': None})
                continue
            hit = pg.ev("(function(){var b=window.__costumeHit(%d,%d);"
                        " return b?b.id:null;})()" % (sc['cx'], sc['cy']))
            print('   %-16s n=%-5d edge=%-3s → 命中 %s'
                  % (r['id'], sc['n'], sc['edge'], hit))
            probes.append({'id': r['id'], 'screenof': sc, 'hit_at_point': hit})

        # ---------- 落盘 ----------
        doc = {'key': KEY, 'step_screen': STEP, 'boxes': b0['boxes'], 'box_hash': b0['hash'],
               'screen': {k: scr[k] for k in ('step', 'points', 'wins', 'nulls', 'win',
                                              'rect', 'ms')},
               'vspace': {k: vs[k] for k in ('step', 'nx', 'ny', 'points', 'covered', 'wins',
                                             'anom', 'outTested', 'outNulls', 'union', 'ms',
                                             'onlyBox', 'multi')},
               'rows': rows, 'screenof': probes, 'gates': gates,
               'at': time.strftime('%Y-%m-%d %H:%M:%S')}
        path = os.path.join(OUT, 'reachability_%s.json' % KEY)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(doc, f, ensure_ascii=False, indent=1)
        print('\n基线已写: %s' % path)
        print('=' * 74)
        return 0 if not gates else 3
    finally:
        try:
            pg.ev("(function(){window.__costumeGeoFreeze=0; return 1;})()")
        except Exception:  # noqa: BLE001
            pass
        pg.close()


if __name__ == '__main__':
    sys.exit(main())
