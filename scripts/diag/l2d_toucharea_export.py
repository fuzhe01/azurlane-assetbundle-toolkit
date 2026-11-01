# -*- coding: utf-8 -*-
"""l2d_toucharea_export.py — 导出全部互动区清单（含 model3.json 未登记的）。

为什么需要（2026-10-23 用户提问引出的修正）：
  旧口径只从「参数曲线有多档值」找互动区，漏掉了全部换装开关——因为脱鞋/戴眼镜这类
  切换是**运行时代码写参数**，动作曲线里恒为常量，从曲线数据看"只有 1 档"就被剔除。
  而互动区存在与否的第一性证据是 **moc3 里的 Touch* drawable**：
    全库 262 模型共 4919 个 Touch drawable（Drag 1693 / Idle 2392），
    其中只有 2786 个登记进 model3.json 的 HitAreas，**1299 个存在但前端点不到**。

本脚本产出前端可消费的清单：
  Output/gallery_v2/touchareas.json
    { 模型key: {
        drag: [{drawable:"TouchDrag17", registered:true|false, group:"touch_drag17"|null}, ...],
        idle: [...],
        hitarea_names: [...],
      } }

⚠️ 明确边界：这个清单只回答「有哪些互动区、登记没登记、有没有同名动作组」。
   它**不**回答「点了是什么效果」——实测 TouchDrag17 的显隐只受 Param500 控制，
   与它触发的 ShoseOff 无数据关联；效果映射只存在于游戏代码，无法从资产自动推导。
   因此清单用于**发现与定位**，语义仍需逐个目视确认（或由用户标注）。

用法: py -3.14 scripts/diag/l2d_toucharea_export.py
"""
import sys, os, json, re

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LIVE2D = os.path.join(ROOT, "Output", "Live2D")
SRC = os.path.join(ROOT, ".diag", "touch_drawables.json")
DST = os.path.join(ROOT, "Output", "gallery_v2", "touchareas.json")


def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def main():
    if not os.path.isfile(SRC):
        raise SystemExit("缺 %s —— 先跑 py -3.14 scripts/diag/l2d_touch_drawable_scan.py" % SRC)
    scan = json.load(open(SRC, encoding="utf-8"))
    out = {}
    n_drag = n_idle = n_unreg = 0
    for model, info in scan.items():
        mj = os.path.join(LIVE2D, model, model + ".model3.json")
        try:
            j = json.load(open(mj, encoding="utf-8"))
        except Exception:
            continue
        groups = list(((j.get("FileReferences") or {}).get("Motions") or {}).keys())
        gmap = {norm(g): g for g in groups}
        hit_names = [h.get("Name") for h in (j.get("HitAreas") or [])]
        hit_n = {norm(x) for x in hit_names}

        def pack(ids):
            rows = []
            for d in ids:
                key = norm(d)
                rows.append({
                    "drawable": d,
                    "registered": key in hit_n,
                    "group": gmap.get(key),
                })
            return rows

        drag = pack(info.get("drag_ids") or [])
        idle = pack(info.get("idle_ids") or [])
        if not drag and not idle:
            continue
        n_drag += len(drag)
        n_idle += len(idle)
        n_unreg += sum(1 for r in drag + idle if not r["registered"])
        out[model] = {"drag": drag, "idle": idle, "hitarea_names": hit_names}

    os.makedirs(os.path.dirname(DST), exist_ok=True)
    json.dump(out, open(DST, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    size = os.path.getsize(DST)
    top = sorted(out.items(), key=lambda kv: -(len(kv[1]["drag"]) + len(kv[1]["idle"])))[:8]
    print(f"导出 {len(out)} 个模型 / drag {n_drag} + idle {n_idle} = {n_drag + n_idle} 个互动区"
          f"（未登记 {n_unreg}）-> {DST} （{size/1024:.1f} KB）")
    print("\n互动区最多的模型:")
    for m, v in top:
        reg = sum(1 for r in v["drag"] + v["idle"] if r["registered"])
        print(f"  {m:22s} drag={len(v['drag']):3d} idle={len(v['idle']):3d}"
              f"  已登记={reg:3d}  动作组命中={sum(1 for r in v['drag'] + v['idle'] if r['group']):3d}")
    # ougen_8 抽查：touch_drag17 必须在且标为未登记
    o = out.get("ougen_8") or {}
    d17 = [r for r in (o.get("drag") or []) if r["drawable"] == "TouchDrag17"]
    print(f"\n抽查 ougen_8 / TouchDrag17: {d17 if d17 else '缺失'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
