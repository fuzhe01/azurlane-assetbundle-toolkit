"""给 oai-compatible-copilot 扩展加「上游模型名别名」补丁（幂等，可 --revert）。

背景与判据见 docs/TROUBLESHOOTING.md §175：
VS Code 的 Copilot agent host 在 resume 会话时会从 SDK 自己的
`~/.copilot/session-state/<sid>/events.jsonl` 回放「当前模型」，因此
  * 改 UI 模型下拉框 —— 下一轮 resume 又被回放覆盖；
  * 改 `session.db` 的 `copilot.model` / `configValues…current` —— 界面会显示新模型，
    但实际派发仍用日志里那个。
都会表现为「改了不生效」。此时唯一能「在原会话里原地继续」的修法，是把那个
模型名在上游侧重定向到另一条可用通道（本机中转层没有别名机制，`configId` 也只做
同名区分、不改发往上游的名字，所以只能落在扩展里）。

补丁形态：`out/provider.js` 里 `parsedModelId` 是**全部请求的唯一收口**
（ollama / anthropic / responses / gemini / openai 五个分支都写
`model: parsedModelId.baseId`），故只改这一处即可全覆盖。
Copilot 侧的模型 id 不变 ⇒ `um`（按模型配的 baseUrl / apiMode / context_length）
仍取原模型的配置，只有发往上游的名字被替换。

用法:
  py -3 scripts/diag/apply_oaicopilot_model_alias.py --check
  py -3 scripts/diag/apply_oaicopilot_model_alias.py --probe A --probe B     # 先实测再改
  py -3 scripts/diag/apply_oaicopilot_model_alias.py --alias A=B [--alias C=D]
  py -3 scripts/diag/apply_oaicopilot_model_alias.py --unalias A             # 删掉拖后腿的一跳
  py -3 scripts/diag/apply_oaicopilot_model_alias.py --revert

⚠️ 别名链是**单点**：终点通道一旦也限流，整条链一起死。所以
  1. 改之前先用 `--probe` / 查 `~/.dsh/channel-pack/state.json` 确认终点真的能用；
  2. 只在**必要**时留一跳（把没有出口的模型名接出来），不要为了让某个名字"绕过限流"
     而给本来正常的模型再加一跳 —— 那一跳会成为新的单点。
  实测案例（2026-10-31）：`flash -> flash-sg` 这一跳本是为了避开 `flash` 的限流，
     而 `flash` 先解禁、`-sg` 还在限流，于是整条链被这一跳反向拖死。删掉即恢复。

注意：改完必须让扩展重新加载（VS Code「开发人员: 重新加载窗口」）才生效。
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
MARK_BEGIN = "// >>> oaicopilot model alias patch"
MARK_END = "// <<< oaicopilot model alias patch"
ANCHOR = "const parsedModelId = (0, utils_1.parseModelId)(model.id);"
WIRE_OLD = "model: parsedModelId.baseId,"
WIRE_NEW = "model: wireModelId,"
SETTINGS_KEY = "oaicopilot.modelAliases"


def selftest(provider: Path, sp: Path) -> int:
    """把文件里**原样抽出**的补丁代码跑行为用例（不是"看代码对不对"）。

    判据见 docs/TROUBLESHOOTING.md §175 验证链第 3 条。这条判据是被三次假绿灯逼出来的：
    `node --check` 通过 ≠ 逻辑对，`--check` 的计数也会骗人，所以必须真跑。
    """
    src = read(provider) if provider.exists() else ""
    m = re.search(re.escape(MARK_BEGIN) + r"[^\n]*\n(.*?)" + re.escape(MARK_END), src, re.S)
    if not m:
        print("[FAIL] provider.js 里没有别名补丁块，先跑一次补丁（不加 --check）")
        return 1
    block = m.group(1)
    print("--- 原样抽出的补丁代码 ---")
    print(block.rstrip())
    print("--------------------------\n")

    def resolve(alias_map: dict, model: str):
        js = (
            "function run(config, parsedModelId) {\n" + block + "\n  return wireModelId;\n}\n"
            "return run({ get: (k, d) => (k === 'oaicopilot.modelAliases' ? __MAP__ : d) },"
            " { baseId: __MODEL__ });"
        ).replace("__MAP__", json.dumps(alias_map)).replace("__MODEL__", json.dumps(model))
        node = shutil.which("node")
        if node:
            cmd, env = [node, "-e"], None
        else:
            code = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Microsoft VS Code" / "Code.exe"
            if not code.is_file():
                sys.exit("既没有 node 也找不到 Code.exe，无法执行行为用例")
            cmd, env = [str(code), "-e"], dict(os.environ, ELECTRON_RUN_AS_NODE="1")
        wrapper = "console.log(JSON.stringify((function(){" + js + "})()));"
        r = subprocess.run(cmd + [wrapper], capture_output=True, text=True, env=env)
        if r.returncode != 0:
            sys.exit(f"解析代码执行失败: {(r.stderr or '').strip()[:400]}")
        return json.loads(r.stdout.strip())

    try:
        live = (json.loads(read(sp)) if sp.exists() else {}).get(SETTINGS_KEY) or {}
    except json.JSONDecodeError:
        live = {}

    cases = [
        ("命中一跳", live, sorted(live)[0] if live else "x", live.get(sorted(live)[0] if live else "x")),
        ("未命中", live, "trae/deepseek-v4.1-flash", "trae/deepseek-v4.1-flash"),
        ("空表", {}, "qodercn/dfmodel", "qodercn/dfmodel"),
        ("空值（不该当别名）", {"a": ""}, "a", "a"),
        ("自环", {"a": "a"}, "a", "a"),
        ("环（必须停下）", {"a": "b", "b": "a"}, "a", None),
        ("多跳（有界 5 跳）", {"a": "b", "b": "c", "c": "d"}, "a", "d"),
    ]
    fail = 0
    for name, table, model, expected in cases:
        got = resolve(table, model)
        if expected is None:
            ok, shown = got in table.values(), f"<表内任一值，实际 {got}>"
        else:
            ok, shown = got == expected, expected
        print(f"[{'PASS' if ok else 'FAIL'}] {name:18s} {model} -> {got}  (期望 {shown})")
        fail += 0 if ok else 1

    if live:
        print("\n单点自检：拿真实的别名表，逐条确认链终点没被别的跳再重定向")
        for k in live:
            chain = resolve_chain(live, k)
            tail = chain[-1]
            if tail in live:
                print(f"[FAIL] {k} -> {' -> '.join(chain)}  终点 {tail} 自己还在表里，会继续被重定向")
                fail += 1
            else:
                print(f"[PASS] {k} -> {' -> '.join(chain)}")

    print(f"\n{'全部通过' if fail == 0 else f'{fail} 条失败'}")
    return 0 if fail == 0 else 1

PATCH_BLOCK = (
    f"            {MARK_BEGIN} (repo: scripts/diag/apply_oaicopilot_model_alias.py)\n"
    "            // Only the name sent upstream is replaced; the Copilot-side model id is\n"
    "            // untouched so per-model settings (baseUrl / apiMode / context) still apply.\n"
    "            // Resolution is transitive (bounded, cycle-safe) so a dead channel can be\n"
    "            // pointed at a fallback that is itself pointed at a healthier one.\n"
    '            const __aliasMap = config.get("oaicopilot.modelAliases", {}) || {};\n'
    "            let wireModelId = parsedModelId.baseId;\n"
    "            for (let __hop = 0; __hop < 5; __hop++) {\n"
    "                const __next = __aliasMap[wireModelId];\n"
    "                if (typeof __next !== \"string\" || __next === \"\" || __next === wireModelId) break;\n"
    "                wireModelId = __next;\n"
    "            }\n"
    f"            {MARK_END}\n"
)


def vscode_user_dir() -> Path:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        sys.exit("APPDATA 未设置，无法定位 VS Code 用户目录")
    return Path(appdata) / "Code" / "User"


def find_provider(ext_dir: Path | None) -> Path:
    root = ext_dir or (Path.home() / ".vscode" / "extensions")
    cands = [p for p in root.glob(EXT_GLOB) if (p / "out" / "provider.js").is_file()]
    if not cands:
        sys.exit(f"没找到 {EXT_GLOB}/out/provider.js（目录 {root}）")

    def ver(p: Path) -> tuple:
        return tuple(int(x) for x in re.findall(r"\d+", p.name.split("copilot-", 1)[1]) or [0])

    return max(cands, key=ver) / "out" / "provider.js"


def settings_path() -> Path:
    return vscode_user_dir() / "settings.json"


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def node_check(p: Path) -> str:
    """语法检查。本机通常没有 node，退化到 VS Code 自带的 Electron（node 模式）。

    注意：`Code.exe --check` 是异步跑起来的，直接取退出码不可信；Python 的
    subprocess 会正常等它结束，所以这里必须走 subprocess 而不是 shell 调用。
    """
    node = shutil.which("node")
    if node:
        r = subprocess.run([node, "--check", str(p)], capture_output=True, text=True)
        return "ok" if r.returncode == 0 else f"FAILED: {r.stderr.strip()[:300]}"

    code = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Microsoft VS Code" / "Code.exe"
    if not code.is_file():
        return "skipped (node 不在 PATH，且找不到 Code.exe；请人工确认语法)"
    env = dict(os.environ, ELECTRON_RUN_AS_NODE="1")
    r = subprocess.run([str(code), "--check", str(p)], capture_output=True, text=True, env=env)
    if r.returncode == 0:
        return "ok (via Code.exe ELECTRON_RUN_AS_NODE)"
    return f"FAILED: {(r.stderr or '').strip()[:300]}"


def patch_provider(p: Path) -> str:
    src = read(p)
    if MARK_BEGIN in src:
        return "already patched"
    if src.count(ANCHOR) != 1:
        sys.exit(f"锚点出现 {src.count(ANCHOR)} 次（应为 1），扩展版本可能已变，先人工确认")
    if src.count(WIRE_OLD) != 5:
        sys.exit(f"`{WIRE_OLD}` 出现 {src.count(WIRE_OLD)} 次（应为 5），扩展版本可能已变，先人工确认")
    backup = p.with_suffix(".js.orig")
    if not backup.exists():
        shutil.copy2(p, backup)
    out = src.replace(ANCHOR, ANCHOR + "\n" + PATCH_BLOCK, 1)
    out = out.replace(WIRE_OLD, WIRE_NEW)
    p.write_text(out, encoding="utf-8")
    return f"patched (backup {backup.name})"


def revert_provider(p: Path) -> str:
    src = read(p)
    if MARK_BEGIN not in src:
        return "not patched"
    out = re.sub(re.escape(MARK_BEGIN) + r".*?" + re.escape(MARK_END) + r"\n", "", src, flags=re.S)
    out = out.replace(WIRE_NEW, WIRE_OLD)
    p.write_text(out, encoding="utf-8")
    return "reverted"


def set_aliases(p: Path, aliases: dict[str, str], unaliases: list[str] | None = None) -> str:
    text = read(p)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        sys.exit(f"settings.json 不是纯 JSON（{e}），请手工添加 {SETTINGS_KEY}")
    merged = dict(data.get(SETTINGS_KEY) or {})
    for k in unaliases or []:
        merged.pop(k, None)
    merged.update(aliases)
    value = json.dumps(merged, ensure_ascii=False)
    line = f'"{SETTINGS_KEY}": {value},'
    if re.search(r'^\s*"' + re.escape(SETTINGS_KEY) + r'"\s*:', text, re.M):
        text = re.sub(r'^(\s*)"' + re.escape(SETTINGS_KEY) + r'"\s*:.*$', r"\1" + line, text,
                      count=1, flags=re.M)
    else:
        m = re.search(r'^(\s*)"oaicopilot\.baseUrl"\s*:.*$', text, re.M)
        if not m:
            sys.exit(f"settings.json 里找不到 oaicopilot.baseUrl，无法定位插入点，请手工加 {SETTINGS_KEY}")
        text = text[:m.end()] + "\n" + m.group(1) + line + text[m.end():]
    try:
        json.loads(text)
    except json.JSONDecodeError as e:
        sys.exit(f"插入后 settings.json 不再是合法 JSON（{e}），已放弃写入")
    p.write_text(text, encoding="utf-8")
    return f"aliases={json.dumps(merged, ensure_ascii=False)}"


def resolve_chain(aliases: dict[str, str], model: str) -> list[str]:
    """按补丁同款规则（有界 5 跳、防自环）展开别名链，用于打印最终落到谁。"""
    chain = [model]
    cur = model
    for _ in range(5):
        nxt = aliases.get(cur)
        if not isinstance(nxt, str) or nxt == "" or nxt == cur:
            break
        chain.append(nxt)
        cur = nxt
    return chain


def relay_probe(model: str, base_url: str, api_key: str, timeout: float = 120.0) -> tuple:
    """经中转层打一发最小请求，返回 (status, 摘要)。

    台账（state.json 的 modelRateLimits）只记「上游告诉过我们它在限流」，
    解禁后条目仍会留着，所以它**不能**当「能不能用」的判据 —— 实测才是。
    """
    import urllib.error
    import urllib.request

    body = {"model": model, "messages": [{"role": "user", "content": "回复两个字：可用"}],
            "stream": False, "max_tokens": 8}
    req = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + api_key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            j = json.loads(r.read().decode("utf-8", "replace"))
            c = ((j.get("choices") or [{}])[0].get("message") or {}).get("content")
            return r.status, f"content={c!r}"
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:200].replace("\n", " ")
    except Exception as e:  # 网络/超时一律当不可用，不要吞成「未知」
        return "ERR", repr(e)[:200]


def default_base_url() -> str:
    return "http://127.0.0.1:8326/v1"


def default_api_key() -> str | None:
    """中转层的 key 由 DSH 写在 ~/.dsh/openai-gateway/api-key。"""
    kp = Path.home() / ".dsh" / "openai-gateway" / "api-key"
    if kp.is_file():
        return kp.read_text(encoding="utf-8").strip()
    return None


def report(provider: Path, sp: Path) -> int:
    src = read(provider) if provider.exists() else ""
    patched = MARK_BEGIN in src and WIRE_NEW in src
    wire_ok = (src.count(WIRE_NEW) == 5) if patched else (src.count(WIRE_OLD) == 5)
    try:
        aliases = (json.loads(read(sp)) if sp.exists() else {}).get(SETTINGS_KEY) or {}
    except json.JSONDecodeError:
        aliases = {}
    print(f"provider.js      : {provider}")
    print(f"  patched        : {patched}")
    print(f"  wire sites ok  : {wire_ok}")
    print(f"  node --check   : {node_check(provider)}")
    print(f"settings.json    : {sp}")
    print(f"  {SETTINGS_KEY}: {json.dumps(aliases, ensure_ascii=False)}")
    for k in aliases:
        print(f"    {k}  ->  {' -> '.join(resolve_chain(aliases, k))}")
    ok = patched and wire_ok and bool(aliases)
    print(f"\n[{'OK' if ok else 'FAIL'}] 补丁与别名都在位" if ok else "\n[FAIL] 补丁或别名缺失")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="oai-compatible-copilot 上游模型名别名补丁")
    ap.add_argument("--alias", action="append", default=[], metavar="A=B",
                    help="把上游模型名 A 换成 B（可重复）")
    ap.add_argument("--unalias", action="append", default=[], metavar="A",
                    help="删除一条别名（可重复）")
    ap.add_argument("--probe", action="append", default=[], metavar="MODEL",
                    help="经本机中转层实测该模型是否可用（可重复；先探再改，别只信台账）")
    ap.add_argument("--revert", action="store_true", help="撤销 provider.js 补丁")
    ap.add_argument("--selftest", action="store_true",
                    help="把文件里原样抽出的补丁代码跑行为用例（判据见文档 §175 验证链第 3 条）")
    ap.add_argument("--check", action="store_true", help="只报告状态，不写盘")
    ap.add_argument("--ext-dir", type=Path, help="扩展根目录（默认 ~/.vscode/extensions）")
    a = ap.parse_args()

    provider = find_provider(a.ext_dir)
    sp = settings_path()

    if a.check:
        return report(provider, sp)

    if a.selftest:
        return selftest(provider, sp)

    if a.revert:
        print(revert_provider(provider))
        print(f"node --check   : {node_check(provider)}")
        print("提示：settings.json 里的别名条目保留无副作用，可自行删除")
        return 0

    aliases: dict[str, str] = {}
    for item in a.alias:
        if "=" not in item:
            sys.exit(f"--alias 需要 A=B 形式，收到 {item!r}")
        k, v = item.split("=", 1)
        aliases[k.strip()] = v.strip()

    if a.probe:
        base_url = os.environ.get("OAICOPILOT_BASE_URL") or default_base_url()
        api_key = default_api_key()
        if not api_key:
            sys.exit("找不到中转层 key（~/.dsh/openai-gateway/api-key），无法实测")
        print(f"实测（{base_url}）:")
        bad = []
        for m in a.probe:
            st, detail = relay_probe(m, base_url, api_key)
            mark = "OK  " if st == 200 else "FAIL"
            print(f"  [{mark}] {st}  {m}  {detail}")
            if st != 200:
                bad.append(m)
        print()

    print(patch_provider(provider))
    print(f"node --check   : {node_check(provider)}")
    if aliases or a.unalias:
        print(set_aliases(sp, aliases, a.unalias))
    print("\n⚠️ 需要让扩展重新加载才生效：VS Code「开发人员: 重新加载窗口」")
    return report(provider, sp)


if __name__ == "__main__":
    raise SystemExit(main())
