#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""问页面自己：天津风弹窗现在的取景参数与**每层实际落笔框**到底是多少。

**为什么必须让页面自报**（2026-10-05 的教训）：这一轮我靠「截图看起来缺件」连改三次
（加近黑判据 → 加纯色判据 → 改同帧调用），三次都改错。根因是**我在外面看不到
页面内部状态**，只能靠猜：
  · 画面缺件，可能是取景框错，也可能是某层附件没挂上，也可能是 skin 没选对；
  · 我三次都改 `pixelFit` 的判据/时机，但从没量过「此刻 frameBox 是多少、
    frac 是多少、每层各有几个附件」。

所以这里直接在页面里读：
  · `frameBox` / `base1` / `zoom` / `camX` / `camY`（取景状态）
  * 每层：附件数、顶点数、世界包围盒（**这才是判层间关系的依据**）
  * 逐层单独渲的落笔框（`computeFrameBox` 的中间结果）

⚠️ 通过在页面里 `eval` 读闭包变量是不可能的（`startSpine` 里的都是局部变量），
所以走「猴子补丁」：先把 `spState` 之外的关键函数挂到 window 上不行——
**改为在 `startSpine` 执行后，从 canvas 与骨架数据反推**：
  · canvas 尺寸、`camera` 的实际 viewport
  * 重新自己建一遍骨架（与页面同一 runtime、同一 parts.json）量每层附件数与世界框
这是**只读**的，不改页面状态。

  py -3 scripts/diag/spine_dialog_report.py 天津风 tianjinfeng_2
"""
import json
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

# 在页面里跑：量每层的附件数 + 世界包围盒（与 startSpine 同一套读法）
JS = r"""(()=>{
  const out = {canvas:{}, layers:[], runtime:{}};
  const cv = document.querySelector('#spcwrap canvas') || document.querySelector('canvas');
  if (cv) { out.canvas = {w: cv.width, h: cv.height, cssW: cv.clientWidth, cssH: cv.clientHeight}; }
  out.runtime = {hasSpine: typeof spine!=='undefined', hasWebgl: typeof spine!=='undefined' && !!(spine.webgl)};
  const info = (window.GALLERY||{});
  return JSON.stringify(out);
})()"""


def free_port():
    s = socket.socket(); s.bind(('127.0.0.1', 0)); n = s.getsockname()[1]; s.close()
    return n


def main() -> int:
    os.makedirs(DIAG, exist_ok=True)
    prof = os.path.join(DIAG, 'chrome_rep_%d' % os.getpid())
    os.makedirs(prof, exist_ok=True)
    p = G.Page(free_port(), prof,
               'http://127.0.0.1:%d/gallery_v2/index.html' % PORT, (2560, 1600))
    try:
        for _ in range(60):
            n = p.ev("(window.GALLERY&&window.GALLERY.ships||[]).length")
            if isinstance(n, int) and n > 0:
                break
            time.sleep(0.5)
        p.ev("""(()=>{for(const s of (window.GALLERY.ships||[]))
                for(const sk of (s.skins||[]))
                  if(sk.key===%r){ curShip=s; curSkin=sk; startSpine(s,sk); return 1;}})()""".replace("KEYV", repr(KEY)))
        # 等 canvas 真正出现（弹窗未打开时尺寸是 0×0）
        for _ in range(30):
            cw = p.ev("(()=>{const c=document.querySelector('#spcwrap canvas')||document.querySelector('.view canvas');return c?c.width:0;})()")
            if isinstance(cw, int) and cw > 8:
                print('canvas 就绪: %dx%d' % (cw, p.ev("document.querySelector('#spcwrap canvas').height")))
                break
            time.sleep(1.0)
        else:
            print('[黄] canvas 一直是 0 —— 弹窗可能没打开，跳过自报')
        time.sleep(12.0)
        r = p.ev(JS)
        print('页面自报: %s' % r)

        # 关键：在页面里**重建一遍骨架**逐层量（与 startSpine 同一 runtime/同一 parts.json）
        r2 = p.ev("""(async (KEYV)=>{
          const base='../Spine_v2/'+KEYV+'/';
          const parts=(await (await fetch(base+'parts.json')).json()).layers||[];
          const W=900,H=1400;
          const cv=document.createElement('canvas'); cv.width=W; cv.height=H;
          cv.style.cssText='position:absolute;left:-9999px'; document.body.appendChild(cv);
          const glctx=new spine.webgl.ManagedWebGLRenderingContext(cv,{alpha:true,premultipliedAlpha:true});
          const scene=new spine.webgl.SceneRenderer(cv,glctx,false);
          const gl=glctx.gl; gl.clearColor(0,0,0,0); gl.enable(gl.BLEND);
          gl.blendFunc(gl.ONE,gl.ONE_MINUS_SRC_ALPHA);
          const textures={};
          const layers=[];
          for(const p of parts){
            const L=p.layer;
            try{
              const bytes=new Uint8Array(await (await fetch(base+L+'.skel')).arrayBuffer());
              const atlasTxt=await (await fetch(base+L+'.atlas')).text();
              const pages=[];
              for(const ln of atlasTxt.split('\n')){const t=(ln||'').replace(/\r$/,'');
                if(/^[A-Za-z0-9_].*\.(png|jpg)$/i.test(t)&&!ln.startsWith(' ')&&!ln.startsWith('\t')&&!t.includes(':'))pages.push(t);}
              for(const pg of pages){ if(textures[pg])continue;
                const img=new Image(); await new Promise((rs,rj)=>{img.onload=rs;img.onerror=()=>rj(new Error(pg));img.src=base+pg;});
                textures[pg]=new spine.webgl.GLTexture(glctx,img,false); }
              const texLoader=pth=>{for(const q in textures){if(q===pth||(''+pth).endsWith(q)||q.endsWith(''+pth))return textures[q];}return textures[pages[0]];};
              const atlas=new spine.TextureAtlas(atlasTxt,texLoader);
              const of=atlas.findRegion.bind(atlas);
              atlas.findRegion=n=>{let x=of(n);if(x)return x;const t=(''+n).trim();return t!==n?of(t):x;};
              const data=new spine.SkeletonBinary(new spine.AtlasAttachmentLoader(atlas)).readSkeletonData(bytes);
              const skel=new spine.Skeleton(data);
              const st=new spine.AnimationState(new spine.AnimationStateData(data));
              const an=(data.animations||[]).map(a=>a&&a.name).filter(Boolean);
              const want=p.startingAnimation||'normal';
              const pick=an.indexOf(want)>=0?want:(an.indexOf('normal')>=0?'normal':an[0]);
              if(pick){st.setAnimation(0,pick,true);st.update(0);st.apply(skel);}
              if(p.localScale){skel.scaleX=p.localScale[0]||1;skel.scaleY=p.localScale[1]||1;}
              skel.updateWorldTransform();
              let withAttach=0,x0=1e30,y0=1e30,x1=-1e30,y1=-1e30;
              for(const sl of skel.slots){
                if(!sl.getAttachment()||!sl.bone||!sl.bone.active)continue;
                withAttach++;
                const a=sl.getAttachment();
                let v,c;
                try{ if(a instanceof spine.RegionAttachment){v=spine.Utils.newFloatArray(8);c=8;a.computeWorldVertices(sl.bone,v,0,2);}
                     else if(a instanceof spine.MeshAttachment&&a.worldVerticesLength){c=a.worldVerticesLength;v=spine.Utils.newFloatArray(c);a.computeWorldVertices(sl,0,c,v,0,2);}
                     else continue; }catch(e){continue;}
                for(let j=0;j<c;j+=2){ if(v[j]<x0)x0=v[j]; if(v[j]>x1)x1=v[j];
                                          if(v[j+1]<y0)y0=v[j+1]; if(v[j+1]>y1)y1=v[j+1]; }
              }
              layers.push({layer:L, anim:pick, slots:skel.slots.length, withAttach,
                worldBox: x1>x0?[+x0.toFixed(1),+y0.toFixed(1),+x1.toFixed(1),+y1.toFixed(1)]:null});
            }catch(e){ layers.push({layer:L, err:String(e&&e.message||e)}); }
          }
          cv.remove();
          return JSON.stringify(layers);
        })()""".replace("KEYV", repr(KEY)))
        print()
        print('=== 逐层附件与世界框 ===')
        try:
            arr = json.loads(r2) if isinstance(r2, str) else r2
            for v in arr:
                if v.get('err'):
                    print('  %-22s [红] %s' % (v['layer'], v['err']))
                    continue
                wb = v['worldBox']
                w = (wb[2] - wb[0]) if wb else 0
                h = (wb[3] - wb[1]) if wb else 0
                print('  %-22s anim=%-8s 槽位=%3d 附件=%3d  世界框=%s  %dx%d'
                      % (v['layer'], v['anim'], v['slots'], v['withAttach'],
                         str(wb), w, h))
        except Exception as e:
            print('解析失败: %s / 原始: %s' % (e, str(r2)[:600]))
    finally:
        try:
            p.proc.terminate()
        except Exception:
            pass
    return 0


if __name__ == '__main__':
    sys.exit(main())
