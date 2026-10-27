# -*- coding: utf-8 -*-
"""headless 浏览器的可靠清理——补上 `proc.terminate()` / `taskkill /T` 覆盖不到的三个洞。

1. **只杀启动器**：`Popen([CHROME, ...])` 拿到的 pid 下面还挂着 crashpad/gpu/网络/若干 renderer，
   `terminate()` 不打整棵树，SwiftShader 软 GPU 的渲染进程会**继续活着吃 CPU 和内存**。
2. **异常时压根不执行**：多数诊断脚本把 `proc.terminate()` 写在最后一行，脚本一抛异常
   （典型：`RuntimeError: Execution context was destroyed`）就永远走不到那一行。
3. ⚠️ **`taskkill /T /F /PID <launcher>` 对 Edge 会「成功但没杀」**（2026-10-27 实测）：
   `Popen` 返回的 pid 常常只是一个**已退出的启动器**，用户数据目录已交给一个**重新孵化的
   主进程**，于是 `/T` 顺着一棵已经断掉的祖谱走，杀不到任何人。
   实测：`taskkill /T /F` 退出码 0、控制台无输出，而同一 profile 下**20 个 msedge 进程全部存活**，
   探针进程退出数分钟后浏览器仍在跑（280MB）。**返回码在这里是假绿灯。**

所以判据不能落在 `taskkill` 的退出码上，要落在**回读**上：杀完再查一次同一 profile 还有没有进程。

用法（一行）：
    PORT, PROFILE = cdp_slot.slot(ROOT, 'tag')
    proc = chrome_tree.install(subprocess.Popen([...'--user-data-dir=' + PROFILE...]))

`install()` 会从 `proc.args` 自动认出自己的 `--user-data-dir`，无需改调用点；
atexit 注册后**异常退出也会清理**。profile 名 = `.diag/chrome_<tag>_<pid>`，每个进程唯一，
所以"按 profile 杀"永远不会碰到别的会话的浏览器（**不按进程名杀**）。
"""
import atexit
import subprocess
import sys
import time

# 只认这两家（本项目用 Edge 当 Chromium 替身，见 TROUBLESHOOTING §122）；
# 不要写成 `Name like '%chrome%'`：那会匹配到别的 Chromium 壳。
_PS_LIST = (
    "Get-CimInstance Win32_Process -Filter \"Name='msedge.exe' or Name='chrome.exe'\" | "
    "ForEach-Object { \"{0}`t{1}\" -f $_.ProcessId, $_.CommandLine }"
)


def _run_ps(script, timeout=60):
    """跑一小段 PowerShell 并取 stdout。失败返回 ''（调用方按"查不到"处理）。"""
    try:
        r = subprocess.run(['powershell', '-NoProfile', '-Command', script],
                           capture_output=True, text=True, timeout=timeout)
        return r.stdout or ''
    except Exception:
        return ''


def profile_of(proc):
    """从 Popen 的参数里认回 `--user-data-dir`（清理时唯一安全的判据）。"""
    args = getattr(proc, 'args', None)
    if isinstance(args, (bytes, str)):
        args = [args]
    for a in args or []:
        if isinstance(a, bytes):
            try:
                a = a.decode('utf-8', 'replace')
            except Exception:
                continue
        s = str(a)
        if s.startswith('--user-data-dir='):
            return s.split('=', 1)[1].strip('"').rstrip('\\/')
    return None


def pids_using(profile_path):
    """当前命令行里引用了该 user-data-dir 的浏览器进程 pid 列表。"""
    if not profile_path:
        return []
    want = profile_path.lower()
    out = _run_ps(_PS_LIST)
    pids = []
    for ln in out.splitlines():
        pid, tab, cmd = ln.partition('\t')
        if not tab or not pid.strip().isdigit():
            continue
        if want in cmd.lower():
            pids.append(int(pid))
    return pids


def kill_tree(pid, profile=None, verify=True, settle=6.0):
    """杀掉这条浏览器进程树。`pid` 用 Popen 的；`profile` 给 user-data-dir 兜底。

    返回 `(ok, remaining)`：ok=True 表示**回读确认**没有残留；remaining 是残留 pid 列表。
    单给 `pid` 时（老的调用点）退化成一棵树的 taskkill，不做回读，`ok` 恒 True——
    但所有走过 `install()` 的脚本在 atexit 里都会带上 profile 再杀一次。

    ⚠️ **回读必须带 settle 宽限期**：`taskkill /F` 是**异步**的，发完信号进程仍可能在
    进程表里停留一小会儿（实测 `install()` 的 atexit 回读抓到 2 个"残留"，几秒后自己消失）。
    掐在发信号后立刻回读会把「正在退出」误报成「漏杀」，于是这个警示行失去意义
    （天天报假残留 = 又一次"判据没有被信"）。所以轮询到清空为止，最多 settle 秒。
    """
    if pid:
        subprocess.call(['taskkill', '/T', '/F', '/PID', str(pid)],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if not profile:
        return True, []
    left = pids_using(profile)
    for p in left:
        subprocess.call(['taskkill', '/F', '/PID', str(p)],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if not verify:
        return True, left
    deadline = time.time() + settle
    left = pids_using(profile)
    while left and time.time() < deadline:
        time.sleep(0.4)
        left = pids_using(profile)
    return (not left), left


def install(proc, profile=None):
    """注册 atexit 整树清理（异常退出也会执行），原样返回 proc。"""
    prof = profile or profile_of(proc)

    def _cleanup():
        ok, left = kill_tree(proc.pid, prof)
        if not ok:
            # 不静默：漏杀是「假绿灯」的同族问题，必须让人看得见（且不抛异常打扰退出）。
            print('[chrome_tree] 清理后仍有残留 pid %s（profile=%s）' % (left[:8], prof),
                  file=sys.stderr)

    atexit.register(_cleanup)
    return proc


def sweep(profile, label=''):
    """收尾用：只按 profile 杀一次并回读，给"清理已泄漏的浏览器"这类一次性动作调用。"""
    ok, left = kill_tree(None, profile)
    print('[chrome_tree] %s%s → %s' % (label or 'sweep', (' ' + profile) if profile else '',
                                       '已杀净' if ok else ('残留 %s' % left[:8])))
    return ok, left
