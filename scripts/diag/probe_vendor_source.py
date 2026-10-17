# -*- coding: utf-8 -*-
"""探测候选下载源：逐个抓取并计算 sha256/bytes，可与期望哈希/字节比对。

用途：给 gallery_src/vendor/MANIFEST.json 补 verified 源之前，先确认某个 URL 真的能下、
且内容是否为期望的那份（by sha256/bytes）。不写盘到运行目录，临时数据仅内存。

用法：
  py -3 scripts/diag/probe_vendor_source.py <url>...
  py -3 scripts/diag/probe_vendor_source.py --expect-hash <sha> --expect-bytes <n> <url>...
返回 0 = 至少一个 URL 命中期望（或未提供期望时全部可下）；1 = 无命中/全失败。
"""
import hashlib
import sys
import urllib.request


def main():
    argv = sys.argv[1:]
    want_hash = None
    want_bytes = None
    urls = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--expect-hash":
            want_hash = argv[i + 1].lower()
            i += 2
        elif a == "--expect-bytes":
            want_bytes = int(argv[i + 1])
            i += 2
        else:
            urls.append(a)
            i += 1

    hit = 0
    for u in urls:
        try:
            req = urllib.request.Request(u, headers={"User-Agent": "vendor-probe"})
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read()
        except Exception as e:
            print(f"× {u}\n   下载失败 {type(e).__name__}: {e}")
            continue
        h = hashlib.sha256(data).hexdigest()
        b = len(data)
        cond = []
        mark = ""
        if want_hash:
            chk = "匹配" if h == want_hash else "不符"
            cond.append(f"hash={chk}({h[:12]}…)")
            if h == want_hash:
                hit += 1
                mark = " ★命中"
        if want_bytes:
            cb = "匹配" if b == want_bytes else "≠"
            cond.append(f"bytes={cb}({b})")
            if want_hash is None and b == want_bytes:
                hit += 1
                mark = " ★命中"
        print(f"▲ {u}\n   {b}B  sha256={h}\n   {'；'.join(cond)}{mark}")
    print("--- 命中 %d/%d ---" % (hit, len(urls)))
    return 0 if hit else 1


if __name__ == "__main__":
    sys.exit(main())
