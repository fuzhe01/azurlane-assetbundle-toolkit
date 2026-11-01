r"""分屏线拖动互动区验收：`Param373` 是否真的能拖动、线是否跟手（2026-10-30）。

需求来源：用户「idle8 有分屏线，在分屏线附近可以左右拖动控制左右分屏的占比和大小」。
接线在 `gallery_src/index.html` 的 `COSTUME_DRAG`（结构表 + 拖动反解），本脚本只验收。

判据（缺一不可，任一条红即未达标）
  ① `__splitInfo()` 能报出参数与它反解到的**遮罩件索引**（-1 = 反查失败，拖动会静默失效）；
  ② `__splitScreenX(参数, v, y)` 随 v **单调**移动（线真的跟着参数走）；
  ③ 真实拖动：线上按下 → 横拖 → 松手，参数必须变化（不是只写了 pin 没生效）；
  ④ **线跟手**：拖到某点后，反解出的线位置与指针落点误差 ≤ 40 px
     （这一条区分「能拖」和「拖起来手感对」；旧实现用固定 span，误差可达数百 px）；
  ⑤ 松手保持：1.2 s 后参数不回弹（分屏占比不是瞬时动作）；
  ⑥ 阴性对照：远离分屏线处拖动，参数必须不变。

用法
  py -3 scripts/diag/l2d_split_drag_verify.py [模型key] [参数id]
  例：py -3 scripts/diag/l2d_split_drag_verify.py ougen_8 Param373

前置
  画廊服务器在 8778（`py -3 scripts/diag/serve_gallery_8778.py`），且模型已播到含分屏线的动作
  （`ougen_8` 是 idle8；其它动作 `Param373` 恒 0，分屏线贴在画布最右，拖动带可能落在画布外）。

产物
  .diag/splitdrag/*.png  拖前/拖后帧（供复查，不进上下文）
"""
import sys, os, json, time, base64
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
sys.path.insert(0, os.path.join(ROOT, 'scripts', 'diag'))
from gallery_ui_shots import Page   # noqa: E402
import numpy as np
from PIL import Image

BASE = 'http://127.0.0.1:8778/gallery_v2/index.html#gallery_v2'
KEY = sys.argv[1] if len(sys.argv) > 1 else 'ougen_8'
PID = sys.argv[2] if len(sys.argv) > 2 else 'Param373'
OUT = os.path.join(ROOT, '.diag', 'splitdrag')
os.makedirs(OUT, exist_ok=True)

PAGE = Page(9685, os.path.join(ROOT, '.diag', 'probe_sd'), BASE, (1500, 1000), gpu=True, keepalive=True)
try:
    time.sleep(3.0)
    PAGE.ev("""(function(){var b=document.querySelector('#gOpt button[data-k=login]');
       if(b&&(b.classList.contains('on')||b.dataset.on==='1')) b.click(); return 1;})()""")
    time.sleep(0.9)
    PAGE.ev("""(function(){var s=(window.GALLERY.ships||[]).find(function(x){
         return (x.skins||[]).some(function(k){return k.key===%s;});});
      var c=[...document.querySelectorAll('.card')].find(function(e){
         return (e.textContent||'').indexOf(s.name)>=0;}); if(c) c.click(); return 1;})()""" % json.dumps(KEY))
    time.sleep(1.8)
    PAGE.ev("""(function(){var d=[...document.querySelectorAll('#mSkins .skin')].find(function(e){
       return e.dataset.k===%s;}); if(d) d.click(); return 1;})()""" % json.dumps(KEY))
    time.sleep(1.4)
    PAGE.ev("""(function(){var t=[...document.querySelectorAll('#mTabs .tab')].find(function(e){
       return e.dataset.k==='live2d';}); if(t) t.click(); return 1;})()""")
    for _ in range(90):
        if PAGE.ev("(function(){var m=window.__l2ModelRef&&window.__l2ModelRef(); return m?1:0;})()") == 1:
            break
        time.sleep(1.0)
    PAGE.detach_frames(60)
    time.sleep(2.0)

    PAGE.ev("(function(){var im=window.__l2ModelRef().internalModel;"
            "try{im.motionManager.startMotion('idle8',0,3);}catch(e){} return 1;})()")
    time.sleep(3.0)

    rect = json.loads(PAGE.ev(r"""(function(){
      var cv=document.querySelector('#l2wrap canvas');
      var r=cv.getBoundingClientRect();
      return JSON.stringify({x:r.left,y:r.top,w:r.width,h:r.height});})()"""))

    info = json.loads(PAGE.ev("(function(){ return JSON.stringify(window.__splitInfo());})()"))
    print('① __splitInfo:', info)
    assert info and info[0]['mask'] >= 0, '遮罩件反查失败（mask=-1）'

    # ② 单调性：固定屏幕 y，扫参数值看屏幕 x
    cy = rect['y'] + rect['h'] * 0.5
    splitx = lambda v, y: PAGE.ev(
        "(function(a){ var x=window.__splitScreenX(a[0],a[1],a[2]); return x===null?'null':x.toFixed(1);})"
        "([%s,%s,%s])" % (json.dumps(PID), json.dumps(v), json.dumps(y)))
    xs = []
    lo, hi = float(info[0]['lo']), float(info[0]['hi'])
    for v in [lo + (hi - lo) * i / 5.0 for i in range(6)]:
        x = splitx(round(v, 2), cy)
        xs.append((round(v, 2), x))
        print('   %s=%-6s → 屏幕 x=%s' % (PID, round(v, 2), x))
    vals = [float(x[1]) for x in xs if x[1] != 'null']
    mono = all(vals[i] > vals[i+1] for i in range(len(vals)-1))
    print('② 单调移动: %s  (x: %.0f → %.0f)' % (mono, vals[0], vals[-1]))

    def pval():
        return json.loads(PAGE.ev("(function(pn){var c=window.__l2ModelRef().internalModel.coreModel;"
                                  "return JSON.stringify({v:+c.getParameterValueById(pn).toFixed(2)});})(%s)"
                                  % json.dumps(PID)))['v']

    def drag(x0, y0, x1, y1, steps=12):
        PAGE.cmd('Input.dispatchMouseEvent', {'type': 'mousePressed', 'x': x0, 'y': y0, 'button': 'left', 'clickCount': 1})
        for i in range(1, steps + 1):
            PAGE.cmd('Input.dispatchMouseEvent', {'type': 'mouseMoved',
                'x': x0 + (x1 - x0) * i / steps, 'y': y0 + (y1 - y0) * i / steps, 'button': 'left'})
            time.sleep(0.03)
        PAGE.cmd('Input.dispatchMouseEvent', {'type': 'mouseReleased', 'x': x1, 'y': y1, 'button': 'left', 'clickCount': 1})

    # 把参数归到 lo（线在最右），再取该值下的线位置
    PAGE.ev("(function(pn){var c=window.__l2ModelRef().internalModel.coreModel;"
            "c.setParameterValueById(pn,%f); c.update(); return 1;})(%s)" % (lo, json.dumps(PID)))
    time.sleep(1.2)
    sx = float(splitx(pval(), cy))
    print('\n③ 真实拖动：起点 (%.0f,%.0f)  按下前 %s=%s  线在 x=%.0f' % (sx, cy, PID, pval(), sx))
    hit = PAGE.ev("(function(){ var r=window.__splitHitAt(%f,%f); return r?JSON.stringify(r):'null';})()" % (sx, cy))
    print('   __splitHitAt:', hit)

    v_before = pval()
    drag(sx, cy, sx - 220, cy)      # 向左拖
    time.sleep(1.0)
    v_after = pval()
    print('   拖完后 %s: %s → %s' % (PID, v_before, v_after))
    print('③ 拖动生效: %s' % (abs(v_after - v_before) > 0.5))
    # 线跟手：拖到 sx-220 后，线应落在该处附近（±40px）
    sx2 = float(splitx(v_after, cy))
    print('   线跟手: 目标 x=%.0f  实际线 x=%.0f  误差=%.0f px' % (sx - 220, sx2, abs(sx2 - (sx - 220))))

    time.sleep(1.2)
    v_hold = pval()
    print('④ 松手保持: %s (拖完 %s → 1.2s 后 %s)' % (abs(v_hold - v_after) < 0.05, v_after, v_hold))

    # ⑤ 阴性对照：远离分屏线处拖
    far_x = rect['x'] + 40
    v0 = pval()
    drag(far_x, cy, far_x - 200, cy)
    time.sleep(1.0)
    v1 = pval()
    print('⑤ 阴性对照（远离线处拖）: %s → %s  不变=%s' % (v0, v1, abs(v1 - v0) < 0.05))

    # 视觉确认：拖前拖后各一张
    def shot(tag):
        r = PAGE.cmd('Page.captureScreenshot', {'format': 'png',
            'clip': {'x': rect['x'], 'y': rect['y'], 'width': rect['w'], 'height': rect['h'], 'scale': 1}})
        p = os.path.join(OUT, tag + '.png')
        open(p, 'wb').write(base64.b64decode(r['data']))
        return p
    a = np.asarray(Image.open(shot('v_after')).convert('RGB'), dtype=np.int16)
    PAGE.ev("(function(pn){var c=window.__l2ModelRef().internalModel.coreModel;"
            "c.setParameterValueById(pn,%f); c.update();"
            "try{l2State.app.renderer.render(l2State.app.stage);}catch(e){} return 1;})(%s)" % (lo, json.dumps(PID)))
    time.sleep(0.4)
    b = np.asarray(Image.open(shot('v_lo')).convert('RGB'), dtype=np.int16)
    h = min(a.shape[0], b.shape[0]); w = min(a.shape[1], b.shape[1])
    m = np.abs(a[:h, :w] - b[:h, :w]).max(axis=2) > 12
    print('\n画面差（%s=%s vs %s）: %d px (%.2f%%)' % (PID, v_after, lo, int(m.sum()), 100.0*m.sum()/(h*w)))
finally:
    PAGE.close()
