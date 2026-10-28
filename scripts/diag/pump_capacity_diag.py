# -*- coding: utf-8 -*-
"""量推帧器的**真实容量**：到底是「浏览器钳住定时器」还是「单帧渲染成本顶住」。

背景（2026-10-28）：`render_entry_verify.py` 在解耦模式下报 34.8 fps，而按单帧成本
（EMA 9.28 ms）推算本应能达到 61 fps。两个数互相矛盾 ⇒ 说明"单帧成本"这个读数
本身不可靠（EMA 权重 0.2 收敛慢；抓帧时 `did=2` 会把总耗时除以 2）。
在改判据之前必须先把「限制项是谁」量出来，否则又会把硬件成本写成"帧源停摆"。

判据（四个读数同时看）：
  · ticks/s   —— setInterval(4) 的回调频率。理论 250/s；明显偏低 = 定时器被钳
  · maxItv    —— 相邻回调最大间隔。远大于 4ms = 定时器被钳/主线程被占
  · n/s       —— 实际推出去的帧数（= 帧率）
  · cost      —— 单帧 ticker.update 耗时
若 ticks/s ≈ 250 且 maxItv 小，而 n/s 只有 35 ⇒ **cost 才是上限**，fps 判据必须按 cost 算。
若 ticks/s 只有 ~35 且 maxItv ~28ms ⇒ 定时器被钳，得换驱动方式（如 rAF 或 Worker）。

用法：py -3 scripts/diag/pump_capacity_diag.py [宽x高]
"""
import json
import os
import sys
import time

sys.path.insert(0, r'd:\azur\scripts\diag')
from gallery_ui_shots import Page  # noqa: E402

URL = 'http://127.0.0.1:8778/gallery_v2/index.html#gallery_v2'
WIN = (1400, 1000)
if len(sys.argv) > 1:
    w, h = sys.argv[1].lower().split('x')
    WIN = (int(w), int(h))

CLOSE_LOGIN = """(function(){var b=document.querySelector('#gOpt button[data-k=login]');
   if(b&&(b.classList.contains('on')||b.dataset.on==='1')) b.click(); return 1;})()"""
OPEN_SHIP = """(function(){var s=(window.GALLERY.ships||[]).find(function(x){
     return (x.skins||[]).some(function(k){return k.key=='ougen_8';});});
  var c=[...document.querySelectorAll('.card')].find(function(e){
     return (e.textContent||'').indexOf(s.name)>=0;});
  if(!c) return 'NO_CARD'; c.click(); return 'OK';})()"""
PICK_SKIN = """(function(){var d=[...document.querySelectorAll('#mSkins .skin')].find(function(e){
   return e.dataset.k=='ougen_8';}); if(!d) return 'NO_ROW'; d.click(); return 'OK';})()"""
TO_L2D = """(function(){var t=[...document.querySelectorAll('#mTabs .tab')].find(function(e){
   return e.dataset.k=='live2d';}); if(!t) return 'NO_TAB';
   if(t.classList.contains('dis')) return 'DIS'; t.click(); return 'OK';})()"""


def snap(pg):
    return json.loads(pg.ev(pg.FRAME_SAMPLE))


def main():
    pg = Page(9404, r'D:\azur\.diag\cap_prof', URL, WIN, gpu=True, keepalive=False)
    try:
        time.sleep(4)
        pg.ev(CLOSE_LOGIN); time.sleep(0.9)
        print('开卡:', pg.ev(OPEN_SHIP), end=' '); time.sleep(1.6)
        print('选肤:', pg.ev(PICK_SKIN), end=' '); time.sleep(1.3)
        print('切L2D:', pg.ev(TO_L2D))
        t0 = time.time()
        while time.time() - t0 < 90:
            if pg.ev("(function(){return (window.__l2ModelRef&&window.__l2ModelRef())?1:0;})()") == 1:
                break
            time.sleep(1.0)
        print('窗口:', WIN, '解耦:', pg.detach_frames(60))
        time.sleep(2.0)
        print('\n%6s %9s %9s %9s %8s %8s' % ('t', 'n/s', 'ticks/s', 'maxItv', 'cost', 'ntk'))
        prev = snap(pg)
        pt = time.time()
        for i in range(8):
            time.sleep(2.5)
            cur = snap(pg)
            dt = time.time() - pt
            print('%6.1f %9.2f %9.1f %9.1f %8s %8s' % (
                time.time() - t0,
                (cur['n'] - prev['n']) / dt,
                (cur.get('ticks', 0) - prev.get('ticks', 0)) / dt,
                cur.get('maxItv', 0), cur.get('cost'), cur.get('ntk')))
            prev, pt = cur, time.time()
        print('\nerr:', cur.get('err'))
        # 对照：把推帧步长放宽到 30 fps，看 n/s 是否跟着变（若不变 ⇒ 上限就是 cost）
        pg.reattach_frames(); time.sleep(0.3)
        print('重挂后 src:', snap(pg).get('src'))
    finally:
        pg.close()


if __name__ == '__main__':
    main()
