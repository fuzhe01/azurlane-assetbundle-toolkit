# -*- coding: utf-8 -*-
"""l2d_loaded_resource_diag.py — 检查页面实际加载了哪些资源、内容是否与磁盘一致。

背景（2026-10-23 ougen_8 左腿）：moc3 两侧 MD5 完全相同、model3.json 仅 HitAreas 顺序不同，
但新画廊里 ArtMesh255~258 的 vis 最终变 0、旧画廊恒为 1。
需要排除「页面真正 fetch 到的文件不是我们以为的那份」——
缓存、路径别名、model3 指向别的目录都可能造成这种"数据一致但表现不同"。

判据：在页面内用 performance.getEntriesByType('resource') 列出所有已加载资源，
再对关键文件重新 fetch 一次取字节数+前 64 字节哈希，与磁盘对照。

用法: py -3.14 scripts/diag/l2d_loaded_resource_diag.py --port 8778 --ship ougen_8
"""
import sys, os, json, time, subprocess, urllib.request, hashlib

sys.stdout.reconfigure(encoding="utf-8")
import websocket

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CAND = [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"]
BROWSER = next((c for c in CAND if os.path.isfile(c)), None)


def arg(n, d=None):
    return sys.argv[sys.argv.index(n) + 1] if n in sys.argv else d


SRV = arg("--port", "8778")
SHIP = arg("--ship", "ougen_8")
PORT = int(arg("--cdp", "9402"))
PROFILE = os.path.join(ROOT, ".diag", f"chrome_res_{PORT}")


def main():
    ps = ("$ErrorActionPreference='SilentlyContinue';"
          "Get-CimInstance Win32_Process -Filter \"Name='msedge.exe'\" | "
          "Where-Object { $_.CommandLine -like '*%s*' } | "
          "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" % PROFILE)
    subprocess.run(["powershell.exe", "-NoProfile", "-Command", ps],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.5)
    url = f"http://127.0.0.1:{SRV}/gallery_v2/index.html?ship={SHIP}&_t={int(time.time()*1000)}"
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
    for _ in range(140):
        if ev("(typeof l2State!=='undefined'&&l2State&&l2State.app&&"
              "l2State.app.stage.children[0]&&l2State.app.stage.children[0].internalModel)?1:0") == 1:
            break
        time.sleep(0.5)

    # 列出所有 live2d 相关已加载资源
    res = ev("""(()=>{ try{
      const out=[];
      for(const e of performance.getEntriesByType('resource')){
        if(/Live2D|ougen_8|vendor\\/live2d/i.test(e.name)) out.push({url:e.name, bytes:e.transferSize});
      }
      return JSON.stringify(out);
    }catch(e){ return 'ERR:'+e.message; } })()""")
    try:
        lst = json.loads(res)
    except Exception:
        lst = []
    print(f"页面已加载的 Live2D 相关资源 {len(lst)} 条:")
    for x in lst[:20]:
        print(f"  {x['url'].split('/gallery_v2/')[-1]:<60} {x['bytes']} B")

    # 重新 fetch 关键文件，取字节数 + 前 64 字节 hex，与磁盘对照
    targets = [
        f"Live2D/{SHIP}/{SHIP}.moc3",
        f"Live2D/{SHIP}/{SHIP}.model3.json",
        f"Live2D/{SHIP}/{SHIP}.physics3.json",
    ]
    print("\n关键文件重新 fetch（页面视角）:")
    for t in targets:
        r = ev(f"""(async()=>{{ try{{
          const r=await fetch({json.dumps('./' + t)});
          const b=await r.arrayBuffer();
          const u=new Uint8Array(b).slice(0,64);
          let h=0; for(const x of u) h=(Math.imul(h,31)+x)>>>0;
          return JSON.stringify({{ok:r.ok, bytes:b.byteLength, h64:h}});
        }}catch(e){{ return 'ERR:'+e.message; }} }})()""", ap=True)
        disk = os.path.join(ROOT, "Output", t.replace("/", os.sep))
        dbytes = os.path.getsize(disk) if os.path.isfile(disk) else -1
        dh = 0
        if os.path.isfile(disk):
            with open(disk, "rb") as f:
                for x in f.read(64):
                    dh = (dh * 31 + x) & 0xFFFFFFFF
        try:
            js = json.loads(r)
        except Exception:
            js = {"raw": str(r)[:120]}
        same = (js.get("bytes") == dbytes and js.get("h64") == dh)
        print(f"  {t}")
        print(f"     页面: {js}    磁盘: bytes={dbytes} h64={dh}    {'一致' if same else '**不一致**'}")

    ws.close()
    proc.terminate()
    return 0


if __name__ == "__main__":
    sys.exit(main())
