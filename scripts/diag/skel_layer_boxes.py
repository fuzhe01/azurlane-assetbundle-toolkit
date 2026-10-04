# -*- coding: utf-8 -*-
"""量 Spine 各层的**实际落笔像素框**，判「层间是否错位」。

**为什么必须真渲一帧读 alpha**：spine-ts 的 `SkeletonRenderer` 在渲染时把
`skeletonData.x/y` 折进 world transform，而各层这两个值**互不相同** ——
`tianjinfeng_2` 实测（官方 runtime 读，见 `skel_header.js`）：

    主层 / 2B      x=0       y=0
    2B2            x=-2957.5 y=-1081.0
    2M             x=-995.1  y=+1475.0
    2T             x=-6160.9 y=+175.2

⇒ 任何在 Python 侧拿骨骼世界坐标算的框都**不是最终落笔位置**；
顶点框算出来的 8027×3761 巨框（§98 记的那条）就是这么来的。

**判据**：
1. 每层单独渲的像素 bbox + 覆盖率 —— 覆盖率过低 = 这层几乎没画出来；
2. **两两 bbox 交叠比** —— 同一具身体的不同部位层必须大幅重叠；
   某层与所有层交叠比都≈0 ⇒ 它被摆到画外（用户看到的「背后另一个身体」即此）。

**只读**：不写任何资产；`--shots` 时每层截图落 `.diag/`。

  py -3 scripts/diag/skel_layer_boxes.py tianjinfeng_2
  py -3 scripts/diag/skel_layer_boxes.py tianjinfeng_2 --shots
  py -3 scripts/diag/skel_layer_boxes.py tianjinfeng_3          # 健康对照
"""
import sys, os, json, time, argparse
sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE)))   # cdp_slot.py 在 scripts/
import gallery_ui_shots as G
import cdp_slot

ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
DIAG = os.path.join(ROOT, '.diag')
# 测量页必须放在**服务器根目录（Output/）之内**才能被 fetch 到 ——
# 放仓库根的 .diag/ 会 404（服务器 directory=Output/，不服务 .diag）。
PAGE = os.path.join(ROOT, 'Output', 'gallery_v2', 'layer_boxes_probe.html')
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('key', help='皮肤 key（对应 Spine_v2/<key>）')
    ap.add_argument('--anim', default='', help='动画名；默认取 parts.json 的 startingAnimation')
    ap.add_argument('--shots', action='store_true')
    args = ap.parse_args()

    if not os.path.isfile(PAGE):
        print('[缺] 测量页不在 %s' % PAGE, file=sys.stderr)
        return 2

    port, profile = cdp_slot.slot(ROOT, 'skelbox')
    # ⚠️ 端口分工别搞混：
    #    · `port` 是**这个 Chrome 自己的调试端口**（cdp_slot 给的）
    #    · `srv` 是**画廊服务器**端口（页面要 fetch 资源，必须走 http，file:// 会被 CORS 拦）
    # 服务器根目录是 `Output/`，所以页面在 `/gallery_v2/xxx.html`、
    # 资源在 `/Spine_v2/...` 与 `/gallery_v2/vendor/...`。
    # 先探服务，不通就大声失败 —— 静默截出空白页却退出码 0 是本项目吃过的亏。
    import urllib.request
    srv = None
    for cand in (8777, 8080, 8000, 8765):
        try:
            with urllib.request.urlopen('http://127.0.0.1:%d/Spine_v2/' % cand, timeout=2) as r:
                if r.status in (200, 403, 404):   # 连上就有响应
                    srv = cand
                    break
        except Exception:
            continue
    if srv is None:
        print('[红] 画廊服务器没起。先跑：\n'
              '  py -3 scripts/diag/run_detached.py --log .diag/_srv.log -- '
              'py -3 Output/gallery_v2/_gallery_server.py', file=sys.stderr)
        return 2

    url = 'http://127.0.0.1:%d/gallery_v2/layer_boxes_probe.html' % srv
    print('CDP 端口 %d  服务器 %d  目录 Spine_v2/%s' % (port, srv, args.key))
    p = G.Page(port, profile, url, (1400, 1000))
    try:
        p.ev("location.href='%s'" % url)
        time.sleep(2.0)
        for _ in range(40):
            if p.ev("typeof window.__measure") == 'function':
                break
            time.sleep(0.5)
        else:
            print('[红] 测量页没就绪（spine-all.js 加载失败？）', file=sys.stderr)
            return 1

        expr = ("window.__measure('Spine_v2/%s/', %s, %s)"
                % (args.key, json.dumps(args.anim), 'true' if args.shots else 'false'))
        r = p.ev(expr)
        if isinstance(r, str):
            print('[红] %s' % r, file=sys.stderr)
            return 1
        out = r
    finally:
        try:
            p.proc.terminate()
        except Exception:
            pass

    if out.get('layers') is None:
        print('[红] 没拿到结果：%s' % json.dumps(out, ensure_ascii=False)[:400], file=sys.stderr)
        return 1

    print('=== %s 各层落笔框（动画：%s）===' % (args.key, args.anim or '各层 startingAnimation'))
    print('%-22s %10s %10s %-26s %8s %6s' %
          ('层', 'skel.x', 'skel.y', '像素 bbox', '覆盖率', 'slot'))
    for L in out['layers']:
        if L.get('err'):
            print('%-22s [红] %s' % (L['layer'], L['err']))
            continue
        print('%-22s %10.1f %10.1f %-26s %7.2f%% %6d' % (
            L['layer'], L['skelX'], L['skelY'], str(L['pxBox']),
            L['coverage'] * 100, L['slots']))

    ov = out.get('overlap') or []
    if ov:
        print('\n=== 两两交叠比（同一具身体的部位层应大幅重叠）===')
        for o in sorted(ov, key=lambda x: x['ratioOfSmaller']):
            flag = '   ★ 几乎不重叠' if o['ratioOfSmaller'] < 0.02 else ''
            print('  %-20s ∩ %-20s %5.1f%%%s' % (
                o['a'], o['b'], o['ratioOfSmaller'] * 100, flag))

    with open(os.path.join(DIAG, 'layerboxes_%s.json' % args.key), 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print('\n完整结果: .diag/layerboxes_%s.json' % args.key)
    return 0


if __name__ == '__main__':
    sys.exit(main())
