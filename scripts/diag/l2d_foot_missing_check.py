"""一次性：ougen_8 左脚/左腿/第二只鞋到底在不在？在就该看得见，不在就是数据缺件（只读）。

判据分层（顺序固定，缺一层结论就不可信）：
  ① 画布与相机：模型的 V 空间画布多大、左脚包围盒是否落在画布/视口之外（= 被裁掉）
  ② 部件本身：脚/腿/鞋候选 drawable 的 opacity、渲染序、顶点包围盒（= 有没有画）
  ③ 找配对：把鞋的包围盒按 x 轴镜像，看有没有另一个 drawable 落在镜像位置（= 第二只鞋）
  ④ 与旧画廊同模型同帧比对（旧画廊目录里资产字节相同 ⇒ 差异只可能在运行时/取景）
全程冻结姿态，避免呼吸/物理让读数漂。
"""
import json
import os
import sys
import time

sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts', 'diag'))
from gallery_ui_shots import Page  # noqa: E402

KEY = sys.argv[1] if len(sys.argv) > 1 else 'ougen_8'
BASE = 'http://127.0.0.1:8778/gallery_v2/index.html#gallery_v2'

CLOSE_LOGIN = """(function(){var b=document.querySelector('#gOpt button[data-k=login]');
   if(b&&(b.classList.contains('on')||b.dataset.on==='1')) b.click(); return 1;})()"""
OPEN_SHIP = """(function(){var k=%s;
  var s=(window.GALLERY.ships||[]).find(function(x){
     return (x.skins||[]).some(function(o){return o.key===k;});});
  if(!s) return 'NO_SHIP';
  var c=[...document.querySelectorAll('.card')].find(function(e){
     return (e.textContent||'').indexOf(s.name)>=0;});
  if(!c) return 'NO_CARD'; c.click(); return 'OK:'+s.name;})()"""
PICK_SKIN = """(function(){var d=[...document.querySelectorAll('#mSkins .skin')].find(function(e){
   return e.dataset.k===%s;}); if(!d) return 'NO_ROW'; d.click(); return 'OK';})()"""
TO_L2D = """(function(){var t=[...document.querySelectorAll('#mTabs .tab')].find(function(e){
   return e.dataset.k==='live2d';}); if(!t) return 'NO_TAB';
   if(t.classList.contains('dis')) return 'DIS'; t.click(); return 'OK';})()"""

NEUTRALIZE = """(function(){var m=(window.__l2ModelRef&&window.__l2ModelRef())||null; if(!m) return 'NO_MODEL';
  var im=m.internalModel, mm=im&&im.motionManager, done=[];
  if(mm&&mm.groups){ if(!mm.__idleBak) mm.__idleBak=mm.groups.idle;
    mm.groups.idle='__hz_frozen__'; done.push('idleOff'); }
  try{ if(mm){ mm.queueManager.stopAllMotions(); mm.state.reset&&mm.state.reset(); } done.push('mot'); }catch(e){}
  if(typeof im.updateNaturalMovements==='function'){
    im.updateNaturalMovements=function(){}; done.push('breath'); }
  if(im.physics&&typeof im.physics.reset==='function'){ try{ im.physics.reset(); done.push('physReset'); }catch(e){} }
  return done.join(',');})()"""

VIEWRECT = r"""(function(){
  /* 画布在**整页截图**里的真实位置（页面 CSS 像素）。
     为什么必须问页面而不是从像素反推：Page.shot() 是 Page.captureScreenshot 整页截图，
     左侧还有画廊侧栏；而本文件其它片段里用到的 toS()/__costumeScreenOf 给的是
     **相对 canvas 左上角**的 stage 坐标（gallery_src/index.html:2393 已写明）。
     两者直接相减 ⇒ 差一个侧栏宽度（实测 292 px），会把「画出来的脚」量成「0 内容」。
     2026-10-29 实测：不加偏移时左鞋区内容覆盖率 0%，加偏移后 99.4% —— 纯仪器假阴性。 */
  /* ⚠️ 必须取 #l2wrap 里的那块画布，不能用 document.querySelector('canvas')：
     画廊缩略图/其它视图也会建 canvas，第一个 canvas 实测是个 986x627 的家伙
     （2026-10-29 踩过：拿错对象 ⇒ 回报 left=0 top=0 width=1370，看着"整页都是画布"）。 */
  var out={};
  try{ var cv=document.querySelector('#l2wrap canvas');
    if(cv){ var r=cv.getBoundingClientRect();
      out.canvas={left:r.left,top:r.top,width:r.width,height:r.height,
                  right:r.right,bottom:r.bottom,cw:cv.width,ch:cv.height}; } }catch(e){}
  /* 页面里所有 canvas 都报一遍：第一个不一定是模型那块（画廊自己的缩略图也建 canvas）。 */
  out.allCanvas=[];
  document.querySelectorAll('canvas').forEach(function(c){
    var r=c.getBoundingClientRect();
    out.allCanvas.push({id:c.id||'', cls:c.className||'', parent:(c.parentElement&&c.parentElement.id)||'',
      left:Math.round(r.left), top:Math.round(r.top), w:Math.round(r.width), h:Math.round(r.height),
      cw:c.width, ch:c.height}); });
  ['mView','l2wrap','l2panel','l2bar'].forEach(function(id){
    var e=document.getElementById(id); if(!e) return;
    var r=e.getBoundingClientRect();
    out[id]={left:Math.round(r.left),top:Math.round(r.top),
             width:Math.round(r.width),height:Math.round(r.height)}; });
  out.dpr=window.devicePixelRatio||1;
  out.inner=[window.innerWidth, window.innerHeight];
  out.bodyScroll=[document.documentElement.scrollWidth, document.documentElement.scrollHeight];
  return JSON.stringify(out);})()"""

CANVAS = r"""(function(){
  var m=(window.__l2ModelRef&&window.__l2ModelRef())||null; if(!m||!m.internalModel)
    return JSON.stringify({err:'NO_MODEL'});
  var im=m.internalModel, c=im.coreModel, ppu=im.pixelsPerUnit||1;
  var r=m.getBoundingBox&&m.getBoundingBox();
  return JSON.stringify({
    canvasW:im.width, canvasH:im.height, ppu:ppu,
    cux:+(im.width/ppu).toFixed(3), cuy:+(im.height/ppu).toFixed(3),
    originX:im.originalWidth, originY:im.originalHeight,
    mdlX:+m.x.toFixed(2), mdlY:+m.y.toFixed(2), scaleX:+m.scale.x.toFixed(4),
    modelBB:r?[+r.x.toFixed(2),+r.y.toFixed(2),+(r.x+r.width).toFixed(2),+(r.y+r.height).toFixed(2)]:null,
    drawableCount:c.getDrawableCount(),
    partCount:c.getPartCount()
  });})()"""

DUMP = r"""(function(){
  var m=(window.__l2ModelRef&&window.__l2ModelRef())||null; if(!m||!m.internalModel)
    return JSON.stringify({err:'NO_MODEL'});
  var c=m.internalModel.coreModel, n=c.getDrawableCount(), out=[];
  var ro=null; try{ ro=c.getDrawableRenderOrders(0); }catch(e){}
  /* 父 Part 索引/名：判「第二只鞋」要看它挂在哪个 Part 下，而不是靠包围盒猜 */
  var pid=null;
  try{ pid=c._model&&c._model.drawableParentPartIndices; }catch(e){}
  var pnames=null;
  try{ pnames=(c._partIds&&c._partIds._ptr)||c._partIds||null; }catch(e){}
  for(var i=0;i<n;i++){
    var op=0, bx=null, nm='';
    try{ op=+c.getDrawableOpacity(i); }catch(e){}
    try{ nm=String(c.getDrawableId(i)); }catch(e){}
    var vis=null; try{ vis=c.getDrawableDynamicFlagIsVisible(i)?1:0; }catch(e){}
    var mc=null; try{ var a=c.getDrawableMaskCounts(); mc=a?+a[i]:null; }catch(e){}
    var mk=null; try{ var ms=c.getDrawableMasks(); if(ms&&ms[i]!=null){ var s=[]; var q=ms[i];
        if(q&&q._ptr){ for(var z=0;z<(q._size||0);z++) s.push(+q._ptr[z]); } 
        else { for(var z2=0;z2<q.length;z2++) s.push(+q[z2]); }
        mk=s.slice(0,6); } }catch(e){}
    var pp=null; try{ if(pid&&pid[i]!=null) pp=pid[i]; }catch(e){}
    var pn=''; try{ if(pp!=null&&pnames&&pnames[pp]!=null) pn=String(pnames[pp]); }catch(e){}
    var uv0=null;
    try{ var u=c.getDrawableVertexUvs(i);
      if(u&&u.length>=2){ var a0=1e9,b0=1e9,a1=-1e9,b1=-1e9;
        for(var k2=0;k2+1<u.length;k2+=2){
          if(u[k2]<a0)a0=u[k2]; if(u[k2]>a1)a1=u[k2];
          if(u[k2+1]<b0)b0=u[k2+1]; if(u[k2+1]>b1)b1=u[k2+1]; }
        uv0=[+a0.toFixed(4),+b0.toFixed(4),+a1.toFixed(4),+b1.toFixed(4)]; } }catch(e){}
    try{ var v=c.getDrawableVertexPositions(i);
      if(v&&v.length>=2){ var x0=1e9,y0=1e9,x1=-1e9,y1=-1e9;
        for(var k=0;k+1<v.length;k+=2){
          if(v[k]<x0)x0=v[k]; if(v[k]>x1)x1=v[k];
          if(v[k+1]<y0)y0=v[k+1]; if(v[k+1]>y1)y1=v[k+1]; }
        bx=[+x0.toFixed(3),+y0.toFixed(3),+x1.toFixed(3),+y1.toFixed(3)]; } }catch(e){}
    out.push([i,nm,+op.toFixed(3),bx,(ro&&ro[i]!=null)?ro[i]:null,vis,pn,mc,mk,uv0]);
  }
  return JSON.stringify({n:n, rows:out});})()"""

PARTS = r"""(function(){
  var m=(window.__l2ModelRef&&window.__l2ModelRef())||null; if(!m||!m.internalModel)
    return JSON.stringify({err:'NO_MODEL'});
  var c=m.internalModel.coreModel, n=c.getPartCount(), out=[];
  /* getPartId 在这个包装里没实现（全返回空串），退回框架内部的 _partIds 原始数组 */
  var raw=null;
  try{ raw=(c._partIds&&c._partIds._ptr)||c._partIds||null; }catch(e){}
  for(var i=0;i<n;i++){
    var nm='', op=null;
    try{ nm=String(c.getPartId(i)); }catch(e){}
    if(!nm || nm==='undefined'){ try{ if(raw&&raw[i]!=null) nm=String(raw[i]); }catch(e){} }
    try{ op=+c.getPartOpacity(i); }catch(e){}
    out.push([i,nm,op]);
  }
  return JSON.stringify({n:n, rows:out});})()"""


def main():
    pg = Page(9412, r'D:\azur\.diag\l2foot_prof', BASE, (1400, 1000),
              gpu=True, keepalive=True)
    try:
        time.sleep(4.0)
        # 画廊数据是异步拉的，GALLERY 未就绪时点卡片会报 undefined.ships
        gok = 0
        for _ in range(40):
            gok = pg.ev("(function(){ return (window.GALLERY&&(window.GALLERY.ships||[]).length)"
                        " ? 1 : 0; })()")
            if gok == 1:
                break
            time.sleep(1.0)
        print('画廊就绪:', gok)
        pg.ev(CLOSE_LOGIN)
        time.sleep(0.9)
        print('开卡:', pg.ev(OPEN_SHIP % json.dumps(KEY)))
        time.sleep(1.6)
        print('选肤:', pg.ev(PICK_SKIN % json.dumps(KEY)))
        time.sleep(1.3)
        print('切L2D:', pg.ev(TO_L2D))
        MODEL = "(function(){ return (window.__l2ModelRef&&window.__l2ModelRef())?1:0; })()"
        ok = 0
        for _ in range(60):
            ok = pg.ev("(function(){ return %s ? 1 : 0; })()" % MODEL)
            if ok == 1:
                break
            time.sleep(1.0)
        if ok != 1:
            print('[FAIL] 模型未就绪')
            return
        print('帧源:', pg.detach_frames(60))
        time.sleep(3.0)
        print('   闸: %.1f fps' % pg.require_frames(2.0))
        print('冻结:', pg.ev(NEUTRALIZE))
        time.sleep(1.5)
        pg.require_frames(1.0)
        VIEW = json.loads(pg.ev(VIEWRECT))
        print('\n=== ⓪ 画布在整页截图中的位置（像素判定的基准，缺了它一切像素结论都不可信）===')
        print(json.dumps(VIEW, indent=2, ensure_ascii=False))
        with open(r'D:\azur\.diag\view_rect.json', 'w', encoding='utf-8') as f:
            json.dump({'key': KEY, 'shot': r'D:\azur\.diag\foot_shot.png', 'view': VIEW},
                      f, ensure_ascii=False, indent=2)
        # 取一张原始截图供人工判读「左脚到底在不在」：数字全绿也可能只是画在别处
        pg.shot(r'D:\azur\.diag\foot_shot.png')
        print('截图: .diag\\foot_shot.png')
        print('\n=== ① 画布与相机 ===')
        cv = json.loads(pg.ev(CANVAS))
        print(json.dumps(cv, indent=2, ensure_ascii=False))
        dump = json.loads(pg.ev(DUMP))
        parts = json.loads(pg.ev(PARTS))
        print('\n=== Part 列表（%d 个）===' % parts.get('n', -1))
        for p in parts.get('rows') or []:
            print('  part[%3d] %-28s op=%s' % (p[0], p[1], p[2]))

        rows = dump.get('rows') or []
        print('\n=== ② 下半身候选（V 空间 y<2，按 x 排序）===')
        low = [r for r in rows if r[3] and r[3][1] < 2]
        low.sort(key=lambda r: r[3][0])
        for r in low:
            print('  #%-4d %-16s op=%.3f ro=%-4s vis=%s part=%-10s mask=%s box=%s uv=%s'
                  % (r[0], r[1], r[2], r[4], r[5], r[6], r[7], r[3], r[8]))

        print('\n=== ②b 被遮罩（mask>0）的部件：这是「数据在、被裁掉」的头号候选 ===')
        mk = [r for r in rows if r[3] and (r[7] or 0) > 0]
        print('  有遮罩的 drawable 共 %d / %d' % (len(mk), len(rows)))
        vism = [r for r in mk if r[2] > 0.01 and r[5] == 1]
        print('  其中 op>0.01 且 dynamicVisible=1 的 %d 个，按渲染序（大=在上）：' % len(vism))
        for r in sorted(vism, key=lambda r: -(int(r[4]) if str(r[4]).isdigit() else 0)):
            print('    ro=%-4s #%-4d %-16s op=%.3f mask=%s part=%-10s box=%s'
                  % (r[4], r[0], r[1], r[2], r[7], r[6], r[3]))

        print('\n=== ③ 找配对：不透明度>0 的部件，按包围盒中心聚成左右两簇 ===')
        vis = [r for r in rows if r[3] and r[2] > 0.01]
        print('  可见部件数 = %d' % len(vis))
        xs = sorted(v[3][0] for v in vis)
        if xs:
            print('  x0 范围 %.2f .. %.2f，中位数 %.2f'
                  % (xs[0], xs[-1], xs[len(xs) // 2]))
        left = [v for v in vis if (v[3][0] + v[3][2]) / 2 < -4]
        print('\n  中心 x < -4 的可见部件（画面最左那块，鞋/左脚应在此）：')
        for r in sorted(left, key=lambda r: r[3][1]):
            print('    #%-4d %-16s op=%.3f ro=%-4s part=%-10s mask=%s box=%s'
                  % (r[0], r[1], r[2], r[4], r[6], r[7], r[3]))
        right = [v for v in vis if (v[3][0] + v[3][2]) / 2 > 4]
        print('\n  中心 x > 4 的可见部件（应为右脚/右腿）：')
        for r in sorted(right, key=lambda r: r[3][1]):
            print('    #%-4d %-16s op=%.3f ro=%-4s part=%-10s mask=%s box=%s'
                  % (r[0], r[1], r[2], r[4], r[6], r[7], r[3]))
        print('\n  镜像对照：把所有可见部件按 x=0 镜像后，看左侧是否有对应件')
        hits = 0
        for r in right:
            mx0, mx1 = -r[3][2], -r[3][0]
            cand = [l for l in left
                    if not (l[3][2] < mx0 - 1.2 or l[3][0] > mx1 + 1.2)]
            if cand:
                hits += 1
                print('    右 #%-4d %-15s 镜像x[%.2f,%.2f] → 左候选 %s'
                      % (r[0], r[1], mx0, mx1,
                         ', '.join('#%d %s' % (c[0], c[1]) for c in cand[:3])))
        print('  右侧 %d 个可见件里，左侧有镜像候选的 = %d 个' % (len(right), hits))
    finally:
        pg.close()


if __name__ == '__main__':
    main()
