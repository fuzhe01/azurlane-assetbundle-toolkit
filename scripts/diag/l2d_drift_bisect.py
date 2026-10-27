# -*- coding: utf-8 -*-
"""l2d_drift_bisect.py — 定位「新画廊里 ArtMesh255~258 从可见漂到隐藏」的触发源。

现象（2026-10-23 实测）：
  同一页面、同一模型，首次采样 ro=54/53/52/34 vis=1，
  之后全部变成 ro=8/7/6/1 vis=0。旧画廊恒为前者。
⇒ 新画廊某个每帧逻辑把它改了。本脚本按嫌疑逐个「停用 → 等 3 秒 → 再采样」，
   找出哪一个停用后状态不再漂移。

嫌疑清单（新画廊相对旧画廊新增的每帧写入）：
  A  restTick（残留复位，写 switchParams 之外的历史参数）
  B  换装 pinTick（window.__costumePinsByModel）
  C  stateApply（STATE_TOGGLES 状态开关）
  D  BASE_PINS（已清空，但钩子仍在）
  E  眼动 ticker（ParamEyeBallX/Y）

用法: py -3.14 scripts/diag/l2d_drift_bisect.py --ship ougen_8
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
TARGETS = ["ArtMesh255", "ArtMesh256", "ArtMesh257", "ArtMesh258"]


def arg(n, d=None):
    return sys.argv[sys.argv.index(n) + 1] if n in sys.argv else d


SHIP = arg("--ship", "ougen_8")
SRV = arg("--port", "8778")
PORT = int(arg("--cdp", "9399"))
PROFILE = os.path.join(ROOT, ".diag", f"chrome_drift_{PORT}")

SAMPLE = """(()=>{ try{
  const core=l2State.app.stage.children[0].internalModel.coreModel;
  let ros=[]; try{ ros=core.getDrawableRenderOrders()||[]; }catch(e){}
  const out={};
  for(const k of %s){ const i=core.getDrawableIndex(k); if(i<0){ out[k]=null; continue; }
    let vis=0; try{ vis=core.getDrawableDynamicFlagIsVisible(i)?1:0; }catch(e){}
    out[k]={ro:ros.length?ros[i]:null, vis:vis}; }
  return JSON.stringify(out);
}catch(e){ return 'ERR:'+e.message; } })()""" % json.dumps(TARGETS)


def main():
    ps = ("$ErrorActionPreference='SilentlyContinue';"
          "Get-CimInstance Win32_Process -Filter \"Name='msedge.exe'\" | "
          "Where-Object { $_.CommandLine -like '*%s*' } | "
          "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" % PROFILE)
    subprocess.run(["powershell.exe", "-NoProfile", "-Command", ps],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.5)
    url = f"http://127.0.0.1:{SRV}/gallery_v2/index.html?ship={SHIP}&_t={int(time.time()*1000)}"
    proc = chrome_tree.launch([
        BROWSER, f"--remote-debugging-port={PORT}", "--remote-allow-origins=*",
        f"--user-data-dir={PROFILE}", "--no-first-run", "--no-default-browser-check",
        "--headless=new", "--gpu", "--window-size=1400,950", url],
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
                return r.get("result", {})

    def ev(e, ap=False):
        r = cmd("Runtime.evaluate", {"expression": e, "returnByValue": True, "awaitPromise": ap})
        if r.get("exceptionDetails"):
            return "EVALERR " + str(r["exceptionDetails"].get("text"))[:200]
        return r.get("result", {}).get("value")

    cmd("Page.enable")
    cmd("Runtime.enable")
    for _ in range(140):
        if ev("(typeof l2State!=='undefined'&&l2State&&l2State.app&&"
              "l2State.app.stage.children[0]&&l2State.app.stage.children[0].internalModel)?1:0") == 1:
            break
        time.sleep(0.5)

    def sample():
        s = ev(SAMPLE)
        try:
            return json.loads(s)
        except Exception:
            return None

    def brief(d):
        if not d:
            return "?"
        return " ".join(f"{k.replace('ArtMesh','')}:{v['vis']}/{v['ro']}" for k, v in d.items() if v)

    print("基线（不停用任何东西）：")
    for i in range(4):
        print(f"   t+{i}: {brief(sample())}")
        time.sleep(1.0)

    # 逐个停用嫌疑：清空 ticker 列表里的对应函数无法精确定位，
    # 直接用「清空 pin 表 / 关掉 stateApply」等可控开关
    trials = [
        ("清空换装 pins", "(()=>{ window.__costumePinsByModel=Object.create(null); return 1; })()"),
        ("清空 STATE_TOGGLES 运行时态",
         "(()=>{ try{ l2State.app.stage.children[0].internalModel.removeAllListeners('beforeModelUpdate'); "
         "return 1; }catch(e){ return 'ERR'; } })()"),
    ]
    for name, js in trials:
        r = ev(js)
        time.sleep(2.0)
        print(f"\n停用「{name}」后（返回 {r}）：")
        for i in range(3):
            print(f"   t+{i}: {brief(sample())}")
            time.sleep(1.0)

    ws.close()
    proc.terminate()
    return 0


if __name__ == "__main__":
    sys.exit(main())
