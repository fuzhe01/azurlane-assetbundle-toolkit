# -*- coding: utf-8 -*-
"""astc_encoder import 兼容补丁。

背景：UnityPy 的 Texture2DConverter 顶层 `import astc_encoder`，
其内部 archspec.host() 会懒加载
`site-packages/archspec/cpu/../json/cpu/microarchitectures.json`。
该路径含 `..`，在本机 Windows 环境下被间歇性拒绝（PermissionError，
坏窗口可持续数分钟；规范化后的 flat 路径实测 100% 可读，Win32
CreateFileW 层两条路径均正常，判定为安全软件过滤驱动按原始路径拦截）。

修复：先尝试直接 import（好窗口零开销）；失败则用规范化路径预填
archspec.cpu.schema 各 LazyDictionary 的 `_data`，使后续 host() 不再
触发文件读取，然后重新 import。

用法（任何会用 UnityPy 解 Texture2D 的脚本，在 main 前调用一次）::

    from astc_import_patch import ensure_astc_importable
    ensure_astc_importable()
"""

import json
import os


def ensure_astc_importable():
    """确保 sys.modules 里有 astc_encoder；返回是否成功。"""
    try:
        import astc_encoder  # noqa: F401
        return True
    except PermissionError:
        pass

    try:
        import archspec.cpu.schema as sch

        for lazy in (sch.TARGETS_JSON, sch.CPUID_JSON,
                     sch.TARGETS_JSON_SCHEMA, sch.CPUID_JSON_SCHEMA):
            if getattr(lazy, "_data", None) is not None:
                continue
            jf = os.path.normpath(str(lazy.args[0]))
            with open(jf, "r", encoding="utf-8") as f:
                lazy._data = json.load(f)

        import astc_encoder  # noqa: F401
        return True
    except Exception as e:
        print(f"[!] astc_encoder 预填失败（ASTC 贴图将不可用）: {type(e).__name__}: {e}")
        return False


if __name__ == "__main__":
    ok = ensure_astc_importable()
    print("astc_encoder importable:", ok)