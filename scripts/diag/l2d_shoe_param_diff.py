"""参数差分取证：把「某参数开/关」渲染成两帧再逐像素相减（2026-10-29）。

为什么需要它（取代「按区域量红像素」的取证路线）：
需求「ougen_8 左脚/左腿消失、两只红底高跟鞋只剩一只」已经用区域统计查了三轮，三轮都翻盘：
  ① 没加画布偏移 → 把画出来的脚量成「0 内容」；
  ② 补了横轴 292 漏了纵轴 45 → 结论仍带偏移；
  ③ **区域框本身取错部位**（V y −1.5..1.15 是小腿/脚踝，不是鞋）→ 读数从
     「左 0.77% / 右 12.90%」直接反转为「左 44.61% / 右 0.00%」，方向完全相反。
根因是同一个：区域统计要求调用方**先猜目标物在哪**，猜错就把「量错部位」当成「东西没渲染」。

差分不需要猜。改一个参数、冻结姿态、截两帧相减 —— 变化范围由**被测系统自己**给出：
  · 变化像素的包围盒 = 该参数的真实作用域；
  · 变化簇的个数 = 该参数作用在几处独立地方（两只鞋会给两个分离的簇，一只鞋给一个）；
  · 左右半分布 = 是单侧还是双侧（判「只渲染了一只」）；
  · 变化区红色增减 = 该参数是否真的在切「红底」。

前置条件（缺一条结论就不可信）：
  · 冻结 idle/呼吸/物理（否则全身逐帧漂移，差分会淹没目标）；
  · 冻结后先证本底漂移为 0（连截两帧差分必须 0 像素变化），否则差分器本身就是坏的；
  · 从产品自己的 pins 入口写参数（`__costumePinsByModel`），而不是直接 setParameterValueById ——
    后者会被 `loadParameters` 每帧拉回曲线值，量到的是「没变化」的假阴性。

用法
  py -3 scripts/diag/l2d_shoe_param_diff.py [模型] [参数]
  例：py -3 scripts/diag/l2d_shoe_param_diff.py ougen_8 ShoseOff

产物
  .diag/diff_<模型>_<参数>_a.png  低端态帧
  .diag/diff_<模型>_<参数>_b.png  高端态帧
  控制台打印差分统计（含阴性对照：同态连截两帧应为 0）
"""
import json
import os
import sys
import time

sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts', 'diag'))
from gallery_ui_shots import Page  # noqa: E402
import shot_regions  # noqa: E402

KEY = sys.argv[1] if len(sys.argv) > 1 else 'ougen_8'
PID = sys.argv[2] if len(sys.argv) > 2 else 'ShoseOff'
BASE = 'http://127.0.0.1:8778/gallery_v2/index.html#gallery_v2'
OUT = os.path.join(ROOT, '.diag')

CLOSE_LOGIN = """(function(){var b=document.querySelector('#gOpt button[data-k=login]');
   if(b&&(b.classList.contains('on')||b.dataset.on==='1')) b.click(); return 1;})()"""
OPEN_SHIP = """(function(){var k=%s;
  var s=(window.GALLERY.ships||[]).find(function(x){
     return (x.skins||[]).some(function(o){return o.key===k;});});
  if(!s) return 'NO_SHIP';
  var c=[...document.querySelectorAll('.card')].find(function(e){
     return (e.textContent||'').indexOf(s.name)>=0;});
  if(!c) return 'NO_CARD'; c.click(); return 'OK:'+s.name;})()"""
PICK_SKIN = """(function(){var d=[...document.querySelectorAll('#mSkins .skin')].find(function(e){
   return e.dataset.k===%s;}); if(!d) return 'NO_ROW'; d.click(); return 'OK';})()"""
TO_L2D = """(function(){var t=[...document.querySelectorAll('#mTabs .tab')].find(function(e){
   return e.dataset.k==='live2d';}); if(!t) return 'NO_TAB';
   if(t.classList.contains('dis')) return 'DIS'; t.click(); return 'OK';})()"""

NEUTRALIZE = """(function(){var m=(window.__l2ModelRef&&window.__l2ModelRef())||null; if(!m) return 'NO_MODEL';
  var im=m.internalModel, mm=im&&im.motionManager, done=[];
  if(mm&&mm.groups){ if(!mm.__idleBak) mm.__idleBak=mm.groups.idle;
    mm.groups.idle='__hz_frozen__'; done.push('idleOff'); }
  try{ if(mm){ mm.queueManager.stopAllMotions(); mm.state.reset&&mm.state.reset(); } done.push('mot'); }catch(e){}
  if(typeof im.updateNaturalMovements==='function'){
    im.updateNaturalMovements=function(){}; done.push('breath'); }
  if(im.physics&&typeof im.physics.reset==='function'){ try{ im.physics.reset(); done.push('phys'); }catch(e){} }
  return done.join(',');})()"""

# 画布在整页截图里的真实位置 —— 必须问页面，不能反推（见 shot_regions 头注释）
VIEWRECT = r"""(function(){var o={};
  try{ var cv=document.querySelector('#l2wrap canvas');
    if(cv){ var r=cv.getBoundingClientRect();
      o.canvas={left:r.left,top:r.top,width:r.width,height:r.height,
                cw:cv.width,ch:cv.height}; } }catch(e){}
  o.dpr=window.devicePixelRatio||1; return JSON.stringify(o);})()"""

# 经产品自己的 pins 入口写参数：只有它会每帧重申（stateTick），直接写 coreModel 会被
# loadParameters 拉回曲线值 —— 那会量出「参数改了但画面没变」的假阴性。
PIN = """(function(){var pm=(window.__costumePinsByModel=window.__costumePinsByModel||Object.create(null));
  if(!pm[%(k)s]) pm[%(k)s]=Object.create(null);
  pm[%(k)s][%(p)s]=%(v)s; return 1;})()"""

READ = """(function(){var m=(window.__l2ModelRef&&window.__l2ModelRef())||null;
  if(!m||!m.internalModel) return '{"err":"NO_MODEL"}';
  var c=m.internalModel.coreModel, id=%(p)s, ix=c.getParameterIndex(id);
  if(ix<0) return '{"err":"NO_IDX"}';
  return JSON.stringify({v:+c.getParameterValueById(id).toFixed(4),
    min:+c.getParameterMinimumValue(ix), max:+c.getParameterMaximumValue(ix),
    pin:(window.__costumePinsByModel||{})[%(k)s]&&(window.__costumePinsByModel||{})[%(k)s][id]});})()"""


def pin(pg, v):
    pg.ev(PIN % {'k': json.dumps(KEY), 'p': json.dumps(PID), 'v': json.dumps(v)})


def read(pg):
    r = pg.ev(READ % {'k': json.dumps(KEY), 'p': json.dumps(PID)})
    try:
        return json.loads(r)
    except Exception:
        return {'err': str(r)[:200]}


def settle(pg, want, timeout=8.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        r = read(pg)
        if isinstance(r.get('v'), float) and abs(r['v'] - want) < 2e-2:
            # 再多等两帧，让 keyform 重算 + 渲染落盘（参数到位 ≠ 画面到位）
            time.sleep(0.25)
            return r
        time.sleep(0.12)
    return read(pg)


def main():
    pg = Page(9412, os.path.join(ROOT, '.diag', 'l2foot_prof'),
              BASE, (1400, 1000), gpu=True, keepalive=True)
    rc = 0
    try:
        time.sleep(3.0)
        pg.ev(CLOSE_LOGIN)
        time.sleep(0.9)
        print('开卡:', pg.ev(OPEN_SHIP % json.dumps(KEY)))
        time.sleep(1.6)
        print('选肤:', pg.ev(PICK_SKIN % json.dumps(KEY)))
        time.sleep(1.3)
        print('切L2D:', pg.ev(TO_L2D))
        for _ in range(60):
            if pg.ev("(function(){var m=window.__l2ModelRef&&window.__l2ModelRef();"
                     " return m?1:0;})()") == 1:
                break
            time.sleep(1.0)
        print('解耦帧源:', pg.detach_frames(60))
        time.sleep(2.5)
        print('帧源闸: %.1f fps' % pg.require_frames(2.0))
        print('冻结姿态:', pg.ev(NEUTRALIZE))
        time.sleep(1.5)
        pg.require_frames(1.0)

        vr = json.loads(pg.ev(VIEWRECT))
        cv = vr.get('canvas') or {}
        left = float(cv.get('left', 0)); top = float(cv.get('top', 0))
        dpr = float(vr.get('dpr', 1))
        print('画布(整页坐标): left=%.3f top=%.3f w=%.1f h=%.1f dpr=%s'
              % (left, top, cv.get('width', 0), cv.get('height', 0), dpr))
        if not cv:
            print('[FAIL] 问不到画布位置，差分坐标不可信'); return 2

        r0 = read(pg)
        if r0.get('err'):
            print('[FAIL] 参数读不到:', r0); return 2
        lo, hi = r0['min'], r0['max']
        print('参数 %s: min=%s max=%s 默认=%s' % (PID, lo, hi, r0['v']))

        # ---- 阴性对照：同一状态连截两帧，差分必须为 0 ----
        pin(pg, lo)
        print('settle lo ->', settle(pg, lo))
        pa = os.path.join(OUT, 'diff_%s_%s_a.png' % (KEY, PID))
        pa2 = os.path.join(OUT, 'diff_%s_%s_a2.png' % (KEY, PID))
        pb = os.path.join(OUT, 'diff_%s_%s_b.png' % (KEY, PID))
        pg.shot(pa)
        time.sleep(0.6)
        pg.shot(pa2)
        base = shot_regions.diff_stats(pa, pa2, left, top, dpr=dpr)
        print('[阴性对照] 同态两帧差分: changed=%s (%.4f%%)  期望 0'
              % (base.get('changed'), base.get('changed_pct') or 0))
        if base.get('changed'):
            print('  [WARN] 同态仍在变 ⇒ 冻结没生效或渲染不稳定，下面的差分含本底噪声')

        # ---- 正片：切到另一端 ----
        pin(pg, hi)
        print('settle hi ->', settle(pg, hi))
        pg.shot(pb)

        d = shot_regions.diff_stats(pa, pb, left, top, dpr=dpr)
        if d.get('err'):
            print('[FAIL] 差分失败:', d); return 2
        print('\n=== 差分 %s: %s -> %s ===' % (PID, lo, hi))
        print('变化像素: %d / %d (%.3f%%)  阈值=%s'
              % (d['changed'], d['n'], d['changed_pct'], d['thresh']))
        print('变化包围盒(canvas):', d.get('bbox_canvas'))
        print('变化包围盒(整页):  ', d.get('page_bbox'))
        sp = d.get('split') or {}
        print('左右分布: left=%s right=%s (canvas 中线 x=%s)'
              % (sp.get('left'), sp.get('right'), sp.get('canvas_mid_x')))
        print('变化区红像素: a=%s b=%s diff=%s'
              % (d['red_delta']['a'], d['red_delta']['b'], d['red_delta']['diff']))
        print('变化簇: %d 个' % d.get('count', 0))
        for c in d.get('top', []):
            print('   n=%-6d canvas%s' % (c['n'], c['canvas_bbox']))

        if not d['changed']:
            print('\n[FAIL] 参数两端帧完全一致 ⇒ 该参数在本模型上没有渲染效果')
            print('       （也可能是写值路径错：确认 pins 被 stateTick 重申）')
            rc = 3
        else:
            # 判「只有一只鞋参与换装」：变化簇应成对、左右各一
            half = sp.get('canvas_mid_x', 0)
            nl = sum(1 for c in d['top'] if c['canvas_bbox'][2] < half)
            nr = sum(1 for c in d['top'] if c['canvas_bbox'][0] > half)
            print('\n簇分布: 完全在左半 %d 个 / 完全在右半 %d 个' % (nl, nr))
        return rc
    finally:
        try:
            pg.ev("""(function(){var pm=(window.__costumePinsByModel||{})[%s]||{};
              delete pm[%s]; return 1;})()""" % (json.dumps(KEY), json.dumps(PID)))
        except Exception:
            pass
        pg.close()


if __name__ == '__main__':
    sys.exit(main())
