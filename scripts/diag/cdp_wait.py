# -*- coding: utf-8 -*-
"""CDP 页面就绪等待——不要用 `document.readyState` 当门槛。

🔴 2026-10-27 实测踩到的假失败总根因
    headless Chrome 起来后，`/json` 里那条 tab 的 `url` 已经写着目标页，但此刻 CDP 会话
    连上的**执行上下文还是 `about:blank`**。而 `about:blank` 的 `document.readyState`
    天生就是 `'complete'` ⇒ 于是 `while readyState != 'complete': sleep()` 这种门槛
    **第一次判就放行**，后续所有 `Runtime.evaluate` 全打在空白页上，症状是：

      - `typeof openShip === 'undefined'` / `ERR openShip is not defined`
      - `document.scripts.length === 0`（页面脚本一个都没加载）
      - `Cannot read properties of undefined (reading 'internalModel')`
      - `Execution context was destroyed`（导航把旧上下文干掉）

    这些都被当成「产品坏了 / 样本不存在」记进了假绿和假红里。真实页面
    （263KB html + vendor live2d + 5 模型索引）在这台机器上要 **约 41 秒**才 `complete`。

✅ 正确的就绪判据（三件同时成立）
    1. `location.href` 真的等于目标 URL（不是 `about:blank`）
    2. `document.readyState === 'complete'`
    3. 业务标志在（默认 `window.GALLERY`）

    `Execution context was destroyed` 在导航期间属正常，重试即可，不能据此判产品故障。

用法
    from cdp_wait import wait_ready
    wait_ready(ev, 'http://127.0.0.1:8778/gallery_v2/index.html', budget=120)
"""
import time


def page_state(ev):
    """一次探针读回 (href, readyState)。读不到（上下文被销毁）返回 (None, None)。"""
    try:
        href = ev('location.href')
        if isinstance(href, str) and href.startswith('EVALERR'):
            return None, None
        return href, ev('document.readyState')
    except RuntimeError:
        return None, None


def wait_ready(ev, want_url, budget=120, flag='window.GALLERY', poll=1.0, quiet=True):
    """等到 `want_url` 真的加载完且业务标志就绪。返回 (ok, 已用秒数, 最后一次状态)。

    budget 默认 120 秒：实测本项目画廊页面 `complete` 需约 41 秒，留三倍余量。
    """
    tail = str(want_url).split('//')[-1].rstrip('/')
    t0 = time.time()
    last = (None, None, None)
    while time.time() - t0 < budget:
        href, rs = page_state(ev)
        have = None
        if href is not None and rs == 'complete':
            try:
                have = ev(flag) if flag else True
            except RuntimeError:
                have = None
        last = (href, rs, have)
        if href is not None and tail in href and rs == 'complete' and have:
            return True, round(time.time() - t0, 1), last
        time.sleep(poll)
    return False, round(time.time() - t0, 1), last


def eval_when_ready(ev, want_url, expr, budget=120, flag='window.GALLERY'):
    """等就绪后再求值，避免把脚本送进 about:blank。返回 (value, ok, 秒数)。"""
    ok, secs, _ = wait_ready(ev, want_url, budget=budget, flag=flag)
    if not ok:
        return None, False, secs
    return ev(expr), True, secs
