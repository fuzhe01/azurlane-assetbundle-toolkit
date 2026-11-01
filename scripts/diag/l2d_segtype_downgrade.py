# -*- coding: utf-8 -*-
"""l2d_segtype_downgrade.py — 把「零切线贝塞尔（smoothstep）」段降级为 Linear，生成对照 AB 组。

背景：`extract_motions.py` 的段类型判据把所有非「真常量/真阶梯/真直线」的段一律写成
Bezier，理由是「忠实还原 Unity 三次多项式」。官方导出器遇到两端切线都为 0 的段（几何上
就是 smoothstep `v0 -> v1`）会写 Linear 并**丢掉曲率**。这两种写法在段内最多相差
`0.094·|dv|`（dv=60 时 ≈ 5.6 个参数单位）——足以让某个靠阈值判可见的 drawable 翻面。

本脚本就是这条假设的判决实验：把零切线贝塞尔段降级成 Linear，其余**逐字节保留**，
产出 F 组供 `vanish_matrix.py` 与 E 组对照。若 `#33` 的翻转消失，就说明残留偏离来自
「保真还原多项式 vs 官方丢曲率」这个设计选择，而不是解析/写盘错误。

判据（与 `extract_motions.py` 的 smoothstep 定义一致）：
    |c1y - v0| <= REL * scale  且  |c2y - v1| <= REL * scale
    scale = max(|v0|, |v1|, 1.0)

用法:
  py -3 scripts/diag/l2d_segtype_downgrade.py --src=.diag/meta/E --dst=Output/_ab/F
"""
import io
import json
import os
import shutil
import sys

sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, HERE)

import l2d_motion_fidelity_audit as aud  # noqa: E402


def arg(name, default=None):
    for a in sys.argv[1:]:
        if a.startswith('--' + name + '='):
            return a.split('=', 1)[1]
    return default


SRC = arg('src', '.diag/meta/E')
DST = arg('dst', 'Output/_ab/F')
REL = float(arg('rel', '1e-4'))


def abspath(p):
    return p if os.path.isabs(p) else os.path.join(ROOT, p)


def downgrade(segs):
    """零切线贝塞尔段 -> [0, t1, v1]；返回 (新 segs, 降级段数, 保真最大段内偏差)。"""
    out = [segs[0], segs[1]]
    i, n = 2, len(segs)
    changed = 0
    max_dev = 0.0
    while i < n:
        T = int(segs[i])
        L = aud.SEG_LEN[T]
        if T != 1:
            out.extend(segs[i:i + L])
            i += L
            continue
        c1t, c1y, c2t, c2y, t1, v1 = segs[i + 1:i + 7]
        v0 = out[-1]
        scale = max(abs(v0), abs(v1), 1.0)
        if abs(c1y - v0) <= REL * scale and abs(c2y - v1) <= REL * scale:
            # smoothstep 与线性弦的段中点差 = 0.094 * dv
            max_dev = max(max_dev, abs(v1 - v0) * 0.09375)
            out.extend([0, t1, v1])
            changed += 1
        else:
            out.extend(segs[i:i + 7])
        i += 7
    return out, changed, max_dev


def main():
    src, dst = abspath(SRC), abspath(DST)
    if not os.path.isdir(src):
        print('ERR 源目录不存在: %s' % src)
        return 1
    if os.path.isdir(dst):
        shutil.rmtree(dst)
    files = seg_total = 0
    changed_total = 0
    worst = []
    for dirpath, _dirs, names in os.walk(src):
        for nm in names:
            s = os.path.join(dirpath, nm)
            rel = os.path.relpath(s, src)
            d = os.path.join(dst, rel)
            if not os.path.isdir(os.path.dirname(d)):
                os.makedirs(os.path.dirname(d))
            if not nm.endswith('.motion3.json'):
                shutil.copy2(s, d)
                files += 1
                continue
            j = json.loads(io.open(s, encoding='utf-8').read())
            ch = 0
            for c in j['Curves']:
                c['Segments'], k, dev = downgrade(c['Segments'])
                ch += k
                if dev > 0:
                    worst.append((dev, rel, c['Id']))
            changed_total += ch
            if ch:
                files += 1
            io.open(d, 'w', encoding='utf-8', newline='\n').write(
                json.dumps(j, ensure_ascii=False, indent=1))
    worst.sort(reverse=True)
    print('src=%s\ndst=%s' % (src, dst))
    print('降级段数=%d  受影响曲线文件=%d' % (changed_total, files))
    print('预计段内最大偏差 top8:')
    for dev, rel, cid in worst[:8]:
        print('   dev=%.4f  %s :: %s' % (dev, rel, cid))
    return 0


if __name__ == '__main__':
    sys.exit(main())
