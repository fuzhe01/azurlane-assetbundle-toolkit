# -*- coding: utf-8 -*-
"""ConstantClip 定值曲线的运行时生效验证（CDP，headless Edge，§134 实战沉淀）。

验什么：EMIT_CONST 换入后，「姿势定值」是否真的在浏览器里落到参数上——
  play(<组>) → 姿势参数应精确等于该组 constant 定值；切回默认 idle 应归 0
  （constant 定值 = 数据侧权威复位指令，归零是它的本职）。
信源选择：参数直读是权威（§132 教训：截图法三层假阴性）；截图差分只做佐证。

用法：改下方 SKIN / GROUP / POSE / EXPECT 四个常量后
  py -3 scripts/diag/l2d_const_pose_verify.py
或用环境变量免改文件批量跑（EXPECT 为 JSON 串）：
  POSE_SKIN=aersasi_2 POSE_GROUP=idle5 POSE_EXPECT='{"Param71":-0.5}' \
  POSE_URL=http://127.0.0.1:8778/gallery_v2/index.html py -3 scripts/diag/l2d_const_pose_verify.py
定值从哪来：源 bundle 的 m_ConstantClip.data 与 genericBindings 对位
  （见 docs/TROUBLESHOOTING.md §134 的探针方法），挑与默认 idle 不同的非零条目。
前置：8777 画廊服务器在跑（POSE_URL 可指向其它端口，如本项目画廊 8778）；
  会尝试禁开场 login（localStorage 被拒时自动退化
  为真实场景验证——开场 login → GROUP 的全链路，§133 竞态修复同场覆盖）。"""
import sys, os, json, time, subprocess, urllib.request
sys.stdout.reconfigure(encoding='utf-8')
SKIN = os.environ.get('POSE_SKIN', 'ougen_8')
GROUP = os.environ.get('POSE_GROUP', 'idle9')
_EXPECT_ENV = os.environ.get('POSE_EXPECT')
EXPECT = json.loads(_EXPECT_ENV) if _EXPECT_ENV else {
    'Param345': -1.280, 'Param372': -0.920, 'Param91': 1.0, 'Param97': 1.0,
    'Param352': 1.0, 'Param494': 1.0, 'Param500': 1.0, 'Param502': 1.0, 'Param506': 1.0}
POSE = list(EXPECT)
GALLERY_URL = os.environ.get('POSE_URL', 'http://127.0.0.1:8777/gallery_v2/index.html')
# 回零基准（可选）：'{"group":"idle","expect":{"ParamX":15.0}}'——切回组的磁盘 constant
# 定值表。给了就按数据闭环判定（baseline 是开场 login 混合态，不能当回零基准）；
# expect 里没列的参数 = 切回组无复位曲线（数据语义：保持，豁免判定）。
_BACK_ENV = os.environ.get('POSE_BACK')
BACK = json.loads(_BACK_ENV) if _BACK_ENV else None

import websocket

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
sys.path.insert(0, os.path.join(ROOT, 'scripts', 'diag'))
import cdp_slot
CHROME = r'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
PORT, PROFILE = cdp_slot.slot(ROOT, 'constverify')
try:
    with urllib.request.urlopen(GALLERY_URL, timeout=5) as r:
        assert r.status == 200
except Exception as e:
    raise SystemExit(f'! 服务器不可达: {e}')

proc = subprocess.Popen([CHROME, '--headless=new', f'--remote-debugging-port={PORT}',
  '--remote-allow-origins=*', f'--user-data-dir={PROFILE}', '--no-first-run',
  '--no-default-browser-check', '--disable-background-timer-throttling', '--enable-unsafe-swiftshader',
  '--use-angle=swiftshader', '--window-size=1280,900',
  GALLERY_URL], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
cmd('Page.navigate', {'url': GALLERY_URL})
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

def sample():
    return json.loads(ev(RD))

def settle(check, tries=12, interval=2.5, tag=''):
    """轮询采样直到收敛。headless 帧率低 + FadeInTime 长 → 固定 2.5s 常采到
    fade 混合中间态（实测 0.784 权重假阴性），必须等到参数停稳才算数。"""
    last = None
    for i in range(tries):
        time.sleep(interval)
        last = sample()
        if check(last):
            print(f'  settle[{tag}] 第 {i+1} 轮收敛')
            return last, True
    return last, False

want = lambda s: all(s.get(p) is not None and abs(s[p] - EXPECT[p]) < 0.02 for p in POSE)
s9, ok9 = settle(want, tag=GROUP)
print(f'{GROUP} 态:', json.dumps(s9, ensure_ascii=False))

print('\n姿势参数判定(换入后应为定值):')
allok = ok9
for p in POSE:
    got, want_ = s9.get(p), EXPECT[p]
    ok = got is not None and abs(got - want_) < 0.02
    print(f"  {p:<9} 期望 {want_:>7.3f} 实测 {got:>7} {'✓' if ok else '✗'}")

# 切回默认 idle,姿势钉子应被拔掉：参数回到 baseline 附近（默认 idle 自带微动的参数
# 不可能回数学 0，判据=相对 baseline 偏移 < 2.0，只排除「-45 定值残留」这种量级的钉子）
# 切回并按数据闭环验回零：姿势基态随组（不同 idle 变体 constant 定值不同），
# 判据 = 实测 ≈ 切回组的磁盘定值；无 POSE_BACK 时退化为 baseline 对比（弱判据）
if BACK:
    bg, bexp = BACK['group'], BACK['expect']
    ev(f"window.__l2play('{bg}')")
    s0, ok0 = settle(lambda s: all(
        s.get(p) is not None and abs(s[p] - v) < 0.02 for p, v in bexp.items()),
        tag=f'back:{bg}')
    backnote = '（对比切回组磁盘定值）'
else:
    bg = base.get('g') or 'idle'
    ev(f"window.__l2play('{bg}')")
    s0, ok0 = settle(lambda s: all(
        s.get(p) is not None and abs(s[p] - base.get(p, 0)) < 2.0 for p in POSE),
        tag='back')
    backnote = '（对比 baseline，弱判据）'
print(f'\n切回 {bg}:', json.dumps(s0, ensure_ascii=False))
backok = ok0
print('回零判定:', '✓ 精确回到切回组定值' if backok else '✗ 姿势钉子残留', backnote)
print('\n终判:', 'PASS' if (allok and backok) else 'FAIL')

try: cmd('Browser.close')
except Exception: pass
try: proc.wait(timeout=10)
except Exception: chrome_tree.kill_tree(proc.pid)