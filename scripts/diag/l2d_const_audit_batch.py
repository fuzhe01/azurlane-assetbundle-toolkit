#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""l2d_const_audit_batch.py — EMIT_CONST 重导产物的四项审计（批量，只读）

§134 换入前的强制闸门（WF-41 流程第 2 步），对临时重导目录做对账：
  A binding 对账 : 源 clip genericBindings 数(可解析) == 重导磁盘曲线数（逐 clip）
  B streamed 零回退: 现网旧版每 clip 曲线 Id 集合 ⊆ 重导版同 clip 曲线 Id 集合
  C constant 段格式: Segments 按段长表 {0:2, 1:7, 2:1, 3:3} 可完整解析，无 NaN/inf
  D 总数对账    : 源 bindings 总数 == 磁盘曲线总数

用法:
  py -3 scripts/diag/l2d_const_audit_batch.py                     # 默认 4 样本
  py -3 scripts/diag/l2d_const_audit_batch.py antu_2 ougen_8      # 指定模型
  NEW_DIR=.diag/l2d_const_test OLD_DIR=Output/Live2D \
    py -3 scripts/diag/l2d_const_audit_batch.py <模型...>         # 目录可 env 覆盖
退出码: 0=全 PASS，1=有 FAIL（判据见输出）。
"""
import os, sys, json, binascii
import UnityPy
from UnityPy import config

sys.stdout.reconfigure(encoding="utf-8")
config.FALLBACK_UNITY_VERSION = "2022.3.62f3"

SRC_ROOT = os.environ.get("AL_ASSETS_ROOT", r"D:\Azur Lane Assets") \
    + r"\files\AssetBundles\live2d"
NEW_DIR = os.environ.get("NEW_DIR", os.path.join(".diag", "l2d_const_test"))
OLD_DIR = os.environ.get("OLD_DIR", os.path.join("Output", "Live2D"))
DEFAULT_MODELS = ["antu_2", "aersasi_2", "aersasi_3", "qiershazhi_2"]
PARAM_PREFIX, PART_PREFIX = "Parameters/", "Parts/"


def crc(s):
    return binascii.crc32(s.encode("utf-8")) & 0xFFFFFFFF


def load_hash2(env):
    goname = {}
    for o in env.objects:
        if o.type.name == "GameObject":
            try:
                goname[o.path_id] = o.read().m_Name
            except Exception:
                pass
    hash2 = {}
    for o in env.objects:
        if o.type.name != "MonoBehaviour":
            continue
        try:
            d = o.read()
            sr = getattr(d, "m_Script", None)
            if not sr:
                continue
            sn = getattr(sr.read(), "m_Name", "")
            if sn not in ("CubismParameter", "CubismPart"):
                continue
            tt = o.read_typetree()
            gname = goname.get(tt.get("m_GameObject", {}).get("m_PathID"))
            if not gname:
                continue
            pre = PARAM_PREFIX if sn == "CubismParameter" else PART_PREFIX
            hash2[crc(pre + gname)] = sn
        except Exception:
            continue
    return hash2


def parse_segments(segs):
    """返回 (ok, 段数)。段长: id0=InverseStepped2, id1=Bezier7, id2=Stepped1, id3=Linear3。"""
    if not segs or len(segs) < 2:
        return False, 0
    for v in segs:
        if v != v or v in (float("inf"), float("-inf")):
            return False, 0
    pos, n = 2, 0
    L = {0: 2, 1: 7, 2: 1, 3: 3}
    while pos < len(segs):
        sid = segs[pos]
        if sid not in L:
            return False, 0
        pos += 1 + L[sid]
        n += 1
    return pos == len(segs), n


def read_motion(fp):
    if not os.path.isfile(fp):
        return None
    try:
        return json.load(open(fp, encoding="utf-8"))
    except Exception:
        return None


def audit_model(name):
    env = UnityPy.load(os.path.join(SRC_ROOT, name))
    hash2 = load_hash2(env)
    clips = [o.read() for o in env.objects if o.type.name == "AnimationClip"]
    res = {"model": name, "clips": 0, "A_fail": [], "B_fail": [], "C_fail": [],
           "src_bindings": 0, "disk_curves": 0, "old_curves": 0, "seg_total": 0}
    for c in clips:
        cn = c.m_Name
        gb = list(c.m_ClipBindingConstant.genericBindings)
        resolvable = [b for b in gb
                      if hash2.get(getattr(b, "path", 0) & 0xFFFFFFFF)]
        res["clips"] += 1
        res["src_bindings"] += len(resolvable)

        new_m = read_motion(os.path.join(NEW_DIR, name, "motion", cn + ".motion3.json"))
        old_m = read_motion(os.path.join(OLD_DIR, name, "motion", cn + ".motion3.json"))
        if new_m is None:
            res["A_fail"].append((cn, "missing new file"))
            continue
        new_curves = new_m.get("Curves", [])
        res["disk_curves"] += len(new_curves)
        new_ids = {cur.get("Id") for cur in new_curves}

        if len(new_curves) != len(resolvable):
            res["A_fail"].append((cn, f"binding={len(resolvable)} disk={len(new_curves)}"))

        if old_m is not None:
            old_curves = old_m.get("Curves", [])
            res["old_curves"] += len(old_curves)
            missing = {cur.get("Id") for cur in old_curves} - new_ids
            if missing:
                res["B_fail"].append((cn, f"lost {len(missing)}: {sorted(missing)[:3]}"))

        for cur in new_curves:
            ok, n = parse_segments(cur.get("Segments"))
            res["seg_total"] += n
            if not ok:
                res["C_fail"].append((cn, cur.get("Id")))
                break
    return res


def main():
    models = sys.argv[1:] or DEFAULT_MODELS
    all_res = []
    grand = {"clips": 0, "src_bindings": 0, "disk_curves": 0, "old_curves": 0}
    for m in models:
        r = audit_model(m)
        all_res.append(r)
        a, b, c = len(r["A_fail"]), len(r["B_fail"]), len(r["C_fail"])
        for k in grand:
            grand[k] += r[k]
        verdict = "PASS" if not (a or b or c) else "FAIL"
        print(f"[{verdict}] {m:<14} clips={r['clips']:<4} "
              f"src_bindings={r['src_bindings']:<6} disk_curves={r['disk_curves']:<6} "
              f"old(streamed)={r['old_curves']:<6} "
              f"A_fail={a} B_fail={b} C_fail={c}")
        for kind in ("A_fail", "B_fail", "C_fail"):
            for item in r[kind][:5]:
                print(f"    {kind}: {item}")
    total_ok = (grand["src_bindings"] == grand["disk_curves"]
                and all(not (len(r["A_fail"]) or len(r["B_fail"]) or len(r["C_fail"]))
                        for r in all_res))
    print("\n===== D 总数对账 =====")
    print(f"  源 bindings 总数 = {grand['src_bindings']}")
    print(f"  磁盘曲线总数     = {grand['disk_curves']}")
    print(f"  现网旧曲线(对照) = {grand['old_curves']}")
    print(f"  总判据: {'PASS' if total_ok else 'FAIL'}")
    out = os.path.join(".diag", "l2d_const_audit_batch.json")
    json.dump(all_res, open(out, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"详细结果: {out}")
    sys.exit(0 if total_ok else 1)


if __name__ == "__main__":
    main()