"""扫一遍本机中转层上各模型「现在到底能不能用」，并可选地用真实长请求体复核。

为什么需要它：`~/.dsh/channel-pack/state.json` 的 `accounts[].modelRateLimits` 只记录
「上游曾经告诉过我们它在限流」，**解禁之后条目仍然留着**。所以它只能当"排查线索"，
不能当"能不能用"的判据 —— 判据必须是实测一发。

用法:
  # 最小请求扫全部已配置模型（快，但小请求通道上的体积上限查不出来）
  py -3 scripts/diag/probe_relay_models.py

  # 只探指定的几个
  py -3 scripts/diag/probe_relay_models.py --model qodercn/dfmodel --model workbuddy/deepseek-v4.1-flash

  # 用真实长请求体复核（能从扩展日志里抽出失败那次完整 request.body）
  py -3 scripts/diag/probe_relay_models.py --body %TEMP%\\azur_replay_body.json \\
      --model workbuddy/deepseek-v4.1-flash --model workbuddy/deepseek-v4.1-flash-sg

判据纪律：
  * **别只看小请求的结果**。小请求 200 + 长请求 502 = 「小请求通道」，长会话照样挂
    （`qodercn/dfmodel` 就是这样：5/20/50/100/200 条全 200，400/533 条立刻 502）。
  * **阴性对照必须有**：一次扫里至少要有一个已知不可用的模型报错，
    否则"全 200"可能只是探针根本没打对地方。
  * 限流时中转层会回 `HTTP 200` + `choices:[]` + 流内 `error`（见 §175 的「假 422」机制），
    所以流式路径必须解析流内 error，不能只看状态行。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE_URL = os.environ.get("OAICOPILOT_BASE_URL", "http://127.0.0.1:8326/v1")
MIN_BODY = {"messages": [{"role": "user", "content": "回复两个字：可用"}],
            "stream": False, "max_tokens": 8}


def api_key() -> str:
    p = Path.home() / ".dsh" / "openai-gateway" / "api-key"
    if not p.is_file():
        sys.exit(f"找不到中转层 key（{p}）")
    return p.read_text(encoding="utf-8").strip()


def configured_models() -> list[str]:
    sp = Path(os.environ.get("APPDATA", "")) / "Code" / "User" / "settings.json"
    try:
        data = json.loads(sp.read_text(encoding="utf-8"))
    except Exception:
        return []
    return [m["id"] for m in (data.get("oaicopilot.models") or []) if m.get("id")]


def post_stream(key: str, payload: dict, timeout: float) -> tuple:
    """流式路径：状态行恒为 200，真结果藏在流内的 error 帧里。"""
    req = urllib.request.Request(
        BASE_URL.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + key,
                 "Accept": "text/event-stream"},
        method="POST",
    )
    chars = 0
    err = None
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            buf = b""
            for raw in r:
                buf += raw
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    line = line.strip()
                    if not line.startswith(b"data:"):
                        continue
                    data = line[5:].strip()
                    if data == b"[DONE]":
                        continue
                    try:
                        frame = json.loads(data)
                    except Exception:
                        continue
                    if frame.get("error"):
                        err = frame["error"]
                        continue
                    for ch in frame.get("choices") or []:
                        chars += len((ch.get("delta") or {}).get("content") or "")
        return (r.status if not err else 502), round(time.time() - t0, 1), chars, err
    except urllib.error.HTTPError as e:
        return e.code, round(time.time() - t0, 1), 0, e.read().decode("utf-8", "replace")[:200]
    except Exception as e:
        return "ERR", round(time.time() - t0, 1), 0, repr(e)[:160]


def post_plain(key: str, payload: dict, timeout: float) -> tuple:
    req = urllib.request.Request(
        BASE_URL.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + key},
        method="POST",
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode("utf-8", "replace")
            try:
                j = json.loads(body)
            except Exception:
                return r.status, round(time.time() - t0, 1), None
            err = j.get("error")
            if err:
                return 502, round(time.time() - t0, 1), err
            c = ((j.get("choices") or [{}])[0].get("message") or {}).get("content")
            return r.status, round(time.time() - t0, 1), f"content={c!r}"
    except urllib.error.HTTPError as e:
        return e.code, round(time.time() - t0, 1), e.read().decode("utf-8", "replace")[:200]
    except Exception as e:
        return "ERR", round(time.time() - t0, 1), repr(e)[:160]


def main() -> int:
    ap = argparse.ArgumentParser(description="扫中转层各模型当前可用性（实测，不查台账）")
    ap.add_argument("--model", action="append", default=[], help="只探这些模型（默认扫 settings.json 全部）")
    ap.add_argument("--body", type=Path, help="用这份真实请求体替换最小请求（模型字段会被逐条替换）")
    ap.add_argument("--timeout", type=float, default=300.0)
    a = ap.parse_args()

    key = api_key()
    models = a.model or configured_models()
    if not models:
        sys.exit("没有可探的模型（settings.json 里没读到 oaicopilot.models，也没给 --model）")

    base = json.loads(a.body.read_text(encoding="utf-8")) if a.body else dict(MIN_BODY)
    if a.body:
        base.setdefault("stream", True)
        base.setdefault("stream_options", {"include_usage": True})
        print(f"请求体: {a.body}  messages={len(base.get('messages') or [])}")
    print(f"中转层: {BASE_URL}  模型数={len(models)}\n")

    rows = []
    for m in models:
        payload = dict(base, model=m)
        fn = post_stream if payload.get("stream") else post_plain
        st, sec, extra, *rest = fn(key, payload, a.timeout)
        detail = rest[0] if rest else extra
        ok = st == 200
        msg = f"[{'OK  ' if ok else 'FAIL'}] {st}  {sec}s  {m}"
        if isinstance(detail, dict):
            msg += f"  {detail.get('code')} {str(detail.get('message'))[:110]}"
        elif isinstance(detail, str):
            msg += f"  {detail[:110]}"
        if payload.get("stream") and ok and not extra:
            msg += "  (0 字符正文)"
        print(msg)
        rows.append((m, st, ok))

    ok_n, bad_n = sum(1 for _, _, ok in rows if ok), sum(1 for _, _, ok in rows if not ok)
    print(f"\n可用 {ok_n} / 不可用 {bad_n}")
    if bad_n == 0 and len(rows) > 1:
        print("⚠️ 一个都没报错，请确认探针真的打到地方了（建议至少留一个已知不可用的模型做阴性对照）")
    return 0 if bad_n == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
