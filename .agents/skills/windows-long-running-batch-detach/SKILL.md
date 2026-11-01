---
name: windows-long-running-batch-detach
description: 在 Windows 上用完全脱离宿主的分离进程跑长时本地批处理与回归脚本（数据导出、批量渲染、全量校验、CDP 回归），并正确判定它是否真的跑完。当单轮预计超过约 8 分钟，或出现「completed exit code 0 但输出行异常少」「跑一半没了」「后台任务自己结束」「批量任务超时被杀」时使用。覆盖「子进程/浏览器到底被谁杀的」（宿主超时并不杀进程，真正的孤儿来自会话关闭与强杀，故必须走 Job Object 内核级兜底）、shell 复合命令退出码遮蔽、Start-Process 隐藏窗口重定向、进度行轮询、崩溃/截断/完成的三分法判定。触发词：长时批处理、跑一半断了、后台超时、脱离进程、Start-Process、轮询日志、退出码 0 但没跑完、进程被谁杀了、孤儿进程。
version: 1.1.0
---

# Windows 长时批处理：脱离宿主 + 真实完成判定

## Overview

宿主端命令执行器对单条命令有**输出等待上限**（`initial_wait` 默认 30 秒、最大 600 秒），但**超时不杀进程**——超过等待时间后命令转为后台继续跑，完成时再通知。后台（attached）命令在**会话关闭时**会被终止，这才是长时任务中途消失的主要成因。

⚠️ **本技能早期版本写的是「硬性时长上限，默认 2 分钟，最大 10 分钟，超时静默终止」，已被实测推翻**（2026-10-28）：一条前台命令连续跑了 **909 秒（15 分 10 秒）**、输出期间有持续打印，最终 `exit code 0` 正常完成，**没有**被任何上限打断。⇒ 真上限 ≥15 分钟。

于是（a）不要为了"防超时"去 detach 一个本来能在十几分钟内跑完的任务；（b）**更不要把"任务被杀了"归因成宿主超时**——这个错误归因会让排查方向整个偏掉（真实事故：诊断脚本的浏览器被泄漏成 62 个孤儿进程、CPU 96%、内存剩 2.3GB，根因被写成"超时强杀"，实际是 **`finally`/`atexit` 在强杀下都不执行**，宿主的超时上限根本不是必要条件）。

「进程被杀后怎么收尾」的正确做法不是加 `finally`（它在强杀下同样不执行），而是**进程外/内核级兜底**：Windows 上用 **Job Object + `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`**，父进程一死内核自动杀光 job 内所有进程。实现与五判据自检见本项目的 `scripts/diag/chrome_tree.py` 与 `headless-chrome-cdp-batch-export` 第 10 条。

而 `cmd > log; tail log` 这类复合命令的整体退出码取自最后一条命令（恒 0），于是「completed exit code 0」可以完全掩盖一次中断。本技能规定：长任务怎么真正脱离出去，以及用什么证据判定它跑完了。

## 何时用 / 何时不用

- 用：单轮预计 > 8 分钟；无头浏览器或 CDP 全量回归；> 1000 文件的批量导出或渲染；任何要在结果上签「通过」的校验。
- 不用：秒级到几分钟的命令，直接前台跑并读真实退出码——detach 只会让你丢掉实时输出。

## 规则 1：先估时，再决定执行方式

跑之前先答一句「这一轮预计多少分钟」，依据是历史同类日志耗时、或条目数 × 单条耗时。拿不准按最坏估。超过 8 分钟即按规则 2、3 走——理由是**你看不到实时输出、也读不到干净退出码**，不是"宿主会到点杀它"（见 Overview 的实测更正：超时不杀，只转后台）。

⚠️ 但"转后台"不等于安全：**附着（attached）的后台命令在会话关闭时会被终止**。所以一旦预计要跨越你的会话，就必须 detach（规则 3），并且**收尾靠内核级兜底而不是 `finally`**——强杀下 `finally` 与 `atexit` 都不执行。

## 规则 2：禁止用 shell 复合命令的退出码判定成败

反模式（退出码其实是 `tail` 的，脚本怎么死的看不出来）：

```bash
py scripts/diag/verify.py > .diag/_run.log; echo EXIT=$?; tail .diag/_run.log
```

同理 `a && b`、`a; b`、管道 `a | tee`（取到的是 tee 的码）——末尾命令说了算。要真退出码，只能单独跑那一条并读它自己的退出码，或用规则 3 的 wrapper 读 `ExitCode`。

## 规则 3：完全脱离宿主启动

用 PowerShell `Start-Process`，stdout 与 stderr 各指独立文件（**不能指向同一个**，PowerShell 会直接报错），`-PassThru` 拿到 PID 落盘：

```bash
powershell -NoProfile -Command 'Start-Process -FilePath py -ArgumentList "scripts/diag/verify.py","--all" -WorkingDirectory "D:\proj" -WindowStyle Hidden -RedirectStandardOutput "D:\proj\.diag\_run.log" -RedirectStandardError "D:\proj\.diag\_run.err" -PassThru | ForEach-Object { $_.Id } | Set-Content "D:\proj\.diag\_run.pid"'
```

- `-WindowStyle Hidden` 避免弹控制台；日志路径写绝对路径，相对路径参数才和 `-WorkingDirectory` 对得上。
- PID 必须落盘，否则下一次会话无从判断有没有旧进程在跑。
- detach 后你看不到实时输出、也不能靠宿主中断它——所以规则 6 的进度行是前置条件。

需要真退出码时，用 wrapper 等待后读进程对象（退出码只用来区分「崩了」与「正常结束」，仍不作为完成判据）：

```powershell
$p = Start-Process -FilePath py -ArgumentList "scripts/diag/verify.py" -WorkingDirectory "D:\proj" -WindowStyle Hidden -RedirectStandardOutput "D:\proj\.diag\_run.log" -RedirectStandardError "D:\proj\.diag\_run.err" -PassThru
$p.Id | Set-Content "D:\proj\.diag\_run.pid"
$p.WaitForExit()
$p.ExitCode | Set-Content "D:\proj\.diag\_run.code"
```

## 规则 4：判定「跑完」的唯一依据是脚本自己打印的汇总行

汇总/终判行（如 `总判定: ALL PASS`、`完成 269/269`）是真实可观测状态。以下都是代理指标，**不得单独作为通过证据**：退出码 0、日志行数、文件大小、mtime 停止变化、后台任务状态显示 completed。

因此长任务脚本本身必须：正常结束时打印一条**固定可 grep** 的汇总行（成功与失败都打，用不同字面量）；并以真实退出码退出。

## 规则 5：日志三分法，别把中断读成通过

轮询节奏 60–120 秒一次，每次都是独立的一条短命令（`tail`/`grep` + 查进程），不要在一个 sleep 循环里等：

```bash
grep -c "总判定" .diag/_run.log; tail -3 .diag/_run.log; tail -5 .diag/_run.err
powershell -NoProfile -Command 'Get-Process -Id (Get-Content "D:\proj\.diag\_run.pid") -ErrorAction SilentlyContinue | Select-Object Id,ProcessName'
```

| 汇总行 | 进程 | err 日志 | 结论与处置 |
|---|---|---|---|
| 在 | 已退 | 任意 | 按汇总行内容判定通过/失败 |
| 不在 | 在 | — | 还在跑，继续轮询，报「进行中 + 最后一条进度行」 |
| 不在 | 已退 | 有 traceback | 崩了。报告异常类型 + 最后一条进度行指示跑到第几条 |
| 不在 | 已退 | 干净无 traceback | 被外部截断或杀掉。这一轮**作废**，不得记为通过 |

## 规则 6：长跑必须可重入、按条目推进

- 每条处理完 `print(..., flush=True)` 输出进度行，例如 `[213/269] name`。没有 flush，脱离后日志会长时间空着，你就无法区分「慢」和「死」。
- 按条目独立推进并落盘已完成集合，支持跳过续跑；不要把整轮当原子操作。
- 连接类故障（CDP/WebSocket 的 `WinError 10054`、端口占用、目标页被刷新）在长轮里是**常态而非意外**，脚本侧要能跳过单条继续或明确报断点，而不是整轮崩在 254/269。
- 长跑期间**不得改动被回归的输入**（页面、产物、配置）。改了，这一轮结果即刻作废并如实说明，不要拿旧日志的局部通过交差。
- 重跑前先读 PID 确认旧进程已终止：双进程并发写同一输出目录会静默互相污染。

## 规则 7：判"进程还活着"不要用 `os.kill(pid, 0)` —— Windows 上那是杀

任何"父进程轮询子进程是否结束"的实现（面板、监督脚本、串行 runner）里，最顺手的一句是
`try: os.kill(pid, 0); alive=True / except OSError: alive=False`。
**CPython 在 Windows 上把 `os.kill` 实现成 `OpenProcess + TerminateProcess(handle, sig)`**，
传 0 也一样 —— 它真的会把那个进程终止掉。于是"每 8 秒轮一次状态"的控制台，
第一次轮询就把自己启动的长任务杀了；退出码看着正常，症状是"日志停在半路、状态永远 running"。

```python
def pid_alive(pid):                       # 只读探活
    if os.name != 'nt':
        try:
            os.kill(pid, 0); return True
        except OSError:
            return False
    import ctypes
    k = ctypes.windll.kernel32
    h = k.OpenProcess(0x1000, False, int(pid))       # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return False
    try:
        code = ctypes.c_ulong()
        return bool(k.GetExitCodeProcess(h, ctypes.byref(code))) and code.value == 259  # STILL_ACTIVE
    finally:
        k.CloseHandle(h)
```

⇒ **写完探活必须配一条"任务要跑到自然收尾"的判据**（日志里出现脚本自己打的汇总行）。
只测"进程死了能不能被判出来"永远测不到这条 —— 判活的那一行就是凶手。
同类"拿有副作用的 API 当查询"的坑：`Popen.terminate()` 只杀启动器不杀进程树
（见 `headless-chrome-cdp-batch-export` 第 10 条）。

## 规则 8：detach 只解决"宿主死了"，不解决"子进程死了"

`Start-Process` 让任务脱离宿主，但它自己 spawn 出来的**孙进程**仍归它管，与宿主无关。
一旦任务被强杀（`Stop-Process -Force` / `taskkill /F`）、或因崩溃提前退出，
它留下的浏览器/编码器/渲染器子树就成为孤儿，**而且每一轮都会漏一批**，几小时就能把机器压死。

⇒ 凡是会 spawn 长驻子进程的任务，必须三层齐备（缺任一层都有实测过的失效路径）：

| 层 | 做什么 | 为什么少了它就漏 |
|---|---|---|
| **A 内核级兜底** | Windows **Job Object** + `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` | `finally` / `atexit` 在强杀下**都不执行**，任何进程内清理机制都救不了 |
| **B 启动前清理** | 按子进程的独立资源标识（如 `--user-data-dir`）**精确**匹配清残留 | 上一轮由旧代码启动的残留、以及 A 也兜不到的极端情况 |
| **C 回读确认** | 收尾后回查进程表，判据落**回读**不落 `taskkill` 退出码 | `taskkill /T /F /PID <launcher>` 在 Edge 上是假绿灯（返回 0/128 却一个都不杀） |

两条配套纪律：

- **判据必须有阴性对照**。只跑"强杀后残留 0"证明不了是 A 在起作用 —— 必须再跑一次
  **关掉 A**（环境变量开关）的同一条用例，**阴性侧必须漏**。阳性侧的绿没有区分力是这类修复最常见的假绿灯。
- **"看着已经修好"的写法可能半层都没落地**。本项目实测：58 个调用点迁到统一出口后，
  另有 11 个走老接口 `install(proc)`，而该接口**只注册了 atexit** ⇒ 强杀下 100% 泄漏，
  而它们恰恰因为"有 install"看起来最像已修。⇒ **覆盖面要用代码结构统计（AST）判定，
  不要拿几个典型样本代表全库**；老接口的正确处置是**让它自己升级**（内部也 assign 进 job），
  不是逐个改调用方。
- 判活/枚举一律**先按进程名过滤再匹配命令行**，否则查询会匹配到执行查询的 shell 自己。

## Windows 编码硬约束

`Start-Process` 重定向的 stdout 默认按本地代码页（GBK）写，脚本里任何非 ASCII `print`（哪怕一个勾号 `✓`）都会 `UnicodeEncodeError`，把正常跑完的一轮记成失败——而图像/产物其实已写出。主进程 `sys.stdout.reconfigure(encoding="utf-8")` 加子进程环境 `PYTHONIOENCODING=utf-8`，双保险。细节见 `unity-assetbundle-painting-restore`。

## 向用户报告时

引用可核对的证据：日志实际行数、最后一条进度行、汇总行原文、进程是否存活。**不要**引用「后台任务 completed / exit code 0」当作跑完的证明。截断或作废就直说截断或作废。

## 相关技能（避免重复展开）

- `headless-chrome-cdp-batch-export`：浏览器端批量渲染导出，本技能管宿主端时长与判定。
- `unity-assetbundle-painting-restore`：全量合成的分离进程与编码踩坑细节。
- `safe-pipeline-fix-targeted-rerun`：全量前先小样本验证与零回退闸门。
