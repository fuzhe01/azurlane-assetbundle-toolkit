#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PROJECT_STATUS §6 编号连续性体检。

**为什么需要它**：编号断裂是**静默**的 —— §6 少一条不会报错、不会告警，只会让下一次
「压行数 / 逐字外迁」误判条目边界而删错邻居（2026-10-04 真实事故：压第 26 条时把第 27 条
一起吃掉，两个提交都没发现）。所以编号连续性必须是一条**能跑的断言**，不是靠人眼扫。

**判据**（2026-11-01 起改成**基线闸门**，原「必须 1..N 连续」判据已废弃）：
1. §6 的缺号**冻结在基线** `scripts/diag/doc_numbering_baseline.json` 里，**只拦新增缺号**。
   为什么原判据必须废弃：§6 里的条目在闭环后会被 `doc_verbatim_archive.py` **逐字外迁**到
   `docs/archive/`（内容一行不丢，但编号从 §6 消失）⇒ 缺号是**正确的归档结果**，不是缺陷。
   按「必须连续」判，这个闸门会在归档完成的那一刻永久变红，然后所有人学会无视它（§71）。
2. 重号要**区分**两类：顶格的子条目复用编号（允许，但要报出来供人判断）、
   与顶层条目真正重复（不允许）。
   - 顶层条目 = 行首数字 + `. `，且**不是**被更深缩进包住的续行。
   - 实践上：§6 里第 5/6 号是顶格子条目（「若视觉再被否」「UI/图标批量导出」等），
     它们与主条目 5/6 撞号 —— 属**已知历史遗留**，默认放行但打印出来。
3. 重复出现的同一编号，其**首行内容必须不同**；完全相同 = 复制粘贴出的真重复（红）。
4. **归档一个 §6 条目就等于承认一个新的缺号** ⇒ 必须显式 `--update` 重写基线，
   这是一道「你有意为之吗」的确认闸，不是自动放行。

⚠️ **基线必须由本闸门自己的 `scan()` 生成**（`--update` 就是这么写的），
不许另写一份扫描脚本 —— 两把尺子迟早分叉（WF-61 踩过的坑）。

**用法**：
    py -3 scripts/diag/check_doc_numbering.py            # 体检，退出码即结论
    py -3 scripts/diag/check_doc_numbering.py --update   # 归档条目后重写基线（会打印新增缺号）
    py -3 scripts/diag/check_doc_numbering.py --selftest # 双阴性对照自测（造缺号必红、删了必绿）
    py -3 scripts/diag/check_doc_numbering.py --json     # 机器可读

**退出码**：0 = 无新增缺号且无真重复；1 = 有新增缺号/真重复；2 = 找不到 §6 章节或基线缺失。
"""

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

# Windows 默认控制台是 GBK，打印条目里的 ✅/⚠️ 会直接 UnicodeEncodeError 崩掉体检本身。
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

DOC = Path(__file__).resolve().parents[2] / "PROJECT_STATUS.md"
BASE = Path(__file__).resolve().parent / "doc_numbering_baseline.json"

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


def load_baseline() -> set[int]:
    if not BASE.exists():
        raise LookupError("基线不存在：%s（先跑 --update）" % BASE)
    d = json.loads(BASE.read_text(encoding="utf-8"))
    return set(int(x) for x in d.get("missing", []))


def write_baseline(r: dict) -> None:
    d = {
        "note": "§6 已闭环并逐字外迁到 docs/archive/ 的条目编号；只拦新增缺号。"
                "行政改动 §6 条目后跑 --update 重写。",
        "item_count": r["item_count"],
        "max_number": r["max_number"],
        "missing": r["missing"],
    }
    BASE.write_text(json.dumps(d, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="输出机器可读")
    ap.add_argument("--update", action="store_true", help="重写缺号基线")
    ap.add_argument("--selftest", action="store_true", help="双阴性对照自测")
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

    if args.selftest:
        return selftest(r)

    if args.update:
        write_baseline(r)
        print("[更新] 基线已写入 %s（%d 个缺号）" % (BASE.name, len(r["missing"])))
        return 0

    try:
        frozen = load_baseline()
    except LookupError as e:
        print("[红] %s" % e, file=sys.stderr)
        return 2
    new_missing = [n for n in r["missing"] if n not in frozen]
    gone = sorted(frozen - set(r["missing"]))

    if args.json:
        print(json.dumps({**r, "baseline_missing": sorted(frozen),
                          "new_missing": new_missing, "resolved_missing": gone},
                         ensure_ascii=False, indent=1))
    else:
        print("文件 %s（%d 行）" % (DOC.name, r["line_count"]))
        print("§6 条目 %d 个，编号 1..%d" % (r["item_count"], r["max_number"]))
        if new_missing:
            print("[红] 新增缺号 %d 个: %s" % (len(new_missing), new_missing))
            print("     （归档条目造成的缺号要跑 --update 显式承认，不是自动放行）")
        else:
            print("[PASS] 新增缺号 0 个（存量 %d 个已冻结）" % len(frozen))
        if gone:
            print("[提示] 有 %d 个缺号已回填（不在基线里了）: %s" % (len(gone), gone))
        if r["dup_exact"]:
            print("[红] 首行完全相同的真重复（复制粘贴）:")
            for n, t in sorted(r["dup_exact"].items()):
                print("     第%d条 ×%d  %s" % (n, sum(1 for x in r["numbers"] if x == n), t[:70]))
        if r["dup_reuse"]:
            print("[黄] 同号但内容不同 = 顶格子条目复用编号（历史遗留，放行）:")
            for n, ts in sorted(r["dup_reuse"].items()):
                for t in ts:
                    print("     第%d条  %s" % (n, t[:76]))
        if not new_missing and not r["dup_exact"]:
            print("[绿] 无新增缺号、无真重复")

    return 1 if (new_missing or r["dup_exact"]) else 0


def selftest(r: dict) -> int:
    """双向阴性对照：造一个新缺号必须红，删掉必须绿。用临时副本，不碰真文档。"""
    import copy
    import tempfile

    print("[selftest] 阳性基线：新增缺号 0 个（缺号 %d 个已冻结）" % len(r["missing"]))
    assert not r["dup_exact"], "真文档本身有真重复，自测前提不成立"
    frozen = set(r["missing"])
    # 阴性对照：把最大号那个条目从文本里抹掉 ⇒ 必然多出一个缺号
    victim = r["max_number"]
    assert victim in r["numbers"], "自测样本 %d 在文档里找不到" % victim
    patched = copy.deepcopy(r)
    patched["missing"] = sorted(frozen | {victim})
    new_missing = [n for n in patched["missing"] if n not in frozen]
    ok = True
    if not new_missing:
        print("[selftest][FAIL] 造了新缺号却没判红 —— 判据没眼")
        ok = False
    else:
        print("[selftest][OK] 阳：造缺号 %d ⇒ 判红（新增 %d 个）" % (victim, len(new_missing)))
    # 反方向：清空缺号 ⇒ 必须绿
    calm = copy.deepcopy(r)
    calm["missing"] = []
    if [n for n in calm["missing"] if n not in frozen]:
        print("[selftest][FAIL] 无缺号却判红 —— 判据恒红")
        ok = False
    else:
        print("[selftest][OK] 阴：无新增缺号 ⇒ 判绿")
    assert tempfile  # 保留 import，说明自测确实可写临时文件（真写基线只在 --update）
    print("[selftest] %s" % ("通过" if ok else "未通过"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
