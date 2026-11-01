r"""参数效果的**像素级**判据（API 通道之外的独立第二意见）。

为什么需要它
  `l2d_param_map_batch.py` 用 13 路 API 通道判「参数驱动哪些 drawable」，但它有一个
  结构性盲区：阈值是**绝对 V 空间**值（box/cen/disp 都判 >0.5）。眼睛/瞳孔这类 drawable
  自身可能只有 0.1 单位宽，变形 0.02 单位在屏幕上是十几个像素，在绝对阈值下却是「没变化」。
  ⇒ API 报 0 件不等于参数无效果。本工具直接比像素，并按 drawable 自身尺寸归一化，
  给出「相对变化」与「绝对变化」两套读数。

必须防的三个污染源（全部实测踩过）
  ① 眨眼：`InternalModel.update()` 里 `if(!motionUpdated) this.eyeBlink.updateParameters(...)`。
     只冻 idle/motion 时 `motionUpdated=false` ⇒ 眨眼**照跑**，随机改 ParamEyeLOpen/ROpen。
     实测：疑似「眼睛参数有效果」的 348 px / 103 px 差异，包围盒 (638,265)-(689,280)
     与眨眼包围盒 (639,266)-(689,282) 几乎重合，纯属采样撞上闭眼。
     正确冻法：`CubismEyeBlink` 的方法是 `updateParameters`（**不是** `update`）。
  ② 呼吸：`updateNaturalMovements` 每帧推 ParamAngleX/Y/BodyAngleX ⇒ 整模缓慢漂移。
  ③ 残留叠加：冻结后没人会替你把上一条参数复原，必须每条测完显式写回 lo 并 settle。

判据本身也要有区分力：跑阳性对照（已证驱动 4/9/25 件的 Cloth3/ShoseOff/Param233）。
阳性若与噪声同量级 ⇒ 本工具盲，任何 0 都不许当结论（AGENTS.md 人话版规则 5）。

用法
  py -3 scripts/diag/l2d_param_effect_pixel.py ougen_8 BondEyes HeartEyes ParamEyeSmile Cloth3
  py -3 scripts/diag/l2d_param_effect_pixel.py ougen_8            # 默认跑全部 + 3 条阳性对照

输出 `.diag/param_pixel/<模型>.json`：
  {模型: {参数: {px, ratio, box, top:[[idx, id, ext, chan, abs, rel], ...]}}}
退出码：0 全部有结论 / 2 环境或仪器红（冻结漂移 / 帧源停摆 / 阳性对照无区分力）
"""
import base64
import faulthandler
import io
import json
import os
import sys
import time
import urllib.request

import numpy as np
from PIL import Image

sys.stdout.reconfigure(encoding='utf-8')
faulthandler.dump_traceback_later(1200, exit=True)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts', 'diag'))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

from gallery_ui_shots import Page  # noqa: E402

KEY = sys.argv[1] if len(sys.argv) > 1 else 'ougen_8'
ONLY = [a for a in sys.argv[2:] if not a.startswith('--')] or None
PORT = 9420
BASE = 'http://127.0.0.1:8778/gallery_v2/index.html#key=%s&tab=live2d' % KEY
OUT = os.path.join(ROOT, '.diag', 'param_pixel')
os.makedirs(OUT, exist_ok=True)

# 阳性对照：这些参数已由 API 通道证死驱动多件（4 / 9 / 25）。
CONTROLS = ['Cloth3', 'ShoseOff', 'Param233']
# 变化像素阈值：单通道差 >8（0..255）才算变化，滤掉 GPU 舍入噪声。
PIX_THR = 8
# 本底噪声红线：冻结成功后连拍必须几乎为 0。0.0005 ≈ 1000x800 里 400 px，
# 留给字形缓存/抗锯齿重绘的极小抖动；超过即判冻结失败。
NOISE_MAX = 0.0005

SNAP_ALL = r"""
(function(){
  var m=(window.__l2ModelRef&&window.__l2ModelRef())||null;
  if(!m||!m.internalModel) return '{"err":"NO_MODEL"}';
  var c=m.internalModel.coreModel, n=c.getDrawableCount(), out=[];
  for(var i=0;i<n;i++){
    var op=0, geo=null, vis=-1, uv=null, tex=-1, ro=0, bl=0;
    try{ op=+c.getDrawableOpacity(i); }catch(e){}
    try{ vis=c.getDrawableDynamicFlagIsVisible(i)?1:0; }catch(e){}
    try{ var v=c.getDrawableVertexPositions(i);
      if(v&&v.length>=2){ var x0=1e9,y0=1e9,x1=-1e9,y1=-1e9,sx=0,sy=0,nv=v.length/2;
        for(var k=0;k+1<v.length;k+=2){
          if(v[k]<x0)x0=v[k]; if(v[k]>x1)x1=v[k];
          if(v[k+1]<y0)y0=v[k+1]; if(v[k+1]>y1)y1=v[k+1];
          sx+=v[k]; sy+=v[k+1]; }
        var cx=sx/nv, cy=sy/nv, sp=0;
        for(var k2=0;k2+1<v.length;k2+=2){ sp+=Math.abs(v[k2]-cx)+Math.abs(v[k2+1]-cy); }
        geo=[+x0.toFixed(4),+y0.toFixed(4),+x1.toFixed(4),+y1.toFixed(4),
             +cx.toFixed(4),+cy.toFixed(4),nv,+(sp/nv).toFixed(4)]; } }catch(e){}
    try{ var t=c.getDrawableVertexUvs(i);
      if(t&&t.length>=2){ var su=0,sv=0,du=0,dv=0,m2=t.length/2;
        for(var u=0;u+1<t.length;u+=2){ su+=t[u]; sv+=t[u+1]; }
        var mu=su/m2, mv=sv/m2;
        for(var u2=0;u2+1<t.length;u2+=2){ du+=Math.abs(t[u2]-mu); dv+=Math.abs(t[u2+1]-mv); }
        uv=[+su.toFixed(3),+sv.toFixed(3),m2,+(du/m2).toFixed(4),+(dv/m2).toFixed(4)]; } }catch(e){}
    try{ tex=c.getDrawableTextureIndices(i); }catch(e){}
    try{ ro=c.getDrawableRenderOrders(i); }catch(e){}
    try{ bl=c.getDrawableBlendMode(i); }catch(e){}
    out.push([i,+op.toFixed(4),geo,vis,uv,tex,ro,bl]); }
  return JSON.stringify({n:n, rows:out});})()
"""

NAMES = """(function(){
  var m=(window.__l2ModelRef&&window.__l2ModelRef())||null;
  if(!m||!m.internalModel) return '[]';
  var c=m.internalModel.coreModel, n=c.getDrawableCount(), out=[];
  for(var i=0;i<n;i++){ var nm='';
    try{ nm=c.getDrawableId(i); }catch(e){}
    out.push([i,nm]); }
  return JSON.stringify(out);})()"""

NEUTRALIZE = """(function(){var m=(window.__l2ModelRef&&window.__l2ModelRef())||null;
  if(!m) return 'NO_MODEL';
  var im=m.internalModel, mm=im&&im.motionManager, done=[];
  if(mm&&mm.groups){ if(!mm.__idleBak) mm.__idleBak=mm.groups.idle;
    mm.groups.idle='__hz_frozen__'; done.push('idle'); }
  try{ if(mm){ mm.queueManager.stopAllMotions(); mm.state.reset&&mm.state.reset(); } done.push('mot'); }catch(e){}
  if(typeof im.updateNaturalMovements==='function'){
    im.updateNaturalMovements=function(){}; done.push('breath'); }
  /* 眨眼：真名是 updateParameters（InternalModel 里 `if(!motionUpdated) eyeBlink.updateParameters(model,dt)`）。
     替换成「把眨眼目标参数写回 1」而不是空函数——空函数会让眼睛停在上一次眨眼值，
     若恰好停在半闭状态，整个测量过程都在半闭眼上做，读数失去意义。 */
  var eb=im.eyeBlink;
  if(eb&&typeof eb.updateParameters==='function'){
    if(!eb.__hzBak) eb.__hzBak=eb.updateParameters;
    eb.updateParameters=function(model){
      try{ var ids=(model&&model.parameters&&model.parameters.ids)||[];
        for(var i=0;i<ids.length;i++){ if(/^ParamEye[LR]Open$/.test(String(ids[i])))
          model.setParameterValueByIndex(i,1); } }catch(e){}
      return 1; };
    done.push('blinkOpen');
  } else if(eb){
    /* 兜底：改构造函数里的 blink 参数集合（拿不到 updateParameters 时至少让它不眨） */
    try{ if(eb._blinking) eb._blinking.parameterIndexes=[]; done.push('blinkDefanged'); }
    catch(e){ done.push('blinkFail'); }
  } else done.push('noBlink');
  if(im.physics&&typeof im.physics.reset==='function'){ try{ im.physics.reset(); done.push('phys'); }
    catch(e){} }
  return done.join(',');})()"""

PIN = """(function(){
  var pm=(window.__costumePinsByModel=window.__costumePinsByModel||Object.create(null));
  if(!pm[%(k)s]) pm[%(k)s]=Object.create(null);
  pm[%(k)s][%(p)s]=%(v)s; return 1;})()"""

READ = """(function(){
  var m=(window.__l2ModelRef&&window.__l2ModelRef())||null;
  if(!m||!m.internalModel) return '{"err":"NO_MODEL"}';
  var c=m.internalModel.coreModel, id=%(p)s, ix=c.getParameterIndex(id);
  if(ix<0) return JSON.stringify({err:'NO_IDX'});
  return JSON.stringify({v:+c.getParameterValueById(id).toFixed(4),
    min:+c.getParameterMinimumValue(ix), max:+c.getParameterMaximumValue(ix)});})()"""


def ev(pg, expr):
    """带进度兜底的 evaluate：返回值异常时立刻报出来，不静默吞。"""
    r = pg.ev(expr)
    if isinstance(r, str) and r.startswith('EXC'):
        raise RuntimeError('页面求值失败: %s' % r[:200])
    return r


def shot_bytes(pg):
    return base64.b64decode(pg.cmd('Page.captureScreenshot', {'format': 'png'})['data'])


def to_gray(bs):
    im = Image.open(io.BytesIO(bs)).convert('RGB')
    return np.asarray(im, dtype=np.int16)


def pix_diff(a, b):
    """返回 (变化像素占比, 变化像素数, 包围盒 (x0,y0,x1,y1) 或 None)。"""
    d = np.abs(a - b).max(axis=2) > PIX_THR
    n = int(d.sum())
    if n == 0:
        return 0.0, 0, None
    ys, xs = np.nonzero(d)
    return n / float(d.size), n, (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()))


def ext_of(box):
    if not box:
        return 0.0
    return max(abs(box[2] - box[0]), abs(box[3] - box[1]))


def row_deltas(a, b):
    """逐通道**原始**差值（不判阈）。返回 {通道: 绝对值}。"""
    d = {}
    d['op'] = abs((a[1] or 0) - (b[1] or 0))
    if a[2] and b[2]:
        d['box'] = max(abs(a[2][j] - b[2][j]) for j in range(4))
        if len(a[2]) >= 8 and len(b[2]) >= 8:
            d['cen'] = max(abs(a[2][4] - b[2][4]), abs(a[2][5] - b[2][5]))
            d['nv'] = abs(a[2][6] - b[2][6])
            d['disp'] = abs(a[2][7] - b[2][7])
    if len(a) > 4 and a[4] and b[4]:
        d['uv'] = max(abs(a[4][j] - b[4][j]) for j in range(4))
    for pos, tag in ((3, 'vis'), (5, 'tex'), (6, 'ro'), (7, 'blend')):
        if len(a) > pos:
            d[tag] = 0.0 if a[pos] == b[pos] else 1.0
    return d


def ident(snap):
    """模型身份指纹：drawable 数量 + 前 16 件的可见性/贴图/绘制序 + 首件包围盒。

    为什么必须逐条参数比对：有的参数一碰就触发装扮重建（换肤/换套装），整模 instantiate
    出新的 drawable 集合。此时「842/842 件都变了」不是参数形变，是换了个人。
    实测污染读数：`ShoseOff` 报 842/842、`Param233` 共用同一 `#828 abs=89.1257`，
    而模型顶点 X 范围只有 -448..154（总宽约 600）⇒ 89 V 的「位移」是荒谬量级，
    它其实是新 drawable 集合与旧集合错位比对的结果。像素读数（2434/6275 px）独立可信，
    但 API 侧那 842 件必须判废，否则会把整模重建当成「这个参数驱动了所有部件」。
    """
    rows = snap.get('rows') or []
    sig = [len(rows)]
    for r in rows[:16]:
        sig.append([r[3], r[5], r[6], (r[2] or [None])[0]])
    return sig


def settle(pg, pid, want, timeout=10.0):
    t0 = time.time()
    r = {}
    while time.time() - t0 < timeout:
        r = json.loads(ev(pg, READ % {'p': json.dumps(pid)}))
        if r.get('err'):
            return r
        if r.get('v') is not None and abs(r['v'] - want) < 2e-2:
            return r
        time.sleep(0.15)
    return r


def pin(pg, pid, v):
    ev(pg, PIN % {'k': json.dumps(KEY), 'p': json.dumps(pid), 'v': v})


def main():
    try:
        with urllib.request.urlopen(BASE.split('#')[0], timeout=6) as r:
            if r.status != 200:
                print('[INVALID] 服务返回', r.status)
                return 2
    except Exception as e:  # noqa: BLE001
        print('[INVALID] 服务不可达:', e)
        return 2

    tbl = json.load(open(os.path.join(ROOT, 'Output', 'gallery_v2', 'costume_params.json'),
                        encoding='utf-8'))
    rows = tbl.get(KEY) or []
    if not rows:
        print('[FAIL] costume_params.json 里没有 %s' % KEY)
        return 2
    want = ONLY or ([r['id'] for r in rows] + CONTROLS)
    rows_by = {r['id']: r for r in rows}
    todo = [p for p in want if p in rows_by]
    missing = [p for p in want if p not in rows_by]
    if missing:
        print('[WARN] 表里没有这些参数，跳过: %s' % missing)
    if not todo:
        print('[FAIL] 没有可测参数')
        return 2

    pg = Page(PORT, os.path.join(ROOT, '.diag', 'czp%d' % PORT), BASE, (1000, 800),
              gpu=True, keepalive=True)
    try:
        time.sleep(3.0)
        ev(pg, """(function(){var b=document.querySelector('#gOpt button[data-k=login]');
           if(b&&(b.classList.contains('on')||b.dataset.on==='1')) b.click(); return 1;})()""")
        time.sleep(0.9)
        print('开卡:', ev(pg, """
        (function(){var s=(window.GALLERY.ships||[]).find(function(x){
             return (x.skins||[]).some(function(k){return k.key===%s;});});
          if(!s) return 'NO_SHIP';
          var c=[...document.querySelectorAll('.card')].find(function(e){
             return (e.textContent||'').indexOf(s.name)>=0;});
          if(!c) return 'NO_CARD'; c.click(); return 'OK';})()
        """ % json.dumps(KEY)), flush=True)
        time.sleep(1.6)
        print('选肤:', ev(pg, """(function(){var d=[...document.querySelectorAll('#mSkins .skin')].find(function(e){
           return e.dataset.k===%s;}); if(!d) return 'NO_ROW'; d.click(); return 'OK';})()"""
                             % json.dumps(KEY)), flush=True)
        time.sleep(1.3)
        print('切L2D:', ev(pg, """(function(){var t=[...document.querySelectorAll('#mTabs .tab')].find(function(e){
           return e.dataset.k==='live2d';}); if(!t) return 'NO_TAB'; t.click(); return 'OK';})()"""),
              flush=True)
        for _ in range(60):
            if ev(pg, "(function(){var m=window.__l2ModelRef&&window.__l2ModelRef();"
                     " return m?1:0;})()") == 1:
                break
            time.sleep(1.0)
        print('解耦帧源:', pg.detach_frames(60), flush=True)
        time.sleep(2.2)
        ok, fps, _ = pg.frames_alive(2.0, min_fps=Page.MIN_FPS)
        print('帧源闸: %.1f fps %s' % (fps, 'OK（≥%.0f）' % Page.MIN_FPS if ok else '[FAIL] 帧源停摆'),
              flush=True)
        if not ok:
            return 2
        print('冻结姿态:', ev(pg, NEUTRALIZE), flush=True)
        time.sleep(1.2)
        pg.require_frames(1.0)

        # 全部被测参数一起钉到 lo：冻结后没人会替你复原，不钉住就会逐条污染叠加
        vals = {}
        for p in todo:
            r = json.loads(ev(pg, READ % {'p': json.dumps(p)}))
            if r.get('err'):
                print('[FAIL] 参数读不到 %s: %s' % (p, r))
                return 2
            vals[p] = r
            pin(pg, p, r['min'])
        for p in todo:
            settle(pg, p, vals[p]['min'])
        print('已把所有 %d 条参数钉到各自最小值' % len(todo), flush=True)

        base = to_gray(shot_bytes(pg))
        base_ident = ident(json.loads(ev(pg, SNAP_ALL)))
        noise_n = 0
        for k in range(4):
            time.sleep(0.7)
            cur = to_gray(shot_bytes(pg))
            ratio, n, box = pix_diff(base, cur)
            if n:
                noise_n += 1
                print('  本底第 %d 张有差异 %d px box=%s' % (k + 1, n, box), flush=True)
        if noise_n:
            print('[FAIL] 冻结没生效：4 张本底里 %d 张有差异。眨眼/呼吸/物理仍有一路在动，'
                  '任何逐参数差值都是噪声 ⇒ 本工具拒绝出结论' % noise_n, flush=True)
            return 2
        print('本底噪声: 0 px（连拍 5 张全等）', flush=True)

        names = dict((int(a), b) for a, b in json.loads(ev(pg, NAMES)))
        snap_base = json.loads(ev(pg, SNAP_ALL))
        result = {}
        print('\n%-20s %-8s %-8s %-24s %s'
              % ('参数', '变化px', '占比', '变化包围盒', 'API 级变化（相对自身尺寸）'), flush=True)
        for p in todo:
            r = vals[p]
            pin(pg, p, r['max'])
            got = settle(pg, p, r['max'])
            if got.get('err') or got.get('v') is None or abs(got['v'] - r['max']) > 2e-2:
                print('%-20s [FAIL] 值落不进去 want=%s got=%s' % (p, r['max'], got.get('v'),),
                      flush=True)
                result[p] = {'err': 'PIN_NOT_APPLIED'}
                pin(pg, p, r['min'])
                settle(pg, p, r['min'])
                continue
            time.sleep(0.35)
            cur_px = to_gray(shot_bytes(pg))
            ratio, n, box = pix_diff(base, cur_px)
            cur = json.loads(ev(pg, SNAP_ALL))
            rebuilt = ident(cur) != base_ident

            # API 级：不判阈，给出原始差值 + 按 drawable 自身尺寸归一化的相对值
            top = []
            for i in range(snap_base['n']):
                d = row_deltas(snap_base['rows'][i], cur['rows'][i])
                if not d:
                    continue
                chan = max(d, key=lambda k: d[k])
                absd = d[chan]
                if absd <= 1e-9:
                    continue
                ext = ext_of(snap_base['rows'][i][2])
                rel = (absd / ext) if (ext > 1e-6 and chan in ('box', 'cen', 'disp')) else absd
                top.append((rel, i, names.get(i, '?')[:14], ext, chan, absd))
            top.sort(reverse=True)

            result[p] = {'lo': r['min'], 'hi': r['max'], 'px': int(n),
                         'ratio': round(ratio, 6), 'box': box,
                         'rebuilt': bool(rebuilt),
                         'top': ([] if rebuilt else
                                 [[i, nm, round(ext, 4), ch, round(absd, 5), round(rel, 5)]
                                  for rel, i, nm, ext, ch, absd in top[:8]]),
                         'n_api': 0 if rebuilt else len(top)}
            if rebuilt:
                api_note = '[模型已重建：API 读数判废]'
            else:
                api_note = ('%d 件 rel=%.3f %s#%d' % (len(top), top[0][0], top[0][4], top[0][1])
                            if top else '无')
            print('%-20s %-8d %-8.4f%% %-24s %s'
                  % (p, n, ratio * 100,
                     str(box), api_note), flush=True)
            if top and not rebuilt:
                for rel, i, nm, ext, ch, absd in top[:5]:
                    print('    #%-4d %-14s ext=%-8.4f %-5s abs=%-8.4f rel=%-8.4f'
                          % (i, nm, ext, ch, absd, rel), flush=True)
            pin(pg, p, r['min'])
            settle(pg, p, r['min'])
            time.sleep(0.25)

        dst = os.path.join(OUT, '%s.json' % KEY)
        json.dump({KEY: result}, open(dst, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print('\n已写 %s' % dst, flush=True)

        # 阳性对照自检：像素判据必须能在已知有效的参数上给出**显著**差异。
        ctl = [p for p in CONTROLS if p in result and 'px' in result[p]]
        if ctl:
            mx = max(result[p]['px'] for p in ctl)
            print('阳性对照最大变化 %d px（%s）' % (mx, ', '.join(
                '%s=%d' % (p, result[p]['px']) for p in ctl)), flush=True)
            if mx == 0:
                print('[FAIL] 阳性对照也是 0 px ⇒ 像素判据无区分力，'
                      '本表里所有 0 都不许当结论（AGENTS.md 规则 5）', flush=True)
                return 2
        else:
            print('[WARN] 没跑阳性对照，本表 0 值不具判读资格', flush=True)

        zeros = [p for p in todo if result.get(p, {}).get('px') == 0]
        if zeros:
            print('\n像素级 0 变化（且阳性对照有区分力）: %s' % zeros)
            print('  含义：这些参数在本模型当前姿态下**不改变任何可见像素**。')
            print('  ⇒ 不能做热区（点了看不见变化），应降级为面板控件。')
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())
