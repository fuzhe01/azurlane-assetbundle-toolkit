# -*- coding: utf-8 -*-
"""本地 Live2D 目视页服务器（8777）。

用途：让 `Output/l2d_visual.html` 里以相对路径加载的 model3.json / moc3 / 贴图 / physics3 /
motion3 资源全部可访问——只靠 `SimpleHTTPRequestHandler` 会因两类请求 404 而黑屏，
故在 do_GET 里做了两处 rewrite：

① pixi 把 model3 的完整 URL（**含文件名**）当成资源 base 目录，于是请求形如
   `.../<dir>/<name>.model3.json/<res>`；把它 rewrite 回真实资源 `.../<dir>/<res>`。
② 对以 '/' 结尾、去掉斜杠后是真实文件的请求退回 serve 该文件，避免尾斜杠 404。

一键启动：`py -3 scripts/diag/serve_live2d.py`（根目录 = `Output/`，端口 8777）。
如需可靠重启 + 自验证，见同目录 `ensure_server_l2d.py`；无头验证播放见 `vis_auto_l2d.py`。
"""
import os, sys, re, http.server, threading
os.chdir(r'D:\Azur Lane Assets\Output')

# 匹配 `.../<dir>/<name>.model3.json/<res>`，取其 <dir> 前缀 + <res>
MODEL3_AS_DIR = re.compile(r'/([^/]+\.model3\.json)/(.+)$')


class Handler(http.server.SimpleHTTPRequestHandler):
    """① pixi 把 model3 的完整 URL(含文件名)当资源 base 目录 -> rewrite 到真实资源;
       ② 对以 '/' 结尾/对应文件存在的请求退回 serve 该文件，避免尾斜杠 404."""

    def do_GET(self):
        p = self.path.split('?', 1)[0]
        # ① `.../<dir>/<name>.model3.json/<res>` -> `.../<dir>/<res>`
        mr = MODEL3_AS_DIR.search(p)
        if mr:
            rw = p[:mr.start()] + '/' + mr.group(2)
            if os.path.isfile(self.translate_path(rw)):
                self.path = rw
                super().do_GET()
                return
        # ② 带尾斜杠、去斜杠后是文件 -> serve 该文件
        if p.endswith('/'):
            fp = self.translate_path(p[:-1])
            if os.path.isfile(fp):
                self.path = p[:-1]
        super().do_GET()


httpd = http.server.ThreadingHTTPServer(('127.0.0.1', 8777), Handler)
httpd.serve_forever()
