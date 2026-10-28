"""第六层仪器故障取证：**画布尺寸 / 超视口画布** 是否让 headless 合成器周期性卡死。

上一轮排除台账（每条都是同仪器实测读数）：
  · SwiftShader 回退 —— UNMASKED 全程 NVIDIA RTX 4070；
  · 上下文丢失 —— webglcontextlost 0 次、isContextLost() 恒 false；
  · 节流 —— visibility=visible、hasFocus=true、ΔrAF ≡ Δcore.update；
  · 每帧工作变慢 —— medA=6ms / medB=11ms 平稳，只有偶发 1s 整段停顿；
  · CDP 取样本身 —— 20 秒只取两次仍 11.6fps；
  · `Network.enable` / `setCacheDisabled` —— A/B/C 三组全衰减；
  · Live2D 特有 —— 不切 Live2D 的静态立绘页同样掉到 1fps；
  · 堆累积 / 主 GC —— 堆全程 24–38MB 平稳，强制 GC 后仍 1fps；
  · 宿主本身卡 —— 极简 800×600 页面同浏览器稳定 60fps 满 12 秒。

⇒ 剩下唯一未被控制的差异：**画布尺寸**。
  产品页两块 canvas：986×651 与 **2098×1558**；窗口只有 1400×1000 × dpr=1.5 = 2100×1500。
  第二块正好是「视口 × dpr」，即**超出 CSS 视口约 1.5 倍的超大 WebGL 后备缓冲**。
  本机 dpr=1.5 是因为 Windows 显示缩放 150%。

判据（新页自带参数，逐个只改尺寸，其余全同）：
  S1 800×600        → 基线；必须 60fps（复现上一轮 C2）
  S2 fit=1（视口×dpr）→ 若衰减，尺寸/超视口就是成因
  S3 fit=2 ov=2（视口×dpr×2，刻意更大）→ 若 S2 不衰减而 S3 衰减，说明是**阈值**问题
  三组同轮跑完；只有 S1 稳而 S2 或不稳才能定责，任一不稳都说明尺寸不是唯一变量。
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, r'd:\azur\scripts\diag')

from cdp_helper import open_page  # noqa: E402

BASE = 'file:///D:/azur/scripts/diag/glmin_size.html'

READ = r"""
(function(){
  var p=window.__rafc||{}, s=window.__size||{};
  return JSON.stringify({n:p.n, ms:+(performance.now()-(p.t0||0)).toFixed(0),
    gapMax:+(p.gapMax||0).toFixed(0), stalls:p.stalls||0,
    w:s.w, h:s.h, dpr:s.dpr, iw:s.iw, ih:s.ih, gl:String(window.__info)});
})()
"""


def fps_between(a, b):
    dm = b['ms'] - a['ms']
    return (b['n'] - a['n']) * 1000.0 / dm if dm else 0.0


def case(label, query, rounds=12):
    url = BASE + query
    print('\n===== %s  (%s) =====' % (label, query))
    pg = open_page(url + '#gallery_v2', win=(1400, 1000), tag=label[:2])
    try:
        time.sleep(2.0)
        first = json.loads(pg.ev(READ))
        print('  canvas %dx%d (dpr=%s, 视口 %dx%d) | %s'
              % (first['w'], first['h'], first['dpr'], first['iw'], first['ih'], first['gl']))
        print('  %-7s %-6s %-9s %-7s %s' % ('ms', 'n', 'gapMax', 'stalls', 'fps'))
        prev = first
        for _ in range(rounds):
            s = json.loads(pg.ev(READ))
            f = fps_between(prev, s)
            print('  %-7d %-6d %-9d %-7d %.1f' % (s['ms'], s['n'], s['gapMax'],
                                                  s['stalls'], f))
            prev = s
            time.sleep(1.0)
        print('  ⇒ 末窗 %.1f fps, 停顿次数=%d' % (fps_between(prev, prev), prev['stalls']))
    finally:
        pg.close()


def main():
    case('S1 800x600', '?w=800&h=600')
    case('S2 视口xdpr', '?fit=1')
    case('S3 视口xdpr x2', '?fit=2&ov=2')
    return 0


if __name__ == '__main__':
    sys.exit(main())
