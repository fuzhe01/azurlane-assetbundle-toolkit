# -*- coding: utf-8 -*-
"""把 Spine 弹窗里每一层**单独**截一张图 —— 回答「画面里这块东西是谁画的」。

为什么要有这个工具（2026-10-05 的教训）：
  这一轮我盯着整图猜「菱形房间是 2B2 层画的」，靠 `skel_layers_report.js` 算出的
  世界框（2B2 = 7000×7007）去反推，结果取景框明明已经剔除 2B2、画面里的菱形却
  **仍然铺满整屏** —— 说明「谁画了菱形」这个前提本身就是错的。
  唯一能定案的办法：把每层单独画出来看一眼。层数最多十几层，一次 Chrome 启动全拍完。

做法：页面在 `startSpine()` 里把 `layers` 挂到了 `window.__spLayers`（诊断出口），
  这里直接改每层 `skeleton.color` 的 alpha（`Skeleton.color` 是整层乘色，
  spine-webgl 的 `drawSkeleton` 会带上它），一次只留一层可见，然后 CDP 截图。

用法: py -3 scripts/diag/spine_layer_isolate.py 天津风 tianjinfeng_2 [--port 8777]
"""
import base64
import os
import socket
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gallery_ui_shots as G  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
DIAG = os.path.join(ROOT, '.diag')

CN = sys.argv[1] if len(sys.argv) > 1 else '天津风'
KEY = sys.argv[2] if len(sys.argv) > 2 else 'tianjinfeng_2'
PORT = 8777
if '--port' in sys.argv:
    PORT = int(sys.argv[sys.argv.index('--port') + 1])


def free_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    n = s.getsockname()[1]
    s.close()
    return n


def shot(p, path):
    d = p.cmd('Page.captureScreenshot', {'format': 'png'})
    with open(path, 'wb') as f:
        f.write(base64.b64decode(d['data']))
    return os.path.getsize(path) / 1048576.0


def main() -> int:
    os.makedirs(DIAG, exist_ok=True)
    prof = os.path.join(DIAG, 'chrome_isolate_%d' % os.getpid())
    os.makedirs(prof, exist_ok=True)
    url = 'http://127.0.0.1:%d/gallery_v2/index.html' % PORT
    p = G.Page(free_port(), prof, url, (2560, 1600))
    try:
        for _ in range(60):
            n = p.ev("(window.GALLERY&&Array.isArray(window.GALLERY.ships)"
                     "&&typeof startSpine==='function'&&typeof openShip==='function')"
                     "?window.GALLERY.ships.length:-1")
            if isinstance(n, int) and n > 0:
                break
            time.sleep(0.5)
        else:
            print('[红] 页面没就绪', file=sys.stderr)
            return 1

        # ⚠️ 必须先 openShip 把详情页打开：`startSpine()` 画在详情页的 viewEl 里，
        # 详情页没开时 viewEl 尺寸为 0 ⇒ canvas 0×0 ⇒ 截出来全是画廊网格，
        # 而"层清单"照样打印得出来（层是加载了的），极易误判成"层没渲染"。
        ro = p.ev("""(()=>{
          for (const s of ((window.GALLERY&&window.GALLERY.ships)||[]))
            for (const sk of (s.skins||[]))
              if (sk.key === %r || sk.id === %r) { openShip(s, null);
                return (s.name||'?')+' / '+(sk.key||sk.id); }
          return null; })()""" % (KEY, KEY))
        print('openShip: %r' % ro)
        if not ro:
            return 1
        time.sleep(3.0)

        r = p.ev("""(()=>{
          for (const s of ((window.GALLERY&&window.GALLERY.ships)||[]))
            for (const sk of (s.skins||[]))
              if (sk.key === %r || sk.id === %r) {
                window.__curShip = s; curShip = s; curSkin = sk; startSpine(s, sk);
                return (s.name||'?')+' / '+(sk.key||sk.id); }
          return null; })()""" % (KEY, KEY))
        print('startSpine: %r' % r)
        if not r:
            return 1

        for _ in range(60):
            w = p.ev("(window.__frameInfo?window.__frameInfo().W:0)||0")
            if isinstance(w, int) and w > 8:
                break
            time.sleep(0.5)
        time.sleep(6.0)                      # 贴图上传 + 动画起跑

        names = p.ev("(window.__spLayers||[]).map(s=>s.name)")
        print('层清单: %s' % names)
        # 全部隐藏 → 逐层单独显示。用页面里的 `L.hidden` 绘制开关（比改 skeleton.color 稳：
        # 动画的 color timeline 会覆盖 color，却动不了这个开关）。
        p.ev("(window.__spLayers||[]).forEach(L=>{L.hidden=true;})")
        time.sleep(0.6)
        f = os.path.join(DIAG, 'iso_%s_none.png' % KEY)
        print('  全隐藏      -> %s（%.2f MB）' % (os.path.basename(f), shot(p, f)))
        for nm in (names or []):
            p.ev("(()=>{const L=(window.__spLayers||[]).find(x=>x.name===%r);"
                 "if(L)L.hidden=false;})()" % nm)
            time.sleep(1.5)
            f = os.path.join(DIAG, 'iso_%s_%s.png' % (KEY, nm))
            print('  只留 %-24s -> %s（%.2f MB）' % (nm, os.path.basename(f), shot(p, f)))
            p.ev("(()=>{const L=(window.__spLayers||[]).find(x=>x.name===%r);"
                 "if(L)L.hidden=true;})()" % nm)
        p.ev("(window.__spLayers||[]).forEach(L=>{L.hidden=false;})")
    finally:
        try:
            p.proc.terminate()
        except Exception:
            pass
    return 0


if __name__ == '__main__':
    sys.exit(main())
