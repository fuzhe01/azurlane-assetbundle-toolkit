#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""l2d_pose_anchor_pick.py — 姿势验证锚点挑选（EMIT_CONST 换入验证前置，只读）

从重导产物里挑「适合运行时姿势落值验证」的锚点参数（§134 续 / WF-41 流程第 5 步）：
  * 该参数在目标组是**纯定值曲线**（`[0,v,0,dur,v]` 单段 InverseStepped，首尾同值）；
  * 与默认 idle 组的同名参数定值**不同**（差异 >= 1.0）；
  * 默认 idle 组里**有同名曲线**（切回时能验证复位/回到基态）。
  * |v| >= 0.5（太小的值分不清噪声）；跳过明显超范围的巨值（clamp 坑，由
    l2d_const_pose_verify 侧用 core.getParameterMaximumValue 核）。

用法:
  py -3 scripts/diag/l2d_pose_anchor_pick.py                     # 默认 4 样本
  py -3 scripts/diag/l2d_pose_anchor_pick.py aersasi_2 ougen_8   # 指定模型
输出: 每模型一行 `模型|组|{"Param":值,...}`（期望表，喂给 POSE_EXPECT）。
回零基准: 默认 idle 组里锚点参数的定值另行查（喂给 POSE_BACK 的 expect）。
目录可用 NEW_DIR 环境变量覆盖（默认 .diag/l2d_const_test）。
"""
import os, sys, json

sys.stdout.reconfigure(encoding="utf-8")

NEW_DIR = os.environ.get("NEW_DIR", os.path.join(".diag", "l2d_const_test"))
DEFAULT_MODELS = ["antu_2", "aersasi_2", "aersasi_3", "qiershazhi_2"]


def const_value(segs):
    """单段 InverseStepped/Stepped 且首尾值相同 → 定值，否则 None。"""
    if len(segs) == 5 and segs[2] == 0 and segs[1] == segs[4]:
        return round(float(segs[1]), 3)
    if len(segs) == 4 and segs[2] == 2:
        return round(float(segs[1]), 3)
    return None


def main():
    for m in (sys.argv[1:] or DEFAULT_MODELS):
        md = os.path.join(NEW_DIR, m, "motion")
        if not os.path.isdir(md):
            print(f"[{m}] 无 motion 目录: {md}")
            continue
        groups = sorted(f[:-len(".motion3.json")] for f in os.listdir(md)
                        if f.endswith(".motion3.json"))
        default = "idle" if "idle" in groups else ("idle1" if "idle1" in groups else None)
        if not default:
            print(f"[{m}] 无默认 idle 组，跳过")
            continue
        dcurves = {c["Id"]: c for c in json.load(
            open(os.path.join(md, default + ".motion3.json"), encoding="utf-8"))["Curves"]}

        best = None
        for g in groups:
            if g == default or not g.startswith("idle"):
                continue
            cur = json.load(open(os.path.join(md, g + ".motion3.json"),
                                 encoding="utf-8"))["Curves"]
            diff = {}
            for c in cur:
                v = const_value(c.get("Segments", []))
                if v is None or abs(v) < 0.5 or abs(v) > 90:
                    continue
                if c["Id"] not in dcurves:
                    continue
                dv = const_value(dcurves[c["Id"]].get("Segments", []))
                if dv is not None and abs(dv - v) >= 1.0:
                    diff[c["Id"]] = v
            if best is None or len(diff) > len(best[1]):
                best = (g, diff)
        if not best or len(best[1]) < 3:
            print(f"[{m}] 差异定值不足 3 条: {best}")
            continue
        g, diff = best
        sel = dict(sorted(diff.items(), key=lambda kv: -abs(kv[1]))[:6])
        print(f"{m}|{g}|{json.dumps(sel, ensure_ascii=False)}")


if __name__ == "__main__":
    main()