#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 `scripts/git-hooks/` 的正本装成 `.git/hooks/` 的生效副本，并核对没有漂移。

为什么写成脚本（2026-11-01 实测）：AGENTS.md 一直写着"换机器或重新 clone 后必须重装一次"，
但这一步**只靠记性**——本轮接手的这份克隆里 `.git/hooks/` 只有 `.sample`，
两道闸（改代码必须同步文档 / 提交必须交代技能判定）**整整一段时间完全没生效过**，
而文档里读起来像是有闸的。手工 `cp` 还会漏 `chmod`、漏核对是否与正本同步。

    py -3 scripts/install_git_hooks.py           # 装（幂等：已一致就不重复写）
    py -3 scripts/install_git_hooks.py --check   # 只核对：有缺失或与正本不同 -> 退出码 1

退出码: 0 全部就位 / 1 --check 发现缺失或漂移 / 2 正本缺失。
"""
import argparse
import hashlib
import os
import shutil
import stat
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(HERE, 'git-hooks')
HOOKS = ('pre-commit', 'commit-msg')


def _git_dir():
    """用 git 自己问，别手拼 `.git`（子模块/worktree 里 `.git` 是个文件）。"""
    import subprocess
    p = subprocess.run(['git', 'rev-parse', '--git-dir'], cwd=ROOT,
                       capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError((p.stderr or p.stdout).strip() or 'git rev-parse 失败')
    return os.path.abspath(os.path.join(ROOT, p.stdout.strip()))


def _sha(p):
    with open(p, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()


def _exec_ok(p):
    """Windows 上 git 用自带的 sh 跑 hook，不依赖 unix 权限位；这里只做提示性核对。"""
    try:
        m = os.stat(p).st_mode
        return bool(m & stat.S_IXUSR)
    except OSError:
        return False


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--check', action='store_true', help='只核对不安装')
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

    missing_src = [h for h in HOOKS if not os.path.isfile(os.path.join(SRC, h))]
    if missing_src:
        print(f'[FAIL] 正本缺失：{", ".join(missing_src)}（应当在 scripts/git-hooks/ 下）')
        return 2

    try:
        hooks_dir = os.path.join(_git_dir(), 'hooks')
    except Exception as e:
        print(f'[FAIL] 定位不到 .git/hooks：{e}')
        return 2
    os.makedirs(hooks_dir, exist_ok=True)

    bad = []
    for h in HOOKS:
        src = os.path.join(SRC, h)
        dst = os.path.join(hooks_dir, h)
        if not os.path.isfile(dst):
            bad.append(f'{h}：未安装')
            continue
        if _sha(src) != _sha(dst):
            bad.append(f'{h}：与正本不一致（有人改了生效副本，或正本更新后没重装）')
        elif not _exec_ok(dst) and os.name != 'nt':
            bad.append(f'{h}：缺可执行位')

    if a.check:
        for b in bad:
            print(f'  ✗ {b}')
        print(('[FAIL] ' if bad else '[PASS] ') +
              (f'{len(bad)} 个 hook 未就位或已漂移' if bad else '两个 hook 均已就位且与正本一致'))
        return 1 if bad else 0

    for h in HOOKS:
        shutil.copyfile(os.path.join(SRC, h), os.path.join(hooks_dir, h))
        if os.name != 'nt':
            st = os.stat(os.path.join(hooks_dir, h))
            os.chmod(os.path.join(hooks_dir, h), st.st_mode | stat.S_IXUSR)
        print(f'  已装 {h} -> {os.path.relpath(os.path.join(hooks_dir, h), ROOT)}')
    print('[OK] 两个 hook 已就位（正本在 scripts/git-hooks/，改逻辑改正本再跑一次本脚本）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
