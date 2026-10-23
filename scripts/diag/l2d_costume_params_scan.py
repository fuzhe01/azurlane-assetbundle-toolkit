# -*- coding: utf-8 -*-
"""l2d_costume_params_scan.py — 全库扫描「换装/装饰类参数」，产出互动区候选表。

为什么需要：这类参数（衣服 Cloth*、丝袜 Stock*、鞋 ShoseOff、眼镜、戒指 Paramring、
配饰 Stock1/2…）在游戏里是**玩家可点击/拖动改变的装扮状态**，对应我们前端要接的
「互动区」。它们的共同特征：
  1) 在多个动作里被**定值曲线**锁住（不是被动画驱动做连续变化）；
  2) 值域小（0..1 或 0..10 这类离散档位）；
  3) 参数名/显示名带语义（Cloth/Stock/Shose/Eye/Ring/Hat…）。

⚠️ 光靠名字猜会漏也会错。本脚本只做**候选筛查**，每条必须再用运行时 `--findop`
反查「它到底控制哪些 mesh」才能接线（判据见 docs/TROUBLESHOOTING.md §139）。

用法:
  py -3.14 scripts/diag/l2d_costume_params_scan.py            # 全库
  py -3.14 scripts/diag/l2d_costume_params_scan.py ougen_8    # 单模型
输出: .diag/costume_params.json + 终端摘要（按参数名分组统计）
"""
import sys, os, json, glob, re, collections

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LIVE2D = os.path.join(ROOT, "Output", "Live2D")
OUT = os.path.join(ROOT, ".diag", "costume_params.json")

# 语义关键词（大小写不敏感）。
# ⚠️ 眼睛类**必须保留**（2026-10-23 用户指出）：瞳孔形状/眼罩/瞳色也是玩家可调外观，
#    它们在游戏里同样由定值曲线锁定、可被互动区切换。只把「纯动画量」当噪声：
#    眨眼开合(ParamEyeLOpen/ROpen)、眼球转动(ParamEyeBallX/Y)、眉/嘴/呼吸/角度。
NOISE_EXACT_KW = ["brow", "mouth", "breath", "angle", "tear", "cheek", "sweat"]
NOISE_REGEX = [
    r"^parameyelopen$", r"^parameyeropen$", r"^parameyelballx$", r"^parameyelbally$",
    r"^parameyelballlx$", r"^parameyelballly$", r"^parameyelballrx$", r"^parameyelballry$",
]
KW_SWITCH = [
    ("cloth", "衣服"), ("stock", "丝袜"), ("shose", "鞋"), ("shoe", "鞋"),
    ("eye", "眼镜/眼罩"), ("glass", "眼镜"), ("ring", "戒指"), ("hat", "帽子"),
    ("crown", "头冠"), ("veil", "面纱"), ("cape", "披风"), ("coat", "外套"),
    ("glove", "手套"), ("earring", "耳环"), ("necklace", "项链"), ("ribbon", "缎带"),
    ("belt", "腰带"), ("armor", "装甲"), ("weapon", "武器"), ("sword", "刀剑"),
    ("wing", "翅膀"), ("horn", "角"), ("tail", "尾巴"), ("mask", "面具"),
    ("skirt", "裙"), ("apron", "围裙"), ("jacket", "夹克"), ("bra", "内衣"),
    ("panty", "内裤"), ("sock", "袜"), ("boot", "靴"), ("heels", "高跟"),
    ("hairpin", "发饰"), ("badge", "徽章"), ("medal", "勋章"), ("scarf", "围巾"),
    ("hx", "屏蔽条"), ("shop", "商店"),
    # 眼睛/瞳孔类可调外观（用户 2026-10-23 指出：瞳孔形状也可调）
    ("pupil", "瞳孔"), ("iris", "虹膜"), ("eyeshape", "眼型"), ("eyeballshape", "瞳孔形状"),
    ("parameyesize", "眼睛大小"), ("eyesize", "眼睛大小"), ("eye", "眼睛"),
    ("sclera", "眼白"), ("eyelash", "睫毛"), ("eyeshadow", "眼影"), ("eyeline", "眼线"),
]
# 已经被前端 STATE_TOGGLES 接过的（避免重复报告）
KNOWN = {
    "ougen_8": {"ShoseOff"},
    "aersasi_2": {"Param24"},
}


def parse_curve_values(segs):
    """从 motion3.json 的 Segments 数组里**只提取曲线值**（不含时间轴）。

    段格式（Cubism motion3.json）：
      segs[0] = 首点时间(通常 0)
      segs[1] = 首点值
      之后每段：type, [控制点...], 末点时间, 末点值
        type 1 = 直线(1 个控制点时间? 实际形状: type, t_end, v_end)
        type 2 = 贝塞尔(type, c1t,c1v, c2t,c2v, t_end, v_end)
        type 3 = 阶梯(type, t_end, v_end)
        type 0 = 台阶(type, t_end, v_end)
    简化且稳妥的做法：从 segs[1] 开始，按段的 type 跳过对应数量的值，
    每段最后一个数才是"值"。这里用 Cubism 官方语义逐段走。
    """
    vals = []
    if len(segs) < 2:
        return vals
    vals.append(segs[1])
    i = 2
    n = len(segs)
    while i < n:
        t = segs[i]
        try:
            t = int(t)
        except Exception:
            break
        if t == 1 or t == 0 or t == 3:      # 直线 / 台阶：type, t_end, v_end
            if i + 2 >= n:
                break
            vals.append(segs[i + 2])
            i += 3
        elif t == 2:                        # 贝塞尔：type, c1t,c1v, c2t,c2v, t_end, v_end
            if i + 6 >= n:
                break
            vals.append(segs[i + 6])
            i += 7
        else:
            break
    return vals


def ranges_of(mdir):
    """扫描一个模型全部 motion，返回 {参数: {'vals':set, 'groups':[...], 'nseg':[...]}}"""
    info = collections.defaultdict(lambda: {"vals": set(), "groups": [], "nseg": []})
    for p in glob.glob(os.path.join(mdir, "*.motion3.json")):
        g = os.path.basename(p)[:-len(".motion3.json")]
        try:
            j = json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
        for c in j.get("Curves") or []:
            if (c.get("Target") or "") != "Parameter":
                continue
            pid = c.get("Id")
            segs = c.get("Segments") or []
            if not pid or len(segs) < 3:
                continue
            vals = parse_curve_values(segs)
            if not vals:
                continue
            e = info[pid]
            e["vals"].update(round(v, 3) for v in vals)
            e["groups"].append(g)
            e["nseg"].append(len(segs))
    return info


def classify(name, e):
    """返回 (类别, 理由) 或 (None, None)。

    核心判据不是「名字像换装」，而是**它真的在不同动作间被锁成不同档位**：
      - 只有 1 个取值 ⇒ 所有动作都把它钉成同一个值，玩家没有可调空间，不是互动项
        （2026-10-23 实测：ParamEyeBallX 在 260 个模型里值域都是 0..0，属纯噪声）；
      - 2 档 ⇒ 典型开关（0/1、0/10）；
      - 3~4 档且跨度小 ⇒ 多态开关（如 0/1/2 表情档）；
      - 5~12 档 ⇒ 渐变/滑杆类。
    """
    vals = sorted(e["vals"])
    if not vals:
        return None, None
    lo, hi = vals[0], vals[-1]
    span = hi - lo
    distinct = len(vals)
    if distinct <= 1:
        return None, None                       # 恒定 = 无可调空间
    if distinct == 2:
        return "switch", f"值域 {lo}..{hi}（2 档）"
    if distinct <= 4 and span <= 12:
        return "switch", f"值域 {lo}..{hi}（{distinct} 档）"
    if distinct <= 12 and span <= 40:
        return "slider", f"值域 {lo}..{hi}（{distinct} 档）"
    return "unknown", f"值域 {lo}..{hi}（{distinct} 档 / {len(e['groups'])} 组）"


def main():
    only = [a for a in sys.argv[1:] if not a.startswith("--")]
    models = only or sorted(d for d in os.listdir(LIVE2D)
                            if os.path.isdir(os.path.join(LIVE2D, d)))
    out = {}
    kw_hits = collections.Counter()
    for i, m in enumerate(models, 1):
        mdir = os.path.join(LIVE2D, m, "motion")
        if not os.path.isdir(mdir):
            continue
        info = ranges_of(mdir)
        cand = {}
        for pid, e in info.items():
            low = pid.lower()
            if any(n in low for n in NOISE_EXACT_KW):
                continue
            if any(re.match(p, low) for p in NOISE_REGEX):
                continue
            labels = [zh for kw, zh in KW_SWITCH if kw.lower() in low]
            if not labels:
                continue
            kind, why = classify(pid, e)
            if not kind:
                continue
            cand[pid] = {
                "label": "/".join(sorted(set(labels))),
                "kind": kind,
                "why": why,
                "n_groups": len(e["groups"]),
                "vals": sorted(e["vals"])[:12],
                "known": pid in KNOWN.get(m, set()),
            }
            kw_hits["/".join(sorted(set(labels)))] += 1
        if cand:
            out[m] = cand
        if i % 40 == 0:
            print(f"... {i}/{len(models)}", flush=True)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print("\n" + "=" * 64)
    print(f"含换装类参数的模型 {len(out)} 个；明细 -> {OUT}")
    tot = sum(len(v) for v in out.values())
    n_switch = sum(1 for v in out.values() for x in v.values() if x["kind"] == "switch")
    n_slider = sum(1 for v in out.values() for x in v.values() if x["kind"] == "slider")
    print(f"候选参数 {tot} 个（开关型 {n_switch} / 渐变型 {n_slider}）")
    print("\n按语义分组（命中次数）:")
    for k, n in kw_hits.most_common(20):
        print(f"  {k:14s} {n:5d}")
    print("\n前 12 个模型示例:")
    for m in list(out)[:12]:
        items = list(out[m].items())[:6]
        print(f"  {m}: " + ", ".join(f"{k}[{v['kind']}]" for k, v in items)
              + (f" …共{len(out[m])}个" if len(out[m]) > 6 else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
