# -*- coding: utf-8 -*-
r"""chrome_tree 生命周期兜底的**阴性对照自测**——证明「强杀不漏」是机制而非巧合。

为什么必须做成独立自测（2026-10-28 教训）：本轮之前所有探针都靠 `install()` 的 atexit
收尾，正常路径看起来完全正确。但实测三组对照：

    正常退出                      → atexit 执行 ✅
    sys.exit()                    → atexit 执行 ✅
    Stop-Process -Force / taskkill /F → atexit **不执行**，Chrome 整棵树全存活 ❌

⇒ `finally` / `atexit` 在 SIGKILL 等价物下都不跑，**任何进程内清理机制都救不了**。
真实事故：宿主超时强杀 python，6 个孤儿实例、62 个进程、5.83 GB 内存横跨 6 次运行累积，
把系统 CPU 顶到 96%。修法只能是进程外 / 内核级兜底（Job Object）。

本自测的五条判据（缺任一条都不算成立）：
  ① 正常退出          → 残留 0（atexit + job 句柄关闭两条路径）
  ② 父进程被强杀      → 残留 0（**Job Object 是唯一防线**）
  ③ 同一条强杀 + AL_NO_JOB=1（阴性对照）→ 残留 **>0**
     没有这一条，②的绿就是「判据没有区分力」的假绿灯：②可能只是浏览器自己退得快。
  ④ 启动前清理能回收 ③ 泄漏的现场（B 层对旧残留有效）
  ⑤ 老写法 `Popen` + `install()` 被强杀 → 残留 0
     这条针对**覆盖缺口**：全库还有 11 个探针走 `install(proc)` 而不是 `launch()`。
     曾经的 `install()` 只注册 atexit ⇒ 它们在强杀下 100% 泄漏。A 层必须也做进 install()。

跑法：
    py -3 scripts/diag/chrome_lifecycle_selftest.py [--no-kill]

退出码：0 = 机制成立 / 1 = 判据不成立（附带诊断行）
"""
import json
import os
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
sys.path.insert(0, os.path.join(ROOT, 'scripts', 'diag'))
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')
import chrome_tree     # noqa: E402
import cdp_slot        # noqa: E402

READY_TIMEOUT = 120


# ---------------------------------------------------------------------------
# 子进程模式：launch 一个真浏览器，然后一直活着等被强杀
# ---------------------------------------------------------------------------
def child_main(ready_file, tag, no_job, mode='launch'):
    port, profile = cdp_slot.slot(ROOT, tag)
    cmd = [os.environ.get('CDP_CHROME') or _chrome(),
           '--headless=new', f'--remote-debugging-port={port}',
           '--remote-allow-origins=*', f'--user-data-dir={profile}',
           '--no-first-run', '--no-default-browser-check',
           '--enable-unsafe-swiftshader', '--use-angle=swiftshader',
           '--window-size=640,480', 'about:blank']
    if mode == 'install':
        # 老写法（全库还有 11 个探针是这个形态）：先 Popen，再 install。
        # 这条判据存在的理由：install() 曾经只注册 atexit ⇒ 强杀下 A 层完全没落地。
        raw = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        proc = chrome_tree.install(raw)
    else:
        proc = chrome_tree.launch(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    with open(ready_file, 'w', encoding='utf-8') as f:
        json.dump({'profile': profile, 'port': port, 'pid': os.getpid(),
                   'child_pid': proc.pid, 'no_job': bool(no_job), 'mode': mode,
                   't_launch': time.time()}, f)
    # 什么都不做，等父进程决定怎么让我死
    while True:
        time.sleep(1)


def _chrome():
    try:
        sys.path.insert(0, os.path.join(ROOT, 'scripts'))
        import paths
        return paths.CHROME
    except Exception:
        return r'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'


# ---------------------------------------------------------------------------
# 父进程模式
# ---------------------------------------------------------------------------
def _spawn_child(tag, no_job, mode='launch'):
    fd, ready = tempfile.mkstemp(prefix='ctself_', suffix='.json', dir=os.path.join(ROOT, '.diag'))
    os.close(fd)
    os.unlink(ready)
    env = dict(os.environ, PYTHONIOENCODING='utf-8')
    if no_job:
        env['AL_NO_JOB'] = '1'
    p = subprocess.Popen([sys.executable, os.path.abspath(__file__), '--child',
                          ready, tag, '--mode', mode] + (['--no-job'] if no_job else []),
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, encoding='utf-8', errors='replace', env=env)
    deadline = time.time() + READY_TIMEOUT
    while time.time() < deadline:
        if os.path.exists(ready):
            time.sleep(0.3)
            with open(ready, encoding='utf-8') as f:
                info = json.load(f)
            os.unlink(ready)
            return p, info
        if p.poll() is not None:
            out = p.stdout.read() if p.stdout else ''
            raise SystemExit('[ERROR] 子进程提前退出 rc=%s\n%s' % (p.returncode, out[-3000:]))
        time.sleep(0.4)
    raise SystemExit('[ERROR] 等不到子进程的就绪标记（浏览器没起来）')


def _residual(profile):
    """按 profile 精确回读浏览器进程（判据只落在这里，不看 taskkill 退出码）。"""
    return chrome_tree.pids_using(profile)


def _kill_force(pid):
    """模拟宿主超时强杀：Stop-Process -Force 对 python 等价于 SIGKILL，不走 atexit。"""
    subprocess.call(['powershell', '-NoProfile', '-Command',
                     'Stop-Process -Id %d -Force -ErrorAction SilentlyContinue' % pid],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _wait_dead(p, secs=20):
    try:
        p.wait(timeout=secs)
    except Exception:
        pass


def case_normal_exit():
    """① 正常退出：子进程 launch 后自己 sys.exit()，atexit 必须清干净。"""
    fd, ready = tempfile.mkstemp(prefix='ctself_', suffix='.json', dir=os.path.join(ROOT, '.diag'))
    os.close(fd)
    os.unlink(ready)
    env = dict(os.environ, PYTHONIOENCODING='utf-8')
    code = r'''
import json, os, subprocess, sys, time
sys.path.insert(0, os.path.join(r"%s", 'scripts'))
sys.path.insert(0, os.path.join(r"%s", 'scripts', 'diag'))
sys.stdout.reconfigure(encoding='utf-8')
import chrome_tree, cdp_slot
port, profile = cdp_slot.slot(r"%s", 'ctnormal')
proc = chrome_tree.launch([r"%s", '--headless=new', '--remote-debugging-port=%%d' %% port,
    '--remote-allow-origins=*', '--user-data-dir=%%s' %% profile,
    '--no-first-run', '--no-default-browser-check', '--window-size=640,480', 'about:blank'],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
json.dump({'profile': profile}, open(r"%s", 'w'))
time.sleep(float("%s"))
sys.exit(0)          # 走正常退出路径 → atexit 必须执行
''' % (ROOT, ROOT, ROOT, _chrome(), ready, max(3.0, chrome_tree.ADOPT_WINDOW + 1.0))
    p = subprocess.Popen([sys.executable, '-c', code], env=env,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, encoding='utf-8', errors='replace')
    deadline = time.time() + READY_TIMEOUT
    info = None
    while time.time() < deadline:
        if os.path.exists(ready):
            time.sleep(0.2)
            with open(ready, encoding='utf-8') as f:
                info = json.load(f)
            os.unlink(ready)
            break
        if p.poll() is not None:
            break
        time.sleep(0.4)
    out = ''
    try:
        p.wait(timeout=180)
    except Exception:
        p.kill()
    out = (p.stdout.read() if p.stdout else '')[-1500:]
    if not info:
        return False, '子进程没报出 profile（rc=%s）\n%s' % (p.returncode, out)
    left = _residual(info['profile'])
    time.sleep(2)
    left = left or _residual(info['profile'])
    msg = 'rc=%s 残留=%d %s' % (p.returncode, len(left), left[:6] if left else '')
    if left:
        return False, msg + '\n' + out
    return True, msg


def case_forced_kill(no_job, mode='launch'):
    """② / ③ 强杀：父进程被 Stop-Process -Force。no_job=True 是阴性对照。"""
    p, info = _spawn_child('ctkill' + ('nj' if no_job else '') + ('' if mode == 'launch' else mode),
                           no_job, mode)
    # 等 adopt 窗口走完，保证 job 已覆盖重新孵化的主进程（否则测的是半成品）
    wait = chrome_tree.ADOPT_WINDOW + 2.0
    left_over = wait - (time.time() - info['t_launch'])
    if left_over > 0:
        time.sleep(left_over)
    before = _residual(info['profile'])
    _kill_force(p.pid)
    _wait_dead(p)
    # taskkill /F 是异步的，留 settle 宽限期再判
    deadline = time.time() + 15
    left = _residual(info['profile'])
    while left and time.time() < deadline:
        time.sleep(0.5)
        left = _residual(info['profile'])
    msg = '父进程 %d 被强杀；强杀前 %d 个进程；残留 %d %s' % (
        p.pid, len(before), len(left), left[:6] if left else '')
    if no_job:
        return (len(left) > 0), msg, info
    return (len(left) == 0), msg, info


def main():
    if '--child' in sys.argv:
        i = sys.argv.index('--child')
        mode = 'launch'
        if '--mode' in sys.argv:
            mode = sys.argv[sys.argv.index('--mode') + 1]
        return child_main(sys.argv[i + 1], sys.argv[i + 2], '--no-job' in sys.argv, mode)

    print('chrome_tree 生命周期自测  JOB_ENABLED=%s CLEAN_ENABLED=%s ADOPT_WINDOW=%ss'
          % (chrome_tree.JOB_ENABLED, chrome_tree.CLEAN_ENABLED, chrome_tree.ADOPT_WINDOW))
    ok_all = True
    results = []

    print('\n① 正常退出（sys.exit → atexit）')
    ok, msg = case_normal_exit()
    print('   %s  %s' % ('PASS' if ok else 'FAIL', msg))
    ok_all &= ok
    results.append(ok)

    print('\n② 父进程被强杀（Job Object 是唯一防线）')
    ok, msg, info2 = case_forced_kill(no_job=False)
    print('   %s  %s' % ('PASS' if ok else 'FAIL', msg))
    ok_all &= ok
    results.append(ok)
    if not ok:
        chrome_tree.kill_tree(None, info2['profile'])

    print('\n③ 阴性对照：同一条强杀 + AL_NO_JOB=1 → 必须**漏**')
    ok3, msg3, info3 = case_forced_kill(no_job=True)
    print('   %s  %s' % ('PASS' if ok3 else 'FAIL —— 阴性侧不漏，说明②的绿是巧合而非机制', msg3))
    ok_all &= ok3
    results.append(ok3)

    print('\n④ 启动前清理（B 层）回收 ③ 漏下的现场')
    killed = chrome_tree.clean_profile(info3['profile'], quiet=True)
    left4 = _residual(info3['profile'])
    ok4 = bool(killed) and not left4
    print('   %s  清掉 %d 个进程，回读残留 %d' % (
        'PASS' if ok4 else 'FAIL', len(killed), len(left4)))
    ok_all &= ok4
    results.append(ok4)
    if left4:
        chrome_tree.kill_tree(None, info3['profile'])

    print('\n⑤ 老写法 Popen + install()（全库仍有 11 个）被强杀 → 也必须 0 残留')
    ok5, msg5, info5 = case_forced_kill(no_job=False, mode='install')
    print('   %s  %s' % ('PASS' if ok5 else 'FAIL —— install() 里没有 A 层，这 11 个探针会漏', msg5))
    ok_all &= ok5
    results.append(ok5)
    if msg5 and '强杀前 0 个进程' in msg5:
        print('   [WARN] 强杀前一个进程都没有 = 假绿灯（浏览器早已自己退出），本条不算数')
        ok_all = False
        results[-1] = False
    if not ok5:
        chrome_tree.kill_tree(None, info5['profile'])

    print('\n判据汇总：① %s / ② %s / ③ %s / ④ %s / ⑤ %s' % tuple(
        'PASS' if v else 'FAIL' for v in results))
    stray = chrome_tree.orphans(os.path.join(ROOT, '.diag'))
    if stray:
        print('\n[WARN] 仍有孤儿浏览器 %d 组（本次自测的旁证）：' % len(stray))
        for prof, pids in stray:
            print('   %s → %d 个进程' % (os.path.basename(prof), len(pids)))
    print('\n[PASS] chrome_tree 生命周期机制成立（A Job Object + B 启动前清理 + C 回读确认）'
          if ok_all else '\n[FAIL] 生命周期机制不成立，见上方 FAIL 行')
    return 0 if ok_all else 1


if __name__ == '__main__':
    sys.exit(main())
