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
  if(forceEnd && started===action){
    // 先走库自己的 complete()（自然播完也是这条）：它把 currentPriority 归零，
    // 之后 startRandomMotion 才能正常 reserve；只 stopAllMotions 会留下优先级，造成偶发假 FAIL。
    try{ if(mm.state&&mm.state.complete) mm.state.complete(); }catch(e){}
    try{ mm.queueManager.stopAllMotions(); }catch(e){} }
  // 等回落（currentGroup===expected），最多 15s
  tm=performance.now();
  while(performance.now()-tm<15000){ await t(400); if(mm.state.currentGroup===expected) break; }
  const got=mm.state.currentGroup;
  const curr=(()=>{ const h=document.getElementById('l2Curr'); return h?h.textContent:null; })();
  const prio=(mm.state&&typeof mm.state.currentPriority!=='undefined')?mm.state.currentPriority:null;
  return JSON.stringify({key, action, expected, init, started, got, curr, prio, forceEnd, patched,
    pass:(got===expected && (started===action || init===expected))});
})"""

cases = [
  ('aersasi_2', 'touch_idle1',  None, True),    # touch_idle*：best 与默认差距 <15% → 回默认（两者都是 idle）
  ('aersasi_2', 'touch_body',   None, True),    # best 就是默认 idle
  ('aersasi_2', 'touch_head',   None, True),    # ⚠️ 2026-10-19 新语义：best=idle5 只比 idle 好 2% → 回默认 idle
  ('aersasi_2', 'home',         None, True),    # home 场景 → 按同一闸门判定（回归：不得被当循环待机）
  ('ougen_8',   'main_1',       None, True),    # main_* 场景 → 按同一闸门判定
  ('aersasi_3', 'touch_head',   None, True),    # best=idle1 与 idle 打平 → 默认 idle
  ('aersasi_3', 'touch_idle2',  None, True),    # best=idle2 好 6 倍 → 必须走变体
  ('aersasi_2', 'touch_idle2',  None, True),    # ⚠️ 2026-10-19 新语义：best=idle5 只差 8%，touch_idle 仍必须走 best
  ('aersasi_3', 'touch_idle31', None, True),    # best=idle1 与 idle 打平，touch_idle 仍必须走 best
  ('aersasi_3', 'touch_drag1',  'touch_drag1', True),  # drag 循环 → 回落自身
  ('jianye_4',  'mail',         None, True),    # best=idle3（norm 0.01 vs 默认 idle 8866）→ 必须走变体
  ('z46_4',     'mission',      None, True),    # fallback=true（无候选）→ 默认 idle
]
CHAIN = json.load(open(os.path.join(ROOT, 'Output', 'gallery_v2', 'motion_chain.json'), encoding='utf-8')) \
  .get('models', {})
# 抽查：几类不同 idle 组织的代表性模型（编号多变体 / 仅1组 fallback），自动选取 action
#   · 所有非 drag 组 → expected 用 None，由 expected_for() 按前端同一套闸门算
#   · drag → expected 自身（循环）
for m in ['zhangwu_2', 'zhenzhuhao_2', 'z46_4']:
    c = CHAIN.get(m, {}).get('chain', {})
    if not c:
        continue
    tids = [a for a in c if a.startswith('touch_idle')]
    longs = [a for a in c if not a.startswith('touch_') and not a.startswith('idle')]
    drags = [a for a in c if 'drag' in a]
    if tids: cases.append((m, tids[0], None, True))
    if longs: cases.append((m, longs[0], None, True))
    if drags: cases.append((m, drags[0], drags[0], True))
def _groups(key):
    p = os.path.join(ROOT, 'Output', 'Live2D', key, key + '.model3.json')
    try:
        j = json.load(open(p, encoding='utf-8'))
        return list(((j.get('FileReferences') or {}).get('Motions') or {}).keys())
    except Exception:
        return []

def _default_idle(key):
    gs = _groups(key)
    for g in ('idle', 'main', 'home'):
        if g in gs:
            return g
    return gs[0] if gs else 'idle'

def expected_for(key, action):
    """复刻前端 _pickFallback 的闸门（只读表 + model3 组清单），返回 (组, 理由)。"""
    ig = _default_idle(key)
    c = ((CHAIN.get(key) or {}).get('chain') or {}).get(action)
    if not c or c.get('fallback'):
        return ig, 'no-entry/fallback'
    b = c.get('best')
    if not b or b not in _groups(key):
        return ig, 'best-missing'
    nb = c.get('best_norm')
    if nb is None:
        return ig, 'no-norm'
    if action.startswith('touch_idle'):
        return b, 'best(touch_idle always)=%s' % b
    nd = next((r.get('norm') for r in (c.get('runners_up') or []) if r.get('group') == ig), None)
    if nd is not None and nd > 0 and nb > nd * 0.85:
        return ig, 'marginal(best=%s %.0f%% better)' % (b, (nd / nb - 1) * 100 if nb else 0)
    return b, 'best=%s' % b

all_pass = True
# warmup：预取 motion_chain（浏览器缓存）+ 预载首模型，消除首 case 冷启时序
try: ev("fetch('./motion_chain.json').then(r=>r.ok?'ok':('http'+r.status)).catch(e=>'err'+String(e))")
except Exception as e: print('warmup fetch 异常', e)
try:
    d = ev(JS + "(['aersasi_2','idle','idle',true])")
except Exception as e: print('warmup 渲染 异常', e)
for key, action, expected, forceEnd in cases:
    if expected is None:
        expected, why = expected_for(key, action)
    else:
        why = 'self-loop'
    c = (key, action, expected, forceEnd)
    raw = ev(JS + f"({json.dumps(list(c))})")
    try:
        o = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        o = {'raw': raw}
    ok = o.get('pass', False)
    all_pass = all_pass and ok
    flag = 'PASS' if ok else 'FAIL'
    print(f'[{flag}] {c[0]:12} {c[1]:14} -> 期望 {c[2]:8}  实际 {o.get("got")!r:8}  init={o.get("init")!r} started={o.get("started")!r}  currLabel={o.get("curr")!r}  [{why}] {o.get("skip","") if o.get("skip") else ""}')
    if not ok and 'skip' not in o:
        print('     ', json.dumps(o, ensure_ascii=False)[:400])

print('\n==== 汇总 ====')
print('全部通过' if all_pass else '存在失败')
ws.close(); proc.terminate()
sys.exit(0 if all_pass else 1)