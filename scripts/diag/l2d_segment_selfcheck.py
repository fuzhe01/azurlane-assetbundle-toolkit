# -*- coding: utf-8 -*-
"""Validate motion3 segment records and interpolation invariants without mutation."""
import argparse
import json
import math
import os
import sys
from glob import glob

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))

TYPE_LENGTHS = {0: 3, 1: 7, 2: 3, 3: 3}
POINTS_PER_SEGMENT = {0: 1, 1: 3, 2: 1, 3: 1}


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def parse_segments(values):
    """Parse [start_time, start_value, type, ...] into start and typed segments."""
    if not isinstance(values, list) or len(values) < 2:
        raise ValueError('Segments must contain an initial (time, value) point')
    if not all(_number(value) for value in values):
        raise ValueError('Segments contains a non-numeric or non-finite value')
    start = (float(values[0]), float(values[1]))
    segments = []
    offset = 2
    previous_time = start[0]
    while offset < len(values):
        kind_value = values[offset]
        if int(kind_value) != kind_value or int(kind_value) not in TYPE_LENGTHS:
            raise ValueError(f'unknown segment type at offset {offset}: {kind_value}')
        kind = int(kind_value)
        length = TYPE_LENGTHS[kind]
        end = offset + length
        if end > len(values):
            raise ValueError(f'truncated segment type {kind} at offset {offset}')
        record = [float(value) for value in values[offset + 1:end]]
        if kind == 1:
            cp1 = (record[0], record[1])
            cp2 = (record[2], record[3])
            endpoint = (record[4], record[5])
            segments.append((kind, start, cp1, cp2, endpoint))
        else:
            endpoint = (record[0], record[1])
            segments.append((kind, start, endpoint))
        if endpoint[0] < previous_time:
            raise ValueError('segment endpoint times are not monotonic')
        start = endpoint
        previous_time = endpoint[0]
        offset = end
    return segments


def validate_motion(data, source='<memory>'):
    errors = []
    if not isinstance(data, dict):
        return [f'{source}: root must be a JSON object']
    meta = data.get('Meta')
    curves = data.get('Curves')
    if not isinstance(meta, dict):
        return [f'{source}: Meta must be an object']
    if not isinstance(curves, list):
        return [f'{source}: Curves must be a list']

    if meta.get('CurveCount') != len(curves):
        errors.append(f'{source}: CurveCount {meta.get("CurveCount")} != {len(curves)}')
    segment_count = 0
    point_count = 0
    for curve_index, curve in enumerate(curves):
        if not isinstance(curve, dict):
            errors.append(f'{source}: Curves[{curve_index}] must be an object')
            continue
        label = f'{source}: Curves[{curve_index}] ({curve.get("Id", "?")})'
        try:
            parsed = parse_segments(curve.get('Segments'))
        except (TypeError, ValueError) as e:
            errors.append(f'{label}: {e}')
            continue
        segment_count += len(parsed)
        point_count += 1
        point_count += sum(POINTS_PER_SEGMENT[item[0]] for item in parsed)
    if meta.get('TotalSegmentCount') != segment_count:
        errors.append(f'{source}: TotalSegmentCount {meta.get("TotalSegmentCount")} != {segment_count}')
    if meta.get('TotalPointCount') != point_count:
        errors.append(f'{source}: TotalPointCount {meta.get("TotalPointCount")} != {point_count}')
    return errors


def _bezier(p0, p1, p2, p3, t):
    u = 1.0 - t
    return (u ** 3 * p0 + 3 * u ** 2 * t * p1
            + 3 * u * t ** 2 * p2 + t ** 3 * p3)


def selftest():
    good = {
        'Meta': {'CurveCount': 1, 'TotalSegmentCount': 2, 'TotalPointCount': 5},
        'Curves': [{'Id': 'ParamAngleX', 'Segments': [
            0, 10, 0, 1, 20,
            1, 4 / 3, 22, 5 / 3, 28, 2, 30,
        ]}],
    }
    if validate_motion(good):
        raise AssertionError(f'valid fixture rejected: {validate_motion(good)}')

    broken = json.loads(json.dumps(good))
    broken['Curves'][0]['Segments'][2] = 9
    if not validate_motion(broken):
        raise AssertionError('unknown segment type was not rejected')

    control_overshoot = json.loads(json.dumps(good))
    control_overshoot['Curves'][0]['Segments'][7] = 100
    if validate_motion(control_overshoot):
        raise AssertionError('valid Bezier control-point overshoot was rejected')

    bad_time = json.loads(json.dumps(good))
    bad_time['Curves'][0]['Segments'][10] = 0.5
    if not validate_motion(bad_time):
        raise AssertionError('decreasing segment endpoint time was not rejected')

    # Uniform one-third x controls make restricted-time and solved-x interpolation agree.
    p0, p1, p2, p3 = 10.0, 22.0, 28.0, 30.0
    for u in (0.1, 0.25, 0.5, 0.75, 0.9):
        x = _bezier(0.0, 1 / 3, 2 / 3, 1.0, u)
        restricted = _bezier(p0, p1, p2, p3, u)
        low, high = 0.0, 1.0
        for _ in range(60):
            mid = (low + high) / 2
            if _bezier(0.0, 1 / 3, 2 / 3, 1.0, mid) < x:
                low = mid
            else:
                high = mid
        solved = _bezier(p0, p1, p2, p3, (low + high) / 2)
        if abs(restricted - solved) > 1e-10:
            raise AssertionError('restricted and solved-x Bezier values diverge')
    return True


def _motion_files(directory):
    return sorted(glob(os.path.join(directory, '**', '*.motion3.json'), recursive=True))


def main(argv=None):
    parser = argparse.ArgumentParser(description='motion3.json 段布局与值域自检（只读）')
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--selftest', action='store_true', help='运行内置阳性/阴性夹具')
    mode.add_argument('--dir', help='扫描一个模型目录')
    mode.add_argument('--all', action='store_true', help='扫描 Output/Live2D 全库')
    parser.add_argument('--json', action='store_true', help='机器可读 JSON 输出')
    args = parser.parse_args(argv)
    if args.selftest:
        try:
            selftest()
        except AssertionError as e:
            print(f'[FAIL] {e}', file=sys.stderr)
            return 1
        print('[PASS] 阳性夹具通过；未知类型、逆序终点均被阴性夹具捕获；控制点过冲可通过；Bezier 双路径一致')
        return 0

    directory = os.path.join(ROOT, 'Output', 'Live2D') if args.all else args.dir
    if not os.path.isdir(directory):
        print(f'[ERROR] 目录不存在：{directory}', file=sys.stderr)
        return 2
    files = _motion_files(directory)
    if not files:
        print(f'[ERROR] 未找到 *.motion3.json：{directory}', file=sys.stderr)
        return 2

    findings = []
    for path in files:
        try:
            with open(path, encoding='utf-8') as stream:
                data = json.load(stream)
            findings.extend(validate_motion(data, os.path.relpath(path, ROOT)))
        except (OSError, UnicodeError, json.JSONDecodeError) as e:
            findings.append(f'{os.path.relpath(path, ROOT)}: {type(e).__name__}: {e}')
    if args.json:
        print(json.dumps({'files': len(files), 'errors': findings}, ensure_ascii=False))
    else:
        print(f'扫描 {len(files)} 个 motion3.json；问题 {len(findings)} 个')
        for finding in findings[:50]:
            print(f'  [FAIL] {finding}')
        if len(findings) > 50:
            print(f'  …另有 {len(findings) - 50} 项')
    return 1 if findings else 0


if __name__ == '__main__':
    sys.exit(main())
