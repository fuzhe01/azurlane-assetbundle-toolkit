# -*- coding: utf-8 -*-
"""合并长分叉前，先查「章节号撞车」——只读，不改任何文件（退出码即结论）。

为什么需要它：`docs/TROUBLESHOOTING.md` 的 `## §N` 与 `docs/WORKFLOWS.md` 的 `### WF-N:`
是**全仓唯一的引用坐标**。两条分支各自往后追加时，git 会把「同样位置的追加」判成冲突，
但**编号撞车不会被 git 报出来**：两边都用了 §115，合并后 `WF-30` 就指向两篇不同的流程，
且所有自引用静默错链。上一轮合并 fork 的 97 个提交时就是靠人工 grep 才发现
（§115/§116 与 WF-30/31/32 各撞一次，fork 那边已独立用到 §176 / WF-59）。

三方比对（这才是判据，不靠记忆）：
  base   = `git merge-base` 出来的公共祖先
  ours   = 本分支 HEAD
  theirs = 要并进来的分支
只有「本分支新增」∩「对方新增」的号才是撞车；base 里已有的号两边都在用，不算冲突。

⚠️ **「追加」不算撞号**：`### WF-16 追加（2026-09-28）：…` 是同一流程的续篇，
不是第二个 WF-16。判据是标题号后紧跟 `:` 才算正篇（`### WF-16:`），续篇一律排除；
否则本仓会被自己的续篇样式刷出一堆假撞号（实测 4 个假阳性）。
`## §37` 这类真重复要报，但要分清是**谁带进来的**：base 就有 → 历史遗留不许顺手改
（它的自引用会全炸），只有本分支或对方**新增**的重复才需要处理。

用法:
  py -3 scripts/diag/check_merge_numbering.py                       # 用 HEAD / MERGE_HEAD / merge-base
  py -3 scripts/diag/check_merge_numbering.py --theirs fork/master  # 合并前干跑
  py -3 scripts/diag/check_merge_numbering.py --base 149053b --ours a72fbcf --theirs 1c16cea
  py -3 scripts/diag/check_merge_numbering.py --theirs 1c16cea --worktree   # 合并**未提交**时验自己让号对不对

⚠️ `--worktree` 的意义：合并解完之后、提交之前，`HEAD` 仍是**合并前**那个提交，
所以 `git show HEAD:docs/WORKFLOWS.md` 里还是旧的 `WF-30/31/32`，工具会一直报撞号 ——
那个 FAIL 是**判据读错了对象**，不是你没让号（实测踩过：让号做完了仍然红）。
此时必须用 `--worktree` 让 ours 从**磁盘**读，才能验证让号结果。

退出码: 0 = 无撞号（历史遗留重复只 WARN）；1 = 有撞号或新增重复。
"""
import argparse
import os
import re
import subprocess
import sys

sys.stdout.reconfigure(encoding='utf-8')
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))

# (文件, 正篇编号正则, 编号前缀) —— 新增一个「带唯一编号的长文档」就往这里加一行
TARGETS = [
    ('docs/TROUBLESHOOTING.md', re.compile(r'^## §(\d+)'), '§'),
    ('docs/WORKFLOWS.md', re.compile(r'^### WF-(\d+)[:：]'), 'WF-'),
]


def git(*args):
    r = subprocess.run(['git'] + list(args), cwd=ROOT, capture_output=True, text=True, encoding='utf-8')
    return r.stdout if r.returncode == 0 else None


def ids_at(rev, path, rx, worktree=False):
    if worktree:
        abs_ = os.path.join(ROOT, path)
        if not os.path.exists(abs_):
            return None
        with open(abs_, 'rb') as f:
            text = f.read().decode('utf-8', 'replace').replace('\r\n', '\n')
    else:
        text = git('show', f'{rev}:{path}')
        if text is None:
            return None
    return [int(m.group(1)) for line in text.split('\n') if (m := rx.match(line))]


def dup_of(ids, base_ids):
    """返回 (历史遗留重复, 新增重复)：base 里也有这个号 ⇒ 历史遗留，不许顺手改号。"""
    c = {i: ids.count(i) for i in set(ids)}
    old = sorted(i for i, n in c.items() if n > 1 and i in base_ids)
    new = sorted(i for i, n in c.items() if n > 1 and i not in base_ids)
    return old, new


def check_merged(a, path, rx, tag):
    """合并产物自检（--worktree）：合并 = 两边并集，所以「新增编号」这个词已经失效，
    此时唯一该问的是：**合并产物里有没有重复的标题**，以及重复是继承的还是本分支造出来的。"""
    b = ids_at(a.base, path, rx) or []
    t = ids_at(a.theirs, path, rx) or []
    cur = ids_at(None, path, rx, worktree=True)
    if cur is None:
        print(f'{path}: 工作树里没有该文档，跳过')
        return 0, -1
    bad = 0
    c = {i: cur.count(i) for i in set(cur)}
    dups = sorted(i for i, n in c.items() if n > 1)
    inherited = [i for i in dups if b.count(i) > 1 or t.count(i) > 1]
    created = [i for i in dups if i not in inherited]
    print(f'{path}   [{tag}N] 合并产物')
    print(f'  正篇 {len(cur)} 个，最大 {tag}{max(cur) if cur else "-"}'
          f'；base {len(b)} 个 / theirs {len(t)} 个')
    if inherited:
        print(f'  [WARN] 继承来的重复（base 或对方分支本来就有，**不要顺手改**，改了自引用全炸）: '
              f'{", ".join(f"{tag}{i}" for i in inherited)}')
    if created:
        bad += 1
        print(f'  [FAIL] 合并新造出的重复 {len(created)} 处: {", ".join(f"{tag}{i}" for i in created)}')
        print('         ⇒ 说明并集把同一个号写了两遍：让号没做或做漏了')
    if not dups:
        print(f'  [PASS] 合并产物无重复编号（下一个可用号 {tag}{max(cur) + 1 if cur else 1}）')
    print()
    return bad, max(cur) if cur else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', default=None, help='公共祖先，默认 merge-base(ours, theirs)')
    ap.add_argument('--ours', default='HEAD')
    ap.add_argument('--theirs', default='MERGE_HEAD')
    ap.add_argument('--worktree', action='store_true',
                    help='检查**合并产物**（从磁盘读）而不是三方撞号：合并已解完但未提交时必须用这个')
    a = ap.parse_args()
    if git('cat-file', '-e', f'{a.theirs}^{{commit}}') is None:
        print(f'[FAIL] 解析不到 theirs={a.theirs}（合并态默认 MERGE_HEAD；不在合并中须显式 --theirs）')
        return 1
    if a.base is None:
        a.base = (git('merge-base', a.ours, a.theirs) or '').strip() or None
        if not a.base:
            print(f'[FAIL] 取不到 merge-base({a.ours}, {a.theirs}) —— 指定 --base')
            return 1
    mode = '合并产物自检（ours 从工作树读）' if a.worktree else '合并前三方撞号'
    print(f'base={a.base}  ours={a.ours}  theirs={a.theirs}  [{mode}]\n')
    bad = 0
    for path, rx, tag in TARGETS:
        if a.worktree:
            n, _ = check_merged(a, path, rx, tag)
            bad += n
            continue
        b, o, t = ids_at(a.base, path, rx), ids_at(a.ours, path, rx), ids_at(a.theirs, path, rx)
        if o is None or t is None:
            print(f'{path}: 有一侧没有该文档，跳过'
                  f'（base {len(b or [])} / ours {len(o or [])} / theirs {len(t or [])} 个正篇编号）')
            continue
        b = b or []
        new_o, new_t = set(o) - set(b), set(t) - set(b)
        clash = sorted(new_o & new_t)
        nxt = max(o + t + b) + 1
        print(f'{path}   [{tag}N]')
        print(f'  base   正篇 {len(b)} 个（最大 {tag}{max(b) if b else "-"}）')
        print(f'  ours   新增 {len(new_o)} 个: {", ".join(f"{tag}{i}" for i in sorted(new_o)) or "无"}')
        print(f'  theirs 新增 {len(new_t)} 个: {", ".join(f"{tag}{i}" for i in sorted(new_t)[:8])}'
              f'{" ..." if len(new_t) > 8 else ""}（共 {len(new_t)}）')
        if clash:
            bad += 1
            print(f'  [FAIL] 编号撞车 {len(clash)} 处: {", ".join(f"{tag}{i}" for i in clash)}')
            print(f'         ⇒ 让号方案：本分支侧改成从 {tag}{nxt} 起的连续空号，'
                  f'并把全部自引用一起动（逐条精确串替换 + 命中次数断言）')
        else:
            print(f'  [PASS] 双方新增编号互不相交（下一个可用号 {tag}{nxt}）')
        old_o, dup_o = dup_of(o, b)
        old_t, dup_t = dup_of(t, b)
        if old_o or old_t:
            print(f'  [WARN] base 就有的重复编号（历史遗留，**不要顺手改**，改了自引用全炸）: '
                  f'{", ".join(f"{tag}{i}" for i in sorted(set(old_o) | set(old_t)))}')
        if dup_o:
            bad += 1
            print(f'  [FAIL] ours 新增了重复编号 {len(dup_o)} 处: {", ".join(f"{tag}{i}" for i in dup_o)}')
        if dup_t:
            print(f'  [WARN] theirs 自身新增重复 {len(dup_t)} 处: '
                  f'{", ".join(f"{tag}{i}" for i in dup_t)}（对方历史遗留，本分支不负责改）')
        print()
    if bad:
        print('[FAIL] 合并产物有本分支新造出的重复编号' if a.worktree
              else '[FAIL] 存在编号撞车：先定让号清单再开始解冲突（不要边解边改号）')
        return 1
    print('[PASS] 合并产物无重复编号' if a.worktree else '[PASS] 无编号撞车')
    return 0


if __name__ == '__main__':
    sys.exit(main())
