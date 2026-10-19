# -*- coding: utf-8 -*-
"""l2d_spine_dpr_verify.py — Live2D/Spine 画质（DPR 分辨率）验收探针（只读，不改产物）。

用无头 Chromium（优先 Chrome，缺则 Edge）真实加载画廊，逐皮肤断言渲染画布分辨率：
  Live2D : app.view buffer 尺寸应 = CSS 视口 × max(2, devicePixelRatio)
           —— 对应 index.html L1214 `resolution:Math.max(2,dpr)` + autoDensity:true
  Spine  : spcwrap canvas buffer 尺寸应 = CSS 尺寸 × devicePixelRatio
           —— 对应 index.html 的 resize()（2026-10-19 修：不能再调 scene.resize()，
              它会把 buffer 改回 CSS 尺寸；旧版探针只在 DPR=1 下跑，是假绿灯）
判据（不绕页面入口）：走搜索→点卡片→点皮肤→点 Live2D/Spine 标签的真实点击路径，再回读 canvas。

⚠️ DPR 必须显式抬高：无头默认 devicePixelRatio=1，此时 Spine 1x 也"达标"，
   永远抓不到"2x 屏上仍 1x"这个 bug。默认 --dpr 2，用 --dpr 1 可回到旧口径。

用法: PYTHONIOENCODING=utf-8 py -3 scripts/diag/l2d_spine_dpr_verify.py --only aersasi_2,yunlong_2 [--dpr 2]
输出: 逐皮肤 PASS|FAIL；退出码 0=全过 / 1=有失败 / 2=探针自身失败。
"""
import sys, os, json, time, subprocess, urllib.request
sys.stdout.reconfigure(encoding="utf-8")
import websocket

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CHROME_CANDIDATES = [
    r"C:/Program Files/Google/Chrome/Application/chrome.exe",
    r"C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%/Google/Chrome/Application/chrome.exe"),
    r"C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
    r"C:/Program Files/Microsoft/Edge/Application/msedge.exe",
]
CHROME = next((c for c in CHROME_CANDIDATES if os.path.isfile(c)), None)
PORT = 9351
SRV = 8777
URL = f"http://127.0.0.1:{SRV}/gallery_v2/index.html"
DEBUG = os.path.join(ROOT, ".diag", "chrome_dpr_verify")
DEFAULT = ["aersasi_2", "aersasi_3", "ougen_8", "yunlong_2"]


def arg(name, default=None, cast=str):
    return cast(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else default


only = [x for x in (arg("--only", "") or "").split(",") if x] or DEFAULT
DPR = arg("--dpr", 2, int)
if DPR < 1: raise SystemExit("--dpr 必须是 >=1 的整数")


def srv_alive():
    try:
        return urllib.request.urlopen(URL, timeout=2).status == 200
    except Exception:
        return False


def kill_stale(ud):
    ps = ("$ErrorActionPreference='SilentlyContinue';"
          "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe' OR Name='msedge.exe'\" | "
          "Where-Object { $_.CommandLine -like '*%s*' } | "
          "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" % ud)
    subprocess.run(["powershell.exe", "-NoProfile", "-Command", ps],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if not CHROME:
    raise SystemExit("未找到 Chrome/Edge，无法无头验证（先装其一）")
if not srv_alive():
    raise SystemExit("画廊服务器 8777 不可达——先跑 py -3 Output/gallery_v2/_gallery_server.py")

kill_stale(DEBUG)
os.makedirs(DEBUG, exist_ok=True)
proc = subprocess.Popen([CHROME, "--headless=new", f"--remote-debugging-port={PORT}",
                         "--remote-allow-origins=*", f"--user-data-dir={DEBUG}",
                         "--no-first-run", "--no-default-browser-check",
                         "--disable-background-timer-throttling",
                         "--enable-unsafe-swiftshader", "--use-angle=swiftshader",
                         "--force-device-scale-factor=%d" % DPR, "--window-size=1600,1100", URL],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

ws = None
for _ in range(80):
    try:
        tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json"))
        w = [t["webSocketDebuggerUrl"] for t in tabs
             if "gallery_v2" in t.get("url", "") and t.get("webSocketDebuggerUrl")]
        if w:
            ws = websocket.create_connection(w[0], timeout=90)
            break
    except Exception:
        pass
    time.sleep(0.5)
if not ws:
    raise SystemExit("CDP 连接失败")


def open_tab(ship_id, key, tab_kind):
    """真实点击路径打开指定皮肤并切入 Live2D/Spine 标签，返回 dict 或 error 字符串。"""
    js = r"""(async()=>{ try{
  const t=ms=>new Promise(r=>setTimeout(r,ms));
  const q=document.getElementById('search');
  q.value=%s; q.dispatchEvent(new Event('input',{bubbles:true})); await t(900);
  const card=[...document.querySelectorAll('.card')].find(c=>{const p=c.querySelector('.py');return p&&p.textContent.trim().startsWith(%s);});
  if(!card) return 'ERR:card-not-found'; card.click(); await t(700);
  const skin=document.querySelector('.skin[data-k="%s"]');
  if(!skin) return 'ERR:skin-not-found'; skin.click(); await t(700);
  const tb=[...document.querySelectorAll('#mTabs .tab')].find(x=>x.dataset.k==='%s');
  if(!tb||tb.classList.contains('dis')) return 'ERR:tab-disabled'; tb.click();
  if('%s'==='live2d'){ await t(6500);
    const app=l2State&&l2State.app; if(!app) return 'ERR:no-l2-app';
    const cv=app.view; const wrap=document.getElementById('l2wrap'); if(!cv) return 'ERR:no-l2-canvas';
    return {kind:'live2d', canvasW:cv.width, canvasH:cv.height,
            cssW:wrap.clientWidth, cssH:wrap.clientHeight, dpr:window.devicePixelRatio||1,
            model:!!(app.stage&&app.stage.children[0]), res:app.renderer&&app.renderer.resolution};
  } else { await t(4500);
    const wrap=document.getElementById('spcwrap'); if(!wrap) return 'ERR:no-sp-wrap';
    const cv=wrap.querySelector('canvas'); if(!cv) return 'ERR:no-sp-canvas';
    return {kind:'spine', canvasW:cv.width, canvasH:cv.height,
            cssW:cv.clientWidth, cssH:cv.clientHeight, dpr:window.devicePixelRatio||1};
  }
}catch(e){ return 'ERR:'+String(e&&e.message||e); } })()""" % (json.dumps(ship_id), json.dumps(ship_id), key, tab_kind, tab_kind)
    return ev(js)

def reload_page():
    """每个皮肤前重载页面并等 #search 出现，消除连续加载的状态残留（前一皮肤打开后 #search 可能不可见）。"""
    cmd("Page.navigate", {"url": URL})
    for _ in range(60):
        try:
            if ev("!!document.getElementById('search')"):
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def main():
    idx = json.load(open(os.path.join(ROOT, "Output", "gallery_v2", "index.json"), encoding="utf-8"))
    samples = []
    for s in idx["ships"]:
        for sk in s.get("skins", []):
            k = sk["key"]
            if k not in only:
                continue
            if sk.get("live2d"):
                samples.append((s["id"], k, "live2d"))
            elif sk.get("spine"):
                samples.append((s["id"], k, "spine"))
    got = {k for _, k, _ in samples}
    missing = [k for k in only if k not in got]
    if missing:
        print("未在索引找到指定皮肤:", missing, file=sys.stderr)

    fails = 0
    print("待测 %d 个皮肤（DPR 画质验收）：%s" % (len(samples), ", ".join(s for _, s, _ in samples)))
    for ship_id, key, kind in samples:
        if not reload_page():
            print("  %-12s %-6s  ERROR page-reload-failed" % (key, kind))
            fails += 1
            continue
        r = open_tab(ship_id, key, kind)
        if isinstance(r, str):
            print("  %-12s %-6s  ERROR %s" % (key, kind, r))
            fails += 1
            continue
        cw, ch = r["canvasW"], r["canvasH"]
        csw, csh = r["cssW"], r["cssH"] or 1
        dpr = r["dpr"]
        want = max(2, dpr) if kind == "live2d" else dpr
        ok_w = cw >= csw * want * 0.95
        ok_h = ch >= csh * want * 0.95
        if abs(dpr - DPR) > 0.01:
            print("  [WARN] 页面 dpr=%s 与 --dpr=%s 不一致（强制缩放未生效？）" % (dpr, DPR))
        if kind == "live2d" and not r.get("model"):
            ok_w = ok_h = False
        passed = ok_w and ok_h
        if not passed:
            fails += 1
        print("  %-12s %-6s  %4d x %4d   css %4d x %4d   ratio=%.2f   dpr=%s   want>=%.2f   %s"
              % (key, kind, cw, ch, csw, csh, (cw / csw if csw else 0), r["dpr"], want,
                 "PASS" if passed else "FAIL"))
    ws.close()
    proc.terminate()
    print("")
    print("结果: %s / 失败 %d" % ("PASS" if fails == 0 else "FAIL", fails))
    raise SystemExit(0 if fails == 0 else 1)


_id = 0


def cmd(m, p=None):
    global _id
    _id += 1
    ws.send(json.dumps({"id": _id, "method": m, "params": p or {}}))
    while True:
        r = json.loads(ws.recv())
        if r.get("id") == _id:
            if "error" in r:
                raise RuntimeError(json.dumps(r["error"])[:200])
            return r.get("result", {})


def ev(e, ap=True):
    r = cmd("Runtime.evaluate", {"expression": e, "returnByValue": True, "awaitPromise": ap})
    if r.get("exceptionDetails"):
        return "EVALERR " + str(r["exceptionDetails"].get("text"))[:200]
    return r.get("result", {}).get("value")


if __name__ == "__main__":
    main()