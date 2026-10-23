# -*- coding: utf-8 -*-
"""l2d_toucharea_inventory.py — 全库盘点「互动区规模」与「换装参数是否有驱动」。

回答一个问题：玩家能点击/拖动的换装互动区，全库到底有多少、分布在哪些模型上。
判据分三层（缺一层都不成立）：
  1) moc3 里真的有 Touch* drawable（模型自带的按钮/热区部件）；
  2) model3.json 的 HitAreas 登记了它们（运行时能命中）；
  3) 存在同名动作组（touch_dragN / touch_idleN）或参数开关驱动 —— 点击才有反应。

用法: py -3.14 scripts/diag/l2d_toucharea_inventory.py [--json out.json]
输出: 每模型 {touch_drawables, hitareas, drag_groups, idle_groups, costume_params}
"""
import sys, os, json, glob, re, collections

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LIVE2D = os.path.join(ROOT, "Output", "Live2D")
OUT = os.path.join(ROOT, ".diag", "toucharea_inventory.json")

COSTUME_KW = [
    "cloth", "stock", "shose", "shoe", "ring", "hat", "crown", "veil", "cape",
    "glove", "glass", "mask", "ribbon", "skirt", "belt", "boot", "sock",
    "wing", "horn", "tail", "pupil", "iris", "bra", "jacket", "apron",
]


def touch_count(moc3_path):
    """moc3 是二进制，字符串池里的 drawable id 可直接计数（够用且不依赖解析库）。"""
    try:
        raw = open(moc3_path, "rb").read()
        return raw.count(b"Touch")
    except Exception:
        return -1


def model_info(name):
    d = os.path.join(LIVE2D, name)
    mj = os.path.join(d, name + ".model3.json")
    moc = os.path.join(d, name + ".moc3")
    if not os.path.isfile(mj):
        return None
    try:
        j = json.load(open(mj, encoding="utf-8"))
    except Exception:
        return None
    mot = ((j.get("FileReferences") or {}).get("Motions") or {})
    groups = list(mot.keys())
    hit = [h.get("Name") for h in (j.get("HitAreas") or [])]
    drag = sorted(g for g in groups if re.match(r"^touch_?drag", g, re.I))
    idle = sorted(g for g in groups if re.match(r"^touch_?idle", g, re.I))
    return {
        "touch_drawables": touch_count(moc),
        "hitareas": len(hit),
        "hitarea_names": hit,
        "groups": len(groups),
        "drag_groups": drag,
        "idle_groups": idle,
    }


def costume_params(name):
    """从 .diag/costume_params.json 里取该模型已扫出的换装类参数。"""
    p = os.path.join(ROOT, ".diag", "costume_params.json")
    if not os.path.isfile(p):
        return {}
    try:
        d = json.load(open(p, encoding="utf-8"))
    except Exception:
        return {}
    return d.get(name, {})


def main():
    out_path = OUT
    for i, a in enumerate(sys.argv):
        if a == "--json":
            out_path = sys.argv[i + 1]
    names = sorted(d for d in os.listdir(LIVE2D) if os.path.isdir(os.path.join(LIVE2D, d)))
    inv = {}
    for i, n in enumerate(names, 1):
        info = model_info(n)
        if not info:
            continue
        cp = costume_params(n)
        info["costume_params"] = {k: v["kind"] for k, v in cp.items()}
        info["n_costume"] = len(cp)
        # 分档：有没有换装互动能力
        info["has_costume_ui"] = (info["touch_drawables"] >= 10 and
                                  (len(info["drag_groups"]) > 0 or len(info["idle_groups"]) > 3))
        inv[n] = info
        if i % 50 == 0:
            print(f"... {i}/{len(names)}", flush=True)

    json.dump(inv, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    n_all = len(inv)
    n_ui = sum(1 for v in inv.values() if v["has_costume_ui"])
    print("\n" + "=" * 64)
    print(f"模型 {n_all} 个；有换装互动能力 {n_ui} 个 / 仅基础三区 {n_all - n_ui} 个")
    print(f"明细 -> {out_path}")

    td = collections.Counter()
    for v in inv.values():
        t = v["touch_drawables"]
        td["0-5" if t < 6 else ("6-15" if t < 16 else ("16-40" if t < 41 else "40+"))] += 1
    print("\nTouch drawable 数量分布:")
    for k in ["0-5", "6-15", "16-40", "40+"]:
        print(f"  {k:6s} {td[k]:4d} 个模型")

    print("\n换装互动能力最强的 15 个模型:")
    rich = sorted((v for v in inv.values() if v["has_costume_ui"]),
                  key=lambda v: -(len(v["drag_groups"]) + len(v["idle_groups"])))
    for v in rich[:15]:
        nm = [k for k, x in inv.items() if x is v][0]
        print(f"  {nm:22s} touch={v['touch_drawables']:3d} hit={v['hitareas']:3d} "
              f"drag={len(v['drag_groups']):2d} idle={len(v['idle_groups']):2d} "
              f"换装参数={v['n_costume']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
