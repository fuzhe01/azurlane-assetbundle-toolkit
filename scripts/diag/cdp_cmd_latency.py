"""逐条 CDP 命令的耗时归因（2026-10-29）。

问题
----
`l2d_click_branch_diag.py` 实测：模型加载完成后
    `1+1`（不含任何产品代码）             18 ms
    `Page.bringToFront`                   5224 / 3615 / 7306 / 11414 ms
    一次 trivial 的 JS（RESET）           2492 / 8018 / 5914 ms
    `__costumeScreenOf`                   2880 / 4455 / 10113 ms
    `__L2_HITALL`                         3042 / 4261 / 10600 ms
    `SNAP`                                6149 / 4257 / 9855 ms
⇒ 后续每条命令都在秒级排队，导致 `mousePressed`→`mouseReleased` 间隔 6.5–13.9 秒。
   而产品**正是靠这两个时刻各自的几何**判命中（`onDown` 的 `cosDown` + `onUp` 的补算）
   ⇒ 在这种延迟下，任何点击探针的输出都是**仪器产物**，不能归因产品。

两个候选成因
------------
H1 **心跳线程 + 主线程共用一把锁**：`Page.cmd` 在 `self._lock` 内发请求并阻塞等响应，
   `_heartbeat` 每 8 秒也走同一条路径调 `Page.bringToFront`。若 `bringToFront` 本身
   要 5–11 秒，它就把锁占住 5–11 秒，主线程的每次 evaluate 都在队尾等。
H2 **`Page.bringToFront` 在 headless 下本身就慢**（与心跳无关）。

判据
----
· 紧邻序列 10 次 `1+1` 全在 <100 ms，而序列里只要夹一次 `bringToFront` 后面就变秒级
  ⇒ H1 成立（锁被心跳/显式调用占住）
· 停掉心跳后（`KEEPALIVE=0` 或直接 `_hb_stop.set()`）逐条命令全部回到毫秒级
  ⇒ H1 成立，且修法 = **点击类探针必须关掉心跳**（或换锁为「按 id 分表等待」）
· 关掉心跳后 `bringToFront` 仍要数秒 ⇒ H2 成立，则修法 = 别调它，改用别的保活手段

用法:
  py -3 scripts/diag/cdp_cmd_latency.py [keepalive 0|1] [显式调 bringToFront 0|1]
  py -3 scripts/diag/cdp_cmd_latency.py 1 1     # 默认：心跳开 + 手动 bringToFront
  py -3 scripts/diag/cdp_cmd_latency.py 0 0     # 对照：心跳关 + 不手动调
  py -3 scripts/diag/cdp_cmd_latency.py 1 0     # 只留心跳
"""
import json
import os
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts', 'diag'))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

from gallery_ui_shots import Page  # noqa: E402

KA = (sys.argv[1] if len(sys.argv) > 1 else '1') != '0'
FRONT = (sys.argv[2] if len(sys.argv) > 2 else '1') != '0'
KEY = 'ougen_8'
PID = 'ShoseOff'
BASE = 'http://127.0.0.1:8778/gallery_v2/index.html#gallery_v2'
PORT = 9414
PROF = r'D:\azur\.diag\cmdlat_prof'

RESET = "(function(){return 'ok';})()"
HITALL = "(function(){return JSON.stringify(window.__L2_HITALL(556,335)||[]);})()"
SCREENOF = "JSON.stringify(window.__costumeScreenOf(%s))" % json.dumps(PID)
SNAP = ("(function(){var m=(window.__l2ModelRef&&window.__l2ModelRef())||null;"
        "if(!m||!m.internalModel) return 'NO';var c=m.internalModel.coreModel,n=c.getDrawableCount(),o=[];"
        "for(var i=0;i<n;i++){var p=0;try{p=+c.getDrawableOpacity(i);}catch(e){}o.push(+p.toFixed(3));}"
        "return JSON.stringify({n:n,rows:o});})()")


def timed(pg, label, expr=None, cmd=None, reps=1):
    ts = []
    for _ in range(reps):
        t0 = time.time()
        if cmd:
            pg.cmd(cmd)
        else:
            pg.ev(expr)
        ts.append((time.time() - t0) * 1000)
    s = sorted(ts)
    print('  %-22s %s' % (label, ' '.join('%d' % x for x in ts)))
    return s[len(s) // 2]


def main():
    try:
        with urllib.request.urlopen(BASE, timeout=6) as r:
            if r.status != 200:
                print('[INVALID] HTTP %s' % r.status); return 2
    except Exception as e:  # noqa: BLE001
        print('[INVALID] 服务不可达: %s' % e); return 2

    print('keepalive=%s  手动 bringToFront=%s' % (KA, FRONT))
    pg = Page(PORT, PROF, BASE, (1400, 1000), gpu=True, keepalive=KA)
    try:
        time.sleep(4)
        pg.ev("""(function(){var b=document.querySelector('#gOpt button[data-k=login]');
           if(b&&(b.classList.contains('on')||b.dataset.on==='1')) b.click(); return 1;})()""")
        time.sleep(0.9)
        pg.ev("""(function(){var s=(window.GALLERY.ships||[]).find(function(x){
             return (x.skins||[]).some(function(k){return k.key==%s;});});
          if(!s) return 'NO_SHIP';
          var c=[...document.querySelectorAll('.card')].find(function(e){
             return (e.textContent||'').indexOf(s.name)>=0;});
          if(!c) return 'NO_CARD'; c.click(); return 'OK';})()""" % json.dumps(KEY))
        time.sleep(1.6)
        pg.ev("""(function(){var d=[...document.querySelectorAll('#mSkins .skin')].find(function(e){
           return e.dataset.k===%s;}); if(!d) return 'NO_ROW'; d.click(); return 'OK';})()"""
              % json.dumps(KEY))
        time.sleep(1.3)
        pg.ev("""(function(){var t=[...document.querySelectorAll('#mTabs .tab')].find(function(e){
           return e.dataset.k==='live2d';}); if(!t) return 'NO_TAB';
           if(t.classList.contains('dis')) return 'DIS'; t.click(); return 'OK';})()""")
        for _ in range(90):
            if pg.ev("(function(){ return (window.__l2ModelRef&&__l2ModelRef())?1:0; })()") == 1:
                break
            time.sleep(1.0)
        if pg.ev("(function(){ return (window.__l2ModelRef&&__l2ModelRef())?1:0; })()") != 1:
            print('[FAIL] 模型未加载'); return 2
        print('模型已加载（未开推帧泵）\n')

        print('--- 阶段 1：裸序列（紧跟加载）---')
        timed(pg, '1+1 ×10', expr='1+1', reps=10)

        print('\n--- 阶段 2：夹一次 Page.bringToFront ---')
        timed(pg, 'bringToFront ×2', cmd='Page.bringToFront', reps=2)
        timed(pg, '1+1 ×10（其后）', expr='1+1', reps=10)

        print('\n--- 阶段 3：产品重调用 ---')
        timed(pg, 'SNAP ×3', expr=SNAP, reps=3)
        timed(pg, 'ScreenOf ×3', expr=SCREENOF, reps=3)
        timed(pg, 'HITALL ×3', expr=HITALL, reps=3)
        timed(pg, '1+1 ×10（再其后）', expr='1+1', reps=10)

        print('\n--- 阶段 4：若心跳开，临时停掉它再测 ---')
        if KA:
            try:
                pg._hb_stop.set()
                print('  已置 _hb_stop（当前循环最多再跑一次 bringToFront）')
            except Exception as e:  # noqa: BLE001
                print('  停心跳失败:', e)
            time.sleep(10)
        timed(pg, '1+1 ×10（停心跳后）', expr='1+1', reps=10)
        timed(pg, 'bringToFront ×2（停心跳后）', cmd='Page.bringToFront', reps=2)
        timed(pg, '1+1 ×10（停心跳+调front后）', expr='1+1', reps=10)

        print('\n--- 阶段 5：真点击的派发间隔 ---')
        for i in range(3):
            t0 = time.time()
            pg.cmd('Input.dispatchMouseEvent', {'type': 'mousePressed', 'x': 600, 'y': 400,
                                               'button': 'left', 'clickCount': 1})
            t1 = time.time()
            time.sleep(0.08)
            t2 = time.time()
            pg.cmd('Input.dispatchMouseEvent', {'type': 'mouseReleased', 'x': 600, 'y': 400,
                                               'button': 'left', 'clickCount': 1})
            t3 = time.time()
            print('  第%d次: Press %.0f ms / Release %.0f ms ⇒ 间隔 %.0f ms'
                  % (i + 1, (t1 - t0) * 1000, (t3 - t2) * 1000,
                     (t1 - t0) * 1000 + 80 + (t3 - t2) * 1000))

        print('\n--- 阶段 6：开推帧泵后的对照（已知会慢，作判据用）---')
        print('  泵:', pg.detach_frames(60))
        time.sleep(1.0)
        timed(pg, '1+1 ×6（泵开）', expr='1+1', reps=6)
        print('  泵后 fps: %.1f' % pg.require_frames(2.0))
        return 0
    finally:
        try: pg._hb_stop.set()
        except Exception: pass
        pg.close()


if __name__ == '__main__':
    sys.exit(main())
