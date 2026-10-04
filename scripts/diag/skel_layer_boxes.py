# -*- coding: utf-8 -*-
"""Spine 多层「层间是否错位」**A/B 对照**：原样 vs 置零 `skeleton.x/y`，人眼看图定案。

**为什么这个 A/B 能定案**（2026-10-04 实测推导，见 `docs/TROUBLESHOOTING.md` §99）：
- 各层内容躺在**自己的** `[0,w]×[0,h]` 局部画布里（`skeleton.width/height` 与落笔框
  宽高吻合 —— `2T` 是 7087×3449，落笔框宽正好 7087）；
- prefab 侧五层 `anchoredPosition` **与整条父链**实测全 `[0,0]`
  （`scripts/diag/spine_transform_tree.py`）⇒ 游戏里各层就是**按原点对齐**的；
- spine-webgl 的 `updateWorldTransform` 会额外加 `skeleton.x/y`
  （`worldX = x * sx + skeleton.x`）⇒ **多出来这一层位移就是错位来源**。

⇒ **B 版（置零）应当是正确观感**；A 版是「照搬 skel 头、但 Unity 侧并不这么画」。

**只读**：不写任何资产；`--shots` 时两版对照图落 `.diag/`。

  py -3 scripts/diag/skel_layer_boxes.py tianjinfeng_2 --shots
  py -3 scripts/diag/skel_layer_boxes.py tianjinfeng_3 --shots     # 健康对照
"""
import sys, os, json, time, argparse
sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))          # cdp_slot.py 在 scripts/
import gallery_ui_shots as G
import cdp_slot

ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
DIAG = os.path.join(ROOT, '.diag')
# 测量页必须放在**服务器根目录（Output/）之内**才能被 fetch 到 ——
# 画廊服务器 directory=Output/，放仓库根的 .diag/ 会 404。
PAGE = os.path.join(ROOT, 'Output', 'gallery_v2', 'layer_ab_probe.html')


def syntax_ok(page_html: str) -> bool:
    """把测量页里的内联 <script> 抽出来丢给 `node --check`。

    为什么值得单独一步：页面脚本有语法错时，浏览器**静默不执行**整个 script，
    页面停在 "ready" 之前，而报错只在 devtools console 里 —— CDP 的
    `Runtime.evaluate` 拿不到。实测本轮就因为「同一作用域两次 const BG」
    卡了三条命令才定位到（现象：探针只报"测量页没就绪"）。
    """
    import subprocess
    import tempfile
    h = open(page_html, encoding='utf-8').read()
    i = h.rfind('<script>')
    j = h.rfind('</script>')
    if i < 0 or j <= i:
        print('[黄] 没找到内联 script，跳过语法检查', file=sys.stderr)
        return True
    js = h[h.find(chr(10), i) + 1:j]
    fd, tmp = tempfile.mkstemp(suffix='.js')
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        f.write(js)
    try:
        r = subprocess.run(['node', '--check', tmp], capture_output=True, text=True,
                           encoding='utf-8', errors='replace')
        if r.returncode == 0:
            return True
        print('[红] 测量页脚本语法错（node --check）：\n%s' % (r.stderr or '')[:600],
              file=sys.stderr)
        return False
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('key', help='皮肤 key（对应 Spine_v2/<key>）')
    ap.add_argument('--anim', default='', help='动画名；默认取 parts.json 的 startingAnimation')
    ap.add_argument('--shots', action='store_true', help='两版各落一张对照图到 .diag/')
    args = ap.parse_args()

    if not os.path.isfile(PAGE):
        print('[缺] 测量页不在 %s' % PAGE, file=sys.stderr)
        return 2

    # ⚠️ 端口分工别搞混：cdp_port 是这个 Chrome 自己的调试端口，
    #    srv 是画廊服务器端口（页面要 fetch 资源，必须走 http，file:// 会被 CORS 拦）。
    cdp_port, profile = cdp_slot.slot(ROOT, 'skelbox')
    import urllib.request
    srv = None
    for cand in (8777, 8080, 8000, 8765):
        try:
            with urllib.request.urlopen('http://127.0.0.1:%d/Spine_v2/' % cand, timeout=2) as r:
                if r.status in (200, 403, 404):     # 连上就有响应
                    srv = cand
                    break
        except Exception:
            continue
    if srv is None:
        print('[红] 画廊服务器没起。先跑：\n'
              '  py -3 scripts/diag/run_detached.py --log .diag/_srv.log -- '
              'py -3 Output/gallery_v2/_gallery_server.py', file=sys.stderr)
        return 2

    url = 'http://127.0.0.1:%d/gallery_v2/layer_ab_probe.html' % srv
    print('CDP 端口 %d  服务器 %d  目录 Spine_v2/%s' % (cdp_port, srv, args.key))
    # ⚠️ 语法自检放在**起浏览器之前**做（node --check 本地跑）：页面 JS 一旦有
    #    SyntaxError，整个 script 不执行，`typeof window.__ab` 永远是 undefined，
    #    只报「没就绪」根本看不出是语法错（本轮踩过：同一作用域两次 `const BG`）。
    #    也别在页面里用 `document.querySelector('script:not([src])')` 找内联脚本 ——
    #    本页的内联 script 无属性，选择器行为各版本不一致，会返回 null 把真错盖掉。
    if not syntax_ok(PAGE):
        return 1

    p = G.Page(cdp_port, profile, url, (1500, 1100))
    try:
        for _ in range(60):
            if p.ev("typeof window.__ab") == 'function':
                break
            time.sleep(0.5)
        else:
            print('[红] 测量页没就绪（语法已本地查过 ⇒ 更可能是 spine-all.js 404 '
                  '或资源路径不对）', file=sys.stderr)
            log = p.ev("(document.getElementById('log')||{}).textContent || '(无 log 元素)'")
            print('     页面 log = %r' % log, file=sys.stderr)
            return 1
        expr = ("window.__ab(%s, %s, %s)"
                % (json.dumps('Spine_v2/%s/' % args.key),
                   json.dumps(args.anim),
                   'true' if args.shots else 'false'))
        r = p.ev(expr)
        if isinstance(r, str):
            print('[红] %s' % r, file=sys.stderr)
            return 1
        out = r
        if args.shots:
            # 逐层 PNG 走 dataUrl 回来落盘（canvas 像素只存在于那个 page 里，
            # 关浏览器就没了，所以必须在这里取）
            import base64
            shots = out.get('shots') or {}
            for layer, url in shots.items():
                b64 = url.split(',', 1)[1] if ',' in url else ''
                if not b64:
                    continue
                fp = os.path.join(DIAG, 'layer_%s_%s.png' % (args.key, layer))
                with open(fp, 'wb') as f:
                    f.write(base64.b64decode(b64))
            out.pop('shots', None)
            if shots:
                print('逐层图: .diag/layer_%s_<层名>.png（%d 张）' % (args.key, len(shots)))
    finally:
        try:
            p.proc.terminate()
        except Exception:
            pass

    if not out.get('layers'):
        print('[红] 没拿到层信息：%s' % json.dumps(out, ensure_ascii=False)[:300], file=sys.stderr)
        return 1

    print('\n=== %s 各层骨架信息 ===' % args.key)
    print('%-22s %11s %11s %11s %11s %6s' %
          ('层', 'skel.x', 'skel.y', 'skel.w', 'skel.h', 'slot'))
    for L in out['layers']:
        if L.get('err'):
            print('%-22s [红] %s' % (L['layer'], L['err']))
            continue
        print('%-22s %11.1f %11.1f %11.1f %11.1f %6d' % (
            L['layer'], L['skelX'], L['skelY'], L['skelW'], L['skelH'], L['slots']))

    print('\n=== A/B 两版（skeleton.x/y 恒为 0 ⇒ 两版必然相同，此处只作反证）===')
    name = {'A_orig': 'A 原样（保留 skeleton.x/y）', 'B_zero': 'B 置零（按局部原点对齐）'}
    for k in ('A_orig', 'B_zero'):
        v = out['variants'].get(k)
        if not v:
            continue
        print('%-30s zoom=%-10.5f 覆盖=%6.2f%%  世界框=%s'
              % (name[k], v['zoom'], v['coverage'] * 100, v['worldBox']))

    pl = out.get('perLayer') or []
    if pl:
        print('\n=== 逐层：附件计数 + 真实落笔框（★ 落笔框才是判据）===')
        print('（coverage=0 时先看 withAttach：0 = 附件没挂上；>0 = 挂了画不出）')
        print('%-22s %6s %6s %6s %8s %-30s' % ('层', '槽位', '活跃', '有附件', '覆盖', '落笔框'))
        for v in pl:
            print('%-22s %6d %6d %6d %7.2f%% %-30s'
                  % (v['layer'], v.get('slots', 0), v.get('activeSlots', 0),
                     v.get('withAttach', 0), v['inkCoverage'] * 100, str(v['inkBox'])))
        blank = [v for v in pl if v['inkCoverage'] < 0.001]
        if blank:
            print('\n[红] %d 层单渲全空白：%s'
                  % (len(blank), '、'.join(v['layer'] for v in blank)))
            for v in blank:
                if v.get('withAttach', 0) == 0:
                    print('     %-22s 附件数 0 ⇒ **附件根本没挂上**（不是渲染/相机问题）'
                          % v['layer'])
                else:
                    print('     %-22s 附件数 %d ⇒ 挂上了但画不出（查纹理/混合/相机）'
                          % (v['layer'], v['withAttach']))
        ink = [v for v in pl if v.get('inkBox') and v['inkCoverage'] >= 0.001]
        if len(ink) > 1:
            xs0 = min(v['inkBox'][0] for v in ink)
            ys0 = min(v['inkBox'][1] for v in ink)
            xs1 = max(v['inkBox'][2] for v in ink)
            ys1 = max(v['inkBox'][3] for v in ink)
            print('\n落笔并集: [%.0f, %.0f, %.0f, %.0f] = %.0f×%.0f'
                  % (xs0, ys0, xs1, ys1, xs1 - xs0, ys1 - ys0))
            print('\n=== 每层与「其余层并集」的交叠（部位层之间应大幅重叠）===')
            for v in ink:
                a = v['inkBox']
                ox0 = oy0 = 1e30; ox1 = oy1 = -1e30
                for u in ink:
                    if u is v:
                        continue
                    b = u['inkBox']
                    ox0 = min(ox0, b[0]); oy0 = min(oy0, b[1])
                    ox1 = max(ox1, b[2]); oy1 = max(oy1, b[3])
                iw = min(a[2], ox1) - max(a[0], ox0)
                ih = min(a[3], oy1) - max(a[1], oy0)
                inter = iw * ih if (iw > 0 and ih > 0) else 0
                ar = (a[2] - a[0]) * (a[3] - a[1]) or 1
                r = inter / ar
                print('  %-22s 交叠占自身 %6.1f%%%s'
                      % (v['layer'], r * 100,
                         '   ★ 几乎不重叠（被摆在画外）' if r < 0.02 else ''))

    with open(os.path.join(DIAG, 'layerab_%s.json' % args.key), 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print('\n完整结果: .diag/layerab_%s.json' % args.key)
    return 0


if __name__ == '__main__':
    sys.exit(main())
