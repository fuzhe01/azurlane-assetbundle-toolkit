#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dump Spine prefab 的 RectTransform 树：查「多层的偏移到底存在哪一级」。

**为什么需要**：2026-10-04 实测 `tianjinfeng_2` 五层的 `anchoredPosition` 全是 `[0,0]`、
`localScale` 全 `[1,1]`、`rotZ` 全 `-0.0`（prefab 实测），但这五层渲出来**互相错开**
（笼子偏右上、角色部件在左下）⇒ 偏移量在**提取时根本没被读到**。

关键点：`m_AnchoredPosition` 是**相对父节点**的。`skel_layers()` 只给 SkeletonGraphic
自己的 GameObject 建了 GO→RectTransform 直连映射（`rect_of_go`），**父链上的偏移没读**
⇒ 若多层挂在不同父节点下、而父节点各有偏移，子节点各自的 `[0,0]` 就会叠出不同的实际位置。

本脚本 dump：
1. 每个 SkeletonGraphic 的**自身** RectTransform；
2. 从它一路往上到根的**父链每一级**（名字 + anchoredPosition + localScale + rotation + size）
   —— 偏移若存在，判据是「父链上某级有非零 anchoredPosition 且各层深度不同」。

**只读**，不写任何资产。

**用法**：
    py -3 scripts/diag/spine_transform_tree.py spinepainting/tianjinfeng_2
    py -3 scripts/diag/spine_transform_tree.py spinepainting/tianjinfeng_2 --json
"""

import argparse
import json
import math
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "scripts"))
import paths as P  # noqa: E402  仓库根/资产根出口，AL_ASSETS_ROOT 可覆盖
import UnityPy  # noqa: E402
from UnityPy import config  # noqa: E402

config.FALLBACK_UNITY_VERSION = "2022.3.62f3"


def _resolve(prefab_bundle: str) -> str:
    """把 bundle 名解析成盘上路径（与 compose_paintings_v2.load_bundle 同一套规则）。"""
    p = os.path.join(P.AB, prefab_bundle.lower().replace("/", os.sep))
    if os.path.isfile(p):
        return p
    raise SystemExit("[缺] %s（AB=%s）" % (prefab_bundle, P.AB))


def _f(v, n=3):
    try:
        return round(float(v), n)
    except Exception:
        return None


def dump(prefab_bundle: str):
    env = UnityPy.load(_resolve(prefab_bundle))
    objs = {o.path_id: o for o in env.objects}

    # GO path_id -> GameObject；RectTransform path_id -> (go_path_id, parent_path_id)
    go_name, rect_of_go, rect_info = {}, {}, {}
    for o in env.objects:
        if o.type.name == "GameObject":
            try:
                go_name[o.path_id] = str(o.read().m_Name)
            except Exception:
                go_name[o.path_id] = "?"
        elif o.type.name in ("RectTransform", "Transform"):
            try:
                d = o.read()
            except Exception:
                continue
            gid = getattr(getattr(d, "m_GameObject", None), "m_PathID", 0)
            pid = getattr(getattr(d, "m_Father", None), "m_PathID", 0)
            rect_info[o.path_id] = (gid, pid)
            if gid:
                rect_of_go[gid] = o.path_id

    scr = {}
    for o in env.objects:
        if o.type.name == "MonoScript":
            try:
                scr[o.path_id] = str(o.read().m_Name)
            except Exception:
                pass

    def rect_dump(rid):
        """返回 RectTransform 的可读字段；Transform 无这些字段时返回 None。"""
        o = objs.get(rid)
        if o is None:
            return None
        try:
            r = o.read()
        except Exception:
            return None
        out = {"path_id": rid, "class": o.type.name}
        for f in ("m_AnchoredPosition", "m_LocalScale", "m_LocalPosition"):
            v = getattr(r, f, None)
            if v is not None and hasattr(v, "x"):
                out[f] = [_f(v.x, 2), _f(v.y, 2), _f(getattr(v, "z", 0.0), 2)]
        q = getattr(r, "m_LocalRotation", None)
        if q is not None:
            try:
                out["rotZ_deg"] = _f(math.degrees(2 * math.atan2(float(q.z), float(q.w))), 2)
            except Exception:
                pass
        for f in ("m_SizeDelta", "m_AnchorMin", "m_AnchorMax", "m_Pivot"):
            v = getattr(r, f, None)
            if v is not None and hasattr(v, "x"):
                out[f] = [_f(v.x, 2), _f(v.y, 2)]
        return out

    layers = []
    for o in env.objects:
        if o.type.name != "MonoBehaviour":
            continue
        try:
            d = o.read()
        except Exception:
            continue
        if scr.get(getattr(getattr(d, "m_Script", None), "m_PathID", 0)) != "SkeletonGraphic":
            continue
        gid = getattr(getattr(d, "m_GameObject", None), "m_PathID", 0)
        node = go_name.get(gid, "?")
        own = rect_dump(rect_of_go.get(gid, 0))
        # 父链：从本节点往上
        chain, cur, depth = [], rect_of_go.get(gid, 0), 0
        while cur and depth < 40:
            gid2, pid = rect_info.get(cur, (0, 0))
            chain.append({
                "depth": depth,
                "name": go_name.get(gid2, "?"),
                "rect": rect_dump(cur),
            })
            if not pid or pid == cur:
                break
            cur, depth = pid, depth + 1
        layers.append({
            "node": node,
            "own": own,
            "chainLen": len(chain),
            "chain": chain,
        })
    layers.sort(key=lambda x: x["node"])
    return layers


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("bundle", help="prefab bundle 名，如 spinepainting/tianjinfeng_2")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    layers = dump(args.bundle)
    if not args.json:
        print("=== %s：%d 个 SkeletonGraphic ===" % (args.bundle, len(layers)))
        for L in layers:
            print("\n● %s" % L["node"])
            ow = L["own"] or {}
            print("   自身 anchoredPosition=%s localScale=%s rotZ=%s"
                  % (ow.get("m_AnchoredPosition"), ow.get("m_LocalScale"), ow.get("rotZ_deg")))
            print("   父链 %d 级：" % L["chainLen"])
            for c in L["chain"]:
                r = c["rect"] or {}
                print("     d%-2d %-26s ap=%-18s ls=%-14s rotZ=%-8s size=%s"
                      % (c["depth"], c["name"][:26], r.get("m_AnchoredPosition"),
                         r.get("m_LocalScale"), r.get("rotZ_deg"), r.get("m_SizeDelta")))
    else:
        print(json.dumps(layers, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
