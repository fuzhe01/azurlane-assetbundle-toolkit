"""修「SSE 里的错误被吞掉 → 假 422 上下文超限」这个根因（幂等，可 --revert）。

## 缺陷

中转层（以及任何 OpenAI 兼容网关）在上游限流/配额时，SSE 头已经发出去了，
状态码改不了，只能在流里喊错：

    data: {"choices":[],"error":{"message":"...限流中...","code":"QUOTA_EXCEEDED","status":502}}
    data: [DONE]

而 oai-compatible-copilot 扩展的三条 SSE 循环都只看 `choices[0]`：
  * openai/openaiApi.js        processDelta       —— `if (!choice) return false;`
  * openai/openaiApi.js        createMessage      —— `if (!choice) continue;`
  * openai/openaiResponsesApi.js processStreamingResponse —— 只看 `event.type`
于是错误帧被静默跳过、`[DONE]` 也不抛 ⇒ 零文本零工具调用 ⇒ Copilot agent host
把它判成「模型空响应」，再包装成
`422 ... returned an empty response ... exceeds the model's context window`。
**这句话是错的**：真因是上游限流，而且因为全程无异常，`executeWithRetry` 也没机会重试。

## 修法

在三条循环里加同一件事：解析出的帧带 `error` ⇒ 转成带 `[<status>]` 前缀的 Error 抛出。
`executeWithRetry` 认 `[429]/[502]/[503]/[504]` 这些状态码，于是会自动退避重试；
重试耗尽则把上游原文透给上层，用户看到的就是「限流中 + 解禁时间」而不是假的上下文超限。

**关键实现细节（踩过）**：抛错点位于 `JSON.parse` 的 try 内，而那个 catch 会把任何
异常都当作「SSE 解析失败」吞掉并只打日志。所以必须先打标记、在 catch 里原样重抛：

    let e; try { e = build(err) } catch {} if (e) throw e;   // 循环体末尾
    catch (err) { if (err && err.__isSseError) throw err; ... }  // 原 catch 首行

副作用：工具调用增量是缓冲到 `[DONE]` 才 flush 的，抛错会丢掉同批已到达的工具调用。
但该批次本身就是上游拒绝的回合（`choices` 为空），没有可执行内容，不受影响。

## 用法

    py -3 scripts/diag/patch_oaicopilot_sse_error.py --check
    py -3 scripts/diag/patch_oaicopilot_sse_error.py
    py -3 scripts/diag/patch_oaicopilot_sse_error.py --revert

改完必须让扩展重新加载：VS Code「开发人员: 重新加载窗口」。
扩展升级会覆盖补丁 —— 重新跑一次本脚本即可（幂等）。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

EXT_GLOB = "johnny-zhao.oai-compatible-copilot-*"
MARK = "// >>> oaicopilot sse error patch"

UTILS_ANCHOR = 'exports.executeWithRetry = executeWithRetry;'
UTILS_BLOCK = '''
/**
 * Turn an OpenAI-compatible SSE `error` frame into a real Error.
 *
 * Gateways that have already sent the SSE headers can no longer change the
 * status line, so a refusal arrives as `{"choices":[],"error":{...}}`. Without
 * this, the caller sees zero text and zero tool calls and reports an empty
 * response, which the host then mislabels as a context-window overflow.
 *
 * The status is rendered as `[502]` because that is exactly the shape
 * `executeWithRetry` matches on to decide whether to retry.
 */
function sseErrorFromFrame(frame) {
    if (!frame || typeof frame !== "object") {
        return null;
    }
    const raw = frame.error ?? (frame.type === "error" ? frame : null);
    if (!raw) {
        return null;
    }
    const body = typeof raw === "object" ? raw : { message: String(raw) };
    // A frame carrying `error` at all means the gateway is refusing the turn.
    // When it gives no numeric status (Responses-style `{type:"error",message}`),
    // fall back to 502 so the message stays informative and stays retryable.
    const declared = typeof body.status === "number" ? body.status
        : (typeof body.code === "number" ? body.code : 0);
    const status = declared > 0 ? declared : 502;
    const message = body.message ?? body.code ?? JSON.stringify(body);
    const code = typeof body.code === "string" ? ` ${body.code}` : "";
    return new Error(`Upstream refused the request: [${status}]${code} ${message}`);
}
exports.sseErrorFromFrame = sseErrorFromFrame;
'''

# 每个循环：(label, 用于定位的整行内容, 该行出现的第几次, 该循环 catch 首行)
# 为什么用「第几次出现」而不是上下文锚点：`openaiApi.js` 里两处循环都以同样的
# `try {` + `const parsed = JSON.parse(data);` 开头，上下文锚点并不唯一；
# 而 `const parsed = JSON.parse(data);` 这行本身在全文恰好只出现于这两处，
# 按出现序号定位最稳。delta 在前、create 在后（已用行号核对）。
# 抛错点必须落在 `if (!choice) continue;` 之前 —— 错误帧本来就没有 choices，
# 放在后面会先被 continue 跳过，等于没修。
PARSE_LINE = '                        const parsed = JSON.parse(data);'
TARGETS = {
    "delta": (
        PARSE_LINE, 1,
        '                    catch (e) {\n'
        '                        console.error("[OpenAI Provider] Failed to parse SSE chunk:", e, "data:", data);',
    ),
    "create": (
        PARSE_LINE, 2,
        '                    catch (e) {\n'
        '                        console.error("[OpenAI Provider] Failed to parse SSE chunk:", e, "data:", data);',
    ),
    "responses": (
        PARSE_LINE, 1,
        '                    catch (e) {\n'
        '                        console.error("[OpenAI-Responses Provider] Failed to parse SSE chunk:", e, "data:", data);',
    ),
}


def ext_root(ext_dir: Path | None) -> Path:
    root = ext_dir or (Path.home() / ".vscode" / "extensions")
    cands = [p for p in root.glob(EXT_GLOB) if (p / "out" / "utils.js").is_file()]
    if not cands:
        sys.exit(f"没找到 {EXT_GLOB}（目录 {root}）")

    def ver(p: Path) -> tuple:
        return tuple(int(x) for x in re.findall(r"\d+", p.name.split("copilot-", 1)[1]) or [0])

    return max(cands, key=ver)


def node_check(p: Path) -> str:
    node = shutil.which("node")
    if node:
        r = subprocess.run([node, "--check", str(p)], capture_output=True, text=True)
        return "ok" if r.returncode == 0 else f"FAILED: {r.stderr.strip()[:300]}"
    code = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Microsoft VS Code" / "Code.exe"
    if not code.is_file():
        return "skipped (node 与 Code.exe 都找不到；请人工确认语法)"
    env = dict(os.environ, ELECTRON_RUN_AS_NODE="1")
    r = subprocess.run([str(code), "--check", str(p)], capture_output=True, text=True, env=env)
    return "ok (via Code.exe)" if r.returncode == 0 else f"FAILED: {(r.stderr or '').strip()[:300]}"


def patch_utils(p: Path) -> str:
    src = p.read_text(encoding="utf-8")
    if "sseErrorFromFrame" in src:
        return "already patched"
    if src.count(UTILS_ANCHOR) != 1:
        sys.exit(f"utils.js 锚点出现 {src.count(UTILS_ANCHOR)} 次（应为 1）")
    p.with_suffix(".js.orig").exists() or shutil.copy2(p, p.with_suffix(".js.orig"))
    p.write_text(src.replace(UTILS_ANCHOR, UTILS_ANCHOR + "\n" + UTILS_BLOCK, 1), encoding="utf-8")
    return "patched"


def patch_loop(path: Path, entries: list[tuple[str, str, int, str]]) -> list[str]:
    """entries: (label, 定位整行, 该行第几次出现(1-based), catch 首行)。

    按行插入，**绝不替换半行** —— 早先按子串替换把行尾注释截断成了
    `} (stream_options.include_usage)`，语法检查照样绿、运行时必崩。
    """
    src = path.read_text(encoding="utf-8")
    if MARK in src:
        return [f"{path.name}: already patched"]
    backup = path.with_suffix(".js.orig")
    if not backup.exists():
        shutil.copy2(path, backup)
    notes = []
    lines = src.split("\n")
    # 自后向前插入，避免前面插入后行号漂移
    ordered = sorted(entries, key=lambda e: (e[1], e[2]), reverse=True)
    for label, needle, nth, catch_line in ordered:
        hits = [i for i, ln in enumerate(lines) if ln == needle]
        if len(hits) < nth:
            sys.exit(f"{path.name} 定位行 [{label}] 只出现 {len(hits)} 次，少于需要的第 {nth} 次")
        idx = hits[nth - 1]
        # 关键：同一个文件里两处循环的 catch 首行**完全相同**，不能按全文首匹配插入，
        # 否则两处补丁会插到同一个 catch 上（出现重复行，另一处漏打）。
        # 只在本次插入点之后找自己的那个 catch。（catch_line 是多行，取首行匹配）
        catch_first = catch_line.split("\n")[0]
        catch_idx = next((i for i in range(idx + 1, len(lines)) if lines[i] == catch_first), None)
        if catch_idx is None:
            sys.exit(f"{path.name} 在 [{label}] 插入点之后找不到 catch 首行")
        # catch { console.error(...);  <-- 插在 console.error 之后 } 之前
        insert_at = catch_idx + 2
        lines.insert(insert_at, "                        if (e && e.__isSseError) { throw e; }")
        lines[idx + 1:idx + 1] = [
            f"                        {MARK} ({label})",
            f"                        var __sseErr_{label} = (0, utils_1.sseErrorFromFrame)(parsed);",
            f"                        if (__sseErr_{label}) {{ __sseErr_{label}.__isSseError = true; throw __sseErr_{label}; }}",
        ]
        notes.append(f"{path.name}: {label} ok (line {idx + 1}, catch line {catch_idx + 1})")

    src = "\n".join(lines)
    path.write_text(src, encoding="utf-8")
    return notes


def revert(root: Path) -> list[str]:
    notes = []
    for rel in ("utils.js", "openai/openaiApi.js", "openai/openaiResponsesApi.js"):
        p = root / "out" / rel
        b = p.with_suffix(".js.orig")
        if b.exists():
            shutil.copy2(b, p)
            notes.append(f"{rel}: restored from .orig")
        else:
            notes.append(f"{rel}: 无 .orig，跳过")
    return notes


def report(root: Path) -> int:
    utils_p = root / "out" / "utils.js"
    api_p = root / "out" / "openai" / "openaiApi.js"
    resp_p = root / "out" / "openai" / "openaiResponsesApi.js"
    utils_ok = "sseErrorFromFrame" in utils_p.read_text(encoding="utf-8")
    api_src = api_p.read_text(encoding="utf-8")
    resp_src = resp_p.read_text(encoding="utf-8")
    api_ok = api_src.count(MARK) == 2
    resp_ok = resp_src.count(MARK) == 1
    # 每个补丁点有 2 处 __isSseError：打标记处 + catch 里重抛处
    throws_ok = (api_src.count("__isSseError") == 4 and resp_src.count("__isSseError") == 2)
    # 结构完整性：标记行必须独占一行，且不能有被截断的行尾残留
    structure_ok = all(
        not re.search(re.escape(MARK) + r".{0,80}\}\s*\(", p.read_text(encoding="utf-8"))
        for p in (api_p, resp_p)
    )
    print(f"扩展目录: {root}")
    print(f"  utils.sseErrorFromFrame : {utils_ok}")
    print(f"  openaiApi 补丁点        : {api_src.count(MARK)}/2  -> {api_ok}")
    print(f"  responsesApi 补丁点     : {resp_src.count(MARK)}/1  -> {resp_ok}")
    print(f"  重抛标记(__isSseError)  : {throws_ok}")
    print(f"  结构完整(无截断)        : {structure_ok}")
    for name, p in (("utils.js", utils_p), ("openaiApi.js", api_p), ("responsesApi.js", resp_p)):
        print(f"  node --check {name:<16}: {node_check(p)}")
    ok = utils_ok and api_ok and resp_ok and throws_ok and structure_ok
    print(f"\n[{'OK' if ok else 'FAIL'}] 三条 SSE 路径都会把流内错误转成真异常" if ok
          else "\n[FAIL] 补丁不完整")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="oai-compatible-copilot SSE 错误帧修复补丁")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--revert", action="store_true")
    ap.add_argument("--ext-dir", type=Path)
    a = ap.parse_args()
    root = ext_root(a.ext_dir)

    if a.check:
        return report(root)

    if a.revert:
        for n in revert(root):
            print(n)
        print("\n已还原；请重新加载窗口")
        return report(root)

    print(patch_utils(root / "out" / "utils.js"))

    def entries(*labels):
        return [(lb, TARGETS[lb][0], TARGETS[lb][1], TARGETS[lb][2]) for lb in labels]

    notes = []
    notes += patch_loop(root / "out" / "openai" / "openaiApi.js", entries("delta", "create"))
    notes += patch_loop(root / "out" / "openai" / "openaiResponsesApi.js", entries("responses"))
    for n in notes:
        print(n)
    print("\n⚠️ 需要让扩展重新加载才生效：VS Code「开发人员: 重新加载窗口」")
    return report(root)


if __name__ == "__main__":
    raise SystemExit(main())
