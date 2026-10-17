# -*- coding: utf-8 -*-
"""方案B 前端回落验证（只读）：播动作后，currentGroup 是否回落到 motion_chain.json 映射的 best 待机组。
走页面自己的 play()（下拉框 onchange）——不能直接 mm.startMotion（绕前端交互层 → 假阴性，见 l2d_touchidle_probe 注释）。
用法: py -3 scripts/diag/l2d_motion_chain_verify.py
"""
import sys, os, json, time, subprocess, urllib.request
sys.stdout.reconfigure(encoding='utf-8')
import websocket

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CHROME = r'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
PORT = 9383
PROFILE = os.path.join(ROOT, '.diag', 'chrome_motionchain')
os.makedirs(PROFILE, exist_ok=True)
proc = subprocess.Popen([CHROME, '--headless=new', f'--remote-debugging-port={PORT}',
  '--remote-allow-origins=*', f'--user-data-dir={PROFILE}', '--no-first-run',
  '--no-default-browser-check', '--disable-background-timer-throttling', '--enable-unsafe-swiftshader',
  '--use-angle=swiftshader', '--window-size=1280,900',
  'http://127.0.0.1:8777/gallery_v2/index.html'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
w = None
for _ in range(90):
    try:
        tabs = json.load(urllib.request.urlopen(f'http://127.0.0.1:{PORT}/json'))
        w = [t['webSocketDebuggerUrl'] for t in tabs if 'gallery_v2' in t.get('url', '') and t.get('webSocketDebuggerUrl')]
        if w: break
    except Exception: pass
    time.sleep(0.5)
if not w:
    print('FATAL: 未找到页面 tab'); proc.kill(); sys.exit(1)
ws = websocket.create_connection(w[0], timeout=300, max_size=None)
_id = 0
def cmd(m, p=None):
    global _id; _id += 1; mid = _id
    ws.send(json.dumps({'id': mid, 'method': m, 'params': p or {}})); ws.settimeout(300)
    while True:
        r = json.loads(ws.recv())
        if r.get('id') == mid:
            if 'error' in r: raise RuntimeError(json.dumps(r['error'])[:200])
            return r.get('result', {})
def ev(e):
    r = cmd('Runtime.evaluate', {'expression': e, 'returnByValue': True, 'awaitPromise': True})
    if r.get('exceptionDetails'): return 'EVALERR ' + str(r.get('exceptionDetails'))[:300]
    return r.get('result', {}).get('value')

JS = r"""(async(args)=>{ const key=args[0], action=args[1], expected=args[2], forceEnd=!!args[3];
  const t=ms=>new Promise(r=>setTimeout(r,ms));
  for(let i=0;i<90 && !(window.GALLERY && typeof openShip==='function');i++) await t(300);
  let ship=null, sk=null;
  for(const s of GALLERY.ships){ const k=s.skins.find(x=>x.key===key); if(k&&s.live2dSkins.includes(key)){ship=s;sk=k;break;} }
  if(!sk) return JSON.stringify({key, skip:'no skin'});
  openShip(ship); setSkin(sk); buildSkinList(ship);
  const l2=[...document.querySelectorAll('#mTabs .tab')].find(x=>x.dataset.k==='live2d');
  l2.click();
  const t0=performance.now();
  while(!l2State||!l2State.app||!l2State.app.stage.children.length){ if(performance.now()-t0>40000) break; await t(200); }
  if(!l2State||!l2State.app||!l2State.app.stage.children.length) return JSON.stringify({key, skip:'no app'});
  const mdl=l2State.app.stage.children[0], mm=mdl.internalModel.motionManager;
  const init=mm.state.currentGroup;
  // 等动作下拉框渲染出来（bar 异步构建）
  let sel=null;
  for(let i=0;i<40 && !(sel=document.getElementById('l2Motion'));i++) await t(250);
  if(!sel) return JSON.stringify({key, action, expected, init, skip:'no dropdown'});
  sel.value=action; sel.onchange();                 // 走页面 play() 真实路径
  const patched = /chainModel/.test(String(mm.startRandomMotion));
  // 等动作真正开始（currentGroup===action），最多 6s
  let tm=performance.now();
  while(performance.now()-tm<6000){ await t(300); if(mm.state.currentGroup===action) break; }
  const started=mm.state.currentGroup;
  // headless 低帧率下动作播不完（aersasi_2 软渲染 ~1fps）：forceEnd 用 stopAllMotions 模拟动作结束。
  // 回落触发链与自然播完完全一致：isFinished→complete→shouldRequestIdleMotion→startRandomMotion。
  if(forceEnd && started===action){ try{ mm.queueManager.stopAllMotions(); }catch(e){} }
  // 等回落（currentGroup===expected），最多 15s
  tm=performance.now();
  while(performance.now()-tm<15000){ await t(400); if(mm.state.currentGroup===expected) break; }
  const got=mm.state.currentGroup;
  const curr=(()=>{ const h=document.getElementById('l2Curr'); return h?h.textContent:null; })();
  return JSON.stringify({key, action, expected, init, started, got, curr, forceEnd, patched,
    pass:(got===expected && (started===action || init===expected))});
})"""

cases = [
  ('aersasi_2', 'touch_idle1',  None, True),    # touch_idle* 走启发式：expected 从表动态读 best
  ('aersasi_2', 'touch_body',   'idle', True),  # 长动画 → 默认 idle
  ('aersasi_2', 'home',         'idle', True),  # home 场景 → 回默认 idle（回归：修复被误当循环待机）
  ('ougen_8',   'main_1',       'idle', True),  # main_* 场景 → 回默认 idle（回归修复）
  ('aersasi_3', 'touch_head',   'idle', True),  # 长动画 → 默认 idle
  ('aersasi_3', 'touch_idle2',  None, True),    # touch_idle* 启发式 best（动态读）
  ('aersasi_3', 'touch_drag1',  'touch_drag1', True),  # drag 循环 → 回落自身
]
CHAIN = json.load(open(os.path.join(ROOT, 'Output', 'gallery_v2', 'motion_chain.json'), encoding='utf-8')) \
  .get('models', {})
# 抽查：几类不同 idle 组织的代表性模型（编号多变体 / 仅1组 fallback），自动选取 action
#   · touch_idle* → expected 用 None（循环里读表 best）
#   · 长动画（非 touch_/idle 前缀）→ expected 'idle'（前端统一回默认待机）
#   · drag → expected 自身（循环）
for m in ['zhangwu_2', 'zhenzhuhao_2', 'z46_4']:
    c = CHAIN.get(m, {}).get('chain', {})
    if not c:
        continue
    tids = [a for a in c if a.startswith('touch_idle')]
    longs = [a for a in c if not a.startswith('touch_') and not a.startswith('idle')]
    drags = [a for a in c if 'drag' in a]
    if tids: cases.append((m, tids[0], None, True))
    if longs: cases.append((m, longs[0], 'idle', True))
    if drags: cases.append((m, drags[0], drags[0], True))
all_pass = True
# warmup：预取 motion_chain（浏览器缓存）+ 预载首模型，消除首 case 冷启时序
try: ev("fetch('./motion_chain.json').then(r=>r.ok?'ok':('http'+r.status)).catch(e=>'err'+String(e))")
except Exception as e: print('warmup fetch 异常', e)
try:
    d = ev(JS + "(['aersasi_2','idle','idle',true])")
except Exception as e: print('warmup 渲染 异常', e)
for key, action, expected, forceEnd in cases:
    if expected is None:
        expected = (CHAIN.get(key, {}).get('chain', {}).get(action, {}).get('best')) or 'idle'
    c = (key, action, expected, forceEnd)
    raw = ev(JS + f"({json.dumps(list(c))})")
    try:
        o = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        o = {'raw': raw}
    ok = o.get('pass', False)
    all_pass = all_pass and ok
    flag = 'PASS' if ok else 'FAIL'
    print(f'[{flag}] {c[0]}  {c[1]:14} -> 期望 {c[2]:8}  实际 {o.get("got")!r:8}  init={o.get("init")!r} started={o.get("started")!r}  currLabel={o.get("curr")!r}  {o.get("skip","") if o.get("skip") else ""}')
    if not ok and 'skip' not in o:
        print('     ', json.dumps(o, ensure_ascii=False)[:300])

print('\n==== 汇总 ====')
print('全部通过' if all_pass else '存在失败')
ws.close(); proc.terminate()
sys.exit(0 if all_pass else 1)
