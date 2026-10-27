# -*- coding: utf-8 -*-
"""Live2D 动作状态机全链路插桩取证（CDP，headless Edge）。

裁决三类问题的通用模板（2026-10-20 §133 实战沉淀）：
  ① 动作"播不完/不回落"——entry 快照（_startTimeSeconds/_endTimeSeconds/_finished/
     _stateWeight/_loopDurationSeconds/_isLoop）+ 真实时间比对：et 固定且远超 st+dur 仍
     fin:0 = headless 时钟伪影（deltaMS 被 maxElapsedMS cap，勿当 bug 查）；
  ② currentGroup 卡死——MotionState 全字段（currentGroup/currentPriority/reservedGroup/
     reservePriority/reservedIdleGroup）+ queueManager.isFinished()/playing 逐拍序列；
  ③ 调用流断链——包 mm.startMotion/startRandomMotion/state.reserve/setCurrent/complete
     记录（组名/索引/优先级/返回值/时刻），看回落链在哪一环没走。

用法：改下方 SKIN/TEST_GROUP 常量后 `py -3 scripts/diag/l2d_motion_state_trace.py`。
前置：8777 画廊服务器在跑；开场 login 已用 localStorage 禁掉（脚本自带注入）。"""
SKIN = 'ougen_8'
TEST_GROUP = 'touch_idle7'
import sys, os, json, time, subprocess, urllib.request
sys.stdout.reconfigure(encoding='utf-8')
import websocket

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
sys.path.insert(0, os.path.join(ROOT, 'scripts', 'diag'))
import cdp_slot
CHROME = r'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
PORT, PROFILE = cdp_slot.slot(ROOT, 'statetrace')
try:
    with urllib.request.urlopen('http://127.0.0.1:8777/gallery_v2/index.html', timeout=5) as r:
        assert r.status == 200
except Exception as e:
    raise SystemExit(f'! 服务器不可达: {e}')

proc = subprocess.Popen([CHROME, '--headless=new', f'--remote-debugging-port={PORT}',
  '--remote-allow-origins=*', f'--user-data-dir={PROFILE}', '--no-first-run',
  '--no-default-browser-check', '--disable-background-timer-throttling', '--enable-unsafe-swiftshader',
  '--use-angle=swiftshader', '--window-size=1280,900',
  'http://127.0.0.1:8777/gallery_v2/index.html'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
import chrome_tree; chrome_tree.install(proc)
w = None
for _ in range(90):
    try:
        tabs = json.load(urllib.request.urlopen(f'http://127.0.0.1:{PORT}/json'))
        w = [t['webSocketDebuggerUrl'] for t in tabs if 'gallery_v2' in t.get('url', '') and t.get('webSocketDebuggerUrl')]
        if w: break
    except Exception: pass
    time.sleep(0.5)
ws = websocket.create_connection(w[0], timeout=300, max_size=None)
_id = 0
def cmd(m, p=None):
    global _id; _id += 1; mid = _id
    ws.send(json.dumps({'id': mid, 'method': m, 'params': p or {}})); ws.settimeout(300)
    while True:
        r = json.loads(ws.recv())
        if r.get('id') == mid:
            if 'error' in r: raise RuntimeError(json.dumps(r['error'])[:150])
            return r.get('result', {})
def ev(e):
    r = cmd('Runtime.evaluate', {'expression': e, 'returnByValue': True, 'awaitPromise': True})
    if r.get('exceptionDetails'):
        ed = r['exceptionDetails']; ex = ed.get('exception', {}) or {}
        return 'EVALERR ' + str(ex.get('description') or ex.get('value') or ed.get('text'))[:400]
    return r.get('result', {}).get('value')

cmd('Page.enable')
print('set login=false:', ev("localStorage.setItem('gallery.opt.v1', JSON.stringify({login:false}))"))
cmd('Page.navigate', {'url': 'http://127.0.0.1:8777/gallery_v2/index.html'})
time.sleep(2)

SETUP = """(async()=>{
  const t=ms=>new Promise(r=>setTimeout(r,ms));
  for(let i=0;i<90 && !window.GALLERY;i++) await t(300);
  let ship=null, sk=null;
  for(const s of GALLERY.ships){ const k=s.skins.find(x=>x.key==='"+SKIN+"'); if(k&&s.live2dSkins.includes('"+SKIN+"')){ship=s;sk=k;break;} }
  if(!sk) return 'NO_SKIN';
  openShip(ship); setSkin(sk); buildSkinList(ship);
  const l2=[...document.querySelectorAll('#mTabs .tab')].find(x=>x.dataset.k==='live2d');
  l2.click();
  /* 预算 200×500ms=100s：按**最坏情形**（连跑多模型 / 冷启）定，不按单跑实测拍
     （2026-10-27 §156 形态三；同批探针里 inspector 150s / 这里曾 55s 属失配）。 */
  for(let i=0;i<200 && !(l2State&&l2State.app&&l2State.app.stage.children[0]);i++) await t(500);
  if(!(l2State&&l2State.app&&l2State.app.stage.children[0])) return 'NO_MODEL';
  return 'OK';
})()"""
print('setup:', ev(SETUP))

HOOK = """(()=>{
  const mdl=l2State.app.stage.children[0];
  const mm=mdl.internalModel.motionManager;
  const st=mm.state, qm=mm.queueManager;
  const L=(window.__CALLS=window.__CALLS||[]);
  const ts=()=>+(performance.now()/1000).toFixed(2);
  const oSM=mm.startMotion.bind(mm);
  mm.startMotion=(g,i,p)=>{ L.push([ts(),'sm',g,i,p]); return oSM(g,i,p); };
  const oSRM=mm.startRandomMotion.bind(mm);
  mm.startRandomMotion=(g,i,p)=>{ L.push([ts(),'srm',g,i,p]); return oSRM(g,i,p); };
  const oRes=st.reserve.bind(st);
  st.reserve=(g,i,p)=>{ const r=oRes(g,i,p); L.push([ts(),'res',g,i,p,!!r]); return r; };
  const oSet=st.setCurrent.bind(st);
  st.setCurrent=(g,i,p)=>{ L.push([ts(),'setCur',g,i,p]); return oSet(g,i,p); };
  const oCmp=st.complete.bind(st);
  st.complete=()=>{ L.push([ts(),'complete']); return oCmp(); };
  window.__HOOKED=performance.now();
  return 'hooked';
})()"""
print('hook:', ev(HOOK))

RD = """(()=>{
  const mdl=l2State.app.stage.children[0];
  const mm=mdl.internalModel.motionManager, st=mm.state, qm=mm.queueManager;
  const core=mdl.internalModel.coreModel;
  let ents=[];
  try{ ents=qm._motions.map(e=>({st:e._startTimeSeconds, et:e._endTimeSeconds,
    started:e._started, fin:e._finished, w:+(e._stateWeight||0).toFixed(2),
    fto:e._isTriggeredFadeOut, dur:e._motion&&e._motion._loopDurationSeconds,
    loop:e._motion&&e._motion._isLoop})); }catch(e){ ents='ERR'+String(e).slice(0,50); }
  return JSON.stringify({ut:qm._userTimeSeconds, cg:st.currentGroup, cp:st.currentPriority,
    rg:st.reservedGroup, rp:st.reservePriority, rig:st.reservedIdleGroup,
    qfin:qm.isFinished(), playing:mm.playing,
    ax:+core.getParameterValueById('ParamAngleX').toFixed(2),
    ay:+core.getParameterValueById('ParamAngleY').toFixed(2), n:ents.length, ents});
})()"""

time.sleep(2.0)
print('baseline:', ev(RD))
print('play:', ev("window.__l2play('"+TEST_GROUP+"') ? 'played' : 'false'"))
series = []
t0 = time.time()
for i in range(40):
    r = ev(RD)
    try: d = json.loads(r)
    except Exception: d = {'raw': str(r)[:100]}
    d['t'] = round(time.time() - t0, 2)
    series.append(d)
    time.sleep(0.3)

print(f"\n{'t':>5} {'ut':>7} {'group':<11} {'cp':>2} {'rg':<10} {'rp':>2} {'qfin':>5} {'play':>5} {'ax':>6} {'ay':>6}  entries")
for d in series:
    ents = d.get('ents')
    es = ''
    if isinstance(ents, list):
        es = ' | '.join(f"[st:{e['st']} et:{e['et']} fin:{int(bool(e['fin']))} w:{e['w']} dur:{e['dur']} loop:{str(e['loop'])[:5]}]" for e in ents)
    elif ents: es = str(ents)
    print(f"{d.get('t',''):>5} {str(d.get('ut',''))[:7]:>7} {str(d.get('cg',''))[:11]:<11} {str(d.get('cp',''))[:2]:>2} "
          f"{str(d.get('rg',''))[:10]:<10} {str(d.get('rp',''))[:2]:>2} {str(d.get('qfin',''))[:5]:>5} {str(d.get('playing',''))[:5]:>5} "
          f"{str(d.get('ax',''))[:6]:>6} {str(d.get('ay',''))[:6]:>6}  {es}")

calls = ev("window.__CALLS||[]")
print('\n调用流(前60条):')
if isinstance(calls, list):
    for c in calls[:60]: print(' ', c)

try: cmd('Browser.close')
except Exception: pass
try: proc.wait(timeout=10)
except Exception: chrome_tree.kill_tree(proc.pid)