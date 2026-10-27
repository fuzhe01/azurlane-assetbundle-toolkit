# -*- coding: utf-8 -*-
"""无头 Chrome + CDP 对小批 Live2D 模型做**抖动/复位**目视取证。

走真画廊 index.html 的 renderLive2D（真入口，不是另写播放器）。每个模型：
  1. 打开 live2d 标签，等模型加载。
  2. 采样 ~8s：每 250ms 读一次 motionManager.state.currentGroup（真播放判据，§3.2）、
     全部核心参数当前值。
  3. 对每个参数算「振幅 = max-min」与「方向翻转次数」（相邻采样差值符号变化，
     单位时间多 = 高频抖动/振荡信号；振幅≈0 则不变）。
  4. 在 t≈0/2/4/6s 各裁一张模型画布截图供**目视**比对。

结论只能由人看截图 + 参数翻转统计共同给定；本探针只给证据，不判对错。

用法:
  py -3 scripts/diag/l2d_jitter_probe.py aersasi_2 ougen_8
前置: 服务器 127.0.0.1:8777 已起（根=Output/），Output/gallery_v2/index.html 已在。
输出: .diag/l2d_jitter/<key>_t<n>.png + 每模型一行统计
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
PORT = 9338
DEBUG_DIR = os.path.join(ROOT, '.diag', 'chrome_l2d_jitter')
SHOTS = os.path.join(ROOT, '.diag', 'l2d_jitter')
BASE = 'http://127.0.0.1:8777/gallery_v2/index.html'
SAMPLES = 34
DT = 0.25
SHOT_AT = (0, 2, 4, 6)
KEYS = [a for a in sys.argv[1:] if not a.startswith('--')]
os.makedirs(SHOTS, exist_ok=True)

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


ws = websocket.create_connection(wait_ws(), timeout=90)
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
        return 'EVALERR ' + str(ex.get('exception', {}).get('description') or ex.get('text'))[:200]
    res = r.get('result', {})
    return res.get('value')


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
      const cv=document.querySelector('#l2wrap canvas');
      const r=cv.getBoundingClientRect();
      const cm=m.internalModel.coreModel, pd=(cm._parameterIds||[]);
      return JSON.stringify({key:K, ok:true, drawables:m.internalModel.coreModel.getDrawableCount(),
         pidLen:pd.length, pidSample:pd.slice(0,3),
         clip:{x:Math.round(r.x),y:Math.round(r.y),w:Math.round(r.width),h:Math.round(r.height)}});
    } catch(e){ return JSON.stringify({key:__KEY__, fail:'JSERR '+(e&&e.message||String(e)).slice(0,150)}); }
    })()""".replace('__KEY__', json.dumps(key))
    return ev(js, awaitp=True)


def snapshot():
    """读 currentGroup + 全部参数值 -> json 字符串。"""
    return ev("""(async () => { try {
      const m=l2State&&l2State.app&&l2State.app.stage.children[0]; if(!m) return null;
      const mm=m.internalModel.motionManager, cm=m.internalModel.coreModel;
      const g=mm.state&&mm.state.currentGroup;
      const n=cm.getParameterCount();
      const v=[]; for(let i=0;i<n;i++) v.push(cm.getParameterValueByIndex(i));
      const names=[]; const ids=(cm._parameterIds||[]);
      for(let i=0;i<n;i++){ let nm='#'+i; try{ nm=(ids[i]!=null)?String(ids[i]):nm; }catch(e){}
        try{ if(nm==='#'+i&&cm.getParameterId) nm=String(cm.getParameterId(i)); }catch(e){}
        names.push(nm); }
      const dbg={idLen:(cm._parameterIds||[]).length, n404:(cm._parameterIds&&cm._parameterIds[404]!=null)?String(cm._parameterIds[404]):null};
      return JSON.stringify({g:g, n:n, v:v, names:names, dbg:dbg});
    } catch(e){ return null; } })()""", awaitp=True)


def shot(clip, name):
    if not clip:
        return
    d = cmd('Page.captureScreenshot', {'format': 'png', 'clip': {
        'x': clip['x'], 'y': clip['y'], 'width': clip['w'], 'height': clip['h'], 'scale': 1}})
    open(os.path.join(SHOTS, name), 'wb').write(base64.b64decode(d['data']))


def analyze(key, series):
    n = len(series[0]['v'])
    names = series[0].get('names') or []
    amps = []
    flips = []
    for i in range(n):
        vals = [s['v'][i] for s in series]
        amp = max(vals) - min(vals)
        f = sum(1 for k in range(2, len(vals))
                if (vals[k] - vals[k-1]) * (vals[k-1] - vals[k-2]) < 0 and
                   abs(vals[k] - vals[k-1]) > 1e-6 and abs(vals[k-1] - vals[k-2]) > 1e-6)
        amps.append(amp)
        flips.append(f)
    moving = [i for i in range(n) if amps[i] > 1e-4]
    flips_m = [flips[i] for i in moving]
    avg = (sum(flips_m) / len(flips_m)) if flips_m else 0
    groups = sorted({s['g'] for s in series})
    print(f"[{key}] params={n} moving={len(moving)} | "
          f"avgDirFlips(moving)={avg:.2f} maxFlips={max(flips_m or [0])} | groups={groups}")
    peak = sorted(((flips[i], amps[i], i) for i in moving), reverse=True)[:8]
    for f, a, i in peak:
        nm = names[i] if i < len(names) else '#%d' % i
        wave = ' '.join('%5.2f' % s['v'][i] for s in series)
        print(f"      #{i} {nm}  dirFlips={f} amp={a:.3f}\n         {wave}")


try:
    cmd('Page.enable')
    for _ in range(180):
        if ev('String(typeof GALLERY!=="undefined"&&Array.isArray(GALLERY.ships)&&GALLERY.ships.length>0)') == 'true':
            break
        time.sleep(1.0)
    for key in KEYS:
        r = json.loads(open_view(key))
        if not r.get('ok'):
            print(json.dumps(r, ensure_ascii=False))
            continue
        print(json.dumps({'key': key, 'drawables': r.get('drawables'),
                          'pidLen': r.get('pidLen'), 'pidSample': r.get('pidSample')}, ensure_ascii=False))
        clip = r['clip']
        series = []
        for k in range(SAMPLES):
            s = snapshot()
            if s:
                try:
                    j = json.loads(s)
                    if j:
                        series.append({'t': k * DT, 'g': j.get('g'), 'v': j.get('v'),
                                       'names': j.get('names') or [], 'dbg': j.get('dbg')})
                except Exception:
                    pass
            for at in SHOT_AT:
                if abs(k * DT - at) < DT / 2:
                    shot(clip, f'{key}_t{int(at)}.png')
            time.sleep(DT)
        if series:
            print(f"  [dbg] idLen={series[0].get('dbg',{}).get('idLen')} "
                  f"n404={series[0].get('dbg',{}).get('n404')} "
                  f"names[:5]={series[0].get('names',[])[:5]}")
            analyze(key, series)
        else:
            print(f"[{key}] 无参数采样（模型未就绪）")
finally:
    ws.close()
    proc.terminate()
print('截图目录:', SHOTS)
