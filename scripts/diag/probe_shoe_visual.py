"""决定性实验：ShoseOff 到底有没有可见效果，以及哪个写入位置能进画面。

## 为什么做（2026-10-24 实测证据链）

1. `probe_param_value_states.py`（同一次 evaluate 内 设参→im.update→逐 drawable 比）
   三次结果互相矛盾：`0 vs 1` 一次 0 个变化、一次 2 个（驱动集合内）；`-1 vs 0` 一次 0 个、一次 4 个。
   ⇒ 该方法受 idle 演进污染，不能当判据（重复运行结论会翻转 = 判据不可信）。
2. `probe_param_write_site2.py`（真 ticker，三种写入位置）：
   - 写在 beforeModelUpdate：帧内读回 v=0（被 loadParameters 改回），drawable 0 变化；
   - 写在 LOW ticker：帧内 v=1 保持，但 drawable 同样 0 变化。
   两种位置的 driven 部件 opacity 恒为 460→0 / 461→1，**与设定值无关**。
   ⇒ 要么该参数在本模型上确实没有可见效果，要么「动作一直在跑」把所有测量都搅混了。

## 本探针的做法（把噪声源全部关掉，只剩被测变量）

- 停动作：`stopAllMotions()` + `state.complete()` → motionManager.update 不再写参数
- 关呼吸/物理/眨眼/表情：`breath.setParameters([])`、`physics=null`、`eyeBlink=null`、`expressionManager=null`
  （技能 §3.5：CubismBreath 每帧 ADD 角度参数；不关掉它，两次截图的本底差异会淹没局部开关）
- 用**产品自己的 pins 机制**（`window.__costumePinsByModel` + 页面 LOW ticker）设定值，
  不另写一套写入路径 —— 验的是产品行为，不是探针行为
- 每个状态等 1.2s（让 LOW ticker 把值稳定下来、若干帧 model.update 已按新值算过）后截图
- 判据三层：
  ① 逐 drawable：460/461 的 opacity 与 bbox（点名部件，非像素）
  ② 截图：逐像素差分（差异像素数 / 最大通道差 / 差异外接框）
  ③ 阴性对照：同一状态连拍两张，量「静止本底差异」——若它与 ①/② 的信号同量级，判据无效

用法: py -3 scripts/diag/probe_shoe_visual.py [模型] [参数]
      py -3 scripts/diag/probe_shoe_visual.py ougen_8 ShoseOff
"""
import base64
import io
import json
import os
import struct
import sys
import time
import urllib.request
import zlib

sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts', 'diag'))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

from cdp_helper import open_page  # noqa: E402

KEY = sys.argv[1] if len(sys.argv) > 1 else 'ougen_8'
PID = sys.argv[2] if len(sys.argv) > 2 else 'ShoseOff'
BASE = 'http://127.0.0.1:8778/gallery_v2/index.html'
OUT = os.path.join(ROOT, '.diag', 'shoe_visual')
os.makedirs(OUT, exist_ok=True)

HOOK = r"""
(function(){var t=0;function p(){if(!(window.PIXI&&window.PIXI.Container)){if(t++<900)setTimeout(p,20);return;}
  var pr=window.PIXI.Container.prototype;if(pr.__sv)return;pr.__sv=1;var o=pr.addChild;
  pr.addChild=function(){for(var i=0;i<arguments.length;i++){var c=arguments[i];
    try{if(c&&c.internalModel&&c.internalModel.coreModel)window.__l2model=c;}catch(e){}}return o.apply(this,arguments);};}p();})()
"""

QUIET = r"""
(function(){
  var m=window.__l2model; if(!m) return 'NO_MODEL';
  var im=m.internalModel, rep=[];
  try{ im.motionManager.queueManager.stopAllMotions(); rep.push('stopAllMotions'); }catch(e){}
  try{ im.motionManager.state.complete(); rep.push('stateComplete'); }catch(e){}
  try{ im.breath.setParameters([]); rep.push('breathOff'); }catch(e){}
  try{ im.physics=null; rep.push('physicsOff'); }catch(e){}
  try{ im.eyeBlink=null; rep.push('eyeBlinkOff'); }catch(e){}
  try{ im.expressionManager=null; rep.push('exprOff'); }catch(e){}
  try{ im.pose=null; rep.push('poseOff'); }catch(e){}
  return rep.join(',');
})()
"""

# 帧末状态：参数 + 指定 drawable 的 id/opacity/bbox（采样点放在 LOW ticker 末尾）
STATE = r"""
(function(){
  var m=window.__l2model; if(!m) return '{"err":"NO_MODEL"}';
  var core=m.internalModel.coreModel;
  var want=%s;
  var o={pidVal:null, g:(m.internalModel.motionManager.state||{}).currentGroup||null, d:[]};
  try{ o.pidVal=+core.getParameterValueById(%s).toFixed(4); }catch(e){}
  for(var k=0;k<want.length;k++){
    var i=want[k], id=null, op=null, bx=null;
    try{ var ids=core._model&&core._model.drawables&&core._model.drawables.ids; id=ids?String(ids[i]):null; }catch(e){}
    try{ op=+core.getDrawableOpacity(i).toFixed(4); }catch(e){}
    try{ var p=core.getDrawableVertexPositions(i);
      if(p&&p.length>=2){ var xs=[],ys=[];
        for(var q=0;q+1<p.length;q+=2){xs.push(p[q]);ys.push(p[q+1]);}
        bx=[+Math.min.apply(null,xs).toFixed(2),+Math.min.apply(null,ys).toFixed(2),
            +Math.max.apply(null,xs).toFixed(2),+Math.max.apply(null,ys).toFixed(2)]; } }catch(e){}
    o.d.push([i,id,op,bx]);
  }
  return JSON.stringify(o);
})()
""" % ('%s', '%s')

# 该参数在「动作铺完之后」的值（beforeModelUpdate 入口，= loadParameters 之前）
PREVAL = r"""
(function(){
  var m=window.__l2model;
  window.__svPre={n:0, v:null};
  m.internalModel.on('beforeModelUpdate', function(){
    try{ window.__svPre.v=+m.internalModel.coreModel.getParameterValueById(%s).toFixed(4);
         window.__svPre.n++; }catch(e){}
  });
  return 1;})()
"""


def png_stats(raw_a, raw_b):
    """逐像素差分（只解 PNG 到 RGBA，不依赖 PIL）。返回差异像素数与最大通道差。"""
    def decode(raw):
        assert raw[:8] == b'\x89PNG\r\n\x1a\n'
        pos, w, h, idat = 8, None, None, b''
        while pos < len(raw):
            ln = struct.unpack('>I', raw[pos:pos + 4])[0]
            typ = raw[pos + 4:pos + 8]
            data = raw[pos + 8:pos + 8 + ln]
            if typ == b'IHDR':
                w, h = struct.unpack('>II', data[:8])
            elif typ == b'IDAT':
                idat += data
            elif typ == b'IEND':
                break
            pos += 12 + ln
        d = zlib.decompress(idat)
        return w, h, d
    wa, ha, da = decode(raw_a)
    wb, hb, db = decode(raw_b)
    if (wa, ha) != (wb, hb):
        return {'err': 'size mismatch %dx%d vs %dx%d' % (wa, ha, wb, hb)}
    # 两张都是同一页面同尺寸截图，过滤器类型相同；按 4 字节通道比、跳过每行首字节（filter）
    stride = wa * 4 + 1
    n = 0
    mx = 0
    x0, y0, x1, y1 = 10 ** 9, 10 ** 9, -1, -1
    for y in range(ha):
        base = y * stride + 1
        for x in range(wa):
            o = base + x * 4
            d0 = max(abs(da[o + c] - db[o + c]) for c in range(3))
            if d0 > 8:
                n += 1
                if d0 > mx:
                    mx = d0
                if x < x0: x0 = x
                if x > x1: x1 = x
                if y < y0: y0 = y
                if y > y1: y1 = y
    return {'w': wa, 'h': ha, 'diff_px': n, 'max_ch': mx,
            'box': None if n == 0 else [x0, y0, x1, y1],
            'pct': round(100.0 * n / (wa * ha), 3)}


def main():
    try:
        with urllib.request.urlopen(BASE, timeout=6) as r:
            assert r.status == 200
    except Exception as e:  # noqa: BLE001
        print('[INVALID] 服务不可达:', e); return 2
    pg = open_page(BASE, tag='shoev', win=(1400, 1000))
    try:
        pg.cmd('Page.addScriptToEvaluateOnNewDocument', {'source': HOOK})
        pg.cmd('Network.enable'); pg.cmd('Network.setCacheDisabled', {'cacheDisabled': True})
        pg.cmd('Page.navigate', {'url': BASE})
        time.sleep(4)
        pg.ev("""(function(){var b=document.querySelector('#gOpt button[data-k=login]');
           if(b&&(b.classList.contains('on')||b.dataset.on==='1')) b.click(); return 1;})()""")
        time.sleep(0.9)
        pg.ev("""(function(){var s=(window.GALLERY.ships||[]).find(function(x){
             return (x.skins||[]).some(function(k){return k.key===%s;});});
          var c=[...document.querySelectorAll('.card')].find(function(e){
             return (e.textContent||'').indexOf(s.name)>=0;}); if(c) c.click(); return 1;})()"""
              % json.dumps(KEY))
        time.sleep(1.6)
        pg.ev("""(function(){var d=[...document.querySelectorAll('#mSkins .skin')].find(function(e){
           return e.dataset.k===%s;}); if(d) d.click(); return 1;})()""" % json.dumps(KEY))
        time.sleep(1.3)
        pg.ev("""(function(){var t=[...document.querySelectorAll('#mTabs .tab')].find(function(e){
           return e.dataset.k==='live2d';}); if(t&&!t.classList.contains('dis')) t.click(); return 1;})()""")
        for _ in range(45):
            time.sleep(1.0)
            if pg.ev("(window.__l2model && window.PARAM_DRAWABLES)?1:0") == 1:
                break
        if pg.ev("(window.__l2model?1:0)") != 1:
            print('[FAIL] 模型未加载'); return 2
        drv = json.loads(pg.ev("""(function(){var t=(window.PARAM_DRAWABLES||{})[%s]||{};
          return JSON.stringify(t[%s]||[]);})()""" % (json.dumps(KEY), json.dumps(PID))))
        print('驱动部件索引:', drv)
        state_expr = STATE % (json.dumps(drv), json.dumps(PID))

        # 动作铺完后的参数值（判断 idle 是否每帧把它写回去）
        pg.ev(PREVAL % json.dumps(PID))
        time.sleep(0.8)
        print('动作铺完后(beforeModelUpdate 入口)参数值:', pg.ev("JSON.stringify(window.__svPre)"))

        print('\n静音:', pg.ev(QUIET))
        time.sleep(1.5)
        st_quiet = json.loads(pg.ev(state_expr))
        print('静音后状态:', st_quiet)

        def set_pin(v):
            pg.ev("""(function(){var pm=(window.__costumePinsByModel=window.__costumePinsByModel||Object.create(null));
              if(!pm[%s]) pm[%s]=Object.create(null); pm[%s][%s]=%s; return 1;})()"""
                  % (json.dumps(KEY), json.dumps(KEY), json.dumps(KEY), json.dumps(PID), json.dumps(v)))

        shots = {}
        states = {}
        for tag, v in (('lo', -1), ('def', 0), ('hi', 1)):
            set_pin(v)
            time.sleep(1.3)
            states[tag] = json.loads(pg.ev(state_expr))
            path = os.path.join(OUT, '%s_%s_%s.png' % (KEY, PID, tag))
            pg.shot(path)
            shots[tag] = open(path, 'rb').read()
            print('  pin=%s → %s' % (v, json.dumps(states[tag], ensure_ascii=False)))
        # 阴性对照：同一状态连拍两张（量静止本底）
        set_pin(1)
        time.sleep(1.0)
        p_a = os.path.join(OUT, '%s_%s_ctrl_a.png' % (KEY, PID))
        pg.shot(p_a)
        time.sleep(1.0)
        p_b = os.path.join(OUT, '%s_%s_ctrl_b.png' % (KEY, PID))
        pg.shot(p_b)
        ctrl = png_stats(open(p_a, 'rb').read(), open(p_b, 'rb').read())

        print('\n' + '=' * 64)
        print('阴性对照（同一 pin 连拍两张，静止本底）:', ctrl)
        for tag in ('lo', 'def', 'hi'):
            print('  %-4s 参数值=%s  部件=%s' % (tag, states[tag]['pidVal'],
                  [(d[0], d[1], d[2], d[3]) for d in states[tag]['d']]))
        for a, b in (('lo', 'hi'), ('def', 'hi'), ('lo', 'def')):
            ds = png_stats(shots[a], shots[b])
            print('  截图差分 %-4s vs %-4s: %s' % (a, b, ds))
        # 收尾：清 pins
        pg.ev("""(function(){var pm=(window.__costumePinsByModel||{})[%s]||{};
          delete pm[%s]; return 1;})()""" % (json.dumps(KEY), json.dumps(PID)))
        print('=' * 64)
        print('截图目录: .diag/shoe_visual/')
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())
