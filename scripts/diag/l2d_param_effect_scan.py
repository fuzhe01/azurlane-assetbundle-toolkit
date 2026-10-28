r"""参数效果实测：某个参数到底驱动哪些 drawable？映射表声明的是否可信？（2026-10-28）

为什么需要这个工具：`param_drawables.json` 是早期扫描产出的静态映射，它声明「参数 P 驱动
部件集合 S」。当验收探针报「pins 两端态的差异与 S 无交集」时，有两种可能必须分开：
  a) 映射表错（扫描输入的 `.diag/param_drawables`、`.diag/costume_scan` 已丢失、无法重生成）；
  b) 该参数在本模型上确实没有可见效果（数据缺失）。
用 clamp 逐档 pin + 全 drawable 快照就能一次定死。

用法
  py -3 scripts/diag/l2d_param_effect_scan.py [模型] [参数] [档数]
  例：py -3 scripts/diag/l2d_param_effect_scan.py ougen_8 ShoseOff 8

⚠️ **必须先冻结姿态再比快照，否则结论完全不可用**（本工具内置 `NEUTRALIZE`，并会先报
「冻结后本底漂移 N/842」）。不冻结时 idle 每帧把参数写回曲线值、呼吸/物理让全身顶点逐帧漂，
逐档差值**完全非单调**——实测 ougen_8/ShoseOff 会误报「47 个 drawable 随参数变化」并列出
#697 在 want=-0.5 变 32.14、want=+0.25 只变 4.25 这种无意义数字；冻结后真相是 **5 个**，
本底漂移 **0/842**。判据见 docs/TROUBLESHOOTING.md §162 第 4 层、docs/WORKFLOWS.md WF-52。

顺带产出：把「脚/腿区域」（V 空间 x<0 ∧ y<3）的 drawable 全部列出（含 opacity/包围盒/
是否随参数变），用于判定「某部位画面消失」是几何被裁、还是不透明度为 0、还是数据缺件。
"""
import json
import os
import sys
import time

sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts', 'diag'))
from gallery_ui_shots import Page  # noqa: E402

KEY = sys.argv[1] if len(sys.argv) > 1 else 'ougen_8'
PID = sys.argv[2] if len(sys.argv) > 2 else 'ShoseOff'
NSTEP = int(sys.argv[3]) if len(sys.argv) > 3 else 8
BASE = 'http://127.0.0.1:8778/gallery_v2/index.html#gallery_v2'
SNAP_ALL = r"""
(function(){
  var m=(window.__l2ModelRef&&window.__l2ModelRef())||null;
  if(!m||!m.internalModel) return '{"err":"NO_MODEL"}';
  var c=m.internalModel.coreModel, n=c.getDrawableCount(), out=[];
  for(var i=0;i<n;i++){
    var op=0, bx=null;
    try{ op=+c.getDrawableOpacity(i); }catch(e){}
    try{ var v=c.getDrawableVertexPositions(i);
      if(v&&v.length>=2){ var x0=1e9,y0=1e9,x1=-1e9,y1=-1e9;
        for(var k=0;k+1<v.length;k+=2){
          if(v[k]<x0)x0=v[k]; if(v[k]>x1)x1=v[k];
          if(v[k+1]<y0)y0=v[k+1]; if(v[k+1]>y1)y1=v[k+1]; }
        bx=[+x0.toFixed(3),+y0.toFixed(3),+x1.toFixed(3),+y1.toFixed(3)]; } }catch(e){}
    out.push([i,+op.toFixed(4),bx]); }
  return JSON.stringify({n:n, rows:out});
})()
"""

PIN = """(function(){
  var pm=(window.__costumePinsByModel=window.__costumePinsByModel||Object.create(null));
  if(!pm[%(k)s]) pm[%(k)s]=Object.create(null);
  pm[%(k)s][%(p)s]=%(v)s; return 1;})()"""

READ = """(function(){
  var m=(window.__l2ModelRef&&window.__l2ModelRef())||null;
  if(!m||!m.internalModel) return '{"err":"NO_MODEL"}';
  var c=m.internalModel.coreModel, id=%(p)s, ix=c.getParameterIndex(id);
  if(ix<0) return JSON.stringify({err:'NO_IDX'});
  var pm=(window.__costumePinsByModel||{})[%(k)s]||{};
  return JSON.stringify({v:+c.getParameterValueById(id).toFixed(4),
    min:+c.getParameterMinimumValue(ix), max:+c.getParameterMaximumValue(ix),
    pin:(pm[id]===undefined?null:+pm[id])});})()"""

NAMES = """(function(){
  var m=(window.__l2ModelRef&&window.__l2ModelRef())||null;
  if(!m||!m.internalModel) return '[]';
  var c=m.internalModel.coreModel, n=c.getDrawableCount(), out=[];
  for(var i=0;i<n;i++){ var nm='';
    try{ nm=c.getDrawableId(i); }catch(e){}
    out.push([i,nm]); }
  return JSON.stringify(out);})()"""

# 冻住姿态三件套（与 l2d_hotzone_reachability.py 的 NEUTRALIZE 同源）：
# 缺任何一个，参数效果都会被 idle 本底演化淹没 —— 实测未冻结时逐档变化完全非单调
# （#697 在 want=-0.5 变 32、want=+0.25 只变 4.25），那是漂移噪声不是参数驱动。
NEUTRALIZE = """(function(){var m=(window.__l2ModelRef&&window.__l2ModelRef())||null; if(!m) return 'NO_MODEL';
  var im=m.internalModel, mm=im&&im.motionManager, done=[];
  if(mm&&mm.groups){ if(!mm.__idleBak) mm.__idleBak=mm.groups.idle;
    mm.groups.idle='__hz_frozen__'; done.push('idleOff'); }
  try{ if(mm){ mm.queueManager.stopAllMotions(); mm.state.reset&&mm.state.reset(); } done.push('mot'); }catch(e){}
  if(typeof im.updateNaturalMovements==='function'){
    im.updateNaturalMovements=function(){}; done.push('breath'); }
  if(im.physics&&typeof im.physics.reset==='function'){ try{ im.physics.reset(); done.push('phys'); }
    catch(e){} }
  return done.join(',');})()"""


def read(pg):
    return json.loads(pg.ev(READ % {'k': json.dumps(KEY), 'p': json.dumps(PID)}))


def pin(pg, v):
    pg.ev(PIN % {'k': json.dumps(KEY), 'p': json.dumps(PID), 'v': json.dumps(v)})


def unpin(pg):
    pg.ev("""(function(){var pm=(window.__costumePinsByModel||{})[%s]||{};
      delete pm[%s]; return 1;})()""" % (json.dumps(KEY), json.dumps(PID)))


def settle(pg, want, timeout=8.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        r = read(pg)
        if r.get('v') is not None and abs(r['v'] - want) < 1e-2:
            return r
        time.sleep(0.15)
    return read(pg)


def main():
    pg = Page(9411, os.path.join(ROOT, '.diag', 'czh_prof'),
              BASE, (1400, 1000), gpu=True, keepalive=True)
    try:
        time.sleep(3.0)
        pg.ev("""(function(){var b=document.querySelector('#gOpt button[data-k=login]');
           if(b&&(b.classList.contains('on')||b.dataset.on==='1')) b.click(); return 1;})()""")
        time.sleep(0.9)
        print('开卡:', pg.ev("""
        (function(){var s=(window.GALLERY.ships||[]).find(function(x){
             return (x.skins||[]).some(function(k){return k.key===%s;});});
          if(!s) return 'NO_SHIP';
          var c=[...document.querySelectorAll('.card')].find(function(e){
             return (e.textContent||'').indexOf(s.name)>=0;});
          if(!c) return 'NO_CARD'; c.click(); return 'OK:'+s.name;})()
        """ % json.dumps(KEY)))
        time.sleep(1.6)
        print('选肤:', pg.ev("""(function(){var d=[...document.querySelectorAll('#mSkins .skin')].find(function(e){
           return e.dataset.k===%s;}); if(!d) return 'NO_ROW'; d.click(); return 'OK';})()"""
                             % json.dumps(KEY)))
        time.sleep(1.3)
        print('切L2D:', pg.ev("""(function(){var t=[...document.querySelectorAll('#mTabs .tab')].find(function(e){
           return e.dataset.k==='live2d';}); if(!t) return 'NO_TAB';
           if(t.classList.contains('dis')) return 'DIS'; t.click(); return 'OK';})()"""))
        for _ in range(60):
            if pg.ev("(function(){var m=window.__l2ModelRef&&window.__l2ModelRef();"
                     " return m?1:0;})()") == 1:
                break
            time.sleep(1.0)
        print('解耦帧源:', pg.detach_frames(60))
        time.sleep(2.5)
        print('帧源闸: %.1f fps' % pg.require_frames(2.0))
        print('冻结姿态:', pg.ev(NEUTRALIZE))
        time.sleep(1.5)
        pg.require_frames(1.0)

        # 冻结后必须先证几何真的不再动，否则后面的逐档差值全是漂移噪声
        h = []
        for _ in range(4):
            h.append(json.loads(pg.ev(SNAP_ALL)))
            time.sleep(0.5)
        drift = 0
        for i in range(h[0]['n']):
            for k in range(1, 4):
                a, b = h[0]['rows'][i], h[k]['rows'][i]
                db = 0.0
                if a[2] and b[2]:
                    db = max(abs(a[2][0] - b[2][0]), abs(a[2][1] - b[2][1]),
                             abs(a[2][2] - b[2][2]), abs(a[2][3] - b[2][3]))
                if abs((a[1] or 0) - (b[1] or 0)) > 0.02 or db > 0.5:
                    drift += 1
                    break
        print('冻结后本底漂移: %d / %d 个 drawable 仍在变' % (drift, h[0]['n']))
        if drift > 0:
            print('[WARN] 冻结没生效，下面的读数不可信')

        names = dict((int(a), b) for a, b in json.loads(pg.ev(NAMES)))
        r0 = read(pg)
        if r0.get('err'):
            print('[FAIL] 参数读不到:', r0); return 2
        lo, hi = r0['min'], r0['max']
        print('参数 %s: min=%s max=%s 当前=%s' % (PID, lo, hi, r0['v']))

        # 基线档：lo
        pin(pg, lo)
        rb = settle(pg, lo)
        print('pin lo ->', rb)
        base = json.loads(pg.ev(SNAP_ALL))
        if base.get('err'):
            print('[FAIL] 快照失败'); return 2

        steps = [lo + (hi - lo) * i / float(NSTEP) for i in range(NSTEP + 1)]
        driven = {}
        WATCH = [460, 461, 697, 698, 699, 700, 711, 712, 740, 741, 742, 743,
                 764, 765, 785, 786]
        print('\n=== 逐档实测（目标值 → 实际值；关键部件包围盒）===')
        for v in steps[1:]:
            pin(pg, v)
            rr = settle(pg, v)
            s = json.loads(pg.ev(SNAP_ALL))
            if s.get('err'):
                print('[FAIL] 快照失败'); return 2
            got = rr.get('v')
            hit = []
            for i in range(base['n']):
                a, b = base['rows'][i], s['rows'][i]
                dop = abs((a[1] or 0) - (b[1] or 0))
                db = 0.0
                if a[2] and b[2]:
                    db = max(abs(a[2][0] - b[2][0]), abs(a[2][1] - b[2][1]),
                             abs(a[2][2] - b[2][2]), abs(a[2][3] - b[2][3]))
                if dop > 0.02 or db > 0.5:
                    r = driven.setdefault(i, {'maxdop': 0.0, 'maxdb': 0.0, 'at': []})
                    r['maxdop'] = max(r['maxdop'], dop)
                    r['maxdb'] = max(r['maxdb'], db)
                    r['at'].append(got)
            for i in WATCH:
                a, b = base['rows'][i], s['rows'][i]
                db = 0.0
                if a[2] and b[2]:
                    db = max(abs(a[2][0] - b[2][0]), abs(a[2][1] - b[2][1]),
                             abs(a[2][2] - b[2][2]), abs(a[2][3] - b[2][3]))
                hit.append('#%d:%+.2f' % (i, db))
            print('  want=%+.2f got=%+.3f  %s' % (v, got if got is not None else -99,
                                                  ' '.join(hit)))
        print()

        print('\n=== 真正随 %s 变化的 drawable：%d 个 ===' % (PID, len(driven)))
        for i in sorted(driven):
            d = driven[i]
            print('  #%-4d %-30s maxdOp=%.3f maxdBox=%.2f @%s'
                  % (i, names.get(i, '?'), d['maxdop'], d['maxdb'], d['at'][:6]))

        mapped = [460, 461]
        print('\n=== 映射表声明的驱动件 ===')
        for i in mapped:
            d = driven.get(i)
            a = base['rows'][i]
            print('  #%-4d %-30s base(op=%.3f box=%s) 随参数变化=%s'
                  % (i, names.get(i, '?'), a[1], a[2], 'YES' if d else 'NO'))

        # 左半区（V 空间 x<0）低处部件：脚/腿候选
        print('\n=== V 空间 x<0 且 y<3 的部件（脚/腿候选，含不可见）===')
        for i in range(base['n']):
            bx = base['rows'][i][2]
            if not bx:
                continue
            if bx[2] < 0.5 and bx[1] < 3.0:
                print('  #%-4d %-30s op=%.3f box=%s 随参数变=%s'
                      % (i, names.get(i, '?'), base['rows'][i][1], bx,
                         'YES' if i in driven else 'no'))

        unpin(pg)
        print('\n[完成] 已清除 pins')
        return 0
    finally:
        try:
            unpin(pg)
        except Exception:
            pass
        pg.close()


if __name__ == '__main__':
    sys.exit(main())
