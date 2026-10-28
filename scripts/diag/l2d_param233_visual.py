r"""验证 Param233 是否就是「消失的第二只鞋/另一条腿」的总开关（2026-10-28）

背景：ougen_8 的 idle 里屏幕右侧（角色自身左侧）有一整套 16 个部件恒不可见
（#405..#417 / #447 / #448 / #665）。`l2d_opacity_binding_hunt.py` 证明它们由
`Param233` 一个参数控制；本工具做**视觉层**确认：把它推到 1 之后，画面变化到底
出现在哪里、是「补上一条腿」还是「多叠一条腿」。

判据（三条都要满足才可下结论）
  1. 变化必须是**新增内容**而不是整体位移：diff 区域应当落在脚/腿那条低高度带；
  2. 变化区域在**屏幕右半**（V x>0），且与左侧鞋件的高度带一致（不是头/手）；
  3. 与 Param233=0 的对照图相比，变化像素占比应该很小（几万像素量级），
     不是整屏重绘。

用法
  py -3 scripts/diag/l2d_param233_visual.py [模型] [参数名]
"""
import json
import os
import sys
import time

sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, HERE)
from gallery_ui_shots import Page  # noqa: E402
import shot_regions as SR  # noqa: E402

KEY = sys.argv[1] if len(sys.argv) > 1 else 'ougen_8'
PARAM = sys.argv[2] if len(sys.argv) > 2 else 'Param233'
BASE = 'http://127.0.0.1:8778/gallery_v2/index.html#gallery_v2'
PORT = int(os.environ.get('AL_PORT', '9411'))
PROFILE = os.path.join(ROOT, '.diag', 'czh_prof')
OUT = os.path.join(ROOT, '.diag')

NEUTRALIZE = """(function(){var m=(window.__l2ModelRef&&window.__l2ModelRef())||null; if(!m) return 'NO_MODEL';
  var im=m.internalModel, mm=im&&im.motionManager, done=[];
  if(mm&&mm.groups){ if(!mm.__idleBak) mm.__idleBak=mm.groups.idle;
    mm.groups.idle='__hz_frozen__'; done.push('idleOff'); }
  try{ if(mm){ mm.queueManager.stopAllMotions(); mm.state.reset&&mm.state.reset(); } done.push('mot'); }catch(e){}
  if(typeof im.updateNaturalMovements==='function'){
    im.updateNaturalMovements=function(){}; done.push('breath'); }
  if(im.physics&&typeof im.physics.reset==='function'){ try{ im.physics.reset(); done.push('phys'); }
    catch(e){} }
  return done.join(',');})()"""

RECT = """(function(){var c=document.querySelector('#l2wrap canvas');
  if(!c) return 'null'; var r=c.getBoundingClientRect();
  return JSON.stringify({left:r.left, top:r.top, w:r.width, h:r.height});})()"""

SETP = """(function(){var c=window.__l2ModelRef().internalModel.coreModel;
  var i=c.getParameterIndex(%s); if(i>=c.getParameterCount()) return 'NO_PARAM';
  c.setParameterValueByIndex(i, %s); c.update();
  return JSON.stringify({idx:i, v:c.getParameterValueByIndex(i),
    min:c.getParameterMinimumValue(i), max:c.getParameterMaximumValue(i)});})()"""


def open_model(pg):
    pg.ev("""(function(){var b=document.querySelector('#gOpt button[data-k=login]');
       if(b&&b.classList.contains('on')) b.click(); return 1;})()""")
    time.sleep(0.9)
    print('开卡:', pg.ev("""
    (function(){var s=(window.GALLERY.ships||[]).find(function(x){
         return (x.skins||[]).some(function(k){return k.key===%s;});});
      var c=[...document.querySelectorAll('.card')].find(function(e){
         return (e.textContent||'').indexOf(s.name)>=0;}); c.click(); return 'OK';})()"""
                    % json.dumps(KEY)))
    time.sleep(1.6)
    pg.ev("""(function(){var d=[...document.querySelectorAll('#mSkins .skin')].find(function(e){
       return e.dataset.k===%s;}); d.click(); return 1;})()""" % json.dumps(KEY))
    time.sleep(1.3)
    pg.ev("""(function(){var t=[...document.querySelectorAll('#mTabs .tab')].find(function(e){
       return e.dataset.k==='live2d';}); t.click(); return 1;})()""")
    for _ in range(60):
        if pg.ev("(function(){var m=window.__l2ModelRef&&window.__l2ModelRef(); return m?1:0;})()") == 1:
            return True
        time.sleep(1.0)
    return False


def main():
    pg = Page(PORT, PROFILE, BASE, (1400, 1000), gpu=True, keepalive=True)
    try:
        time.sleep(3.0)
        if not open_model(pg):
            print('[FAIL] 模型没加载')
            return 2
        print('解耦帧源:', pg.detach_frames(60))
        time.sleep(2.5)
        print('帧源闸: %.1f fps' % pg.require_frames(2.0))
        print('冻结:', pg.ev(NEUTRALIZE))
        time.sleep(1.5)
        pg.require_frames(1.0)

        rect = json.loads(pg.ev(RECT))
        json.dump(rect, open(os.path.join(OUT, 'view_rect.json'), 'w'), indent=2)
        print('canvas rect =', rect)

        a = os.path.join(OUT, 'p233_off.png')
        b = os.path.join(OUT, 'p233_on.png')
        pg.shot(a)
        print('\n设定 %s=1 →' % PARAM, pg.ev(SETP % (json.dumps(PARAM), '1')))
        time.sleep(0.6)
        pg.require_frames(1.0)
        pg.shot(b)

        st = SR.diff_stats(a, b, left=rect['left'], top=rect['top'],
                           box=[0, 0, rect['w'], rect['h']])
        print('\n=== 差异统计（canvas 内）===')
        print('  变化像素 %d / 占比 %.3f%%' % (st['changed'], st['changed_pct']))
        print('  bbox(canvas) =', st['bbox'])
        print('  左右分布 =', st.get('split'))
        if st['bbox']:
            x0, y0, x1, y1 = st['bbox']
            print('  变化区 canvas 相对位置: x %.1f%%..%.1f%%  y %.1f%%..%.1f%%'
                  % (x0 / rect['w'] * 100, x1 / rect['w'] * 100,
                     y0 / rect['h'] * 100, y1 / rect['h'] * 100))
            print('  判定：变化区在 %s（中线=50%%）'
                  % ('屏幕右半' if (x0 + x1) / 2 > rect['w'] / 2 else '屏幕左半'))
            print('  判定：高度带 %%y %.1f..%.1f（脚/腿带通常 >75%%）'
                  % (y0 / rect['h'] * 100, y1 / rect['h'] * 100))

        # 同时取回 16 个件的动态标志，确认它们都打开了
        print('\n=== 部件动态标志复核 ===')
        print(pg.ev("""(function(){var c=window.__l2ModelRef().internalModel.coreModel;
          var idx=[405,406,407,408,409,410,411,412,413,414,415,416,417,447,448,665], o=[];
          for(var k=0;k<idx.length;k++){ var i=idx[k];
            o.push([i, +c.getDrawableOpacity(i).toFixed(3), c.getDrawableDynamicFlagIsVisible(i)?1:0]); }
          return JSON.stringify(o);})()"""))
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())
