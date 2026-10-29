# -*- coding: utf-8 -*-
r"""参数型互动区的**可点击性清单**（需求②验收）：每条换装/眼睛/渐变参数到底能不能点。

## 为什么需要这份清单

一个参数"有热区"不等于"点得到"。已知三种点不到的情形（都是本项目实测过的）：

1. **驱动件为空**：`BondEyes`/`HeartEyes` 在 ougen_8 里 `n_drawables=0`
   ⇒ `buildCosGeo()` 直接 `continue`，热区根本不存在。
2. **几何小到屏幕上是几个像素**：`Paramring` 的多边形只有 0.30×0.18（V 空间），
   视口缩小时落不到一个像素格上，人根本点不中。
3. **全靠幽灵区**：`NeckMoney` 在待机态 `vis=0`（隐藏件），第一次靠"幽灵区第二遍"能点到，
   但用户把它关掉之后就再没有可见件可认。

所以判据必须是**屏幕像素**口径，不是 V 空间面积。

## 判据

对每条参数输出：
- `parts / nVis`：驱动件数 / 其中此刻可见数
- `vbox`：V 空间包围盒（含 COS_MIN_SIDE 兜底后的实际判定盒）
- `px`：该盒投到屏幕上的像素宽高（用当前相机 scale）—— **< 8px 视为人体工学上点不到**
- `clickable`：在盒内打 9×9 网格，有多少点真的命中自己（`__costumeHitV` 与产品同一函数）

## 用法

    py -3 scripts/diag/l2d_hotzone_clickable.py [模型key] [--json out.json]

退出码：0 = 每条参数都点得到；1 = 有点不到的参数（清单里会列出原因）。
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

import websocket

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
sys.path.insert(0, os.path.join(ROOT, 'scripts', 'diag'))
import cdp_slot      # noqa: E402
import chrome_tree   # noqa: E402  ⚠️ 必须在 launch() 之前导入

CHROME = os.environ.get('CHROME_PATH') or r'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
URL = os.environ.get('GALLERY_URL') or 'http://127.0.0.1:8778/gallery_v2/index.html'
KEY = next((a for a in sys.argv[1:] if not a.startswith('--')), 'ougen_8')
OUT = sys.argv[sys.argv.index('--json') + 1] if '--json' in sys.argv else None

#: 屏幕像素下限。8px 是"鼠标能稳定命中一个方块的边"的经验值；
#: 再小就不是用户点不准，而是设计上没打算让人点到。
MIN_PX = 8.0


JS = r"""(async(cfg)=>{ try{
  const KEY=cfg.key;
  const t=ms=>new Promise(r=>setTimeout(r,ms));
  for(let i=0;i<200 && !(window.GALLERY&&typeof openShip==='function'&&typeof stopLive2D==='function');i++) await t(300);
  let ship=null, sk=null;
  for(const s of GALLERY.ships){ const k=s.skins.find(x=>x.key===KEY); if(k&&s.live2dSkins.includes(KEY)){ship=s;sk=k;break;} }
  if(!sk) return JSON.stringify({skip:'no skin'});
  /* 必须走**页面自己的打开流程**（openShip → setSkin → buildSkinList → 切到 live2d 页），
     不能只调 `stopLive2D(); renderLive2D(...)`。只调后者时 #l2wrap 还没被布局（该面板没显示），
     `refit()` 拿到的视口尺寸是退化的 ⇒ 模型 scale 停在 1e-4 量级、位置 -0.47，
     V→屏幕换算出来每条参数都只有 0.0~0.3 px，整张表全红——那是取景没做，不是点不到。
     实测同一页面走完整流程后 scale≈0.08（与 hit_verify 一致）。 */
  openShip(ship); setSkin(sk); buildSkinList(ship);
  const l2=[...document.querySelectorAll('#mTabs .tab')].find(x=>x.dataset.k==='live2d');
  if(l2) l2.click();
  await t(600);
  /* 等模型真进舞台（大贴图皮肤要几秒） */
  for(let i=0;i<200 && !(l2State&&l2State.app&&l2State.app.stage.children[0]);i++) await t(300);
  if(!(l2State&&l2State.app&&l2State.app.stage.children[0]))
    return JSON.stringify({err:'模型 60s 内没进舞台（探针故障）'});
  const im=l2State.app.stage.children[0].internalModel, core=im.coreModel;

  /* 等齐三样再动手：COSTUME 行（json 晚到）、PARAM_DRAWABLES 映射、以及 ticker 建出的几何。
     实测时间线：模型 0.4s 就在 stage 上，但 COSTUME/PARAM_DRAWABLES 直到 **3.2s** 才到，
     几何再到 **4.0s** 才建出来（单线程服务器 + 大贴图）。旧的 7s 预算在数据更慢那轮就会空手，
     然后报「几何一直没建出来」——那是探针预算不足，不是产品缺陷。 */
  let geo=[], nRows=0;
  for(let i=0;i<150;i++){
    nRows=((window.COSTUME||{})[KEY]||[]).length;
    geo=(window.__costumeGeoByModel||{})[KEY]||[];
    if(nRows && geo.length) break;
    await t(150);
  }
  if(!nRows) return JSON.stringify({err:'COSTUME 行 22.5s 内没加载（探针预算不足或 json 缺失）'});
  if(!geo.length) return JSON.stringify({err:'几何 22.5s 内没建出来（ticker 未跑或映射缺失）'});
  window.__costumeGeoFreeze=true; await t(200);
  geo=(window.__costumeGeoByModel||{})[KEY]||[];

  const rows=(window.COSTUME||{})[KEY]||[];
  const map=(window.PARAM_DRAWABLES||{})[KEY]||{};
  const mdl0=l2State.app.stage.children[0];
  const sc=(mdl0&&mdl0.scale&&+mdl0.scale.x)||0;
  /* V 空间 → 屏幕像素必须乘 pixelsPerUnit：pixi-live2d 的 stage scale 是**像素→屏幕**，
     而 V 是 Cubism 的模型单位。漏掉 ppu 会得到小 5~6 个数量级的读数（实测 0.0001），
     于是每条参数的"屏幕尺寸"都变成 0.0×0.0，整张表全红 —— 那是换算错，不是点不到。
     产品自己的 `__costumeScreenOf` 用的正是 `(vx+cux/2)*ppu*s`，这里与它对齐。 */
  const ppu=(mdl0&&mdl0.internalModel&&mdl0.internalModel.pixelsPerUnit)||1;
  const k=ppu*sc;
  if(!(k>0)) return JSON.stringify({err:'换算系数为 0（模型未取景）', scale:sc, ppu:ppu});

  const out=[];
  for(const it of rows){
    const b=geo.find(g=>g.id===it.id);
    const drv=(map[it.id]||[]).length;
    if(!b){
      out.push({id:it.id, label:it.label, kind:it.kind, drv:drv, present:false,
                reason: drv? '几何缺失（驱动件取不到顶点）':'驱动件为空 ⇒ 没有热区'});
      continue;
    }
    const g=b.box;
    /* 9×9 网格实测命中自己多少个点（与产品同一个 __costumeHitV） */
    let own=0, tot=0;
    for(let ix=0;ix<9;ix++) for(let iy=0;iy<9;iy++){
      const vx=g.x0+(g.x1-g.x0)*(ix+0.5)/9, vy=g.y0+(g.y1-g.y0)*(iy+0.5)/9;
      tot++;
      const me=window.__costumeHitV? window.__costumeHitV(vx,vy):null;
      if(me && (me.id||me)===it.id) own++;
    }
    const wPx=(g.x1-g.x0)*k, hPx=(g.y1-g.y0)*k;
    out.push({id:it.id, label:it.label, kind:it.kind, drv:drv, present:true,
      n:b.n, nVis:b.nVis, nMark:b.nMark||0,
      vbox:[+g.x0.toFixed(2),+g.y0.toFixed(2),+g.x1.toFixed(2),+g.y1.toFixed(2)],
      vw:+(g.x1-g.x0).toFixed(3), vh:+(g.y1-g.y0).toFixed(3),
      pxW:+wPx.toFixed(1), pxH:+hPx.toFixed(1),
      own:own, tot:tot, ownPct: Math.round(1000*own/tot)/10});
  }
  window.__costumeGeoFreeze=false;
  return JSON.stringify({key:KEY, scale:+sc.toFixed(6), ppu:ppu, pxPerV:+k.toFixed(6),
    viewport:[window.innerWidth,window.innerHeight], rows:out});
}catch(e){ return JSON.stringify({err:''+(e&&e.message||e)}); }})"""


def main():
    port, profile = cdp_slot.slot(ROOT, 'clickv')
    proc = chrome_tree.launch(
        [CHROME, '--headless=new', f'--remote-debugging-port={port}',
         f'--user-data-dir={profile}', '--no-first-run', '--no-default-browser-check',
         '--disable-background-timer-throttling', '--enable-unsafe-swiftshader',
         '--use-angle=swiftshader', '--window-size=1280,900', URL],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ws = None
    try:
        target = None
        for _ in range(90):
            try:
                tabs = json.load(urllib.request.urlopen(f'http://127.0.0.1:{port}/json'))
                cand = [t['webSocketDebuggerUrl'] for t in tabs
                        if 'gallery_v2' in t.get('url', '') and t.get('webSocketDebuggerUrl')]
                if cand:
                    target = cand[0]
                    break
            except Exception:
                pass
            time.sleep(0.5)
        if not target:
            print('[ERROR] 找不到画廊 tab（探针故障）')
            return 2
        ws = websocket.create_connection(target, timeout=900, max_size=None)
        st = {'id': 0}

        def cmd(method, params=None, tmo=900):
            st['id'] += 1
            mid = st['id']
            ws.send(json.dumps({'id': mid, 'method': method, 'params': params or {}}))
            ws.settimeout(tmo)
            while True:
                r = json.loads(ws.recv())
                if r.get('id') == mid:
                    if 'error' in r:
                        raise RuntimeError(json.dumps(r['error'])[:200])
                    return r.get('result', {})

        def ev(expr):
            last = None
            for _ in range(4):
                try:
                    r = cmd('Runtime.evaluate', {'expression': expr,
                                                'returnByValue': True, 'awaitPromise': True})
                except Exception as ex:
                    last = ex
                    if 'destroyed' in str(ex) or 'Cannot find context' in str(ex):
                        time.sleep(2)
                        continue
                    raise
                if r.get('exceptionDetails'):
                    det = r['exceptionDetails']
                    return 'EVALERR ' + str(det.get('text')) + ' :: ' + \
                        str(det.get('exception', {}).get('description', ''))[:600]
                return r.get('result', {}).get('value')
            return 'EVALFAIL ' + str(last)[:200]

        raw = ev(JS + '(%s)' % json.dumps({'key': KEY}))
        if not isinstance(raw, str) or not raw.lstrip().startswith('{'):
            print('[ERROR] 页面求值失败（探针故障）：', str(raw)[:600])
            return 2
        d = json.loads(raw)
        if 'err' in d:
            print('[ERROR] 页内异常：', d['err'][:400])
            return 2
        if 'skip' in d:
            print(f'[SKIP] 画廊里没有 {KEY} 的 Live2D 皮肤')
            return 2
        if OUT:
            open(OUT, 'w', encoding='utf-8').write(json.dumps(d, ensure_ascii=False, indent=1))

        print(f"模型 {KEY}  scale={d['scale']}  ppu={d['ppu']}  "
              f"换算={d['pxPerV']} 屏幕px/V  视口 {d['viewport'][0]}×{d['viewport'][1]}")
        print('%-14s %-8s %5s %5s %5s %14s %16s %7s %s'
              % ('参数', '类别', '驱动', '可见', '标记', 'V 盒尺寸', '屏幕像素', '自身覆盖', '判定'))
        bad = []
        for r in d['rows']:
            if not r['present']:
                print('%-14s %-8s %5d %s  %s' % (r['id'], r['kind'], r['drv'],
                                                 ' ' * 30, r['reason']))
                bad.append((r['id'], r['reason']))
                continue
            # 判定分两级，别把设计行为当缺陷：
            #  · 屏幕尺寸：小于 MIN_PX 就真是人体工学上点不到（项目实测 Paramring 15.4×15.4 仍可点）
            #  · 自身覆盖：只做提示，不做硬判据。面积大的热区（ShoseOff 238×321）天然会有大片
            #    "多边形没有的边角"，`own` 低是几何形状造成的，用户照样点得到它。硬卡 30% 会把
            #    Cloth2/ShoseOff 判成不可点，而它们在 hit_verify 里是能点中的。
            tooSmall = min(r['pxW'], r['pxH']) < MIN_PX
            covered = r['ownPct'] >= 30.0
            if tooSmall:
                why = '屏幕 %.1f×%.1f px < %.0f ⇒ 点不到' % (r['pxW'], r['pxH'], MIN_PX)
            else:
                why = ''
            if why:
                bad.append((r['id'], why))
            print('%-14s %-8s %5d %5d %5d %14s %16s %6.1f%% %s'
                  % (r['id'], r['kind'], r['drv'], r['nVis'], r['nMark'],
                     '%.2f×%.2f' % (r['vw'], r['vh']),
                     '%.1f×%.1f' % (r['pxW'], r['pxH']),
                     r['ownPct'],
                     ('OK' if not why else '✗ ' + why)
                     + ('' if covered else '  （覆盖偏低，几何形状所致）')))
        print()
        if bad:
            print('点不到的参数 %d / %d：' % (len(bad), len(d['rows'])))
            for pid, why in bad:
                print('   %-14s %s' % (pid, why))
            return 1
        print('全部 %d 条参数屏幕尺寸 ≥ %.0fpx（可点击）；'
              '覆盖偏低的在判定列里单独标注' % (len(d['rows']), MIN_PX))
        return 0
    finally:
        try:
            if ws is not None:
                ws.close()
        except Exception:
            pass
        chrome_tree.kill_tree(proc.pid)


if __name__ == '__main__':
    sys.exit(main())
