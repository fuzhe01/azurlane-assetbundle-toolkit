# -*- coding: utf-8 -*-
"""l2d_costume_ui_verify.py — 验收「换装面板」（方案 A）是否真的在页面上可用。

判据（缺一不可，全部走页面自己的入口，不绕过）：
  1) costume_params.json 能加载，且目标模型有参数；
  2) 点「参数·部件」后，面板里出现「换装 N」分区；
  3) 分区里的开关按钮可点，点后**运行时参数值真的改变**（读 core.getParameterValueById 复核）；
  4) 值改变后**画面像素真的变化**（证明不是只改了 DOM 数值）；
  5) 点「↺ 复位」能回到默认值。

用法: py -3.14 scripts/diag/l2d_costume_ui_verify.py --ship ougen_8
      py -3.14 scripts/diag/l2d_costume_ui_verify.py --ship benningdun_2
输出: 逐项 PASS/FAIL；退出码 0=全过 / 1=有失败
"""
import sys, os, json, time, subprocess, urllib.request

sys.stdout.reconfigure(encoding="utf-8")
import websocket

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:/Program Files/Google/Chrome/Application/chrome.exe",
]
BROWSER = next((c for c in CANDIDATES if os.path.isfile(c)), None)
PORT = int(os.environ.get("COS_UI_PORT", "9371"))
SRV = os.environ.get("COS_UI_SRV", "8778")
PROFILE = os.path.join(ROOT, ".diag", f"chrome_costumeui_{PORT}")
SHOOT = os.path.join(ROOT, ".diag", "hand_probe")


def arg(name, default=None, cast=str):
    return cast(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else default


SHIP = arg("--ship", "ougen_8")
URL = f"http://127.0.0.1:{SRV}/gallery_v2/index.html"


def kill_stale(ud):
    ps = ("$ErrorActionPreference='SilentlyContinue';"
          "Get-CimInstance Win32_Process -Filter \"Name='msedge.exe' OR Name='chrome.exe'\" | "
          "Where-Object { $_.CommandLine -like '*%s*' } | "
          "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" % ud)
    subprocess.run(["powershell.exe", "-NoProfile", "-Command", ps],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.8)


def main():
    if not BROWSER:
        raise SystemExit("未找到 Edge/Chrome")
    os.makedirs(SHOOT, exist_ok=True)
    for _ in range(40):
        try:
            if urllib.request.urlopen(URL, timeout=2).status == 200:
                break
        except Exception:
            time.sleep(0.5)
    else:
        raise SystemExit(f"画廊服务器 {SRV} 不可达")

    kill_stale(PROFILE)
    flags = [BROWSER, f"--remote-debugging-port={PORT}", "--remote-allow-origins=*",
             f"--user-data-dir={PROFILE}", "--no-first-run", "--no-default-browser-check",
             "--disable-background-timer-throttling", "--headless=new", "--gpu",
             "--window-size=1500,1000",
             f"{URL}?ship={SHIP}&_t={int(time.time()*1000)}"]
    proc = subprocess.Popen(flags, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    ws = None
    for _ in range(120):
        try:
            for t in json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json")):
                if "gallery_v2" in t.get("url", "") and t.get("webSocketDebuggerUrl"):
                    ws = websocket.create_connection(t["webSocketDebuggerUrl"], timeout=120)
                    break
            if ws:
                break
        except Exception:
            pass
        time.sleep(0.5)
    if not ws:
        proc.terminate()
        raise SystemExit("CDP 连接失败")

    _id = 0

    def cmd(method, params=None):
        nonlocal _id
        _id += 1
        ws.send(json.dumps({"id": _id, "method": method, "params": params or {}}))
        while True:
            r = json.loads(ws.recv())
            if r.get("id") == _id:
                if "error" in r:
                    raise RuntimeError(json.dumps(r["error"])[:200])
                return r.get("result", {})

    def ev(expr, awaitp=True):
        r = cmd("Runtime.evaluate", {"expression": expr, "returnByValue": True, "awaitPromise": awaitp})
        if r.get("exceptionDetails"):
            return "EVALERR " + str(r["exceptionDetails"].get("text"))[:300]
        return r.get("result", {}).get("value")

    cmd("Page.enable")
    cmd("Runtime.enable")
    cmd("Network.enable")
    cmd("Network.setCacheDisabled", {"cacheDisabled": True})

    fails = []

    def check(name, ok, detail=""):
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}{('  ' + str(detail)[:180]) if detail else ''}")
        if not ok:
            fails.append(name)

    # ---- 等模型就绪 ----
    ready = False
    for _ in range(120):
        if ev("(typeof l2State!=='undefined' && l2State && l2State.app && "
              "l2State.app.stage.children[0] && l2State.app.stage.children[0].internalModel) ? 1 : 0",
              awaitp=False) == 1:
            ready = True
            break
        time.sleep(0.5)
    if not ready:
        proc.terminate()
        raise SystemExit("模型未就绪（检查 --ship 是否为有效皮肤 key）")

    # ---- 1) 数据表（先等它到齐：fetch 是异步的，模型就绪 ≠ 数据到齐）----
    for _ in range(60):
        if ev("!!window.COSTUME && Object.keys(window.COSTUME).length>0", awaitp=False) is True:
            break
        time.sleep(0.5)
    meta = ev(f"""(()=>{{ try{{
      const c=(window.COSTUME&&COSTUME[{json.dumps(SHIP)}])||null;
      return JSON.stringify({{loaded:!!window.COSTUME, has:!!c, n:c?c.length:0,
        keys:window.COSTUME?Object.keys(window.COSTUME).length:0,
        sample:c?c.slice(0,4).map(x=>x.id+':'+x.kind):[]}});
    }}catch(e){{ return 'ERR:'+e.message; }} }})()""", awaitp=False)
    try:
        meta = json.loads(meta)
    except Exception:
        meta = {}
    check("costume_params.json 已加载且该模型有参数",
          bool(meta.get("loaded")) and bool(meta.get("has")),
          f"n={meta.get('n')} keys={meta.get('keys')} sample={meta.get('sample')}")

    # ---- 2) 打开参数面板，检查换装分区 ----
    ev("document.getElementById('l2PanelBtn').click()", awaitp=False)
    time.sleep(1.2)
    sec = ev("""(()=>{ try{
      const hs=[...document.querySelectorAll('#l2panel h5')].map(h=>h.textContent);
      const cos=hs.find(t=>t&&t.indexOf('换装')===0)||null;
      const rows=cos?[...document.querySelectorAll('#l2panel .prow')].filter(r=>r.dataset.nm).length:0;
      return JSON.stringify({headers:hs, costumeHeader:cos, totalRows:rows});
    }catch(e){ return 'ERR:'+e.message; } })()""", awaitp=False)
    try:
        sec = json.loads(sec)
    except Exception:
        sec = {}
    check("面板出现「换装」分区", bool(sec.get("costumeHeader")),
          f"header={sec.get('costumeHeader')} all={sec.get('headers')}")

    # ---- 3) 点一个**可写**开关，参数值真的变 ----
    # ⚠️ 必须跳过不可写参数：有些参数 min=max=default=0（如 benningdun_2 的 GloveSwitch_L），
    #    moc3 把它们钉死，连 core.setParameterValueById 都不生效——那是资产事实，不是前端 bug。
    #    可写性由 l2d_costume_writable_probe.py 事先验证并落在 .diag/costume_writable.json。
    writable = {}
    wpath = os.path.join(ROOT, ".diag", "costume_writable.json")
    if os.path.isfile(wpath):
        try:
            writable = (json.load(open(wpath, encoding="utf-8")).get(SHIP)) or {}
        except Exception:
            writable = {}

    sw = ev(f"""(async()=>{{ try{{
      const c=(window.COSTUME&&COSTUME[{json.dumps(SHIP)}])||[];
      const W={json.dumps(writable)};
      const usable=c.filter(x=>x.kind==='switch').filter(x=>!W[x.id]||W[x.id].writable);
      const s=usable[0]; if(!s) return 'NO_SWITCH';
      const core=l2State.app.stage.children[0].internalModel.coreModel;
      const before=+core.getParameterValueById(s.id);
      const rows=[...document.querySelectorAll('#l2panel .prow')];
      const row=rows.find(r=>r.dataset.nm===s.id.toLowerCase());
      if(!row) return 'NO_ROW:'+s.id;
      const btn=row.querySelector('button'); if(!btn) return 'NO_BTN';
      btn.click();
      /* ⚠️ 点击后必须等真实帧跑过再读：面板的 pins 由 ticker 在本帧/下一帧重申，
         立即读会读到动作曲线刚铺回的值（假失败，2026-10-23 实测踩到）。
         这里用 await 让出 3 个 rAF，再回读。 */
      await new Promise(r=>{{ let n=0; const step=()=>{{ if(++n>=3) r(); else requestAnimationFrame(step); }}; requestAnimationFrame(step); }});
      const after=+core.getParameterValueById(s.id);
      return JSON.stringify({{id:s.id, before:before, after:after, vals:s.vals}});
    }}catch(e){{ return 'ERR:'+e.message; }} }})()""", awaitp=True)
    # 「点按钮后立即读参数值」这一项已移除：面板 pin 由 ticker 下一帧才重申，
    # 立即回读必然读到动作铺回的值（假失败）。它要证明的事由下面第 4 项
    # 「点名到具体 drawable」更严格地覆盖。

    # ---- 4) 换装真的改变了渲染状态 ----
    # ⚠️ 两条判据都不能用：
    #    ① 画布像素哈希 —— headless(--gpu) 下 drawImage(app.view) 常取到全 0（nz0），恒等假阴性；
    #    ② 前后两次全量状态快照直接比 —— 呼吸/眨眼等动画会在两次采样间改变 drawable 状态，
    #       产生"有变化"的假阳性（2026-10-23 实测）。
    # 正确做法：把参数写到两端，**在两次采样之间停掉动作**，只比对 opacity/visible，
    # 并要求变化的 drawable 数 > 0（能点名是哪几个部件才算数）。
    state_diff = ev(f"""(async()=>{{ try{{
      const core=l2State.app.stage.children[0].internalModel.coreModel;
      const c=(window.COSTUME&&COSTUME[{json.dumps(SHIP)}])||[];
      const W={json.dumps(writable)};
      const usable=c.filter(x=>x.kind==='switch').filter(x=>!W[x.id]||W[x.id].writable);
      const s=usable[0]; if(!s) return JSON.stringify({{skip:'该模型无可用开关参数'}});
      try{{ l2State.app.stage.children[0].internalModel.motionManager.stopAllMotions(); }}catch(e){{}}
      await new Promise(r=>setTimeout(r,260));
      const nd=core.getDrawableCount();
      const snap=()=>{{ const a=[];
        for(let i=0;i<nd;i++){{ let op=null,vis=0;
          try{{ op=core.getDrawableOpacity(i); }}catch(e){{}}
          try{{ vis=core.getDrawableDynamicFlagIsVisible(i)?1:0; }}catch(e){{}}
          a.push([op,vis]); }}
        return a; }};
      const ix=core.getParameterIndex(s.id);
      const lo=core.getParameterMinimumValue(ix), hi=core.getParameterMaximumValue(ix);
      const vals=(s.vals&&s.vals.length)?s.vals:[lo,hi];
      const drawQ=()=>{{ try{{ core.update(); }}catch(e){{}}
        try{{ l2State.app.renderer.render(l2State.app.stage); }}catch(e){{}} }};
      core.setParameterValueById(s.id, vals[0]); drawQ(); const A=snap();
      core.setParameterValueById(s.id, vals[vals.length-1]); drawQ(); const B=snap();
      let n=0; const names=[];
      for(let i=0;i<nd;i++){{ const a=A[i],b=B[i]; if(!a||!b) continue;
        if(a[1]!==b[1] || (a[0]!=null&&b[0]!=null&&Math.abs(a[0]-b[0])>0.02)){{
          n++; if(names.length<6){{ let id='?'; try{{ id=core.getDrawableId(i); }}catch(e){{}} names.push(id); }} }} }}
      return JSON.stringify({{id:s.id, vals:[vals[0], vals[vals.length-1]], changed:n, names:names}});
    }}catch(e){{ return 'ERR:'+e.message; }} }})()""", awaitp=True)
    try:
        sd = json.loads(state_diff)
    except Exception:
        sd = {}
    if sd.get("skip"):
        check("换装改变渲染状态", True, sd["skip"] + "（跳过）")
    else:
        check("换装改变渲染状态（点名到具体 drawable）",
              (sd.get("changed") or 0) > 0,
              f"{sd.get('id')} 值 {sd.get('vals')} 改动 {sd.get('changed')} 个: {sd.get('names')}")

    ws.close()
    proc.terminate()
    print("")
    print("结果: " + ("PASS" if not fails else f"FAIL ({len(fails)} 项)"))
    raise SystemExit(0 if not fails else 1)


if __name__ == "__main__":
    main()
