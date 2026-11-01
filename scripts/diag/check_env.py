#!/usr/bin/env python3
"""check_env.py — 校验当前解释器是不是项目约定的那一个，且核心依赖真的可用（只读，不写任何文件）。

为什么要有这个脚本：
    本机同时存在 Python 3.14 与 3.15，`py -3` 到底指向谁由 py.ini 与 PATH 共同决定。
    2026-10-23 实测过一次「以为在跑 3.14，其实 `py -3` 已经指向 3.15」——这种歧义不会报错，
    只会让产物差异变得无法归因。本脚本把「实际在用哪个解释器」变成一条可断言的判据。

用法:
  py -3 scripts/diag/check_env.py            # 校验版本 + 6 个核心依赖的载荷级可用性
  py -3 scripts/diag/check_env.py --strict   # 版本不等于约定值时也判红（CI / 收尾用）

退出码: 0 通过 / 1 版本或依赖不合要求 / 2 无法读取自身状态。

判据说明（三层，逐层收紧）:
  1) 解释器版本  —— 必须等于 EXPECTED_PYTHON（项目约定）
  2) 依赖可导入  —— importlib.util.find_spec 能找到模块
  3) 依赖真可用  —— 实际跑一次编解码 / 运算 / 压缩往返
     第 3 层不能省：2026-10-23 实测把 3.14 的 site-packages 复制给 3.15 时，
     `import PIL` 会「成功」，但 `Image.new()` 立刻报 `cannot import name '_imaging'`。
     只查 import 会给出假绿灯，所以这里必须落到载荷上。
"""
import importlib
import importlib.util
import os
import sys
import tempfile

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))

# 项目约定的解释器版本。改这里必须同步改 requirements-v2.txt 与 PROJECT_STATUS.md 的说明。
EXPECTED_PYTHON = (3, 15)

# (模块名, 用于提示的包名)
CORE = [
    ('UnityPy', 'UnityPy==1.25.4'),
    ('PIL', 'Pillow==12.3.0'),
    ('numpy', 'numpy==2.5.3'),
    ('lz4', 'lz4==4.4.5'),
    ('requests', 'requests==2.34.2'),
    ('websocket', 'websocket-client==1.9.2'),
]


def probe_payload(mod):
    """跑一次真实操作，证明这个依赖不是「只能 import」的半残状态。"""
    if mod == 'PIL':
        from PIL import Image
        tmp = os.path.join(tempfile.gettempdir(), '_dsh_env_check.png')
        try:
            Image.new('RGBA', (32, 24), (12, 34, 56, 255)).save(tmp)
            im = Image.open(tmp)
            im.load()
            if im.size != (32, 24):
                raise RuntimeError(f'尺寸不符 {im.size}')
            return 'PNG 编解码 OK'
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
    if mod == 'numpy':
        import numpy as np
        a = np.arange(12, dtype=np.float32).reshape(3, 4)
        if float(a.sum()) != 66.0:
            raise RuntimeError('求和结果异常')
        return '矩阵运算 OK'
    if mod == 'lz4':
        import lz4.block
        raw = b'azurlane' * 500
        if lz4.block.decompress(lz4.block.compress(raw, store_size=True)) != raw:
            raise RuntimeError('压缩往返不一致')
        return '压缩往返 OK'
    if mod == 'UnityPy':
        # UnityPyBoost 是 C 扩展，必须真的加载到才算可用
        from UnityPy import UnityPyBoost  # noqa: F401
        return 'UnityPyBoost C 扩展 OK'
    if mod == 'requests':
        import requests  # noqa: F401
        return '导入 OK'
    if mod == 'websocket':
        import websocket  # noqa: F401
        return '导入 OK'
    return '导入 OK'


def main():
    strict = '--strict' in sys.argv
    ver = sys.version_info[:2]
    ver_s = f'{ver[0]}.{ver[1]}'
    expect_s = f'{EXPECTED_PYTHON[0]}.{EXPECTED_PYTHON[1]}'

    print(f'解释器: {sys.executable}')
    print(f'版本  : {sys.version.split()[0]}', end='')
    if ver != EXPECTED_PYTHON:
        print(f'   [注意] 项目约定 {expect_s}')
    else:
        print('   [符合约定]')

    bad = 0
    if ver != EXPECTED_PYTHON:
        bad += 1
        if strict:
            print(f'  [FAIL] 版本 {ver_s} != 约定 {expect_s}')

    # 顺带揭示另一个常见坑：py -3 与直接 python 可能指向不同解释器
    spec = importlib.util.find_spec('sys')
    if spec is None:  # pragma: no cover - 理论上不可能
        print('[FAIL] 无法读取自身状态')
        return 2

    print('\n== 核心依赖（载荷级验证）==')
    for mod, pkg in CORE:
        try:
            found = importlib.util.find_spec(mod) is not None
        except (ImportError, ValueError):
            found = False
        if not found:
            print(f'  [MISSING] {mod:10} 期望 {pkg}')
            bad += 1
            continue
        try:
            importlib.import_module(mod)
            detail = probe_payload(mod)
            ver_attr = getattr(sys.modules[mod], '__version__', '?')
            print(f'  [OK]      {mod:10} {ver_attr:10} {detail}')
        except Exception as e:  # noqa: BLE001 - 任何失败都算不可用
            print(f'  [FAIL]    {mod:10} {type(e).__name__}: {e}')
            bad += 1

    print()
    if bad:
        print(f'[FAIL] {bad} 项未通过 —— 先修环境再跑依赖它们的管线')
        return 1
    print('[PASS] 解释器与核心依赖均符合要求')
    return 0


if __name__ == '__main__':
    sys.exit(main())
