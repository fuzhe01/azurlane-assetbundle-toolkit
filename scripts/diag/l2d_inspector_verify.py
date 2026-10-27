# -*- coding: utf-8 -*-
"""Live2D 检查器验收：判定区可视化 + 参数·部件面板（l2d.su 同款三件套）。

断言：
  ① 判定区开关：Graphics 出现且 visible=true，图形数=判定区数，标签=部位名；关闭后 visible=false
  ② 面板：行数 = 参数数 + 部件数；名字取到真实参数名（非 ParamN 占位）
  ③ 滑杆读写往返：setParameterValueByIndex 后读回一致；部件 setPartOpacityByIndex 同理
  ④ 过滤器：输入子串后可见行数减少且命中项包含该子串
用法: py -3 scripts/diag/l2d_inspector_verify.py [皮肤key，默认 lafeiii_3]
输出: .diag/_probe_feats.json、.diag/_areaviz_on.png（判定区开启时的截图）
退出码: 0=判据成立 / 2=探针自身故障 / 3=样本不在画廊或页面报错（未评估）
"""
import sys, os, json, time, base64, subprocess, urllib.request
sys.stdout.reconfigure(encoding='utf-8')
import websocket

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cdp_slot            # 端口 / profile 不写死：写死会让两个会话灌进同一个页面（见该模块 docstring）
import cdp_wait            # 就绪门槛不能用 document.readyState（about:blank 天生 complete）
from probe_exit import bad_reason, available_keys
GALLERY = os.environ.get('GALLERY_URL', 'http://127.0.0.1:8777/gallery_v2/index.html')
CHROME = r'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
PORT, PROFILE = cdp_slot.slot(ROOT, 'insp')
proc = chrome_tree.launch([CHROME, '--headless=new', f'--remote-debugging-port={PORT}',
  '--remote-allow-origins=*', f'--user-data-dir={PROFILE}', '--no-first-run',
  '--no-default-browser-check', '--disable-background-timer-throttling', '--enable-unsafe-swiftshader',
  '--use-angle=swiftshader', '--window-size=1280,900',
  GALLERY], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
import chrome_tree; chrome_tree.install(proc)   # 异常退出也要收整棵树，见该模块 docstring
w = None
for _ in range(90):
    try:
        tabs = json.load(urllib.request.urlopen(f'http://127.0.0.1:{PORT}/json'))
        w = [t['webSocketDebuggerUrl'] for t in tabs if 'gallery_v2' in t.get('url', '') and t.get('webSocketDebuggerUrl')]
        if w: break
    except Exception: pass
    time.sleep(0.5)
ws = websocket.create_connection(w[0], timeout=180, max_size=None)
_id = 0
def cmd(m, p=None):
    global _id; _id += 1; mid = _id
    ws.send(json.dumps({'id': mid, 'method': m, 'params': p or {}})); ws.settimeout(420)
    while True:
        r = json.loads(ws.recv())
        if r.get('id') == mid:
            if 'error' in r: raise RuntimeError(json.dumps(r['error'])[:150])
            return r.get('result', {})
def ev(e):
    r = cmd('Runtime.evaluate', {'expression': e, 'returnByValue': True, 'awaitPromise': True})
    if r.get('exceptionDetails'): return 'EVALERR ' + str(r.get('exceptionDetails'))[:300]
    return r.get('result', {}).get('value')

KEY = sys.argv[1] if len(sys.argv) > 1 else 'lafeiii_3'
JS = r"""(async(key)=>{ try{
  const t=ms=>new Promise(r=>setTimeout(r,ms));
  /* ⚠️ 页面每帧被**强制 10fps 节流**（`if(now-last<100) return requestAnimationFrame(tick);`）。
     所以下面所有"等 N 轮"的轮询真实耗时 = 轮数 × max(单轮间隔, 100ms)，无头下更慢。 */
  // 失败定位标记：JS 里任一步拿到 null 元素时，错误文本会带上"卡在第几步"，
    // 否则只会得到 `Cannot read properties of null (reading 'click')` 这种无法定位的消息。
    const me={step:'boot'};
    for(let i=0;i<120 && !(window.GALLERY && typeof openShip==='function');i++) await t(300);
  if(!window.GALLERY || typeof openShip!=='function') return JSON.stringify({key, err:'页面脚本未就绪（GALLERY/openShip 缺失）'});
  let ship=null, sk=null;
  for(const s of GALLERY.ships){ const k=s.skins.find(x=>x.key===key); if(k&&s.live2dSkins.includes(key)){ship=s;sk=k;break;} }
  if(!sk) return JSON.stringify({key, skip:'no skin'});
  openShip(ship); setSkin(sk); buildSkinList(ship);
  me.step='tab';
  const l2=[...document.querySelectorAll('#mTabs .tab')].find(x=>x.dataset.k==='live2d');
  if(!l2) return JSON.stringify({key, fail:'#mTabs 里没有 live2d 标签', tabs:[...document.querySelectorAll('#mTabs .tab')].map(x=>x.dataset.k)});
  l2.click();
  // 固定等 6s 会让大贴图皮肤（benningdun_2 三张共 40MB，服务器还是单线程）必然读不到模型，
  // 表现为脚本自身"偶发 ERR ... reading 'internalModel'"。改成轮询到模型出现，上限 90s
  // （实测 aersasi_2 也在 40~60s 区间浮动，40s 会偶发假失败）。
  // ⚠️ 模型加载轮询：headless + swiftshader 下整个页面被 10fps 节流，实测大贴图皮肤要 100s+。
  // 预算按实测天花板定，**别用"该模型平时多久"拍**——那是暖服务下的数。
  for(let i=0;i<150 && !(l2State&&l2State.app&&l2State.app.stage.children[0]);i++) await t(1000);
  me.step='waitModel';
  if(!(l2State&&l2State.app&&l2State.app.stage.children[0]))
      return JSON.stringify({key, fail:'150s 内模型未加载', note:(document.querySelector('.note')||{}).textContent||''});
  /* 模型挂上 stage 只代表渲染器起来了，条栏是随后才回填的（#l2bar 先只有"加载中…"）。
     等 stage.children[0] 出现就立刻取按钮会拿到 null —— 不是产品缺陷，是探针抢跑。
     判据改成"等目标控件真的存在"，最多 40s。 */
  me.step='waitBar';
  for(let i=0;i<80 && !document.getElementById('l2AreasBtn');i++) await t(500);
  if(!document.getElementById('l2AreasBtn'))
      return JSON.stringify({key, fail:'40s 内条栏未回填 #l2AreasBtn',
        barHTML:(document.getElementById('l2bar')||{}).innerHTML?.slice(0,200)||''});
  const out={key};
  const m=l2State.app.stage.children[0], core=m.internalModel.coreModel, im=m.internalModel;
  // ① 判定区可视化
  const st=l2State.app.stage;
  me.step='areasBtn';
  const areasBtn=document.getElementById('l2AreasBtn');
  if(!areasBtn) return JSON.stringify({key, fail:'#l2AreasBtn 不存在', bar:!!document.getElementById('l2bar')});
  /* ⚠️ 标签与「此刻在视口内的框」天然**差一帧**，不能直接 click 一次就读，也不能靠 sleep 等：
     标签由挂在 ticker 上的 drawAreas() 画（读到的是上一帧的 inView 结论），而 __L2_HITSHOW()
     是现算的。模型 idle 一直在动，道具框（TouchIdle/TouchDrag 系列）进出视口时两者必然不等
     —— 2026-10-27 实测 labels=7 vs shownN=4，多出来的 3 个正是刚出画的换装按钮框。
     确定解：onclick 的「打开」分支会**同步**调用 drawAreas()（index.html L2158），
     所以先关→再开，随后在**同一个 JS 任务**里读标签与 SHOW 就是同一帧（JS 单线程，
     中间插不进 ticker）。`await t(600)` 那种"等一会儿再读"是赌博，会退化成偶发假失败。 */
  if(!areasBtn.classList.contains('on')){ areasBtn.click(); await t(800); }
  areasBtn.click(); if(areasBtn.classList.contains('on')) areasBtn.click(); await t(150); areasBtn.click();
  const gfx=st.children.filter(c=>c instanceof PIXI.Graphics);
  const usable=(window.__L2_HITUSE? __L2_HITUSE().slice() : (im.settings.hitAreas||[]).map(a=>a.Name));
  const labels=st.children.filter(c=>c instanceof PIXI.Text && c.visible).map(c=>c.text);
  const shown=(window.__L2_HITSHOW? __L2_HITSHOW().slice() : usable.slice());
  out.areas={btnOn:document.getElementById('l2AreasBtn').classList.contains('on'),
             graphics:gfx.length, visible:gfx.map(g=>g.visible), shapes:gfx.map(g=>g.geometry.graphicsData.length),
             registered:(im.settings.hitAreas||[]).length, usableN:usable.length,
             shownN:shown.length,
             labels:labels};
  /* 2026-09-24 起登记数 ≠ 可点数：退化框（面积或宽/高≈0）被 geomOf 挡掉，既不可点也不画，
     否则那种点不到的框会抢走合法大框的点击（§27）。所以断言改成对齐**产品自己的可用清单**，
     并且要求画出的标签集合与它逐个相同 —— 比旧的"等于登记数"更强（旧的那条只看数量）。
     2026-09-27 再分一层：多边形按「可点清单」画，标签只按「此刻与视口相交的那批」画。
     换装按钮静止态被停在画布外（随动作才进画面），旧代码的 x clamp 会把它们的名字
     拽到屏幕右边缘，看着像"角落里点不到的判定区"。故标签基准换成 __L2_HITSHOW，
     仍与产品同源（探针不复算几何）。 */
  const drawn=out.areas.labels.slice().sort().join('|');
  out.areas.ok = out.areas.btnOn && out.areas.shapes[0]===usable.length
                 && out.areas.labels.length===shown.length
                 && drawn===shown.slice().sort().join('|');
  if(!out.areas.ok){ out.areas.expectLabels=shown.slice().sort(); }
  // ② 参数·部件面板
  me.step='panelBtn';
  const panelBtn=document.getElementById('l2PanelBtn');
  if(!panelBtn) return JSON.stringify({key, fail:'#l2PanelBtn 不存在', bar:!!document.getElementById('l2bar')});
  panelBtn.click(); await t(400);
  const pn=document.getElementById('l2panel'); const rows=pn.querySelectorAll('.prow');
  /* ⚠️ 面板期望行数**不能写成 getParameterCount()+getPartCount()**（旧口径，已过期）：
     面板现在有 4 个分区 —— 参数 / 换装 / **互动区** / 部件（`mkSec` 四处，L2212/2230/2294/2333），
     换装与互动区是服务端数据驱动、条数随模型变。旧口径在 ougen_8 上算出 expect=892 而实际
     rows=903（多出换装 11）→ 把「探针口径没跟上产品」误报成产品 FAIL。
     改成**从分区标题自推导**：每个 h5 声明了本区条数（`参数 582` / `换装 11` /
     `互动区 21（已登记 17）` / `部件 310`），逐区断言「声明数 == 该区实际 .prow 数」。
     这比旧口径更强：能抓到「标题写着 N、底下一条没画」——正是本文件要防的那类整批静默失效。 */
  const secs=[]; {
    /* 结构是 `pn.append(h5, groupDiv)` —— 行在**下一个兄弟节点**里，不是 h5 的直接子节点，
       也不是 pn 的直接子节点。按 h5 的 nextElementSibling 数 `.prow`。 */
    for(const h of pn.querySelectorAll('h5')){
      const m=/(\d+)/.exec(h.textContent);
      const g=h.nextElementSibling;
      secs.push({title:h.textContent, declared:m?+m[1]:null,
                 rows:g?g.querySelectorAll('.prow').length:0});
    }
  }
  const secBad=secs.filter(s=>s.declared!==s.rows).map(s=>s.title+' 声明'+s.declared+' 实际'+s.rows);
  const total=rows.length, sum=secs.reduce((a,s)=>a+s.rows,0);
  out.panel={on:pn.classList.contains('on'), rows:total, sumOfSections:sum,
             expect:core.getParameterCount()+core.getPartCount(),
             sections:secs.map(s=>s.title+' = '+s.rows),
             firstNames:[...rows].slice(0,4).map(r=>r.dataset.nm)};
  out.panel.ok = out.panel.on && secs.length>=2 && total===sum && secBad.length===0
                 && out.panel.firstNames.every(n=>!/^Param\d+$/.test(n));
  if(secBad.length) out.panel.secBad=secBad;
  // ③ 滑杆读写往返
  let target=null;
  for(let i=0;i<core.getParameterCount();i++){ if(core.getParameterMaximumValue(i)-core.getParameterMinimumValue(i)>=1){ target=i; break; } }
  out.roundtrip={};
  if(target!==null){ core.setParameterValueByIndex(target, core.getParameterMaximumValue(target));
    out.roundtrip.param={i:target, set:core.getParameterMaximumValue(target), read:+core.getParameterValueByIndex(target).toFixed(3)}; }
  core.setPartOpacityByIndex(0,0.3); out.roundtrip.part={read:+core.getPartOpacityByIndex(0).toFixed(2)}; core.setPartOpacityByIndex(0,1);
  out.roundtrip.ok = (!out.roundtrip.param || out.roundtrip.param.read===out.roundtrip.param.set) && out.roundtrip.part.read===0.3;
  // ④ 过滤器
  /* ⚠️ 不能写死 'a'：面板行名是小写参数名，478 个参数全叫 `param*`，子串 'a' 命中全部行，
     会让"过滤无效"看起来像产品 bug（实测 visible=total=559）。判据改成先用行名自算一个
     有区分度的子串（命中数 0<n<total/2），再用它验证过滤与命中一致性。 */
  const pickQ=()=>{ for(let L=3;L<=7;L++){ const cnt=new Map();
      for(const r of rows){ const p=(r.dataset.nm||'').slice(0,L); if(p.length<L) continue; cnt.set(p,(cnt.get(p)||0)+1); }
      let best=null,bn=0;
      for(const [p,n] of cnt) if(n>0 && n<rows.length/2 && (!best||n<bn)){ best=p; bn=n; }
      if(best) return best; } return null; };
  const q=pickQ();
  if(!q){ out.filter={ok:false, reason:'找不到有区分度的子串（行名过于同质）'}; }
  else{
    const f=pn.querySelector('.pf input'); f.value=q; f.oninput();
    const vis=[...rows].filter(r=>r.style.display!=='none');
    out.filter={q, visible:vis.length, total:rows.length,
                allMatch:vis.every(r=>r.dataset.nm.includes(q)),
                hiddenMatch:[...rows].filter(r=>r.style.display==='none').every(r=>!r.dataset.nm.includes(q))};
    out.filter.ok = out.filter.visible>0 && out.filter.visible<out.filter.total
                    && out.filter.allMatch && out.filter.hiddenMatch;
    f.value=''; f.oninput();
  }
  return JSON.stringify(out,null,1);
}catch(e){ return 'ERR['+me.step+'] '+(e.message||e); }})"""
out = None
# 🔴 就绪门槛：about:blank 的 readyState 天生 'complete'，只看它第一次判就放行，
# 后续求值全打在空白页上（§152/§155 同类假失败）。三件套判据见 cdp_wait 模块 docstring。
_ok, _secs, _last = cdp_wait.wait_ready(ev, GALLERY, budget=150)
print(f'  [ready] ok={_ok} {_secs}s last={_last}', flush=True)
if not _ok:
    print('[ERROR] 页面在预算内未就绪（探针故障，非产品故障）')
    ws.close(); chrome_tree.kill_tree(proc.pid); sys.exit(2)
for _try in range(6):
    try:
        out = ev(JS + f"({json.dumps(KEY)})"); break
    except RuntimeError as e:
        # 页面仍在导航时 CDP 执行上下文会被销毁 —— 探针自身的假失败（与"两个 Chrome 抢 CDP"
        # 是两类成因，串行也照犯）。上下文在导航结束后重建，重连同一张 tab 即可。
        print(f"  [retry {_try+1}] {str(e)[:70]}", flush=True); time.sleep(4)
if out is None:
    print('[ERROR] 6 次仍拿不到稳定执行上下文（探针故障，非产品故障）')
    ws.close(); chrome_tree.kill_tree(proc.pid); sys.exit(2)
with open(os.path.join(ROOT, '.diag', '_probe_feats.json'), 'w', encoding='utf-8') as f:
    f.write(out if isinstance(out, str) else json.dumps(out))
r = cmd('Page.captureScreenshot', {'format': 'png'})
shot = os.path.join(ROOT, '.diag', '_areaviz_on.png')
open(shot, 'wb').write(base64.b64decode(r['data']))
print(out)
print(f'\n截图: {shot}')
print('判据：areas.ok / panel.ok / roundtrip.ok / filter.ok 全为 true。')
ws.close(); chrome_tree.kill_tree(proc.pid)

# 🔴 探针「打印失败但 exit 0」= 判据与退出码脱节，runner 会记成通过（2026-10-27 实测六件套
# 第 2/3 件就是这样假绿的）。三档：0=PASS / 2=探针自身故障 / 3=未评估或判据不成立。
_bad = bad_reason(out)
_flags = {}
if not _bad:
    try:
        _j = json.loads(out) if isinstance(out, str) else out
        _flags = {k: bool((_j.get(k) or {}).get('ok')) for k in ('areas', 'panel', 'roundtrip', 'filter')}
    except Exception as e:
        _bad = f'payload 不是可解析 JSON: {e}'
if _bad:
    print(f'\n[NOT-EVALUATED] {_bad}')
    print('  本项目画廊实有 live2d 模型: ' + available_keys())
    print('  换样本重跑，例如: py -3 scripts/diag/l2d_inspector_verify.py aersasi_3')
    sys.exit(3)
_fail = [k for k, v in _flags.items() if not v]
if _fail:
    print('\n[FAIL] 判据不成立: ' + ', '.join(_fail))
    sys.exit(1)
print('\n[PASS] 判定区 / 面板 / 往返 / 过滤器 四项判据全部成立')
