#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""给 Spine 弹窗在**固定相位**拍画布图，并做「改前 / 改后」的像素差比对。

**为什么需要**（2026-10-05 天津风皮肤2「空中那份天津风没显示」）：
换层绘制序会同时动到 5 个皮肤，其余 229 个必须证明零回退。而 `spine_dialog_shot.py`
拍的是"打开后第 N 秒"，动画相位受真实帧率影响不可复现 —— 本脚本改为：
  ① 走页面真实入口 `startSpine()`；
  ② 暂停 + `window.__seekAnim(at)` **精确推进**到固定秒数（页面自己的步进器，
     与帧循环同一套 update/apply，不受 headless 帧率影响）；
  ③ 只截 canvas 的 `getBoundingClientRect()` 区域（左栏 UI 与层序无关，算进哈希只有噪声）；
  ④ 拍之前**冻住 DOM 动画**并藏掉 `#bgfx` 呼吸光晕层 —— 画布是 `alpha:true` 的透明 WebGL，
     截图会把身后那层一直在动的 CSS 光晕一起合成进来。

⚠️ **它给不出"逐字节相同"的判据，这是取证的硬限制、不是脚本没写好**：
   弹窗的 `pixelFit()` 二次构图用 `readPixels` 的像素包围盒定机位，而"哪几张贴图在那一刻
   已经上传完"本身是时序相关的 ⇒ 同一份代码连拍两次，机位会在**亚像素**级别不同，
   差异表现为角色轮廓的 1px 描边抖动（实测 0.94%% 像素、bbox 覆盖整个角色）。
   ⇒ 所以：**零回退的主判据放在数据层**（比对 `index.json` 里每个目录的 `spine.parts` 数组，
      未受影响的目录必须逐字不变），本脚本只负责**人眼看图**与「差异是否超出噪声底」：
      先用 `--selfcheck` 量出噪声底，再用 `--cmp` 看改动带来的差异有没有显著超过它。

用法:
    # 1) 改前：拍一轮（--selfcheck 连拍两次，用来量噪声底）
    py -3 scripts/diag/spine_dialog_fingerprint.py tianjinfeng_2 tianjinfeng_3 --tag before --selfcheck
    # 2) 改后：再拍一轮
    py -3 scripts/diag/spine_dialog_fingerprint.py tianjinfeng_2 tianjinfeng_3 --tag after
    # 3) 比对（同一 key 的两个 tag 逐像素求差）
    py -3 scripts/diag/spine_dialog_fingerprint.py --cmp before after
    py -3 scripts/diag/spine_dialog_fingerprint.py --cmp before before_r1   # 噪声底
"""
import argparse
import base64
import glob
import hashlib
import json
import os
import socket
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, HERE)
import gallery_ui_shots as G  # noqa: E402

DIAG = os.path.join(ROOT, '.diag', 'fingerprint')
PORT = 8777


def free_port():
    s = socket.socket(); s.bind(('127.0.0.1', 0)); n = s.getsockname()[1]; s.close(); return n


OPEN = """(()=>{
  for(const s of (window.GALLERY.ships||[])){for(const sk of (s.skins||[])){
    if(sk.key===%r||sk.id===%r){curShip=s;curSkin=sk;openShip(s,null);return (s.name||'?')+'/'+sk.key;}}}
  return null;})()"""
START = """(()=>{
  for(const s of (window.GALLERY.ships||[])){for(const sk of (s.skins||[])){
    if(sk.key===%r||sk.id===%r){curShip=s;curSkin=sk;startSpine(s,sk);return sk.key;}}}
  return null;})()"""
FREEZE = ("(()=>{const g=document.getElementById('bgfx');if(g)g.style.display='none';"
          "for(const a of (document.getAnimations?document.getAnimations():[]))"
          "{try{a.currentTime=0;a.pause();}catch(e){}}})()")


def capture(p, key, at):
    """打开 -> 暂停 -> 精确推进 at 秒 -> 冻 DOM 动画 -> 截画布。返回 (png 字节, 取景自报, 错误)。"""
    r = p.ev(OPEN % (key, key))
    if not r or str(r).startswith('EXC'):
        return None, None, 'openShip 失败: %r' % r
    time.sleep(2.5)
    r2 = p.ev(START % (key, key))
    if not r2 or str(r2).startswith('EXC'):
        return None, None, 'startSpine 失败: %r' % r2
    for _ in range(60):
        w = p.ev("(window.__frameInfo?window.__frameInfo().W:0)||0")
        if isinstance(w, int) and w > 8:
            break
        time.sleep(0.5)
    else:
        return None, None, '画布一直是 0×0（弹窗没真正打开），截图不可信'
    time.sleep(8.0)                                      # 贴图上传 + pixelFit 定案
    p.ev("(()=>{const b=document.getElementById('spPlay');"
         "if(b&&b.textContent!=='播放')b.click();})()")   # 文案是「暂停」时才点 = 切到暂停
    p.ev("(window.__seekAnim?window.__seekAnim(%s):'-')" % json.dumps(at))
    p.ev(FREEZE)
    time.sleep(0.5)
    box = p.ev("(()=>{const c=document.querySelector('#mView canvas');"
               "if(!c)return null;const r=c.getBoundingClientRect();"
               "return JSON.stringify({x:r.x,y:r.y,w:r.width,h:r.height});})()")
    if not box or str(box).startswith('EXC'):
        return None, None, '找不到画布元素'
    b = json.loads(box)
    if b['w'] < 8 or b['h'] < 8:
        return None, None, '画布矩形太小: %s' % b
    d = p.cmd('Page.captureScreenshot', {'format': 'png', 'clip': {
        'x': b['x'], 'y': b['y'], 'width': b['w'], 'height': b['h'], 'scale': 1}})
    png = base64.b64decode(d['data'])
    fi = p.ev("(window.__frameInfo?JSON.stringify(window.__frameInfo()):'-')")
    return png, fi, None


def diff_pct(fa, fb):
    """两张 PNG 的差异像素占比（通道最大差 >6 才算，避开 PNG 编码与抖动级噪声）。"""
    from PIL import Image, ImageChops
    a = Image.open(fa).convert('RGB')
    b = Image.open(fb).convert('RGB')
    if a.size != b.size:
        return None, '尺寸不同 %s vs %s' % (a.size, b.size)
    d = ImageChops.difference(a, b).convert('L').point(lambda v: 255 if v > 6 else 0)
    raw = d.tobytes()
    n = sum(1 for v in raw if v)
    return 100.0 * n / (a.size[0] * a.size[1]), d.getbbox()


def do_cmp(t1, t2):
    keys = sorted({os.path.basename(x).split('_' + t1)[0]
                   for x in glob.glob(os.path.join(DIAG, '*_%s.png' % t1))})
    if not keys:
        print('[红] 没有 tag=%s 的图（先跑一遍 --tag %s）' % (t1, t1), file=sys.stderr)
        return 1
    bad = 0
    for k in keys:
        f1, f2 = os.path.join(DIAG, '%s_%s.png' % (k, t1)), os.path.join(DIAG, '%s_%s.png' % (k, t2))
        if not os.path.isfile(f2):
            print('  %-22s [跳过] 没有 %s' % (k, os.path.basename(f2))); continue
        pct, bbox = diff_pct(f1, f2)
        if pct is None:
            print('  %-22s [红] %s' % (k, bbox)); bad += 1; continue
        print('  %-22s 差异 %.3f%%%s' % (k, pct, '' if pct < 0.05 else '  bbox=%s' % (bbox,)))
    return 1 if bad else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('keys', nargs='*')
    ap.add_argument('--at', default='3')
    ap.add_argument('--tag', default='shot')
    ap.add_argument('--selfcheck', action='store_true', help='连拍两次（第二次带 _r1 后缀），用来量噪声底')
    ap.add_argument('--cmp', nargs=2, metavar=('TAG_A', 'TAG_B'))
    a = ap.parse_args()
    if a.cmp:
        return do_cmp(a.cmp[0], a.cmp[1])
    if not a.keys:
        print(__doc__)
        return 2
    os.makedirs(DIAG, exist_ok=True)
    prof = os.path.join(ROOT, '.diag', 'chrome_fp_%d' % os.getpid())
    os.makedirs(prof, exist_ok=True)
    p = G.Page(free_port(), prof, 'http://127.0.0.1:%d/gallery_v2/index.html' % PORT, (2560, 1500))
    bad = 0
    try:
        for _ in range(60):
            n = p.ev("(window.GALLERY&&Array.isArray(window.GALLERY.ships)"
                     "&&typeof startSpine==='function'&&typeof openShip==='function')"
                     "?window.GALLERY.ships.length:-1")
            if isinstance(n, int) and n > 0:
                break
            time.sleep(0.5)
        else:
            print('[红] 页面没就绪（画廊服务器起了吗？端口 %d）' % PORT, file=sys.stderr)
            return 1
        for key in a.keys:
            for i, suffix in enumerate([''] + (['_r1'] if a.selfcheck else [])):
                png, fi, err = capture(p, key, a.at)
                if err:
                    print('  %-22s [红] %s' % (key, err)); bad += 1; continue
                fp = os.path.join(DIAG, '%s_%s%s.png' % (key, a.tag, suffix))
                with open(fp, 'wb') as f:
                    f.write(png)
                print('  %-22s md5=%s (%.2f MB) -> %s' % (key, hashlib.md5(png).hexdigest(),
                                                          len(png) / 1048576.0, os.path.basename(fp)))
                print('      取景 %s' % (fi or '-')[:260])
    finally:
        try:
            p.proc.terminate()
        except Exception:
            pass
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
