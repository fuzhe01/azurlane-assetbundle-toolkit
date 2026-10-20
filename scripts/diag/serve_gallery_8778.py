# -*- coding: utf-8 -*-
r"""本项目画廊启动器：在 8778 端口服务本项目 Output/。

背景：8777 端口可能被另一份画廊占用（如旧机拷贝 `D:\Azur Lane Assets\Output`，
其 `_gallery_server.py` 同名同端口）——本项目画廊验证必须用独立端口，
探针用 `INTV_URL`/`POSE_URL` 指向 http://127.0.0.1:8778/gallery_v2/index.html。

用法（脱离宿主启动，见 WF-41）：
  powershell -Command 'Start-Process -WindowStyle Hidden -FilePath "py" -ArgumentList "-3","<本文件绝对路径>"'
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "Output", "gallery_v2"))
import _gallery_server as s

s.make_server(8778, os.path.join(ROOT, "Output")).serve_forever()