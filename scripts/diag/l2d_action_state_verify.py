# -*- coding: utf-8 -*-
r"""跨动作独立状态验收（任务4，走页面真实 play()/真实点击入口）。

守住 5 条：
  A. touch_idle12 内部 KissShow 必须先从低值渐变（不能开播就瞬间 pin=7）；
  B. 动作完成/回落抓到的 KissShow 非零状态，在用户随后直接选 mission 时必须保持；
  C. 对同一个 core 写 0 的干扰：stateTick 开时必须恢复，移除后必须保持 0（机制阴性对照）；
  D. touch_idle11 产生的 3 个身体印记跨普通动作保持；
  E. 互动区真实点击产生的 ShoseOff 状态跨两次动作保持，且新动作姿势 ParamAngleX 能变化。

为什么要阴性对照：只跑“改后保持”可能是动作本来就不覆盖该参数，判据没区分力。
对**同一个 core 写 0 干扰**做 A/B：stateTick 开时恢复、移除后不恢复，才证明机制有效。

用法：
  py -3 scripts/diag/l2d_action_state_verify.py [--ship ougen_8]
环境：GALLERY_URL 可覆盖（默认本项目 8778）。
退出码：0 全过 / 1 判据失败 / 2 探针环境故障。
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding='utf-8')
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cdp_slot       # noqa: E402
import cdp_wait       # noqa: E402
import chrome_tree    # noqa: E402
import websocket      # noqa: E402

CHROME = r'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
URL = os.environ.get('GALLERY_URL') or 'http://127.0.0.1:8778/gallery_v2/index.html'


class Page:
    def __init__(self, tag):
        port, profile = cdp_slot.slot(ROOT, tag)
        self.proc = chrome_tree.install(subprocess.Popen(
            [CHROME, '--headless=new', f'--remote-debugging-port={port}',
             '--remote-allow-origins=*', f'--user-data-dir={profile}',
             '--no-first-run', '--no-default-browser-check',
             '--disable-background-timer-throttling',
             '--enable-unsafe-swiftshader', '--use-angle=swiftshader',
             '--window-size=1280,900', 'about:blank'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        ws = None
        for _ in range(120):
            try:
                tabs = json.load(urllib.request.urlopen(f'http://127.0.0.1:{port}/json'))
                cand = [t for t in tabs if t.get('type') == 'page' and t.get('webSocketDebuggerUrl')]
                if cand:
                    ws = cand[0]['webSocketDebuggerUrl']
                    break
            except Exception:
                pass
            time.sleep(0.5)
        if not ws:
            raise RuntimeError('CDP tab 未出现')
        self.ws = websocket.create_connection(ws, timeout=300, max_size=None)
        self._id = 0
        self.cmd('Page.enable')
        self.cmd('Runtime.enable')
        self.cmd('Page.navigate', {'url': URL})
        ok, secs, last = cdp_wait.wait_ready(self.ev, URL, budget=150)
        print(f'  [ready] {tag} ok={ok} {secs}s')
        if not ok:
            raise RuntimeError(f'页面未就绪: {last}')

    def cmd(self, m, p=None):
        self._id += 1
        mid = self._id
        self.ws.send(json.dumps({'id': mid, 'method': m, 'params': p or {}}))
        while True:
            r = json.loads(self.ws.recv())
            if r.get('id') == mid:
                if 'error' in r:
                    raise RuntimeError(json.dumps(r['error'])[:200])
                return r.get('result', {})

    def ev(self, e):
        r = self.cmd('Runtime.evaluate',
                     {'expression': e, 'returnByValue': True, 'awaitPromise': True})
        if r.get('exceptionDetails'):
            ed = r['exceptionDetails']; ex = ed.get('exception', {}) or {}
            return 'EVALERR ' + str(ex.get('description') or ed.get('text'))[:300]
        return r.get('result', {}).get('value')

    def close(self):
        try:
            self.cmd('Browser.close')
        except Exception:
            pass
        try:
            self.proc.wait(timeout=10)
        except Exception:
            chrome_tree.kill_tree(self.proc.pid, chrome_tree.profile_of(self.proc))


def open_model(pg, skin):
    js = """(async()=>{const t=ms=>new Promise(r=>setTimeout(r,ms));
      let ship=null,sk=null;
      for(const s of GALLERY.ships){const k=s.skins.find(x=>x.key===%s);
        if(k&&s.live2dSkins.includes(%s)){ship=s;sk=k;break;}}
      if(!sk) return 'NO_SKIN';
      openShip(ship);setSkin(sk);buildSkinList(ship);
      const b=[...document.querySelectorAll('#mTabs .tab')].find(x=>x.dataset.k==='live2d');
      if(b)b.click();
      for(let i=0;i<200&&!(l2State&&l2State.app&&l2State.app.stage.children[0]);i++)await t(500);
      return (l2State&&l2State.app&&l2State.app.stage.children[0])?'ok':'NO_MODEL';})()""" % (
          json.dumps(skin), json.dumps(skin))
    return pg.ev(js)


def value(pg, pid):
    v = pg.ev("""(()=>{try{const m=l2State.app.stage.children[0],c=m.internalModel.coreModel;
      const i=c.getParameterIndex(%s);return i>=0?+c.getParameterValueByIndex(i).toFixed(4):null;
      }catch(e){return null;}})()""" % json.dumps(pid))
    return v if isinstance(v, (int, float)) else None


def group(pg):
    return pg.ev("(l2State.app.stage.children[0].internalModel.motionManager.state||{}).currentGroup||null")


def wait_value(pg, pid, pred, budget=90, poll=0.35):
    t0 = time.time(); last = None
    while time.time() - t0 < budget:
        last = value(pg, pid)
        if last is not None and pred(last):
            return last, round(time.time() - t0, 2)
        time.sleep(poll)
    return last, round(time.time() - t0, 2)


def play(pg, g):
    """走页面入口，并等 currentGroup 真进入；startMotion 是 async，返回 played 不等于已进组。"""
    for _ in range(3):
        r = pg.ev(f"window.__l2play({json.dumps(g)},3)?'played':'false'")
        t0 = time.time()
        while time.time() - t0 < 12:
            if group(pg) == g:
                return r
            time.sleep(0.15)
    return 'NOT_ENTERED:' + str(group(pg))


def check(name, ok, detail, fails):
    print(f'  [{"PASS" if ok else "FAIL"}] {name}  {detail}')
    if not ok:
        fails.append(name)


def direct_state_case(skin):
    pg = Page('state_posneg'); fails = []
    try:
        if open_model(pg, skin) != 'ok':
            raise RuntimeError('模型未加载')
        # 无头环境 rAF/SwiftShader 会让动作时间轴慢于 wall-clock，而产品回落定时器按 wall-clock 触发，
        # 会在曲线到达末值前抢先回落（假失败）。探针只把 ticker 加速 4 倍，让曲线先完成；
        # 入口仍是页面 __l2play，不直接调 startMotion。
        pg.ev("l2State.app.ticker.speed=4")
        print('\n== A/C 正向: touch_idle12 完成 → 用户直接选 mission ==')
        before = value(pg, 'KissShow')
        reached = secs = None
        for attempt in range(1, 4):
            # 无头 SwiftShader 下动作时间轴与 wall-clock 回落定时器会竞速；若定时器先到，
            # 该轮曲线还没走到 KissShow 非零段。重播是**仪器稳定化**，不是放宽产品判据。
            pg.ev("(()=>{const p=((window.__actionStatePinsByModel||{}).ougen_8||{});delete p.KissShow;"
                  "const c=l2State.app.stage.children[0].internalModel.coreModel;c.setParameterValueById('KissShow',0);return 1;})()")
            entered = play(pg, 'touch_idle12')
            if attempt == 1:
                check('touch_idle12 真进入 currentGroup', not str(entered).startswith('NOT_ENTERED'),
                      f'play={entered} grp={group(pg)}', fails)
                time.sleep(0.4)
                early = value(pg, 'KissShow')
                pin_early = pg.ev("+((((window.__actionStatePinsByModel||{}).ougen_8||{}).KissShow)||0)")
                check('动作内部过渡未被提前钉成 7', early is not None and early < 1 and pin_early == 0,
                      f'before={before} early={early} pin={pin_early}', fails)
            reached, secs = wait_value(pg, 'KissShow', lambda x: x > 0.55, budget=18, poll=0.04)
            if reached is not None and reached > 0.55:
                break
            print(f'  [RETRY] 第 {attempt} 轮被 wall-clock 回落抢先（value={reached} grp={group(pg)}）')
        check('动作完成/回落时产生非零 KissShow 状态',
              reached is not None and reached > 0.55,
              f'value={reached} after={secs}s grp={group(pg)}', fails)
        if reached is None or reached <= 0.55:
            return fails

        angle0 = value(pg, 'ParamAngleX')
        play(pg, 'mission')
        time.sleep(0.5)
        v05 = value(pg, 'KissShow')
        time.sleep(4.0)
        v45 = value(pg, 'KissShow')
        angle1 = value(pg, 'ParamAngleX')
        pin = pg.ev("+((((window.__actionStatePinsByModel||{}).ougen_8||{}).KissShow)||0)")
        check('用户直接选新动作后 KissShow 保持', v45 is not None and abs(v45 - reached) < 0.15,
              f'pre={reached} v0.5={v05} v4.5={v45} pin={pin}', fails)
        check('新动作姿势仍能接管', angle0 is not None and angle1 is not None and abs(angle1-angle0) > 0.2,
              f'ParamAngleX {angle0} → {angle1}', fails)
        tick_flags = pg.ev("JSON.stringify({state:!!l2State.app.__statePinTick,costume:!!l2State.app.__costumePinTick})")
        check('唯一状态 ticker（无旧 costume ticker）', tick_flags == '{"state":true,"costume":false}',
              str(tick_flags), fails)

        print('\n== 阴性对照: 同一写入，stateTick 开/关必须给出相反结果 ==')
        # A/B 对照必须对**同一个干扰**下手，否则普通动作可能本来就没有 KissShow 曲线，
        # “没掉”不能证明 ticker 有效。先在 ticker 开着时把 core 强写 0（下一帧应恢复），
        # 再移除 ticker、同样写 0（应保持 0）。该写入只用于验证机制，不替代产品入口验收。
        poke = "(()=>{const c=l2State.app.stage.children[0].internalModel.coreModel;c.setParameterValueById('KissShow',0);return 1;})()"
        pg.ev(poke); time.sleep(0.6); restored = value(pg, 'KissShow')
        check('stateTick 开着时会把同一干扰写回状态值',
              restored is not None and abs(restored-reached) < 0.15,
              f'pre={reached} afterPoke={restored}', fails)
        removed = pg.ev("(()=>{const a=l2State.app;if(a&&a.__statePinTick){a.ticker.remove(a.__statePinTick);return 1;}return 0;})()")
        pg.ev(poke); time.sleep(0.6); neg = value(pg, 'KissShow')
        check('禁用 stateTick 后同一干扰保持在默认值',
              removed == 1 and neg is not None and abs(neg) < 0.1,
              f'pre={reached} afterPoke={neg} capturedPin={pin} removed={removed}', fails)
        return fails
    finally:
        pg.close()


def body_and_costume_case(skin):
    pg = Page('state_body'); fails = []
    try:
        if open_model(pg, skin) != 'ok':
            raise RuntimeError('模型未加载')
        pg.ev("l2State.app.ticker.speed=4")
        print('\n== B: touch_idle11 身体印记跨动作 ==')
        vals = {}
        for attempt in range(1, 4):
            entered = play(pg, 'touch_idle11')
            if attempt == 1:
                check('touch_idle11 真进入 currentGroup', not str(entered).startswith('NOT_ENTERED'),
                      f'play={entered} grp={group(pg)}', fails)
            t0 = time.time()
            while time.time() - t0 < 20:
                vals = {p: value(pg, p) for p in ('BoobHeart', 'ButtHeart1', 'ButtHeart2')}
                if all(v is not None and abs(v) > 0.55 for v in vals.values()):
                    break
                time.sleep(0.05)
            if all(v is not None and abs(v) > 0.55 for v in vals.values()):
                break
            print(f'  [RETRY] touch_idle11 第 {attempt} 轮被 wall-clock 回落抢先（values={vals}）')
        created = all(vals.get(p) is not None and abs(vals[p]) > 0.55 for p in vals)
        check('动作实际产生 3 个身体印记', created, f'values={vals} grp={group(pg)}', fails)
        play(pg, 'mission'); time.sleep(4.0)
        after = {p: value(pg, p) for p in vals}
        ok = created and all(after[p] is not None and abs(vals[p]-after[p]) < 0.15 for p in vals)
        check('3 个身体印记跨普通动作保持', ok, f'before={vals} after={after}', fails)

        print('\n== D: 真实互动区点击状态优先 ==')
        # 找产品自己的真实命中点，走 CDP Input.dispatchMouseEvent（不调 __costumeToggle）。
        pt = pg.ev("JSON.stringify(window.__costumeScreenOf&&__costumeScreenOf('ShoseOff'))")
        try:
            point = json.loads(pt)
        except Exception:
            point = None
        if not point or not (point.get('x') or point.get('cx')):
            check('找到 ShoseOff 真实命中点', False, str(pt), fails)
            return fails
        x, y = point.get('x', point.get('cx')), point.get('y', point.get('cy'))
        pg.cmd('Input.dispatchMouseEvent', {'type': 'mousePressed', 'x': x, 'y': y, 'button': 'left', 'clickCount': 1})
        pg.cmd('Input.dispatchMouseEvent', {'type': 'mouseReleased', 'x': x, 'y': y, 'button': 'left', 'clickCount': 1})
        changed, _ = wait_value(pg, 'ShoseOff', lambda z: abs(z) > 0.9, budget=10)
        play(pg, 'mission'); time.sleep(1.0); play(pg, 'touch_head'); time.sleep(4.0)
        kept = value(pg, 'ShoseOff')
        check('真实互动区状态跨两次动作保持', changed is not None and kept is not None and abs(kept-changed) < 0.15,
              f'clicked={changed} after2motions={kept} point=({x:.1f},{y:.1f})', fails)
        return fails
    finally:
        pg.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--ship', default='ougen_8')
    a = ap.parse_args()
    all_fails = []
    try:
        all_fails += direct_state_case(a.ship)
        all_fails += body_and_costume_case(a.ship)
    except Exception as e:
        print('[ERROR] 探针环境故障:', type(e).__name__, e)
        return 2
    print('\n结果:', 'PASS' if not all_fails else 'FAIL ' + ', '.join(all_fails))
    return 0 if not all_fails else 1


if __name__ == '__main__':
    sys.exit(main())
