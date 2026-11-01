# -*- coding: utf-8 -*-
"""Check required inputs and optional tools before rebuilding project outputs."""
import argparse
import importlib.util
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
sys.path.insert(0, SCRIPTS)

import paths as P  # noqa: E402


def _directory_size(path):
    total = 0
    files = 0
    errors = []
    if not os.path.isdir(path):
        return {'exists': False, 'files': 0, 'bytes': 0, 'errors': errors}
    def on_walk_error(error):
        errors.append(f'{error.filename}: {type(error).__name__}: {error}')

    for dp, _, names in os.walk(path, onerror=on_walk_error):
        for name in names:
            try:
                total += os.path.getsize(os.path.join(dp, name))
                files += 1
            except OSError as e:
                errors.append(f'{os.path.join(dp, name)}: {type(e).__name__}: {e}')
                continue
    return {'exists': True, 'files': files, 'bytes': total, 'errors': errors}


def inspect(adb=False):
    required = []
    if not os.path.isdir(os.path.join(P.ROOT, 'scripts')):
        required.append(f'项目脚本目录不存在：{P.ROOT}')
    if not os.path.isdir(P.AB):
        required.append(f'源包目录不存在：{P.AB}')

    packages = {}
    for package in ('UnityPy', 'PIL'):
        try:
            packages[package] = importlib.util.find_spec(package) is not None
        except (ImportError, ValueError):
            packages[package] = False
        if not packages[package]:
            required.append(f'缺 Python 依赖：{package}')

    inputs = {
        'azdata': os.path.join(P.ROOT, 'inputs', 'azdata', 'MANIFEST.json'),
        'gamecfg': os.path.join(P.ROOT, 'inputs', 'gamecfg', 'MANIFEST.json'),
    }
    outputs = {
        name: _directory_size(path)
        for name, path in (
            ('Paintings_v2', P.PAINT_OUT),
            ('Spine_v2', P.SPINE_OUT),
            ('Live2D', P.LIVE2D_OUT),
            ('CG_v2', P.CG_OUT),
            ('Audio', P.AUDIO_OUT),
        )
    }
    optional = {
        'vgmstream': bool(P.VGMSTREAM),
        'ffmpeg': bool(P.FFMPEG),
        'adb': bool(P.MUMU_ADB),
        'chrome_or_edge': bool(P.CHROME),
        'dependency_manifest': os.path.isfile(P.MANIFEST_PATH),
        'vendor_manifest': os.path.isfile(
            os.path.join(P.ROOT, 'gallery_src', 'vendor', 'MANIFEST.json')),
        'inputs_azdata_manifest': os.path.isfile(inputs['azdata']),
        'inputs_gamecfg_manifest': os.path.isfile(inputs['gamecfg']),
    }
    adb_result = None
    if adb:
        if not P.MUMU_ADB:
            adb_result = {'returncode': 127, 'output': '找不到 adb；设置 AL_ADB 或安装 Android 工具'}
        else:
            try:
                result = subprocess.run(
                    [P.MUMU_ADB, 'devices'], capture_output=True, text=True,
                    encoding='utf-8', errors='replace', timeout=15, check=False)
                adb_result = {'returncode': result.returncode,
                              'output': (result.stdout + result.stderr).strip()}
            except (OSError, subprocess.TimeoutExpired) as e:
                adb_result = {'returncode': 127, 'output': f'{type(e).__name__}: {e}'}

    return {
        'root': P.ROOT,
        'required_missing': required,
        'packages': packages,
        'optional': optional,
        'inputs': inputs,
        'outputs': outputs,
        'adb': adb_result,
    }


def _human(report):
    print(f"项目根目录: {report['root']}")
    print('\n[必需项]')
    print('  OK 项目脚本目录' if os.path.isdir(os.path.join(P.ROOT, 'scripts'))
          else '  XX 项目脚本目录')
    print(f"  {'OK' if os.path.isdir(P.AB) else 'XX'} AssetBundles: {P.AB}")
    for package, available in report['packages'].items():
        print(f"  {'OK' if available else 'XX'} Python 依赖: {package}")
    print('\n[阶段工具/数据]（缺失不拦截其他阶段）')
    for name, available in report['optional'].items():
        print(f"  {'OK' if available else '提示'} {name}")
    print('\n[规模] Output')
    for name, item in report['outputs'].items():
        if item['exists']:
            print(f"  {name:<14} {item['files']:>8} 文件  {item['bytes'] / 2**30:.2f} GiB")
            for error in item['errors']:
                print(f'    [提示] 无法统计：{error}')
        else:
            print(f"  {name:<14}（目录不存在）")
    if report['adb'] is not None:
        print(f"\n[模拟器] adb devices exit={report['adb']['returncode']}")
        print(report['adb']['output'] or '（无输出）')
    if report['required_missing']:
        print(f"\n结论：必需项缺失 {len(report['required_missing'])} 项")
        for item in report['required_missing']:
            print(f'  - {item}')
        print('安装 Python 依赖：py -3 -m pip install -r requirements-v2.txt')
    else:
        print('\n结论：必需项齐备。阶段专属工具/数据请按需补齐。')


def main(argv=None):
    parser = argparse.ArgumentParser(description='新机器/新设备的项目工具链体检')
    parser.add_argument('--json', action='store_true', help='输出机器可读 JSON')
    parser.add_argument('--adb', action='store_true', help='额外运行 adb devices 检查模拟器连接')
    args = parser.parse_args(argv)
    report = inspect(adb=args.adb)
    if args.json:
        print(json.dumps(report, ensure_ascii=False))
    else:
        _human(report)
    return 1 if report['required_missing'] else 0


if __name__ == '__main__':
    sys.exit(main())
