# -*- coding: utf-8 -*-
"""l2d_ro_stability_diag.py — 验证 renderOrder 是否随加载时机变化。

背景：同一份 moc3（MD5 相同）、同一浏览器、同 GPU，两个画廊里
`getDrawableRenderOrders()` 返回的排序完全不同（旧 ro=54/53/52/34，新 ro=8/7/6/1），
且新画廊里 4 个 mesh 的 `vis` 变成 0。
若 ro 本身不稳定（随 update 次数/加载阶段变化），那"布局差异"就是错觉，
真正要查的是 **vis 为什么变成 0**。

判据：
  ① 同一页面内连续多次采样 ro，看是否变化（不稳定 ⇒ ro 不能当布局依据）
  ② 采样 vis 同时刻，看 4 个目标 mesh 的 vis 是否也在变

用法: py -3.14 scripts/diag/l2d_ro_stability_diag.py --ship ougen_8 --port 8778 --targets ArtMesh255,ArtMesh256,ArtMesh257,ArtMesh258
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


def arg(n, d=None):
    return sys.argv[sys.argv.index(n) + 1] if n in sys.argv else d


SHIP = arg("--ship", "ougen_8")
SRV = arg("--port", "8778")
TARGETS = [x for x in (arg("--targets", "ArtMesh255,ArtMesh256,ArtMesh257,ArtMesh258")).split(",") if x]
PORT = int(arg("--cdp", "9395"))
PROFILE = os.path.join(ROOT, ".diag", f"chrome_rostab_{PORT}")


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

    SAMPLE = f"""(()=>{{ try{{
      const core=l2State.app.stage.children[0].internalModel.coreModel;
      let ros=[]; try{{ ros=core.getDrawableRenderOrders()||[]; }}catch(e){{}}
      const out={{}};
      for(const k of {json.dumps(TARGETS)}){{
        const i=core.getDrawableIndex(k);
        if(i<0){{ out[k]=null; continue; }}
        let vis=0, op=null;
        try{{ vis=core.getDrawableDynamicFlagIsVisible(i)?1:0; }}catch(e){{}}
        try{{ op=+core.getDrawableOpacity(i).toFixed(3); }}catch(e){{}}
        out[k]={{ro:ros.length?ros[i]:null, vis:vis, op:op, idx:i}};
      }}
      /* ro 全表指纹：前 20 个 id 的 ro 序列，用来判断顺序是否变化 */
      let sig='';
      for(let i=0;i<Math.min(20,ros.length);i++){{ let id='?';
        try{{ id=core.getDrawableId(i); }}catch(e){{}} sig+=id+':'+ros[i]+';'; }}
      return JSON.stringify({{targets:out, sig:sig, n:ros.length}});
    }}catch(e){{ return 'ERR:'+e.message; }} }})()"""

    print(f"模型 {SHIP} @ {SRV}  目标 {TARGETS}\n")
    prev_sig = None
    prev_t = None
    for n in range(6):
        s = ev(SAMPLE)
        try:
            d = json.loads(s)
        except Exception:
            print(f"  采样{n}: {str(s)[:150]}")
            time.sleep(0.8)
            continue
        sig = d.get("sig", "")
        tg = d.get("targets") or {}
        line = "  ".join(f"{k.replace('ArtMesh','')}:ro={v['ro']}/vis={v['vis']}"
                         for k, v in tg.items() if v)
        changed = "" if prev_sig is None else (" <== ro 顺序变了" if sig != prev_sig else "")
        tchanged = ""
        if prev_t is not None:
            tv = {k: (v or {}).get("vis") for k, v in tg.items()}
            if tv != prev_t:
                tchanged = " <== vis 变了"
        print(f"  采样{n}: {line}{changed}{tchanged}")
        prev_sig, prev_t = sig, {k: (v or {}).get("vis") for k, v in tg.items()}
        time.sleep(0.9)

    ws.close()
    proc.terminate()
    return 0


if __name__ == "__main__":
    sys.exit(main())
