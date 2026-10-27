# -*- coding: utf-8 -*-
"""l2d_costume_writable_probe.py — 验证候选参数「运行时到底能不能被写入」。

为什么必须验：导出曾按「动作间出现多档值」筛参数，但**能不能写**是另一回事——
  实测 benningdun_2 的 GloveSwitch_L：min=max=default=0，
  连 core.setParameterValueById(…, 2) 都无法保持（读回仍是 0）。这类参数在面板上
  点了没反应，属假交互，必须剔除。
判据：写入值 v 后隔 ≥2 帧回读 |read - v| < 1e-3 ⇒ 可写；否则剔除。
同时记录「写入是否改变画面」（像素哈希），用于区分「可写但无可见效果」的备用参数。

用法:
  py -3.14 scripts/diag/l2d_costume_writable_probe.py --ship benningdun_2
  py -3.14 scripts/diag/l2d_costume_writable_probe.py --all --limit 20
输出: .diag/costume_writable.json  结构 {模型: {参数: {writable, visible, sampled}}}
"""
import sys, os, json, time, subprocess, urllib.request

sys.stdout.reconfigure(encoding="utf-8")
import websocket

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import chrome_tree        # 整树清理：atexit + profile 回读（见该模块 docstring）

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CAND = [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:/Program Files/Google/Chrome/Application/chrome.exe"]
BROWSER = next((c for c in CAND if os.path.isfile(c)), None)
PORT = int(os.environ.get("CW_PORT", "9375"))
SRV = "8778"
PROFILE = os.path.join(ROOT, ".diag", f"chrome_coswrite_{PORT}")
COSTUME = os.path.join(ROOT, "Output", "gallery_v2", "costume_params.json")
OUT = os.path.join(ROOT, ".diag", "costume_writable.json")


def arg(n, d=None):
    return sys.argv[sys.argv.index(n) + 1] if n in sys.argv else d


class Probe:
    def __init__(self, port):
        self.port = port
        self.ws = None
        self.pid = None
        self._id = 0

    def open(self, url):
        ps = ("$ErrorActionPreference='SilentlyContinue';"
              "Get-CimInstance Win32_Process -Filter \"Name='msedge.exe'\" | "
              "Where-Object { $_.CommandLine -like '*%s*' } | "
              "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" % PROFILE)
        subprocess.run(["powershell.exe", "-NoProfile", "-Command", ps],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.5)
        self.proc = chrome_tree.launch([
            BROWSER, f"--remote-debugging-port={self.port}", "--remote-allow-origins=*",
            f"--user-data-dir={PROFILE}", "--no-first-run", "--no-default-browser-check",
            "--headless=new", "--gpu", "--window-size=1300,900", url],
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
            raise SystemExit("CDP 失败")
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

    def wait_model(self, tries=120):
        for _ in range(tries):
            if self.ev("(typeof l2State!=='undefined'&&l2State&&l2State.app&&"
                       "l2State.app.stage.children[0]&&l2State.app.stage.children[0].internalModel)?1:0") == 1:
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


PROBE_JS = r"""(()=>{ try{
  const app=l2State.app, mdl=app.stage.children[0], core=mdl.internalModel.coreModel;
  const items=%s;
  const cv=document.createElement('canvas');
  cv.width=160; cv.height=Math.round(160*app.renderer.height/app.renderer.width);
  const g=cv.getContext('2d',{willReadFrequently:true});
  const hash=()=>{ try{ g.clearRect(0,0,cv.width,cv.height);
    g.drawImage(app.view,0,0,cv.width,cv.height);
    const d=g.getImageData(0,0,cv.width,cv.height).data;
    let h=2166136261>>>0; for(let i=0;i<d.length;i+=32){ h^=d[i]; h=Math.imul(h,16777619)>>>0; }
    return h>>>0; }catch(e){ return -1; } };
  const out={};
  /* 不 stopAllMotions：停掉动作后模型停在静止帧，很多装扮部件的 keyform 依赖动作姿势，
     静止帧下改参数可能看不到任何像素变化（会把"可写且有视觉"误判成"不可写"）。
     改为：写入后用 beforeModelUpdate 每帧重申（与前端换装面板同一机制），
     等真实渲染帧跑过再比对，等价于用户实际使用的路径。 */
  const draw=()=>{ try{ core.update(); }catch(e){}
    try{ app.renderer.render(app.stage); }catch(e){} };
  for(const it of items){
    const k=it.id, vals=(it.vals&&it.vals.length)?it.vals:[];
    const rec={writable:false, visible:false, sampled:0};
    try{
      const before=+core.getParameterValueById(k);
      const h0=hash();
      let kept=0, tried=0, changed=false;
      for(const v of vals){
        if(Math.abs(v-before)<1e-6) continue;
        tried++;
        /* 判"可写"必须复刻前端的真实使用方式：前端换装面板每帧在 beforeModelUpdate
           重申一次 pin 值（否则动作 loadParameters 会把曲线值铺回来）。
           探针只用一次 write+update 会读到"刚写入"的假可写（benningdun_2 的
           GloveSwitch_L 正是如此：单次读像可写，下一帧回 0）。
           这里连写 3 帧再读，读到的才是用户实际会看到的稳定值。 */
        for(let f=0; f<3; f++){ core.setParameterValueById(k, v); draw(); }
        const back=+core.getParameterValueById(k);
        if(Math.abs(back-v)<1e-3) kept++;
        else { try{ core.setParameterValueById(k, before); }catch(e){} }
      }
      rec.sampled=tried;
      rec.writable = tried>0 && kept>0;
      /* 可见性：写到第一个可保持的值后对比画面。
         ⚠️ 必须用 app.renderer.render() 走完整渲染（只 core.update() 不刷新画面 → 全判"无变化"，
            2026-10-23 实测踩到：20 条参数全被判不可见）。 */
      if(rec.writable){
        /* 可见性判据**不依赖像素**：headless 下 drawImage(app.view) 常取到全 0 缓冲
           （实测 nz0），像素哈希会恒等于同一值 → 把"有视觉"误判成"无视觉"。
           改为看这个参数是否改变任意 drawable 的 opacity/visible —— 与渲染结果等价，
           且不受读帧时机影响。 */
        const nd=core.getDrawableCount();
        const snap=()=>{ const a=[];
          for(let i=0;i<nd;i++){ let op=null, vis=0;
            try{ op=core.getDrawableOpacity(i); }catch(e){}
            try{ vis=core.getDrawableDynamicFlagIsVisible(i)?1:0; }catch(e){}
            a.push([op,vis]); }
          return a; };
        core.setParameterValueById(k, before); draw(); const s0=snap();
        let nchg=0, sample=[];
        for(const v of vals){ if(Math.abs(v-before)<1e-6) continue;
          core.setParameterValueById(k, v); draw();
          const s1=snap();
          let c=0;
          for(let i=0;i<nd;i++){
            const a=s0[i], b=s1[i];
            if(!a||!b) continue;
            if(a[1]!==b[1] || (a[0]!=null&&b[0]!=null&&Math.abs(a[0]-b[0])>0.02)){
              c++; if(sample.length<6){ let id='?'; try{ id=core.getDrawableId(i); }catch(e){}
                sample.push(id+'@'+v); } } }
          if(c>0){ changed=true; nchg=c; break; }
        }
        core.setParameterValueById(k, before); draw();
        rec.changedDrawables=nchg; rec.sample=sample;
      }
      rec.visible=changed;
    }catch(e){ rec.err=String(e&&e.message||e); }
    out[k]=rec;
  }
  return JSON.stringify(out);
}catch(e){ return 'ERR:'+String(e&&e.message||e); } })()"""


def probe_model(pr, model, items):
    url = f"http://127.0.0.1:{SRV}/gallery_v2/index.html?ship={model}&_t={int(time.time()*1000)}"
    pr.cmd("Page.navigate", {"url": url})
    if not pr.wait_model():
        return None
    for _ in range(60):   # 等换装表
        if pr.ev("!!window.COSTUME && Object.keys(window.COSTUME).length>0") is True:
            break
        time.sleep(0.4)
    r = pr.ev(PROBE_JS % json.dumps(items), ap=True)
    try:
        return json.loads(r)
    except Exception:
        return {"__err__": str(r)[:200]}


def main():
    data = json.load(open(COSTUME, encoding="utf-8"))
    if "--all" in sys.argv:
        lim = int(arg("--limit", "0"))
        models = sorted(data)[:lim] if lim else sorted(data)
    else:
        models = [arg("--ship", "benningdun_2")]

    pr = Probe(PORT)
    pr.open(f"http://127.0.0.1:{SRV}/gallery_v2/index.html")
    results = {}
    for i, m in enumerate(models, 1):
        items = data.get(m) or []
        if not items:
            continue
        r = probe_model(pr, m, items)
        if not r or "__err__" in (r or {}):
            print(f"  [{i}/{len(models)}] {m}: 失败 {str((r or {}).get('__err__'))[:80]}", flush=True)
            continue
        nw = sum(1 for v in r.values() if v.get("writable"))
        nv = sum(1 for v in r.values() if v.get("visible"))
        results[m] = r
        print(f"  [{i}/{len(models)}] {m}: 可写 {nw}/{len(items)}，其中有可见效果 {nv}", flush=True)
    pr.close()

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(results, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    tot = sum(len(v) for v in results.values())
    nw = sum(1 for v in results.values() for x in v.values() if x.get("writable"))
    nv = sum(1 for v in results.values() for x in v.values() if x.get("visible"))
    print("\n" + "=" * 60)
    print(f"验证 {len(results)} 个模型 / {tot} 条参数")
    print(f"  可写 {nw} 条；可写且视觉有变化 {nv} 条")
    print(f"  明细 -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
