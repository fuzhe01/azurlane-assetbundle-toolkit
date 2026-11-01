# -*- coding: utf-8 -*-
"""inspect_old_page.py — 只读地看一遍旧画廊页面（_old_l2d_visual.html）里的模型结构。

用途：确认「同一个模型在旧页面（Cubism2 运行时）里，drawable 索引与数量是否与本仓库
（Cubism4 运行时）一致」。索引不一致时，直接比较 opacities[256] 就是在比较两个不同的东西
——本项目踩过一次：把「旧页面读完赤字的 drawable 恰好可见」误判成本仓库回归。
"""
import json
import os
import sys
import time

sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

import paths as P  # noqa: E402
import gallery_ui_shots as GU  # noqa: E402

GU.CHROME = P.CHROME
from gallery_ui_shots import Page  # noqa: E402

URL = ('http://127.0.0.1:8778/gallery_v2/_old_l2d_visual.html'
       '?m=../Live2D/ougen_8/ougen_8.model3.json&clip=mail&idx=0')

DUMP = r"""
(function(){
  var A=window.__AB||{}; var m=A.model;
  if(!m) return JSON.stringify({err:'NO_MODEL', keys:Object.keys(window).filter(function(k){
      return /AB|model|l2/i.test(k)}).slice(0,20)});
  var im=m.internalModel||m, core=im.coreModel&&im.coreModel.coreModel;
  if(!core) core=im.coreModel;
  if(!core && m.coreModel) core=m.coreModel;
  var out={modelCtor:String(m.constructor&&m.constructor.name)};
  out.keys=[];
  try{ out.keys=Object.keys(m).slice(0,40); }catch(e){}
  out.imKeys=[];
  try{ out.imKeys=Object.keys(im).slice(0,40); }catch(e){}
  try{ out.dc=core.getDrawableCount(); }catch(e){ out.dcErr=String(e); }
  try{ out.dn=(core.model.getDrawableIds? core.model.getDrawableIds():undefined); }catch(e){}
  try{ out.ids=[]; for(var i=0;i<Math.min(core.getDrawableCount(),8);i++){
        out.ids.push(core.getDrawableId?core.getDrawableId(i):('#'+i)); } }catch(e){}
  try{ out.pc=core.getParameterCount(); }catch(e){}
  try{ out.partc=core.getPartCount?core.getPartCount():undefined; }catch(e){}
  try{ out.op256=core.getDrawableOpacity(256); }catch(e){ out.op256e=String(e); }
  try{ out.maxop=(function(){var best=-1,bi=-1,n=core.getDrawableCount();
        for(var i=0;i<n;i++){var v=core.getDrawableOpacity(i); if(v>best){best=v;bi=i;}}
        return [bi,+best.toFixed(3)];})(); }catch(e){ out.maxope=String(e); }
  try{ out.nonzero=[]; var n=core.getDrawableCount();
        for(var i=0;i<n;i++){var v=core.getDrawableOpacity(i); if(v>0.001) out.nonzero.push(+v.toFixed(3));} }catch(e){}
  return JSON.stringify(out);
})()
"""


def main():
    pg = Page(9460, os.path.join(ROOT, '.diag', 'chrome_inspold'), URL, (900, 900))
    try:
        for _ in range(40):
            time.sleep(1)
            if pg.ev("!!(window.__AB&&window.__AB.model)"):
                break
        print('group=', pg.ev("window.__AB&&window.__AB.group"),
              'frames=', pg.ev("window.__AB&&window.__AB.frames"),
              'err=', pg.ev("window.__AB&&window.__AB.err"))
        d = pg.ev(DUMP)
        try:
            o = json.loads(d)
        except ValueError:
            print('DUMP 非 JSON:', str(d)[:400]); return 2
        for k, v in o.items():
            print('%-10s %s' % (k, json.dumps(v, ensure_ascii=False)[:300]))
        pg.shot(os.path.join(ROOT, '.diag', 'old_page_shot.png'))
        print('截图 -> .diag/old_page_shot.png')
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())
