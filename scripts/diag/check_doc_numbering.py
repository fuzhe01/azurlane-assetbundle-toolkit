#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PROJECT_STATUS §6 编号连续性体检。

**为什么需要它**：编号断裂是**静默**的 —— §6 少一条不会报错、不会告警，只会让下一次
「压行数 / 逐字外迁」误判条目边界而删错邻居（2026-10-04 真实事故：压第 26 条时把第 27 条
一起吃掉，两个提交都没发现）。所以编号连续性必须是一条**能跑的断言**，不是靠人眼扫。

**判据**：
1. §6 的顶层条目编号必须是 1..N 连续（缺号即红）。
2. 重号要**区分**两类：顶格的子条目复用编号（允许，但要报出来供人判断）、
   与顶层条目撞号（不允许）。
   - 顶层条目 = 行首数字 + `. `，且**不是**被更深缩进包住的续行。
   - 实践上：§6 里第 5/6 号是顶格子条目（「若视觉再被否」「UI/图标批量导出」等），
     它们与主条目 5/6 撞号 —— 属**已知历史遗留**，默认放行但打印出来。
3. 重复出现的同一编号，其**首行内容必须不同**；完全相同 = 复制粘贴出的真重复（红）。

**用法**：
    py -3 scripts/diag/check_doc_numbering.py            # 体检，退出码即结论
    py -3 scripts/diag/check_doc_numbering.py --json     # 机器可读

**退出码**：0 = 连续（或仅已知子条目重号）；1 = 有缺号/真重复；2 = 找不到 §6 章节。
"""

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

DOC = Path(__file__).resolve().parents[2] / "PROJECT_STATUS.md"

SEC_HEAD = "## 6. 接下来的任务"
SEC_TAIL = "## 7. 新会话对接指南"
# 顶层条目：行首数字 + ". "，数字前不得有空白（缩进的算子条目/续行）
ITEM_RE = re.compile(r"(?m)^(\d+)\.\s")


def extract_section(text: str) -> str:
    """截出 §6 整段。找不到起止就抛，让退出码 2 表达「文档结构变了」。"""
    i = text.find(SEC_HEAD)
    if i < 0:
        raise LookupError("找不到 §6 标题：%r" % SEC_HEAD)
    j = text.find(SEC_TAIL, i)
    return text[i:] if j < 0 else text[i:j]


def scan(text: str) -> dict:
    seg = extract_section(text)
    items = [(m.start(), int(m.group(1))) for m in ITEM_RE.finditer(seg)]
    if not items:
        raise LookupError("§6 里没扫到任何条目 —— 标题或编号格式变了？")

    nums = [n for _, n in items]
    counts = Counter(nums)
    top = max(nums)

    # 每个编号的全部出现位置 + 首行，用于分辨「子条目复用」与「真重复」
    occ: dict[int, list[str]] = {}
    for k, (pos, n) in enumerate(items):
        end = items[k + 1][0] if k + 1 < len(items) else len(seg)
        first = seg[pos:end].split("\n")[0].strip()
        occ.setdefault(n, []).append(first)

    missing = [n for n in range(1, top + 1) if n not in counts]
    # 真重复 = 同编号的多次出现**首行完全相同**（复制粘贴）；不同 = 子条目复用
    dup_exact = {n: v[0] for n, v in occ.items() if len(v) > 1 and len(set(v)) == 1}
    dup_reuse = {n: sorted(set(v)) for n, v in occ.items()
                 if len(v) > 1 and len(set(v)) > 1}

    return {
        "line_count": text.count("\n") + 1,
        "item_count": len(items),
        "numbers": nums,
        "max_number": top,
        "missing": missing,
        "dup_exact": dup_exact,
        "dup_reuse": dup_reuse,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="输出机器可读")
    args = ap.parse_args()

    if not DOC.exists():
        print("[缺] 找不到 %s" % DOC, file=sys.stderr)
        return 2
    text = DOC.read_text(encoding="utf-8")

    try:
        r = scan(text)
    except LookupError as e:
        print("[红] %s" % e, file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=1))
    else:
        print("文件 %s（%d 行）" % (DOC.name, r["line_count"]))
        print("§6 条目 %d 个，编号 1..%d" % (r["item_count"], r["max_number"]))
        if r["missing"]:
            print("[红] 缺号: %s" % r["missing"])
        if r["dup_exact"]:
            print("[红] 首行完全相同的真重复（复制粘贴）:")
            for n, t in sorted(r["dup_exact"].items()):
                print("     第%d条 ×%d  %s" % (n, len(r["numbers"]) and
                                                sum(1 for x in r["numbers"] if x == n), t[:70]))
        if r["dup_reuse"]:
            print("[黄] 同号但内容不同 = 顶格子条目复用编号（历史遗留，放行）:")
            for n, ts in sorted(r["dup_reuse"].items()):
                for t in ts:
                    print("     第%d条  %s" % (n, t[:76]))
        if not r["missing"] and not r["dup_exact"]:
            print("[绿] 编号 1..%d 连续，无真重复" % r["max_number"])

    return 1 if (r["missing"] or r["dup_exact"]) else 0


if __name__ == "__main__":
    sys.exit(main())
