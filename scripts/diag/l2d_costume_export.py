# -*- coding: utf-8 -*-
"""l2d_costume_export.py — 把换装参数扫描结果导出成前端可直接消费的精简表。

背景（方案 A）：前端不逐个接 HitAreas 互动区，而是给每个模型自动列出「可调的装扮参数」
（开关型 → 按钮，渐变型 → 滑块），一次性覆盖全部有换装能力的模型。

数据来源：.diag/costume_params.json（l2d_costume_params_scan.py 产出）
输出：Output/gallery_v2/costume_params.json
  结构 { 模型key: [ {id, label, kind, lo, hi, vals:[...]}, ... ] }
  - 只保留 kind ∈ {switch, slider} 且确有多个取值的参数（恒定参数没有可调空间）
  - 排除参数名明显是动画量的（眼球转动、眨眼开合），那些由动作/视线系统驱动

用法: py -3.14 scripts/diag/l2d_costume_export.py
"""
import sys, os, json

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(ROOT, ".diag", "costume_params.json")
DST = os.path.join(ROOT, "Output", "gallery_v2", "costume_params.json")

# 明确排除：这些参数由动作/视线/眨眼系统逐帧驱动，做成滑块会与运行时打架
EXCLUDE_REGEX_HINTS = (
    "eyeballx", "eyebally", "eyeballlx", "eyeballly", "eyeballrx", "eyeballry",
    "eyelopen", "eyeropen", "eyeopen", "breath", "angle",
)


def main():
    if not os.path.isfile(SRC):
        raise SystemExit("缺 %s —— 先跑 py -3.14 scripts/diag/l2d_costume_params_scan.py" % SRC)
    raw = json.load(open(SRC, encoding="utf-8"))
    out = {}
    n_switch = n_slider = 0
    for model, params in raw.items():
        rows = []
        for pid, info in params.items():
            kind = info.get("kind")
            if kind not in ("switch", "slider"):
                continue
            low = pid.lower()
            if any(h in low for h in EXCLUDE_REGEX_HINTS):
                continue
            vals = [v for v in (info.get("vals") or []) if isinstance(v, (int, float))]
            if len(set(vals)) < 2:
                continue
            rows.append({
                "id": pid,
                "label": info.get("label") or "",
                "kind": kind,
                "vals": sorted(set(vals))[:16],
            })
            if kind == "switch":
                n_switch += 1
            else:
                n_slider += 1
        if rows:
            # 开关型排前面（更适合当按钮），同类型按名字拼音序稳定输出
            rows.sort(key=lambda r: (0 if r["kind"] == "switch" else 1, r["id"].lower()))
            out[model] = rows

    os.makedirs(os.path.dirname(DST), exist_ok=True)
    json.dump(out, open(DST, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    size = os.path.getsize(DST)
    print(f"导出 {len(out)} 个模型 / {n_switch + n_slider} 条参数"
          f"（开关 {n_switch} / 渐变 {n_slider}）-> {DST} （{size/1024:.1f} KB）")
    # 冒烟：挑一个多参数模型打印
    rich = sorted(out.items(), key=lambda kv: -len(kv[1]))[:3]
    for m, rows in rich:
        print(f"  {m}: {len(rows)} 条 -> " + ", ".join(f"{r['id']}[{r['kind'][0]}]" for r in rows[:8]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
