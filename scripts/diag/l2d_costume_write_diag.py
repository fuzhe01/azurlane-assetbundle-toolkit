# -*- coding: utf-8 -*-
"""l2d_costume_write_diag.py — 诊断「点了换装按钮但参数值不保持」的确切原因。

按时间顺序取证（每一步都回读真实值）：
  T1 点击后立即读
  T2 等 100ms 再读（看是否被 ticker/动作覆盖）
  T3 直接 core.setParameterValueById 写，立即读（确认 API 本身可用）
  T4 写后等 300ms 再读（确认是否被 loadParameters 拉回）
  T5 关掉动作（stopAllMotions）后写，再读
输出每一环的值，定位"谁把它改回去了"。

用法: py -3.14 scripts/diag/l2d_costume_write_diag.py --ship benningdun_2 --param GloveSwitch_L
"""
import sys, os, json, time, subprocess, urllib.request

sys.stdout.reconfigure(encoding="utf-8")
import websocket
import chrome_tree        # 整树清理：atexit + profile 回读（见该模块 docstring）
_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (_HERE, os.path.join(_HERE, '..')):
    _p = os.path.abspath(_p)
    if _p not in sys.path: sys.path.insert(0, _p)


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CAND = [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"]
BROWSER = next((c for c in CAND if os.path.isfile(c)), None)
PORT = int(os.environ.get("COSDIAG_PORT", "9373"))
SRV = "8778"
PROFILE = os.path.join(ROOT, ".diag", f"chrome_cosdiag_{PORT}")


def arg(n, d=None):
    return sys.argv[sys.argv.index(n) + 1] if n in sys.argv else d


SHIP = arg("--ship", "benningdun_2")
PARAM = arg("--param", "GloveSwitch_L")
URL = f"http://127.0.0.1:{SRV}/gallery_v2/index.html"


def main():
    ps = ("$ErrorActionPreference='SilentlyContinue';"
          "Get-CimInstance Win32_Process -Filter \"Name='msedge.exe'\" | "
          "Where-Object { $_.CommandLine -like '*%s*' } | "
          "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" % PROFILE)
    subprocess.run(["powershell.exe", "-NoProfile", "-Command", ps],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.6)
    proc = chrome_tree.launch([
        BROWSER, f"--remote-debugging-port={PORT}", "--remote-allow-origins=*",
        f"--user-data-dir={PROFILE}", "--no-first-run", "--no-default-browser-check",
        "--headless=new", "--gpu", "--window-size=1400,950",
        f"{URL}?ship={SHIP}&_t={int(time.time()*1000)}"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ws = None
    for _ in range(120):
        try:
            for t in json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json")):
                if "gallery_v2" in t.get("url", "") and t.get("webSocketDebuggerUrl"):
                    ws = websocket.create_connection(t["webSocketDebuggerUrl"], timeout=90)
                    break
            if ws:
                break
        except Exception:
            pass
        time.sleep(0.5)
    if not ws:
        proc.terminate()
        raise SystemExit("CDP 失败")

    _id = 0

    def cmd(m, p=None):
        nonlocal _id
        _id += 1
        ws.send(json.dumps({"id": _id, "method": m, "params": p or {}}))
        while True:
            r = json.loads(ws.recv())
            if r.get("id") == _id:
                if "error" in r:
                    raise RuntimeError(str(r["error"])[:200])
                return r.get("result", {})

    def ev(e, ap=True):
        r = cmd("Runtime.evaluate", {"expression": e, "returnByValue": True, "awaitPromise": ap})
        if r.get("exceptionDetails"):
            return "EVALERR " + str(r["exceptionDetails"].get("text"))[:200]
        return r.get("result", {}).get("value")

    cmd("Page.enable")
    cmd("Runtime.enable")
    cmd("Network.enable")
    cmd("Network.setCacheDisabled", {"cacheDisabled": True})

    for _ in range(120):
        if ev("(typeof l2State!=='undefined'&&l2State&&l2State.app&&"
              "l2State.app.stage.children[0]&&l2State.app.stage.children[0].internalModel)?1:0",
              ap=False) == 1:
            break
        time.sleep(0.5)

    CORE = ("l2State.app.stage.children[0].internalModel.coreModel")
    # ⚠️ 读回前必须 core.update()：Cubism 参数写入先进待应用队列，
    # 不 update 就读到旧值（2026-10-23：这会让"可写"被误判成"不可写"）。
    def upd():
        ev(f"(()=>{{ try{{ {CORE}.update(); }}catch(e){{}} "
           f"try{{ l2State.app.renderer.render(l2State.app.stage); }}catch(e){{}} return 1; }})()", ap=False)
        time.sleep(0.06)

    READ = f"(()=>{{ try{{ return +{CORE}.getParameterValueById({json.dumps(PARAM)}); }}catch(e){{ return 'ERR'; }} }})()"

    print(f"目标参数 {PARAM} @ {SHIP}")
    print(f"  meta: min={ev(f'{CORE}.getParameterMinimumValue({CORE}.getParameterIndex({json.dumps(PARAM)}))', ap=False)}"
          f" max={ev(f'{CORE}.getParameterMaximumValue({CORE}.getParameterIndex({json.dumps(PARAM)}))', ap=False)}"
          f" default={ev(f'{CORE}.getParameterDefaultValue({CORE}.getParameterIndex({json.dumps(PARAM)}))', ap=False)}")
    print(f"  当前值 = {ev(READ, ap=False)}")

    # T1/T2：走面板按钮
    ev("document.getElementById('l2PanelBtn').click()", ap=False)
    time.sleep(1.0)
    click = ev(f"""(()=>{{ try{{
      const pn=document.getElementById('l2panel');
      const row=[...pn.querySelectorAll('.prow')].find(r=>r.dataset.nm==={json.dumps(PARAM.lower())});
      if(!row) return 'NO_ROW'; const b=row.querySelector('button');
      if(!b) return 'NO_BTN'; b.click(); return 'clicked';
    }}catch(e){{ return 'ERR:'+e.message; }} }})()""", ap=False)
    t1 = ev(READ, ap=False)
    time.sleep(0.12)
    t2 = ev(READ, ap=False)
    time.sleep(0.6)
    t2b = ev(READ, ap=False)
    print(f"  T1 点击后立即   = {t1}   ({click})")
    print(f"  T2 +120ms       = {t2}")
    print(f"  T2b +700ms      = {t2b}")

    # T3/T4：直接写 API
    ev(f"{CORE}.setParameterValueById({json.dumps(PARAM)}, 2)", ap=False)
    t3 = ev(READ, ap=False)
    time.sleep(0.3)
    t4 = ev(READ, ap=False)
    print(f"  T3 直接写 2 立即 = {t3}")
    print(f"  T4 +300ms       = {t4}")

    # T5：停掉动作再写
    ev("l2State.app.stage.children[0].internalModel.motionManager.stopAllMotions()", ap=False)
    time.sleep(0.3)
    ev(f"{CORE}.setParameterValueById({json.dumps(PARAM)}, 3)", ap=False)
    t5 = ev(READ, ap=False)
    time.sleep(0.5)
    t5b = ev(READ, ap=False)
    print(f"  T5 停动作后写 3  = {t5}")
    print(f"  T5b +500ms      = {t5b}")

    # 该参数是否真的影响画面：改到两端比像素哈希
    HASH = """(()=>{ try{
      const app=l2State.app; const cv=document.createElement('canvas');
      cv.width=200; cv.height=Math.round(200*app.renderer.height/app.renderer.width);
      const g=cv.getContext('2d',{willReadFrequently:true});
      g.drawImage(app.view,0,0,cv.width,cv.height);
      const d=g.getImageData(0,0,cv.width,cv.height).data;
      let h=2166136261>>>0; for(let i=0;i<d.length;i+=32){ h^=d[i]; h=Math.imul(h,16777619)>>>0; }
      return 'h'+h.toString(16);
    }catch(e){ return 'ERR'; } })()"""
    ev("l2State.app.stage.children[0].internalModel.motionManager.stopAllMotions()", ap=False)
    time.sleep(0.2)
    ev(f"{CORE}.setParameterValueById({json.dumps(PARAM)}, 0)", ap=False)
    time.sleep(0.25)
    h0 = ev(HASH, ap=False)
    ev(f"{CORE}.setParameterValueById({json.dumps(PARAM)}, 3)", ap=False)
    time.sleep(0.25)
    h3 = ev(HASH, ap=False)
    print(f"  视觉影响：值0 -> {h0}   值3 -> {h3}   {'有差异' if h0 != h3 else '无差异（该参数不控制可见内容）'}")

    ws.close()
    proc.terminate()
    return 0


if __name__ == "__main__":
    sys.exit(main())
