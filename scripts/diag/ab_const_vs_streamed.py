"""决定性 A/B：把 ougen_8 的 motion 退回「补 ConstantClip 之前」的版本，看鞋是否出现。

用户坚持：旧画廊能看到红底高跟鞋，新画廊看不到，且点击高跟鞋位置能触发脱鞋动画。
我此前的仪表（drawable opacity / 参数值 / 像素差）都显示两画廊等价，
但**仪表测不到不等于不存在**。所以改用最直接的实验：

  A 组 = 当前产物（EMIT_CONST，23326 条曲线）
  B 组 = 上一轮备份的旧产物（仅有 streamed，4487 条曲线，备份在 Output/_bak_motion_ougen_8）

交替换入 → 同一流程截图 → 目视对比「鞋在不在」。
若 B 组能看到鞋而 A 组看不到 ⇒ 是本轮补全引入的，立刻回退。

用法: py -3 scripts/diag/ab_const_vs_streamed.py ougen_8
"""
import json
import os
import shutil
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts', 'diag'))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

import paths as P  # noqa: E402
import gallery_ui_shots as GU  # noqa: E402
GU.CHROME = P.CHROME
from gallery_ui_shots import Page  # noqa: E402
from PIL import Image, ImageStat, ImageFilter  # noqa: E402

KEY = sys.argv[1] if len(sys.argv) > 1 else 'ougen_8'
PORT = 9410
URL = 'http://127.0.0.1:8778/gallery_v2/index.html'
OUT = os.path.join(ROOT, '.diag', 'const_vs_streamed')
os.makedirs(OUT, exist_ok=True)
TARGET = os.path.join(ROOT, 'Output', 'Live2D', KEY, 'motion')
BAK = os.path.join(ROOT, 'Output', '_bak_motion_%s' % KEY)


def switch_to(src, label):
    """把 src 的动作文件换入正式目录。"""
    if not os.path.isdir(src):
        print('[FAIL] 源目录不存在: %s' % src); return False
    for f in os.listdir(src):
        if f.endswith('.motion3.json'):
            shutil.copy2(os.path.join(src, f), os.path.join(TARGET, f))
    files = [f for f in os.listdir(TARGET) if f.endswith('.motion3.json')]
    tot = 0
    for f in files:
        d = json.load(open(os.path.join(TARGET, f), encoding='utf-8'))
        tot += len(d.get('Curves', []))
    print('  [%s] 换入完成，曲线总数 %d' % (label, tot))
    return True


def red_px(path):
    im = Image.open(path).convert('RGB')
    w, h = im.size
    im = im.crop((int(w * .42), int(h * .10), int(w * .99), int(h * .92)))
    px = im.load(); W, H = im.size; n = 0
    for y in range(0, H, 2):
        for x in range(0, W, 2):
            r, g, b = px[x, y]
            if r > 110 and r - g > 60 and r - b > 60:
                n += 1
    return n


def shoot(tag):
    pg = Page(PORT, os.path.join(ROOT, '.diag', 'chrome_cvs'), URL, (1400, 1000))
    try:
        pg.ev("""(function(){var b=document.querySelector('#gOpt button[data-k=login]');
           if(b&&(b.classList.contains('on')||b.dataset.on==='1')) b.click(); return 1;})()""")
        time.sleep(0.8)
        pg.ev("""
        (function(){var s=(window.GALLERY.ships||[]).find(function(x){
             return (x.skins||[]).some(function(k){return k.key===%s;});});
          var c=[...document.querySelectorAll('.card')].find(function(e){
             return (e.textContent||'').indexOf(s.name)>=0;});
          if(c) c.click(); return 1;})()
        """ % json.dumps(KEY))
        time.sleep(1.5)
        pg.ev("""(function(){var d=[...document.querySelectorAll('#mSkins .skin')].find(function(e){
           return e.dataset.k===%s;}); if(d) d.click(); return 1;})()""" % json.dumps(KEY))
        time.sleep(1.2)
        pg.ev("""(function(){var t=[...document.querySelectorAll('#mTabs .tab')].find(function(e){
           return e.dataset.k==='live2d';}); if(t&&!t.classList.contains('dis')) t.click(); return 1;})()""")
        time.sleep(11)
        p = os.path.join(OUT, '%s.png' % tag)
        pg.shot(p)
        return p
    finally:
        pg.close()


def main():
    try:
        with urllib.request.urlopen(URL, timeout=6) as r:
            if r.status != 200:
                print('[INVALID]'); return 2
    except Exception as e:  # noqa: BLE001
        print('[INVALID] 服务器不可达:', e); return 2

    if not os.path.isdir(BAK):
        print('[FAIL] 没有备份目录 %s，无法做该 A/B' % BAK); return 2

    print('=== A 组：当前产物（EMIT_CONST）===')
    switch_to(TARGET, 'A-now')  # 已是当前，仅统计
    pa = shoot('A_const')

    print('\n=== B 组：退回补 ConstantClip 之前（仅 streamed）===')
    switch_to(BAK, 'B-streamed')
    pb = shoot('B_streamed')

    print('\n=== 还原为 A 组 ===')
    switch_to(os.path.join(ROOT, '.diag', 'motion_const', KEY, 'motion'), 'A-restore')

    print('\n%-10s %-10s %s' % ('组', '红像素', '截图'))
    print('%-10s %-10d %s' % ('A(23326)', red_px(pa), os.path.basename(pa)))
    print('%-10s %-10d %s' % ('B(4487)', red_px(pb), os.path.basename(pb)))
    print('\n判读：若 A 与 B 红像素接近，说明补 ConstantClip 与「鞋是否可见」无关')
    return 0


if __name__ == '__main__':
    sys.exit(main())