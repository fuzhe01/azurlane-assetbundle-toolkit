# -*- coding: utf-8 -*-
"""l2d_hand_probe.py — Live2D 手掌是否被真正画出（渲染级像素判据，只读探针）。

背景：ougen_8 mail 动作「手掌消失」只在用户真实浏览器复现，headless 全绿（§136）。
本探针把「状态层」与「渲染层」用两条独立判据拆开：

  状态层（Cubism core 直接读）: 手部 mesh 的 opacity / dynamic-visible / blend / renderOrder
  渲染层（像素）              : 把手部 mesh 顶点用页面自己的映射
                                `P=(Vx+cux/2, cuy/2-Vy) → stage=mdl.pos+P*ppu*scale`
                                投到 stage，取 bbox，统计该 bbox 内 canvas 的 alpha>8 覆盖率。
                                cover 低 + op/vis 正常 ⇒ 状态说该画、像素说没画 = 渲染被裁/被盖。

DPR 由 Emulation.setDeviceMetricsOverride 精确注入（支持 1.5 这类非整数缩放，
--force-device-scale-factor 只能整数）。--headed 用真窗口跑，用于对齐用户环境
（真实 GPU 合成路径 + 真实 DPI），这是 headless 永远测不到的那一维。

用法:
  py -3.14 scripts/diag/l2d_hand_probe.py --dpr 1.0
  py -3.14 scripts/diag/l2d_hand_probe.py --dpr 1.5 --headed --window 1707,1067
  py -3.14 scripts/diag/l2d_hand_probe.py --model ougen_8 --motion mail --frames 8
输出: 每帧一行状态 + 汇总；截图存 .diag/hand_probe/<tag>_fN.png
退出码: 0=全部帧手部正常 / 1=有帧异常 / 2=探针自身失败
"""
import sys, os, json, time, base64, subprocess, urllib.request

sys.stdout.reconfigure(encoding="utf-8")
import websocket
import chrome_tree        # 整树清理：atexit + profile 回读（见该模块 docstring）
_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (_HERE, os.path.join(_HERE, '..')):
    _p = os.path.abspath(_p)
    if _p not in sys.path: sys.path.insert(0, _p)


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:/Program Files/Google/Chrome/Application/chrome.exe",
]
BROWSER = next((c for c in CANDIDATES if os.path.isfile(c)), None)
PORT = int(os.environ.get("HAND_PROBE_PORT", "9361"))
SRV = os.environ.get("HAND_PROBE_SRV", "8778")
SHOTS = os.path.join(ROOT, ".diag", "hand_probe")
# 手部 mesh 清单：ougen_8（§136 同源），可用 --hand 覆盖
DEFAULT_HAND = ["ArtMesh111", "ArtMesh112", "ArtMesh114", "ArtMesh117",
                "ArtMesh119", "ArtMesh359", "ArtMesh159", "ArtMesh29"]


def arg(name, default=None, cast=str):
    return cast(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else default


MODEL = arg("--model", "ougen_8")
MOTION = arg("--motion", "mail")
DPR = arg("--dpr", 1.0, float)
HEADED = "--headed" in sys.argv
WIN = arg("--window", "1707,1067")
FRAMES = arg("--frames", 6, int)
STEP = arg("--step", 400, int)
HAND = [x for x in (arg("--hand", "") or "").split(",") if x] or DEFAULT_HAND
PRE = [x for x in (arg("--pre", "") or "").split(",") if x]
PRE_GAP = arg("--pre-gap", 6000, int)
UI = [x for x in (arg("--ui", "") or "").split(",") if x]
ISO = "--isolate" in sys.argv
NO_EMUL = "--no-emul" in sys.argv
HD = "--hd" in sys.argv
DIAGPOST = arg("--diagpost", "")
SHIPARG = arg("--ship", "")
HOLD = arg("--hold", 0, int)
GPU = "--gpu" in sys.argv
DIAGFRAMES = arg("--diagframes", 5, int)
SCAN = "--scan" in sys.argv
DUMPPARAMS = "--params" in sys.argv
SETPARAM = arg("--setparam", "")   # 形如 ShoseOff=1：直接写参数（状态开关的真实路径）
ABPARAM = arg("--abparam", "")     # 参数名：在同一帧内对比 0 与 1 两态（排除动作相位干扰）
FOLLOW = arg("--follow", 0, int)   # 播完跟踪：采样 N 次 currentGroup/isFinished（验回落去向）
FINDOP = arg("--findop", "")       # 目标 mesh：扫描哪个参数能改变它的 opacity/visible
SETPARAMS = arg("--setparams", "") # 批量设参数 "A=1,B=2,C=3"（--setparam 的多参数版）
PARAMSIN = arg("--paramsin", "")   # 从 JSON 文件读参数值批量注入（配合 --params 采集的快照）
DIFFBOX = arg("--diffbox", "")     # 区域 "x0,y0,x1,y1"（CSS px）：--bisect 只看这块的像素变化
FORCEVIS = [x for x in (arg("--forcevis", "") or "").split(",") if x]
BISECT_FILE = arg("--bisect", "")  # 参照参数快照 JSON：二分找出让目标区域恢复的最小参数集
DIAGSTEP = arg("--diagstep", 700, int)
TAG = arg("--tag", "") or ("head" if HEADED else "hl") + f"_dpr{DPR:g}_{MOTION}"
URL = f"http://127.0.0.1:{SRV}/gallery_v2/index.html"
PROFILE = os.path.join(ROOT, ".diag", f"chrome_handprobe_{PORT}")


def kill_stale(ud):
    ps = ("$ErrorActionPreference='SilentlyContinue';"
          "Get-CimInstance Win32_Process -Filter \"Name='msedge.exe' OR Name='chrome.exe'\" | "
          "Where-Object { $_.CommandLine -like '*%s*' } | "
          "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" % ud)
    subprocess.run(["powershell.exe", "-NoProfile", "-Command", ps],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.8)


def wait_server():
    for _ in range(40):
        try:
            if urllib.request.urlopen(URL, timeout=2).status == 200:
                return True
        except Exception:
            time.sleep(0.5)
    return False


def main():
    if not BROWSER:
        raise SystemExit("未找到 Edge/Chrome")
    os.makedirs(SHOTS, exist_ok=True)
    if not wait_server():
        raise SystemExit(f"画廊服务器 {SRV} 不可达——先起 http.server（--directory Output）")

    kill_stale(PROFILE)
    w, h = [int(x) for x in WIN.split(",")]
    flags = [BROWSER, f"--remote-debugging-port={PORT}", "--remote-allow-origins=*",
             f"--user-data-dir={PROFILE}", "--no-first-run", "--no-default-browser-check",
             "--disable-background-timer-throttling", f"--window-size={w},{h}"]
    if not HEADED:
        flags += ["--headless=new"]
        # --gpu：用真实 GPU（D3D11）而非 SwiftShader。用户环境是硬件光栅化，
        # 软件/硬件两条路径在 mask/stencil/浮点精度上可能不同，对照必须同路径。
        if not GPU:
            flags += ["--enable-unsafe-swiftshader", "--use-angle=swiftshader"]
    _qs = []
    if HD:
        _qs.append("handdebug")
    if SHIPARG:
        import urllib.parse as _up0
        _qs.append("ship=" + _up0.quote(SHIPARG, safe=""))
        if MOTION:
            _qs.append("motion=" + _up0.quote(MOTION, safe=""))
    if DIAGPOST:
        import urllib.parse as _up
        _qs.append("diagpost=" + _up.quote(DIAGPOST, safe=""))
        _qs.append("diagframes=%d" % DIAGFRAMES)
        _qs.append("diagstep=%d" % DIAGSTEP)
    # 每次探针都用唯一时间戳：http.server 会发 Last-Modified，浏览器缓存会命中旧 index.html/
    # motion_chain.json，导致「代码改了但测试结果没变」的假阴性（2026-10-23 实测踩到）。
    _qs.append("_t=%d" % int(time.time() * 1000))
    flags.append(URL + (("?" + "&".join(_qs)) if _qs else ""))
    proc = subprocess.Popen(flags, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    proc = chrome_tree.install(proc)

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

    def shot(name):
        r = cmd("Page.captureScreenshot", {"format": "png"})
        path = os.path.join(SHOTS, name + ".png")
        open(path, "wb").write(base64.b64decode(r["data"]))
        return path

    cmd("Page.enable")
    cmd("Runtime.enable")
    cmd("Network.enable")
    cmd("Network.setCacheDisabled", {"cacheDisabled": True})
    # 精确注入 DPR：非整数缩放（1.5）只有这条路走得通。
    # --no-emul：完全不动设备度量，用系统真实 DPI + 真实窗口合成路径（用户环境原样）。
    if NO_EMUL:
        print("[env] --no-emul: 跳过设备度量覆盖，用系统真实 DPI")
    else:
        cmd("Emulation.setDeviceMetricsOverride",
            {"width": w, "height": h, "deviceScaleFactor": DPR, "mobile": False})

    for _ in range(80):
        if ev("typeof GALLERY!=='undefined'", awaitp=False) is True:
            break
        time.sleep(0.5)
    else:
        proc.terminate()
        raise SystemExit("GALLERY 未就绪")

    # ---- 1) 打开模型：--ship 走页面自己的 ?ship= 直达（全量索引下卡片是「船」而不是皮肤，
    #        按皮肤 key 搜卡片会 card-not-found）；否则退回点击路径 ----
    if SHIPARG:
        open_js = r"""(async()=>{ try{
          const t=ms=>new Promise(r=>setTimeout(r,ms));
          for(let i=0;i<120;i++){ const a=(typeof l2State!=='undefined'&&l2State)?l2State.app:null;
            const m=a&&a.stage&&a.stage.children[0];
            if(m&&m.internalModel) break; await t(500); }
          const app=l2State&&l2State.app; if(!app) return 'ERR:no-app';
          const mdl=app.stage.children[0]; if(!mdl||!mdl.internalModel) return 'ERR:no-model';
          window.__hp={app:app,mdl:mdl};
          const im=mdl.internalModel;
          return JSON.stringify({ok:1, dpr:window.devicePixelRatio, res:app.renderer.resolution,
            w:app.renderer.width, h:app.renderer.height,
            cssW:document.getElementById('l2wrap').clientWidth,
            cssH:document.getElementById('l2wrap').clientHeight,
            imW:im.width, imH:im.height, ppu:im.pixelsPerUnit,
            mdlX:+mdl.x.toFixed(2), mdlY:+mdl.y.toFixed(2), mdlS:+mdl.scale.x.toFixed(5)});
        }catch(e){ return 'ERR:'+String(e&&e.message||e); } })()"""
    else:
        open_js = r"""(async()=>{ try{
          const t=ms=>new Promise(r=>setTimeout(r,ms));
          const q=document.getElementById('search');
          q.value=%s; q.dispatchEvent(new Event('input',{bubbles:true})); await t(900);
          const card=[...document.querySelectorAll('.card')].find(c=>{const p=c.querySelector('.py');return p&&p.textContent.trim().startsWith(%s);});
          if(!card) return 'ERR:card-not-found'; card.click(); await t(700);
          const skin=document.querySelector('.skin[data-k="%s"]');
          if(!skin) return 'ERR:skin-not-found'; skin.click(); await t(700);
          const tb=[...document.querySelectorAll('#mTabs .tab')].find(x=>x.dataset.k==='live2d');
          if(!tb||tb.classList.contains('dis')) return 'ERR:tab-disabled'; tb.click();
          await t(7000);
          const app=l2State&&l2State.app; if(!app) return 'ERR:no-app';
          const mdl=app.stage.children[0]; if(!mdl||!mdl.internalModel) return 'ERR:no-model';
          window.__hp={app:app,mdl:mdl};
          const im=mdl.internalModel;
          return JSON.stringify({ok:1, dpr:window.devicePixelRatio, res:app.renderer.resolution,
            w:app.renderer.width, h:app.renderer.height,
            cssW:document.getElementById('l2wrap').clientWidth,
            cssH:document.getElementById('l2wrap').clientHeight,
            imW:im.width, imH:im.height, ppu:im.pixelsPerUnit,
            mdlX:+mdl.x.toFixed(2), mdlY:+mdl.y.toFixed(2), mdlS:+mdl.scale.x.toFixed(5)});
        }catch(e){ return 'ERR:'+String(e&&e.message||e); } })()""" % (
            json.dumps(MODEL), json.dumps(MODEL), MODEL)
    info = ev(open_js)
    try:
        info = json.loads(info)
    except Exception:
        proc.terminate()
        raise SystemExit(f"打开模型失败: {str(info)[:300]}")
    print(f"[env] dpr={info['dpr']} res={info['res']} buffer={info['w']}x{info['h']} "
          f"css={info['cssW']}x{info['cssH']} im={info['imW']}x{info['imH']} ppu={info['ppu']} "
          f"mdl pos=({info['mdlX']},{info['mdlY']}) scale={info['mdlS']}")
    # ---- 顶点 API 探查（不同 cubism 封装层方法名/返回形态不同）----
    dbg = ev(r"""(()=>{ try{
      const {mdl}=window.__hp; const core=mdl.internalModel.coreModel;
      const out={coreKeys:Object.getOwnPropertyNames(Object.getPrototypeOf(core)).filter(k=>/Vertex|Drawable/i.test(k))};
      const im=mdl.internalModel;
      out.imKeys=Object.getOwnPropertyNames(Object.getPrototypeOf(im)).filter(k=>/Vertex|Drawable/i.test(k));
      const ix=core.getDrawableIndex('ArtMesh111');
      out.ix=ix;
      /* 部件清单：Cubism 的 mesh 挂在 Part 下，Part id 常带语义（Hand 等）。
         手部 mesh 清单若靠猜（ArtMesh 编号无语义），判据就会一直在看手腕。 */
      try{ const n=core.getPartCount?core.getPartCount():0;
        out.partCount=n;
        out.partApi=Object.getOwnPropertyNames(Object.getPrototypeOf(core)).filter(k=>/Part/i.test(k));
      }catch(e){ out.partsErr=e.message; }
      const cands=['getDrawableVertexPositions','getDrawableVertices','getDrawableVertexPosition'];
      out.cand={};
      for(const c of cands){
        try{ const v=core[c]?core[c](ix):undefined;
          out.cand[c]={exists:!!core[c], ctor:v&&v.constructor&&v.constructor.name, len:v&&v.length,
                       head:v&&v.length?Array.from(v.slice(0,6)):null};
        }catch(e){ out.cand[c]='ERR:'+e.message; }
      }
      return JSON.stringify(out);
    }catch(e){ return 'ERR:'+e.message; } })()""", awaitp=False)
    print("[vertex-api]", str(dbg)[:900])
    if HD:
        hdbox = ev("""(()=>{ const d=document.getElementById('l2handdbg');
          return d ? ('BOX_OK:'+d.textContent.slice(0,500)) : 'NO_BOX'; })()""", awaitp=False)
        print("[handdebug-box]", str(hdbox)[:700])

    # ---- 1.5) 直接写参数（--setparam，形如 ShoseOff=1）----
    # 为什么需要它：TouchDragN 里的「状态开关」在页面上不是播动作，而是 setParameterValueById；
    # 只播同名动作组根本不会改变开关值（实测 ShoseOff 在两种路径下都停在 0）。
    if SETPARAM:
        try:
            _k, _v = SETPARAM.split("=", 1)
        except Exception:
            proc.terminate()
            raise SystemExit("--setparam 需形如 ShoseOff=1")
        sp_js = """(()=>{ try{
          const {app,mdl}=window.__hp; const core=mdl.internalModel.coreModel;
          const k=%s, v=%f;
          const set=()=>{ try{ core.setParameterValueById(k, v); }catch(e){} };
          set();
          /* 每帧在 model update 之后写回，防止被动作曲线/物理覆盖（LOW 优先级 = 后执行） */
          PIXI.Ticker.shared.add(()=>set(), null, (PIXI.UPDATE_PRIORITY && PIXI.UPDATE_PRIORITY.LOW) || -25);
          try{ app.render(); }catch(e){}
          return 'set '+k+' = '+v;
        }catch(e){ return 'ERR:'+e.message; } })()""" % (json.dumps(_k), float(_v))
        print("[setparam]", ev(sp_js, awaitp=False))

    # ---- 1.5b) 从快照注入参数（--paramsin file.json，配合 --diffbox 做区域差分实验）----
    # 用途：A 动作区域正常、B 动作异常时，把 A 采集到的参数值整套搬到 B 上，
    # 再配合区域差分二分，定位「哪几个参数负责这块区域」。
    if PARAMSIN:
        try:
            snap = json.load(open(PARAMSIN, encoding="utf-8"))
            vals = snap.get("vals") or snap
        except Exception as e:
            proc.terminate()
            raise SystemExit("读参数快照失败: %s" % e)
        pi_js = """(()=>{ try{
          const {app,mdl}=window.__hp; const core=mdl.internalModel.coreModel;
          const V=%s; let n=0;
          try{ mdl.internalModel.motionManager.stopAllMotions(); }catch(e){}
          const set=()=>{ for(const k in V){ try{ core.setParameterValueById(k, V[k]); n++; }catch(e){} } };
          set();
          PIXI.Ticker.shared.add(set, null, (PIXI.UPDATE_PRIORITY && PIXI.UPDATE_PRIORITY.LOW) || -25);
          try{ app.render(); }catch(e){}
          return 'injected '+Object.keys(V).length+' params ('+n+' writes)';
        }catch(e){ return 'ERR:'+e.message; } })()""" % json.dumps(vals)
        print("[paramsin]", str(ev(pi_js, awaitp=False))[:300])

    # ---- 1.5c) 区域差分自检（--diffbox + --params）：只在注入前后比较指定区域 ----
    if DIFFBOX and not BISECT_FILE:
        bxv = [int(v) for v in DIFFBOX.split(",")]
        dd_js = r"""(()=>{ try{
          const {app,mdl}=window.__hp; const core=mdl.internalModel.coreModel;
          const box=%s, cw=app.renderer.width, ch=app.renderer.height;
          const wrap=document.getElementById('l2wrap');
          const sx=cw/(wrap.clientWidth||cw), sy=ch/(wrap.clientHeight||ch);
          const cv=document.createElement('canvas'); cv.width=cw; cv.height=ch;
          const g=cv.getContext('2d',{willReadFrequently:true});
          const sub=()=>{ g.clearRect(0,0,cw,ch); g.drawImage(app.view,0,0,cw,ch);
            const X0=Math.max(0,Math.floor(box[0]*sx)), Y0=Math.max(0,Math.floor(box[1]*sy));
            const X1=Math.min(cw,Math.ceil(box[2]*sx)), Y1=Math.min(ch,Math.ceil(box[3]*sy));
            const w=X1-X0,h=Y1-Y0,out=[];
            const d=g.getImageData(X0,Y0,w,h).data;
            let skin=0;
            for(let i=0;i<d.length;i+=4){ const r=d[i],gg=d[i+1],b=d[i+2];
              if(r>110&&gg>60&&b>40&&r>gg&&gg>=b&&(r-b)>18&&(r-gg)>6) skin++; }
            return {w:w,h:h,px:w*h,skin:skin}; };
          try{ core.update(); }catch(e){}
          try{ app.renderer.render(app.stage); }catch(e){}
          const s=sub();
          return JSON.stringify({box:box,px:s.px,skinPx:s.skin,skinRatio:+(s.skin/Math.max(1,s.px)).toFixed(4)});
        }catch(e){ return 'ERR:'+e.message; } })()""" % json.dumps(bxv)
        print("[diffbox]", str(ev(dd_js, awaitp=False))[:400])

    # ---- 1.6) 同帧双态对比（--abparam <参数名>）：固定其它一切，只改这一个参数 ----
    # 为什么必须同帧：两次独立会话的动作相位不同，整图差异能到 50%（全是姿势差），
    # 只有「同一帧、只动一个参数」的差异才是这个开关真正控制的部件。
    if ABPARAM:
        ab_js = r"""(()=>{ try{
          const {app,mdl}=window.__hp; const core=mdl.internalModel.coreModel;
          const k=%s;
          try{ mdl.internalModel.motionManager.stopAllMotions(); }catch(e){}
          const cw=app.renderer.width, ch=app.renderer.height;
          const cv=document.createElement('canvas'); cv.width=cw; cv.height=ch;
          const g=cv.getContext('2d',{willReadFrequently:true});
          const grab=()=>{ g.clearRect(0,0,cw,ch); g.drawImage(app.view,0,0,cw,ch);
            return g.getImageData(0,0,cw,ch).data; };
          const draw=()=>{ try{ core.update(); }catch(e){} try{ app.renderer.render(app.stage); }catch(e){} };
          core.setParameterValueById(k, 0); draw(); const A=grab();
          core.setParameterValueById(k, 1); draw(); const B=grab();
          let diff=0, x0=1e9,y0=1e9,x1=-1e9,y1=-1e9, dskin=0;
          for(let y=0;y<ch;y++){ for(let x=0;x<cw;x++){
            const p=((y*cw)+x)*4;
            const dd=Math.abs(A[p+3]-B[p+3])+Math.abs(A[p]-B[p])+Math.abs(A[p+1]-B[p+1])+Math.abs(A[p+2]-B[p+2]);
            if(dd<=30) continue;
            diff++; if(x<x0)x0=x; if(x>x1)x1=x; if(y<y0)y0=y; if(y>y1)y1=y;
            const r=B[p],gg=B[p+1],bb2=B[p+2];
            if(r>110&&gg>60&&bb2>40&&r>gg&&gg>=bb2&&(r-bb2)>18&&(r-gg)>6) dskin++;
          }}
          /* 差异区的「一态平均色」：判断消失的是肤色(腿)还是衣物 */
          let sumA=[0,0,0], sumB=[0,0,0], n=0;
          for(let y=0;y<ch;y++){ for(let x=0;x<cw;x++){
            const p=((y*cw)+x)*4;
            const dd=Math.abs(A[p+3]-B[p+3])+Math.abs(A[p]-B[p])+Math.abs(A[p+1]-B[p+1])+Math.abs(A[p+2]-B[p+2]);
            if(dd<=30) continue; n++;
            sumA[0]+=A[p];sumA[1]+=A[p+1];sumA[2]+=A[p+2];
            sumB[0]+=B[p];sumB[1]+=B[p+1];sumB[2]+=B[p+2];
          }}
          return JSON.stringify({param:k, canvas:[cw,ch], diffPx:diff, diffSkin:dskin,
            bbox:[x0,y0,x1,y1],
            avgShose0:[Math.round(sumA[0]/Math.max(1,n)),Math.round(sumA[1]/Math.max(1,n)),Math.round(sumA[2]/Math.max(1,n))],
            avgShose1:[Math.round(sumB[0]/Math.max(1,n)),Math.round(sumB[1]/Math.max(1,n)),Math.round(sumB[2]/Math.max(1,n))]});
        }catch(e){ return 'ERR:'+e.message; } })()""" % json.dumps(ABPARAM)
        print("[abparam]", str(ev(ab_js, awaitp=False))[:800])
        shot(TAG + "_ab")

    # ---- 2) 播动作（走页面自己的 play 入口 window.__l2play，不直接调 runtime 的 startMotion）
    # 用户真实路径是下拉/「▶ 全部」→ play(g)：其中有语音、标签、lastGroup 记录、回落映射。
    # --pre 用来复刻「▶ 全部」的场景：前序动作被 FORCE 打断后切到目标组，检验参数残留。
    pre_ok = True
    # --ui full,panel：用户在真实浏览器里会点这些按钮，它们会改 canvas 尺寸/重设 renderer，
    # 是「手在边缘被裁」这类问题的常见触发条件，必须在采样前进入同一 UI 状态。
    for u in UI:
        sel = {"full": "#l2Full", "panel": "#l2PanelBtn", "areas": "#l2AreasBtn"}.get(u)
        if not sel:
            continue
        r = ev(f"""(()=>{{ try{{ const b=document.querySelector('{sel}');
          if(!b) return 'ERR:no-btn'; b.click(); return 'clicked'; }}catch(e){{ return 'ERR:'+e.message; }} }})()""",
               awaitp=False)
        print(f"[ui] {u} -> {r}")
        time.sleep(1.5)
    for g in PRE:
        r = ev(f"""(()=>{{ try{{ return String(window.__l2play?window.__l2play({json.dumps(g)}):'no-l2play'); }}
                     catch(e){{ return 'ERR:'+e.message; }} }})()""", awaitp=False)
        print(f"[pre] {g} -> {r}")
        if str(r).startswith("ERR"):
            pre_ok = False
        time.sleep(PRE_GAP / 1000.0)
    has = ev(f"""(()=>{{ const mm=window.__hp.mdl.internalModel.motionManager;
      return JSON.stringify({{has:!!(mm.definitions||{{}})['{MOTION}'],
        groups:Object.keys(mm.definitions||{{}})}}); }})()""", awaitp=False)
    print("[motions]", str(has)[:400])

    play = ev(r"""(async()=>{ const t=ms=>new Promise(r=>setTimeout(r,ms));
      let ok=null;
      try{ ok=(window.__l2play?window.__l2play(%s):null); }catch(e){ return 'ERR:'+e.message; }
      if(ok===null){ try{ window.__hp.mdl.internalModel.motionManager.startMotion(%s,0,3); ok='fallback'; }
        catch(e){ return 'ERR2:'+e.message; } }
      await t(1000);
      return String(ok); })()""" % (json.dumps(MOTION), json.dumps(MOTION)))
    if str(play).startswith("ERR"):
        proc.terminate()
        raise SystemExit("播动作失败: " + str(play)[:300])

    # ---- 3) 逐帧采样：状态 + 手部 bbox 像素覆盖率 ----
    sample_js = r"""(async()=>{
      const t=ms=>new Promise(r=>setTimeout(r,ms));
      const {app,mdl}=window.__hp; const im=mdl.internalModel;
      const core=im.coreModel, ppu=im.pixelsPerUnit||1;
      const cux=im.width/ppu, cuy=im.height/ppu, s=mdl.scale.x;
      const toStage=(vx,vy)=>[mdl.x+(vx+cux/2)*ppu*s, mdl.y+(cuy/2-vy)*ppu*s];
      const HAND=%s;
      const ISO=%s;
      /* 隔离渲染：把非手部 drawable 的 opacity 打过补丁压成 0，只留手部 mesh。
         判据意义：隔离后画布上仍有像素 ⇒ 手确实被画了（之前看不到只能是遮挡/裁剪）；
                   隔离后画布空白 ⇒ 手根本没被绘制（状态/数据/渲染管线问题）。 */
      const handIdx=new Set(HAND.map(id=>core.getDrawableIndex(id)).filter(i=>i>=0));
      const ros=(core.getDrawableRenderOrders?core.getDrawableRenderOrders():[]);
      const cw=Math.min(700, app.renderer.width), ch=Math.round(cw*app.renderer.height/app.renderer.width);
      const cv=document.createElement('canvas'); cv.width=cw; cv.height=ch;
      const g=cv.getContext('2d',{willReadFrequently:true});
      const kx=cw/app.renderer.width, ky=ch/app.renderer.height;   // stage(CSS) → 统计图
      const out=[];
      for(let fi=0; fi<%d; fi++){
        let isoRestore=null, isoInk=-1, isoArea=-1;
        if(ISO){
          const o=core.getDrawableOpacity.bind(core);
          core.getDrawableOpacity=(i)=> handIdx.has(i) ? o(i) : 0;
          isoRestore=()=>{ core.getDrawableOpacity=o; };
        }
        try{PIXI.Ticker.shared.tick(performance.now());}catch(e){}
        try{app.render();}catch(e){}
        if(isoRestore){
          try{ g.clearRect(0,0,cw,ch); g.drawImage(app.view,0,0,cw,ch);
            const dd=g.getImageData(0,0,cw,ch).data; isoInk=0;
            for(let i=3;i<dd.length;i+=4){ if(dd[i]>8) isoInk++; }
            isoArea=cw*ch;
          }catch(e){}
          isoRestore(); isoRestore=null;
          try{ app.render(); }catch(e){}
        }
        const hand=[]; let x0=1e9,y0=1e9,x1=-1e9,y1=-1e9, nBad=0, nVis=0;
        const nd=core.getDrawableCount();
        for(const id of HAND){
          const ix=core.getDrawableIndex(id);
          if(ix<0){ hand.push({id:id,miss:1}); continue; }
          const op=+core.getDrawableOpacity(ix).toFixed(3);
          const vis=core.getDrawableDynamicFlagIsVisible(ix)?1:0;
          const bl=core.getDrawableBlendMode?core.getDrawableBlendMode(ix):-1;
          const ro=ros.length?ros[ix]:-1;
          let mk=[]; try{ const nm=core.getDrawableMaskCounts(ix)||0;
            for(let k=0;k<nm;k++) mk.push(core.getDrawableMasks(ix)[k]); }catch(e){}
          hand.push({id:id,op:op,vis:vis,blend:bl,ro:ro,mask:mk});
          if(op<0.05||!vis) nBad++;
          const p=core.getDrawableVertexPositions(ix);
          if(!p||p.length<4){ hand[hand.length-1].plen=(p?p.length:-1); continue; }
          let bx0=1e9,by0=1e9,bx1=-1e9,by1=-1e9;
          for(let k=0;k+1<p.length;k+=2){
            const st=toStage(p[k],p[k+1]);
            if(st[0]<bx0)bx0=st[0]; if(st[0]>bx1)bx1=st[0];
            if(st[1]<by0)by0=st[1]; if(st[1]>by1)by1=st[1];
          }
          if(bx1<bx0 || by1<by0) continue;   /* 无效 bbox（顶点未初始化）才跳过 */
          hand[hand.length-1].bb=[Math.round(bx0),Math.round(by0),Math.round(bx1),Math.round(by1)];
          if(bx0<x0)x0=bx0; if(bx1>x1)x1=bx1; if(by0<y0)y0=by0; if(by1>y1)y1=by1;
        }
        let ink=0, area=0, cover=-1, hx0=0,hy0=0,hw=0,hh=0, skin=0, out_avg=[0,0,0];
        if(x1>x0 && y1>y0){
          g.clearRect(0,0,cw,ch);
          g.drawImage(app.view,0,0,cw,ch);
          const qx0=Math.max(0,Math.floor(x0*kx)), qy0=Math.max(0,Math.floor(y0*ky));
          const qx1=Math.min(cw,Math.ceil(x1*kx)), qy1=Math.min(ch,Math.ceil(y1*ky));
          hx0=qx0; hy0=qy0; hw=qx1-qx0; hh=qy1-qy0;
          if(hw>0 && hh>0){
            const d=g.getImageData(qx0,qy0,hw,hh).data;
            let rs=0,gs=0,bs=0,cnt=0;
            for(let i=0;i<d.length;i+=4){
              if(d[i+3]<=8) continue;
              cnt++; rs+=d[i]; gs+=d[i+1]; bs+=d[i+2];
              const r=d[i],gg=d[i+1],b=d[i+2];
              /* 肤色：暖调、红>绿>蓝、非纯白非纯黑（与衣服的冷色/深色可区分） */
              if(r>110 && gg>60 && b>40 && r>gg && gg>=b && (r-b)>18 && (r-gg)>6) ink++;
            }
            area=hw*hh; cover=+(cnt/area).toFixed(3);
            out_avg=[cnt?Math.round(rs/cnt):0, cnt?Math.round(gs/cnt):0, cnt?Math.round(bs/cnt):0];
            skin=+(ink/area).toFixed(4);
          }
        }
        out.push({fi:fi, hand:hand, nBad:nBad, nd:nd, cover:cover, skin:skin, avg:out_avg,
          bbox:[Math.round(x0),Math.round(y0),Math.round(x1),Math.round(y1)],
          ink:ink, area:area, isoInk:isoInk, isoArea:isoArea});
        await t(%d);
      }
      return JSON.stringify(out);
    })()""" % (json.dumps(HAND), "true" if ISO else "false", FRAMES, STEP)
    raw = ev(sample_js)
    try:
        frames = json.loads(raw)
    except Exception:
        proc.terminate()
        raise SystemExit("采样失败: " + str(raw)[:300])

    # ---- 全参数快照（--params）：定位「某部件被参数间接隐藏/显示」时用 ----
    if DUMPPARAMS:
        pj = r"""(()=>{ try{
          const {mdl}=window.__hp; const core=mdl.internalModel.coreModel;
          const ids=(core._model&&core._model.parameters&&core._model.parameters.ids)||[];
          const out={};
          for(let i=0;i<ids.length;i++){ try{ out[ids[i]]=+core.getParameterValueByIndex(i).toFixed(4); }catch(e){} }
          const dflt={};
          for(let i=0;i<ids.length;i++){ try{ dflt[ids[i]]=+core.getParameterDefaultValue(i).toFixed(4); }catch(e){} }
          return JSON.stringify({ids:ids.length, vals:out, defaults:dflt});
        }catch(e){ return 'ERR:'+e.message; } })()"""
        pv = ev(pj, awaitp=False)
        pp = os.path.join(SHOTS, TAG + "_params.json")
        try:
            open(pp, "w", encoding="utf-8").write(pv if isinstance(pv, str) else json.dumps(pv))
            print("[params]", pp)
        except Exception as e:
            print("[params] 写失败", e)

    # ---- 强制显示指定 mesh（--forcevis）：判定「op=1 却 vis=0」的部件到底长什么样 ----
    # Cubism 的 vis 为 false 时渲染器整块跳过；patch 成 true 且只留该 mesh，
    # 就能看出它是手指/手掌还是本就该隐藏的备用件。
    if FORCEVIS:
        fv_js = r"""(async()=>{
          const {app,mdl}=window.__hp; const core=mdl.internalModel.coreModel;
          const ids=%s, idx=new Set();
          for(const id of ids){ try{ const k=core.getDrawableIndex(id); if(k>=0) idx.add(k); }catch(e){} }
          const origVis=core.getDrawableDynamicFlagIsVisible.bind(core);
          const origOp=core.getDrawableOpacity.bind(core);
          const cw2=Math.min(560, app.renderer.width), ch2=Math.round(cw2*app.renderer.height/app.renderer.width);
          const cv2=document.createElement('canvas'); cv2.width=cw2; cv2.height=ch2;
          const g2=cv2.getContext('2d',{willReadFrequently:true});
          const grab=()=>{ g2.clearRect(0,0,cw2,ch2); g2.drawImage(app.view,0,0,cw2,ch2);
            return g2.getImageData(0,0,cw2,ch2).data; };
          const stat=(d)=>{ let ink=0, skin=0; for(let p=0;p<d.length;p+=4){
              if(d[p+3]<=8) continue; ink++;
              const rr=d[p],gg=d[p+1],bb2=d[p+2];
              if(rr>110&&gg>60&&bb2>40&&rr>gg&&gg>=bb2&&(rr-bb2)>18&&(rr-gg)>6) skin++; }
            return {ink:ink, skin:skin}; };
          let r='';
          try{
            app.render(); const base=grab(); const sb=stat(base);
            /* 只把目标 mesh 的 vis 强制为 true（其余保持原值），opacity 也保持原值：
               这样画面是「原图 + 目标部件」，差异区就是目标本身，不会破坏遮罩关系。 */
            core.getDrawableDynamicFlagIsVisible=(i)=> idx.has(i) ? true : origVis(i);
            core.getDrawableOpacity=(i)=> idx.has(i) ? Math.max(1, origOp(i)) : origOp(i);
            app.render(); const after=grab(); const sa=stat(after);
            let x0=1e9,y0=1e9,x1=-1e9,y1=-1e9, diff=0, dskin=0;
            for(let y=0;y<ch2;y++){ for(let x=0;x<cw2;x++){
              const p=((y*cw2)+x)*4;
              const da=Math.abs(after[p+3]-base[p+3])+Math.abs(after[p]-base[p])+Math.abs(after[p+1]-base[p+1])+Math.abs(after[p+2]-base[p+2]);
              if(da<=24) continue;
              diff++;
              if(x<x0)x0=x; if(x>x1)x1=x; if(y<y0)y0=y; if(y>y1)y1=y;
              const rr=after[p],gg=after[p+1],bb2=after[p+2];
              if(rr>110&&gg>60&&bb2>40&&rr>gg&&gg>=bb2&&(rr-bb2)>18&&(rr-gg)>6) dskin++;
            }}
            r=JSON.stringify({ids:ids, baseInk:sb.ink, afterInk:sa.ink, skinBefore:sb.skin, skinAfter:sa.skin,
              diffPx:diff, diffSkin:dskin, diffBB:[x0,y0,x1,y1]});
            window.__fvAfter=after;
          }catch(e){ r='ERR:'+e.message; }
          core.getDrawableDynamicFlagIsVisible=origVis;
          core.getDrawableOpacity=origOp;
          try{ app.render(); }catch(e){}
          return r;
        })()""" % json.dumps(FORCEVIS)
        fr = ev(fv_js)
        print("[forcevis]", str(fr)[:600])
        shot(TAG + "_forcevis")

    # ---- 逐 mesh 隔离渲染扫描（--scan）：找出所有「皮肤色」mesh，从而确定手掌 id ----
    # 手部 mesh 清单一直靠猜（ArtMesh 编号无语义），猜错就会一直在看手腕。
    if SCAN:
        scan_js = r"""(async()=>{
          const {app,mdl}=window.__hp; const im=mdl.internalModel; const core=im.coreModel;
          const cw=Math.min(560, app.renderer.width), ch=Math.round(cw*app.renderer.height/app.renderer.width);
          const cv=document.createElement('canvas'); cv.width=cw; cv.height=ch;
          const g=cv.getContext('2d',{willReadFrequently:true});
          const nd=core.getDrawableCount(), res=[];
          const orig=core.getDrawableOpacity.bind(core);
          for(let i=0;i<nd;i++){
            let op=0, vis=0;
            try{ op=orig(i); vis=core.getDrawableDynamicFlagIsVisible(i)?1:0; }catch(e){ continue; }
            if(op<0.5||!vis) continue;
            core.getDrawableOpacity=(j)=> (j===i ? orig(j) : 0);
            let ok=true; try{ app.render(); }catch(e){ ok=false; }
            if(ok){
              g.clearRect(0,0,cw,ch); g.drawImage(app.view,0,0,cw,ch);
              const d=g.getImageData(0,0,cw,ch).data;
              let ink=0, skin=0, x0=1e9,y0=1e9,x1=-1e9,y1=-1e9;
              for(let y=0;y<ch;y++){ for(let x=0;x<cw;x++){
                const p=((y*cw)+x)*4, a=d[p+3]; if(a<=8) continue;
                ink++; if(x<x0)x0=x; if(x>x1)x1=x; if(y<y0)y0=y; if(y>y1)y1=y;
                const r=d[p],gg=d[p+1],b=d[p+2];
                if(r>110&&gg>60&&b>40&&r>gg&&gg>=b&&(r-b)>18&&(r-gg)>6) skin++;
              }}
              if(ink>0){ let id='?'; try{ id=core.getDrawableId(i); }catch(e){}
                res.push({i:i,id:id,ink:ink,skin:skin,ratio:+(skin/ink).toFixed(3),bb:[x0,y0,x1,y1]}); }
            }
            core.getDrawableOpacity=orig;
            await new Promise(r=>setTimeout(r,0));
          }
          try{ app.render(); }catch(e){}
          return JSON.stringify(res);
        })()"""
        raw2 = ev(scan_js)
        try:
            scan = json.loads(raw2)
        except Exception:
            proc.terminate()
            raise SystemExit("扫描失败: " + str(raw2)[:300])
        sp = os.path.join(SHOTS, TAG + "_scan.json")
        open(sp, "w", encoding="utf-8").write(json.dumps(scan, ensure_ascii=False, indent=1))
        skinny = sorted([x for x in scan if x["ratio"] > 0.3], key=lambda x: -x["skin"])[:25]
        nsk = len([x for x in scan if x["ratio"] > 0.3])
        print(f"\n[scan] {len(scan)} 个可见 mesh 有像素；肤色占比>0.3 的 {nsk} 个")
        for x in skinny:
            print(f"  {x['id']:<12} skin={x['skin']:>6} ink={x['ink']:>6} ratio={x['ratio']} bb={x['bb']}")
        print("[scan] 明细:", sp)

    # ---- 找 opacity 控制参数（--findop <meshId>）：Cubism 的 drawable 透明度由参数绑定驱动，
    #      高层 API 不暴露"哪个参数控制它"，只能逐个参数试值后看 opacity 是否变化。 ----
    if FINDOP:
        fo_js = r"""(async()=>{
          const t=ms=>new Promise(r=>setTimeout(r,ms));
          const {app,mdl}=window.__hp; const core=mdl.internalModel.coreModel;
          try{ mdl.internalModel.motionManager.stopAllMotions(); }catch(e){}
          const target=%s;
          const gi=core.getDrawableIndex(target);
          if(gi<0) return 'ERR:no-such-mesh';
          const ids=(core._model&&core._model.parameters&&core._model.parameters.ids)||[];
          const base=core.getDrawableOpacity(gi), baseVis=core.getDrawableDynamicFlagIsVisible(gi);
          const hits=[];
          const orig={};
          for(let i=0;i<ids.length;i++){ try{ orig[ids[i]]=core.getParameterValueByIndex(i); }catch(e){} }
          const setAll=(k,v)=>{ try{ core.setParameterValueById(k,v); }catch(e){} };
          const restore=()=>{ for(const k in orig){ setAll(k, orig[k]); } };
          for(let i=0;i<ids.length;i++){
            const p=ids[i];
            let lo=0, hi=1;
            try{ lo=core.getParameterMinimumValue(i); hi=core.getParameterMaximumValue(i); }catch(e){}
            let best=null;
            for(const v of [lo,hi]){
              setAll(p,v); try{ core.update(); }catch(e){}
              let op=0, vis=false;
              try{ op=core.getDrawableOpacity(gi); vis=core.getDrawableDynamicFlagIsVisible(gi); }catch(e){}
              setAll(p, orig[p]);
              if(Math.abs(op-base)>0.05 || vis!==baseVis){
                best={param:p, val:v, op:+op.toFixed(3), vis:vis?1:0};
                break;
              }
            }
            if(best) hits.push(best);
            if(i%%40===0) await t(0);
          }
          restore(); try{ core.update(); }catch(e){}
          return JSON.stringify({mesh:target, baseOp:+base.toFixed(3), baseVis:baseVis?1:0,
            hits:hits.slice(0,40), n_hits:hits.length});
        })()""" % json.dumps(FINDOP)
        fo = ev(fo_js)
        print("[findop]", str(fo)[:1500])

    # ---- 1.5c) 参数二分定位（--bisect params.json + --diffbox）----
    # 前提：已确认「注入参照动作的全部参数」能显著改变目标区域（--paramsin + --diffbox 可验）。
    # 做法：以肤色像素数为目标，逐个参数试「设成参照值」，按增量排序后贪心累加，
    # 找到「用最少参数把肤色拉到全量注入的 90%」的最小集合。
    if BISECT_FILE:
        try:
            snap = json.load(open(BISECT_FILE, encoding="utf-8"))
            ref = snap.get("vals") or snap
        except Exception as e:
            proc.terminate()
            raise SystemExit("读参照快照失败: %s" % e)
        if not DIFFBOX:
            proc.terminate()
            raise SystemExit("--bisect 需要配 --diffbox x0,y0,x1,y1")
        bxv = [int(v) for v in DIFFBOX.split(",")]
        bi_js = r"""(async()=>{
          const t=ms=>new Promise(r=>setTimeout(r,ms));
          const {app,mdl}=window.__hp; const core=mdl.internalModel.coreModel;
          const REF=%s, BOX=%s;
          try{ mdl.internalModel.motionManager.stopAllMotions(); }catch(e){}
          const ids=(core._model&&core._model.parameters&&core._model.parameters.ids)||[];
          const cur={}; for(let i=0;i<ids.length;i++){ try{cur[ids[i]]=core.getParameterValueByIndex(i);}catch(e){} }
          const cw=app.renderer.width, ch=app.renderer.height;
          const wrap=document.getElementById('l2wrap');
          const sx=cw/(wrap.clientWidth||cw), sy=ch/(wrap.clientHeight||ch);
          const cv=document.createElement('canvas'); cv.width=cw; cv.height=ch;
          const g=cv.getContext('2d',{willReadFrequently:true});
          const X0=Math.max(0,Math.floor(BOX[0]*sx)), Y0=Math.max(0,Math.floor(BOX[1]*sy));
          const X1=Math.min(cw,Math.ceil(BOX[2]*sx)), Y1=Math.min(ch,Math.ceil(BOX[3]*sy));
          const W=X1-X0, H=Y1-Y0;
          const skinCount=()=>{ g.clearRect(0,0,cw,ch); g.drawImage(app.view,0,0,cw,ch);
            const d=g.getImageData(X0,Y0,W,H).data; let n=0;
            for(let i=0;i<d.length;i+=4){ const r=d[i],gg=d[i+1],b=d[i+2];
              if(r>110&&gg>60&&b>40&&r>gg&&gg>=b&&(r-b)>18&&(r-gg)>6) n++; }
            return n; };
          const draw=()=>{ try{ core.update(); }catch(e){}
            try{ app.renderer.render(app.stage); }catch(e){} };
          const setP=(k,v)=>{ try{ core.setParameterValueById(k,v); }catch(e){} };
          const reset=()=>{ for(const k in cur) setP(k,cur[k]); };
          draw(); const base=skinCount();
          /* 全量注入作为目标 */
          for(const k in REF) setP(k,REF[k]);
          draw(); const full=skinCount();
          reset(); draw();
          const gain=full-base;
          if(Math.abs(gain)<50) return JSON.stringify({note:'全量注入对该区域几乎无影响', base:base, full:full});
          /* 单参数增益排序 */
          const solo=[];
          const keys=Object.keys(REF);
          let i=0;
          for(const k of keys){
            if(Math.abs((REF[k]||0)-(cur[k]||0))<1e-6) continue;
            setP(k,REF[k]); draw(); const v=skinCount(); setP(k,cur[k]);
            if(v-base>0) solo.push({k:k, d:v-base});
            if(((i++)%%30)===0) await t(0);
          }
          solo.sort((a,b)=>b.d-a.d);
          /* 贪心累加 */
          reset();
          const chosen=[], steps=[]; let last=base;
          for(const it of solo){
            setP(it.k, REF[it.k]); draw();
            const v=skinCount();
            steps.push({k:it.k, solo:it.d, cum:v, delta:v-last});
            last=v; chosen.push(it.k);
            if(v-base >= gain*0.9) break;
          }
          reset(); draw();
          return JSON.stringify({box:BOX, basePx:base, fullPx:full, gain:gain,
            n_changed:solo.length, chosenN:chosen.length, chosen:chosen,
            top:solo.slice(0,15), steps:steps});
        })()""" % (json.dumps(ref), json.dumps(bxv))
        r = ev(bi_js)
        print("[bisect]", str(r)[:4000])

    # ---- 播完跟踪（--follow N）：动作结束后落在哪个组，是「回落对不对」的唯一判据 ----
    # 只看 currentGroup / isFinished；不依赖画面，因此不受低帧率伪影影响。
    if FOLLOW:
        fl_js = r"""(async()=>{
          const t=ms=>new Promise(r=>setTimeout(r,ms));
          const {mdl}=window.__hp; const mm=mdl.internalModel.motionManager;
          const out=[];
          for(let i=0;i<%d;i++){
            out.push({i:i, cur:(mm.state&&mm.state.currentGroup)||null,
                      fin:!!(mm.state&&mm.state.isFinished),
                      label:(document.getElementById('l2Curr')||{}).textContent||null});
            await t(%d);
          }
          return JSON.stringify(out);
        })()""" % (FOLLOW, STEP)
        rawf = ev(fl_js)
        try:
            seq = json.loads(rawf)
        except Exception:
            seq = []
        print("[follow]", json.dumps(seq, ensure_ascii=False)[:1200])
        shots = sorted(set(x["cur"] for x in seq if x.get("cur")))
        print("[follow] 出现过的组:", shots)

    shot(TAG + "_page")
    bad = 0
    fp = os.path.join(SHOTS, TAG + "_frames.json")
    open(fp, "w", encoding="utf-8").write(json.dumps(frames, ensure_ascii=False, indent=1))
    print("[frames]", fp)
    print(f"\n===== {MODEL} / {MOTION} @ dpr={DPR} {'headed' if HEADED else 'headless'} =====")
    for f in frames:
        hs = " ".join(f"{h['id'][-3:]}:op{h.get('op')}/v{h.get('vis')}"
                      + (f"/plen{h['plen']}" if "plen" in h else "")
                      for h in f["hand"] if not h.get("miss"))
        miss = [h["id"] for h in f["hand"] if h.get("miss")]
        flag = ""
        hvis = [h for h in f["hand"] if not h.get("miss") and h["id"] != "ArtMesh29"]
        nHidden = sum(1 for h in hvis if h.get("op", 1) < 0.05 or not h.get("vis"))
        if hvis and nHidden == len(hvis):
            flag = "STATE-ALL-HIDDEN"
        elif f["cover"] is not None and f["cover"] < 0.02:
            flag = "RENDER-NOINK"    # 渲染层：bbox 内几乎没有像素
        elif (f.get("skin") or 0) < 0.02:
            flag = "RENDER-NOSKIN"   # bbox 有像素但没有肤色 ⇒ 手被别的东西顶掉/没画
        if flag:
            bad += 1
        print(f"  f{f['fi']} cover={f['cover']} skin={f.get('skin')} avg={f.get('avg')} "
              f"iso={f.get('isoInk')}/{f.get('isoArea')} "
              f"bbox={f['bbox']} {hs}" + (f" miss={miss}" if miss else "") + (" <== " + flag if flag else ""))
        shot(f"{TAG}_f{f['fi']}")

    ws.close()
    if HOLD > 0:
        print(f"[hold] 保持页面 {HOLD}s 等待页面侧异步回传/落盘")
        time.sleep(HOLD)
    proc.terminate()
    print(f"\n截图: {SHOTS}\\{TAG}_*.png")
    print("结论: " + ("异常帧 %d/%d" % (bad, len(frames)) if bad else "全部帧手部状态/像素正常"))
    raise SystemExit(0 if bad == 0 else 1)


if __name__ == "__main__":
    main()
