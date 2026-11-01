"""在旧画廊（8777）里打开 ougen_8，截 idle 与 mail，供与新画廊对照。

用户要求（2026-10-24）：
  旧画廊 ougen_8 的 idle 左脚正常；mail 右手正常。要在**浏览器里**对比确认。
  注意端口：8777 = 旧画廊 D:\Azur Lane Assets；8778 = 本项目 D:\azur。

本脚本走真实交互：卡片 → 皮肤 → Live2D tab → 播 idle / mail → 截图。

用法: py -3 scripts/diag/shot_old_ougen.py [idle mail]
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

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8777
CLIPS = sys.argv[2:] or ['idle', 'mail']
TAG = 'old' if PORT == 8777 else 'new'
URL = 'http://127.0.0.1:%d/gallery_v2/index.html' % PORT
OUT = os.path.join(ROOT, '.diag', 'ougen_cmp')
os.makedirs(OUT, exist_ok=True)

HOOK = r"""
(function(){
  var tries=0;
  function patch(){
    if(!(window.PIXI && window.PIXI.Container)){ if(tries++<800) setTimeout(patch,20); return; }
    var proto=window.PIXI.Container.prototype;
    if(proto.__dshHookOC) return; proto.__dshHookOC=true;
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


def main():
    try:
        with urllib.request.urlopen(URL, timeout=6) as r:
            if r.status != 200:
                print('[INVALID] HTTP %d' % r.status); return 2
    except Exception as e:  # noqa: BLE001
        print('[INVALID] %d 不可达: %s' % (PORT, e)); return 2

    print('目标: %s（端口 %d）' % (URL, PORT))
    pg = open_page(URL, tag='oc' + TAG)
    try:
        pg.cmd('Page.addScriptToEvaluateOnNewDocument', {'source': HOOK})
        pg.cmd('Page.navigate', {'url': URL})
        time.sleep(6)

        print('页面就绪:', pg.ev("""JSON.stringify({
            GALLERY: typeof window.GALLERY,
            cards: document.querySelectorAll('.card').length
        })"""))

        # 关掉开场 login，避免遮挡
        pg.ev("""(function(){var b=document.querySelector('#gOpt button[data-k=login]');
           if(b&&(b.classList.contains('on')||b.dataset.on==='1')) b.click(); return 1;})()""")
        time.sleep(0.8)

        # 找 ougen 卡片
        r = pg.ev("""
        (function(){
          var s=(window.GALLERY.ships||[]).find(function(x){ return x.id==='ougen'; });
          if(!s) return 'NO_SHIP';
          var cards=[...document.querySelectorAll('.card')];
          var c=cards.find(function(e){
             var t=(e.textContent||'');
             return t.indexOf('欧根亲王')>=0 || t.indexOf('ougen')>=0;});
          if(!c) return 'NO_CARD('+cards.length+')';
          c.click(); return 'OPENED';
        })()
        """)
        print('打开卡片:', r)
        time.sleep(2.5)

        # 选 ougen_8 皮肤
        r2 = pg.ev("""
        (function(){
          var rows=[...document.querySelectorAll('#mSkins .skin')];
          var d=rows.find(function(e){ return e.dataset.k==='ougen_8'; });
          if(!d) return 'NO_ROW('+rows.length+')';
          d.click(); return 'OK';
        })()
        """)
        print('选皮肤 ougen_8:', r2)
        time.sleep(1.5)

        # 切 Live2D
        r3 = pg.ev("""
        (function(){
          var t=[...document.querySelectorAll('#mTabs .tab')].find(function(e){
             return e.dataset.k==='live2d';});
          if(!t) return 'NO_TAB';
          if(t.classList.contains('dis')) return 'DIS';
          t.click(); return 'OK';
        })()
        """)
        print('切 Live2D:', r3)
        time.sleep(14)

        print('模型钩子:', pg.ev("typeof window.__l2model"))
        if pg.ev("typeof window.__l2model") != 'object':
            print('[FAIL] 模型未就绪')
            pg.shot(os.path.join(OUT, '%s_fail.png' % TAG))
            return 2

        for clip in CLIPS:
            rr = pg.ev("""
            (function(){
              var s=document.getElementById('l2Motion');
              if(!s) return 'NO_SEL';
              if(![...s.options].some(function(o){return o.value===%s;})) return 'NO_GROUP';
              s.value=%s;
              if(window.__l2play){ window.__l2play(%s); return 'PLAYED'; }
              var b=document.getElementById('l2Replay');
              if(b){ b.click(); return 'REPLAY'; }
              return 'NO_PATH';
            })()
            """ % (json.dumps(clip), json.dumps(clip), json.dumps(clip)))
            # 取该动作中间某帧（避开首尾）
            time.sleep(3.5)
            p = os.path.join(OUT, '%s_%s.png' % (TAG, clip))
            pg.shot(p)
            print('  %-8s %-8s -> %s' % (clip, rr, os.path.basename(p)))

        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())