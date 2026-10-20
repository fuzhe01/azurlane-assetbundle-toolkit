# -*- coding: utf-8 -*-
"""临时探针：诊断 live2d bundle 里 Texture2D 为何读不出 image（aersasi_2 vs ougen_8）。

用法: py -3 .diag/_probe_tex.py <模型名> [<模型名> ...]
"""
import sys, os
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import UnityPy
from UnityPy import config
config.FALLBACK_UNITY_VERSION = "2022.3.62f3"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "files", "AssetBundles", "live2d")

for name in sys.argv[1:]:
    p = os.path.join(SRC, name)
    print(f"\n===== {name} ({os.path.getsize(p)} bytes) =====")
    env = UnityPy.load(p)
    texs = [o for o in env.objects if o.type.name == "Texture2D"]
    print(f"Texture2D count = {len(texs)}")
    for o in texs:
        try:
            d = o.read()
        except Exception as e:
            print("  read FAIL:", e); continue
        fmt = getattr(d, "m_TextureFormat", None)
        w = getattr(d, "m_Width", None); h = getattr(d, "m_Height", None)
        sd = getattr(d, "m_StreamData", None)
        sd_size = getattr(sd, "size", 0) if sd else 0
        sd_path = getattr(sd, "path", "") if sd else ""
        try:
            img = d.image
            ok = img is not None
            sz = img.size if ok else None
        except Exception as e:
            import traceback; traceback.print_exc()
            ok = False; sz = f"EXC {type(e).__name__}: {e}"
        print(f"  m_Name={d.m_Name!r} fmt={fmt} {w}x{h} stream={sd_size} path={sd_path!r} -> image={ok} {sz}")