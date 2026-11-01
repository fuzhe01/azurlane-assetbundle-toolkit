"""验证 EMIT_CONST 换入效果——按「切换轴」判据（技能明确要求）。

技能原文：常量曲线只在「切动作/切段复位」轴生效，idle 单次循环内不触发复位，
所以在 idle 轴上测会得到「常量无用」的假否证。必须测 idle → touch → idle。

前端真实接口（从 gallery_src/index.html 实读，不是猜的）：
  - 动作下拉  #l2Motion   （select）
  - 重播按钮  #l2Replay
  - 播放入口  window.__l2play(group)   ← 页面自己的入口，不绕过它
  - URL 参数  &motion=<组名> 让模型就绪后自动播

⚠️ 模型对象是闭包局部变量（mdl），前端**没有**暴露 coreModel 的钩子。
因此这里用「截图差分」判据：同一视角下
    A. idle 稳定态            —— 基线
    B. touch_idleN 播放后     —— 姿态改变（应有明显差异）
    C. 切回 idle 后           —— 应回到 A（复位成功）
若 C≈A 且 B≠A，说明切换轴的复位链路是通的。
若 C 明显≠A，说明姿态参数没被复位（正是丢 constant 曲线的症状）。

用法: py -3 scripts/diag/verify_emit_const_runtime.py [key]
"""
import json
import os
import sys
import time

sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(HERE))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

import paths as P  # noqa: E402
import gallery_ui_shots as GU  # noqa: E402
GU.CHROME = P.CHROME
from gallery_ui_shots import Page  # noqa: E402
from PIL import Image, ImageChops, ImageStat  # noqa: E402

KEY = sys.argv[1] if len(sys.argv) > 1 else 'ougen_8'
OUT = os.path.join(ROOT, '.diag', 'emit_const_verify')
os.makedirs(OUT, exist_ok=True)


def diff_ratio(pa, pb):
    """两图在共同尺寸下的像素差异占比（只看显著差异，滤掉呼吸抖动噪声）。

    ⚠️ 尺寸不一致时必须裁到共同区域再比，不能返回哨兵值——
    哨兵值会被判据端当成"差异很小"从而假通过（2026-10-23 踩过：-1.0 < 0.08 被判 OK）。
    """
    a = Image.open(pa).convert('RGB')
    b = Image.open(pb).convert('RGB')
    w = min(a.size[0], b.size[0])
    h = min(a.size[1], b.size[1])
    # 只比中心区域（模型所在），避开顶部工具栏/底部日志栏的文本变化
    box = (int(w * .40), int(h * .20), int(w * .95), int(h * .80))
    a = a.crop(box)
    b = b.crop(box)
    if a.size != b.size:
        b = b.resize(a.size)
    d = ImageChops.difference(a, b).convert('L')
    hist = d.histogram()
    total = sum(hist)
    changed = sum(hist[12:])   # >12 灰度差才计入
    return changed / total if total else 0.0


def open_model(pg, key):
    pg.ev("""
    (function(){var ship=(window.GALLERY.ships||[]).find(s=>(s.skins||[]).some(k=>k.key===%s));
      var c=[...document.querySelectorAll('.card')].find(el=>(el.textContent||'').indexOf(ship.name)>=0);
      if(c) c.click(); return 1;})()""" % json.dumps(key))
    time.sleep(1.0)
    pg.ev("""(function(){var d=[...document.querySelectorAll('#mSkins .skin')].find(el=>el.dataset.k===%s);
      if(d) d.click(); return 1;})()""" % json.dumps(key))
    time.sleep(0.7)
    return pg.ev("""(function(){var t=[...document.querySelectorAll('#mTabs .tab')].find(el=>el.dataset.k==='live2d');
      if(t&&!t.classList.contains('dis')) t.click(); return 1;})()""")


def play(pg, group):
    """走页面自己的入口 window.__l2play，并同步下拉框显示。"""
    return pg.ev("""
    (function(){
      var sel=document.getElementById('l2Motion');
      if(sel){
        var has=[...sel.options].some(function(o){return o.value===%s;});
        if(!has) return 'NO_GROUP';
        sel.value=%s;
      }
      if(typeof window.__l2play!=='function') return 'NO_HOOK';
      var ok=window.__l2play(%s);
      return ok? 'PLAYED':'PLAY_FALSE';
    })()
    """ % (json.dumps(group), json.dumps(group), json.dumps(group)))


def main():
    pg = Page(9234, os.path.join(ROOT, '.diag', 'chrome_ecv'),
              'http://127.0.0.1:8778/gallery_v2/index.html', (1400, 1000))
    try:
        pg.ev("""(function(){var b=document.querySelector('#gOpt button[data-k=login]');
           if(b&&(b.classList.contains('on')||b.dataset.on==='1')) b.click(); return 1;})()""")
        time.sleep(0.5)
        open_model(pg, KEY)
        time.sleep(4)

        groups = pg.ev("JSON.stringify([...((document.getElementById('l2Motion')||{}).options||[])]"
                       ".map(function(o){return o.value;}))")
        print('可选动作组:', groups)

        # A. idle 稳定
        print('\n[A] 播 idle:', play(pg, 'idle'))
        time.sleep(4)
        pa = os.path.join(OUT, 'A_idle.png')
        pg.shot(pa)

        # B. 播一个 touch 组
        target = None
        for cand in ('touch_idle1', 'touch_idle5', 'touch_body', 'touch_head'):
            r = play(pg, cand)
            if r == 'PLAYED':
                target = cand
                break
        print('[B] 播 %s: %s' % (target, r))
        time.sleep(4)
        pb = os.path.join(OUT, 'B_touch.png')
        pg.shot(pb)

        # C. 切回 idle
        print('[C] 切回 idle:', play(pg, 'idle'))
        time.sleep(4)
        pc = os.path.join(OUT, 'C_back_idle.png')
        pg.shot(pc)

        ab = diff_ratio(pa, pb)
        ca = diff_ratio(pc, pa)

        # 判据必须带有效性前置检查，否则「三次都没播成」会输出 0.0 差异 -> 假 PASS
        valid = (target is not None
                 and os.path.getsize(pa) > 0 and os.path.getsize(pb) > 0 and os.path.getsize(pc) > 0)
        print('\n=== 切换轴判据 ===')
        print('  截图尺寸: A=%s B=%s C=%s'
              % (Image.open(pa).size, Image.open(pb).size, Image.open(pc).size))
        if not valid:
            print('  [FAIL] 前置检查未通过（未成功播放 / 截图为空）—— 判据无效，不得当 PASS')
            return 1
        print('  B vs A（touch 改变姿态，应 > 0.02）: %.4f  %s'
              % (ab, 'OK' if ab > 0.02 else 'FAIL(姿态没变)'))
        print('  C vs A（切回 idle 复位，应 < 0.08）: %.4f  %s'
              % (ca, 'OK(已复位)' if ca < 0.08 else 'FAIL(未复位)'))
        print('  页面异常:', pg.ev("JSON.stringify(window.__errs||[])"))
        ok = (ab > 0.02) and (ca < 0.08)
        print('  结论:', 'PASS' if ok else 'FAIL')
        return 0 if ok else 1
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())
