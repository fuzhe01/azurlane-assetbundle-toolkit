# -*- coding: utf-8 -*-
"""hand_diag_sink.py — 接收画廊页面回传的诊断 JSON（手掌消失排查取证端）。

为什么需要它：手掌消失只在用户真实浏览器复现，而 CDP 探针跑的是独立 profile/进程，
拿不到「默认 profile + 真实扩展 + 真实 GPU 合成」那一层。让页面自己把
「全部 drawable 的 opacity/visible/renderOrder/bbox」POST 回来，就能在用户环境原样取数。

用法:
  py -3.14 scripts/diag/hand_diag_sink.py            # 监听 8780，写 .diag/hand_diag/
  页面侧: index.html?ship=ougen_8&motion=mail&diagpost=http://127.0.0.1:8780/diag
"""
import sys, os, json, time, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, ".diag", "hand_diag")
PORT = int(os.environ.get("HAND_SINK_PORT", "8780"))


class H(BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        os.makedirs(OUT, exist_ok=True)
        path = os.path.join(OUT, f"diag_{ts}.json")
        try:
            data = json.loads(body.decode("utf-8"))
            open(path, "w", encoding="utf-8").write(json.dumps(data, ensure_ascii=False, indent=1))
            n_d = len(data.get("drawables") or [])
            print(f"[sink] {ts} <- {n_d} drawables, {len(body)}B -> {path}", flush=True)
        except Exception as e:
            path = os.path.join(OUT, f"diag_{ts}_raw.txt")
            open(path, "wb").write(body)
            print(f"[sink] {ts} 非 JSON（{e}）-> {path}", flush=True)
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"ok")

    def do_GET(self):
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"hand_diag_sink alive\n")

    def log_message(self, *a):
        pass


def main():
    os.makedirs(OUT, exist_ok=True)
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
    print(f"[sink] listening http://127.0.0.1:{PORT}/diag -> {OUT}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
