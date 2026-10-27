# -*- coding: utf-8 -*-
"""Live2D 交互回归：裸滚轮不劫持/不缩放、Ctrl+滚轮才缩放、pointercancel 解除拖拽不再漂移、
   有判定区的模型点空白不播动作、点部位正常播。"""
import sys, os, json, time, base64, subprocess, urllib.request
sys.stdout.reconfigure(encoding='utf-8')
import websocket

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # 本目录：chrome_tree / probe_exit
import cdp_slot            # 端口 / profile 不写死：写死会让两个会话灌进同一个页面（见该模块 docstring）
import cdp_wait            # 就绪门槛不能用 document.readyState（about:blank 天生 complete）
import probe_exit
CHROME = r'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
PORT, PROFILE = cdp_slot.slot(ROOT, 'intv')
# INTV_URL / INTV_MODELS 可覆盖默认的旧画廊(8777)与固定 4 模型清单：
# 本项目画廊(8778, 5 样本)回归用 INTV_URL=http://127.0.0.1:8778/gallery_v2/index.html
GALLERY_URL = os.environ.get('INTV_URL', 'http://127.0.0.1:8777/gallery_v2/index.html')
proc = subprocess.Popen([CHROME, '--headless=new', f'--remote-debugging-port={PORT}',
  '--remote-allow-origins=*', f'--user-data-dir={PROFILE}', '--no-first-run',
  '--no-default-browser-check', '--disable-background-timer-throttling', '--enable-unsafe-swiftshader',
  '--use-angle=swiftshader', '--window-size=1280,900',
  GALLERY_URL], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
import chrome_tree; chrome_tree.install(proc)   # 异常退出也要收整棵树，见该模块 docstring
w = None
for _ in range(90):
    try:
        tabs = json.load(urllib.request.urlopen(f'http://127.0.0.1:{PORT}/json'))
        w = [t['webSocketDebuggerUrl'] for t in tabs if 'gallery_v2' in t.get('url', '') and t.get('webSocketDebuggerUrl')]
        if w: break
    except Exception: pass
    time.sleep(0.5)
ws = websocket.create_connection(w[0], timeout=120, max_size=None)
_id = 0
def cmd(m, p=None):
    global _id; _id += 1; mid = _id
    ws.send(json.dumps({'id': mid, 'method': m, 'params': p or {}})); ws.settimeout(120)
    while True:
        r = json.loads(ws.recv())
        if r.get('id') == mid:
            if 'error' in r: raise RuntimeError(json.dumps(r['error'])[:150])
            return r.get('result', {})
def ev(e):
    r = cmd('Runtime.evaluate', {'expression': e, 'returnByValue': True, 'awaitPromise': True})
    if r.get('exceptionDetails'): return 'EVALERR ' + str(r['exceptionDetails'].get('text'))[:180]
    return r.get('result', {}).get('value')

JS = r"""(async(key)=>{ try{
  const t=ms=>new Promise(r=>setTimeout(r,ms));
  for(let i=0;i<90 && !window.GALLERY;i++) await t(300);
  let ship=null, sk=null;
  for(const s of GALLERY.ships){ const k=s.skins.find(x=>x.key===key); if(k&&s.live2dSkins.includes(key)){ship=s;sk=k;break;} }
  if(!sk) return JSON.stringify({key, skip:'no skin'});
  openShip(ship); setSkin(sk); buildSkinList(ship);
  const l2=[...document.querySelectorAll('#mTabs .tab')].find(x=>x.dataset.k==='live2d');
  l2.click();
  // 与 l2d_inspector_verify.py 同一个坑：固定等 6.5s 对大贴图皮肤（benningdun_2 三张共 40MB，
  // 且服务器单线程）必然不够，表现为四个皮肤全报 reading 'internalModel' 的假失败。
  // 固定等 6s 对 big 贴图皮肤（40MB / 单线程服务器）必然不够；轮询到模型真进舞台为止。
  // ⚠️ 预算必须与 l2d_inspector_verify 对齐（150 次 × 500ms = 75s，上限 150s 量级）：
  //    80×500ms=40s 在**连跑 5 个模型**时不够——每个皮肤三件套约 40MB、服务器单线程，
  //    排在最后的 ougen_8 冷启实测超 40s（单跑却只要 3s），会间歇报「模型未加载」。
  //    `--disable-background-timer-throttling` 已加，但网络+解码是串行的，只能抬预算。
  for(let i=0;i<200 && !(l2State&&l2State.app&&l2State.app.stage.children[0]);i++) await t(500);
  if(!(l2State&&l2State.app&&l2State.app.stage.children[0]))
      return JSON.stringify({key, err:'100s 内模型未加载', note:(document.querySelector('.note')||{}).textContent||''});
  const app=l2State.app, m=app.stage.children[0], im=m.internalModel, core=im.coreModel, ppu=im.pixelsPerUnit||1, mm=im.motionManager;
  const cux2=im.width/ppu, cuy2=im.height/ppu;   // 画布单位边长：V(中心原点/y向上)↔P(左上/y向下) 换算用
  const wrap=document.getElementById('l2wrap'), rect=wrap.getBoundingClientRect();
  const hitAreas=im.settings.hitAreas||[];
  const cx=rect.left+rect.width/2, cy=rect.top+rect.height/2;
  const st=()=>({scale:+m.scale.x.toFixed(6), x:Math.round(m.x), y:Math.round(m.y), grp:mm.state.currentGroup||null});
  const out={key, groups:Object.keys(mm.definitions||{}).length, nAreas:(im.settings.hitAreas||[]).length, start:st()};

  // ① 裸滚轮 20 格：不应改变缩放/位置（也不 preventDefault）
  for(let i=0;i<20;i++){ const e=new WheelEvent('wheel',{deltaY:-120,clientX:cx,clientY:cy,bubbles:true,cancelable:true});
    wrap.dispatchEvent(e); if(e.defaultPrevented) out.plainWheelPrevented=true; await t(25); }
  await t(300); out.afterPlainWheel=st();
  out.plainWheelNoop = out.plainWheelPrevented!==true && out.afterPlainWheel.scale===out.start.scale;

  // ② Ctrl+滚轮 5 格：应放大
  for(let i=0;i<5;i++){ wrap.dispatchEvent(new WheelEvent('wheel',{deltaY:-120,clientX:cx,clientY:cy,ctrlKey:true,bubbles:true,cancelable:true})); await t(40); }
  await t(300); out.afterCtrlWheel=st();
  out.ctrlWheelZooms = out.afterCtrlWheel.scale > out.start.scale*1.2;

  // 复位
  document.getElementById('l2Fit').click(); await t(300);

  // ③ pointerdown -> pointercancel -> 再移动：模型不应漂移
  const p0=st();
  wrap.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true,pointerId:7,clientX:cx,clientY:cy,button:0}));
  window.dispatchEvent(new PointerEvent('pointercancel',{bubbles:true,pointerId:7,clientX:cx,clientY:cy}));
  for(let i=0;i<10;i++){ window.dispatchEvent(new PointerEvent('pointermove',{bubbles:true,pointerId:7,clientX:cx+i*30,clientY:cy+i*20})); await t(25); }
  await t(300); const p1=st();
  out.cancelDrift=Math.abs(p1.x-p0.x)+Math.abs(p1.y-p0.y);
  out.cancelStopsDrag = out.cancelDrift < 3;

  // ④ 点「在所有判定框之外」的点：有判定区的模型不应播任何动作。
  //    注意不能用画面角落代替空白——AL 的 Touch 框本身很大，视觉空白处可能仍属某部位（模型自带定义，游戏同样如此）
  mm.startMotion('idle',0,3); await t(500); const g0=st().grp;
  let ox2=-9, oy2=-9;
  { let guard=0, inside=true;
    while(inside && guard++<40){ inside=false;
      for(const a of (im.settings.hitAreas||[])){ const i=core.getDrawableIndex(a.Id); const pp=core.getDrawableVertexPositions(i);
        if(!pp||!pp.length) continue;
        let x0=1e9,y0=1e9,x1=-1e9,y1=-1e9; for(let k=0;k+1<pp.length;k+=2){x0=Math.min(x0,pp[k]);y0=Math.min(y0,pp[k+1]);x1=Math.max(x1,pp[k]);y1=Math.max(y1,pp[k+1]);}
        const ex=(x1-x0)*0.02, ey=(y1-y0)*0.02;
        if(ox2>=x0-ex&&ox2<=x1+ex&&oy2>=y0-ey&&oy2<=y1+ey){ inside=true; ox2-=2; oy2-=1.5; break; } } } }
  const og=m.toGlobal(new PIXI.Point((ox2+cux2/2)*ppu, (cuy2/2-oy2)*ppu));   // V(顶点原生,中心原点/y向上)→P→global，与产品 hitAt 的 P2V 互逆
  const e1={bubbles:true,cancelable:true,pointerId:9,clientX:rect.left+og.x,clientY:rect.top+og.y,button:0};
  wrap.dispatchEvent(new PointerEvent('pointerdown',e1)); window.dispatchEvent(new PointerEvent('pointerup',e1));
  await t(700); out.emptyClick={probeUnits:[+ox2.toFixed(1),+oy2.toFixed(1)], before:g0, after:st().grp,
    /* null=idle 看守者轮换重取数的间隙（无头下 fetch 慢更明显），不算触发动作 */
    noAction: st().grp===g0 || st().grp===null};

  // ⑤ 点 Head 中心：应播该部位的**某个**合法动作组。
  //    A3 规则（2026-09-24 用户裁定）：同一位置重叠多个 Touch 标记时**随机**冒一条，
  //    所以断言必须是"集合"不是"单值"——旧写法 `played===hitAreas[0].Name` 把 A3 的正确行为
  //    判成假失败（aersasi_2 实测 played=idle want=touch_head）。
  const grps=Object.keys((im.motionManager&&im.motionManager.definitions)||{});
  const dragG=n=>{ if(grps.includes(n)) return n;
    const alt=n.replace(/^touchdrag(\d+)$/i,'touch_drag$1');
    if(grps.includes(alt)) return alt;
    const ds=grps.filter(x=>/^touch_drag\d+$/.test(x));
    if(!ds.length) return null;
    return ds[(parseInt((n.match(/(\d+)$/)||[])[1]||'1',10)-1)%ds.length]; };
  const grpOf=nm=>{ const low=String(nm).toLowerCase();
    return grps.includes(nm) ? nm : (grps.find(x=>x.toLowerCase()===low) || dragG(nm)); };
  const hi=core.getDrawableIndex((im.settings.hitAreas||[])[0]?.Id);
  if(hi>=0){ const p=core.getDrawableVertexPositions(hi); let sx=0,sy=0,n=0;
    for(let k=0;k+1<p.length;k+=2){sx+=p[k];sy+=p[k+1];n++;}
    const pvx=sx/n, pvy=sy/n;                       // V 空间（顶点原生，中心原点/y向上）
    const g=m.toGlobal(new PIXI.Point((pvx+cux2/2)*ppu, (cuy2/2-pvy)*ppu));   // V→P→global，与 hitAt 互逆
    /* 候选集合直接问**产品自己**（__L2_HITALL 与 localHit 同一套几何），不在探针里另算一份。
       参数口径已核对：`hitAll(mx,my)` 收的是**模型空间 V 坐标**（index.html L1889 内部直接拿
       g.x0/x1 与 quad 顶点比）—— 恰好就是上面算出的 pvx/pvy（V 空间顶点平均），所以这个调用是对的。
       ⚠️ 曾经写成裸 `catch(e){}`：全局缺失时静默得到空候选，再经 `ok = candG.length ? … : false`
       报成 `want:[]` 的 FAIL，看起来像"产品点不出动作"，实为探针钩子没加载 ⇒ 无法区分。
       现在显式记来源，全局缺失时**降级**为"登记框名清单"（弱基线）并在 fail 时注明，避免误判。 */
    let cand=[], candSrc='__L2_HITALL';
    if(typeof window.__L2_HITALL === 'function'){ try{ cand=[...new Set(window.__L2_HITALL(pvx,pvy))]; }catch(e){ candSrc='HITALL_THREW:'+String(e&&e.message||e).slice(0,60); } }
    else { cand=(im.settings.hitAreas||[]).map(a=>a.Name); candSrc='fallback:settings.hitAreas（页面未暴露 __L2_HITALL）'; }
    const candG=[...new Set(cand.map(grpOf).filter(Boolean))];
    const e2={bubbles:true,cancelable:true,pointerId:10,clientX:rect.left+g.x,clientY:rect.top+g.y,button:0};
    wrap.dispatchEvent(new PointerEvent('pointerdown',e2)); window.dispatchEvent(new PointerEvent('pointerup',e2));
    /* startMotion 是 async（要拉 motion3.json）。固定等 1.6s 在单线程服务器 + 20s 级大 clip 上
       必然读到还没换组的 currentGroup → 假失败。改成轮询到进组或 12s 上限。 */
    let played=st().grp, waited=0;
    while(waited<12000 && !candG.includes(played)){ await t(300); waited+=300; played=st().grp; }
    out.headClick={wantName:(im.settings.hitAreas[0].Name), cand, candSrc, want:candG, played, waited,
      pill:(document.getElementById('l2Hit')||{}).textContent};
    out.headClick.ok = candG.length ? candG.includes(played) : false;
  }
  out.endScale=st().scale;
  return JSON.stringify(out,null,1);
}catch(e){ return 'ERR '+(e.message||e); }})
"""
os.makedirs(os.path.join(ROOT, '.diag', 'size_shots'), exist_ok=True)
# 🔴 就绪门槛：about:blank 的 readyState 天生 'complete'，只看它第一次判就放行，
# 后续求值全打在空白页上 → 报 `openShip is not defined` 这类**探针自身假失败**。
_ok, _secs, _last = cdp_wait.wait_ready(ev, GALLERY_URL, budget=150)
print(f'  [ready] ok={_ok} {_secs}s last={_last}', flush=True)
if not _ok:
    print('[ERROR] 页面在预算内未就绪（探针故障，非产品故障）'); ws.close(); chrome_tree.kill_tree(proc.pid); sys.exit(2)
allok = True
_models_env = os.environ.get('INTV_MODELS')
# 默认清单必须只含**本项目画廊实有**的模型（index.json 的 live2dSkins）。
# 旧清单里的 anninvwang_2 / lafeiii_3 在本项目不存在 → 探针打印 skip:'no skin' 后 exit 0，
# runner 记成通过（假绿）。缺失模型现在按「未评估」计，见尾部退出码。
DEFAULT_MODELS = 'benningdun_2,aersasi_2,aersasi_3,antu_2,ougen_8'
for k in ([m.strip() for m in _models_env.split(',') if m.strip()] if _models_env
          else DEFAULT_MODELS.split(',')):
    out = None
    for _try in range(6):
        try:
            out = ev(JS + f"({json.dumps(k)})"); break
        except RuntimeError as e:
            # 页面导航中 CDP 执行上下文会被销毁（探针自身的假失败，WF-16 同类）；
            # 上下文在导航结束后重建，重连同一张 tab 即可，别据此判定产品坏了。
            # 就绪已由 cdp_wait.wait_ready 前置保证，这里不再拿 readyState 当门槛。
            print(f"  [{k}] retry {_try+1}: {str(e)[:70]}", flush=True); time.sleep(4)
    if out is None:
        allok = False; print('=====', k); print('  ✗ 6 次仍拿不到稳定执行上下文（探针故障，非产品故障）'); continue
    print('=====', k)
    print(out)
    try:
        d = json.loads(out)
        if probe_exit.bad_reason(d):
            print(f"  ⊘ 未评估: {probe_exit.bad_reason(d)}（不计通过）")
            allok = False
            continue
        bad = [x for x in ('plainWheelNoop', 'ctrlWheelZooms', 'cancelStopsDrag') if d.get(x) is False]
        if d.get('emptyClick', {}).get('noAction') is False: bad.append('emptyClick')
        if d.get('headClick') and d['headClick'].get('ok') is False: bad.append('headClick')
        if bad: allok = False; print('  ✗ 未通过:', bad)
        else: print('  ✓ 全部通过')
    except Exception: allok = False
print('\n总判定:', 'ALL PASS' if allok else '有未通过项')
r = cmd('Page.captureScreenshot', {'format': 'png'})
open(os.path.join(ROOT, '.diag', 'size_shots', 'interact_final.png'), 'wb').write(base64.b64decode(r['data']))
ws.close(); chrome_tree.kill_tree(proc.pid)
# 退出码契约见 scripts/diag/probe_exit.py：判定与退出码脱节 = 回归永远绿。
# 之前这里只 print 不 exit，'有未通过项' 也是 0，runner 记成通过。
sys.exit(0 if allok else 1)
