# -*- coding: utf-8 -*-
"""Live2D 坐标系取证：验证「顶点 V ↔ 屏幕 P」仿射换算是否正确。

背景（2026-09-23 实测，TROUBLESHOOTING §20）：
  coreModel.getDrawableVertexPositions() 返回 V = Cubism 原生坐标（画布中心为原点、y 向上），
  而 mdl.toLocal()/pixelsPerUnit 得 P = 左上角原点、y 向下。换算：Vx=Px-cux/2，Vy=cuy/2-Py。

判据：在可见模型的 head/chest/hip 三个语义位置反查（不经过被测映射的独立锚点），
      经 flip 映射后应分别落入 Head / Special / Body 框；恒等映射应全部脱靶。
      若 flipHits 出现明显错配（如 head 落到 Body），说明前端 P2V/V2P 或框生成有问题。

用法: py -3 scripts/diag/l2d_coord_forensics.py [皮肤key，默认 aersasi_2]
输出: .diag/_probe_affine.json（UTF-8），终端打印摘要
退出码: 0=判据成立 / 2=探针自身故障（拿不到执行上下文）/ 3=样本不在画廊或页面报错（未评估）
"""
import sys, os, json, time, subprocess, urllib.request
sys.stdout.reconfigure(encoding='utf-8')
import websocket
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import chrome_tree
import cdp_wait
from probe_exit import bad_reason, available_keys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import cdp_slot            # 端口 / profile 不写死：写死会让两个会话灌进同一个页面（见该模块 docstring）
# 画廊地址不写死：8777 可能是另一份画廊（旧机全库），在那上面 PASS 不证明本项目生效
GALLERY = os.environ.get('GALLERY_URL', 'http://127.0.0.1:8777/gallery_v2/index.html')
CHROME = r'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
PORT, PROFILE = cdp_slot.slot(ROOT, 'coordfix')
proc = chrome_tree.launch([CHROME, '--headless=new', f'--remote-debugging-port={PORT}',
  '--remote-allow-origins=*', f'--user-data-dir={PROFILE}', '--no-first-run',
  '--no-default-browser-check', '--disable-background-timer-throttling', '--enable-unsafe-swiftshader',
  '--use-angle=swiftshader', '--window-size=1280,900',
  GALLERY], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
    ws.send(json.dumps({'id': mid, 'method': m, 'params': p or {}})); ws.settimeout(180)
    while True:
        r = json.loads(ws.recv())
        if r.get('id') == mid:
            if 'error' in r: raise RuntimeError(json.dumps(r['error'])[:150])
            return r.get('result', {})
def ev(e):
    r = cmd('Runtime.evaluate', {'expression': e, 'returnByValue': True, 'awaitPromise': True})
    if r.get('exceptionDetails'): return 'EVALERR ' + str(r.get('exceptionDetails'))[:300]
    return r.get('result', {}).get('value')

KEY = sys.argv[1] if len(sys.argv) > 1 else 'aersasi_2'
JS = r"""(async(key)=>{ try{
  const t=ms=>new Promise(r=>setTimeout(r,ms));
  for(let i=0;i<90 && !window.GALLERY;i++) await t(300);
  let ship=null, sk=null;
  for(const s of GALLERY.ships){ const k=s.skins.find(x=>x.key===key); if(k&&s.live2dSkins.includes(key)){ship=s;sk=k;break;} }
  if(!sk) return JSON.stringify({key, skip:'no skin'});
  openShip(ship); setSkin(sk); buildSkinList(ship);
  const l2=[...document.querySelectorAll('#mTabs .tab')].find(x=>x.dataset.k==='live2d');
  l2.click();
  /* ⚠️ 判据必须是 `typeof l2State!=='undefined'`，**不是 `window.l2State`**：页面用 `let l2State`
     声明（不挂到 window 上），`window.l2State` 恒为 undefined ⇒ 门槛第一次判就"通过"、后续
     读所有字段全是 undefined，探针 100% 失败（2026-10-27 实测：`typeof window.l2State`=undefined
     而 `typeof l2State`=object）。`typeof X` 不抛异常，同时兼容 `let` 与挂在 window 上的写法。 */
  /* 预算 200×500ms=100s：按最坏情形（连跑/冷启）定，不按单跑实测拍（§156 形态三）。 */
  for(let i=0;i<200 && !(typeof l2State!=='undefined'&&l2State&&l2State.app&&l2State.app.stage&&l2State.app.stage.children[0]);i++) await t(500);
  if(!(typeof l2State!=='undefined'&&l2State&&l2State.app&&l2State.app.stage&&l2State.app.stage.children[0]))
    return JSON.stringify({key, fail:'100s 内模型未进入舞台'});
  const app=l2State.app, m=app.stage.children[0];
  if(!m||!m.internalModel) return JSON.stringify({key, fail:'舞台首个子节点没有 internalModel'});
  const im=m.internalModel, core=im.coreModel, ppu=im.pixelsPerUnit||1;
  /* ⚠️ y 方向画布边长必须用 height/ppu，不是 width/ppu——非正方形画布用同一个 cu 会整体偏移，
     而那正好会被判据「吞掉」（两列都错、一眼看不出来）。 */
  const cux=im.width/ppu, cuy=im.height/ppu;
  const out={key, cux:+cux.toFixed(3), cuy:+cuy.toFixed(3), boxes:[]};
  const P2V=(px,py,flip)=>({x:px-cux/2, y:flip?cuy/2-py:py-cuy/2});
  for(const a of (im.settings.hitAreas||[])){
    const idx=core.getDrawableIndex(a.Id); if(idx<0) continue;
    const p=core.getDrawableVertexPositions(idx); if(!p||!p.length) continue;
    let x0=1e9,y0=1e9,x1=-1e9,y1=-1e9;
    for(let k=0;k+1<p.length;k+=2){ if(p[k]<x0)x0=p[k]; if(p[k]>x1)x1=p[k]; if(p[k+1]<y0)y0=p[k+1]; if(p[k+1]>y1)y1=p[k+1]; }
    out.boxes.push({name:a.Name, V:[+x0.toFixed(2),+y0.toFixed(2),+x1.toFixed(2),+y1.toFixed(2)]});
  }
  const wrap=document.getElementById('l2wrap');
  const pts=[{tag:'head',sx:0.44,sy:0.27},{tag:'chest',sx:0.44,sy:0.47},{tag:'hip',sx:0.44,sy:0.66}];
  out.pts=[];
  for(const q of pts){
    const lp=m.toLocal(new PIXI.Point(wrap.clientWidth*q.sx, wrap.clientHeight*q.sy));
    const Px=lp.x/ppu, Py=lp.y/ppu;
    const id={x:Px,y:Py}, flip=P2V(Px,Py,true);
    const inBox=(v,b,pad=0.5)=> v.x>=b[0]-pad&&v.x<=b[2]+pad&&v.y>=b[1]-pad&&v.y<=b[3]+pad;
    out.pts.push({tag:q.tag, P:[+Px.toFixed(2),+Py.toFixed(2)],
      identityHits:out.boxes.filter(b=>inBox(id,b.V)).map(b=>b.name),
      flipHits:out.boxes.filter(b=>inBox(flip,b.V)).map(b=>b.name)});
  }
  return JSON.stringify(out,null,1);
}catch(e){ return 'ERR '+(e.message||e); }})"""
out = None
# 🔴 就绪门槛必须是「URL 真的到了 + readyState complete + GALLERY 在」。
# 旧版只看 readyState：CDP 连上时执行上下文还是 about:blank，而 about:blank 的
# readyState 天生 complete ⇒ 第一次判就放行，后续求值全打在空白页上，报出
# `openShip is not defined` / `internalModel undefined` 这类**探针自身假失败**。
ok, secs, last = cdp_wait.wait_ready(ev, GALLERY, budget=120)
print(f'  [ready] ok={ok} {secs}s last={last}', flush=True)
for _try in range(8):
    try:
        out = ev(JS + f"({json.dumps(KEY)})"); break
    except RuntimeError as e:
        # 页面仍在导航时 CDP 执行上下文会被销毁 —— 探针自身的假失败（WF-16 已记过同类），
        # 上下文在导航结束后会重建，等一拍重连同一张 tab 即可，别据此判定产品坏了。
        print(f"  [retry {_try+1}] {str(e)[:80]}", flush=True); time.sleep(4)
if out is None:
    print('[ERROR] 6 次仍拿不到稳定执行上下文'); ws.close(); chrome_tree.kill_tree(proc.pid); sys.exit(2)
path = os.path.join(ROOT, '.diag', '_probe_affine.json')
with open(path, 'w', encoding='utf-8') as f:
    f.write(out if isinstance(out, str) else json.dumps(out))
print(out)
print(f'\n已写出 {path}')
print('判据：head→Head / chest→Special / hip→Body（flipHits 列）；identityHits 应全空。')
ws.close(); chrome_tree.kill_tree(proc.pid)

# 🔴 探针「打印失败但 exit 0」= 判据与退出码脱节，runner 会把它记成通过（2026-10-27 实测
# 六件套第 2/3 件就是靠这个假绿过的）。凡 skip / fail / err 一律非零退出。
_bad = bad_reason(out)
if _bad:
    print(f'\n[NOT-EVALUATED] {_bad}')
    print('  本项目画廊实有 live2d 模型: ' + available_keys())
    print('  换样本重跑，例如: py -3 scripts/diag/l2d_coord_forensics.py aersasi_3')
    sys.exit(3)
print('\n[PASS] 坐标取证全部判据成立')
