# -*- coding: utf-8 -*-
"""监视 copilot chat 的工作是否结束，结束时弹窗提醒。

背景（2026-10-25）：用户指出 copilot chat 正在同一工作区执行任务，
要求等它结束再动手，避免冲突。实测它的活动信号：
  · 写 scripts/**（如 scripts/diag/l2d_segtype_audit.py）
  · 产出 .diag/frames/*.png（逐帧渲染）
  · 写 Output/gallery_v2/_*.html（可视化探针页）
  · 拉起 msedge --remote-debugging-port（CDP 驱动，实测 14 个进程）

判据设计（为什么不能只看「无文件写入」）：
  实测它两次写入之间有 4~5 分钟间隙（03:43:31 → 03:48:24），
  单次短采样会把间隙误判成「已结束」。故用两条组合判据：
    A. 「产出」（scripts / frames / 探针页）连续 QUIET_SEC 秒无新增，且 CDP 进程 <= 2
    B. 或连续 HARD_SEC 秒无新增（即使有残留 Chrome 进程）

  排除 chrome_*/__pycache__/.git：Chrome 在后台会持续写 profile 缓存，
  把它算进活动会导致永远判不出结束（这是本脚本最关键的排除项）。

弹窗用 MessageBoxW 但跑在独立线程，不阻塞监视循环。

用法：
  py -3 scripts/diag/monitor_copilot_idle.py            # 默认 270s/420s 阈值
  py -3 scripts/diag/monitor_copilot_idle.py --quiet 180 --hard 300
"""
import argparse
import ctypes
import json
import os
import subprocess
import sys
import threading
import time

sys.stdout.reconfigure(encoding='utf-8')

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))

# 只统计这些「业务产出」路径——它们是 copilot 真实工作的痕迹
WATCH_DIRS = [
    os.path.join(ROOT, 'scripts'),
    os.path.join(ROOT, '.diag', 'frames'),
    os.path.join(ROOT, 'Output', 'gallery_v2'),
    os.path.join(ROOT, 'gallery_src'),
    os.path.join(ROOT, 'docs'),
    os.path.join(ROOT, '.agents'),
]
WATCH_FILES = [
    os.path.join(ROOT, 'PROJECT_STATUS.md'),
]

# 必须排除：Chrome profile 后台缓存、Python 字节码、git 内部
EXCLUDE_RE = ('chrome_', '__pycache__', '\\.git\\', '/.git/',
              'pipeline', 'cleanup', '_bak')


def newest_mtime():
    """返回 watch 范围内最新的文件修改时间（epoch 秒）。"""
    best = 0.0
    for base in WATCH_DIRS:
        if not os.path.isdir(base):
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            low = dirpath.replace('/', '\\').lower()
            if any(x.lower() in low for x in ('\\chrome_', '__pycache__', '\\.git')):
                continue
            for fn in filenames:
                if any(x in fn for x in EXCLUDE_RE):
                    continue
                fp = os.path.join(dirpath, fn)
                try:
                    m = os.path.getmtime(fp)
                    if m > best:
                        best = m
                except OSError:
                    pass
    for fp in WATCH_FILES:
        try:
            m = os.path.getmtime(fp)
            if m > best:
                best = m
        except OSError:
            pass
    return best


def cdp_processes():
    """被 CDP 驱动的 msedge 主进程数（有 remote-debugging-port 且非子进程）。"""
    try:
        out = subprocess.run(
            ['powershell', '-NoProfile', '-Command',
             "(Get-CimInstance Win32_Process -Filter \"Name='msedge.exe'\" | "
             "Where-Object { $_.CommandLine -like '*remote-debugging-port*' -and "
             "$_.CommandLine -notlike '*--type=*' } | Measure-Object).Count"],
            capture_output=True, text=True, timeout=40).stdout.strip()
        return int(out or 0)
    except Exception:  # noqa: BLE001
        return -1


def popup(title, text):
    """非阻塞弹窗（独立线程，主循环不受影响）。"""
    def _show():
        try:
            MB_ICONINFO = 0x40
            MB_TOPMOST = 0x40000
            ctypes.windll.user32.MessageBoxW(0, text, title, MB_ICONINFO | MB_TOPMOST)
        except Exception:  # noqa: BLE001
            pass
    threading.Thread(target=_show, daemon=False).start()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--quiet', type=int, default=270,
                    help='产出连续无变化多少秒 → 判定结束（需同时 CDP<=2）')
    ap.add_argument('--hard', type=int, default=420,
                    help='产出连续无变化多少秒 → 无条件判定结束')
    ap.add_argument('--poll', type=int, default=20, help='采样间隔秒')
    args = ap.parse_args()

    print('[monitor] 工作区: %s' % ROOT, flush=True)
    print('[monitor] 阈值: quiet=%ds(+CDP<=2)  hard=%ds  轮询=%ds'
          % (args.quiet, args.hard, args.poll), flush=True)

    last = newest_mtime()
    now = time.time()
    quiet_since = time.time() if (now - last) < args.quiet else (last)
    # 若已经静默超过阈值，立刻可判
    print('[monitor] 初始最新写入: %s（距今 %.0f 秒）'
          % (time.strftime('%H:%M:%S', time.localtime(last)), now - last), flush=True)

    n = 0
    while True:
        time.sleep(args.poll)
        n += 1
        cur = newest_mtime()
        cdp = cdp_processes()
        now = time.time()
        if cur > last:
            last = cur
            quiet_since = now
            print('[monitor %02d] 新写入 %s  剩余静默计时 %.0fs  CDP=%s'
                  % (n, time.strftime('%H:%M:%S', time.localtime(cur)),
                     args.hard, cdp), flush=True)
            continue
        quiet = now - max(last, quiet_since)
        print('[monitor %02d] 无新写入 %s  已静默 %.0fs  CDP=%s'
              % (n, time.strftime('%H:%M:%S', time.localtime(last)), quiet, cdp),
              flush=True)

        done = False
        why = ''
        if quiet >= args.hard:
            done = True
            why = '静默 %ds 超过硬阈值 %ds' % (quiet, args.hard)
        elif quiet >= args.quiet and 0 <= cdp <= 2:
            done = True
            why = '静默 %ds 且 CDP 进程仅 %d 个' % (quiet, cdp)

        if done:
            msg = (
                'copilot chat 的任务看起来已结束。\n\n'
                '判据：%s\n'
                '最后写入：%s\n'
                '检查时刻：%s\n\n'
                '现在可以安全开始：\n'
                '  1) 换装相关脚本入库\n'
                '  2) R3 热区命中修复 / R4 写入验证 / R6 真实点击验收'
            ) % (why,
                 time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(last)),
                 time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(now)))
            print('[monitor] === 判定结束：%s ===' % why, flush=True)
            print(json.dumps({'done': True, 'why': why,
                              'last_write': last, 'checked_at': now},
                             ensure_ascii=False), flush=True)
            popup('工作区已空闲 — 可以开工了', msg)
            print('[monitor] 已弹窗提醒。退出。', flush=True)
            return 0


if __name__ == '__main__':
    sys.exit(main())
