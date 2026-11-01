# -*- coding: utf-8 -*-
"""Plan or run the ordered full-rebuild steps on a newly prepared machine.

Planning is read-only. Running requires the explicit --yes flag and checks every
step's success marker instead of relying on child scripts' historical exit codes.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths as P  # noqa: E402

PYTHON = sys.executable
LOG = os.path.join(P.OUT, 'bootstrap_rebuild.log')
ENV = {**os.environ, 'PYTHONIOENCODING': 'utf-8'}


def _cmd(script, *args):
    return [PYTHON, os.path.join(P.ROOT, 'scripts', script), *map(str, args)]


STEPS = [
    ('scan', '扫描源包 → asset_manifest.json',
     [(_cmd('scan_assets.py'), '清单已写入')], []),
    ('deps', '重建官方依赖表 → dependency_manifest.json',
     [(_cmd('export_dependency_manifest.py', '--out', P.MANIFEST_PATH), '条目')], []),
    ('spine', 'Spine 动态立绘全量提取',
     [(_cmd('run_v2_full.py', '--only', 'spine'),
      r're:Spine 阶段完成：失败批次 0$')], []),
    ('paintings', '静态立绘全量合成',
     [(_cmd('run_v2_full.py', '--only', 'static'),
      r're:静态阶段完成：ok=\d+ fail=0$')], []),
    ('live2d', 'Live2D 还原、动作提取与 model3 修复',
     [(_cmd('reconstruct_live2d.py', '--all'), '失败: 0'),
     (_cmd('extract_motions.py', '--all', '--into-production'), '[SUMMARY] 模型'),
     (_cmd('fix_model3.py'), 'Fixed')], []),
    ('audio', '语音提取与音频解码',
     [(_cmd('extract_cv_voice.py', '--all'), 'file:Output/gallery_v2/skin_voice.json'),
     (_cmd('export_cue_audio.py'), 'Failed: 0')], ['vgmstream']),
    ('cg', 'Spine 全屏 CG 批量导出',
     [(_cmd(os.path.join('diag', 'run_cg_export.py'), '--size', '2400',
            '--extra', 'animFrame=1', '--redo'),
      r're:\[SUMMARY\] CG 全部结束：完成\d+ 跳过\d+ 失败0$')], ['chrome']),
    ('index', '索引、缩略图与部署',
     [(_cmd('build_gallery_index.py'), 'DONE'),
     (_cmd('make_thumbs.py'), r're:完成 ok=\d+ skip=\d+ err=0$'),
     (_cmd('deploy_gallery.py'), '完成，同步')], []),
    ('vendor', '按 manifest 补齐画廊运行库',
     [(_cmd('fetch_gallery_vendor.py'), '')], []),
]
KEYS = [step[0] for step in STEPS]


def log(message):
    line = f'[{time.strftime("%H:%M:%S")}] {message}'
    print(line, flush=True)
    os.makedirs(P.OUT, exist_ok=True)
    with open(LOG, 'a', encoding='utf-8') as stream:
        stream.write(line + '\n')


def tool_missing(names):
    have = {'vgmstream': P.VGMSTREAM, 'ffmpeg': P.FFMPEG,
            'chrome': P.CHROME, 'adb': P.MUMU_ADB}
    return [name for name in names if not have.get(name)]


def preflight(install_deps):
    command = [PYTHON, os.path.join(P.ROOT, 'scripts', 'diag', 'check_toolchain.py'), '--json']
    result = subprocess.run(command, cwd=P.ROOT, env=ENV, capture_output=True,
                            text=True, encoding='utf-8', errors='replace', check=False)
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        log(f'XX 体检脚本未输出有效 JSON：{e}')
        if result.stderr:
            log(result.stderr.strip())
        return False
    missing = report.get('required_missing')
    if not isinstance(missing, list):
        log('XX 体检 JSON 缺少 required_missing 列表')
        return False
    expected_code = 1 if missing else 0
    if result.returncode != expected_code:
        log(f'XX 体检退出码与 required_missing 不一致：exit={result.returncode}，'
            f'缺项={len(missing)}')
        return False
    if not missing:
        return True
    log(f"XX 必需项缺 {len(missing)} 个：{'；'.join(map(str, missing))}")
    if install_deps and any('Python 依赖' in item for item in missing):
        install = subprocess.run(
            [PYTHON, '-m', 'pip', 'install', '-r',
             os.path.join(P.ROOT, 'requirements-v2.txt')],
            cwd=P.ROOT, env=ENV, check=False)
        if install.returncode:
            log(f'XX 依赖安装失败，exit={install.returncode}')
            return False
        return preflight(False)
    return False


def run_command(argv, marker, start_time):
    label = ' '.join(argv)
    log(f'   $ {label}')
    try:
        process = subprocess.Popen(
            argv, cwd=P.ROOT, env=ENV, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, encoding='utf-8',
            errors='replace', bufsize=1)
    except OSError as e:
        log(f'   XX 启动失败：{e}')
        return False

    marker_matches = 0
    tail = []
    assert process.stdout is not None
    for line in process.stdout:
        print('   ' + line.rstrip(), flush=True)
        if marker and not marker.startswith('file:'):
            if marker.startswith('re:'):
                matched = re.search(marker[3:], line) is not None
            else:
                matched = marker in line
            marker_matches += int(matched)
        tail.append(line.rstrip())
        del tail[:-12]
    return_code = process.wait()
    if return_code:
        log(f'   XX 子命令退出码 {return_code}')
        return False
    if marker.startswith('file:'):
        path = os.path.join(P.ROOT, marker[5:])
        if not os.path.isfile(path) or os.path.getmtime(path) < start_time - 1:
            log(f'   XX 判据失败：{marker[5:]} 不存在或不是本次产出')
            return False
    elif marker and marker_matches != 1:
        log(f'   XX 判据失败：{marker!r} 应匹配唯一终态行，实际匹配 {marker_matches} 行；'
            f'末尾输出：{" | ".join(tail)}')
        return False
    return True


def run_step(key, title, commands, needs):
    missing = tool_missing(needs)
    if missing:
        log(f'[skip] {key}：缺工具 {missing}；补齐后可用 --only {key} 单独运行')
        return None
    log(f'== {key}: {title}')
    for argv, marker in commands:
        start_time = time.time()
        if not run_command(argv, marker, start_time):
            return False
    return True


def _keys(value):
    return [item.strip() for item in value.split(',') if item.strip()]


def select_steps(only, start, skip):
    unknown = (set(only) | set(skip) | ({start} if start else set())) - set(KEYS)
    if unknown:
        raise ValueError(f'未知步骤 {sorted(unknown)}；可选：{", ".join(KEYS)}')
    steps = [step for step in STEPS if not only or step[0] in only]
    if start:
        keys = [step[0] for step in steps]
        if start not in keys:
            raise ValueError(f'--from {start} 不在所选步骤内；检查 --only')
        steps = steps[keys.index(start):]
    return [step for step in steps if step[0] not in skip]


def main(argv=None):
    parser = argparse.ArgumentParser(description='新机器一键重建画廊')
    parser.add_argument('--plan', action='store_true', help='只打印步骤计划，不写盘')
    parser.add_argument('--yes', action='store_true', help='执行步骤（会写 Output/，耗时可能很长）')
    parser.add_argument('--only', default='', help=f'仅运行指定步骤：{",".join(KEYS)}')
    parser.add_argument('--skip', default='', help='跳过指定步骤，逗号分隔')
    parser.add_argument('--from', dest='start', default='', help='从指定步骤开始，含该步骤')
    parser.add_argument('--install-deps', action='store_true', help='缺必需依赖时安装 requirements-v2.txt')
    args = parser.parse_args(argv)
    try:
        steps = select_steps(_keys(args.only), args.start, _keys(args.skip))
    except ValueError as e:
        parser.error(str(e))
    if not steps:
        parser.error('筛选后没有待执行步骤')

    print(f'项目根：{P.ROOT}')
    print('一键重建步骤（执行前先检查必需项）：')
    for key, title, commands, needs in steps:
        missing = tool_missing(needs)
        print(f'  {key:<12} {title}')
        for command, marker in commands:
            print(f'    · {" ".join(command)} [{marker or "exit 0"}]')
        if needs:
            print(f'    依赖工具：{", ".join(needs)}'
                  + (f'（当前缺 {missing}）' if missing else ''))
    if not args.yes:
        print('\n[dry-run] 未给 --yes，未启动子进程、未写入产物。')
        print('真跑：py -3 scripts/bootstrap_rebuild.py --yes')
        return 0
    if args.plan:
        parser.error('--plan 与 --yes 不能同时使用')
    if not preflight(args.install_deps):
        return 2

    log(f'=== 一键重建开始：{len(steps)} 个步骤；日志 {LOG}')
    done, skipped, failed = [], [], None
    for key, title, commands, needs in steps:
        result = run_step(key, title, commands, needs)
        if result is None:
            skipped.append(key)
        elif result:
            done.append(key)
        else:
            failed = key
            break
    log(f'=== 结束：完成 {done}；跳过 {skipped}；'
        f'{"失败于 " + failed if failed else "无子步骤失败"}')
    if failed:
        log(f'修复该步骤后可断点续跑：--from {failed}')
        return 1
    if skipped:
        log('XX 本次有步骤因缺少工具而跳过；结果不算完整重建。补齐工具后重跑对应 --only 阶段。')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
