# -*- coding: utf-8 -*-
"""在真实弹窗里打开天津风皮肤2 的 Spine 标签并截图 —— 判「修复现在还在不在」。

**为什么必须实测、不能靠读代码判断**：改动写在 `gallery_src/index.html` 正本，运行目录
是硬链接；但 2026-10-04 实测 **Edit 连原地编辑也会断链**（工具内部走「写临时文件+改名」
的原子保存）⇒ 改完不部署 = 用户看到的还是旧版。本轮就踩过一次
（`deploy_gallery.py --check` 报「既断链又漂移」，同步后才生效）。

**走页面真实入口**，不用 data 属性猜：卡片没有 `data-key`，但
`card.onclick=()=>openShip(s,card)` 且 `openShip` 是全局 ⇒ 直接调它最稳。

  py -3 scripts/diag/spine_dialog_shot.py 天津风 tianjinfeng_2
  py -3 scripts/diag/spine_dialog_shot.py 天津风 tianjinfeng_2 --port 8777
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
# --skin none → 裸 setup（__setAllSkin('')）；auto → 下拉选「（自动）」；其它值 → 设该 skin 名
SKIN = None
if '--skin' in sys.argv:
    SKIN = sys.argv[sys.argv.index('--skin') + 1] if sys.argv.index('--skin') + 1 < len(sys.argv) else ''
    if SKIN == 'none':
        SKIN = ''


def free_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    n = s.getsockname()[1]
    s.close()
    return n


def main() -> int:
    os.makedirs(DIAG, exist_ok=True)
    prof = os.path.join(DIAG, 'chrome_dialog_%d' % os.getpid())
    os.makedirs(prof, exist_ok=True)
    url = 'http://127.0.0.1:%d/gallery_v2/index.html' % PORT
    print('打开 %s' % url)
    p = G.Page(free_port(), prof, url, (2560, 1600))
    try:
        # ⚠️ 必须**同时**等 openShip 就绪：只等 GALLERY.ships 就绪会踩到「索引到了、脚本还没 eval 完」的
        # 中间态 —— 实测 openShip 未定义 → 弹窗根本没打开 → 后面 startSpine 拿到的 viewEl 尺寸为 0
        # （__frameInfo 自报 W:0/H:0），而截图看上去"有画面"，极易误判成"取景又错了"。
        for _ in range(60):
            n = p.ev("(window.GALLERY&&Array.isArray(window.GALLERY.ships)"
                     "&&typeof openShip==='function')?window.GALLERY.ships.length:-1")
            if isinstance(n, int) and n > 0:
                print('索引就绪：%d 条' % n)
                break
            time.sleep(0.5)
        else:
            print('[红] 索引没就绪', file=sys.stderr)
            return 1

        r = p.ev("""(()=>{
          for (const s of ((window.GALLERY&&window.GALLERY.ships)||[])) {
            for (const sk of (s.skins||[])) {
              if (sk.key === %r || sk.id === %r) { openShip(s, null);
                return (s.name||'?')+' / '+(sk.key||sk.id); }
            }
          }
          return null;
        })()""" % (KEY, KEY))
        print('打开船: %r' % r)
        if not r:
            print('[红] 索引里没有 %r' % KEY, file=sys.stderr)
            return 1
        time.sleep(3.0)

        # 详情页里选皮肤 + 切 Spine 标签
        # 直接调页面的 startSpine（全局）—— 绕开 UI 猜测，且**就是真实入口**
        # （详情页切到 Spine 标签时走的就是 startSpine(curShip, sk)）。
        r3 = p.ev("""(()=>{
          for (const s of ((window.GALLERY&&window.GALLERY.ships)||[])) {
            for (const sk of (s.skins||[])) {
              if (sk.key === KEYV || sk.id === KEYV) {
                window.__curShip = s; curShip = s; curSkin = sk;
                startSpine(s, sk);
                return (s.name||'?')+' / '+(sk.key||sk.id);
              }
            }
          }
          return null;
        })()""".replace('KEYV', repr(KEY)))
        print('startSpine: %r' % r3)
        # 先等画布真正有尺寸（弹窗完成布局），再等贴图上传 + 动画起跑 + pixelFit 二次构图。
        # W 恒为 0 就是"弹窗没开"的硬证据，此时截图再好看也不可信。
        for _ in range(60):
            w = p.ev("(window.__frameInfo?window.__frameInfo().W:0)||0")
            if isinstance(w, int) and w > 8:
                print('画布尺寸就绪：W=%d' % w)
                break
            time.sleep(0.5)
        else:
            print('[红] 画布尺寸一直为 0 —— 详情页/弹窗没真正打开，下面的截图不可信', file=sys.stderr)
        time.sleep(18.0)

        st = p.ev("(()=>{const b=document.querySelector('.spine-bar');"
                  "return b?b.text.replace(/\\s+/g,' ').trim():'(无 .spine-bar)';})()")
        print('工具栏自报: %r' % st)

        # 取景自报（2026-10-05 加）：直接从页面读**数值**，不再靠截图猜「哪里不对」。
        # 三个关键数：dropped=被剔出取景的背景巨幕层；box=最终取景框；didPixelFit=二次构图跑没跑。
        fi = p.ev("(window.__frameInfo?JSON.stringify(window.__frameInfo())"
                  ":'(页面没有 __frameInfo —— 运行目录是旧版，先跑 scripts/deploy_gallery.py)')")
        print('取景自报: %s' % fi)
        # skin 下拉当前值：默认**不该**落在"不设 skin"（那会让命名 skin 的附件全灭）
        print('skin 下拉当前值: %r' % p.ev(
            "(()=>{const s=document.getElementById('spSkin');return s&&s.style.display!=='none'?s.value:null;})()"))
        print('skin 自报(默认路径): %s' % p.ev(
            "(window.__skinInfo?JSON.stringify(window.__skinInfo()):'-')"))

        # --skin：复现"用户手动切 skin"。
        #   --skin none  → 走 __setAllSkin('')，即**裸 setup**（诊断用，附件会大面积消失）
        #   --skin auto  → 走**皮肤下拉选「（自动）」**，这条才是用户真实路径
        #                  （2026-10-05：用户实机看到的"缺件"就是踩了这条路径，必须能重放）
        #   --skin 1     → 设为 skin '1'
        if SKIN is not None:
            if SKIN == 'auto':
                r4 = p.ev("(()=>{const s=document.getElementById('spSkin');if(!s)return 'no select';"
                          "s.value='\\u2205';s.dispatchEvent(new Event('change'));return 'auto(\\u2205)';})()")
            else:
                r4 = p.ev("(window.__setAllSkin?window.__setAllSkin(%r)||'ok':'没有 __setAllSkin')" % SKIN)
            print('切换 skin -> %r（%r）' % (SKIN, r4))
            time.sleep(4.0)
            print('skin 自报: %s' % p.ev(
                "(window.__skinInfo?JSON.stringify(window.__skinInfo()):'-')"))
            print('取景自报(skin后): %s' % p.ev(
                "(window.__frameInfo?JSON.stringify(window.__frameInfo()):'-')"))

        # 时间序列截图：若只在某几帧缺 ⇒ 是动画时序；若全程缺 ⇒ 取景没生效
        import base64 as _b64
        for wait in (2, 5, 10, 18):
            time.sleep(4 if wait == 2 else (5 if wait == 5 else (5 if wait == 10 else 8)))
            fp = os.path.join(DIAG, 'dialog_%s_t%02d.png' % (KEY, wait))
            d = p.cmd('Page.captureScreenshot', {'format': 'png'})
            with open(fp, 'wb') as f:
                f.write(_b64.b64decode(d['data']))
            print('  t=%2ds -> %s（%.2f MB）' % (wait, os.path.basename(fp),
                  os.path.getsize(fp) / 1048576.0))
    finally:
        try:
            p.proc.terminate()
        except Exception:
            pass
    return 0


if __name__ == '__main__':
    sys.exit(main())
