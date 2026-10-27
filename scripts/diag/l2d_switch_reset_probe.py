# -*- coding: utf-8 -*-
"""无头 Chrome + CDP 验证画廊「切动作轴」的参数残留复位（前端预留复位，非常量曲线）。

测的是 gallery_src/index.html 内 renderLive2D 的 restTick（§1342~1365）：非 idle 动作播/切
回 idle 时，把「该 clip 驱动、而 idle 不驱动」的参数在 REST_DELAY(400ms)+REST_MS(700ms) 内
线性回落到 moc3 默认值。

== 关键：必须走画廊真入口 `play()`（下拉框 #l2Motion dispatch change），不能直接调
   startMotion —— play() 才把组登记进 restTick 的 `played` 集，复位才触发 ==

每模型（离线先算）:
  idleSet   = idle.motion3.json 的 Parameter Id 集
  driveSet  = 驱动组 motion3.json 的 Parameter Id 集
  residual  = driveSet - idleSet  (复位候选)
流程（浏览器）:
  1. open_view 载入模型。
  2. 记录每个 residual 参数的 当前值(=idle 基线) 与 getParameterDefaultValue。
  3. 下拉框 → 驱动组 (dispatch change) → 采样 ~2.5s（参数应偏离默认）。
  4. 下拉框 → idle 组 (dispatch change) → 采样 ~4s（观测 400+700ms 复位渐变）。
判定: 每个 residual 参数 复位末值 |Δdefault| 小(=复位成功) 或 大(=残留/未复位)。

用法:
  py -3 scripts/diag/l2d_switch_reset_probe.py aersasi_2 ougen_8
前置: 服务器 127.0.0.1:8777 已起（根=Output/），Output/gallery_v2/index.html 已在。
输出: 每模型逐参数 默认值/基线/驱动段最大偏离/复位末偏离 + 统计复位成功数。
"""
import sys, os, json, time, base64, subprocess, urllib.request

sys.stdout.reconfigure(encoding='utf-8')
import websocket

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import paths as _paths
import chrome_tree        # 整树清理：atexit + profile 回读（见该模块 docstring）
_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (_HERE, os.path.join(_HERE, '..')):
    _p = os.path.abspath(_p)
    if _p not in sys.path: sys.path.insert(0, _p)

CHROME = (_paths.CHROME or r'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe')
PORT = 9339
DEBUG_DIR = os.path.join(ROOT, '.diag', 'chrome_l2d_switch')
BASE = 'http://127.0.0.1:8777/gallery_v2/index.html'
MOTION_DIR = os.path.join(ROOT, 'Output', 'Live2D')
DEFAULT_DRIVE = ['touch_body', 'touch_head', 'touch_idle1', 'main_1', 'main_2']
KEYS = [a for a in sys.argv[1:] if not a.startswith('--')]
WAVE = None
for a in sys.argv[1:]:
    if a.startswith('--wave='):
        WAVE = a.split('=', 1)[1]
DT = 0.25


def param_set(model, grp):
    f = os.path.join(MOTION_DIR, model, 'motion', grp + '.motion3.json')
    if not os.path.exists(f):
        return None
    j = json.load(open(f, encoding='utf-8'))
    out = set()
    for c in j.get('Curves', []):
        if c.get('Target') == 'Parameter':
            i = c.get('Id')
            out.add(i if isinstance(i, str) else (i.get('string') if isinstance(i, dict) else i))
    return out


def choose(model):
    base_idle = param_set(model, 'idle') or set()
    cands = []
    for g in DEFAULT_DRIVE:
        s = param_set(model, g)
        if s:
            cands.append((g, s))
    if not cands:
        return None, None, None
    best = max(cands, key=lambda gs: len(gs[1] - base_idle))
    g, s = best
    return g, sorted(s - base_idle), None


proc = subprocess.Popen([CHROME, '--headless=new', f'--remote-debugging-port={PORT}',
    '--remote-allow-origins=*', f'--user-data-dir={DEBUG_DIR}', '--no-first-run',
    '--no-default-browser-check', '--disable-background-timer-throttling',
    '--enable-unsafe-swiftshader', '--use-angle=swiftshader', '--window-size=1400,1000', BASE],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


proc = chrome_tree.install(proc)


def wait_ws():
    for _ in range(80):
        try:
            for t in json.load(urllib.request.urlopen(f'http://127.0.0.1:{PORT}/json')):
                if 'gallery_v2' in t.get('url', '') and t.get('webSocketDebuggerUrl'):
                    return t['webSocketDebuggerUrl']
        except Exception:
            pass
        time.sleep(0.5)
    raise RuntimeError('CDP 未就绪')


ws = websocket.create_connection(wait_ws(), timeout=120)
_id = 0


def cmd(method, params=None):
    global _id
    _id += 1
    ws.send(json.dumps({'id': _id, 'method': method, 'params': params or {}}))
    while True:
        m = json.loads(ws.recv())
        if m.get('id') == _id:
            if 'error' in m:
                raise RuntimeError(json.dumps(m['error'])[:200])
            return m.get('result', {})


def ev(expr, awaitp=False):
    r = cmd('Runtime.evaluate', {'expression': expr, 'returnByValue': True, 'awaitPromise': awaitp})
    if r.get('exceptionDetails'):
        ex = r['exceptionDetails']
        return 'EVALERR ' + str(ex.get('exception', {}).get('description') or ex.get('text'))[:250]
    return r.get('result', {}).get('value')


def open_view(key):
    js = """(async () => { try {
      const t=ms=>new Promise(r=>setTimeout(r,ms)), K=__KEY__;
      let ship=null, sk=null;
      for (const s of GALLERY.ships) { const k=s.skins.find(x=>x.key===K);
        if(!k||!(s.live2dSkins||[]).includes(K)) continue; ship=s; sk=k; break; }
      if(!sk) return JSON.stringify({key:K, skip:'index 无此 Live2D 皮肤'});
      openShip(ship); setSkin(sk); buildSkinList(ship); tab='live2d'; renderView();
      await t(9000);
      const m=l2State&&l2State.app&&l2State.app.stage.children[0];
      if(!m) return JSON.stringify({key:K, fail:'no model',
         note:((document.querySelector('.note')||{}).textContent||'')});
      const cm=m.internalModel.coreModel, mm=m.internalModel.motionManager;
      window.__L2_CM=cm; window.__L2_MM=mm;
      return JSON.stringify({key:K, ok:true,
        groups:Object.keys((mm.definitions)||{}),
        idleGroup:mm.groups.idle||null,
        pidLen:(cm._parameterIds||[]).length});
    } catch(e){ return JSON.stringify({key:__KEY__, fail:'JSERR '+(e&&e.message||String(e)).slice(0,150)}); }
    })()""".replace('__KEY__', json.dumps(key))
    return ev(js, awaitp=True)


def run_switch(key, drive, idle_group, res_names):
    res_json = json.dumps(res_names)
    js = """(async () => { try {
      const cm=window.__L2_CM; if(!cm) return JSON.stringify({fail:'no cm'});
      const mm=window.__L2_MM; if(!mm) return JSON.stringify({fail:'no mm'});
      const t=ms=>new Promise(r=>setTimeout(r,ms));
      const names=cm._parameterIds||[];
      const idxOf=n=>names.indexOf(n);
      const res=[];
      for(const n of RES) { const i=idxOf(n); if(i>=0) res.push({n, i, d:+cm.getParameterDefaultValue(i).toFixed(3)}); }
      if(!res.length) return JSON.stringify({fail:'residual 未命中任何参数', names_to_check:RES});
      const sel=document.getElementById('l2Motion'); if(!sel) return JSON.stringify({fail:'no #l2Motion'});
      const groups=[...(sel.options||[])].map(o=>o.value);
      const pick=g=>{ sel.value=g; sel.dispatchEvent(new Event('change')); };
      const samp=()=>{ const row=[+performance.now()]; for(const r of res) row.push(+cm.getParameterValueByIndex(r.i).toFixed(3)); row.push((mm.state&&mm.state.currentGroup)||null); return row; };
      const scan=()=>{ const a=[]; for(let i=0;i<names.length;i++) a.push(+cm.getParameterValueByIndex(i).toFixed(3)); return a; };
      const samples=[{ph:'base', v:samp()}];
      const all0=scan();
      // 切到驱动组，等一拍让 startMotion 生效
      pick(DRIVE);
      await t(700);
      for(let k=0;k<32;k++){ await t(DT); samples.push({ph:'drive', v:samp()}); }
      const all1=scan();
      // 切回 idle → 触发前端复位
      pick(IDLE);
      for(let k=0;k<26;k++){ await t(DT); samples.push({ph:'idle', v:samp()}); }
      const all2=scan();
      const nMovingIdle=[]; for(let i=0;i<names.length;i++) if(all1[i]!=null&&all2[i]!=null&&Math.abs(all2[i]-all1[i])>1e-3) nMovingIdle.push([names[i],all1[i],all2[i]]);
      const nMoving=[]; for(let i=0;i<names.length;i++) if(all0[i]!=null&&all1[i]!=null&&Math.abs(all1[i]-all0[i])>1e-3) nMoving.push([names[i], all0[i], all1[i]]);
      const nMovingResid=res.filter(r=>Math.abs(all1[r.i]-all0[r.i])>1e-3).length;
      return JSON.stringify({key:K, groups:groups, hasDrive:groups.includes(DRIVE),
        nMovingTotal:nMoving.length, nMovingResid:nMovingResid, nMovingIdle:nMovingIdle.length, topMoving:(nMoving||[]).slice(0,8),
        res:res.map(r=>({name:r.n, idx:r.i, def:r.d})), samples:samples});
    } catch(e){ return JSON.stringify({fail:'JSERR '+(e&&e.message||String(e)).slice(0,250)}); }
    })()""".replace('RES', res_json).replace('DRIVE', json.dumps(drive)).replace(
        'IDLE', json.dumps(idle_group)).replace('K', json.dumps(key)).replace('DT', str(DT))
    return ev(js, awaitp=True)


for key in KEYS:
    r = json.loads(open_view(key))
    if r.get('skip'):
        print(f"[{key}] SKIP {r['skip']}")
        continue
    if not r.get('ok'):
        print(f"[{key}] FAIL {json.dumps(r)}")
        continue
    drive, res_names, _ = choose(key)
    if not drive:
        print(f"[{key}] 无可选驱动组")
        continue
    idle_group = r.get('idleGroup') or 'idle'
    print(f"[{key}] drive={drive} idle={idle_group} residual={len(res_names)}")
    out = json.loads(run_switch(key, drive, idle_group, res_names))
    if out.get('fail'):
        print(f"   RESULT-FAIL {out['fail']}")
        continue
    res = out['res']
    samples = out['samples']
    base = next(s['v'] for s in samples if s['ph'] == 'base')
    drive_s = [s['v'] for s in samples if s['ph'] == 'drive']
    idle_s = [s['v'] for s in samples if s['ph'] == 'idle']
    cgs = [s['v'][-1] for s in samples]
    print(f"   采样: base={len(base)} drive={len(drive_s)} idle={len(idle_s)}")
    print(f"   groups={len(out.get('groups') or [])} hasDrive={out.get('hasDrive')} "
          f"nMovingTotal={out.get('nMovingTotal')} nMovingResid={out.get('nMovingResid')} "
          f"nMovingIdle={out.get('nMovingIdle')}")
    print(f"   cg轨迹: {cgs}")
    top = out.get('topMoving') or []
    if top:
        print("   topMoving(base->end): " + ' '.join(f"{nm}:{b0}->{b1}" for nm, b0, b1 in top[:8]))
    ok = 0
    tested = 0
    stuck = []
    for j, rp in enumerate(res):
        d = rp['def']
        b0 = base[j + 1] if len(base) > j + 1 else None
        dvmax = max((abs(s[j + 1] - d) for s in drive_s), default=0)
        last = idle_s[-1][j + 1] if idle_s else None
        dev = abs(last - d) if last is not None else None
        if dvmax < 0.05:
            print(f"   {rp['name']:<28} def={d:7.3f} (未动,不计)")
            continue
        tested += 1
        if dev is not None and dev < 0.05:
            ok += 1
            stat = 'RESET-OK'
        else:
            stat = 'RESIDUAL-STUCK'
            stuck.append((rp['name'], round(dvmax, 3), None if dev is None else round(dev, 3)))
        print(f"   {rp['name']:<28} def={d:7.3f} driveMaxDev={dvmax:6.3f} "
              f"idleEndDev={'' if dev is None else round(dev,3)}  {stat}")
    print(f"   => 驱动动过的 {tested} 个中复位成功 {ok} | "
          f"残余未复位 {len(stuck)}: {stuck}")
    if WAVE:
        wi = next((i for i, r in enumerate(res) if r['name'] == WAVE), None)
        if wi is not None:
            print(f"   [wave {WAVE}] base={base[wi+1] if len(base)>wi+1 else '?'}")
            print(f"      drive→" + ' '.join(f"{s[wi+1]}" for s in drive_s))
            print(f"      idle→" + ' '.join(f"{s[wi+1]}" for s in idle_s))
print("完成")
