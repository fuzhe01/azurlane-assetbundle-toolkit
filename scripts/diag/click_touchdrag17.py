"""点 touchdrag17 判定区，抓点击前后全部参数变化 + 两帧截图。

用户目视证据：点 touchdrag17 → 脱鞋动画 → 黑丝左脚；再点 → 红底高跟鞋闪现即消失。
而 touch_drag17 **没有 motion 文件**，所以那不是动作，只能是参数切换 + keyform 形变。

本脚本用**真实点击**（不是直接调函数），记录：
  ① 点击前后全部 582 个参数的变化
  ② 点击后立刻 / 1 秒后 / 3 秒后的截图
从而找出「真正让鞋出现/消失」的是哪几个参数。

用法: py -3 scripts/diag/click_touchdrag17.py ougen_8
"""
import json
import os
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts', 'diag'))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

import cdp_helper  # noqa: E402
from cdp_helper import open_page  # noqa: E402

KEY = sys.argv[1] if len(sys.argv) > 1 else 'ougen_8'
URL = 'http://127.0.0.1:8778/gallery_v2/index.html'
OUT = os.path.join(ROOT, '.diag', 'clicktd17')
os.makedirs(OUT, exist_ok=True)

HOOK = r"""
(function(){
  var tries=0;
  function patch(){
    if(!(window.PIXI && window.PIXI.Container)){ if(tries++<800) setTimeout(patch,20); return; }
    var proto=window.PIXI.Container.prototype;
    if(proto.__dshHookCT17) return; proto.__dshHookCT17=true;
    var orig=proto.addChild;
    proto.addChild=function(){
      for(var i=0;i<arguments.length;i++){
        var c=arguments[i];
        try{ if(c && c.internalModel && c.internalModel.coreModel){ window.__l2model=c; } }catch(e){}
      }
      return orig.apply(this,arguments);
    };
  }
  patch();
})();
"""

DUMP = r"""
(function(){
  var m=window.__l2model; if(!m) return '{"err":"NO_MODEL"}';
  var core=m.internalModel.coreModel, n=core.getParameterCount();
  var ids=core._parameterIds; var out={};
  for(var i=0;i<n;i++){ try{ out[ids[i]]=+core.getParameterValueByIndex(i).toFixed(4); }catch(e){} }
  return JSON.stringify(out);
})()
"""


def main():
    try:
        with urllib.request.urlopen(URL, timeout=6) as r:
            if r.status != 200:
                print('[INVALID]'); return 2
    except Exception as e:  # noqa: BLE001
        print('[INVALID] 服务不可达:', e); return 2

    pg = open_page(URL, tag='ct17')
    try:
        pg.cmd('Page.addScriptToEvaluateOnNewDocument', {'source': HOOK})
        pg.cmd('Page.navigate', {'url': URL})
        time.sleep(4)
        pg.ev("""(function(){var b=document.querySelector('#gOpt button[data-k=login]');
           if(b&&(b.classList.contains('on')||b.dataset.on==='1')) b.click(); return 1;})()""")
        time.sleep(0.9)
        pg.ev("""
        (function(){var s=(window.GALLERY.ships||[]).find(function(x){
             return (x.skins||[]).some(function(k){return k.key===%s;});});
          var c=[...document.querySelectorAll('.card')].find(function(e){
             return (e.textContent||'').indexOf(s.name)>=0;});
          if(c) c.click(); return 1;})()
        """ % json.dumps(KEY))
        time.sleep(1.6)
        pg.ev("""(function(){var d=[...document.querySelectorAll('#mSkins .skin')].find(function(e){
           return e.dataset.k===%s;}); if(d) d.click(); return 1;})()""" % json.dumps(KEY))
        time.sleep(1.3)
        pg.ev("""(function(){var t=[...document.querySelectorAll('#mTabs .tab')].find(function(e){
           return e.dataset.k==='live2d';}); if(t&&!t.classList.contains('dis')) t.click(); return 1;})()""")
        time.sleep(13)

        if pg.ev("typeof window.__l2model") != 'object':
            print('[INVALID] 模型未就绪'); return 2

        # 取 touchdrag17 判定区的屏幕坐标
        coord = pg.ev("""
        (function(){
          var m=window.__l2model; if(!m) return 'NO_MODEL';
          var core=m.internalModel.coreModel;
          var ix=core.getDrawableIndex('TouchDrag17');
          if(ix<0) return 'NO_DRAWABLE';
          var v=core.getDrawableVertexPositions(ix);
          if(!v||!v.length) return 'NO_VERTS';
          var xs=[],ys=[];
          for(var k=0;k+1<v.length;k+=2){ xs.push(v[k]); ys.push(v[k+1]); }
          var cx=(Math.min.apply(null,xs)+Math.max.apply(null,xs))/2;
          var cy=(Math.min.apply(null,ys)+Math.max.apply(null,ys))/2;
          // 画布内坐标 → 屏幕坐标
          var r=document.getElementById('l2wrap').getBoundingClientRect();
          var im=m.internalModel, ppu=im.pixelsPerUnit||1;
          var lx=cx*ppu, ly=cy*ppu;
          var p=m.toGlobal(new PIXI.Point(lx, ly));
          var cnv=m.parent && m.parent.view ? m.parent.view : null;
          var scale = (m.scale && m.scale.x) || 1;
          return JSON.stringify({
            drawableIdx: ix,
            canvas:[cx,cy],
            global:[p.x, p.y],
            wrapRect:[r.left, r.top, r.width, r.height],
            scale: scale,
            local:[lx, ly]
          });
        })()
        """)
        print('touchdrag17 位置:', coord)
        try:
            c = json.loads(coord)
        except Exception:  # noqa: BLE001
            print('[FAIL] 拿不到坐标'); return 2

        wr = c['wrapRect']
        # global 是 stage 坐标；换算到页面坐标：wrap.left + global*scale
        sx = wr[0] + c['global'][0] * c['scale']
        sy = wr[1] + c['global'][1] * c['scale']
        print('估算点击点: (%.0f, %.0f)  窗口内 wrap=%s' % (sx, sy, wr))

        before = json.loads(pg.ev(DUMP))
        print('\n点击前 ShoseOff=%.3f Stock1=%.3f Stock2=%.3f Cloth1=%.3f'
              % (before.get('ShoseOff', -9), before.get('Stock1', -9),
                 before.get('Stock2', -9), before.get('Cloth1', -9)))
        pg.shot(os.path.join(OUT, '0_before.png'))

        # 真实点击（CDP 鼠标事件，走页面自己的 click 路径）
        for typ in ('mousePressed', 'mouseReleased'):
            pg.cmd('Input.dispatchMouseEvent', {'type': typ, 'x': int(sx), 'y': int(sy),
                                                'button': 'left', 'clickCount': 1})
            time.sleep(0.08)
        print('已点击 touchdrag17')

        time.sleep(0.4)
        p1 = os.path.join(OUT, '1_after_04s.png'); pg.shot(p1)
        after1 = json.loads(pg.ev(DUMP))
        time.sleep(1.0)
        p2 = os.path.join(OUT, '2_after_14s.png'); pg.shot(p2)
        after2 = json.loads(pg.ev(DUMP))
        time.sleep(2.0)
        p3 = os.path.join(OUT, '3_after_34s.png'); pg.shot(p3)

        def show(tag, d):
            ch = {k: (round(before.get(k, 0), 3), round(v, 3))
                  for k, v in d.items()
                  if k in before and abs(v - before[k]) > 0.05}
            print('\n%s 变化参数 %d 个:' % (tag, len(ch)))
            for k, (a, b) in list(ch.items())[:18]:
                print('   %-22s %.3f -> %.3f' % (k, a, b))

        show('点击后 0.4s', after1)
        show('点击后 1.4s', after2)

        print('\n截图: .diag/clicktd17/  0_before / 1_after_04s / 2_after_14s / 3_after_34s')
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())