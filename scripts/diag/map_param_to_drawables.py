"""换装参数 → 目标 drawable 映射（结构化判据，不做截图差分）。

为什么放弃截图差分：
  试了 6 版都在跟「idle 呼吸循环」打架——
    · 不冻结：本底 6%~44%，淹没信号
    · autoUpdate=false：effect 姿态下鞋不在可见位置
    · ?pause 停 ticker：参数改了但 canvas 不再重绘（截图完全相同）
    · ?pause + __step：恢复 ticker 跑几帧，两侧相位仍不同（本底 7.3%）
  这不是判据不稳，是**用像素差分回答"某参数控制哪些部件"本来就选错了工具**。

本方法：直接问模型自己——逐 drawable 取顶点，在某参数 hi/lo 两态下
计算顶点位移量；位移 > 阈值的 drawable 就是该参数控制的目标。
  · 纯几何量，不受呼吸相位影响（同一次 evaluate 内 hi/lo 各算一遍）
  · 能精确回答「这个参数动的是衣服/丝袜/鞋/戒指/眼睛」
  · 不依赖像素、不依赖冻结、不依赖渲染

用法: py -3 scripts/diag/map_param_to_drawables.py ougen_8
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

import paths as P  # noqa: E402
import gallery_ui_shots as GU  # noqa: E402
GU.CHROME = P.CHROME
from gallery_ui_shots import Page  # noqa: E402

KEY = sys.argv[1] if len(sys.argv) > 1 else 'ougen_8'
PORT = 9470
URL = 'http://127.0.0.1:8778/gallery_v2/index.html?pause'
OUT = os.path.join(ROOT, '.diag', 'param_drawables')
os.makedirs(OUT, exist_ok=True)

HOOK = r"""
(function(){
  var tries=0;
  function patch(){
    if(!(window.PIXI && window.PIXI.Container)){ if(tries++<800) setTimeout(patch,20); return; }
    var proto=window.PIXI.Container.prototype;
    if(proto.__dshHookPD2) return; proto.__dshHookPD2=true;
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

# 在同一 evaluate 内：设参数 hi → 采顶点 → 设 lo → 再采顶点 → 算位移
# 用 internalModel 的 update 强制走一遍 keyform 求值（不渲染也能拿到新顶点）
MAP = r"""
(function(){
  var m=window.__l2model; if(!m) return '{"err":"NO_MODEL"}';
  var im=m.internalModel, core=im.coreModel;
  var pid=%s, loV=%s, hiV=%s;

  var idx=core.getParameterIndex(pid);
  if(idx<0) return JSON.stringify({err:'NO_IDX'});

  function snapshot(){
    // 走一次参数→keyform 求值链，让顶点按当前参数重算
    try{ im.update(0, performance.now()); }catch(e){}
    var n=core.getDrawableCount(), out=[];
    for(var i=0;i<n;i++){
      var op=null,v=null;
      try{ op=core.getDrawableOpacity(i); }catch(e){}
      try{ v=core.getDrawableVertexPositions(i); }catch(e){}
      var bx=null;
      if(v && v.length>=2){
        var xs=[],ys=[];
        for(var k=0;k+1<v.length;k+=2){ xs.push(v[k]); ys.push(v[k+1]); }
        bx=[Math.min.apply(null,xs), Math.min.apply(null,ys),
            Math.max.apply(null,xs), Math.max.apply(null,ys)];
      }
      out.push([i, op, bx]);
    }
    return out;
  }

  core.setParameterValueByIndex(idx, hiV);
  var A=snapshot();
  core.setParameterValueByIndex(idx, loV);
  var B=snapshot();

  var moved=[];
  var n=A.length;
  for(var i=0;i<n;i++){
    var a=A[i], b=B[i];
    var dOp = Math.abs((a[1]||0)-(b[1]||0));
    var dBox = 0;
    if(a[2] && b[2]){
      dBox = Math.max(Math.abs(a[2][0]-b[2][0]), Math.abs(a[2][1]-b[2][1]),
                      Math.abs(a[2][2]-b[2][2]), Math.abs(a[2][3]-b[2][3]));
    }
    if(dOp > 0.05 || dBox > 3){
      moved.push([i, +(dOp).toFixed(3), Math.round(dBox)]);
    }
  }
  // 恢复原值
  core.setParameterValueByIndex(idx, 0);
  return JSON.stringify({pid:pid, n:n, moved:moved});
})()
"""


def main():
    table = json.load(open(os.path.join(ROOT, '.diag', 'costume_scan', 'costume_by_range.json'),
                           encoding='utf-8'))
    cands = table.get(KEY, {})
    if not cands:
        print('[FAIL] 无候选表'); return 2

    base_url = URL.split('?')[0]
    try:
        with urllib.request.urlopen(base_url, timeout=6) as r:
            if r.status != 200:
                print('[INVALID]'); return 2
    except Exception as e:  # noqa: BLE001
        print('[INVALID] 服务不可达:', e); return 2

    pg = Page(PORT, os.path.join(ROOT, '.diag', 'chrome_pd2%d' % PORT), URL, (1400, 1000))
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
        time.sleep(12)

        print('drawable 总数:', pg.ev("""
        (function(){var m=window.__l2model; return m? m.internalModel.coreModel.getDrawableCount() : -1;})()
        """))

        result = {}
        for pid, info in sorted(cands.items()):
            lo, hi = info['lo'], info['hi']
            raw = pg.ev(MAP % (json.dumps(pid), lo, hi))
            try:
                d = json.loads(raw)
                if 'err' in d:
                    print('%-16s %s' % (pid, d['err'])); continue
                mv = d['moved']
                result[pid] = {'label': info['label'], 'kind': info['kind'],
                               'n_moved': len(mv), 'moved': mv[:20]}
                print('%-16s %-8s 影响 drawable %-3d 个  %s'
                      % (pid, info['label'], len(mv), [x[0] for x in mv[:12]]))
            except Exception as e:  # noqa: BLE001
                print('%-16s 解析失败 %s / %s' % (pid, e, raw[:100]))

        json.dump(result, open(os.path.join(OUT, 'map.json'), 'w', encoding='utf-8'),
                  ensure_ascii=False, indent=1)
        print('\n已写 %s' % os.path.join(OUT, 'map.json'))
        print('\n判读：影响 drawable 数 > 80 的可能是姿势参数；集中在少数几个的是局部开关。')
        for pid, v in sorted(result.items(), key=lambda x: x[1]['n_moved']):
            print('  %-16s %-8s %3d 个' % (pid, v['label'], v['n_moved']))
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())