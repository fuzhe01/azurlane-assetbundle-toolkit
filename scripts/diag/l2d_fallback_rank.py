# -*- coding: utf-8 -*-
"""l2d_fallback_rank.py — 重算「动作末帧 vs 各 idle 首帧」的完整候选排行（含 raw_sse）。

存在的理由：build_motion_chain_map.py 的 norm 计分是 `Σ(d/range)²/N`，值域大的参数差异会被
大幅压低 —— 实测 ougen_8 的 touch_idle14 选中 idle5 时 raw_sse 是 13 个候选里最大（归一化把
「实际差异最大」洗成了「最优」）。本脚本把每个候选的 raw_sse / norm 都打出来，便于判断
「算法排序」与「实际衔接」是否背离。

用法: py -3.14 scripts/diag/l2d_fallback_rank.py ougen_8 touch_idle14 [--top 20]
"""
import sys, os, json, glob

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LIVE2D = os.path.join(ROOT, "Output", "Live2D")


def curve_ends(mp):
    """motion3.json → {参数: (首帧值, 末帧值)}。Segments 首值=首帧，末段值=末帧。"""
    d = json.load(open(mp, encoding="utf-8"))
    out = {}
    for c in d.get("Curves") or []:
        if (c.get("Target") or "") != "Parameter":
            continue
        pid, segs = c.get("Id"), c.get("Segments") or []
        if not pid or len(segs) < 3:
            continue
        first, last = segs[1], segs[-1]
        try:
            out[pid] = (float(first), float(last))
        except Exception:
            pass
    return out


def main():
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    model, action = sys.argv[1], sys.argv[2]
    top = 20
    for i, a in enumerate(sys.argv):
        if a == "--top":
            top = int(sys.argv[i + 1])

    mdir = os.path.join(LIVE2D, model, "motion")
    ap = os.path.join(mdir, action + ".motion3.json")
    if not os.path.isfile(ap):
        raise SystemExit("找不到动作文件: " + ap)
    a_full = curve_ends(ap)
    end_val = {p: v[1] for p, v in a_full.items()}

    # idle 候选：idle / idleN
    import re
    idles = {}
    for p in glob.glob(os.path.join(mdir, "*.motion3.json")):
        g = os.path.basename(p)[:-len(".motion3.json")]
        if re.fullmatch(r"idle\d*", g):
            idles[g] = curve_ends(p)
    if not idles:
        raise SystemExit("没有 idle 候选")

    # 参数值域：该参数在各 idle 候选的首帧之间的范围
    rng = {}
    for p_ in end_val:
        vals = [idles[g][p_][0] for g in idles if p_ in idles[g]]
        rng[p_] = (min(vals), max(vals)) if vals else (0.0, 0.0)

    rows = []
    for g, ce in idles.items():
        raw = norm = 0.0
        n_common = n_miss_rng = 0
        for p_, ev_ in end_val.items():
            if p_ in ce:
                sv = ce[p_][0]
                n_common += 1
            else:
                sv = 0.0
            d = ev_ - sv
            raw += d * d
            lo, hi = rng.get(p_, (sv, sv))
            rr = hi - lo
            if rr > 1e-9:
                norm += (d / rr) ** 2
            else:
                n_miss_rng += 1
        denom = len(end_val) - n_miss_rng
        rows.append({"group": g, "raw_sse": raw, "norm": (norm / denom) if denom else float("inf"),
                     "n_common": n_common})

    rows.sort(key=lambda x: x["raw_sse"])
    print(f"{model} / {action}  末帧参数数={len(end_val)}  候选={len(rows)}\n")
    print("按 raw_sse（实际几何差异，越小越接近）排序：")
    print("  %-8s %14s %12s %8s" % ("组", "raw_sse", "norm", "公共参数"))
    for i, r in enumerate(rows[:top], 1):
        mark = "  <== raw 最优" if i == 1 else ""
        print("  %-8s %14.2f %12.4f %8d%s" % (r["group"], r["raw_sse"], r["norm"], r["n_common"], mark))

    rows_n = sorted(rows, key=lambda x: x["norm"])
    print("\n按 norm（算法实际排序依据）排序：")
    print("  %-8s %12s %14s" % ("组", "norm", "raw_sse"))
    for i, r in enumerate(rows_n[:top], 1):
        mark = "  <== norm 最优（算法会选它）" if i == 1 else ""
        print("  %-8s %12.4f %14.2f%s" % (r["group"], r["norm"], r["raw_sse"], mark))

    print("\n两种排序的位置对照：")
    pos_raw = {r["group"]: i + 1 for i, r in enumerate(rows)}
    pos_norm = {r["group"]: i + 1 for i, r in enumerate(rows_n)}
    for g in [r["group"] for r in rows_n[:6]]:
        print("  %-8s raw排名=%-3d norm排名=%-3d  背离=%s"
              % (g, pos_raw[g], pos_norm[g], "是" if abs(pos_raw[g] - pos_norm[g]) >= 3 else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
