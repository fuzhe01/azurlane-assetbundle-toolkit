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

4. ⚠️ **父进程被强杀时，进程内的收尾机制全部失效**（2026-10-27 对照实验，已定论）：

   | 退出方式 | `atexit` / `finally` |
   |---|---|
   | 正常退出 | 执行 ✅ |
   | `sys.exit()` | 执行 ✅ |
   | `Stop-Process -Force` / `taskkill /F` 强杀父 python | **不执行** ❌（Chrome 整棵树 18 个进程全存活） |

   宿主命令执行器超时即强杀（SIGKILL 等价物）⇒ 那一刻 **任何"进程内"的收尾都救不了**
   （加 `finally` 同理）。实测事故规模：6 个孤儿实例 / 62 个进程 / 5.83 GB，两个 SwiftShader
   gpu-process 各占 35% CPU，横跨 6 次脚本运行——是每次跑都漏，不是偶发。

## 三层防线

**A. Job Object（内核级，根治）** — `launch()` 自动启用
`CreateJobObjectW` + `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`，子进程以 `CREATE_BREAKAWAY_FROM_JOB`
起来后立刻 `AssignProcessToJobObject`。父进程一死（含被强杀）内核关闭 job 最后一个句柄
→ job 内**所有**进程被杀光。**不依赖 python 执行任何代码**。纯 ctypes，无需 pywin32。

⚠️ Chromium/Edge 启动时会**重新孵化**浏览器主进程（原 launcher 早退、主进程换父），
所以只 assign 一次抓不全。`launch()` 另起一个**有限时长**的守护线程，把随后出现的同 profile
进程一并拉进 job（实测见 `scripts/diag/chrome_lifecycle_selftest.py`）。

**B. 启动前清孤儿（进程外兜底，必做）** — `launch()` 自动执行
同一个 `--user-data-dir` 若还有上一轮活着的浏览器，除了吃 CPU，**Chrome 还会复用它并忽略你
新传的 URL**（探针于是连到旧页面 ⇒「我明明改了也部署了，结果还是旧的」这类假矛盾）。
按 **profile 全路径精确匹配**清理，绝不按进程名全杀。

**C. 整树收尾 + 回读验证** — `kill_tree()` / `install()` 的 atexit
`TerminateJobObject` → `taskkill /T /F` → 按 profile 回读确认；判据落在回读，不落在退出码。

## 用法（一行，把 Popen 整体换成 launch）

    PORT, PROFILE = cdp_slot.slot(ROOT, 'tag')
    proc = chrome_tree.launch([CHROME, '--headless=new', f'--remote-debugging-port={PORT}',
                               f'--user-data-dir={PROFILE}', url],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

`launch(cmd, **popen_kw)` 的参数形状与 `Popen` 完全一致，并自动完成 A+B+C。
`install(proc)` 保留作兼容（老调用点不必改），但它是在 Popen **之后**才调用，
拿不到 breakaway 也来不及做启动前清理 ⇒ **新代码/批量迁移一律用 `launch()`**。

profile 名 = `.diag/chrome_<tag>_<pid>`，每进程唯一，所以"按 profile 杀"永远碰不到并发会话。

## 排查用环境变量

    AL_NO_JOB=1      关掉 A（只留 B+C）——**仅用于自检的阴性对照**，正常跑别设
    AL_NO_CLEAN=1    关掉 B
"""
import atexit
import ctypes
import ctypes.wintypes as wt
import os
import subprocess
import sys
import threading
import time

# 只认这两家（本项目用 Edge 当 Chromium 替身，见 TROUBLESHOOTING §122）；
# 不要写成 `Name like '%chrome%'`：那会匹配到别的 Chromium 壳。
_PS_LIST = (
    "Get-CimInstance Win32_Process -Filter \"Name='msedge.exe' or Name='chrome.exe'\" | "
    "ForEach-Object { \"{0}`t{1}`t{2}\" -f $_.ProcessId, $_.ParentProcessId, $_.CommandLine }"
)

# ---------------------------------------------------------------------------
# Job Object（A：内核级兜底）
# ---------------------------------------------------------------------------
IS_WIN = os.name == 'nt'

JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
JobObjectExtendedLimitInformation = 9
CREATE_BREAKAWAY_FROM_JOB = 0x01000000
PROCESS_SET_QUOTA = 0x0100
PROCESS_TERMINATE = 0x0001

JOB_ENABLED = IS_WIN and os.environ.get('AL_NO_JOB') not in ('1', 'true', 'yes')
CLEAN_ENABLED = os.environ.get('AL_NO_CLEAN') not in ('1', 'true', 'yes')

# launch() 之后多久算「启动阶段结束」——Chromium 会在这段窗口里重新孵化主进程。
ADOPT_WINDOW = float(os.environ.get('AL_ADOPT_WINDOW', '12'))


class _IO_COUNTERS(ctypes.Structure):
    _fields_ = [('ReadOperationCount', ctypes.c_ulonglong),
                ('WriteOperationCount', ctypes.c_ulonglong),
                ('OtherOperationCount', ctypes.c_ulonglong),
                ('ReadTransferCount', ctypes.c_ulonglong),
                ('WriteTransferCount', ctypes.c_ulonglong),
                ('OtherTransferCount', ctypes.c_ulonglong)]


class _BASIC_LIMIT(ctypes.Structure):
    _fields_ = [('PerProcessUserTimeLimit', ctypes.c_longlong),
                ('PerJobUserTimeLimit', ctypes.c_longlong),
                ('LimitFlags', wt.DWORD),
                ('MinimumWorkingSetSize', ctypes.c_size_t),
                ('MaximumWorkingSetSize', ctypes.c_size_t),
                ('ActiveProcessLimit', wt.DWORD),
                ('Affinity', ctypes.c_size_t),
                ('PriorityClass', wt.DWORD),
                ('SchedulingClass', wt.DWORD)]


class _EXT_LIMIT(ctypes.Structure):
    _fields_ = [('BasicLimitInformation', _BASIC_LIMIT),
                ('IoInfo', _IO_COUNTERS),
                ('ProcessMemoryLimit', ctypes.c_size_t),
                ('JobMemoryLimit', ctypes.c_size_t),
                ('PeakProcessMemoryUsed', ctypes.c_size_t),
                ('PeakJobMemoryUsed', ctypes.c_size_t)]


if IS_WIN:
    _k32 = ctypes.WinDLL('kernel32', use_last_error=True)
    _k32.CreateJobObjectW.restype = wt.HANDLE
    _k32.CreateJobObjectW.argtypes = [wt.LPVOID, wt.LPCWSTR]
    _k32.SetInformationJobObject.restype = wt.BOOL
    _k32.SetInformationJobObject.argtypes = [wt.HANDLE, ctypes.c_int, wt.LPVOID, wt.DWORD]
    _k32.AssignProcessToJobObject.restype = wt.BOOL
    _k32.AssignProcessToJobObject.argtypes = [wt.HANDLE, wt.HANDLE]
    _k32.OpenProcess.restype = wt.HANDLE
    _k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
    _k32.GetExitCodeProcess.restype = wt.BOOL
    _k32.GetExitCodeProcess.argtypes = [wt.HANDLE, ctypes.POINTER(wt.DWORD)]
    _k32.TerminateJobObject.restype = wt.BOOL
    _k32.TerminateJobObject.argtypes = [wt.HANDLE, wt.UINT]
    _k32.CloseHandle.restype = wt.BOOL
    _k32.CloseHandle.argtypes = [wt.HANDLE]

_JOBS = {}          # pid -> job 句柄（保活：句柄在，job 才在；句柄关则成员全灭）
_JOB_LOCK = threading.Lock()
_WARNED = set()


def _warn_once(key, msg):
    if key not in _WARNED:
        _WARNED.add(key)
        print('[chrome_tree] ⚠️ ' + msg, file=sys.stderr, flush=True)


def _new_job():
    """建一个 KILL_ON_JOB_CLOSE 的匿名 job 并设好 limit；失败返回 None。"""
    if not JOB_ENABLED:
        return None
    try:
        h = _k32.CreateJobObjectW(None, None)
        if not h:
            return None
        info = _EXT_LIMIT()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not _k32.SetInformationJobObject(h, JobObjectExtendedLimitInformation,
                                            ctypes.byref(info), ctypes.sizeof(info)):
            _k32.CloseHandle(h)
            return None
        return h
    except Exception:
        return None


def _assign(hjob, pid):
    if not hjob:
        return False
    h = _k32.OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, False, int(pid))
    if not h:
        return False
    try:
        return bool(_k32.AssignProcessToJobObject(hjob, h))
    except Exception:
        return False
    finally:
        _k32.CloseHandle(h)


def _pid_alive(pid):
    """只读探活。⚠️ 不用 os.kill(pid, 0) —— Windows 上那会真的把进程杀掉。"""
    if not IS_WIN:
        return True
    h = _k32.OpenProcess(0x1000, False, int(pid))       # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return False
    try:
        code = wt.DWORD()
        return bool(_k32.GetExitCodeProcess(h, ctypes.byref(code))) and code.value == 259
    finally:
        _k32.CloseHandle(h)


def _run_ps(script, timeout=60):
    """跑一小段 PowerShell 并取 stdout。失败返回 ''（调用方按"查不到"处理）。"""
    try:
        r = subprocess.run(['powershell', '-NoProfile', '-Command', script],
                           capture_output=True, text=True, errors='replace', timeout=timeout)
        return r.stdout or ''
    except Exception:
        return ''


def _profile_of_cmdline(cmdline):
    """从命令行里取出 `--user-data-dir` 的值（精确匹配用；不是子串匹配）。"""
    if not cmdline:
        return None
    i = cmdline.lower().find('--user-data-dir=')
    if i < 0:
        return None
    rest = cmdline[i + len('--user-data-dir='):]
    # 引号包裹时取到闭合引号，否则取到第一个空白
    if rest[:1] in ('"', "'"):
        q = rest[0]
        end = rest.find(q, 1)
        return rest[1:end] if end > 0 else rest[1:]
    return rest.split()[0] if rest.split() else None


def _same_profile(a, b):
    if not a or not b:
        return False
    na = os.path.normcase(os.path.normpath(a.rstrip('\\/') or '/'))
    nb = os.path.normcase(os.path.normpath(b.rstrip('\\/') or '/'))
    return na == nb


def _parse_ps_rows(out):
    """把 `pid<TAB>ppid<TAB>cmdline` 解析成 [(pid, ppid, cmdline)]。"""
    rows = []
    for ln in (out or '').splitlines():
        pid_s, tab, rest = ln.partition('\t')
        if not tab or not pid_s.strip().isdigit():
            continue
        ppid_s, tab2, cmd = rest.partition('\t')
        if not tab2:
            continue
        try:
            rows.append((int(pid_s), int(ppid_s.strip() or 0), cmd))
        except ValueError:
            continue
    return rows


def _adopt(hjob, profile, window=None):
    """把随后出现的同 profile 浏览器进程一起拉进 job。

    Chromium 启动时会**重新孵化**主进程：`Popen` 拿到的 launcher 早退，真正的主进程换了父，
    所以「assign 一次」只覆盖启动器那一支。这里在有限窗口内反复扫同 profile 的进程并补 assign。
    ⚠️ 只在启动窗口内跑，不是常驻轮询——避免长跑探针反复花 1 秒查进程表。
    """
    if not hjob or not profile:
        return 0
    deadline = time.time() + (ADOPT_WINDOW if window is None else window)
    adopted = 0
    seen = set()
    while time.time() < deadline:
        for pid, _ppid, cmd in _parse_ps_rows(_run_ps(_PS_LIST)):
            if pid in seen:
                continue
            if _same_profile(_profile_of_cmdline(cmd), profile):
                seen.add(pid)
                if _assign(hjob, pid):
                    adopted += 1
        time.sleep(0.5)
    return adopted


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
    """命令行 `--user-data-dir` **精确等于** 该 profile 的浏览器进程 pid 列表。

    ⚠️ 只做子串匹配会把 `chrome_x_1` 误命中 `chrome_x_10`，于是清理 A 时杀掉 B ——
    并发会话的浏览器就这么被杀掉过。一律按 `--user-data-dir=` 取值后精确比对。
    """
    if not profile_path:
        return []
    return [pid for pid, _ppid, cmd in _parse_ps_rows(_run_ps(_PS_LIST))
            if _same_profile(_profile_of_cmdline(cmd), profile_path)]


def processes_for_profile(profile_path):
    """同 profile 的浏览器进程 [(pid, ppid, cmdline)]（含 owner 归属判断需要的 ppid）。"""
    if not profile_path:
        return []
    return [r for r in _parse_ps_rows(_run_ps(_PS_LIST))
            if _same_profile(_profile_of_cmdline(r[2]), profile_path)]


def clean_profile(profile, quiet=False, settle=8.0):
    """B：启动**之前**按 profile 清理上一轮残留。返回被杀掉的 pid 列表。

    为什么必须有这一层：A（Job Object）在内核级兜住了「父进程被杀」，但兜不住
    「job 句柄随进程一起消失之后才孵化出来的进程」、也兜不住**上一轮由旧代码启动**的残留。
    而且更隐蔽的后果不是泄漏本身：Chrome 发现同 profile 已有实例会**复用旧实例并忽略你新传的 URL**，
    于是新探针静默附着到上一轮的页面上（"我明明改了却还是旧行为"）。
    ⇒ 每次启动前清一次，是「预防假绿灯」和「防泄漏」共用的同一条动作。
    """
    if not CLEAN_ENABLED or not profile:
        return []
    killed = []
    left = pids_using(profile)
    if left:
        for p in left:
            subprocess.call(['taskkill', '/T', '/F', '/PID', str(p)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            killed.append(p)
        deadline = time.time() + settle
        left = pids_using(profile)
        while left and time.time() < deadline:
            time.sleep(0.4)
            left = pids_using(profile)
        if left and not quiet:
            _warn_once('clean:' + str(profile),
                       '启动前清理后仍有残留 pid %s（profile=%s）' % (left[:8], profile))
    if killed and not quiet:
        print('[chrome_tree] 启动前清掉上一轮残留 %d 个进程（profile=%s）'
              % (len(killed), profile), file=sys.stderr, flush=True)
    return killed


def _close_all_jobs():
    """进程正常退出时先关 job 句柄：KILL_ON_JOB_CLOSE 让内核把成员全杀光。"""
    with _JOB_LOCK:
        jobs = list(_JOBS.items())
        _JOBS.clear()
    for _pid, h in jobs:
        try:
            _k32.TerminateJobObject(h, 1)
        except Exception:
            pass
        try:
            _k32.CloseHandle(h)
        except Exception:
            pass


atexit.register(_close_all_jobs)


def orphans(scope=None):
    """扫出「profile 里含 scope 但 owner 进程已死」的浏览器进程 —— 供收尾自检用。

    owner 判据：profile 名形如 `chrome_<tag>_<pid>`，取末尾数字当 owner pid；仅当该 pid
    **已不存在**时才算孤儿。owner 还活着的树属于别的会话正在正常使用，绝不动它。
    """
    rows = _parse_ps_rows(_run_ps(_PS_LIST))
    groups = {}
    for pid, ppid, cmd in rows:
        prof = _profile_of_cmdline(cmd)
        if not prof:
            continue
        if scope and scope.lower() not in prof.lower():
            continue
        groups.setdefault(os.path.normcase(os.path.normpath(prof)), []).append((pid, ppid, cmd))
    out = []
    for prof, members in groups.items():
        name = os.path.basename(prof.rstrip('\\/') or prof)
        tail = name.rsplit('_', 1)[-1]
        owner = int(tail) if tail.isdigit() else None
        if owner is not None and _pid_alive(owner):
            continue
        out.append((prof, [m[0] for m in members]))
    return out


def kill_tree(pid, profile=None, verify=True, settle=6.0):
    """杀掉这条浏览器进程树。`pid` 用 Popen 的 Objects 化传参（Popen 对象也行）；`profile` 兜底。

    返回 `(ok, remaining)`：ok=True 表示**回读确认**没有残留；remaining 是残留 pid 列表。

    ⚠️ **回读必须带 settle 宽限期**：`taskkill /F` 是**异步**的，发完信号进程仍可能在
    进程表里停留一小会儿（实测 atexit 回读抓到 2 个"残留"，几秒后自己消失）。
    掐在发信号后立刻回读会把「正在退出」误报成「漏杀」，于是这个警示行失去意义
    （天天报假残留 = 又一次"判据没有被信"）。所以轮询到清空为止，最多 settle 秒。

    ⚠️ **`taskkill /T /F /PID <launcher>` 在 Edge 上是假绿灯**（TROUBLESHOOTING §156 形态一）：
    launcher 早已退出、父子链断开，命令返回 0/128 却一个都不杀。⇒ 判据只能落在 profile 回读。
    """
    if pid is not None and not isinstance(pid, int):
        proc = pid
        pid = getattr(proc, 'pid', None)
        profile = profile or profile_of(proc)
        try:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(3)
                except Exception:
                    pass
        except Exception:
            pass
    if pid:
        hjob = _JOBS.pop(pid, None)
        if hjob:
            try:
                _k32.TerminateJobObject(hjob, 1)
            except Exception:
                pass
            try:
                _k32.CloseHandle(hjob)
            except Exception:
                pass
        subprocess.call(['taskkill', '/T', '/F', '/PID', str(pid)],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if not profile:
        return True, []
    left = pids_using(profile)
    for p in left:
        subprocess.call(['taskkill', '/T', '/F', '/PID', str(p)],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if not verify:
        return True, left
    deadline = time.time() + settle
    left = pids_using(profile)
    while left and time.time() < deadline:
        time.sleep(0.4)
        left = pids_using(profile)
    return (not left), left


def _attach_job(proc, profile=None, window=None):
    """把**已经启动**的进程拉进一个 KILL_ON_JOB_CLOSE 的 job，并补 assign 后续孵化出来的同 profile 进程。

    为什么要有这个函数（2026-10-28 补漏）：`launch()` 建 `Popen` 时能带 `CREATE_BREAKAWAY_FROM_JOB`，
    但 `install(proc)` 是**在 Popen 之后**才被调用的老接口 —— 它拿不到 creationflags，只能事后 assign。
    事后 assign 同样有效（`AssignProcessToJobObject` 不要求进程是 job 的创建子进程），差别只在
    "父进程若已被放进某个不允许 breakaway 的 job，assign 可能失败"。若不在这里补做 A，
    那 11 个只用 `install()` 的探针在宿主强杀下**照样整棵树泄漏** —— A 层等于没落地。
    """
    if not JOB_ENABLED:
        return None
    hjob = _new_job()
    if not hjob:
        return None
    pid = getattr(proc, 'pid', proc)
    ok = _assign(hjob, pid)
    with _JOB_LOCK:
        _JOBS[pid] = hjob
    if ok:
        t = threading.Thread(target=_adopt, args=(hjob, profile, window), daemon=True)
        t.start()
    else:
        _warn_once('assign:%s' % pid,
                   'Job Object assign 失败（pid=%s），该进程只能靠 C 层清理' % pid)
    return hjob


def launch(cmd, profile=None, **popen_kw):
    """启动一个无头浏览器，**自动**做齐 A+B+C，返回 Popen。

    参数形状与 `subprocess.Popen(cmd, **kw)` 一致（`cmd` 是 argv 列表，kw 原样透传）。
    自动依次完成：
      B  启动前按 profile 清掉上一轮残留（防泄漏 + 防"复用旧实例忽略新 URL"）
      A  建 KILL_ON_JOB_CLOSE 的 Job Object 并把浏览器进程（含重新孵化的主进程）拉进去
         → 本进程被强杀（Stop-Process -Force / taskkill /F / 宿主超时）时，内核照样杀光整棵树
      C  注册 atexit 整树清理 + profile 回读确认（正常与异常退出路径）
    """
    profile = profile or _profile_of_cmdline(' '.join(
        a.decode() if isinstance(a, bytes) else str(a) for a in cmd))
    if CLEAN_ENABLED and profile:
        clean_profile(profile)
    hjob = _new_job()
    flags = int(popen_kw.pop('creationflags', 0) or 0)
    # 父进程若已在某个不允许 breakaway 的 job 里，带这个 flag 会被拒；退回去重试。
    try:
        proc = subprocess.Popen(cmd, creationflags=flags | CREATE_BREAKAWAY_FROM_JOB,
                                **popen_kw)
    except OSError:
        proc = subprocess.Popen(cmd, creationflags=flags, **popen_kw)
        if hjob:
            _warn_once('breakaway', '父进程 job 不允许 breakaway，Job Object 兜底降级为普通程度')
    if hjob:
        with _JOB_LOCK:
            _JOBS[proc.pid] = hjob
        if _assign(hjob, proc.pid):
            t = threading.Thread(target=_adopt, args=(hjob, profile), daemon=True)
            t.start()
        else:
            _warn_once('assign', 'Job Object assign 失败（pid=%s），该类进程只能靠 C 层清理'
                       % proc.pid)
    install(proc, profile)
    return proc



def install(proc, profile=None):
    """给**已经启动**的进程注册整树清理，原样返回 proc。

    三层一起给（2026-10-28 起）：A 事后 assign 进 Job Object + C atexit 整树清理。
    ⚠️ 只有 C 是不够的 —— `atexit` 在宿主强杀（`Stop-Process -Force` / `taskkill /F`）下
    **不执行**，实测漏掉整棵 18~24 个进程的浏览器树。所以 A 必须在 install 里也落地，
    否则老的 `install(proc)` 调用点等于没有内核级兜底。
    """
    prof = profile or profile_of(proc)
    _attach_job(proc, prof)

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
