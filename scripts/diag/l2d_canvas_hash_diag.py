# -*- coding: utf-8 -*-
"""l2d_canvas_hash_diag.py — 验证「画布像素哈希」这条判据本身是否可靠。

背景：可写性探针一直报 visible=False（20 条参数全无视觉变化），怀疑是哈希取不到像素
或画面本来就不随参数变。本脚本做最小区分：
  H0  连续两次哈希（不动任何参数）—— 若相同 ⇒ 哈希稳定，判据可用
  H1  把整个模型挪一下（mdl.x += 40）后哈希 —— 若变化 ⇒ 哈希能感知画面变化
  H2  写一个已知可写参数后再哈希
三件事一分，就能判定"visible 全 False"是判据坏了还是参数真无视觉。

用法: py -3.14 scripts/diag/l2d_canvas_hash_diag.py --ship benningdun_2 --param GloveSwitch_R
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
PORT = int(os.environ.get("CHD_PORT", "9381"))
SRV = "8778"
PROFILE = os.path.join(ROOT, ".diag", f"chrome_hashdiag_{PORT}")


def arg(n, d=None):
    return sys.argv[sys.argv.index(n) + 1] if n in sys.argv else d


SHIP = arg("--ship", "benningdun_2")
PARAM = arg("--param", "GloveSwitch_R")

HASH_JS = r"""(()=>{ try{
  const app=l2State.app; const cv=document.createElement('canvas');
  cv.width=160; cv.height=Math.round(160*app.renderer.height/app.renderer.width);
  const g=cv.getContext('2d',{willReadFrequently:true});
  g.clearRect(0,0,cv.width,cv.height);
  g.drawImage(app.view,0,0,cv.width,cv.height);
  const d=g.getImageData(0,0,cv.width,cv.height).data;
  let h=2166136261>>>0, n=0, nonzero=0;
  for(let i=0;i<d.length;i+=32){ h^=d[i]; h=Math.imul(h,16777619)>>>0; n++;
    if(d[i]||d[i+(i+1<d.length?1:0)]) nonzero++; }
  return h+'_'+n+'_nz'+nonzero;
}catch(e){ return 'ERR:'+e.message; } })()"""


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
        "--headless=new", "--gpu", "--window-size=1300,900", url],
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
    for _ in range(120):
        if ev("(typeof l2State!=='undefined'&&l2State&&l2State.app&&"
              "l2State.app.stage.children[0])?1:0") == 1:
            break
        time.sleep(0.5)
    time.sleep(3)

    print(f"模型 {SHIP} / 参数 {PARAM}")
    print("  view =", ev("JSON.stringify({w:l2State.app.view.width,h:l2State.app.view.height})"))
    print("  模型 =", ev("JSON.stringify({x:+l2State.app.stage.children[0].x.toFixed(1),"
                      "y:+l2State.app.stage.children[0].y.toFixed(1),"
                      "s:+l2State.app.stage.children[0].scale.x.toFixed(4)})"))

    h0a = ev(HASH_JS)
    time.sleep(0.4)
    h0b = ev(HASH_JS)
    print(f"  H0 连续两次   : {h0a}   {h0b}   {'稳定' if h0a == h0b else '不稳定(判据不可靠)'}")

    ev("(()=>{ try{ const m=l2State.app.stage.children[0]; m.x+=40; "
       "l2State.app.renderer.render(l2State.app.stage); return 1;}catch(e){return 0;} })()")
    time.sleep(0.4)
    h1 = ev(HASH_JS)
    print(f"  H1 模型右移40 : {h1}   {'能感知画面变化' if h1 != h0b else '取不到画面(假阴性)'}")
    ev("(()=>{ try{ const m=l2State.app.stage.children[0]; m.x-=40; "
       "l2State.app.renderer.render(l2State.app.stage); return 1;}catch(e){return 0;} })()")
    time.sleep(0.4)

    core = "l2State.app.stage.children[0].internalModel.coreModel"
    ev(f"(()=>{{ try{{ {core}.setParameterValueById({json.dumps(PARAM)}, 3); {core}.update(); "
       f"l2State.app.renderer.render(l2State.app.stage); }}catch(e){{}} return 1; }})()")
    time.sleep(0.5)
    h2 = ev(HASH_JS)
    back = ev(f"(()=>{{try{{return +{core}.getParameterValueById({json.dumps(PARAM)});}}catch(e){{return 'ERR';}}}})()")
    print(f"  H2 写{PARAM}=3 : {h2}   读回={back}   "
          f"{'有视觉变化' if h2 != h0b else '无视觉变化'}")

    # H3：直接检查该参数控制哪些 drawable 的 opacity（不依赖像素）
    op = ev(f"""(()=>{{ try{{
      const core={core}, app=l2State.app;
      const n=core.getDrawableCount(); const before=[];
      for(let i=0;i<n;i++){{ try{{ before.push(core.getDrawableOpacity(i)); }}catch(e){{ before.push(null); }} }}
      core.setParameterValueById({json.dumps(PARAM)}, 3); core.update();
      const diff=[];
      for(let i=0;i<n;i++){{ try{{ const v=core.getDrawableOpacity(i);
        if(before[i]!=null && Math.abs(v-before[i])>0.02){{ let id='?';
          try{{ id=core.getDrawableId(i); }}catch(e){{}} diff.push(id+':'+before[i].toFixed(2)+'->'+v.toFixed(2)); }} }}
        catch(e){{}} }}
      core.setParameterValueById({json.dumps(PARAM)}, 0); core.update();
      return JSON.stringify({{n_changed:diff.length, sample:diff.slice(0,8)}});
    }}catch(e){{ return 'ERR:'+e.message; }} }})()""")
    print(f"  H3 该参数改动的 drawable(不依赖像素): {op}")

    ws.close()
    proc.terminate()
    return 0


if __name__ == "__main__":
    sys.exit(main())
