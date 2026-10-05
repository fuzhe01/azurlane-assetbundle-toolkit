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
# --anim <名字>：先切到该动画再截图（走页面的动画下拉，等同用户手动切换）
ANIM = None
if '--anim' in sys.argv:
    ANIM = sys.argv[sys.argv.index('--anim') + 1] if sys.argv.index('--anim') + 1 < len(sys.argv) else ''
    if ANIM == 'setup':
        ANIM = ''
# --at <秒>：切完动画后再等这么多秒才截图（复现"播到某一刻才出问题"）
AT = None
if '--at' in sys.argv:
    AT = sys.argv[sys.argv.index('--at') + 1] if sys.argv.index('--at') + 1 < len(sys.argv) else None
# --seek <秒>：切完动画后由页面**精确推进**这么多秒（不受真实帧率/dt 钳制影响）
SEEK = None
if '--seek' in sys.argv:
    SEEK = sys.argv[sys.argv.index('--seek') + 1] if sys.argv.index('--seek') + 1 < len(sys.argv) else None


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

        # --anim：切到指定动画再截（走页面自己的动画下拉，等同用户手动切换）。
        # 2026-10-05：用户指出「normal 下房间和角色分开、touch_body 下才是正常的」——
        # 层间相对位置**随动画不同**，必须能逐动画取证。
        if ANIM:
            print('切换动画 -> %r（%r）' % (ANIM, p.ev(
                "(()=>{const s=document.getElementById('spAnim');if(!s)return 'no select';"
                "s.value=%r;s.dispatchEvent(new Event('change'));return s.value;})()" % ANIM)))
            # --at <秒>：切完动画再等这么多秒才截 —— 用来复现"动画播到某一刻才出问题"
            # （实测 tianjinfeng_2 的 2T 层在 t≈8~32s 会爆到 29780×15185，而取景框只在
            #  打开那一瞬算一次 ⇒ 画面正常与否取决于打开时动画停在哪个相位）。
            time.sleep(float(AT) if AT else 6.0)
            print('取景自报(动画后): %s' % p.ev(
                "(window.__frameInfo?JSON.stringify(window.__frameInfo()):'-')"))
            if SEEK:
                print('推进动画 %ss -> %r' % (SEEK, p.ev(
                    "(window.__seekAnim?window.__seekAnim(%s):'没有 __seekAnim')" % SEEK)))
                time.sleep(0.6)
                # 推完**立刻**截一张：这是"动画播到该相位时画面到底长什么样"的唯一硬证据
                fp = os.path.join(DIAG, 'seek_%s_%ss.png' % (KEY, SEEK))
                d = p.cmd('Page.captureScreenshot', {'format': 'png'})
                with open(fp, 'wb') as f:
                    f.write(base64.b64decode(d['data']))
                print('  seek 截图 -> %s（%.2f MB）' % (os.path.basename(fp),
                      os.path.getsize(fp) / 1048576.0))
            print('层实时快照: %s' % p.ev(
                "(window.__layerBoxes?JSON.stringify(window.__layerBoxes()):'-')"))

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
