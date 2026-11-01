"""关键方法学复核：**所有"60fps 稳定"的对照都只跑了约 10 秒**，而产品页总在 15–25 秒后衰减。

这一条如果成立，本轮前十三节的"排除法"有一半结论要作废 —— 因为它们都建立在
"极简页稳定 60fps"这个前提上，而那个前提的观测窗口太短。

证据（本轮读数的时间轴，全部同一台机）：
  · `stall_trigger_step_diag`：初载 60fps 满 10 秒，点舰船卡后 1.9fps；
  · `headful_vs_headless_fps`：初载 60.0，点舰船卡后 **5 秒内仍 59.3**，再 5 秒掉到 2.8；
  · `gl_call_audit_diag`：点舰船卡后 **18 秒仍 59.7fps**，第 25 秒才 3.7fps；
  ⇒ 衰减有一个 **15–25 秒的潜伏期**。
  而所有对照页（800x600 / 视口×dpr / 视口×dpr×2 / 单上下文 / 双上下文）
  **每例只观测 10–12 秒**，正好卡在潜伏期之内。

本节只做一件事：极简页（不含任何产品代码）连续观测 **70 秒**，每秒一行。
  L1 800x600      —— 与最初"稳定"的对照同参数
  L2 视口×dpr     —— 与产品页第二块画布同参数
判据：
  · 若两个极简页在 20 秒后也衰减 ⇒ 「衰减」与产品无关，是宿主/浏览器的时间性行为，
    前十三节所有"产品侧"结论全部作废，必须回到环境侧；
  · 若 70 秒一直 60fps ⇒ 产品页确实特殊，回到产品侧继续查。
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
  var p=window.__rafc||{n:0,t0:0,gapMax:0,stalls:0}, s=window.__size||{};
  return JSON.stringify({n:p.n, ms:+(performance.now()-(p.t0||0)).toFixed(0),
    gapMax:+(p.gapMax||0).toFixed(0), stalls:p.stalls||0, w:s.w, h:s.h});
})()
"""


def run(label, query, seconds=70):
    print('\n===== %s (%s) 连续观测 %d 秒 =====' % (label, query, seconds))
    pg = open_page(BASE + query + '#gallery_v2', win=(1400, 1000), tag=label[:2])
    try:
        time.sleep(2.0)
        first = json.loads(pg.ev(READ))
        print('  canvas %dx%d' % (first['w'], first['h']))
        print('  %-7s %-6s %-9s %-7s %s' % ('ms', 'n', 'gapMax', 'stalls', 'fps'))
        prev = first
        drops = []
        for i in range(seconds):
            s = json.loads(pg.ev(READ))
            dm = s['ms'] - prev['ms']
            f = (s['n'] - prev['n']) * 1000.0 / dm if dm else 0.0
            flag = ''
            if f < 30.0:
                drops.append(int(s['ms'] / 1000))
                flag = '   <<< 掉帧'
            if i % 2 == 0 or f < 30.0:
                print('  %-7d %-6d %-9d %-7d %-6.1f%s'
                      % (s['ms'], s['n'], s['gapMax'], s['stalls'], f, flag))
            prev = s
            time.sleep(1.0)
        print('  ⇒ 共 %d 秒，掉帧（<30fps）出现于第 %s 秒'
              % (seconds, drops[:8] if drops else '无'))
    finally:
        pg.close()


def main():
    run('L1 800x600', '?w=800&h=600')
    run('L2 视口xdpr', '?fit=1')
    return 0


if __name__ == '__main__':
    sys.exit(main())
