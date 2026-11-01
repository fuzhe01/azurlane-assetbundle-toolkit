# -*- coding: utf-8 -*-
"""Package selected AssetBundle samples and their dependency closure into a tgz."""
import argparse
from collections import deque
import hashlib
import json
import os
import sys
import tarfile
from pathlib import PurePosixPath

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
sys.path.insert(0, SCRIPTS)

import paths as P  # noqa: E402

SKIP_DEPS = {'custom_builtin'}


def _safe_key(key):
    return (
        isinstance(key, str)
        and bool(key)
        and '\x00' not in key
        and '\\' not in key
        and ':' not in key
        and all(part not in ('', '.', '..') for part in key.split('/'))
        and not PurePosixPath(key).is_absolute()
    )


def _load_manifest(path):
    if not os.path.isfile(path):
        return None
    with open(path, encoding='utf-8') as stream:
        return json.load(stream)


def _bundle_path(key):
    if not _safe_key(key):
        return None
    path = os.path.join(P.AB, *key.split('/'))
    root = os.path.realpath(P.AB)
    try:
        for candidate in (path, path + '.bundle'):
            if os.path.commonpath((root, os.path.realpath(candidate))) != root:
                continue
            if os.path.isfile(candidate):
                return candidate
    except ValueError:
        pass
    return None


def _siblings(key):
    category, _, name = key.partition('/')
    directory = os.path.join(P.AB, category)
    if not os.path.isdir(directory):
        return []
    prefix = name + '_'
    return [
        f'{category}/{filename}'
        for filename in os.listdir(directory)
        if filename.startswith(prefix) and os.path.isfile(os.path.join(directory, filename))
    ]


def closure(keys, manifest):
    """Return all requested and transitively required bundles and missing paths."""
    seen = set()
    queue = deque(keys)
    while queue:
        key = queue.popleft()
        if not _safe_key(key):
            raise ValueError(f'不安全的资源路径：{key!r}')
        if key in seen or key in SKIP_DEPS:
            continue
        seen.add(key)
        if manifest is not None:
            entry = manifest.get(key) or {}
            if not isinstance(entry, dict):
                raise ValueError(f'依赖表条目必须是对象：{key}')
            dependencies = entry.get('deps') or []
            if (not isinstance(dependencies, list)
                    or any(not isinstance(item, str) for item in dependencies)):
                raise ValueError(f'依赖表 deps 必须是字符串列表：{key}')
            for dependency in dependencies:
                if dependency not in seen and dependency not in SKIP_DEPS:
                    queue.append(dependency)
        queue.extend(item for item in _siblings(key) if item not in seen)
    missing = [key for key in sorted(seen) if _bundle_path(key) is None]
    return sorted(seen), missing


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _sample_keys(args):
    return (
        [f'live2d/{item}' for item in args.live2d.split(',') if item]
        + [f'painting/{item}' for item in args.painting.split(',') if item]
        + [f'spinepainting/{item}' for item in args.spine.split(',') if item]
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description='打包指定资源及依赖闭包供离线复现')
    parser.add_argument('--live2d', default='', help='Live2D 模型名，逗号分隔')
    parser.add_argument('--painting', default='', help='立绘皮肤名，逗号分隔')
    parser.add_argument('--spine', default='', help='Spine 皮肤名，逗号分隔')
    parser.add_argument('--out', default='samples.tgz', help='输出归档路径')
    parser.add_argument('--no-manifest', action='store_true', help='不把依赖 manifest 放进归档')
    parser.add_argument('--dry-run', action='store_true', help='只列文件与体积，不写归档')
    args = parser.parse_args(argv)
    keys = _sample_keys(args)
    if not keys:
        parser.error('至少指定 --live2d、--painting 或 --spine 中的一项')
    if not os.path.isdir(P.AB):
        print(f'XX 源包根不存在：{P.AB}', file=sys.stderr)
        return 2

    try:
        manifest = _load_manifest(P.MANIFEST_PATH)
    except (OSError, UnicodeError, json.JSONDecodeError) as e:
        print(f'XX 依赖表读取失败：{type(e).__name__}: {e}', file=sys.stderr)
        return 2
    if manifest is not None and not isinstance(manifest, dict):
        print('XX 依赖表根节点必须是 JSON 对象。', file=sys.stderr)
        return 2
    if manifest is None:
        print(f'! 缺少依赖表 {P.MANIFEST_PATH}，将仅按同名前缀收集兄弟包。')
    try:
        resources, missing = closure(keys, manifest)
    except (OSError, ValueError) as e:
        print(f'XX 依赖闭包计算失败：{type(e).__name__}: {e}', file=sys.stderr)
        return 2
    entries = []
    for key in resources:
        path = _bundle_path(key)
        if path:
            archive_path = os.path.join('files', 'AssetBundles', os.path.relpath(path, P.AB))
            entries.append((path, archive_path.replace('\\', '/')))
    if not args.no_manifest and os.path.isfile(P.MANIFEST_PATH):
        entries.insert(0, (P.MANIFEST_PATH, 'Output/dependency_manifest.json'))

    total = sum(os.path.getsize(path) for path, _ in entries)
    print(f'依赖表 {"已读" if manifest is not None else "缺失"}；闭包 {len(resources)} 个资源')
    for path, archive_path in entries:
        print(f'  OK {archive_path}  {os.path.getsize(path) / 1048576:.2f} MB')
    print(f'合计（未压缩）{total / 1048576:.1f} MB')
    if missing:
        print(f'XX 缺件 {len(missing)} 个；先补齐后再打包：', file=sys.stderr)
        for key in missing:
            print(f'  {key}', file=sys.stderr)
        return 1
    if args.dry_run:
        print('[dry-run] 未写归档。')
        return 0

    output = os.path.abspath(args.out)
    source_collision = os.path.exists(output) and any(
        os.path.samefile(output, path) for path, _ in entries
    )
    if source_collision or any(
            os.path.normcase(os.path.realpath(output)) == os.path.normcase(os.path.realpath(path))
            for path, _ in entries):
        print('XX 输出路径与输入文件冲突，拒绝覆盖。', file=sys.stderr)
        return 2
    os.makedirs(os.path.dirname(output) or '.', exist_ok=True)
    try:
        with tarfile.open(output, 'w:gz') as archive:
            for path, archive_path in entries:
                archive.add(path, arcname=archive_path)
        with tarfile.open(output, 'r:gz') as archive:
            actual = archive.getnames()
    except (OSError, tarfile.TarError) as e:
        print(f'XX 打包或回读失败：{type(e).__name__}: {e}', file=sys.stderr)
        return 1
    expected = [archive_path for _, archive_path in entries]
    if actual != expected:
        print(f'XX 回读条目不符：预期 {len(expected)}，实际 {len(actual)}', file=sys.stderr)
        return 1
    print(f'已写入 {output}  {os.path.getsize(output) / 1048576:.1f} MB')
    print(f'sha256={_sha256(output)}；回读条目 {len(actual)}/{len(expected)}')
    print(f'解包：tar -xzf {os.path.basename(output)} -C <仓库根>')
    return 0


if __name__ == '__main__':
    sys.exit(main())
