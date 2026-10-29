# -*- coding: utf-8 -*-
r"""跨动作参数保留的验收（需求④）：以**渲染有效值**为判据，逐动作全量扫。

## 为什么不能读参数回读值

产品把参数 pin 重放在 `internalModel` 的 `beforeModelUpdate` 事件里。Cubism 的顺序是：

    motionManager.update（写曲线值）
      → saveParameters
      → emit beforeModelUpdate（产品在此写 pin）
      → core.update()        ← 用当前值计算 drawable
      → loadParameters（把参数复原成存档值）

所以任意时刻从外部读 `getParameterValueById` 看到的是**曲线值**，不是渲染值。
本项目已用 A/B/C/D 四组对照证明过这个坑（见 `gallery_src/index.html` 里 `stateApply`
上方的取证注释：只写 LOW 的 A 组"参数读回 [1,1]，可见帧 0"）。

本脚本因此**在 `beforeModelUpdate` 上后注册**一个监听器 —— 产品先注册、我们后注册，
同名事件按注册顺序回调 ⇒ 我们读到的就是 `core.update` 即将使用的值 = 用户看到的那一帧。

## 判据

1. 把每条装扮参数钉到某一侧（奇偶各取一侧，保证两侧都覆盖）；
2. 逐动作播放，动作期间持续采样「渲染有效值」；
3. 断言：每条参数的有效值必须始终落在被钉的那一侧（容差 = 值域 8%）。

## 输出与退出码

逐动作列出不符合项；末行给出通过/失败计数。退出码 0 = 全部保持，1 = 有被拉走。
`--limit N` 只跑前 N 个动作（快速自检用）。

用法：
    py -3 scripts/diag/l2d_param_retain_verify.py [模型key] [--limit N]
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
import cdp_slot      # noqa: E402  端口/profile 一律不写死
import chrome_tree   # noqa: E402  ⚠️ 必须在 launch() 之前导入

CHROME = os.environ.get('CHROME_PATH') or r'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
URL = os.environ.get('GALLERY_URL') or 'http://127.0.0.1:8778/gallery_v2/index.html'
KEY = next((a for a in sys.argv[1:] if not a.startswith('--')), 'ougen_8')
LIMIT = int(sys.argv[sys.argv.index('--limit') + 1]) if '--limit' in sys.argv else 0


def main():
    port, profile = cdp_slot.slot(ROOT, 'retainv')
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
            print('[ERROR] 找不到画廊 tab（探针故障，非产品故障）')
            return 2
        ws = websocket.create_connection(target, timeout=900, max_size=None)
        state = {'id': 0}

        def cmd(method, params=None, tmo=900):
            state['id'] += 1
            mid = state['id']
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

        out = ev(JS + '(%s)' % json.dumps({'key': KEY, 'limit': LIMIT}))
        if not isinstance(out, str) or not out.lstrip().startswith('{'):
            print('[ERROR] 页面求值失败（探针故障，非产品故障）：', str(out)[:600])
            return 2
        d = json.loads(out)
        if 'err' in d:
            print('[ERROR] 页内异常：', d['err'][:400])
            print('       现场：', json.dumps({k: v for k, v in d.items() if k != 'err'},
                                            ensure_ascii=False))
            return 2
        if 'skip' in d:
            print(f'[SKIP] 画廊里没有 {KEY} 的 Live2D 皮肤')
            return 2

        print(f"模型 {KEY}  动作 {d['probeN']}/{d['nGroups']}  装扮参数 {len(d['ids'])} 条"
              f"  监听器触发 {d.get('fired')} 帧")
        # 🔴 反假绿灯（AGENTS.md 规则 5）：监听器没触发 ⇒ eff 是空的 ⇒ 循环里一次比较都不做，
        # "0 个被拉走"是空断言。这类空结果必须判红，绝不能当结论。
        if not d['ids'] or not d.get('fired') or not any(d.get('baseline') or {}):
            print('[FAIL] 仪器没采到渲染有效值（监听器未触发 / 参数表为空 / 监听器异常:'
                  + str(d.get('lerr') or '无') + '）—— 这是仪器故障，不是产品合格')
            return 2
        print('用户设定：', json.dumps(d['wantSide'], ensure_ascii=False))
        print('基线渲染有效值：', json.dumps(d['baseline'], ensure_ascii=False))
        rows = [x for x in d['out'] if x.get('played')]
        skipped = [x for x in d['out'] if x.get('skipped')]
        bad_rows = [x for x in rows if x['bad']]
        print(f"→ 播放成功 {len(rows)} 个 | 渲染有效值被拉离设定 {len(bad_rows)} 个"
              + (f" | 无法播放 {len(skipped)} 个" if skipped else ''))
        agg = {}
        for x in bad_rows:
            for k, c in x['bad'].items():
                agg[k] = agg.get(k, 0) + 1
        for k, c in sorted(agg.items(), key=lambda kv: -kv[1])[:15]:
            print('   %-48s 出现于 %d/%d 个动作' % (k, c, len(rows)))
        for x in bad_rows[:10]:
            print('   FAIL', x['group'], json.dumps(x['bad'], ensure_ascii=False))
        return 0 if (rows and not bad_rows) else 1
    finally:
        # 强杀下 atexit 不跑；launch() 的 Job Object 是内核级兜底（见 chrome_tree docstring）
        try:
            if ws is not None:
                ws.close()
        except Exception:
            pass
        chrome_tree.kill_tree(proc.pid)


JS = r"""(async(cfg)=>{ try{
  const KEY=cfg.key, LIMIT=cfg.limit;
  const t=ms=>new Promise(r=>setTimeout(r,ms));
  for(let i=0;i<200 && !(window.GALLERY&&typeof openShip==='function'&&typeof stopLive2D==='function');i++) await t(300);
  let ship=null, sk=null;
  for(const s of GALLERY.ships){ const k=s.skins.find(x=>x.key===KEY); if(k&&s.live2dSkins.includes(KEY)){ship=s;sk=k;break;} }
  if(!sk) return JSON.stringify({skip:'no skin'});
  stopLive2D(); await renderLive2D(ship, sk); await t(2500);
  const im=l2State.app.stage.children[0].internalModel, mm=im.motionManager, core=im.coreModel;
  const rows=(window.COSTUME||{})[KEY]||[];
  if(!(window.__costumePinsByModel)) window.__costumePinsByModel=Object.create(null);
  const pins=window.__costumePinsByModel[KEY]||(window.__costumePinsByModel[KEY]=Object.create(null));
  const ids=rows.map(r=>r.id);
  const rng=id=>{ const ix=core.getParameterIndex(id); let lo=0,hi=1;
    try{ lo=core.getParameterMinimumValue(ix); hi=core.getParameterMaximumValue(ix); }catch(e){}
    return [lo,hi]; };

  /* 采样点：把 `core.update` 包一层，**原函数返回之后**立刻读参数值。
     为什么不用 `beforeModelUpdate` 事件：那个 emit 在本页实测**不稳定**（同一个模型，
     限跑 3 个动作时触发 15 帧，跑全量时一帧都不触发），拿它当判据会得到空断言。
     为什么"返回之后"读仍然等于渲染值：`core.update()` 用当时的参数值算完所有 drawable，
     之后 motionManager 才 loadParameters 把参数复原成曲线值。所以 update 刚返回那一刻
     读到的就是**这一帧真正用于渲染的值**。不依赖任何 emit。 */
  const eff={}, diag={on:0, fired:0, err:'', hooks:0, rehooks:0};
  /* 自愈挂钩：`coreModel` 会随换肤/重建而换成新对象，一次性包旧对象会得到 fired=0 的
     空断言（实测限跑 3 个动作触发 65 帧、跑全量一帧都不触发 —— 就是撞上重建）。
     这里周期性地重新解析当前模型的 coreModel，没包过就包一次（用函数自身标记防重包）。 */
  const hookOnce=(im2)=>{
    try{
      const cm2=im2&&im2.coreModel; if(!cm2) return false;
      if(cm2.update && cm2.update.__retainWrapped) return true;
      const orig=cm2.update.bind(cm2);
      const wrapped=(...a)=>{ const r=orig(...a);
        try{ if(diag.on){ diag.fired++;
          for(const id of ids) eff[id]=+cm2.getParameterValueById(id).toFixed(4); } }
        catch(e){ diag.err=String((e&&e.message)||e).slice(0,200); }
        return r; };
      wrapped.__retainWrapped=1;
      cm2.update=wrapped; diag.hooks++;
      return true;
    }catch(e){ diag.err=String((e&&e.message)||e).slice(0,200); return false; }
  };
  const curIM=()=>{ try{ const st=l2State&&l2State.app&&l2State.app.stage;
    return st&&st.children&&st.children[0]?st.children[0].internalModel:null; }catch(e){ return null; } };
  hookOnce(curIM());
  const rehookTimer=setInterval(()=>{ const im2=curIM(); if(im2&&!hookOnce(im2)) return;
    if(im2&&diag.hooks>1) diag.rehooks++; }, 250);

  const want={}, wantSide={};
  ids.forEach((id,k)=>{ const rg=rng(id);
    want[id]=(k%2===0)?rg[1]:rg[0]; wantSide[id]=(k%2===0)?'on':'off'; pins[id]=want[id]; });
  await t(500);
  diag.on=1;
  /* 等监听器真采到一帧再取基线：固定 sleep 会在模型还没进渲染循环时（连跑多个模型、
     服务器单线程、大贴图解码）落到空结果上，于是整个循环一次比较都不做 ——
     "0 个被拉走"是空断言（AGENTS.md 规则 5 那类假绿灯）。轮询到有值为止。 */
  let baseline={};
  for(let i=0;i<60;i++){ await t(150);
    const keys=Object.keys(eff);
    if(keys.length && keys.every(k=>typeof eff[k]==='number')){ baseline=Object.assign({}, eff); break; } }
  if(!Object.keys(baseline).length)
    return JSON.stringify({err:'监听器在 9s 内没采到任何渲染有效值',
      fired:diag.fired, lerr:diag.err, nIds:ids.length, hooks:diag.hooks, rehooks:diag.rehooks,
      wrapped:!!(curIM()&&curIM().coreModel&&curIM().coreModel.update&&curIM().coreModel.update.__retainWrapped),
      hasUpd:!!(curIM()&&curIM().coreModel&&typeof curIM().coreModel.update==='function'),
      effKeys:Object.keys(eff).length,
      tickerRunning:(l2State&&l2State.app&&l2State.app.ticker)?!!l2State.app.ticker.started:null,
      stageKids:(l2State&&l2State.app&&l2State.app.stage)?l2State.app.stage.children.length:null});
  await t(200);

  const groups=Object.keys(mm.definitions||{}).sort();
  const probe=LIMIT? groups.slice(0,LIMIT) : groups;
  const res=[];
  for(const g of probe){
    let played=false; try{ played=!!mm.startMotion(g,0,3); }catch(e){}
    if(!played){ res.push({group:g, skipped:true}); continue; }
    const bad={};
    for(let i=0;i<26;i++){
      await t(110);
      for(const id of ids){
        const v=eff[id]; if(typeof v!=='number') continue;
        const rg=rng(id);
        if(Math.abs(rg[1]-rg[0])<1e-6) continue;   /* 值域无跨度 ⇒ 无判据 */
        const tol=Math.max(0.08*Math.abs(rg[1]-rg[0]),0.02);
        if(Math.abs(v-want[id])>tol){
          const k=id+' 有效值='+v.toFixed(3)+' 应为'+want[id].toFixed(3);
          bad[k]=(bad[k]||0)+1;
        }
      }
    }
    res.push({group:g, played:true, bad});
  }
  diag.on=0; try{ clearInterval(rehookTimer); }catch(e){}
  try{ const cm3=curIM()&&curIM().coreModel; if(cm3) delete cm3.update; }catch(e){}
  return JSON.stringify({wantSide:wantSide, baseline:baseline, ids:ids, fired:diag.fired, lerr:diag.err,
    nGroups:groups.length, probeN:probe.length, out:res});
}catch(e){ return JSON.stringify({err:''+(e&&e.message||e)}); }})"""


if __name__ == '__main__':
    sys.exit(main())
