# -*- coding: utf-8 -*-
"""l2d_old_gallery_probe.py — 在旧画廊（无 ?ship= 支持）里用点击路径打开模型并采样。

旧画廊 index.html 是 2026-10-21 版本，没有 ?ship=/?motion= 这些诊断参数，
必须走「搜索 → 点卡片 → 点皮肤 → 点 Live2D 标签」的真实路径。

用途：对旧画廊做与 l2d_ro_stability_diag.py 相同的采样，
回答「renderOrder/vis 随时间变化」是旧画廊也有、还是新画廊独有。

用法: py -3.14 scripts/diag/l2d_old_gallery_probe.py --ship ougen_8 --port 8777
"""
import sys, os, json, time, subprocess, urllib.request

sys.stdout.reconfigure(encoding="utf-8")
import websocket

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CAND = [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"]
BROWSER = next((c for c in CAND if os.path.isfile(c)), None)


def arg(n, d=None):
    return sys.argv[sys.argv.index(n) + 1] if n in sys.argv else d


SHIP = arg("--ship", "ougen_8")
SRV = arg("--port", "8777")
TARGETS = [x for x in (arg("--targets", "ArtMesh255,ArtMesh256,ArtMesh257,ArtMesh258")).split(",") if x]
PORT = int(arg("--cdp", "9397"))
PROFILE = os.path.join(ROOT, ".diag", f"chrome_oldg_{PORT}")
BASE = SHIP.split("_")[0]


def main():
    ps = ("$ErrorActionPreference='SilentlyContinue';"
          "Get-CimInstance Win32_Process -Filter \"Name='msedge.exe'\" | "
          "Where-Object { $_.CommandLine -like '*%s*' } | "
          "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" % PROFILE)
    subprocess.run(["powershell.exe", "-NoProfile", "-Command", ps],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.5)
    url = f"http://127.0.0.1:{SRV}/gallery_v2/index.html?_t={int(time.time()*1000)}"
    proc = subprocess.Popen([
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
    for _ in range(60):
        if ev("typeof GALLERY!=='undefined'") is True:
            break
        time.sleep(0.4)

    print(f"旧画廊 {SRV}：走点击路径打开 {SHIP}")
    # 1) 搜索
    ev(f"""(()=>{{ try{{
      const q=document.getElementById('search');
      if(q){{ q.value={json.dumps(BASE)}; q.dispatchEvent(new Event('input',{{bubbles:true}})); }}
      return 1; }}catch(e){{ return 0; }} }})()""")
    time.sleep(1.2)
    # 2) 点卡片
    r2 = ev(f"""(()=>{{ try{{
      const cards=[...document.querySelectorAll('.card')];
      const c=cards.find(x=>{{ const p=x.querySelector('.py');
        return p && p.textContent.trim().startsWith({json.dumps(BASE)}); }});
      if(!c) return 'NO_CARD'; c.click(); return 'card-clicked'; }}catch(e){{ return 'ERR:'+e.message; }} }})()""")
    print("  ", r2)
    time.sleep(1.2)
    # 3) 点皮肤
    r3 = ev(f"""(()=>{{ try{{
      const sk=document.querySelector('.skin[data-k="{SHIP}"]');
      if(!sk) return 'NO_SKIN'; sk.click(); return 'skin-clicked'; }}catch(e){{ return 'ERR:'+e.message; }} }})()""")
    print("  ", r3)
    time.sleep(1.0)
    # 4) 切 Live2D 标签
    r4 = ev("""(()=>{ try{
      const tb=[...document.querySelectorAll('#mTabs .tab')].find(x=>x.dataset.k==='live2d');
      if(!tb) return 'NO_TAB'; if(tb.classList.contains('dis')) return 'TAB_DIS';
      tb.click(); return 'tab-clicked'; }catch(e){ return 'ERR:'+e.message; } })()""")
    print("  ", r4)

    ok = False
    for _ in range(120):
        if ev("(typeof l2State!=='undefined'&&l2State&&l2State.app&&"
              "l2State.app.stage.children[0]&&l2State.app.stage.children[0].internalModel)?1:0") == 1:
            ok = True
            break
        time.sleep(0.5)
    if not ok:
        print("  模型未就绪，放弃")
        ws.close()
        proc.terminate()
        return 1

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
        out[k]={{ro:ros.length?ros[i]:null, vis:vis, op:op}};
      }}
      let sig='';
      for(let i=0;i<Math.min(20,ros.length);i++){{ let id='?';
        try{{ id=core.getDrawableId(i); }}catch(e){{}} sig+=id+':'+ros[i]+';'; }}
      return JSON.stringify({{targets:out, sig:sig}});
    }}catch(e){{ return 'ERR:'+e.message; }} }})()"""

    print()
    prev_sig = None
    for n in range(6):
        s = ev(SAMPLE)
        try:
            d = json.loads(s)
        except Exception:
            print(f"  采样{n}: {str(s)[:120]}")
            time.sleep(0.8)
            continue
        tg = d.get("targets") or {}
        line = "  ".join(f"{k.replace('ArtMesh','')}:ro={v['ro']}/vis={v['vis']}"
                         for k, v in tg.items() if v)
        ch = "" if prev_sig is None else (" <== ro 变了" if d.get("sig") != prev_sig else "")
        print(f"  采样{n}: {line}{ch}")
        prev_sig = d.get("sig")
        time.sleep(0.9)

    ws.close()
    proc.terminate()
    return 0


if __name__ == "__main__":
    sys.exit(main())
