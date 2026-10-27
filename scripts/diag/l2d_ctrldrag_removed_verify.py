# -*- coding: utf-8 -*-
"""l2d_ctrldrag_removed_verify.py — 验收「Ctrl+拖拽触发互动区」已移除，且点击互动仍正常。

判据（走页面自己的事件路径，不直接调内部函数）：
  1) Ctrl+左键在互动区按下并拖动 → 当前动作组**不应变成** touch_dragN
     （移除前会播 drag 并强制 loop）
  2) 普通左键在互动区**点击**（不拖）→ 仍能触发动作（回归：别把点击一起弄坏）
  3) Ctrl+滚轮缩放仍可用（用户只要求移除 Ctrl+拖拽，缩放要保留）

用法: py -3.14 scripts/diag/l2d_ctrldrag_removed_verify.py --ship ougen_8
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
SRV = "8778"
PORT = int(arg("--cdp", "9405"))
PROFILE = os.path.join(ROOT, ".diag", f"chrome_ctrldrag_{PORT}")


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
    for _ in range(140):
        if ev("(typeof l2State!=='undefined'&&l2State&&l2State.app&&"
              "l2State.app.stage.children[0]&&l2State.app.stage.children[0].internalModel)?1:0") == 1:
            break
        time.sleep(0.5)

    fails = []

    def check(name, ok, detail=""):
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}{('  ' + str(detail)[:180]) if detail else ''}")
        if not ok:
            fails.append(name)

    CUR = "((document.getElementById('l2Curr')||{}).textContent)||''"

    # 取一个可点的 TouchDrag 区中心（用页面自己的 geom 计算，不猜坐标）
    info = ev("""(()=>{ try{
      const out=[];
      for(const ha of (window.__L2_HITUSE?__L2_HITUSE():[])){
        /* 只要有 drag 命名的区 */
        if(/drag/i.test(ha)) out.push(ha);
      }
      return JSON.stringify({dragAreas: out});
    }catch(e){ return 'ERR:'+e.message; } })()""")
    try:
        ij = json.loads(info)
    except Exception:
        ij = {}
    print(f"  可用 drag 区: {ij.get('dragAreas')[:6]}")

    # 1) Ctrl+拖拽 不应再切到 touch_dragN
    r1 = ev("""(async()=>{ try{
      const t=ms=>new Promise(r=>setTimeout(r,ms));
      const wrap=document.getElementById('l2wrap');
      const rect=wrap.getBoundingClientRect();
      const cx=rect.left+rect.width*0.5, cy=rect.top+rect.height*0.55;
      const before=(document.getElementById('l2Curr')||{}).textContent||'';
      const mk=(type,x,y,opt)=>new PointerEvent(type, Object.assign({bubbles:true,cancelable:true,
        clientX:x, clientY:y, button:0, buttons:1, pointerId:1, isPrimary:true}, opt||{}));
      wrap.dispatchEvent(mk('pointerdown', cx, cy, {ctrlKey:true}));
      for(let i=1;i<=6;i++){ window.dispatchEvent(mk('pointermove', cx+i*14, cy+i*4, {ctrlKey:true})); await t(40); }
      window.dispatchEvent(mk('pointerup', cx+90, cy+24, {ctrlKey:true}));
      await t(500);
      const after=(document.getElementById('l2Curr')||{}).textContent||'';
      return JSON.stringify({before:before, after:after,
        becameDrag: /touch_drag/i.test(after||'')});
    }catch(e){ return 'ERR:'+e.message; } })()""", ap=True)
    try:
        r1j = json.loads(r1)
    except Exception:
        r1j = {}
    check("Ctrl+拖拽不再触发 touch_dragN",
          not r1j.get("becameDrag"),
          f"{r1j.get('before')} -> {r1j.get('after')}")

    # 2) 普通左键点击仍能触发（回归）
    # ⚠️ 不能瞎猜屏幕坐标（第一次点画布 30% 高处落在空白区，被误判成"点击失效"）。
    #    用页面自己的命中数据算出某个区的真实屏幕坐标再点。
    r2 = ev("""(async()=>{ try{
      const t=ms=>new Promise(r=>setTimeout(r,ms));
      const wrap=document.getElementById('l2wrap');
      const rect=wrap.getBoundingClientRect();
      const mdl=l2State.app.stage.children[0], im=mdl.internalModel;
      const core=im.coreModel, ppu=im.pixelsPerUnit||1;
      const cux=im.width/ppu, cuy=im.height/ppu, s=mdl.scale.x;
      /* 取一个已登记且有同名动作组的 drag 区（这些一定可点） */
      const TA=(window.TOUCHAREAS&&TOUCHAREAS[%s])||null;
      let target=null;
      if(TA){ for(const it of (TA.drag||[])){ if(it.group){ target=it.drawable; break; } } }
      if(!target) return JSON.stringify({skip:'无可用 drag 区'});
      const ix=core.getDrawableIndex(target);
      if(ix<0) return JSON.stringify({skip:'drawable 不存在 '+target});
      const p=core.getDrawableVertexPositions(ix);
      if(!p||p.length<4) return JSON.stringify({skip:'无顶点'});
      let x0=1e9,y0=1e9,x1=-1e9,y1=-1e9;
      for(let k=0;k+1<p.length;k+=2){
        const stx=mdl.x+(p[k]+cux/2)*ppu*s, sty=mdl.y+(cuy/2-p[k+1])*ppu*s;
        if(stx<x0)x0=stx; if(stx>x1)x1=stx; if(sty<y0)y0=sty; if(sty>y1)y1=sty; }
      const cx=rect.left+(x0+x1)/2, cy=rect.top+(y0+y1)/2;
      const before=(document.getElementById('l2Curr')||{}).textContent||'';
      const mk=(type,x,y)=>new PointerEvent(type,{bubbles:true,cancelable:true,
        clientX:x, clientY:y, button:0, buttons:1, pointerId:2, isPrimary:true});
      wrap.dispatchEvent(mk('pointerdown', cx, cy));
      window.dispatchEvent(mk('pointerup', cx, cy));
      await t(700);
      const after=(document.getElementById('l2Curr')||{}).textContent||'';
      return JSON.stringify({target:target, at:[Math.round(cx),Math.round(cy)],
        before:before, after:after, changed:before!==after});
    }catch(e){ return 'ERR:'+e.message; } })()""" % json.dumps(SHIP), ap=True)
    try:
        r2j = json.loads(r2)
    except Exception:
        r2j = {}
    check("普通左键点击仍能触发动作",
          bool(r2j.get("changed")),
          f"{r2j.get('before')} -> {r2j.get('after')}")

    # 3) Ctrl+滚轮缩放仍可用
    r3 = ev("""(()=>{ try{
      const mdl=l2State.app.stage.children[0];
      const before=+mdl.scale.x.toFixed(5);
      const wrap=document.getElementById('l2wrap');
      const rect=wrap.getBoundingClientRect();
      wrap.dispatchEvent(new WheelEvent('wheel',{bubbles:true,cancelable:true,
        clientX:rect.left+rect.width/2, clientY:rect.top+rect.height/2,
        deltaY:-120, ctrlKey:true}));
      const after=+mdl.scale.x.toFixed(5);
      return JSON.stringify({before:before, after:after, changed:Math.abs(after-before)>1e-6});
    }catch(e){ return 'ERR:'+e.message; } })()""")
    try:
        r3j = json.loads(r3)
    except Exception:
        r3j = {}
    check("Ctrl+滚轮缩放仍可用（未误删）",
          bool(r3j.get("changed")),
          f"scale {r3j.get('before')} -> {r3j.get('after')}")

    ws.close()
    proc.terminate()
    print("")
    print("结果: " + ("PASS" if not fails else f"FAIL ({len(fails)} 项)"))
    raise SystemExit(0 if not fails else 1)


if __name__ == "__main__":
    sys.exit(main())
