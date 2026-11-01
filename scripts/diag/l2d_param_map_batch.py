r"""批量重建「参数 → 它驱动哪些 drawable」映射（替代已损坏的 map_param_to_drawables.py）。

为什么重写：`map_param_to_drawables.py` 的写法是「设参数 hi → `im.update(0, now)` → 采顶点
→ 设 lo → 再采」，**不冻结姿态、也不校验参数真的落进 coreModel**。实测 2026-10-29 重跑
`ougen_8` 对 11 条换装参数里 **10 条报「影响 0 个 drawable」**，而 `l2d_param_effect_scan.py`
早已证死 `ShoseOff` 真实驱动 5 件（183/184/460/461/615）、`Param233` 16 件。原因很直接：
`im.update()` 之前 motionManager 已经把参数写回曲线值，`setParameterValueByIndex` 那一笔
在 evaluate 期间就被下一次 motion 更新覆盖 —— 所以量到的是「什么都没变」。
**这类「0 命中」是仪器失灵，不是数据结论**（AGENTS.md 人话版规则 5）。

本工具沿用 `l2d_param_effect_scan.py` 已验证的三件套：
  ① 先 `NEUTRALIZE` 冻结 idle / motion / 呼吸 / 物理，并**断言冻结后本底漂移 = 0**
     （不为 0 就直接判红 —— 冻结没生效时逐档差值全是漂移噪声）；
  ② 参数走产品自己的 pin 出口（`__costumePinsByModel`），由 `stateApply` 每帧重申
     ⇒ 值真的落进 coreModel，且能被 `settle()` 读到；
  ③ 快照含 opacity + 顶点包围盒 + `DynamicFlagIsVisible` 三路，任一变化即算「驱动」。

用法
  py -3 scripts/diag/l2d_param_map_batch.py ougen_8            # 扫 costume_params.json 里全部参数
  py -3 scripts/diag/l2d_param_map_batch.py ougen_8 BondEyes  # 只扫指定参数

输出 `.diag/param_drawables/<模型>.batch.json`：
  {模型: {参数: {lo, hi, n, idx:[...], why:{idx: 'op|box|vis'}}}}
退出码：0 全参数有结论 / 2 环境或仪器红 / 3 有参数报「驱动 0 件」（需人工判读）
"""
import json
import os
import sys

# 仪器自保：本工具曾在「基线已取」之后单核空转 4 分钟以上（CPU 从 730s 涨到 757s，
# 日志一行不动），既不是等画面也不是超时——这种静默空转只能靠栈把它揪出来。
# 超时点设在 20 分钟（全量 12 条参数 × 2 态快照的实测上界约 12 分钟），到点直接
# dump 全部线程栈并退出，不许无限期挂着。
import faulthandler  # noqa: E402
import os as _os  # noqa: E402
faulthandler.dump_traceback_later(int(_os.environ.get('HZ_WATCHDOG', '1200')), exit=True)
import time
import urllib.request

sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts', 'diag'))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

from gallery_ui_shots import Page  # noqa: E402

KEY = sys.argv[1] if len(sys.argv) > 1 else 'ougen_8'
_args = sys.argv[2:]
USE_UV = '--uv' in _args
ONLY = [a for a in _args if not a.startswith('--')] or None
PORT = 9412
BASE = 'http://127.0.0.1:8778/gallery_v2/index.html#gallery_v2'
OUT = os.path.join(ROOT, '.diag', 'param_drawables')
os.makedirs(OUT, exist_ok=True)

SNAP_ALL = r"""
(function(){
  var t0=(window.performance&&performance.now)?performance.now():Date.now();
  var m=(window.__l2ModelRef&&window.__l2ModelRef())||null;
  if(!m||!m.internalModel) return '{"err":"NO_MODEL"}';
  var c=m.internalModel.coreModel, n=c.getDrawableCount(), out=[];
  var wantUV=%(uv)s;
  for(var i=0;i<n;i++){
    var op=0, geo=null, vis=-1, mc=null, sc=null, uv=null, mk=null, cu=-1, inv=-1;
    try{ op=+c.getDrawableOpacity(i); }catch(e){}
    try{ vis=c.getDrawableDynamicFlagIsVisible(i)?1:0; }catch(e){}
    // 颜色通道：眼睛类参数可能只改**着色**（换色/发光），只有 multiplyColor / screenColor 会变。
    // 不采这两路就会把「换色」误判成「参数无效果」= AGENTS.md 禁止的仪器型零命中。
    try{ var q=c.getDrawableMultiplyColor(i);
      if(q) mc=[+q[0].toFixed(3),+q[1].toFixed(3),+q[2].toFixed(3),+q[3].toFixed(3)]; }catch(e){}
    try{ var s=c.getDrawableScreenColor(i);
      if(s) sc=[+s[0].toFixed(3),+s[1].toFixed(3),+s[2].toFixed(3),+s[3].toFixed(3)]; }catch(e){}
    try{ var v=c.getDrawableVertexPositions(i);
      if(v&&v.length>=2){ var x0=1e9,y0=1e9,x1=-1e9,y1=-1e9,sx=0,sy=0,nv=v.length/2;
        for(var k=0;k+1<v.length;k+=2){
          if(v[k]<x0)x0=v[k]; if(v[k]>x1)x1=v[k];
          if(v[k+1]<y0)y0=v[k+1]; if(v[k+1]>y1)y1=v[k+1];
          sx+=v[k]; sy+=v[k+1]; }
        var cx=sx/nv, cy=sy/nv, sp=0;
        for(var k2=0;k2+1<v.length;k2+=2){ sp+=Math.abs(v[k2]-cx)+Math.abs(v[k2+1]-cy); }
        // 只比包围盒会漏掉「顶点在盒内重新排布」这类变化（虹膜换图样是典型：
        // 包围盒一模一样，但顶点位置换了 / 顶点数变了 ⇒ 画面完全不同）。
        // 补三路：质心(cx,cy) 抓整体位移、顶点数 nv 抓 keyform 切换、
        // 平均离散度 sp/nv 抓「形心不动但内部变形」。三者都归一化，跨分辨率可比。
        geo=[+x0.toFixed(3),+y0.toFixed(3),+x1.toFixed(3),+y1.toFixed(3),
             +cx.toFixed(3),+cy.toFixed(3),nv,+(sp/nv).toFixed(3)]; } }catch(e){}
    // UV 通道：眼睛换图样最省事的实现是在**同一张图集页内把 UV 挪到另一块**（
    // 这样顶点/包围盒/着色全不动，但画面换了）。实测 ougen_8 的虹膜换色就是这一类，
    // 少了这一路，参数会被报成「驱动 0 件」。
    try{ var t=c.getDrawableVertexUvs(i);
      if(t&&t.length>=2){ var su=0,sv=0,du=0,dv=0,m2=t.length/2;
        for(var u=0;u+1<t.length;u+=2){ su+=t[u]; sv+=t[u+1]; }
        var mu=su/m2, mv=sv/m2;
        for(var u2=0;u2+1<t.length;u2+=2){ du+=Math.abs(t[u2]-mu); dv+=Math.abs(t[u2+1]-mv); }
        uv=[+su.toFixed(3),+sv.toFixed(3),m2,+(du/m2).toFixed(4),+(dv/m2).toFixed(4)]; } }catch(e){}
    // 蒙版成员 / 反转蒙版 / 剔除：这三条也属于「参数改了但画面看似没变」的通道
    try{ var ms=c.getDrawableMasks(i), mc2=c.getDrawableMaskCounts(i);
      if(ms&&mc2>0){ var h=0; for(var z=0;z<mc2;z++) h+=(ms[z]+1)*(z+1); mk=[mc2,h]; } }catch(e){}
    try{ inv=c.getDrawableInvertedMaskBit(i)?1:0; }catch(e){}
    try{ cu=c.getDrawableCulling(i)?1:0; }catch(e){}
    var tex=-1, ro=0, bl=0;
    try{ tex=c.getDrawableTextureIndices(i); }catch(e){}
    try{ ro=c.getDrawableRenderOrders(i); }catch(e){}
    try{ bl=c.getDrawableBlendMode(i); }catch(e){}
    out.push([i,+op.toFixed(4),geo,vis,mc,sc,uv,mk,inv,cu,tex,ro,bl]); }
  return JSON.stringify({n:n, rows:out, ms:Math.round(((window.performance&&performance.now)?performance.now():Date.now())-t0),
    hasMC: out.some(function(r){return r[4]!==null;}),
    hasSC: out.some(function(r){return r[5]!==null;}),
    hasUV: out.some(function(r){return r[6]!==null;})});
})()
"""


def snap(pg, uv=False):
    """取一次快照。uv 通道默认关（842 件 × 数千顶点会拖到分钟级，见 SNAP_ALL 内注释）。"""
    r = json.loads(pg.ev(SNAP_ALL % {'uv': 'true' if uv else 'false'}))
    return r

NAMES = """(function(){
  var m=(window.__l2ModelRef&&window.__l2ModelRef())||null;
  if(!m||!m.internalModel) return '[]';
  var c=m.internalModel.coreModel, n=c.getDrawableCount(), out=[];
  for(var i=0;i<n;i++){ var nm='';
    try{ nm=c.getDrawableId(i); }catch(e){}
    out.push([i,nm]); }
  return JSON.stringify(out);})()"""

NEUTRALIZE = """(function(){var m=(window.__l2ModelRef&&window.__l2ModelRef())||null; if(!m) return 'NO_MODEL';
  var im=m.internalModel, mm=im&&im.motionManager, done=[];
  if(mm&&mm.groups){ if(!mm.__idleBak) mm.__idleBak=mm.groups.idle;
    mm.groups.idle='__hz_frozen__'; done.push('idleOff'); }
  try{ if(mm){ mm.queueManager.stopAllMotions(); mm.state.reset&&mm.state.reset(); } done.push('mot'); }catch(e){}
  if(typeof im.updateNaturalMovements==='function'){
    im.updateNaturalMovements=function(){}; done.push('breath'); }
  /* 眨眼必须单独冻（2026-10-29 实测的第九条仪器 bug）：
     InternalModel.update() 里是 `if(!motionUpdated) this.eyeBlink.updateParameters(model, dt)`，
     冻住 idle/motion 恰恰让 motionUpdated=false ⇒ **眨眼反而开始跑**。它会随机把
     ParamEyeLOpen/ROpen 拍成 0..1，眼睛区域整块重绘。实测后果：像素探针把
     「采样撞上闭眼」的 348 px / 103 px 差异记成 BondEyes / ParamEyeSmile 的效果，
     而这两次差异的包围盒 (638,265)-(689,280) 与眨眼本身的包围盒 (639,266)-(689,282)
     几乎重合 —— 典型的假阳性。
     正确名字是 `updateParameters`（`update` 在这个类上不存在，改它等于没改）。
     这里不是停掉眨眼，而是**每次调用都把眼睛开到 1**：空函数会让眼睛停在上一次
     眨到的中间值，整场测量都在半闭眼上做，读数同样作废。 */
  var eb=im.eyeBlink;
  if(eb&&typeof eb.updateParameters==='function'){
    if(!eb.__hzBak) eb.__hzBak=eb.updateParameters;
    eb.updateParameters=function(model){
      try{ var ids=(model&&model.parameters&&model.parameters.ids)||[];
        for(var q=0;q<ids.length;q++){
          if(/^ParamEye[LR]Open$/.test(String(ids[q]))) model.setParameterValueByIndex(q,1); } }
      catch(e){}
      return 1; };
    done.push('blinkOpen');
  } else if(eb){
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

UNPIN = """(function(){var pm=(window.__costumePinsByModel||{})[%(k)s]||{};
  delete pm[%(k)s]; return 1;})()"""

READ = """(function(){
  var m=(window.__l2ModelRef&&window.__l2ModelRef())||null;
  if(!m||!m.internalModel) return '{"err":"NO_MODEL"}';
  var c=m.internalModel.coreModel, id=%(p)s, ix=c.getParameterIndex(id);
  if(ix<0) return JSON.stringify({err:'NO_IDX'});
  return JSON.stringify({v:+c.getParameterValueById(id).toFixed(4),
    min:+c.getParameterMinimumValue(ix), max:+c.getParameterMaximumValue(ix)});})()"""


def settle(pg, pid, want, timeout=10.0):
    """等参数真的落进 coreModel。读不到就返回最后读数，由调用方判红。"""
    t0 = time.time()
    r = {}
    while time.time() - t0 < timeout:
        r = json.loads(pg.ev(READ % {'p': json.dumps(pid)}))
        if r.get('err'):
            return r
        if r.get('v') is not None and abs(r['v'] - want) < 2e-2:
            return r
        time.sleep(0.15)
    return r


def drift_check(pg, rounds=4, gap=0.5, uv=False):
    """冻结后本底漂移：同一份快照连采 rounds 次，逐 drawable 比。返回 (漂移数, 总数)。"""
    snaps = []
    for _ in range(rounds):
        snaps.append(snap(pg, uv))
        time.sleep(gap)
    if snaps[0].get('err'):
        return -1, 0
    n = snaps[0]['n']
    bad = 0
    for i in range(n):
        for k in range(1, rounds):
            if row_diff(snaps[0]['rows'][i], snaps[k]['rows'][i]):
                bad += 1
                break
    return bad, n


def _ext(row):
    """drawable 自身尺寸（包围盒长边）。用来把绝对阈值换成相对阈值。"""
    box = row[2]
    if not box:
        return 0.0
    return max(abs(box[2] - box[0]), abs(box[3] - box[1]))


def _thr(row, rel=0.005, floor=1e-4):
    """相对阈值：取自身尺寸的 rel 倍，但兜底不低于 floor。

    为什么必须相对：旧版把 box/cen/disp 的阈值写死成 0.5（绝对 V 空间）。整模量级约
    600 单位（ougen_8 顶点范围 -448..153），0.5 是它的 0.08%；但眼睛 ArtMesh 只有
    0.14 单位宽，0.5 是它的 **3.5 倍** ⇒ 任何小于半个单位的形变都被判「没变化」。
    实测 `ParamEyeSmile` 驱动 15 件、最高相对变化 10.6%（屏幕上 89 px），
    在绝对阈值下就是 0 件 —— 仪器把真效果吃掉了。0.5% 相对阈值能抓住它，
    而冻结漂移实测为 0/842，留有余量。
    """
    e = _ext(row)
    return max(floor, e * rel) if e > 1e-6 else max(floor, 1e-3)


def row_diff(a, b):
    """单行两态比较，返回变化通道列表。

    通道：op=透明度 / box=包围盒 / cen=质心 / cnt=顶点数(keyform 切换) / disp=顶点离散度 /
    uv=贴图坐标(图集内换块) / vis=可见标志 / mc=multiplyColor / sc=screenColor /
    mask=蒙版成员 / inv=反转蒙版 / cull=剔除 / tex=贴图页 / ro=绘制序 / blend=混合模式。

    为什么这么多路：Live2D 里「参数有效果」可以被藏在任意一路。本项目实测过的漏判——
    只比 opacity+包围盒+可见性时，虹膜换图样（UV 变、几何全不动）与换色（mc/sc 变）
    都会被报成「驱动 0 件」。判据必须覆盖所有能变的东西，否则 0 是仪器造成的。
    """
    why = []
    if abs((a[1] or 0) - (b[1] or 0)) > 0.02:
        why.append('op')
    if a[2] and b[2]:
        t = _thr(a)
        if max(abs(a[2][j] - b[2][j]) for j in range(4)) > t:
            why.append('box')
        if len(a[2]) >= 8 and len(b[2]) >= 8:
            if abs(a[2][4] - b[2][4]) > t or abs(a[2][5] - b[2][5]) > t:
                why.append('cen')
            if a[2][6] != b[2][6]:
                why.append('cnt')
            if abs(a[2][7] - b[2][7]) > t:
                why.append('disp')
    if len(a) > 3 and a[3] != b[3]:
        why.append('vis')
    for pos, tag in ((4, 'mc'), (5, 'sc')):
        if len(a) > pos and len(b) > pos and a[pos] and b[pos]:
            if max(abs(a[pos][j] - b[pos][j]) for j in range(4)) > 0.01:
                why.append(tag)
    if len(a) > 6 and len(b) > 6 and a[6] and b[6]:
        if max(abs(a[6][j] - b[6][j]) for j in range(5)) > 2e-3:
            why.append('uv')
    if len(a) > 7 and a[7] != b[7]:
        why.append('mask')
    for pos, tag in ((8, 'inv'), (9, 'cull'), (10, 'tex'), (11, 'ro'), (12, 'blend')):
        if len(a) > pos and a[pos] != b[pos]:
            why.append(tag)
    return why


#: 「语义通道」—— 真正说明「参数改变了这件 drawable 的渲染语义」的证据。
#   box/cen/disp 只是几何被顺带牵动（典型：交叉淡化的对侧件被推了几个像素），
#   ro 更是整表平移的结果。用它们做**参考簇**会把簇本身撑大。
SEMANTIC_CH = ('op', 'vis', 'uv', 'mc', 'sc', 'cnt', 'mask', 'inv', 'cull', 'tex', 'blend')


def prune(idx, why, geo, margin_rel=0.25, area_rel=4.0, min_side=0.05):
    """几何聚类收窄：剔掉「退化 / 远离簇 / 超尺寸」的件，返回 (keep, drop)。

    为什么必须有这一步（2026-10-29 实测）：映射里混进异常件后，前端 `buildCosGeo()`
    把这些件的顶点并集当成热区盒 ⇒ 盒被撑大 20~70 倍。可达率工具的 V 空间网格是
    `step = span/target`（span = 全部热区盒并集），span 从 21.68 变 252 ⇒ step 从
    0.1204 变 1.4001，采样点 15385→2172。于是 `own` 从千级掉到个位数、
    `box_hash` 变、`rate_v` 全线塌 —— **看起来像热区变小了，其实是分母口径变了**。
    实例：`ShoseOff` 里 `#828` 质心 x≈-240.8（整模顶点范围仅 -448..154，鞋在
    x≈-10.8..-0.4）、`#612/#620/#628` 质心 x≈8.2（鞋的**右侧**）、`#757` 盒是一点；
    `Stock1` 里 `#591 ArtMesh813` 盒 13.84×13.98 而参考簇并集仅约 33。

    ⚠️ 不能只按通道剔：`ShoseOff` 的 `194/195/466/468/840/841` 有的只有
    `op|box|cen|disp|ro`（无 vis），却是真鞋件（交叉淡化的对侧，vis=1/op=0）。
    所以主判据是**几何聚类**，通道只用来挑出「参考簇」（语义件各占一处的并集）。

    geo: {idx: [x0,y0,x1,y1,cx,cy]}（冻结 lo 态下该 drawable 的顶点包围盒与质心）
    """
    idx = sorted(idx)
    if not idx:
        return [], {}
    ref = [i for i in idx if set(why.get(i, '').split('|')) & set(SEMANTIC_CH)] or idx
    box = [geo[i] for i in ref if i in geo]
    if not box:
        # 没有几何就拿不出聚类判据 —— 退化为原样返回，并在 drop 里标出原因，
        # 免得「静默全留」被当成「已收窄」。
        return idx, {'_no_geo': 'GEO_MISSING'}
    ux0, uy0 = min(b[0] for b in box), min(b[1] for b in box)
    ux1, uy1 = max(b[2] for b in box), max(b[3] for b in box)
    w, h = ux1 - ux0, uy1 - uy0
    m = margin_rel * max(w, h)
    ref_area = max(w, 1e-6) * max(h, 1e-6)
    keep, drop = [], {}
    for i in idx:
        g = geo.get(i)
        if not g:
            drop[i] = 'GEO_MISSING'
            continue
        x0, y0, x1, y1, cx, cy = g[:6]
        dw, dh = x1 - x0, y1 - y0
        if dw < min_side and dh < min_side:
            drop[i] = 'degenerate'
        elif not (ux0 - m <= cx <= ux1 + m and uy0 - m <= cy <= uy1 + m):
            drop[i] = 'outside'
        elif dw * dh > area_rel * ref_area:
            drop[i] = 'oversize'
        else:
            keep.append(i)
    return keep, drop


def ident(snap):
    """模型身份指纹：drawable 数量 + 前 16 件的可见性/贴图/绘制序 + 首件包围盒左边界。

    为什么需要：有的参数一碰就触发装扮重建（整模 instantiate 出新的 drawable 集合），
    这时「842/842 件全变」不是参数形变，是换了个人。实测 `ShoseOff` 报 842/842、
    且与 `Param233` 共享同一件 `#828 abs=89.1257` —— 而模型顶点 X 范围只有 -448..154
    （总宽约 600），89 V 的「位移」是荒谬量级。这类读数必须判废，否则会把
    「整模重建」当成「这条参数驱动了所有部件」，并让下一条参数继承污染基线。
    """
    rows = snap.get('rows') or []
    sig = [len(rows)]
    for r in rows[:16]:
        sig.append([r[3], r[5], r[6], (r[2] or [None])[0]])
    return sig


def diff_rows(base, cur):
    """两态快照逐 drawable 比，返回 {idx: 'op|box|vis|mc|sc'}。

    颜色两路必须在内：眼睛类参数只改着色（multiplyColor / screenColor），
    少了它们就会把真实的换色效果报成「0 件驱动」。

    **只有 ro（绘制序）变化的行要剔除**（2026-10-29 实测的第十条仪器 bug）：
    `getDrawableRenderOrders` 不是 drawable 的属性，是渲染器每帧按可见性重排出来的
    结果。任何一件被隐藏/显示，整表绘序号都会平移，于是**每一件**都报「变了」。
    实测 `ShoseOff` 报 842/842，其中 822 件的变化通道**只有 ro**；剔掉后真驱动 20 件。
    真正的层序翻转（谁压谁变了）不会单独出现 —— 被翻动的那两件必然伴随 vis/op 变化，
    所以 ro 保留为辅助通道，只是「仅 ro」不算证据。
    """
    out = {}
    for i in range(base['n']):
        why = row_diff(base['rows'][i], cur['rows'][i])
        if why and why != ['ro']:
            out[i] = '|'.join(why)
    return out


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
    if ONLY:
        rows = [r for r in rows if r['id'] in ONLY]
        if not rows:
            print('[FAIL] 指定的参数不在表里:', ONLY)
            return 2

    pg = Page(PORT, os.path.join(ROOT, '.diag', 'czm%d' % PORT),
              BASE, (1400, 1000), gpu=True, keepalive=True)
    try:
        time.sleep(3.0)
        pg.ev("""(function(){var b=document.querySelector('#gOpt button[data-k=login]');
           if(b&&(b.classList.contains('on')||b.dataset.on==='1')) b.click(); return 1;})()""")
        time.sleep(0.9)
        print('开卡:', pg.ev("""
        (function(){var s=(window.GALLERY.ships||[]).find(function(x){
             return (x.skins||[]).some(function(k){return k.key===%s;});});
          if(!s) return 'NO_SHIP';
          var c=[...document.querySelectorAll('.card')].find(function(e){
             return (e.textContent||'').indexOf(s.name)>=0;});
          if(!c) return 'NO_CARD'; c.click(); return 'OK:'+s.name;})()
        """ % json.dumps(KEY)))
        time.sleep(1.6)
        print('选肤:', pg.ev("""(function(){var d=[...document.querySelectorAll('#mSkins .skin')].find(function(e){
           return e.dataset.k===%s;}); if(!d) return 'NO_ROW'; d.click(); return 'OK';})()"""
                             % json.dumps(KEY)))
        time.sleep(1.3)
        print('切L2D:', pg.ev("""(function(){var t=[...document.querySelectorAll('#mTabs .tab')].find(function(e){
           return e.dataset.k==='live2d';}); if(!t) return 'NO_TAB';
           if(t.classList.contains('dis')) return 'DIS'; t.click(); return 'OK';})()"""))
        for _ in range(60):
            if pg.ev("(function(){var m=window.__l2ModelRef&&window.__l2ModelRef();"
                     " return m?1:0;})()") == 1:
                break
            time.sleep(1.0)
        print('解耦帧源:', pg.detach_frames(60))
        time.sleep(2.5)
        # 闸门只判「帧源在不在动」，不判「快不快」：解耦推帧下 1400x1000 Live2D 单帧成本
        # 20–30 ms ⇒ 43 fps 是硬件上限，不是停摆（拿 45/55 判会红在硬件成本上）。
        ok, fps, _ = pg.frames_alive(2.0, min_fps=Page.MIN_FPS)
        print('帧源闸: %.1f fps %s' % (fps, 'OK（≥%.0f）' % Page.MIN_FPS if ok else '[FAIL] 帧源停摆'))
        if not ok:
            return 2
        print('冻结姿态:', pg.ev(NEUTRALIZE))
        time.sleep(1.5)
        pg.require_frames(1.0)

        bad, nd = drift_check(pg, uv=USE_UV)
        print('冻结后本底漂移: %d / %d 个 drawable 仍在变' % (bad, nd))
        if bad != 0:
            print('[FAIL] 冻结没生效，逐档差值全是漂移噪声 ⇒ 本工具拒绝出结论')
            return 2

        names = dict((int(a), b) for a, b in json.loads(pg.ev(NAMES)))

        # ⚠️ 必须先把**全部**被测参数一起钉到 lo 再开始测（2026-10-29 实测的仪器 bug）：
        # 姿态已冻结，delete pin 之后**没有任何人会把它写回去** ⇒ 参数永久停在 hi，
        # 下一条参数的快照就带着上一条的残留，读数逐条累加（实测 14→25→26→26→30→42→46→57→58，
        # 乍看像「每条都驱动很多件」，其实是污染叠加）。钉住 lo 就等于给中性态一个出口。
        for it in rows:
            pg.ev(PIN % {'k': json.dumps(KEY), 'p': json.dumps(it['id']), 'v': it['lo']})
        print('已把 %d 条参数全部钉 lo: %s' % (len(rows), [r['id'] for r in rows]), flush=True)
        print('取基线快照…', flush=True)
        base = None
        base_ident = None
        n_rebuilt = 0
        result = {}
        base = None
        base_ident = None
        for it in rows:
            pid = it['id']
            lo = it['lo']
            print('  → 测 %s (lo=%.3f)…' % (pid, lo), flush=True)
            # ★ 每条参数都重取一次基线（2026-10-29 实测的第十一条仪器 bug）：
            # 全 12 条钉 lo 只能保证「参数本身回到 lo」，不能保证「画面回到基态」。
            # 冻结姿态下没人复原，前一条的残留会把下一条读数带跑。实测铁证：
            #   NeckMoney 单独测 = 1 件，全量跑 = 14 件，而且 14 件里 10 件与 Param233
            #   完全相同（194,195,466,467,468,469,612,620,628,757,828,840,841）——
            #   那不是 NeckMoney 的效果，是 Param233 的残留。
            # 重取基线后，残留**同时出现在基线和 hi 态里**，逐 drawable 相减自动消掉。
            # 代价是每条多一次全量快照（842 件，含 UV 实测约 4–6 s）。
            r = settle(pg, pid, lo)
            if r.get('err'):
                print('[FAIL] 参数读不到 %s: %s' % (pid, r))
                return 2
            pg.require_frames(1.0)
            base = snap(pg, USE_UV)
            base_ident = ident(base)
            if base.get('err'):
                print('[FAIL] 基线快照失败')
                return 2
            if it is rows[0]:
                print('基线已取（%d 个 drawable，每条参数前都重取）' % base['n'])
                mc_ok = bool(base.get('hasMC'))
                sc_ok = bool(base.get('hasSC'))
                print('颜色/UV 通道可用性: multiplyColor=%s screenColor=%s uv=%s'
                      % ('OK' if mc_ok else 'NO', 'OK' if sc_ok else 'NO',
                         'OK' if base.get('hasUV') else 'NO'))
            # 每条的运行时值域都要重读：表的 lo/hi 是导出时的快照，个别模型会变
            rr = json.loads(pg.ev(READ % {'p': json.dumps(pid)}))
            if rr.get('err'):
                print('%-16s %s' % (pid, rr['err']))
                result[pid] = {'err': rr['err']}
                continue
            lo2, hi2 = rr['min'], rr['max']
            pg.ev(PIN % {'k': json.dumps(KEY), 'p': json.dumps(pid), 'v': hi2})
            got = settle(pg, pid, hi2)
            if got.get('err') or got.get('v') is None or abs(got['v'] - hi2) > 2e-2:
                print('%-16s [FAIL] 值落不进去 want=%s got=%s' % (pid, hi2, got.get('v')))
                result[pid] = {'err': 'PIN_NOT_APPLIED', 'want': hi2, 'got': got.get('v')}
                pg.ev(UNPIN % {'k': json.dumps(KEY), 'p': json.dumps(pid)})
                continue
            # ★ 值落进去 ≠ 几何已重算（第十二条仪器 bug）：`settle` 轮询的是
            # `getParameterValueById` 的**读回值**，那是本帧写进去的参数，而 drawable
            # 顶点/opacity 要等 `core.update()` 才重算。刚 settle 完立刻快照，
            # 拿到的可能是**上一帧**的几何 —— 与 hi 态无关 ⇒ 真效果被读成 0 件。
            # 强制等新的一帧渲染出来再取。
            pg.require_frames(1.0)
            cur = snap(pg, USE_UV)
            if ident(cur) != base_ident:
                # 模型被这条参数重建了（换肤/换套装）：API 侧 842/842 读数判废，
                # 且后续参数不能继续拿旧基线比 —— 先复位到 lo 再把新集合当基线。
                print('%-16s [MODEL_REBUILT] 该参数触发整模重建，API 读数判废（需像素侧判读）'
                      % pid)
                result[pid] = {'lo': lo2, 'hi': hi2, 'rebuilt': True,
                               'n_old': base['n'], 'n_new': cur['n']}
                pg.ev(UNPIN % {'k': json.dumps(KEY), 'p': json.dumps(pid)})
                pg.ev(PIN % {'k': json.dumps(KEY), 'p': json.dumps(pid), 'v': lo2})
                settle(pg, pid, lo2)
                n_rebuilt += 1
                continue
            d = diff_rows(base, cur)
            # 收窄用**本条参数自己的 lo 基线**几何（每条参数前都重取，见上方残留注释）
            geo_lo = dict((r[0], r[2]) for r in base['rows'] if r[2])
            keep, drop = prune(sorted(d), d, geo_lo)
            dropped = dict((str(k), v) for k, v in drop.items() if not isinstance(k, str))
            result[pid] = {'lo': lo2, 'hi': hi2, 'n': len(d),
                           'idx': sorted(d), 'why': {str(k): v for k, v in d.items()},
                           'n_pruned': len(keep), 'pruned': keep, 'dropped': dropped}
            print('%-16s %-8s hi=%+.2f 驱动 %-3d 件（收窄后 %d）  %s'
                  % (pid, it.get('label', ''), hi2, len(d), len(keep),
                     ' '.join('#%d%s' % (i, names.get(i, '?')) for i in sorted(d)[:10])))
            if dropped:
                print('%-16s 剔除 %d 件: %s' % ('', len(dropped),
                      ', '.join('%s(%s %s)' % (k, names.get(int(k), '?'), v)
                                for k, v in dropped.items())))
            pg.ev(UNPIN % {'k': json.dumps(KEY), 'p': json.dumps(pid)})
            # 回落到 lo 要显式写回：冻结姿态下没人会替你复原（见上方基线注释）
            pg.ev(PIN % {'k': json.dumps(KEY), 'p': json.dumps(pid), 'v': lo2})
            settle(pg, pid, lo2)

        # 样本运行时不许覆盖全量产物（`ONLY` 只测几条，覆盖会让 12 条的权威映射蒸发）
        dst = os.path.join(OUT, '%s%s.batch.json' % (KEY, '' if not ONLY else '.only'))
        json.dump({KEY: result}, open(dst, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print('\n已写 %s' % dst)

        zero = [p for p, v in result.items() if v.get('n') == 0]
        err = [p for p, v in result.items() if 'err' in v]
        print('\n有映射 %d / 报 0 件 %d / 整模重建 %d / 读数失败 %d（共 %d 条）'
              % (len(result) - len(zero) - len(err) - n_rebuilt, len(zero), n_rebuilt,
                 len(err), len(result)))
        if n_rebuilt:
            print('  [需判读] 触发整模重建的参数（API 读数判废，只能靠像素侧）: %s'
                  % [p for p, v in result.items() if v.get('rebuilt')])
        if zero:
            print('  [需判读] 驱动 0 件的参数: %s' % zero)
            print('  注意：这里的 0 是**仪器跑通了之后**的 0（冻结漂移已断言为 0、'
                  '参数已读到 hi），与旧工具那种「参数根本没写进去」的 0 不同；')
            print('  若某参数确实 0 件，说明它在本模型上不可见 ⇒ 应降级为面板控件而非热区。')
        if err:
            print('  [FAIL] 读数失败: %s' % err)
            return 2
        return 3 if zero else 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())
