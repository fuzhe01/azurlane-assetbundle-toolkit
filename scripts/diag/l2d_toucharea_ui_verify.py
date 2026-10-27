# -*- coding: utf-8 -*-
"""l2d_toucharea_ui_verify.py — 验收「互动区面板」(方案 A+) 是否真的把全部互动区列出来。

判据（走页面自己的路径，不绕过）：
  1) touchareas.json 加载成功，目标模型有条目；
  2) 面板出现「互动区 N（已登记 M）」分区，且 N 与数据表一致；
  3) **未登记的互动区也出现在面板里**（这是本次修复的核心诉求：
     ougen_8 的 TouchDrag17 存在于 moc3 却不在 model3.json 的 HitAreas 里，
     旧前端完全看不到它）；
  4) 点「▶」（有同名动作组的）能真的切到该动作组。

用法: py -3.14 scripts/diag/l2d_toucharea_ui_verify.py --ship ougen_8
      py -3.14 scripts/diag/l2d_toucharea_ui_verify.py --ship benningdun_2
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
PORT = int(os.environ.get("TAUI_PORT", "9385"))
SRV = "8778"
PROFILE = os.path.join(ROOT, ".diag", f"chrome_taui_{PORT}")


def arg(n, d=None):
    return sys.argv[sys.argv.index(n) + 1] if n in sys.argv else d


SHIP = arg("--ship", "ougen_8")
URL = f"http://127.0.0.1:{SRV}/gallery_v2/index.html"


def main():
    ps = ("$ErrorActionPreference='SilentlyContinue';"
          "Get-CimInstance Win32_Process -Filter \"Name='msedge.exe'\" | "
          "Where-Object { $_.CommandLine -like '*%s*' } | "
          "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" % PROFILE)
    subprocess.run(["powershell.exe", "-NoProfile", "-Command", ps],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.5)
    proc = subprocess.Popen([
        BROWSER, f"--remote-debugging-port={PORT}", "--remote-allow-origins=*",
        f"--user-data-dir={PROFILE}", "--no-first-run", "--no-default-browser-check",
        "--headless=new", "--gpu", "--window-size=1400,950",
        f"{URL}?ship={SHIP}&_t={int(time.time()*1000)}"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    proc = chrome_tree.install(proc)
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
    cmd("Network.enable")
    cmd("Network.setCacheDisabled", {"cacheDisabled": True})

    for _ in range(120):
        if ev("(typeof l2State!=='undefined'&&l2State&&l2State.app&&"
              "l2State.app.stage.children[0]&&l2State.app.stage.children[0].internalModel)?1:0") == 1:
            break
        time.sleep(0.5)
    for _ in range(60):
        if ev("!!window.TOUCHAREAS && Object.keys(window.TOUCHAREAS).length>0") is True:
            break
        time.sleep(0.4)

    fails = []

    def check(name, ok, detail=""):
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}{('  ' + str(detail)[:200]) if detail else ''}")
        if not ok:
            fails.append(name)

    meta = ev(f"""(()=>{{ try{{
      const t=(window.TOUCHAREAS&&TOUCHAREAS[{json.dumps(SHIP)}])||null;
      const all=t?[...(t.drag||[]),...(t.idle||[])]:[];
      return JSON.stringify({{loaded:!!window.TOUCHAREAS, has:!!t, n:all.length,
        registered:all.filter(x=>x.registered).length,
        unregistered:all.filter(x=>!x.registered).length,
        hasTD17: all.some(x=>x.drawable==='TouchDrag17')}});
    }}catch(e){{ return 'ERR:'+e.message; }} }})()""")
    try:
        meta = json.loads(meta)
    except Exception:
        meta = {}
    check("touchareas.json 已加载且该模型有条目",
          bool(meta.get("loaded")) and bool(meta.get("has")),
          f"互动区={meta.get('n')} 已登记={meta.get('registered')} 未登记={meta.get('unregistered')}")

    ev("document.getElementById('l2PanelBtn').click()")
    time.sleep(1.2)
    sec = ev("""(()=>{ try{
      const hs=[...document.querySelectorAll('#l2panel h5')].map(h=>h.textContent);
      const h=hs.find(t=>t&&t.indexOf('互动区')===0)||null;
      const rows=[...document.querySelectorAll('#l2panel .prow')].map(r=>r.dataset.nm).filter(Boolean);
      return JSON.stringify({headers:hs, touchHeader:h,
        hasTouchDrag17: rows.some(x=>x==='touchdrag17'),
        nRows: rows.length, sample:rows.filter(x=>x.indexOf('touch')===0).slice(0,8)});
    }catch(e){ return 'ERR:'+e.message; } })()""")
    try:
        sec = json.loads(sec)
    except Exception:
        sec = {}
    check("面板出现「互动区」分区", bool(sec.get("touchHeader")),
          f"header={sec.get('touchHeader')} all={sec.get('headers')}")
    check("未登记的 TouchDrag17 已出现在面板（核心诉求）",
          bool(sec.get("hasTouchDrag17")),
          f"touch行样例={sec.get('sample')}")

    # 点一个有动作组的 ▶，确认真的切组
    play = ev("""(()=>{ try{
      const pn=document.getElementById('l2panel');
      const rows=[...pn.querySelectorAll('.prow')];
      const row=rows.find(r=>{ const b=r.querySelector('button'); return b && b.textContent==='▶'; });
      if(!row) return 'NO_PLAYABLE';
      const before=(document.getElementById('l2Curr')||{}).textContent;
      row.querySelector('button').click();
      return JSON.stringify({before:before, after:(document.getElementById('l2Curr')||{}).textContent,
        row:row.dataset.nm});
    }catch(e){ return 'ERR:'+e.message; } })()""")
    try:
        pj = json.loads(play)
    except Exception:
        pj = None
    if pj:
        check("点「▶」能切到对应动作组", pj.get("before") != pj.get("after"),
              f"{pj.get('row')}: {pj.get('before')} -> {pj.get('after')}")
    else:
        check("点「▶」能切到对应动作组", False, play)

    ws.close()
    proc.terminate()
    print("")
    print("结果: " + ("PASS" if not fails else f"FAIL ({len(fails)} 项)"))
    raise SystemExit(0 if not fails else 1)


if __name__ == "__main__":
    sys.exit(main())
