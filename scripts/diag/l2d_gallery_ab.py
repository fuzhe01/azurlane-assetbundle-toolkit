# -*- coding: utf-8 -*-
"""l2d_gallery_ab.py — 同一模型在两个画廊（旧 8777 / 新 8778）之间做渲染级 A/B。

用途：数据与资源逐字节相同、表现却不同的情况（2026-10-23 ougen_8 左腿：
两个画廊的 moc3/贴图/physics/55 个 motion 全部 SAME，但旧画廊腿正常、新画廊缺一块），
差异只可能在前端渲染行为。本脚本用**同一台机器、同一个探针、同一组 drawable 判据**
分别打两个画廊，输出可直接对账的逐 drawable 状态表。

判据（不依赖画布像素：headless 下 drawImage(app.view) 常取到全 0 缓冲）：
  · 每个 drawable 的 opacity / dynamicFlagIsVisible / renderOrder
  · 指定关注 mesh 的 bbox
  · WebGL renderer 字符串（确认两侧同渲染路径）
两侧状态表逐项 diff，列出「旧可见／新不可见」与反向的条目。

用法:
  py -3.14 scripts/diag/l2d_gallery_ab.py --ship ougen_8 --motion idle
  py -3.14 scripts/diag/l2d_gallery_ab.py --ship ougen_8 --motion idle --focus ArtMesh517,ArtMesh518
"""
import sys, os, json, time, subprocess, urllib.request

sys.stdout.reconfigure(encoding="utf-8")
import websocket

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import chrome_tree        # 整树清理：atexit + profile 回读（见该模块 docstring）

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CAND = [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"]
BROWSER = next((c for c in CAND if os.path.isfile(c)), None)


def arg(n, d=None):
    return sys.argv[sys.argv.index(n) + 1] if n in sys.argv else d


SHIP = arg("--ship", "ougen_8")
MOTION = arg("--motion", "idle")
FOCUS = [x for x in (arg("--focus", "") or "").split(",") if x]
SIDES = [("old", 8777, 9391), ("new", 8778, 9392)]


class Probe:
    def __init__(self, port, profile):
        self.port, self.profile = port, profile
        self.ws = None
        self._id = 0

    def open(self, url):
        ps = ("$ErrorActionPreference='SilentlyContinue';"
              "Get-CimInstance Win32_Process -Filter \"Name='msedge.exe'\" | "
              "Where-Object { $_.CommandLine -like '*%s*' } | "
              "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" % self.profile)
        subprocess.run(["powershell.exe", "-NoProfile", "-Command", ps],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.5)
        self.proc = subprocess.Popen([
            BROWSER, f"--remote-debugging-port={self.port}", "--remote-allow-origins=*",
            f"--user-data-dir={self.profile}", "--no-first-run", "--no-default-browser-check",
            "--headless=new", "--gpu", "--window-size=1400,950", url],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        chrome_tree.install(self.proc)   # atexit 兜底：判据落在 profile 回读上（见 chrome_tree docstring）
        for _ in range(120):
            try:
                for t in json.load(urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json")):
                    if "gallery_v2" in t.get("url", "") and t.get("webSocketDebuggerUrl"):
                        self.ws = websocket.create_connection(t["webSocketDebuggerUrl"], timeout=90)
                        break
                if self.ws:
                    break
            except Exception:
                pass
            time.sleep(0.5)
        if not self.ws:
            raise SystemExit(f"CDP 失败 port={self.port}")
        self.cmd("Page.enable")
        self.cmd("Runtime.enable")
        self.cmd("Network.enable")
        self.cmd("Network.setCacheDisabled", {"cacheDisabled": True})

    def cmd(self, m, p=None):
        self._id += 1
        self.ws.send(json.dumps({"id": self._id, "method": m, "params": p or {}}))
        while True:
            r = json.loads(self.ws.recv())
            if r.get("id") == self._id:
                if "error" in r:
                    raise RuntimeError(str(r["error"])[:200])
                return r.get("result", {})

    def ev(self, e, ap=False):
        r = self.cmd("Runtime.evaluate", {"expression": e, "returnByValue": True, "awaitPromise": ap})
        if r.get("exceptionDetails"):
            return "EVALERR " + str(r["exceptionDetails"].get("text"))[:200]
        return r.get("result", {}).get("value")

    def wait_model(self, tries=140):
        for _ in range(tries):
            if self.ev("(typeof l2State!=='undefined'&&l2State&&l2State.app&&"
                       "l2State.app.stage.children[0]&&"
                       "l2State.app.stage.children[0].internalModel)?1:0") == 1:
                return True
            time.sleep(0.5)
        return False

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass
        try:
            self.proc.terminate()
        except Exception:
            pass


SNAP_JS = r"""(()=>{ try{
  const app=l2State.app, mdl=app.stage.children[0], im=mdl.internalModel;
  const core=im.coreModel, ppu=im.pixelsPerUnit||1;
  const cux=im.width/ppu, cuy=im.height/ppu, s=mdl.scale.x;
  const toStage=(vx,vy)=>[mdl.x+(vx+cux/2)*ppu*s, mdl.y+(cuy/2-vy)*ppu*s];
  const nd=core.getDrawableCount(); const rows=[];
  let ros=[]; try{ ros=core.getDrawableRenderOrders()||[]; }catch(e){}
  for(let i=0;i<nd;i++){
    let id='?', op=null, vis=0, bb=null;
    try{ id=core.getDrawableId(i); }catch(e){}
    try{ op=+core.getDrawableOpacity(i).toFixed(4); }catch(e){}
    try{ vis=core.getDrawableDynamicFlagIsVisible(i)?1:0; }catch(e){}
    try{ const p=core.getDrawableVertexPositions(i);
      if(p&&p.length>=4){ let x0=1e9,y0=1e9,x1=-1e9,y1=-1e9;
        for(let k=0;k+1<p.length;k+=2){ const st=toStage(p[k],p[k+1]);
          if(st[0]<x0)x0=st[0]; if(st[0]>x1)x1=st[0];
          if(st[1]<y0)y0=st[1]; if(st[1]>y1)y1=st[1]; }
        if(x1>=x0&&y1>=y0) bb=[Math.round(x0),Math.round(y0),Math.round(x1),Math.round(y1)]; }
    }catch(e){}
    rows.push({id:id, op:op, vis:vis, ro:ros.length?ros[i]:null, bb:bb});
  }
  let vend='?', rnd='?';
  try{ const gl=app.renderer&&app.renderer.gl, dbg=gl&&gl.getExtension('WEBGL_debug_renderer_info');
    if(dbg){ vend=gl.getParameter(dbg.UNMASKED_VENDOR_WEBGL); rnd=gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL); } }catch(e){}
  const params={}; try{ const ids=(core._model&&core._model.parameters&&core._model.parameters.ids)||[];
    for(let i=0;i<ids.length;i++){ try{ params[ids[i]]=+core.getParameterValueByIndex(i).toFixed(3); }catch(e){} } }catch(e){}
  return JSON.stringify({nd:nd, res:app.renderer&&app.renderer.resolution,
    bufW:app.renderer.width, bufH:app.renderer.height,
    cssW:document.getElementById('l2wrap')&&document.getElementById('l2wrap').clientWidth,
    dpr:window.devicePixelRatio, vendor:vend, renderer:rnd,
    mdl:{x:+mdl.x.toFixed(2), y:+mdl.y.toFixed(2), s:+mdl.scale.x.toFixed(5)},
    params:params, rows:rows});
}catch(e){ return 'ERR:'+e.message; } })()"""


def play_motion(pr, motion):
    """把模型停到一个**确定性状态**：播动作 → 停住 → 回到第 0 帧采样。

    为什么不能直接播完就比：两侧动作相位不同（实测 mdl.y 差 16.5px），
    逐 drawable 对比会混入"动作进度不同"的噪声，得不出"谁缺部件"的结论。
    做法：startMotion 后用 mt.stopAllMotions() 冻结，并显式 setParameterValueByIndex
    铺一遍该动作第 0 帧的值 —— 两侧拿到的是同一姿态。
    """
    js = f"""(async()=>{{ try{{
      const t=ms=>new Promise(r=>setTimeout(r,ms));
      const mdl=l2State.app.stage.children[0]; const mm=mdl.internalModel.motionManager;
      const G={json.dumps(motion)};
      if(!(mm.definitions||{{}})[G]) return 'NO_GROUP';
      const defs=mm.definitions[G]; if(!defs||!defs.length) return 'NO_DEFS';
      /* 先正常起播，让库把 motion 解析好 */
      try{{ mm.startMotion(G,0,3); }}catch(e){{}}
      await t(900);
      /* 冻结：停在当前帧，消除两侧相位差 */
      try{{ mm.stopAllMotions(); }}catch(e){{}}
      await t(120);
      const core=mdl.internalModel.coreModel;
      /* 显式铺第 0 帧参数值（从已解析的 motion 对象读，拿不到就保持冻结态） */
      let applied=0;
      try{{
        const d2=(mm.definitions||{{}})[G]||[];
        const mo=d2[0]&&d2[0]._motion&&d2[0]._motion._model;
        if(mo&&mo.curves){{
          for(const c of mo.curves){{
            let pid=null; try{{ pid=c._targetId||(c.target&&c.target._id)||c._id; }}catch(e){{}}
            if(!pid) continue;
            let v=null; try{{ v=c.evaluate(0,0); }}catch(e){{}}
            if(v==null) continue;
            try{{ core.setParameterValueById(pid, v); applied++; }}catch(e){{}}
          }}
        }}
      }}catch(e){{}}
      try{{ core.update(); }}catch(e){{}}
      try{{ l2State.app.renderer.render(l2State.app.stage); }}catch(e){{}}
      await t(200);
      return 'frozen applied='+applied;
    }}catch(e){{ return 'ERR:'+e.message; }} }})()"""
    return pr.ev(js, ap=True)


def main():
    results = {}
    for tag, srv, port in SIDES:
        prof = os.path.join(ROOT, ".diag", f"chrome_ab_{tag}_{port}")
        url = f"http://127.0.0.1:{srv}/gallery_v2/index.html?ship={SHIP}&_t={int(time.time()*1000)}"
        pr = Probe(port, prof)
        try:
            pr.open(url)
        except SystemExit as e:
            print(f"[{tag}] {e}")
            continue
        if not pr.wait_model():
            print(f"[{tag}] 模型未就绪（可能旧画廊不支持 ?ship=）")
            # 旧画廊没有 ?ship= 支持，退回点击路径
            pr.ev(f"""(()=>{{ try{{
              const q=document.getElementById('search');
              if(q){{ q.value={json.dumps(SHIP.split('_')[0])};
                q.dispatchEvent(new Event('input',{{bubbles:true}})); }}
            }}catch(e){{}} return 1; }})()""")
            time.sleep(1.2)
            pr.ev(f"""(()=>{{ try{{
              const card=[...document.querySelectorAll('.card')].find(c=>{{
                const p=c.querySelector('.py'); return p&&p.textContent.trim().startsWith({json.dumps(SHIP.split('_')[0])}); }});
              if(card) card.click();
            }}catch(e){{}} return 1; }})()""")
            time.sleep(1.0)
            pr.ev(f"""(()=>{{ try{{
              const sk=document.querySelector('.skin[data-k="{SHIP}"]');
              if(sk) sk.click();
            }}catch(e){{}} return 1; }})()""")
            time.sleep(1.0)
            pr.ev("""(()=>{ try{ const tb=[...document.querySelectorAll('#mTabs .tab')].find(x=>x.dataset.k==='live2d');
              if(tb&&!tb.classList.contains('dis')) tb.click(); }catch(e){} return 1; })()""")
            if not pr.wait_model():
                print(f"[{tag}] 仍然未就绪，跳过")
                pr.close()
                continue
        pm = play_motion(pr, MOTION)
        time.sleep(1.2)
        snap = pr.ev(SNAP_JS)
        try:
            results[tag] = json.loads(snap)
            results[tag]["_play"] = pm
        except Exception:
            print(f"[{tag}] 快照失败: {str(snap)[:200]}")
        pr.close()

    if len(results) < 2:
        print("两侧未都取到数据，无法对照")
        return 1

    old, new = results.get("old"), results.get("new")
    print("\n" + "=" * 72)
    for tag in ("old", "new"):
        d = results[tag]
        print(f"[{tag}] drawable={d['nd']} res={d['res']} buf={d['bufW']}x{d['bufH']} "
              f"css={d['cssW']} dpr={d['dpr']}")
        print(f"      mdl={d['mdl']} renderer={str(d['renderer'])[:70]}")
        print(f"      play={d.get('_play')}")

    ro = {r["id"]: r for r in old["rows"]}
    rn = {r["id"]: r for r in new["rows"]}
    common = sorted(set(ro) & set(rn))
    print(f"\n共同 drawable: {len(common)}  仅旧:{len(set(ro) - set(rn))}  仅新:{len(set(rn) - set(ro))}")

    only_old = [(k, ro[k], rn[k]) for k in common
                if (ro[k]["vis"] == 1 and (ro[k]["op"] or 0) >= 0.5)
                and (rn[k]["vis"] != 1 or (rn[k]["op"] or 0) < 0.5)]
    only_new = [(k, ro[k], rn[k]) for k in common
                if (rn[k]["vis"] == 1 and (rn[k]["op"] or 0) >= 0.5)
                and (ro[k]["vis"] != 1 or (ro[k]["op"] or 0) < 0.5)]
    print(f"\n【旧可见 / 新不可见】{len(only_old)} 个  <== 这类是「新画廊缺东西」的元凶")
    for k, a, b in only_old[:25]:
        print(f"  {k:<14} 旧 op={a['op']} vis={a['vis']} ro={a['ro']} bb={a['bb']}"
              f"  |  新 op={b['op']} vis={b['vis']} ro={b['ro']} bb={b['bb']}")
    print(f"\n【新可见 / 旧不可见】{len(only_new)} 个")
    for k, a, b in only_new[:15]:
        print(f"  {k:<14} 旧 op={a['op']} vis={a['vis']}  |  新 op={b['op']} vis={b['vis']}")

    # 参数差异
    po, pn = old.get("params") or {}, new.get("params") or {}
    pd = [(k, po.get(k), pn.get(k)) for k in set(po) & set(pn)
          if po.get(k) is not None and pn.get(k) is not None
          and abs(po[k] - pn[k]) > 0.05]
    pd.sort(key=lambda t: -abs(t[1] - t[2]))
    print(f"\n参数差异(>0.05) {len(pd)} 个，前 15:")
    for k, a, b in pd[:15]:
        print(f"  {k:<20} 旧={a:>9.3f}  新={b:>9.3f}")

    if FOCUS:
        print("\n关注 mesh 两侧状态:")
        for k in FOCUS:
            a, b = ro.get(k), rn.get(k)
            print(f"  {k}: 旧 {a} \n          新 {b}")

    json.dump(results, open(os.path.join(ROOT, ".diag", "gallery_ab.json"), "w",
                            encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n明细 -> .diag/gallery_ab.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
