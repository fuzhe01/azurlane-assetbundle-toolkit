# -*- coding: utf-8 -*-
"""extract_spine_v2 的失败语义闸门：驱动真实的 `main()`，验「失败必须落到行首 ✗ 与退出码」。

桩只替掉 extract_one / write_parts 两个叶子函数（决定成败的地方），main() 本身的计数、
打印、退出码全是真路径 —— 不绕过被测入口。不写任何正式产物（不给 --bak ⇒ 不产 MANIFEST，
写向全在临时区）。§111 第 4 节 / WF-28。
"""
import io
import os
import sys
import contextlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import extract_spine_v2 as E  # noqa: E402

CASES = []
FAIL = []


def run_case(label, argv, extract_map, parts_map, want_rc, want_lines):
    sys.argv = ["extract_spine_v2.py"] + argv
    E.extract_one = lambda n: (extract_map[n][0], extract_map[n][1])
    E.write_parts = lambda n, d: (parts_map[n][0], parts_map[n][1]) if parts_map[n][0] else (None, parts_map[n][1])
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = E.main()
    out = buf.getvalue()
    lines = [l for l in out.splitlines() if l.startswith(("✓", "✗"))]
    ok = (rc == want_rc) and (len(lines) == len(want_lines))
    for l, pre in zip(lines, want_lines):
        if not l.startswith(pre):
            ok = False
    print(f"{'PASS' if ok else 'FAIL'} {label}: rc={rc}（期望 {want_rc}）")
    for l in lines:
        print(f"       {l[:120]}")
    if not ok:
        FAIL.append(label)


P = {"layer": ["B", "M", "T"]}  # 真 payload 只需非 None 即算成功

# 1) 提取成功但清单落不下 —— 本轮修的那条：必须行首 ✗ 且非零退出
run_case("整批：extract ✓ 但 parts ✗",
         ["--out", ".diag/spine_exit_test", "skin_a"],
         {"skin_a": (True, "3 skel / 3 atlas / 9 png")},
         {"skin_a": (None, "prefab 挂了但目录里没有这些 skel: ['T']")},
         1, ["✗"])

# 2) 提取本身失败
run_case("整批：extract ✗",
         ["--out", ".diag/spine_exit_test", "skin_b"],
         {"skin_b": (False, "主包与 _res 都没有 skel")},
         {"skin_b": (P, "")},
         1, ["✗"])

# 3) 全绿
run_case("整批：全成功",
         ["--out", ".diag/spine_exit_test", "skin_c"],
         {"skin_c": (True, "2 skel / 2 atlas / 6 png")},
         {"skin_c": (P, "")},
         0, ["✓"])

# 4) 混合一批：只要有一个失败就非零
run_case("整批：1 成 1 败",
         ["--out", ".diag/spine_exit_test", "skin_c", "skin_a"],
         {"skin_c": (True, "2 skel"), "skin_a": (True, "3 skel")},
         {"skin_c": (P, ""), "skin_a": (None, "prefab 里没有可解析的 SkeletonGraphic 层")},
         1, ["✓", "✗"])

# 5) --parts-only 既有失败路径不退化（走真实函数：目录不存在）
sys.argv = ["extract_spine_v2.py", "--parts-only", "--out", ".diag/spine_exit_test_empty", "nope"]
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    rc = E.main()
line = [l for l in buf.getvalue().splitlines() if l.startswith(("✓", "✗"))]
print(f"{'PASS' if rc == 1 and line and line[0].startswith('✗') else 'FAIL'} --parts-only 目录不存在: rc={rc}（期望 1）")
print(f"       {line[0] if line else '(无 ✗/✓ 行)'}")
if rc != 1 or not line or not line[0].startswith("✗"):
    FAIL.append("parts-only")

# 6) 闸门不退化：写正式区不给 --bak 仍 exit 2，且一个字都不写
sys.argv = ["extract_spine_v2.py", "skin_a"]
E.OUT_ROOT = E.P.SPINE_OUT
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    rc = E.main()
print(f"{'PASS' if rc == 2 else 'FAIL'} 正式区无 --bak 仍拒写: rc={rc}（期望 2）")
if rc != 2:
    FAIL.append("backup-gate")

print("\n结论:", "ALL PASS" if not FAIL else f"FAIL -> {FAIL}")
sys.exit(1 if FAIL else 0)
