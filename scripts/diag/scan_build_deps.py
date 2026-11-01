# -*- coding: utf-8 -*-
"""扫描 scripts/ + tools/ 全部 .py，列出非标准库、非项目内部模块的顶层 import。

用途：换机器装环境前，用本脚本确认到底依赖哪些第三方包，结果钉进
仓库根 requirements-v2.txt。项目内部模块（scripts/*.py、tools/**/*.py 的 stem）不算第三方。

用法：py -3 scripts/diag/scan_build_deps.py
"""
import ast
import os
import sys

STD = set(sys.stdlib_module_names)


def collect(root):
    out = []
    for dp, _, fs in os.walk(root):
        if ".git" in dp or "__pycache__" in dp:
            continue
        for f in fs:
            if f.endswith(".py"):
                out.append(os.path.join(dp, f))
    return out


def main():
    files = collect(os.path.join(os.path.dirname(sys.argv[0]), "..", "..", "scripts")) + \
        collect(os.path.join(os.path.dirname(sys.argv[0]), "..", "..", "tools"))
    # 项目自己的模块名（scripts/tools 下任一 .py 的 stem）→ 排除，避免当第三方
    own = set()
    for p in list(files) + [os.path.join("scripts", "paths.py")]:
        own.add(os.path.splitext(os.path.basename(p))[0])

    mods = set()
    for p in files:
        try:
            t = ast.parse(open(p, encoding="utf-8").read(), filename=p)
        except Exception:
            continue
        for n in ast.walk(t):
            if isinstance(n, ast.Import):
                for a in n.names:
                    mods.add(a.name.split(".")[0])
            elif isinstance(n, ast.ImportFrom) and n.module:
                mods.add(n.module.split(".")[0])

    thirds = sorted(
        m for m in mods
        if m not in STD and not m.startswith("_") and m not in own
    )
    for m in thirds:
        print(m)
    print("--- 共 %d 个第三方顶层模块 ---" % len(thirds))
    return 0


if __name__ == "__main__":
    sys.exit(main())
