"""决定性诊断：ShoseOff 有两条产品路径，谁是无效的那条。

已知（写序取证，frame 内顺序）：
  index.html:1762  stateTick  写 pins 值  ← 装扮热区路线
  index.html:2164  costume tween 写渐变值 ← 装扮热区路线
  index.html:2468  stateApply 写 t._on    ← 手工接线路线（STATE_TOGGLES touchdrag17）
  core.update 入口 ← 唯一代表真正上屏的值
实测 update 入口**恒为 -1**，无论 pins 设 1 还是 -1 ⇒ 装扮路线被 stateApply 覆盖。

本脚本用两条独立判据把结论钉死，缺一不算：
  ① 值判据：在 core.update 入口采样，点 touchdrag17 区 vs 点装扮热区，看谁能把值推到 1；
  ② 像素判据：两次截图做差，证明值变化**真的上屏**（否则值对、画面不动，判据仍无效）。
"""
import base64
import json
import os
import sys
import time

sys.stdout.reconfigure(encoding='utf-8')
ROOT = r"d:\azur"
sys.path.insert(0, os.path.join(ROOT, 'scripts', 'diag'))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
from cdp_helper import open_page  # noqa: E402

BASE = 'http://127.0.0.1:8778/gallery_v2/index.html'
KEY = sys.argv[1] if len(sys.argv) > 1 else 'ougen_8'
PID = sys.argv[2] if len(sys.argv) > 2 else 'ShoseOff'
OUT = os.path.join(ROOT, '.diag', 'shoseoff_paths')


def main():
    os.makedirs(OUT, exist_ok=True)
    pg = open_page(BASE, tag='paths')
    try:
        pg.cmd('Network.enable')
        pg.cmd('Network.setCacheDisabled', {'cacheDisabled': True})
        pg.cmd('Page.navigate', {'url': BASE})
        time.sleep(4)
        pg.ev("(function(){var b=document.querySelector('#gOpt button[data-k=login]');"
              " if(b&&(b.classList.contains('on')||b.dataset.on==='1')) b.click(); return 1;})()")
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
        for _ in range(70):
            if pg.ev("(function(){return window.__costumeBoxes?1:0;})()") == 1:
                break
            time.sleep(1)
        time.sleep(1.2)

        # 渲染值采样桩：只在 core.update 入口取（定版时刻）
        STUB = r"""(function(){
          var m=(window.__l2ModelRef&&window.__l2ModelRef())||null;
          if(!m||!m.internalModel) return '{"err":"NO_MODEL"}';
          var core=m.internalModel.coreModel;
          if(core.__rpStub) return '{"err":"ALREADY"}';
          core.__rpStub=true;
          window.__rp={hist:[], n:0};
          var up=core.update.bind(core);
          core.update=function(){
            var v=null; try{ v=+core.getParameterValueById(__P__).toFixed(3); }catch(e){}
            window.__rp.hist.push(v); if(window.__rp.hist.length>200) window.__rp.hist.shift();
            window.__rp.n++;
            return up.apply(core, arguments);
          };
          return JSON.stringify({ok:1});})()""".replace('__P__', json.dumps(PID))
        for _ in range(20):
            st = pg.ev(STUB)
            if st and 'err' not in st:
                break
            time.sleep(1.0)
        print('采样桩:', st)

        # 收窄观察窗：只截模型画布区域，减少无关 UI 干扰
        wrapbox = json.loads(pg.ev("""(function(){var r=document.getElementById('l2wrap').getBoundingClientRect();
          return JSON.stringify({x:Math.round(r.left),y:Math.round(r.top),
            width:Math.round(r.width),height:Math.round(r.height)});})()"""))
        print('观察窗:', wrapbox)

        def render_capture(tag):
            shots = []
            for i in range(3):
                time.sleep(0.7)
                d = pg.cmd('Page.captureScreenshot', {'format': 'png', 'clip': dict(wrapbox, scale=1)})
                raw = base64.b64decode(d['data'])
                shots.append(raw)
            pg.ev("(function(){window.__rp.hist=[]; window.__rp.n=0; return 1;})()")
            time.sleep(1.4)
            hist = json.loads(pg.ev("(function(){return JSON.stringify(window.__rp.hist||[]);})()")) or []
            import hashlib
            hs = [hashlib.md5(s).hexdigest()[:10] for s in shots]
            print('   %-22s 渲染值历史=%s 帧数=%s 截图md5=%s'
                  % (tag, hist[-6:] if hist else '[]',
                     pg.ev("(function(){return window.__rp.n;})()"), hs))
            # 存最后一张供人眼比对
            with open(os.path.join(OUT, tag.replace(' ', '_').replace('/', '_') + '.png'), 'wb') as f:
                f.write(shots[-1])
            return hist, hs

        def click(x, y):
            for typ in ('mousePressed', 'mouseReleased'):
                pg.cmd('Input.dispatchMouseEvent', {'type': typ, 'x': x, 'y': y,
                                                   'button': 'left', 'clickCount': 1})
                time.sleep(0.08)

        # 找到能点到 touchdrag17 的屏幕点（用产品公式换算 V 空间）
        td17 = json.loads(pg.ev("""(function(){
          var m=(window.__l2ModelRef&&window.__l2ModelRef())||null; if(!m) return 'null';
          var im=m.internalModel, ppu=im.pixelsPerUnit||1;
          var r=document.getElementById('l2wrap').getBoundingClientRect();
          for(var sy=r.top+4; sy<r.bottom-4; sy+=5){
            for(var sx=r.left+4; sx<r.right-4; sx+=5){
              var lp=m.toLocal(new window.PIXI.Point(sx-r.left, sy-r.top));
              var VX=lp.x/ppu-(im.width/ppu)/2, VY=(im.height/ppu)/2-lp.y/ppu;
              var a=(window.__L2_HITALL&&window.__L2_HITALL(VX,VY))||[];
              for(var k=0;k<a.length;k++){
                if(String(a[k]).toLowerCase()==='touchdrag17') return JSON.stringify([sx,sy]); }
            }}
          return 'null';})()"""))
        print('touchdrag17 可点屏幕点:', td17)

        soff = json.loads(pg.ev("JSON.stringify(window.__costumeScreenOf(%s)||null)" % json.dumps(PID)))
        print('装扮热区点:', [soff['cx'], soff['cy']], 'edge=', soff['edge'])

        print('\n基线（未点击）:')
        base_hist, base_md5 = render_capture('00_baseline')

        print('\n路径 A：点装扮热区（costumeHitAt → costumeToggle）:')
        click(soff['cx'], soff['cy'])
        a_hist, a_md5 = render_capture('01_click_costume_hotzone')

        # 复位
        print('\n复位: 直接清 pins')
        pg.ev("(function(){var pm=(window.__costumePinsByModel||{})[%s]||{}; delete pm[%s];"
              " var tw=(window.__costumeTweens||{})[%s]||{}; delete tw[%s]; return 1;})()"
              % (json.dumps(KEY), json.dumps(PID), json.dumps(KEY), json.dumps(PID)))
        time.sleep(2.0)
        render_capture('02_after_reset')

        if td17:
            print('\n路径 B：点 touchdrag17 互动区（stateFind → toggleState）:')
            click(td17[0], td17[1])
            b_hist, b_md5 = render_capture('03_click_touchdrag17')
        else:
            print('\n路径 B：找不到 touchdrag17 可点点，跳过'); b_hist, b_md5 = [], []

        print('\n=== 结论矩阵 ===')
        print('  路径 A（装扮热区） 渲染值历史尾部:', a_hist[-4:] if a_hist else '[]')
        print('  路径 B（touchdrag17）渲染值历史尾部:', b_hist[-4:] if b_hist else '[]')
        print('  基线截图 md5:', base_md5)
        print('  路径A截图 md5:', a_md5, '=> 与基线相同?', a_md5[2] == base_md5[2])
        print('  路径B截图 md5:', b_md5, '=> 与基线相同?', b_md5[2] == base_md5[2] if b_md5 else 'n/a')
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())
