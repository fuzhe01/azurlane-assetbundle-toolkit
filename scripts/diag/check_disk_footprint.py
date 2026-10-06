# -*- coding: utf-8 -*-
"""磁盘占用盘点：把「这块能不能删」拆成三个可独立回答的问题，逐字量出来。

为什么需要它（2026-10-06）：仓库 80 GB 被问「是不是重复了 / 能不能清理」时，
按目录名猜和按「同尺寸」估算都会给出**错的数量级** ——
实测 `Output/Audio` 同尺寸嫌疑 2.04 GB，md5 实证真重复只有 **0.09 GB**（虚高 22 倍）；
而真正的大头是一个都没有嫌疑的 `Output/Audio/BGM`（12.6 GB wav，全库零引用）。
所以判据必须分三层，谁也不替谁：

  1. **体量**：每个顶层目录多少 G、多少文件（`du` 级别的真相，不含猜测）。
  2. **可再生性**：产物能不能由「git 里的脚本 + 盘上的源包」重跑出来。
     能再生 → 删了只是花时间；不能再生（换入前的旧字节、`Output/` 不进 git）→ 删了就是永久丢。
  3. **消费方**：有没有人真的读它。判据是 grep 引用，不是"看起来是资产就该留着"。

去重上限用两步法，**不许只报第一步**：
  先按 (size, nlink) 分组算「嫌疑上限」（纯 stat，秒级），
  再对嫌疑组做 前 1 MB 采样哈希 → 全文件 md5 两级确认，才是能回收的字节。

用法:
    py -3 scripts/diag/check_disk_footprint.py                     # 体量 + 嫌疑上限（快）
    py -3 scripts/diag/check_disk_footprint.py --confirm           # 再加 md5 实证（慢，GB 级）
    py -3 scripts/diag/check_disk_footprint.py --bak-uniqueness    # _OLD_bak 逐份和线上比，还剩几份独一无二
    py -3 scripts/diag/check_disk_footprint.py --target Audio      # 只查某个子树
退出码：0 = 量完了（本工具不判红，结论交人判）；2 = 参数/路径错。
"""
import argparse
import hashlib
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'scripts'))
try:
    import paths as P  # noqa: E402
    ROOT = P.ROOT
except Exception:
    ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

GB = 1024 ** 3


def _md5(path, limit=None):
    h = hashlib.md5()
    with open(path, 'rb') as f:
        if limit:
            h.update(f.read(limit))
        else:
            for chunk in iter(lambda: f.read(1 << 20), b''):
                h.update(chunk)
    return h.hexdigest()


def _walk_files(root, skip_names=()):
    for dp, dn, fs in os.walk(root):
        if os.path.basename(dp) in skip_names:
            dn[:] = []
            continue
        for f in fs:
            yield os.path.join(dp, f)


def footprint(root, label, confirm=False):
    groups = defaultdict(list)
    total = 0
    nf = 0
    hl = 0
    hlb = 0
    for fp in _walk_files(root):
        try:
            st = os.stat(fp)
        except OSError:
            continue
        nf += 1
        total += st.st_size
        if st.st_nlink > 1:
            hl += 1
            hlb += st.st_size
        if st.st_size:
            groups[(st.st_size, st.st_nlink > 1)].append(fp)
    ceil = sum((len(v) - 1) * sz for (sz, _), v in groups.items() if len(v) > 1)
    line = (f'{label:26s} {nf:7d} 文件 / {total / GB:6.2f} GB | '
            f'同尺寸嫌疑上限 {ceil / GB:5.2f} GB | 已硬链 {hl} 个 ({hlb / GB:.2f} GB)')
    if confirm:
        rec = 0
        sets = 0
        for (sz, _hl), v in groups.items():
            if len(v) < 2:
                continue
            part = defaultdict(list)
            for fp in v:
                try:
                    part[_md5(fp, 1 << 20)].append(fp)
                except OSError:
                    pass
            full = defaultdict(list)
            for vv in part.values():
                if len(vv) < 2:
                    continue
                for fp in vv:
                    try:
                        full[_md5(fp)].append(fp)
                    except OSError:
                        pass
            for fp_l in full.values():
                if len(fp_l) > 1:
                    sets += 1
                    rec += sz * (len(fp_l) - 1)
        line += f' | md5 实证可回收 {rec / GB:.2f} GB（{sets} 组）'
    return line


def bak_uniqueness(out_root):
    """_OLD_bak 里每一份，线上是否还存在逐字节相同的副本。没有=它是那一版的唯一副本。"""
    bak = os.path.join(out_root, '_OLD_bak')
    if not os.path.isdir(bak):
        return [f'(_OLD_bak 不存在: {bak})']
    live = defaultdict(list)
    for fp in _walk_files(out_root, skip_names=('_OLD_bak',)):
        try:
            live[os.path.basename(fp)].append((os.path.getsize(fp), fp))
        except OSError:
            continue
    cache = {}
    lines = []
    for e in sorted(os.listdir(bak)):
        p = os.path.join(bak, e)
        files = [p] if os.path.isfile(p) else list(_walk_files(p))
        uniq = dup = none = 0
        gb = 0.0
        for fp in files:
            try:
                st = os.stat(fp)
            except OSError:
                continue
            gb += st.st_size
            cands = [c for c in live.get(os.path.basename(fp), []) if c[0] == st.st_size]
            if not cands:
                none += 1          # 线上没有同名同尺寸的对应物（改过名/纯新增的旧版）
                continue
            if fp not in cache:
                cache[fp] = _md5(fp)
            hit = False
            for _, t in cands:
                key = t
                if key not in cache:
                    cache[key] = _md5(t)
                if cache[key] == cache[fp]:
                    hit = True
                    break
            dup += hit
            uniq += not hit
        u = uniq + none
        lines.append(f'  {e:42s} {gb / GB:5.2f} GB | 独一无二 {u:5d} / 与线上相同 {dup:5d}'
                     f' / 共 {len(files)} 份' + ('   ← 全与线上相同，删了零损失' if u == 0 and files else ''))
    return [f'_OLD_bak 唯一副本审计（"独一无二" = 线上已无该字节，删掉即永久失去回滚点）:'] + lines


def main():
    ap = argparse.ArgumentParser(description='磁盘占用 / 可再生性 / 重复实证 三段式盘点')
    ap.add_argument('--root', default=os.path.join(ROOT), help='仓库根，默认由 paths.py 推导')
    ap.add_argument('--target', help='只查某个子树（相对 root，如 Output/Audio）')
    ap.add_argument('--confirm', action='store_true', help='对嫌疑组做 md5 两级实证（慢）')
    ap.add_argument('--bak-uniqueness', action='store_true', help='审计 _OLD_bak 还剩几份独一无二的旧字节')
    a = ap.parse_args()

    root = os.path.abspath(os.path.join(ROOT, a.target)) if a.target else os.path.abspath(a.root)
    if not os.path.isdir(root):
        print(f'[ERROR] 目录不存在: {root}')
        return 2

    out_root = os.path.join(root, 'Output') if os.path.isdir(os.path.join(root, 'Output')) else root
    files_root = os.path.join(root, 'files', 'AssetBundles')
    is_repo_root = os.path.isdir(os.path.join(root, 'scripts'))

    print(f'== 体量与重复嫌疑（{root}）==')
    targets = []
    if is_repo_root and os.path.isdir(files_root):
        targets.append(files_root)
    targets += [os.path.join(out_root, t) for t in sorted(os.listdir(out_root))
                if os.path.isdir(os.path.join(out_root, t))]
    for p in targets:
        print(footprint(p, os.path.relpath(p, root).replace(os.sep, '/'), a.confirm))
    for f in sorted(os.listdir(out_root)):
        fp = os.path.join(out_root, f)
        if os.path.isfile(fp):
            print(f'  散文件 {f}: {os.path.getsize(fp) / GB:.3f} GB')

    if a.bak_uniqueness:
        print('\n== ' + '\n'.join(bak_uniqueness(out_root)))
    return 0


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.exit(main())
