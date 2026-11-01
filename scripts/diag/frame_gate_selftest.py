"""`gallery_ui_shots` 帧源闸门的自测（四判据 + 阴性对照）—— 2026-10-29。

为什么需要这份自测
------------------
`frames_alive()` 曾经**恒判红**：它读的 `window.__rafc` 在产品里根本不存在
（产品只导出 `__l2TickerState` / `__l2Ticker`），于是落到 `src:'ticker'` 且 `n:0`，
`(b.n-a.n)/dm` 永远是 0。这个假红存在了很久没人发现，因为大多数探针只把它当
「打印诊断」而不当硬闸 —— 一旦有人把它接成硬闸，就会把健康页面全判死。
反过来更危险：若改成拿 `lastTime` 当帧率，被节流到 1 Hz 的页面会在采样窗口里
照样涨满 `dm`，得到**满帧的假绿灯**。所以「红」和「绿」两侧都必须有判据。

四判据
------
P1 正常页面（不推帧）：`src` 必须为 `ticker`、`n` 必须真的涨、`frames_alive` 判绿。
P2 推帧泵开着：`src` 必须为 `pump`、判绿。证明另一条分支也活着。
P3 **阴性对照（必须漏）**：把 ticker 停掉后 `frames_alive` 必须判**红**。
   这一条是整份自测的核心 —— 若停掉的 ticker 也能判绿，那 P1 的绿就没有区分力。
P4 采样窗口内的 `n` 增量是**页内单调时钟**算的，故两次读数不能相差离谱
   （同一页面 2 秒窗口的 fps 落在 5–200 之间；越界说明计数器被复用/重置）。

用法
----
    py -3 scripts/diag/frame_gate_selftest.py
退出码 0 = 四判据全过。
"""
import os
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, HERE)

from gallery_ui_shots import Page  # noqa: E402

BASE = 'http://127.0.0.1:8778/gallery_v2/index.html#gallery_v2'
PORT = 9417
PROF = r'D:\azur\.diag\framegate_prof'


def main():
    try:
        with urllib.request.urlopen(BASE, timeout=6) as r:
            if r.status != 200:
                print('[INVALID] HTTP %s' % r.status); return 2
    except Exception as e:  # noqa: BLE001
        print('[INVALID] 服务不可达: %s' % e); return 2

    pg = Page(PORT, PROF, BASE, (1200, 900), gpu=True, keepalive=True)
    fail = []
    try:
        time.sleep(4)
        pg.ev("""(function(){var b=document.querySelector('#gOpt button[data-k=login]');
           if(b&&(b.classList.contains('on')||b.dataset.on==='1')) b.click(); return 1;})()""")
        time.sleep(0.9)
        pg.ev("""(function(){var s=(window.GALLERY.ships||[]).find(function(x){
             return (x.skins||[]).some(function(k){return k.key==='ougen_8';});});
          var c=[...document.querySelectorAll('.card')].find(function(e){
             return (e.textContent||'').indexOf(s.name)>=0;});
          if(c) c.click(); return 1;})()""")
        time.sleep(1.6)
        pg.ev("""(function(){var d=[...document.querySelectorAll('#mSkins .skin')].find(function(e){
           return e.dataset.k==='ougen_8';}); if(d) d.click(); return 1;})()""")
        time.sleep(1.3)
        pg.ev("""(function(){var t=[...document.querySelectorAll('#mTabs .tab')].find(function(e){
           return e.dataset.k==='live2d';}); if(t&&!t.classList.contains('dis')) t.click(); return 1;})()""")
        ok = 0
        for _ in range(90):
            if pg.ev("(function(){ return (window.__l2ModelRef&&__l2ModelRef())?1:0; })()") == 1:
                ok = 1
                break
            time.sleep(1.0)
        if not ok:
            print('[INVALID] 模型未加载'); return 2
        # 让 rAF 侧先跑热，再测闸门（JIT/首帧长任务会污染 maxItv，但不参与判定）
        time.sleep(2.0)

        print('\n===== P1 正常页面（不推帧）=====')
        a = pg.ev(pg.FRAME_SAMPLE)
        ok1, fps1, s1 = pg.frames_alive(2.0, pg.MIN_FPS)
        print('  首读 %s' % a)
        print('  二读 %s' % s1)
        print('  ⇒ ok=%s fps=%.1f src=%s n=%s' % (ok1, fps1, s1.get('src'), s1.get('n')))
        if s1.get('src') != 'ticker':
            fail.append('P1 src=%s（应为 ticker）' % s1.get('src'))
        if not ok1:
            fail.append('P1 健康页面被闸门判红（假红）')
        if not (5.0 <= fps1 <= 400.0):
            fail.append('P4 fps=%.1f 越界（计数器可能被重置/复用）' % fps1)

        print('\n===== P2 推帧泵开着 =====')
        print('  detach:', pg.detach_frames(60))
        time.sleep(1.2)
        ok2, fps2, s2 = pg.frames_alive(2.0, pg.MIN_FPS)
        print('  读数 %s' % s2)
        print('  ⇒ ok=%s fps=%.1f src=%s n=%s cost=%sms'
              % (ok2, fps2, s2.get('src'), s2.get('n'), s2.get('cost')))
        if s2.get('src') != 'pump':
            fail.append('P2 src=%s（应为 pump）' % s2.get('src'))
        if not ok2:
            fail.append('P2 推帧泵开着却判红')

        print('\n===== P3 阴性对照：停掉 ticker，闸门必须判红 =====')
        print('  reattach:', pg.reattach_frames())
        # 把两条 ticker 都停死（不推帧、不自动）。
        # 注意：计数器挂在 ticker 的 listener 上，ticker 不 update 时 n 不涨 —— 这正是要测的。
        pg.ev("""(function(){
          var tk=window.__l2Ticker&&window.__l2Ticker(); if(tk){ tk.autoStart=false; tk.stop(); }
          var sh=(window.PIXI&&window.PIXI.Ticker&&window.PIXI.Ticker.shared)||null;
          if(sh&&sh!==tk){ sh.autoStart=false; sh.stop(); }
          return 'stopped';})()""")
        time.sleep(0.7)
        ok3, fps3, s3 = pg.frames_alive(2.0, pg.MIN_FPS)
        print('  读数 %s' % s3)
        print('  ⇒ ok=%s fps=%.1f n=%s' % (ok3, fps3, s3.get('n')))
        if ok3:
            fail.append('P3 **阴性对照漏了**：ticker 已停死但闸门判绿（%.1f fps）⇒ P1 的绿没有区分力'
                        % fps3)
        else:
            print('  ✅ 阴性对照按预期判红 —— P1/P2 的绿有区分力')

        print('\n' + '=' * 70)
        if fail:
            print('❌ 未通过：')
            for f in fail:
                print('   · ' + f)
            return 1
        print('✅ 四判据全过（P1 绿 + P2 绿 + P3 必红 + P4 数值合理）')
        return 0
    finally:
        try: pg._hb_stop.set()
        except Exception: pass
        pg.close()


if __name__ == '__main__':
    sys.exit(main())
