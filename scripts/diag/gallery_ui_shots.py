# -*- coding: utf-8 -*-
"""画廊 UI 截图：依次打开若干界面状态各截一张（跨「列表 + 三种查看器 + 语音页」）。

用途：改视觉语言时先看样板再铺开——判据是"人眼看图"，所以工具只负责
把每个状态拍成**同一视角、同一尺寸、同一等待时长**的图片。

  py -3 scripts/diag/gallery_ui_shots.py                              # 截 index.html 一套（5 张）
  py -3 scripts/diag/gallery_ui_shots.py --pages a.html,b.html --tags before,after
  py -3 scripts/diag/gallery_ui_shots.py --out .diag/uishots

⚠️ 三个坑（都踩过）：
  1. 无头窗口尺寸必须对齐用户实机（默认 2560,1600）——弹窗上限按 vw/vh 算，小窗口看不出真实观感。
  2. 打开皮肤后**不要**给 .view 刷背景色（取景量具 gallery_framing_ab.py 会刷，那是为了量落笔像素）；
     这里要看的就是用户实际看到的底。
  3. **默认只截 `index.html`**。旧默认还写了一张 `index_b.html`（"改前页"），但那份校对页
     从来没入库、D 盘上也不存在（`git log --all` 无记录）⇒ 默认跑必然在 `preflight` 阶段
     报 404 退出 1（2026-10-27 实测）。要对比两份就显式 `--pages a.html,b.html`。
     皮肤 key 同理：**必须是本项目 index.json 里实有的**（haitian_3 / benningdun_2 /
     aersasi / aersasi_2 / aersasi_3 / antu_2 / ougen_8），旧默认的 ninghai_4 / tansuozhe_2
     来自另一份全库画廊，在本项目上恒 NO_SHIP。
"""
import sys, os, json, time, base64, argparse, subprocess, threading, urllib.request
sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import websocket, chrome_tree, cdp_wait

ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
CHROME = r'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
# ⚠️ BASE 不许再写死 8777：本项目当前服务在 8778（8777 上是另一份画廊，如旧机拷贝的全库）。
# 在错误的服务上截出的"改前/改后"样板看起来正常，实际两个页面都不是本项目产物。
BASE = os.environ.get('SHOTS_BASE', 'http://127.0.0.1:8778/gallery_v2')
WAIT = {'painting': 4.0, 'live2d': 11.0, 'spine': 11.0, 'voice': 4.0}

# 界面状态清单：(文件名, tab, 皮肤 key)。覆盖「列表 + 三种查看器 + 语音页」
# ⚠️ 皮肤 key 必须存在于**当前项目**的 index.json（实测现有 7 个皮肤：
#    haitian_3 / benningdun_2 / aersasi / aersasi_2 / aersasi_3 / antu_2 / ougen_8）。
#    以前写的是 ninghai_4 / tansuozhe_2，那是旧机全库才有的模型 → 本项目上必 NO_SHIP。
STATES = [('1_grid', None, None), ('2_live2d', 'live2d', 'aersasi_2'),
          ('3_painting', 'painting', 'haitian_3'), ('4_spine', 'spine', 'aersasi'),
          ('5_voice', 'voice', 'aersasi_2')]


class Page:
    def __init__(self, port, profile, url, win, gpu=False, keepalive=True):
        """gpu=True 时不传 SwiftShader，走机器真实 GPU（D3D11）。

        为什么需要（2026-10-25，TROUBLESHOOTING §137 已被实证）：SwiftShader 与真 GPU
        对 Live2D 的 `isVisible` 判定不一致（实测 ArtMesh255~258 在软件渲染 vis=1、
        真 GPU vis=0），而用户环境是硬件光栅化。**凡对账「可见性/像素」的裸页判据，
        默认的 SwiftShader 路径会给出系统性偏差的假绿灯**，必须用 gpu=True 复测。

        keepalive=True 强制注入焦点仿真（TROUBLESHOOTING §158 续五，2026-10-28 实证）。
        为什么必须有：`--headless=new` 的页面会被判成**后台文档**，`document.visibilityState`
        在加载后几秒变 `hidden`，浏览器随即**停掉 requestAnimationFrame**。实测（A/B 对照，
        ougen_8，8 秒窗口）：
          · 不加任何保活        → rAF 推进 7 帧（≈1 fps），ticker 长期 Δ0
          · 只加 --disable-renderer-backgrounding / --disable-backgrounding-occluded-windows
                                → 0 帧，visibility 仍 hidden（**无效**）
          · Page.setWebLifecycleState('active') → 第 1 秒仍 Δ0，只到 ≈1 fps（**无效**）
          · Emulation.setFocusEmulationEnabled(true) → **393 帧 ≈ 49 fps，ticker 每秒精确
            推进 1000 ms，visibility 恒 visible**
        仪器后果（都真实发生过，别再归因于产品）：Live2D 动画 450 ms 的 tween 实耗 2–3 s、
        参数 pin 要约 1.0 s 才落进 coreModel、`readUntilStable` 读到中途值判「参数值不稳定」、
        `core.update` 入口采样全帧同值被当成「写入被覆盖」。**这些都是 rAF 停摆的投影。**

        keepalive=False 只用于阴性对照（证明保活确实是成因）。

        keepalive 现在做**两件**事，缺一不可（2026-10-28 补，实证见 TROUBLESHOOTING §158 续六）：

        ② `Page.bringToFront` + 每 `KEEPALIVE_PERIOD`(默认 8s) 重发一次。
           为什么必须周期性重发：只做 ① 的话，页面**加载约 20 秒后**渲染器仍会失去
           「前台窗口」身份，出帧源被降到**精确 1 Hz**（`gapMax` 从 193 ms 跳到 1033 ms）。
           实测（极简 800x600 WebGL 页，不含任何产品代码，同一台机）：
             · 0–18s 60.0 fps；20s 13.5；26s 2.0；42s 1.0；**全程 `visibilityState=visible`、
               `hasFocus=true`** —— 两个属性都看不出问题；
             · 已衰减后调一次 `Page.bringToFront` → **1.5 fps 立刻回到 60.0，并持续稳定
               32 秒以上不再衰减**（后续四轮施救读数全 60，因为状态已被 R1 修复）。
           ⚠️ 这一条推翻了三处旧结论，留痕勿再重犯：
             · 「`--headless=new` 被判后台 ⇒ rAF 停摆 ⇒ 只能靠 setFocusEmulationEnabled」
               —— 伪造 focus 完全挡不住这个 1 Hz（衰减期间 `hasFocus` 一直是 true）；
             · 「`--disable-features=CalculateNativeWinOcclusion` 能关掉」—— 实测仍衰减；
             · 「点舰船卡导致帧率衰减」—— 极简页也会衰减，且时间点与「加载后 18–23 秒」
               重合 ⇒ 每次点击恰好落在潜伏期尾声，是**时间巧合**，不是点击触发。
           ⚠️ 连带后果（本轮十四次排除法里有一半要重做）：所有「极简页/对照页稳定 60fps」
           的阴性结论都只观测了 10–12 秒，正好卡在潜伏期内 ⇒ 不能拿来做排除法依据。
        """
        flags = [CHROME, '--headless=new',
                 f'--remote-debugging-port={port}', '--remote-allow-origins=*',
                 f'--user-data-dir={profile}', '--no-first-run', '--no-default-browser-check',
                 '--disable-background-timer-throttling']
        if not gpu:
            flags += ['--enable-unsafe-swiftshader', '--use-angle=swiftshader']
        flags += [f'--window-size={win[0]},{win[1]}', url]
        self.proc = chrome_tree.launch(
            flags, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        ws = None
        for _ in range(100):
            try:
                tabs = json.load(urllib.request.urlopen(f'http://127.0.0.1:{port}/json'))
                m = [t for t in tabs if 'gallery_v2' in t.get('url', '') and t.get('webSocketDebuggerUrl')]
                if m:
                    ws = m[0]['webSocketDebuggerUrl']
                    break
            except Exception:
                pass
            time.sleep(0.5)
        if not ws:
            raise RuntimeError('no CDP tab')
        self.ws = websocket.create_connection(ws, timeout=180, max_size=None)
        self._id = 0
        self._lock = threading.Lock()
        self.cmd('Page.enable'); self.cmd('Runtime.enable')
        # 关缓存（2026-10-30）：`model3.json` 是被浏览器缓存的静态文件，
        # 改了判定区/动作组后**新开的探针仍会读到旧副本** —— 实测 `hit_verify` 报
        # `nAreas: 60`，而服务器明明已经吐出 120 条。这类「改了不生效」会被误判成产品缺陷。
        # 探针一律禁缓存；产品侧靠服务器已有的 `Cache-Control: no-cache` 兜底。
        try:
            self.cmd('Network.enable')
            self.cmd('Network.setCacheDisabled', {'cacheDisabled': True})
        except Exception:
            pass
        self.keepalive = keepalive
        if keepalive:
            self.cmd('Emulation.setFocusEmulationEnabled', {'enabled': True})
            self.cmd('Page.bringToFront')
            self._hb_stop = threading.Event()
            self._hb = threading.Thread(target=self._heartbeat, daemon=True)
            self._hb.start()

    KEEPALIVE_PERIOD = 8.0

    # ---- 帧源解耦（2026-10-28）--------------------------------------------
    # 见 `__init__` docstring ②：headless 下浏览器会在加载 18–30 秒后把出帧源降到
    # 1 Hz **甚至完全停掉 rAF**（实测 `vis=hidden`、`__rafc.n` 恒 0），而产品每帧成本
    # 全程平稳（core.update 6 ms / render 11 ms）。此时任何逐帧判据都会输出
    # 「0 差异 / 参数没变」的**假结论**。
    # 解法：`ticker.stop()` 后自己用定时器 `ticker.update(now)` 推帧 —— 帧源不再经过
    # 浏览器的 BeginFrame，节流管不到。实测同一条页面：rAF 侧 0.0 fps，推帧侧
    # 90.8 → 90.2 帧/秒持续 40 秒，`lastTime` 单调递增。
    FRAME_DETACH = r"""(function(fps){
      var tk=window.__l2Ticker&&window.__l2Ticker();
      if(!tk) return 'NO_TICKER';
      if(window.__framePump) return 'already';
      // 🔴 **必须推两个 ticker，不是一个**（2026-10-28 实测，第八条仪器 bug）：
      //   · `app.ticker`            = 页面自己的 stateTick / 参数 pin / 最终 render
      //   · `PIXI.Ticker.shared`    = pixi-live2d-display 的 model.update →
      //                               `internalModel.update()` → **`coreModel.update()`**
      //     （vendor/live2d/pixi-live2d-display-cubism4-patched.js:4936 `onTickerUpdate`
      //       读的是 `tickerRef.shared`；PIXI.Application 默认 `sharedTicker:false`，
      //       所以两者是**不同实例**。）
      // 只推 app.ticker 时的现象：画面照常渲染、本次推帧计数照样报 59.9 fps（假绿灯），
      // 但 `core.update` 入口**一次都没被调用** —— `render_entry_verify` 因此拿到
      // 「__u 空数组 / n=0 帧」。不要再只推一个。
      var tks=[tk], sh=(window.PIXI&&window.PIXI.Ticker&&window.PIXI.Ticker.shared)||null;
      if(sh && sh!==tk) tks.push(sh);
      tks.forEach(function(t){ t.autoStart=false; t.stop(); });
      var step=1000/(fps||60);
      var p={n:0,t0:performance.now(),last:performance.now(),fps:fps||60,
             err:null,push:0,cost:0,ntk:tks.length,ticks:0,maxItv:0,_ip:0};
      window.__framePump=setInterval(function(){
        var now=performance.now();
        // 定时器自身是否被限流：`ticks`/秒 与相邻回调间隔最大值。若 `ticks` 远小于
        // 250/s（4ms 间隔的理论值）而 `n` 也跟着小，那是**定时器**被浏览器钳住的证据；
        // 若 `ticks` 正常而 `n` 小，那是单帧成本（`cost`）顶住了，属于机器物理上限。
        // 两者都表现为「fps 不够」，但一个是仪器、一个是硬件，处置完全不同。
        p.ticks++;
        if(p._ip){ var itv=now-p._ip; if(itv>p.maxItv) p.maxItv=+itv.toFixed(1); }
        p._ip=now;
        // **用墙钟封顶**：此刻应收到的帧数 = 自 t0 起经过的步数。只推到 due 为止，
        // 因此推帧率物理上不可能超过 fps。旧写法用累加器 `acc` 且上限 2 步/ tick，
        // 一旦 setInterval 被堆叠就会猛推（实测 430–2078 帧/秒）。
        var due=Math.floor((now-p.t0)/step);
        if(due-p.n>10){ p.t0=now-p.n*step; due=p.n; }  // 掉队超过 10 帧就重锚，不补帧
        var guard=0, t0c=performance.now(), did=0;
        while(p.n<due && guard++<3){
          p.n++; p.push++; p.last=now; did++;
          for(var i=0;i<tks.length;i++){
            try{ tks[i].update(now); }catch(e){ p.err='tk'+i+':'+e; }
          }
        }
        // 单帧真实成本（ms，指数滑动平均）：模型 update + render 的实际耗时。
        // 它决定**这套推帧器最多能跑多快** —— 1400x1000 的 Live2D 页实测 20–30 ms/帧，
        // 即 30–50 fps 是这台机器的物理上限，不是节流。
        if(did) p.cost=+(p.cost*0.8 + (performance.now()-t0c)/did*0.2).toFixed(2);
      }, 4);
      window.__framePumpStat=p; return 'ok';
    })(%d)"""

    FRAME_REATTACH = r"""(function(){
      if(window.__framePump){ clearInterval(window.__framePump); window.__framePump=0; }
      var tk=window.__l2Ticker&&window.__l2Ticker();
      if(tk){ tk.autoStart=true; tk.start(); }
      var sh=(window.PIXI&&window.PIXI.Ticker&&window.PIXI.Ticker.shared)||null;
      if(sh&&sh!==tk){ sh.autoStart=true; sh.start(); }
      return 'ok';})()"""

    # 帧源存活采样：优先读推帧器**自己**算的速率；未推帧时读探针侧挂在 ticker 上的计数器。
    # ⚠️ 为什么速率要在页内算：探针 `ev()` 一次往返可能 1–2 ms，也可能 40 ms；用 Python
    # 侧时间基准算「每秒增量」会把往返抖动直接算进帧率（实测同一页给出 546–700 帧/秒，
    # 且 pump 与 raf 读数完全相等 ⇒ 那是往返时延，不是帧率）。页内 `performance.now()`
    # 是单调时钟，不受宿主影响。
    #
    # ⚠️⚠️ `__rafc` 在产品里**不存在**（2026-10-29 核实：产品只导出 `__l2TickerState`
    # 与 `__l2Ticker`），旧写法退到 `src:'raf'` 那支永远进不去，落到 `src:'ticker'` 且
    # `n:0` ⇒ `frames_alive` 的 `(b.n-a.n)/dm` 恒为 0 ⇒ **`frames_alive` 永远判红**。
    # 而且 `lastTime` 也不能拿来判帧率：它随真实时间推进，被节流到 1 Hz 时一个采样窗口
    # 里照样涨满 `dm`，与满帧无法区分（这正是「假绿灯」的形状）。
    # 正确做法 = 在**ticker 活对象**上挂一个探针自己的计数器（`__l2Ticker()` 是只读出口，
    # 返回活对象，加 listener 不影响产品逻辑；PIXI 每帧都会调用它）。
    FRAME_SAMPLE = r"""(function(){try{
      // ⚠️ 判 pump 是否**还挂着**要看 `__framePump`（interval id），不能看 `__framePumpStat`
      // ——`reattach_frames()` 只清 id、留着 stat 对象，先前的写法会在重挂之后继续
      // 报 src='pump'（假「还在推帧」）。本探针的 `reattach后 src:` 一度就是这么错的。
      var p=window.__framePumpStat;
      if(p && window.__framePump){ var el=(performance.now()-p.t0)/1000;
        return JSON.stringify({src:'pump',n:p.n,
          fps:+(p.n-el*p.fps>0?p.fps:p.n/el).toFixed(1),
          t:p.last,err:p.err,cost:p.cost,ntk:p.ntk,
          ticks:p.ticks,maxItv:p.maxItv}); }
      var tk=window.__l2Ticker&&window.__l2Ticker();
      if(tk){
        var c=window.__probeFrameCounter;
        if(!c || c.tk!==tk){
          c=window.__probeFrameCounter={tk:tk,n:0};
          try{ tk.add(function(){ c.n++; }); }catch(e){ return JSON.stringify(
            {src:'exc',err:'add:'+e}); }
        }
        var st=window.__l2TickerState&&window.__l2TickerState();
        return JSON.stringify({src:'ticker',n:c.n,fps:(st?st.fps:0),
          t:(st?st.lastTime:0),err:null,started:(st?!!st.started:null)});
      }
      return JSON.stringify({src:'none',n:0,fps:0});
    }catch(e){ return JSON.stringify({src:'exc',err:''+e}); }})()"""

    def detach_frames(self, fps=60):
        return self.ev(self.FRAME_DETACH % fps)

    def reattach_frames(self):
        return self.ev(self.FRAME_REATTACH)

    def frames_alive(self, seconds=2.0, min_fps=45.0):
        """测当前帧源是否真的在推进，返回 (ok, fps, sample)。

        **所有逐帧判据都必须先过这一闸**：`0 差异` 与 `参数被覆盖` 这类结论在帧源
        停摆时无法与真实缺陷区分（本项目已因此误判多次）。过不了就直接抛错，
        让探针红掉，而不是带着假读数继续跑。

        三种帧源统一用「n 的每秒增量」算，`t` 只作单调性旁证 —— 早先按 `t` 差值算
        在「`t` 每次读的是当下 `performance.now()`」的源上会恒得 0，那会让闸门永远判红
        （仪器自己的 bug，本轮踩过）。`ticker` 那支的 `n` 来自探针自己挂在活 ticker 上的
        计数器：`lastTime` 只随真实时间走，被节流到 1 Hz 时一个采样窗口里照样涨满，
        与满帧无法区分 —— 拿它当帧率就是假绿灯。
        """
        a = json.loads(self.ev(self.FRAME_SAMPLE))
        if a['src'] in ('none', 'exc'):
            return False, 0.0, a
        t0 = time.time()
        time.sleep(seconds)
        b = json.loads(self.ev(self.FRAME_SAMPLE))
        dm = (time.time() - t0)
        fps = (b['n'] - a['n']) / dm if dm else 0.0
        return fps >= min_fps, fps, b

    def require_frames(self, seconds=2.0, min_fps=0.0):
        """所有逐帧判据的前置闸。**只抓"帧源停摆"，不判"快不快"**。

        为什么把"快不快"从判据里拿掉（2026-10-28 实测，第八条仪器 bug）：
          解耦模式下每帧都要真实跑一次 `ticker.update()`（模型 update + render），
          1400x1000 的 Live2D 页单帧成本 9–27 ms，另加 setInterval(4) 被浏览器钳到
          ≈8–10 ms/次 ⇒ 实测帧率 36.7（JIT 预热期）→ 48.9 → 57.7 → 54–58 稳态。
          拿写死的 55 判红时，红的是**预热 + 硬件成本**，而"帧源停摆"根本不存在
          （`n` 一路在涨、`err=None`）。这类"用硬件成本去判仪器"的错误本轮已犯两次。
        所以判据改为：
          ① `n` 必须真的在涨（≥ `MIN_FPS`=8 即排除 1 Hz 节流与完全停摆）；
          ② 传了 `min_fps` 时，仍按该值判（给"这条探针确实需要 60 帧"的场景留口子）。
          可达上限（`1000/max(cost, maxItv)`）只写进 `self.last_gate` 供打印诊断，
          **不参与判定** —— 它本身也不可靠：`maxItv` 会被页面加载/换肤这种一次性长任务
          污染（实测 503.6 ms），拿它算上限会算出荒谬的 2 fps。
        """
        ok, fps, s = self.frames_alive(seconds, max(min_fps, self.MIN_FPS))
        cost = float(s.get('cost') or 0)
        maxitv = float(s.get('maxItv') or 0)
        self.last_gate = dict(s, reachable=round(1000.0 / max(cost, 4.0), 1))
        if s['src'] in ('none', 'exc'):
            raise RuntimeError('帧源不可用：src=%s err=%s' % (s.get('src'), s.get('err')))
        if not ok:
            raise RuntimeError(
                '帧源停摆：%.1f fps（阈值 %.0f）src=%s ntk=%s err=%s cost=%sms '
                'ticks=%s maxItv=%sms —— 此时任何逐帧判据都不可信'
                % (fps, max(min_fps, self.MIN_FPS), s.get('src'), s.get('ntk'),
                   s.get('err'), s.get('cost'), s.get('ticks'), s.get('maxItv')))
        return fps

    MIN_FPS = 8.0

    def _heartbeat(self):
        """周期性把页面拉回前台。见 `__init__` docstring ②。

        8 秒一次：实测衰减的触发点在加载后 18–23 秒，且恢复后 R1 单独一次就稳定了 32 秒；
        8 秒意味着在第一次可能的衰减之前就至少已重发两次，留足余量。
        """
        while not self._hb_stop.wait(self.KEEPALIVE_PERIOD):
            try:
                self.cmd('Page.bringToFront')
            except Exception:
                return

    def cmd(self, m, p=None):
        # 心跳线程与主线程共用一条 websocket；`self._id` 的递增与 recv 匹配必须原子，
        # 否则两边的响应会互相吞掉（表现为某次 cmd 永远等不到自己的 id）。
        with self._lock:
            self._id += 1; mid = self._id
            self.ws.send(json.dumps({'id': mid, 'method': m, 'params': p or {}}))
            self.ws.settimeout(180)
            while True:
                r = json.loads(self.ws.recv())
                if r.get('id') == mid:
                    return r.get('result', {})

    def ev(self, expr):
        r = self.cmd('Runtime.evaluate', {'expression': expr, 'returnByValue': True, 'awaitPromise': True})
        if r.get('exceptionDetails'):
            ed = r['exceptionDetails']
            ex = ed.get('exception', {}) or {}
            # SyntaxError 的信息在 text / description 里，**不在 message 里**——
            # 只取 message 会输出一句没用的 "EXC None"（2026-09-28 白转两轮）。
            msg = ex.get('description') or ex.get('value') or ed.get('text') or 'no detail'
            return 'EXC ' + str(msg)[:300]
        return r.get('result', {}).get('value')

    def shot(self, path):
        d = base64.b64decode(self.cmd('Page.captureScreenshot', {'format': 'png'})['data'])
        open(path, 'wb').write(d)

    def close(self):
        try: self._hb_stop.set()
        except Exception: pass
        try: self.reattach_frames()
        except Exception: pass
        try: self.cmd('Browser.close')
        except Exception: pass
        try: self.proc.wait(timeout=10)
        except Exception: chrome_tree.kill_tree(self.proc.pid)


def open_state(pg, tab, key):
    if tab is None:
        return pg.ev("document.querySelectorAll('.card').length")
    return pg.ev("""(()=>{const k=%r,t=%r;
      const hit=G.ships.find(s=>(s.live2dSkins||[]).includes(k)||(s.spineSkins||[]).includes(k)
                    ||s.skins.some(x=>x.key===k));
      if(!hit) return 'NO_SHIP';
      const sk=hit.skins.find(x=>x.key===k)||hit.skins[0];
      openShip(hit); setSkin(sk); buildSkinList(hit); tab=t; renderView();
      [...document.getElementById('mTabs').children].forEach(c=>c.classList.toggle('on', c.dataset.k===t));
      return 'ok';})()""" % (key, tab))


def preflight(page):
    """先探一次服务再启动 Chrome。真实翻车：8777 上的服务器静默死掉后，本工具照样
    截出 5 张"空白页"并逐条打印文件名、退出码 0 —— 判据必须能红。"""
    url = f'{BASE}/{page}'
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            if r.status != 200:
                raise RuntimeError(f'{url} -> HTTP {r.status}')
    except Exception as e:
        raise SystemExit(f'! 先起服务器再跑（{url} 不可达：{e}）\n'
                         f'  双击 Output\\gallery_v2\\启动资产浏览器.bat，'
                         f'或不弹浏览器地起：py -3 scripts/diag/run_detached.py --log .diag/_srv.log -- py -3 Output/gallery_v2/_gallery_server.py')
    return url


def assert_rendered(pg, page, name, tab):
    """每拍一张都要证明"画面真的渲染了"，而不是只证明脚本没抛异常。"""
    n = pg.ev("""(()=>{const v=document.getElementById('mView');
      return JSON.stringify([document.querySelectorAll('.card').length,
        !!window.GALLERY, v?v.childElementCount:0,
        (document.querySelector('.note')||{}).textContent||'']);})()""")
    cards, has_g, vchildren, note = json.loads(n)
    if not has_g:
        raise SystemExit(f'! {page} / {name}: window.GALLERY 不存在（index.js 没加载？）')
    if cards == 0:
        raise SystemExit(f'! {page} / {name}: 网格一张卡都没渲染（页面脚本崩了或 index.js 坏了）')
    if tab and vchildren == 0:
        raise SystemExit(f'! {page} / {name}: #mView 是空的，note={note[:80]!r}')
    return cards


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--pages', default=os.environ.get('SHOTS_PAGES', 'index.html'),
                    help='逗号分隔：要截的页面（默认只 index.html；对比两份写 a.html,b.html）')
    ap.add_argument('--tags', default=os.environ.get('SHOTS_TAGS', 'cur'))
    ap.add_argument('--win', default='2560,1600')
    ap.add_argument('--out', default=os.path.join(ROOT, '.diag', 'uishots'))
    ap.add_argument('--port', type=int, default=9431)
    a = ap.parse_args()
    pages = a.pages.split(',')
    tags = a.tags.split(',')
    win = tuple(int(v) for v in a.win.split(','))
    os.makedirs(a.out, exist_ok=True)
    profile = os.path.join(ROOT, '.diag', 'chrome_uishots')
    os.makedirs(profile, exist_ok=True)
    for tag, page in zip(tags, pages):
        preflight(page)
        print(f'== {tag}  {page} ==')
        pg = Page(a.port, profile, f'{BASE}/{page}', win)
        time.sleep(7)
        pg.ev("localStorage.clear()")
        pg.cmd('Page.navigate', {'url': f'{BASE}/{page}'})
        # 就绪门槛（scripts/diag/cdp_wait.py）：不能拿 document.readyState 当判据 ——
        # CDP 会话初连时执行上下文还在 about:blank，其 readyState 天生 'complete'，
        # 门槛第一次判就放行，后面全打在空白页上（本工具的症状是 5 张全空白 PNG）。
        # 同时替代原来那句裸 time.sleep(6) 的赌博。
        _ok, _secs, _last = cdp_wait.wait_ready(pg.ev, f'{BASE}/{page}', budget=150)
        print(f'  [ready] ok={_ok} {_secs}s' + ('' if _ok else f' last={_last}'))
        if not _ok:
            pg.close()
            raise SystemExit(f'! {page}: 页面在预算内未就绪（探针故障，非产品故障）')
        for name, tab, key in STATES:
            r = open_state(pg, tab, key)
            if tab:
                time.sleep(WAIT[tab])
            cards = assert_rendered(pg, page, name, tab)
            out = os.path.join(a.out, f'{tag}_{name}.png')
            pg.shot(out)
            print(f'  {name:<12} 卡片{cards:>5}  {str(r):<8} -> {os.path.basename(out)}')
        pg.close()
        time.sleep(1.5)


if __name__ == '__main__':
    main()
