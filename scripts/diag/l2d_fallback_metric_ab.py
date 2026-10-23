# -*- coding: utf-8 -*-
"""l2d_fallback_metric_ab.py — 「norm vs raw_sse」两种计分口径的全库影响面对账。

背景：build_motion_chain_map.py 对 touch_idle* 用 norm = Σ(d/range)²/N 排序，
range 取「该参数在各 idle 候选首帧间的值域」。实测 ougen_8/touch_idle14：
  idle9 raw=680(norm 排名 11)  idle5 raw=2994(raw 排名 11，norm 排名 1) → 算法选了 idle5，
  用户在游戏里确认应回 idle9。即「实际几何差异最小的候选」被归一化洗到了第 11 名。
本脚本不改任何产物，只回答一个问题：换成 raw_sse 会让多少条回落改变、改变的方向是否更合理。

用法: py -3.14 scripts/diag/l2d_fallback_metric_ab.py [--limit N] [--show ougen_8]
"""
import sys, os, json, glob, re

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LIVE2D = os.path.join(ROOT, "Output", "Live2D")
CHAIN = os.path.join(ROOT, "Output", "gallery_v2", "motion_chain.json")


def curve_ends(mp):
    try:
        d = json.load(open(mp, encoding="utf-8"))
    except Exception:
        return {}
    out = {}
    for c in d.get("Curves") or []:
        if (c.get("Target") or "") != "Parameter":
            continue
        pid, segs = c.get("Id"), c.get("Segments") or []
        if not pid or len(segs) < 3:
            continue
        try:
            out[pid] = (float(segs[1]), float(segs[-1]))
        except Exception:
            pass
    return out


def rank_for(model_dir, action):
    """返回 (raw_sorted[0], norm_sorted[0], 各候选明细)。"""
    mdir = os.path.join(model_dir, "motion")
    ap = os.path.join(mdir, action + ".motion3.json")
    if not os.path.isfile(ap):
        return None
    end_val = {p: v[1] for p, v in curve_ends(ap).items()}
    if not end_val:
        return None
    idles = {}
    for p in glob.glob(os.path.join(mdir, "*.motion3.json")):
        g = os.path.basename(p)[:-len(".motion3.json")]
        if re.fullmatch(r"idle\d*", g):
            ce = curve_ends(p)
            if ce:
                idles[g] = ce
    if not idles:
        return None
    rng = {}
    for p_ in end_val:
        vals = [idles[g][p_][0] for g in idles if p_ in idles[g]]
        rng[p_] = (min(vals), max(vals)) if vals else (0.0, 0.0)
    rows = []
    for g, ce in idles.items():
        raw = norm = 0.0
        n_common = n_miss = 0
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
                n_miss += 1
        denom = len(end_val) - n_miss
        rows.append({"g": g, "raw": raw, "norm": (norm / denom) if denom else float("inf"),
                     "n": n_common})
    raw_sorted = sorted(rows, key=lambda x: (-x["n"], x["raw"]))
    norm_sorted = sorted(rows, key=lambda x: (-x["n"], x["norm"]))
    return {"raw_best": raw_sorted[0]["g"], "norm_best": norm_sorted[0]["g"],
            "raw_best_val": raw_sorted[0]["raw"], "norm_best_val": norm_sorted[0]["norm"],
            "rows": rows}


def main():
    limit = 0
    show = ""
    for i, a in enumerate(sys.argv):
        if a == "--limit":
            limit = int(sys.argv[i + 1])
        if a == "--show":
            show = sys.argv[i + 1]
    chain = json.load(open(CHAIN, encoding="utf-8"))["models"]
    models = sorted(chain)
    if limit:
        models = models[:limit]
    tot = same = diff = skipped = 0
    diffs = []
    for m in models:
        mdir = os.path.join(LIVE2D, m)
        if not os.path.isdir(mdir):
            skipped += 1
            continue
        for a, info in (chain[m].get("chain") or {}).items():
            if not a.startswith("touch_idle"):
                continue
            cur = (info or {}).get("best")
            r = rank_for(mdir, a)
            if not r:
                continue
            tot += 1
            if r["raw_best"] == r["norm_best"]:
                same += 1
            else:
                diff += 1
                if len(diffs) < 40 or m == show:
                    diffs.append((m, a, cur, r["norm_best"], r["raw_best"],
                                  r["norm_best_val"], r["raw_best_val"]))
    print(f"touch_idle* 条目 {tot}  （模型缺目录跳过 {skipped}）")
    if tot:
        print(f"  两口径一致 {same}（{100*same/tot:.1f}%）  不一致 {diff}（{100*diff/tot:.1f}%）")
    print("\n不一致明细（当前产物 best / norm 会选 / raw 会选）:")
    print("  %-22s %-14s %-8s %-8s %-8s %12s %12s" % ("模型", "动作", "现状", "norm选", "raw选", "norm值", "raw值"))
    for row in diffs[:40]:
        m, a, cur, nb, rb, nv, rv = row
        flag = " <== 用户确认应为 raw" if (m == "ougen_8" and a == "touch_idle14") else ""
        print("  %-22s %-14s %-8s %-8s %-8s %12.4f %12.2f%s" % (m, a, cur, nb, rb, nv, rv, flag))
    if show:
        r = rank_for(os.path.join(LIVE2D, show), "touch_idle14")
        if r:
            print(f"\n{show}/touch_idle14 明细（按 raw 排序）:")
            for x in sorted(r["rows"], key=lambda z: z["raw"])[:8]:
                print("  %-8s raw=%10.2f norm=%9.4f n_common=%d" % (x["g"], x["raw"], x["norm"], x["n"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
