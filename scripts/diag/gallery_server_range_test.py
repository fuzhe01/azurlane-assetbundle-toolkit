# -*- coding: utf-8 -*-
"""`_gallery_server.py` 的 Range 支持与既有端点回归（原地起一份服务器，**不占 8777**）。

为什么要这个测试：2026-10-06 给 BGM 页补 Range 支持时，8777 上那台服务器
**可能正被另一个会话的探针用着**，不能为了验证去重启它 ⇒ 把服务器对象抽成
`make_server(port, root)`，测试自己挑一个空闲端口起一份，跑完 shutdown。
⚠️ 只测读路径。`POST /save_cg` 会往正式目录 `Output/CG_v2/` 落文件，
   那是别的会话会扫的生产区 ⇒ 本次改动没碰它的字节流逻辑（只把收尾换成 `_reply`），
   用 `/cg_exists` 的读分支做存在性回归即可，不在 CG_v2 里造临时文件。

用法: py -3 scripts/diag/gallery_server_range_test.py
退出码: 0 = 全过；1 = 有判据未过。
"""
import http.client
import os
import socket
import sys
import threading
import urllib.request

sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, 'gallery_src'))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import _gallery_server as GS   # noqa: E402

FAIL = []


def say(cond, msg):
    print(('  PASS  ' if cond else '  FAIL  ') + msg)
    if not cond:
        FAIL.append(msg)


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def req(port, path, headers=None, method='GET'):
    c = http.client.HTTPConnection('127.0.0.1', port, timeout=15)
    c.request(method, path, headers=headers or {})
    r = c.getresponse()
    body = r.read()
    hd = {k.lower(): v for k, v in r.getheaders()}
    c.close()
    return r.status, hd, body


def main():
    out = os.path.join(ROOT, 'Output')
    port = free_port()
    httpd = GS.make_server(port=port, root=out)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        rel = 'gallery_v2/bgm.html'
        fp = os.path.join(out, 'gallery_v2', 'bgm.html')
        size = os.path.getsize(fp)
        raw = open(fp, 'rb').read()

        st, hd, body = req(port, '/' + rel)
        say(st == 200 and len(body) == size, f'全量 GET：{st} / {len(body)} 字节（文件 {size}）')

        st, hd, body = req(port, '/' + rel, {'Range': 'bytes=0-99'})
        say(st == 206 and body == raw[:100] and hd.get('content-range') == f'bytes 0-99/{size}',
            f'首 100 字节：{st} / Content-Range={hd.get("content-range")} / 内容逐字节相同={body == raw[:100]}')

        st, hd, body = req(port, '/' + rel, {'Range': f'bytes={size // 2}-{size // 2 + 499}'})
        say(st == 206 and body == raw[size // 2:size // 2 + 500],
            f'中段 500 字节：{st} / 长度 {len(body)}')

        st, hd, body = req(port, '/' + rel, {'Range': 'bytes=-50'})
        say(st == 206 and body == raw[-50:], f'后缀区间 bytes=-50：{st} / 长度 {len(body)}（应为 50）')

        st, hd, body = req(port, '/' + rel, {'Range': f'bytes={size - 10}-'})
        say(st == 206 and body == raw[-10:], f'开区间到文件末：{st} / 长度 {len(body)}')

        st, hd, body = req(port, '/' + rel, {'Range': f'bytes={size + 100}-'})
        say(st == 416, f'越界区间应 416，实得 {st}')

        st, hd, body = req(port, '/' + rel, {'Range': 'bytes=abc-'})
        say(st == 200 and len(body) == size, f'畸形 Range ⇒ 回落全量 200（不是 500），实得 {st}')

        # 音频本体：Chrome 先要一个探测性的尾区间，再要中段
        ogg = None
        for f in sorted(os.listdir(os.path.join(out, 'Audio', 'BGM_ogg'))):
            ogg = f
            break
        apath = 'Audio/BGM_ogg/' + ogg
        afs = os.path.join(out, 'Audio', 'BGM_ogg', ogg)
        asz = os.path.getsize(afs)
        araw = open(afs, 'rb').read()
        st, hd, body = req(port, '/' + apath, {'Range': 'bytes=0-1'})
        say(st == 206 and body == araw[:2] and hd.get('content-type', '').startswith('audio'),
            f'音频前 2 字节（magic）：{st} / Content-Type={hd.get("content-type")} / '
            f'开头 {body[:2]!r} == OggS 头 {araw[:4] == b"OggS"}')
        st, hd, body = req(port, '/' + apath, {'Range': f'bytes={asz - 3}-'})
        say(st == 206 and body == araw[-3:], f'音频尾 3 字节：{st} / 长度 {len(body)}')

        st, hd, body = req(port, '/cg_exists?name=2b_2')
        say(st == 200 and body in (b'0', b'1'), f'既有端点 /cg_exists 仍工作：{st} / {body!r}')
        st, hd, body = req(port, '/cg_exists?name=../etc')
        say(st == 200 and body == b'0', f'非法名被 _NAME_RE 挡掉（不越界读盘）：{body!r}')

        st, hd, body = req(port, '/gallery_v2/index.json')
        say(st == 200 and len(body) > 20000, f'大文件全量读仍正常：{st} / {len(body):,} 字节')
        print()
        if FAIL:
            print(f'[FAIL] {len(FAIL)} 条未过')
            return 1
        print('[PASS] Range 支持与既有端点全部判据通过')
        return 0
    finally:
        httpd.shutdown()
        httpd.server_close()


if __name__ == '__main__':
    sys.exit(main())
