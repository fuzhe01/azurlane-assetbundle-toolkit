"""换装参数扫描（运行时值域版）：用 Cubism Core 读 min/max，不依赖「动作间取值不同」。

背景（2026-10-24 确认）：
  旧判据「它在不同动作间被锁成不同档位」对这些参数**失效**——
  Cloth1-3 / Stock1/2 / ShoseOff / Paramring 在全部 45 个动作里恒为 0.0，
  值集合只有 {0.0}，于是被 l2d_costume_export.py 的 `len(set(vals))>=2` 过滤掉。
  但它们的**值域** min..max 是 0..1（或 -1..1），说明可调空间是存在的。

新判据：
  A. 值域：max-min > 0.5 ⇒ 可调
  B. 名称语义：命中 Cloth/Stock/Shose/Shoe/Ring/Hat/Glass/Eye 等词
  C. 局部性验证（§139）：改它造成的像素差异**面小且集中** ⇒ 局部开关；
     面大 ⇒ 姿势参数，不能当开关

本脚本只做 A+B（列候选），C 由 probe_costume_local.py 单独验。

用法: py -3 scripts/diag/scan_costume_by_range.py [模型...]
"""
import json
import os
import re
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts', 'diag'))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

import paths as P  # noqa: E402
import gallery_ui_shots as GU  # noqa: E402
GU.CHROME = P.CHROME
from gallery_ui_shots import Page  # noqa: E402

PORT = 9450
URL = 'http://127.0.0.1:8778/gallery_v2/index.html'
OUT = os.path.join(ROOT, '.diag', 'costume_scan')
os.makedirs(OUT, exist_ok=True)

# 语义词表：命中即候选（大小写不敏感）
KW = [
    ('cloth', '衣服'), ('stock', '丝袜'), ('shose', '鞋'), ('shoe', '鞋'),
    ('ring', '戒指'), ('glass', '眼镜'), ('megane', '眼镜'), ('hat', '帽子'),
    ('eye', '眼睛'), ('hair', '发型'), ('skirt', '裙子'), ('dress', '裙子'),
    ('bra', '内衣'), ('pan', '内裤'), ('glove', '手套'), ('sock', '袜子'),
    ('nek', '项圈'), ('neck', '项圈'), ('earring', '耳环'),
]
# 明确排除：动作/视线/呼吸逐帧驱动
EXCLUDE = ('eyeball', 'eyeopen', 'eyelopen', 'eyeropen', 'breath', 'angle',
           'bodyangle', 'cheek', 'brow', 'mouthform', 'eyeform')

HOOK = r"""
(function(){
  var tries=0;
  function patch(){
    if(!(window.PIXI && window.PIXI.Container)){ if(tries++<800) setTimeout(patch,20); return; }
    var proto=window.PIXI.Container.prototype;
    if(proto.__dshHookCS) return; proto.__dshHookCS=true;
    var orig=proto.addChild;
    proto.addChild=function(){
      for(var i=0;i<arguments.length;i++){
        var c=arguments[i];
        try{ if(c && c.internalModel && c.internalModel.coreModel) window.__l2model=c; }catch(e){}
      }
      return orig.apply(this,arguments);
    };
  }
  patch();
})();
"""


def scan_one(pg, key):
    r = pg.ev("""
    (function(){
      var m=window.__l2model; if(!m) return '{"err":"NO_MODEL"}';
      var core=m.internalModel.coreModel;
      var n=core.getParameterCount();
      var ids=null;
      // 实测（probe_param_names.py）：本库版本里参数名只在 core._parameterIds 上。
      // getParameterIds() / getParameterId() / im._parameterIds 全部不存在或为 undefined。
      try{ ids=core._parameterIds || null; }catch(e){}
      if(!ids || typeof ids[0]!=='string'){
        try{ ids=core.getParameterIds? core.getParameterIds() : null; }catch(e){}
      }
      if(!ids || typeof ids[0]!=='string') return JSON.stringify({err:'NO_IDS', c: !!core, k: Object.keys(m.internalModel).slice(0,20)});
      var out={};
      for(var i=0;i<n;i++){
        var nm=ids[i];
        try{
          var lo=core.getParameterMinimumValue(i), hi=core.getParameterMaximumValue(i);
          var df=core.getParameterDefaultValue(i), now=core.getParameterValueByIndex(i);
          out[nm]={lo:+lo.toFixed(4), hi:+hi.toFixed(4), def:+df.toFixed(4), now:+now.toFixed(4)};
        }catch(e){}
      }
      return JSON.stringify({n:n, params:out});
    })()
    """)
    return json.loads(r)


def open_model(pg, key):
    pg.ev("""
    (function(){var s=(window.GALLERY.ships||[]).find(function(x){
         return (x.skins||[]).some(function(k){return k.key===%s;});});
      if(!s) return 'NO_SHIP';
      var c=[...document.querySelectorAll('.card')].find(function(e){
         return (e.textContent||'').indexOf(s.name)>=0;});
      if(!c) return 'NO_CARD';
      c.click(); return 'OK';})()
    """ % json.dumps(key))
    time.sleep(1.6)
    pg.ev("""(function(){var d=[...document.querySelectorAll('#mSkins .skin')].find(function(e){
       return e.dataset.k===%s;}); if(d) d.click(); return 1;})()""" % json.dumps(key))
    time.sleep(1.3)
    pg.ev("""(function(){var t=[...document.querySelectorAll('#mTabs .tab')].find(function(e){
       return e.dataset.k==='live2d';}); if(t&&!t.classList.contains('dis')) t.click(); return 1;})()""")
    time.sleep(10)


def main():
    models = sys.argv[1:]
    if not models:
        # 默认：从 index 里取所有含 live2d 的皮肤
        idx = json.load(open(os.path.join(ROOT, 'Output', 'gallery_v2', 'index.json'), encoding='utf-8'))
        models = []
        for s in idx['ships']:
            for k in s['skins']:
                if k.get('live2d'):
                    models.append(k['key'])
    print('待扫描模型:', models)

    try:
        with urllib.request.urlopen(URL, timeout=6) as r:
            if r.status != 200:
                print('[INVALID]'); return 2
    except Exception as e:  # noqa: BLE001
        print('[INVALID] 服务不可达:', e); return 2

    pg = Page(PORT, os.path.join(ROOT, '.diag', 'chrome_cs%d' % PORT), URL, (1400, 1000))
    result = {}
    try:
        pg.cmd('Page.addScriptToEvaluateOnNewDocument', {'source': HOOK})
        pg.cmd('Page.navigate', {'url': URL})
        time.sleep(4)
        pg.ev("""(function(){var b=document.querySelector('#gOpt button[data-k=login]');
           if(b&&(b.classList.contains('on')||b.dataset.on==='1')) b.click(); return 1;})()""")
        time.sleep(0.9)

        for key in models:
            open_model(pg, key)
            d = scan_one(pg, key)
            if 'err' in d:
                print('%-14s %s' % (key, d['err'])); continue
            params = d['params']
            cands = {}
            for nm, v in params.items():
                low = nm.lower()
                if any(x in low for x in EXCLUDE):
                    continue
                span = v['hi'] - v['lo']
                if span <= 0.5:
                    continue
                labels = [zh for kw, zh in KW if kw in low]
                if not labels:
                    continue
                kind = 'switch' if span <= 1.0001 else 'slider'
                cands[nm] = {'id': nm, 'label': '/'.join(sorted(set(labels))),
                             'kind': kind, 'lo': v['lo'], 'hi': v['hi'],
                             'def': v['def'], 'now': v['now']}
            result[key] = cands
            print('%-14s 参数 %-4d 换装候选 %-3d  %s'
                  % (key, len(params), len(cands), sorted(cands)[:8]))
    finally:
        pg.close()

    out = os.path.join(OUT, 'costume_by_range.json')
    json.dump(result, open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    tot = sum(len(v) for v in result.values())
    print('\n合计候选 %d 个，已写 %s' % (tot, out))
    return 0


if __name__ == '__main__':
    sys.exit(main())