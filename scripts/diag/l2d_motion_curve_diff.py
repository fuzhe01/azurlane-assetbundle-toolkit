# -*- coding: utf-8 -*-
"""l2d_motion_curve_diff.py — 逐曲线对比两份 motion3.json 的参数集合。

用途：换入重导出产物后，定位「哪条曲线丢了 / 多了」，特别是高度控制用户可见部件
（手、配件）的曲线。输出：
  lost   旧有、新没有（换入后这些参数不再被驱动 → 停在默认位）
  gained 新有、旧没有
  changed 两侧都有但段数/值域差异显著
用法:
  py -3.14 scripts/diag/l2d_motion_curve_diff.py <old.motion3.json> <new.motion3.json> [关键词...]
"""
import sys, os, json

sys.stdout.reconfigure(encoding="utf-8")


def load_curves(path):
    d = json.load(open(path, encoding="utf-8"))
    out = {}
    for c in d.get("Curves", []):
        tgt = c.get("Target") or ""
        cid = c.get("Id") or ""
        key = tgt + (("/" + cid) if cid else "")
        segs = c.get("Segments") or []
        vals = [v for v in segs if isinstance(v, (int, float))]
        # 段数：Segments 里每段以 type 开头，2=线性(2 个值) 3=贝塞尔(4 个) ...
        out[key] = {"nseg": len(segs), "min": min(vals) if vals else None,
                    "max": max(vals) if vals else None, "raw": segs[:6]}
    return d, out


def main():
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    old_p, new_p = sys.argv[1], sys.argv[2]
    kws = [k for k in sys.argv[3:] if k]
    do_, dc = load_curves(old_p)
    dn, nc = load_curves(new_p)
    print(f"old: {os.path.basename(old_p)}  curves={len(dc)}  Duration={do_.get('Meta', {}).get('Duration')}")
    print(f"new: {os.path.basename(new_p)}  curves={len(nc)}  Duration={dn.get('Meta', {}).get('Duration')}")

    lost = sorted(set(dc) - set(nc))
    gained = sorted(set(nc) - set(dc))
    print(f"\nlost={len(lost)}  gained={len(gained)}  common={len(set(dc) & set(nc))}")

    def show(title, items, src):
        if not items:
            return
        print(f"\n--- {title} ({len(items)}) ---")
        for k in items[:60]:
            e = src[k]
            print(f"  {k}   segs={e['nseg']} range=[{e['min']},{e['max']}]")
        if len(items) > 60:
            print(f"  ... 共 {len(items)} 条")

    show("LOST（旧有新无 → 换入后不再被驱动）", lost, dc)
    show("GAINED（新有旧无）", gained, nc)

    changed = []
    for k in sorted(set(dc) & set(nc)):
        a, b = dc[k], nc[k]
        if a["nseg"] != b["nseg"] or a["min"] != b["min"] or a["max"] != b["max"]:
            changed.append(k)
    if changed:
        print(f"\n--- CHANGED（段数或值域不同）({len(changed)}) ---")
        for k in changed[:40]:
            a, b = dc[k], nc[k]
            print(f"  {k}: segs {a['nseg']}→{b['nseg']} range [{a['min']},{a['max']}]→[{b['min']},{b['max']}]")
        if len(changed) > 40:
            print(f"  ... 共 {len(changed)}")

    # 关键词过滤（手部/可见性相关）
    if kws:
        print("\n===== 关键词命中 =====")
        for kw in kws:
            hits = [k for k in (lost + gained + changed) if kw.lower() in k.lower()]
            print(f"  [{kw}] {len(hits)} 条: {hits[:12]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
