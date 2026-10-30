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
  py -3 scripts/diag/apply_oaicopilot_model_alias.py --alias A=B [--alias C=D]
  py -3 scripts/diag/apply_oaicopilot_model_alias.py --revert

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

PATCH_BLOCK = (
    f"            {MARK_BEGIN} (repo: scripts/diag/apply_oaicopilot_model_alias.py)\n"
    "            // Only the name sent upstream is replaced; the Copilot-side model id is\n"
    "            // untouched so per-model settings (baseUrl / apiMode / context) still apply.\n"
    '            const __aliasMap = config.get("oaicopilot.modelAliases", {}) || {};\n'
    "            const wireModelId = typeof __aliasMap[parsedModelId.baseId] === \"string\"\n"
    "                && __aliasMap[parsedModelId.baseId] !== \"\"\n"
    "                ? __aliasMap[parsedModelId.baseId]\n"
    "                : parsedModelId.baseId;\n"
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


def set_aliases(p: Path, aliases: dict[str, str]) -> str:
    text = read(p)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        sys.exit(f"settings.json 不是纯 JSON（{e}），请手工添加 {SETTINGS_KEY}")
    merged = dict(data.get(SETTINGS_KEY) or {})
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
    ok = patched and wire_ok and bool(aliases)
    print(f"\n[{'OK' if ok else 'FAIL'}] 补丁与别名都在位" if ok else "\n[FAIL] 补丁或别名缺失")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="oai-compatible-copilot 上游模型名别名补丁")
    ap.add_argument("--alias", action="append", default=[], metavar="A=B",
                    help="把上游模型名 A 换成 B（可重复）")
    ap.add_argument("--revert", action="store_true", help="撤销 provider.js 补丁")
    ap.add_argument("--check", action="store_true", help="只报告状态，不写盘")
    ap.add_argument("--ext-dir", type=Path, help="扩展根目录（默认 ~/.vscode/extensions）")
    a = ap.parse_args()

    provider = find_provider(a.ext_dir)
    sp = settings_path()

    if a.check:
        return report(provider, sp)

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

    print(patch_provider(provider))
    print(f"node --check   : {node_check(provider)}")
    if aliases:
        print(set_aliases(sp, aliases))
    print("\n⚠️ 需要让扩展重新加载才生效：VS Code「开发人员: 重新加载窗口」")
    return report(provider, sp)


if __name__ == "__main__":
    raise SystemExit(main())
