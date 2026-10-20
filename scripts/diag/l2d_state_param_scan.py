# -*- coding: utf-8 -*-
"""Live2D 状态切换参数扫描器（§132）：找出「游戏代码 set 的纯状态参数」候选。

背景（ougen_8 取证，docs/TROUBLESHOOTING.md §132）：
  部分玩家交互不是播 motion，而是切换一个**状态参数**（首例 ShoseOff「脱鞋」：
  55 个 motion 零曲线驱动，游戏代码直接 set，moc3 keyform 随参数值渐变产生局部过渡动画）。
  误当「动作」处理会播错内容（touch_drag1..3 实为拖身体的软体回弹）。

判据（三条同时满足才算候选）：
  1. 零 motion 驱动：该参数不在任何 motion3.json 曲线的 Id 里；
  2. 零 physics 驱动：不在 physics3.json 任何 Output 的 Destination.Id 里；
  3. 开关型显示名：CubismDisplayInfoParameterName 的 Name 命中关键词
     （脱|穿|off|on|切换|切|开关——大小写不敏感；显示名缺失时按参数名本身判）。

输出（默认）：候选表 = 模型 | 参数 | 显示名 | default | TouchDrag 区数。
  --all   额外打印每模型全部零驱动参数（排查用，量大）
  --models a b c   只扫指定模型（默认 Output/Live2D 全部）

用法：
  py -3 scripts/diag/l2d_state_param_scan.py --models ougen_8
  py -3 scripts/diag/l2d_state_param_scan.py            # 全库
"""
import sys, os, re, json
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
LIVE2D = os.environ.get("L2D_OUT_DIR") or os.path.join(ROOT, "Output", "Live2D")
BUNDLE_DIR = os.path.join(ROOT, "files", "AssetBundles", "live2d")

import UnityPy
from UnityPy import config
config.FALLBACK_UNITY_VERSION = "2022.3.62f3"

KEYWORDS = ("脱", "穿", "off", "on", "切换", "开关", "鞋", "袜")


def motion_driven_ids(model_dir):
    ids = set()
    mdir = os.path.join(model_dir, "motion")
    if not os.path.isdir(mdir):
        return ids
    for fn in os.listdir(mdir):
        if not fn.endswith(".motion3.json"):
            continue
        try:
            d = json.load(open(os.path.join(mdir, fn), encoding="utf-8"))
        except Exception:
            continue
        for c in d.get("Curves", []):
            ids.add(c.get("Id", ""))
    return ids


def physics_driven_ids(model_dir, key):
    ids = set()
    p = os.path.join(model_dir, key + ".physics3.json")
    if not os.path.isfile(p):
        return ids
    try:
        d = json.load(open(p, encoding="utf-8"))
    except Exception:
        return ids
    for st in d.get("PhysicsSettings", []):
        for out in st.get("Outputs", []):
            dst = out.get("Destination", {}).get("Id", "")
            if dst:
                ids.add(dst)
    return ids


def bundle_params(bundle_path):
    """[(参数Id, 显示名, default值, raycastableGO名列表)] —— 经 GameObject join。"""
    out = []
    try:
        env = UnityPy.load(bundle_path)
    except Exception as e:
        return None, None, str(e)
    go_names = {}
    for o in env.objects:
        if o.type.name == "GameObject":
            try:
                go_names[o.path_id] = o.read().m_Name
            except Exception:
                pass
    param_go, disp_by_go, ray_gos = {}, {}, []
    for o in env.objects:
        if o.type.name != "MonoBehaviour":
            continue
        d = o.read()
        sref = getattr(d, "m_Script", None)
        try:
            sname = getattr(sref.read(), "m_Name", "") if sref else ""
        except Exception:
            sname = ""
        if sname not in ("CubismParameter", "CubismDisplayInfoParameterName", "CubismRaycastable"):
            continue
        try:
            tt = o.read_typetree()
        except Exception:
            continue
        go = tt.get("m_GameObject", {}).get("m_PathID")
        if go is None:
            continue
        if sname == "CubismParameter":
            param_go[go] = tt.get("Value", 0.0)
        elif sname == "CubismDisplayInfoParameterName":
            disp_by_go[go] = tt.get("Name") or ""
        else:
            ray_gos.append(go_names.get(go, ""))
    for go, val in param_go.items():
        if go in go_names:
            out.append((go_names[go], disp_by_go.get(go, ""), val))
    return out, ray_gos, None


def is_switch_like(pid, disp):
    text = (disp or "") + (pid or "")
    tl = text.lower()
    return any(k in text or k in tl for k in KEYWORDS)


def main():
    args = sys.argv[1:]
    show_all = "--all" in args
    models = [a for a in args if not a.startswith("--")]
    if not models:
        models = sorted(n for n in os.listdir(LIVE2D)
                        if os.path.isfile(os.path.join(LIVE2D, n, n + ".model3.json")))
    print(f"扫描 {len(models)} 个模型（判据：零 motion 驱动 + 零 physics 驱动 + 开关型显示名）")
    print("=" * 96)
    n_cand = 0
    for name in models:
        mdir = os.path.join(LIVE2D, name)
        bundle = os.path.join(BUNDLE_DIR, name)
        if not os.path.isfile(bundle):
            continue
        driven = motion_driven_ids(mdir) | physics_driven_ids(mdir, name)
        params, rays, err = bundle_params(bundle)
        if err or params is None:
            print(f"  {name}: bundle 读取失败 {err}")
            continue
        ray_drag = [r for r in rays if re.fullmatch(r"(?i)touchdrag\d+", r or "")]
        zero = [(p, disp, val) for (p, disp, val) in params
                if p and p not in driven]
        cand = [(p, disp, val) for (p, disp, val) in zero if is_switch_like(p, disp)]
        if cand:
            n_cand += len(cand)
            print(f"  {name}（TouchDrag 区 {len(ray_drag)} 个，零驱动参数 {len(zero)}，候选 {len(cand)}）:")
            for p, disp, val in sorted(cand):
                print(f"      {p:14s} 显示名={disp!r:20s} default={val}")
        elif show_all:
            print(f"  {name}（TouchDrag 区 {len(ray_drag)} 个，零驱动参数 {len(zero)}，无候选）")
    print("=" * 96)
    print(f"候选合计 {n_cand} 条 —— 高置信度者需人工对照游戏画面确认触发区与语义（扫描器只能给参数层证据）。")


if __name__ == "__main__":
    main()