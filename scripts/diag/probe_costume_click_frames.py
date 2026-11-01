"""点热区后逐帧记录：参数值 + 目标 drawable 的 opacity/顶点 —— 查「参数变成 1 了，但部件没变」的真伪。

背景（2026-10-24）：验收脚本两次运行结果不一致——一次变化集合含 ShoseOff 驱动的 [460,461]，
一次不含。而 probe_param_value_states 证明 0 vs 1 之间**确实**有 2 个 drawable 的 opacity 差异。
所以必须逐帧看清「点击之后，渲染时刻的参数到底是多少、部件到底变没变」。

做法：在 `coreModel.update` **入口**装采样器（记录 参数值 + 460/461 的 opacity + 顶点包围盒 +
时钟），再派发真实点击，等 2.5s 取回全部采样。判据落在**渲染同一帧**的参数与部件上，不跨帧猜。
输出只打印**变化窗口**（首个变化前 6 帧起、800ms 内），并附产品自己的 `__costumeLog`（空了就说明
点击根本没进 `onUp`，不是"产品没效果"）与 `__stateTogglesInfo`（确认让渡已发生）。

⚠️ 为什么挂在 `coreModel.update` 入口而不是 `requestAnimationFrame`（2026-10-28 修）：
  本探针跑在 headless 页上，而 headless 的出帧源会在加载 18–30 秒后降到 1 Hz 甚至完全停掉
  rAF（零产品代码的极简页同样复现，见 TROUBLESHOOTING §158 续六）。rAF 采样器于是拿到
  0–1 帧/秒的稀疏点，`t=+…ms` 全是几百毫秒一跳。`coreModel.update` 是**渲染的真正入口**，
  挂在它上面拿到的是「每一帧渲染读到的值」，与浏览器出帧源无关（配 `detach_frames()` 推帧即可稳定）。
  另外：`pin` 键在 `JSON.stringify` 里会**被丢掉**（pins 为空时值为 `undefined`，而 stringify
  不写 undefined 键）⇒ 旧版逐行 `r['pin']` 直接 KeyError 崩掉。现在显式归一成 null。

用法: py -3 scripts/diag/probe_costume_click_frames.py ougen_8 ShoseOff
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

from gallery_ui_shots import Page  # noqa: E402

KEY = sys.argv[1] if len(sys.argv) > 1 else 'ougen_8'
PID = sys.argv[2] if len(sys.argv) > 2 else 'ShoseOff'
BASE = 'http://127.0.0.1:8778/gallery_v2/index.html#gallery_v2'

# 采样器：**挂在 coreModel.update 入口**（渲染真正读到的值），记录 参数值 + 驱动部件
# opacity/包围盒 + 时间 + currentGroup。见文件头「为什么不用 rAF」。
START_SAMPLER = r"""
(function(){
  var m=(window.__l2ModelRef&&window.__l2ModelRef())||null;
  if(!m||!m.internalModel) return 'NO_MODEL';
  var core=m.internalModel.coreModel, pid=%s;
  if(core.__czfWrapped) return 'ALREADY';
  core.__czfWrapped=true;
  var drv=(window.PARAM_DRAWABLES||{})[%s]||{};
  var idxs=drv[pid]||[];
  window.__czf={rows:[], idxs:idxs, pid:pid, on:true};
  var oupdate=core.update.bind(core);
  core.update=function(){
    var r=oupdate.apply(this, arguments);
    if(!window.__czf.on) return r;
    var ix=-1; try{ ix=this.getParameterIndex(pid); }catch(e){}
    var pv=null; try{ pv=+this.getParameterValueById(pid).toFixed(4); }catch(e){}
    var pin=(window.__costumePinsByModel||{})[%s]||{};
    var row={t:Math.round(performance.now()), v:(ix<0?null:pv),
             pin:(pin[pid]===undefined?null:+pin[pid]),
             g:((m.internalModel.motionManager.state||{}).currentGroup)||null,
             d:[]};
    for(var k=0;k<idxs.length;k++){
      var i=idxs[k], op=null, bx=null;
      try{ op=+this.getDrawableOpacity(i).toFixed(4); }catch(e){}
      try{ var p=this.getDrawableVertexPositions(i);
        if(p&&p.length>=2){ var xs=[],ys=[];
          for(var q=0;q+1<p.length;q+=2){xs.push(p[q]);ys.push(p[q+1]);}
          bx=[Math.min.apply(null,xs),Math.min.apply(null,ys),
              Math.max.apply(null,xs),Math.max.apply(null,ys)]; } }catch(e){}
      row.d.push([i,op,bx]);
    }
    window.__czf.rows.push(row);
    return r;
  };
  return 'STARTED idxs='+JSON.stringify(idxs);
})()
"""


def main():
    try:
        with urllib.request.urlopen(BASE, timeout=6) as r:
            assert r.status == 200
    except Exception as e:  # noqa: BLE001
        print('[INVALID]', e); return 2
    pg = Page(9409, r'D:\azur\.diag\czf_prof', BASE, (1400, 1000), gpu=True, keepalive=False)
    try:
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
        for _ in range(40):
            time.sleep(1.0)
            if pg.ev("((window.__l2ModelRef&&window.__l2ModelRef()) && window.COSTUME && window.PARAM_DRAWABLES)?1:0") == 1:
                break
        if pg.ev("((window.__l2ModelRef&&window.__l2ModelRef())?1:0)") != 1:
            print('[FAIL] 模型未加载'); return 2
        print('解耦帧源:', pg.detach_frames(60))
        time.sleep(3.0)
        print('帧源闸: %.1f fps' % pg.require_frames(2.0))

        scr = pg.ev("JSON.stringify(window.__costumeScreenOf(%s))" % json.dumps(PID))
        sc = json.loads(scr)
        if not sc:
            print('[FAIL] __costumeScreenOf 为 null'); return 1
        print('屏幕点:', sc)
        print('命中:', pg.ev("JSON.stringify(window.__costumeHit(%d,%d))" % (sc['cx'], sc['cy'])))
        print('采样器:', pg.ev(START_SAMPLER % (json.dumps(PID), json.dumps(KEY), json.dumps(KEY))))
        time.sleep(0.6)   # 采几帧基线
        for typ in ('mousePressed', 'mouseReleased'):
            pg.cmd('Input.dispatchMouseEvent', {'type': typ, 'x': sc['cx'], 'y': sc['cy'],
                                                'button': 'left', 'clickCount': 1})
            time.sleep(0.06)
        print('已点击')
        time.sleep(2.0)
        pg.ev("(window.__czf.on=false, 1)")
        rows = json.loads(pg.ev("JSON.stringify(window.__czf.rows)") or '[]')
        print('采样 %d 帧' % len(rows))
        t0 = rows[0]['t'] if rows else 0
        # 打印**变化窗口**而不是从头 2.2 秒（点击经 CDP 派发，真正落到产品代码可能滞后数百毫秒；
        # 固定窗口会打印出一整片点击前的基线，看着像"参数没动"，属第十一条仪器 bug 的近亲）。
        i0 = next((i for i, r in enumerate(rows) if r.get('v') != rows[0].get('v')), None)
        if i0 is None:
            print('  ⚠️ 全程无变化（v 恒 %s）' % rows[0].get('v'))
            view = rows[:4]
        else:
            print('  ★ 首个变化出现在 t=+%dms（v=%s → %s）'
                  % (rows[i0]['t'] - t0, rows[0].get('v'), rows[i0].get('v')))
            lo_i = max(0, i0 - 6)
            view = [r for r in rows[lo_i:] if r['t'] - rows[i0]['t'] <= 800]
        for r in view:
            # `pin`/`g` 在 JSON 里可能缺键（`undefined` 被 stringify 丢掉），一律用 get 兜底。
            line = '  t=%+5dms v=%s pin=%s g=%s ' % (r['t'] - t0, r.get('v'),
                                                     r.get('pin'), r.get('g'))
            parts = []
            for d in r['d']:
                parts.append('%d(op=%s,bx=%s)' % (d[0], d[1],
                                                  'null' if not d[2] else
                                                  '[%.2f,%.2f,%.2f,%.2f]' % tuple(d[2])))
            line += ' | '.join(parts)
            print(line)
        # ---- 汇总（判「点击到底有没有进产品代码」不靠肉眼扫行）----
        vs = [r.get('v') for r in rows if r.get('v') is not None]
        print('\n汇总: 帧=%d  v范围=[%s, %s]  相异值=%d  首帧g=%s 末帧t=+%dms'
              % (len(rows), min(vs) if vs else None, max(vs) if vs else None,
                 len(set(vs)), rows[0].get('g') if rows else None,
                 (rows[-1]['t'] - t0) if rows else 0))
        # 仪器自证：产品自己的点击日志。空了就说明**点击根本没进 onUp**（不是产品没效果）。
        log = json.loads(pg.ev("JSON.stringify(window.__costumeLog||null)") or 'null')
        print('__costumeLog:', log)
        print('__stateTogglesInfo:', pg.ev("JSON.stringify(__stateTogglesInfo?__stateTogglesInfo():[])") or '[]')
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())
