# -*- coding: utf-8 -*-
"""
动态立绘（Spine）提取 v2 —— 依赖表驱动，兼容两种包结构：
  A. 内联型（如 2b_2）：主包直接含 .skel/.atlas TextAsset + Texture2D
  B. 分离型（如 aersasi）：主包只有 UI 结构，资源在 spinepainting/<name>_res

atlas 页纹理若不在以上两包内，按 dependencies 官方依赖表去外部包
（artresource/effect/*、ui/commonui_atlas 等）找同名 Texture2D 补齐。

输出（DeskSpine / spine-webgl 兼容目录结构）:
  Output/Spine_v2/<name>/<name>.skel
  Output/Spine_v2/<name>/<name>.atlas      （页名已重写为本地 png 文件）
  Output/Spine_v2/<name>/<page>.png

用法:
  python extract_spine_v2.py               # 全部
  python extract_spine_v2.py aersasi 2b_2  # 指定
  python extract_spine_v2.py --parts-only  # 只给已导出的目录补 parts.json（不重解码贴图）

  ⚠️ **写向是 `Output/Spine_v2`（正式区）时必须给 `--bak <目录>`**，否则一个文件都不写。
     `Output/` 不进 git ⇒ 被覆写的旧字节只有这一份备份能捞回来。
     只补 parts.json 时给 `--bak Output/_OLD_bak/spine_parts_<日期>/` 就够（每皮肤几十 KB）；
     整目录重提取会连 skel/atlas/png 一起重写，备份量 ≈ 该批现有产物大小。
     写临时区（`--out .diag/pipeline/Spine_v2`）不需要备份 —— 正式区还没动。
"""
import hashlib
import json
import os
import re
import shutil
import sys
import time

import UnityPy
from UnityPy import config
from UnityPy.export.Texture2DConverter import get_image_from_texture2d
import sys as _p_sys, os as _p_os
_p_sys.path.insert(0, _p_os.path.dirname(_p_os.path.abspath(__file__)))
import paths as P  # 仓库根与外部工具位置：见 scripts/paths.py（AL_ASSETS_ROOT 可覆盖）

config.FALLBACK_UNITY_VERSION = "2022.3.62f3"

AB_ROOT = P.AB
MANIFEST_PATH = P.MANIFEST_PATH
OUT_ROOT = P.SPINE_OUT

manifest = json.load(open(MANIFEST_PATH, encoding="utf-8"))
_env_cache = {}


def load_bundle(name):
    if name in _env_cache:
        return _env_cache[name]
    path = os.path.join(AB_ROOT, name.lower().replace("/", os.sep))
    env = None
    if os.path.isfile(path):
        try:
            env = UnityPy.load(path)
        except Exception as e:
            print(f"  ! {name}: {e}")
    _env_cache[name] = env
    return env


def collect_assets(bundle_names):
    """从若干 bundle 收集 TextAsset(skel/atlas) 与 Texture2D。"""
    texts, textures = {}, {}
    for bn in bundle_names:
        env = load_bundle(bn)
        if not env:
            continue
        for o in env.objects:
            try:
                if o.type.name == "TextAsset":
                    d = o.read()
                    texts[str(d.m_Name)] = d.m_Script
                elif o.type.name == "Texture2D":
                    d = o.read()
                    textures[str(d.m_Name)] = o
            except Exception:
                pass
    return texts, textures


PAGE_RE = re.compile(r"^([^\s/\\:]+\.png)\s*$", re.M)


def atlas_pages(atlas_text):
    """解析 atlas 文本中的页纹理文件名列表（页名独占一行、后跟 size:）。"""
    pages = []
    lines = atlas_text.splitlines()
    for i, ln in enumerate(lines):
        s = ln.strip()
        if s.endswith(".png") and i + 1 < len(lines) and lines[i + 1].strip().startswith("size:"):
            if s not in pages:
                pages.append(s)
    return pages


def to_bytes(script):
    if isinstance(script, (bytes, bytearray)):
        return bytes(script)
    return str(script).encode("utf-8", "surrogateescape")


def _md5(p):
    h = hashlib.md5()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def is_production(out_root):
    """写向是否落在正式产物区（`Output/` 之下）。临时区 `.diag/pipeline/` 不算。"""
    a = os.path.abspath(out_root)
    b = os.path.abspath(P.OUT)
    return a == b or a.startswith(b + os.sep)


def snapshot_prior(out_dir, name, bak_root, only, rec):
    """覆写前把**这次真的会被写到的**现有文件逐份取走前身字节，并当场核对 md5 全等。

    `only` 传文件名列表时只备份这些（`--parts-only` 只写 parts.json）；
    传 None 表示整目录都要重写 ⇒ 整目录都取。
    备份不是"装个样子"：md5 与原件不等就直接抛错停下，宁可什么都不写。
    """
    if not os.path.isdir(out_dir):
        return
    targets = []
    if only is None:
        for dp, _dn, fs in os.walk(out_dir):
            for f in sorted(fs):
                targets.append(os.path.join(dp, f))
    else:
        targets = [os.path.join(out_dir, f) for f in only
                   if os.path.isfile(os.path.join(out_dir, f))]
    for src in targets:
        rel = os.path.relpath(src, out_dir).replace(os.sep, "/")
        dst = os.path.join(bak_root, *f"{name}/{rel}".split("/"))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(src, dst)
        prior = _md5(src)
        if _md5(dst) != prior:
            raise RuntimeError(f"换前备份与原件 md5 不等，拒绝覆写: {src}")
        rec.append({"target": f"{name}/{rel}", "md5": prior, "size": os.path.getsize(src)})


def refuse_without_backup(out_root):
    print(f"[FAIL] 写向是正式区 {out_root}，但没给 --bak —— 拒绝覆写。\n"
          f"       Output/ 不进 git，被盖掉的旧字节只有备份这一份能捞回来（§111 第 4 节）。\n"
          f"       只补 parts.json： --bak Output/_OLD_bak/spine_parts_<日期>/\n"
          f"       整批重提取：     先 --out .diag/pipeline/Spine_v2 写临时区，审完再走 painting_swap_in 换入")
    return 2


def write_parts(name, out_dir):
    """把游戏 prefab 真正挂着的层列表落进导出目录，作为分层的**唯一权威**。

    为什么必须是这一份而不是 `glob('*.skel')`：同目录里还躺着 `_hx`（和谐版）等**变体**
    的 skel，它们不是层、是另一张画；`_hx` 是替换某一层而非多加一层。画廊此前按 glob
    决定分层，viewer 与 cg_export.html 共用那份列表 ⇒ 本体与和谐版被叠在一起画，
    实测 234 个目录里 30 个多画、15 对 CG 逐像素完全相同（`docs/TROUBLESHOOTING.md` §58）。

    读不到层列表时**不写文件**，让下游 `build_gallery_index.py` 大声报错 ——
    写一个空壳 parts.json 等于把同一个 bug 换个地方留着。
    返回 (payload, "") 或 (None, 原因) —— 原因要说准，别把「层文件没导出」
    报成「读不到 prefab」（本轮真错过一次）。
    """
    import compose_paintings_v2 as C
    layers = [nd for nd in C.skel_layers(f"spinepainting/{name}") if nd["layer"]]
    if not layers:
        return None, "prefab 里没有可解析的 SkeletonGraphic 层"
    have = {x[:-5] for x in os.listdir(out_dir) if x.endswith(".skel")}
    missing = [nd["layer"] for nd in layers if nd["layer"] not in have]
    if missing:
        # 层文件不在盘上：写出来只会让前端 fetch 404，宁可报错
        # （实测 `fulangxisike_2` 就是这种空壳目录：只有一个散 PNG、没有任何 .skel）
        return None, f"prefab 挂了但目录里没有这些 skel: {missing}"
    # 「order」= Unity UI 的真实绘制序（DFS 先序，先画的在下面）。**只在每一层都读到时才写**——
    # 缺一个就不写，让下游 `build_gallery_index.py` 明确回落到名字启发式并点名告警，
    # 绝不拿半截的序冒充权威（2026-10-05 天津风皮肤2：本体被不透明房间层盖住）。
    order_ok = all(nd.get("renderIndex", -1) >= 0 for nd in layers)
    payload = {
        "bundle": f"spinepainting/{name}",
        "source": "prefab SkeletonGraphic 节点（权威），非目录 glob",
        "layers": [{
            "layer": nd["layer"],
            "skelFile": nd["layer"] + ".skel",
            "node": nd["node"],
            "active": nd["active"],
            "startingAnimation": nd["anim"] or "normal",
            "initialSkinName": nd["skin"],
            "anchoredPosition": nd["anchoredPosition"],
            "localScale": nd["localScale"],
            "rotZ": nd["rotZ"],
        } for nd in layers],
    }
    if order_ok:
        for pl, nd in zip(payload["layers"], layers):
            pl["order"] = nd["renderIndex"]
    else:
        payload["orderNote"] = "prefab 层级里没读全每一层的绘制序，下游按层名启发式排"
    with open(os.path.join(out_dir, "parts.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    return payload, ""


def extract_one(name):
    key = f"spinepainting/{name}"
    main = os.path.join(AB_ROOT, "spinepainting", name)
    if not os.path.isfile(main):
        return False, "主包缺失"
    deps = manifest.get(key, {}).get("deps", [])
    src_bundles = [key] + [d for d in deps if d.endswith("_res")]
    texts, textures = collect_assets(src_bundles)

    skels, atlases = {}, {}
    for k, v in texts.items():
        b = to_bytes(v)
        if k.endswith(".atlas") or k.endswith(".atlas.txt"):
            atlases[k[:-4] if k.endswith(".txt") else k] = v
        elif k.endswith(".skel"):
            skels[k] = v
        else:
            # 无后缀变体：atlas 文本含 spine 特征词；其余大二进制当 skel
            head = b[:4096]
            try:
                txt = head.decode("utf-8")
                is_atlas = ("size:" in txt and ("filter:" in txt or "pma:" in txt))
            except UnicodeDecodeError:
                is_atlas = False
            if is_atlas:
                atlases[k + ".atlas"] = v
            elif len(b) > 1024:
                skels[k + ".skel"] = v
    if not skels:
        return False, "无 skel"

    out_dir = os.path.join(OUT_ROOT, name)
    os.makedirs(out_dir, exist_ok=True)
    n_png = 0
    notes = []
    # 外部依赖包（补页纹理用）
    ext_bundles = [d for d in deps if not d.endswith("_res") and d != "custom_builtin"
                   and d != key]

    for aname, ascript in atlases.items():
        base = aname[:-len(".atlas")]
        atext = to_bytes(ascript).decode("utf-8", "replace")
        pages = atlas_pages(atext)
        for pg in pages:
            texname = pg[:-4]
            o = textures.get(texname)
            if o is None and ext_bundles:
                t2, x2 = collect_assets(ext_bundles)
                o = x2.get(texname)
                textures.update(x2)
                if o is None:
                    notes.append(f"缺页 {pg}")
                    continue
            if o is not None:
                # Spine 运行时按标准 PNG（行0=顶）采样，Unity raw data 需翻转
                img = get_image_from_texture2d(o.read(), flip=True)
                img.save(os.path.join(out_dir, pg))
                n_png += 1
        with open(os.path.join(out_dir, aname), "wb") as f:
            f.write(to_bytes(ascript))
    for sname, sscript in skels.items():
        with open(os.path.join(out_dir, sname), "wb") as f:
            f.write(to_bytes(sscript))
    msg = f"{len(skels)} skel / {len(atlases)} atlas / {n_png} png"
    if notes:
        msg += " | " + "; ".join(notes)
    return True, msg


def main():
    global OUT_ROOT
    argv = sys.argv[1:]
    parts_only = "--parts-only" in argv
    argv = [x for x in argv if x != "--parts-only"]
    if "--out" in argv:
        i = argv.index("--out")
        OUT_ROOT = argv[i + 1]
        argv = argv[:i] + argv[i + 2:]
    bak_root = None
    if "--bak" in argv:
        i = argv.index("--bak")
        bak_root = argv[i + 1]
        argv = argv[:i] + argv[i + 2:]
    if is_production(OUT_ROOT) and bak_root is None:
        return refuse_without_backup(OUT_ROOT)
    if bak_root:
        os.makedirs(bak_root, exist_ok=True)
    rec = []
    if argv:
        names = [a.strip() for a in argv if a.strip()]
    else:
        d = os.path.join(AB_ROOT, "spinepainting")
        names = sorted(f for f in os.listdir(d)
                       if os.path.isfile(os.path.join(d, f)) and not f.endswith("_res"))
    ok = miss = 0
    for n in names:
        out_dir = os.path.join(OUT_ROOT, n)
        try:
            if bak_root:
                # `--parts-only` 只写 parts.json ⇒ 只取那一份；整批重提取会连
                # skel/atlas/png 一起重写 ⇒ 现有文件全取。备份范围必须等于覆写范围。
                snapshot_prior(out_dir, n, bak_root,
                               ["parts.json"] if parts_only else None, rec)
            if parts_only:
                # 只补分层的权威列表，不重新解码贴图 —— 免得为了写一个小 json
                # 去碰 234 个目录里已经正确的 PNG/atlas/skel
                if not os.path.isdir(out_dir):
                    good, msg = False, "导出目录不存在"
                else:
                    p, why = write_parts(n, out_dir)
                    good = p is not None
                    msg = f"{len(p['layers'])} 层（prefab 权威）" if good else why
            else:
                good, msg = extract_one(n)
                if good:
                    p, why = write_parts(n, out_dir)
                    msg += f" | parts.json {'✓' if p else '✗ ' + why}"
        except Exception as e:
            good, msg = False, f"异常: {e}"
        if good:
            ok += 1
            print(f"✓ {n}: {msg}")
        else:
            miss += 1
            print(f"✗ {n}: {msg}")
    if bak_root:
        mpath = os.path.join(bak_root, "MANIFEST.json")
        files = rec
        at = time.strftime("%Y-%m-%d %H:%M:%S")
        if os.path.isfile(mpath):
            # 同一批备份目录可能被分多次写满（`run_v2_full` 每 25 个一批）
            # ⇒ 合并而不是覆盖，否则只有最后一批的 md5 留得下来
            try:
                with open(mpath, encoding="utf-8") as f:
                    old = json.load(f)
                files = old.get("files", []) + rec
                at = f'{old.get("at", "?")} ~ {at}'
            except (OSError, ValueError):
                pass
        with open(mpath, "w", encoding="utf-8") as f:
            json.dump({"out_root": OUT_ROOT, "parts_only": parts_only, "at": at,
                       "skins": len(names), "files": files}, f, ensure_ascii=False, indent=1)
        print(f"换前备份 {len(rec)} 份（本批）/ 共 {len(files)} 份 "
              f"{sum(x['size'] for x in files) / 1048576:.1f} MB -> {bak_root}（MANIFEST.json 逐份记 md5）")
    print(f"\n成功 {ok}，失败 {miss} -> {OUT_ROOT}")


if __name__ == "__main__":
    # 手工直跑时 Windows 默认 cp936，会把这段拒绝覆写的提示打成乱码 —— 判据文案读不懂等于没有。
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    # 必须 sys.exit(main())：以前 `main()` 丢掉返回值 ⇒ 拒绝覆写也报 exit 0，
    # 上层 judge 只看退出码就会把"什么都没写"当成通过（本项目第 N 次撞这个坑）。
    sys.exit(main())
