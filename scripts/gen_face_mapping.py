#!/usr/bin/env python3
"""生成 paintingface_mapping.json"""
import os
import json
import sys as _p_sys, os as _p_os
_p_sys.path.insert(0, _p_os.path.dirname(_p_os.path.abspath(__file__)))
import paths as P  # 仓库根与外部工具位置：见 scripts/paths.py（AL_ASSETS_ROOT 可覆盖）
from collections import defaultdict

FACE_DIR = os.path.join(P.AB, "paintingface")
PAINT_DIR = os.path.join(P.AB, "painting")
OUTPUT = os.path.join(P.OUT, "paintingface_mapping.json")

for _d in (FACE_DIR, PAINT_DIR):
    if not os.path.isdir(_d):
        raise SystemExit(f"[ERROR] 目录不存在: {_d}（资产放 P.AB 下，或用 AL_ASSETS_ROOT 指过去）")

face_files = sorted(os.listdir(FACE_DIR))
paint_files = set(os.listdir(PAINT_DIR))

mapping = {}
for name in face_files:
    face_path = os.path.join(FACE_DIR, name)
    if not os.path.isfile(face_path):
        continue

    has_tex = (name + "_tex") in paint_files
    has_base = name in paint_files

    mapping[name] = {
        "base_bundle": name if has_base else None,
        "tex_bundle": name + "_tex" if has_tex else None,
        "has_painting": has_base and has_tex,
    }

with open(OUTPUT, "w", encoding="utf-8") as f:
    json.dump(mapping, f, ensure_ascii=False, indent=2)

print(f"Generated {OUTPUT}")
print(f"Total: {len(mapping)} entries")
matched = sum(1 for v in mapping.values() if v["has_painting"])
print(f"Matched (has base+tex): {matched}")
print(f"Unmatched (face only): {len(mapping) - matched}")
