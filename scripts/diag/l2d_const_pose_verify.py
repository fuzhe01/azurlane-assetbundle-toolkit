# -*- coding: utf-8 -*-
"""ConstantClip 定值曲线的运行时生效验证（CDP，headless Edge，§134 实战沉淀）。

验什么：EMIT_CONST 换入后，「姿势定值」是否真的在浏览器里落到参数上——
  play(<组>) → 姿势参数应精确等于该组 constant 定值；切回默认 idle 应归 0
  （constant 定值 = 数据侧权威复位指令，归零是它的本职）。
信源选择：参数直读是权威（§132 教训：截图法三层假阴性）；截图差分只做佐证。

用法：改下方 SKIN / GROUP / POSE / EXPECT 四个常量后
  py -3 scripts/diag/l2d_const_pose_verify.py
定值从哪来：源 bundle 的 m_ConstantClip.data 与 genericBindings 对位
  （见 docs/TROUBLESHOOTING.md §134 的探针方法），挑与默认 idle 不同的非零条目。
前置：8777 画廊服务器在跑；会尝试禁开场 login（localStorage 被拒时自动退化
  为真实场景验证——开场 login → GROUP 的全链路，§133 竞态修复同场覆盖）。"""
SKIN = 'ougen_8'
GROUP = 'idle9'
POSE = ['Param345', 'Param372', 'Param91', 'Param97', 'Param352', 'Param494', 'Param500', 'Param502', 'Param506']
EXPECT = {'Param345': -1.280, 'Param372': -0.920, 'Param91': 1.0, 'Param97': 1.0,
          'Param352': 1.0, 'Param494': 1.0, 'Param500': 1.0, 'Param502': 1.0, 'Param506': 1.0}
import sys, os, json, time, subprocess, urllib.request
sys.stdout.reconfigure(encoding='utf-8')
import websocket

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
sys.path.insert(0, os.path.join(ROOT, 'scripts', 'diag'))
import cdp_slot
CHROME = r'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
PORT, PROFILE = cdp_slot.slot(ROOT, 'constverify')
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
  for(const s of GALLERY.ships){ const k=s.skins.find(x=>x.key==='""" + SKIN + """'); if(k&&s.live2dSkins.includes('""" + SKIN + """')){ship=s;sk=k;break;} }
  if(!sk) return 'NO_SKIN';
  openShip(ship); setSkin(sk); buildSkinList(ship);
  const l2=[...document.querySelectorAll('#mTabs .tab')].find(x=>x.dataset.k==='live2d');
  l2.click();
  for(let i=0;i<110 && !(l2State&&l2State.app&&l2State.app.stage.children[0]);i++) await t(500);
  if(!(l2State&&l2State.app&&l2State.app.stage.children[0])) return 'NO_MODEL';
  return 'OK';
})()"""
print('setup:', ev(SETUP))
RD = """(()=>{
  const core=l2State.app.stage.children[0].internalModel.coreModel;
  const mm=l2State.app.stage.children[0].internalModel.motionManager;
  const o={g:mm.state&&mm.state.currentGroup||null};
  for(const p of %s) o[p]=+core.getParameterValueById(p).toFixed(3);
  return JSON.stringify(o);
})()""" % json.dumps(POSE)

time.sleep(2.5)
base = json.loads(ev(RD))
print('baseline(默认idle):', json.dumps(base, ensure_ascii=False))

print(f'play({GROUP}):', ev(f"window.__l2play('{GROUP}') ? 'played' : 'false'"))
time.sleep(2.5)
s9 = json.loads(ev(RD))
print(f'{GROUP} 态:', json.dumps(s9, ensure_ascii=False))

print('\n姿势参数判定(换入后应为定值):')
allok = True
for p in POSE:
    got, want = s9.get(p), EXPECT[p]
    ok = got is not None and abs(got - want) < 0.02
    allok = allok and ok
    print(f"  {p:<9} 期望 {want:>7.3f} 实测 {got:>7} {'✓' if ok else '✗'}")

# 切回默认 idle,姿势应回 0
ev("window.__l2play('idle')")
time.sleep(2.5)
s0 = json.loads(ev(RD))
print('\n切回默认 idle:', json.dumps(s0, ensure_ascii=False))
backok = all(abs(s0.get(p, 99)) < 0.02 for p in POSE)
print('回零判定:', '✓ 全部回 0' if backok else '✗ 未回零')
print('\n终判:', 'PASS' if (allok and backok) else 'FAIL')

try: cmd('Browser.close')
except Exception: pass
try: proc.wait(timeout=10)
except Exception: chrome_tree.kill_tree(proc.pid)