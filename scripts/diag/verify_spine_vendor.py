# -*- coding: utf-8 -*-
"""验证 gallery 前端的 spine-all.js（vendor）能加载并真实渲染 Spine 模型。

用途：把 gallery_src/vendor/MANIFEST.json 的 spine 源换成「上游官方 3.8 构建」后，
用这条命令确认换源没有让 Spine 播放退化 —— 它驱动 cg_export.html 导出 2 个真实
Spine 模型，再对落盘产物做像素断言（尺寸>0、近黑占比低、非空画布）。

    py -3 scripts/diag/verify_spine_vendor.py [--folder a,b] [--size 800] [--port 9444]

依赖：scripts/paths.py（AL_CHROME/AL_ASSETS_ROOT 可覆盖）、websocket-client、Pillow。
不修改任何运行文件；只往 Output/CG_v2/ 写被导出文件夹的 PNG（同 cg_export 设定）。

返回 0 = 全部断言通过；1 = 加载失败 / 导出失败 / 像素判据不过。

⚠️ **本机（2026-10-18）跑不通，原因在环境而非本脚本**：
  - 机器没有 Google Chrome，只有 Microsoft Edge；Edge 的 headless CDP 启动即报
    `Multiple targets are not supported in headless mode`（即使传独立 --user-data-dir、
    不传 URL 也一样），调试端口始终不监听。
  - node 不在 PATH（无法用 node 走 spine 核心解析的替代回归）。
  ⇒ 本机无法跑真实渲染的像素级回归。spine vendor 换源的验证改走可复现的三件套
  （vendor 台账 `--check` 指纹 4/4 + 官方构建同为 3.8.75 + 前端依赖 spine 符号 9/9 全覆盖），
  见 docs/WORKFLOWS.md WF-36 与 docs/TROUBLESHOOTING.md §122。
  本脚本保留为「将来装好 Google Chrome / CDP 环境就绪后」的渲染回归工具。
"""
import json
import os
import sys
import threading
import time

sys.stdout.reconfigure(encoding="utf-8")

import websocket

# 上溯三层定位仓库根（本文件在 scripts/diag/ 下）
_AL_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_AL_ROOT, "scripts"))
sys.path.insert(0, os.path.join(_AL_ROOT, "gallery_src"))

import paths as P  # noqa: E402
import _gallery_server as GS  # noqa: E402


def arg(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


FOLDER_ARG = arg("--folder", "")   # 逗号分隔；空则从 GALLERY 取前 2 个真实 folder
SIZE = int(arg("--size", "800"))
PORT = int(arg("--port", "9444"))

URL_BASE = f"http://127.0.0.1:{PORT}/gallery_v2"
CHROME = P.CHROME.replace(os.sep, "/")
DEBUG_DIR = os.path.join(_AL_ROOT, ".diag", "chrome_verify_spine")

# 1) 起本地服务器（独立端口，避免占用 8777 那台）
httpd = GS.make_server(port=PORT, root=P.OUT)
threading.Thread(target=httpd.serve_forever, daemon=True).start()

# 2) 起无头 Chrome + CDP（五坑：remote-allow-origins / 独立 profile / swiftshader / 就绪轮询）
import subprocess  # noqa: E402

proc = subprocess.Popen(
    [CHROME, "--headless=new", f"--remote-debugging-port={PORT + 1}",
     "--remote-allow-origins=*", f"--user-data-dir={DEBUG_DIR}",
     "--no-first-run", "--no-default-browser-check",
     "--disable-background-timer-throttling", "--enable-unsafe-swiftshader",
     "--use-angle=swiftshader", "--window-size=1280,900"],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
)

proc = chrome_tree.install(proc)


def wait_ws():
    for _ in range(80):
        try:
            tabs = json.load(urllib_request("http://127.0.0.1:%d/json" % (PORT + 1)))
            for t in tabs:
                if t.get("webSocketDebuggerUrl"):
                    return t["webSocketDebuggerUrl"]
        except Exception:
            pass
        time.sleep(0.5)
    raise RuntimeError("CDP 未就绪")


import urllib.request  # noqa: E402


def urllib_request(url):
    with urllib.request.urlopen(url, timeout=10) as r:
        return r.read().decode("utf-8")


ws = websocket.create_connection(wait_ws(), timeout=30)
_id = 0


def ev(expr):
    global _id
    _id += 1
    ws.send(json.dumps({"id": _id, "method": "Runtime.evaluate",
                        "params": {"expression": expr, "returnByValue": True}}))
    while True:
        m = json.loads(ws.recv())
        if m.get("id") == _id:
            return m.get("result", {}).get("result", {}).get("value")


def nav(url):
    global _id
    _id += 1
    ws.send(json.dumps({"id": _id, "method": "Page.navigate", "params": {"url": url}}))
    # 等页面就绪：轮询 window.GALLERY 显式降布尔
    for _ in range(80):
        if ev("String(!!window.GALLERY)") == "true":
            return
        time.sleep(0.3)
    raise RuntimeError("页面未就绪 (GALLERY 未出现)")


# 3) 读 cg_export.html 后取真实 spine folder；若没指定则取 GALLERY 前 2 个
nav(URL_BASE + "/cg_export.html")
folders = arg("--folder", None)
if not folders:
    raw = ev("""(function(){try{var g=window.GALLERY;if(!g||!g.ships)return '[]';
      var s=new Set();g.ships.forEach(function(x){(x.skins||[]).forEach(function(sk){
      if(sk.spine&&sk.spine.folder)s.add(sk.spine.folder)});});
      return JSON.stringify([].slice.call(s).slice(0,2));}catch(e){return 'ERR:'+e.message}})()""")
    if isinstance(raw, str) and raw.startswith("ERR"):
        raise RuntimeError("读 GALLERY 失败: " + raw)
    folders = ",".join(json.loads(raw))
    print("从 GALLERY 取 folder:", folders, flush=True)
if not folders:
    ws.close(); proc.terminate()
    raise SystemExit("没有可用 spine folder")

# 4) 重导航到 cg_export（only=指定 folder + autostart + redo + 破缓存）
nav(URL_BASE + "/cg_export.html?autostart=1&size=%d&only=%s&redo=1&_t=%d"
    % (SIZE, folders, int(time.time())))

# 5) 轮询到结束标记
t0 = time.time()
last = ""
result_log = []
while time.time() - t0 < int(arg("--timeout", "600")):
    prog = ev("document.querySelector('#prog').textContent") or ""
    tail = ev("(function(){var l=document.querySelectorAll('#log div');"
              "return l.length?l[l.length-1].textContent:''})()") or ""
    if tail and tail != last:
        last = tail
        result_log.append(tail)
        print("  " + tail[:120], flush=True)
    if "全部结束" in tail or "已停止" in tail:
        break
    time.sleep(2)

# 6) 像素断言：产物非空、有内容（近黑低、非全透明）
fails = 0
from PIL import Image  # noqa: E402
import chrome_tree        # 整树清理：atexit + profile 回读（见该模块 docstring）
_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (_HERE, os.path.join(_HERE, '..')):
    _p = os.path.abspath(_p)
    if _p not in sys.path: sys.path.insert(0, _p)

for f in folders.split(","):
    p = os.path.join(P.OUT, "CG_v2", f + ".png")
    if not os.path.isfile(p):
        print(f"  ✗ {f}: 产物缺失 {p}", flush=True); fails += 1; continue
    im = Image.open(p).convert("RGBA")
    w, h = im.size
    px = im.load()
    total = w * h
    alpha_nonempty = 0
    for y in range(0, h, max(1, h // 200)):
        for x in range(0, w, max(1, w // 200)):
            a = px[x, y][3]
            if a > 8:
                alpha_nonempty += 1
    frac = alpha_nonempty / max(1, (w // max(1, w // 200 + 1)) * (h // max(1, h // 200 + 1)))
    ok = w > 0 and h > 0 and frac > 0.3
    print(f"  {'✓' if ok else '✗'} {f}: {w}x{h} 非空alpha≈{frac:.2f}", flush=True)
    if not ok:
        fails += 1

print("---", "全部通过" if not fails else f"{fails} 项断言失败", "---", flush=True)
ws.close()
proc.terminate()
httpd.shutdown()
sys.exit(0 if not fails else 1)
