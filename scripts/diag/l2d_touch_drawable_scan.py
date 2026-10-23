# -*- coding: utf-8 -*-
"""l2d_touch_drawable_scan.py — 以「moc3 里的 Touch* drawable」为第一信号，盘点全部互动区。

为什么换信号源（2026-10-23 修正）：
  旧扫描器用「参数在动作间有多档取值」当判据，结果**漏掉全部换装开关**——
  因为脱鞋/戴眼镜这类切换是**运行时代码写参数**（如 ShoseOff），动作曲线里恒为 0，
  从曲线数据看"只有 1 档 ⇒ 无可调空间"，被误剔除。
  而互动区是否存在的第一性证据是 **moc3 里的 Touch* drawable**（模型自带按钮部件），
  与 model3.json 的 HitAreas 是否登记无关（实测 ougen_8 有 44 个 Touch drawable，
  HitAreas 只登记了 3 个 touch_drag —— 大量互动区存在但前端点不到）。

输出（每模型）：
  touch_drawables_total / drag_names / idle_names / registered_in_hitareas
  → 用于回答「全库到底有多少互动区、其中多少已登记、多少漏登记」

用法: py -3.14 scripts/diag/l2d_touch_drawable_scan.py [--json out.json]
"""
import sys, os, json, re, collections

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LIVE2D = os.path.join(ROOT, "Output", "Live2D")
OUT = os.path.join(ROOT, ".diag", "touch_drawables.json")


def touch_ids_from_moc3(path):
    """moc3 是二进制，字符串池里 drawable/part id 可直接正则捞出（不依赖解析库）。"""
    try:
        raw = open(path, "rb").read()
    except Exception:
        return []
    ids = set()
    for m in re.finditer(rb"Touch[A-Za-z0-9_]{0,24}", raw):
        s = m.group().decode("ascii", "ignore")
        # 过滤掉明显是 id 前缀拼接产物；保留 TouchXxx 形态
        if len(s) >= 6:
            ids.add(s)
    return sorted(ids)


def main():
    out_path = OUT
    for i, a in enumerate(sys.argv):
        if a == "--json":
            out_path = sys.argv[i + 1]
    names = sorted(d for d in os.listdir(LIVE2D) if os.path.isdir(os.path.join(LIVE2D, d)))
    inv = {}
    for i, n in enumerate(names, 1):
        d = os.path.join(LIVE2D, n)
        moc = os.path.join(d, n + ".moc3")
        mj = os.path.join(d, n + ".model3.json")
        if not os.path.isfile(moc) or not os.path.isfile(mj):
            continue
        ids = touch_ids_from_moc3(moc)
        try:
            j = json.load(open(mj, encoding="utf-8"))
        except Exception:
            j = {}
        hit = [h.get("Name") for h in (j.get("HitAreas") or [])]
        groups = list(((j.get("FileReferences") or {}).get("Motions") or {}).keys())
        drag_g = sorted(g for g in groups if re.match(r"^touch_?drag", g, re.I))
        idle_g = sorted(g for g in groups if re.match(r"^touch_?idle", g, re.I))

        drag_ids = [x for x in ids if re.search(r"drag", x, re.I)]
        idle_ids = [x for x in ids if re.search(r"idle", x, re.I)]
        # 已登记的：HitAreas 名（touch_dragN）与 drawable 名（TouchDragN）互转后比对
        def norm(s):
            return re.sub(r"[^a-z0-9]", "", (s or "").lower())
        hit_n = {norm(x) for x in hit}
        reg_cnt = sum(1 for x in (drag_ids + idle_ids) if norm(x) in hit_n)

        inv[n] = {
            "touch_total": len(ids),
            "drag_ids": drag_ids,
            "idle_ids": idle_ids,
            "registered": reg_cnt,
            "unregistered": len(drag_ids) + len(idle_ids) - reg_cnt,
            "hitareas": len(hit),
            "drag_groups": len(drag_g),
            "idle_groups": len(idle_g),
        }
        if i % 50 == 0:
            print(f"... {i}/{len(names)}", flush=True)

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    json.dump(inv, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    tot_touch = sum(v["touch_total"] for v in inv.values())
    tot_drag = sum(len(v["drag_ids"]) for v in inv.values())
    tot_idle = sum(len(v["idle_ids"]) for v in inv.values())
    tot_reg = sum(v["registered"] for v in inv.values())
    tot_unreg = sum(v["unregistered"] for v in inv.values())
    print("\n" + "=" * 66)
    print(f"模型 {len(inv)} 个")
    print(f"  Touch* drawable 合计 {tot_touch}")
    print(f"  Drag 类 {tot_drag} / Idle 类 {tot_idle}")
    print(f"  已登记进 HitAreas {tot_reg}  |  **未登记 {tot_unreg}**")
    print(f"  明细 -> {out_path}")
    top = sorted(inv.items(), key=lambda kv: -kv[1]["unregistered"])[:12]
    print("\n漏登记最多的模型（未登记 / 总 Drag+Idle）:")
    for k, v in top:
        print(f"  {k:22s} {v['unregistered']:3d} / {len(v['drag_ids']) + len(v['idle_ids']):3d}"
              f"  (hitareas={v['hitareas']}, drag组={v['drag_groups']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
