"""检查/修复 VS Code 会话「模型切换不生效」——两个模型字段分裂的问题。

## 症状

在 UI 里把模型换成好的，发送时仍然走坏的那个；报错文案里的模型名没变。
`configValues…current` 一直是旧值，而 `copilot.model` 已经是新值。

## 为什么会有两个字段

同一个会话的模型被持久化在 `%APPDATA%\\Code\\agentSessionData\\<sid>\\session.db`
的 `session_metadata` 里两处：

| 键 | 谁写 | 谁读 |
|---|---|---|
| `copilot.model` | 宿主在 `setModel()` RPC **成功之后**才更新 | 恢复会话时作为 fallback |
| `configValues` → `vscode.modelConfiguration.<chatUri>.current.id` | 同一路径的另一次写 | **实际派发用** |

而 `setModel()` 的顺序是「先打日志 → 再 `await session.setModel(...)` → finally 刷新配置」。
会话一旦处于 error / 正在重建（日志里的 `Session configuration changed, refreshing session`
→ disconnect → resume），那次 RPC 会落在正在销毁的实例上并报
`Session not found for sessionId`，于是 `configValues` 那半没写进去，
`copilot.model` 那半写了 —— **两个字段分裂**。

更要命的是恢复会话时模型来自 SDK 自己的事件日志
（`~/.copilot/session-state/<sdk-sid>/events.jsonl` 的最后一条 `session.model_change`），
所以即使 UI 记住了新选择，resume 仍会回放到旧模型。

## 本脚本做什么

不碰 VS Code 内部，只做一件它能接受的事：**把两个字段写成同一个值**，
让「恢复会话」与「实际派发」重新对齐。

    py -3 scripts/diag/sync_session_model.py --list
    py -3 scripts/diag/sync_session_model.py --check b05ca5fd
    py -3 scripts/diag/sync_session_model.py --set b05ca5fd --model oaicopilot/workbuddy/deepseek-v4.1-flash
    py -3 scripts/diag/sync_session_model.py --sync-from-copilot-model b05ca5fd   # 以 copilot.model 为准

`sid` 可以只给前 8 位。写盘前自动备份到 `%TEMP%`，写完做 `integrity_check` 与行数核对。

⚠️ 必须**先关闭该会话**（关掉那个聊天标签页）再跑，否则宿主内存里的旧值会把文件覆盖回去。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

META_MODEL = "copilot.model"
META_CONFIG = "configValues"


def session_root() -> Path:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        sys.exit("APPDATA 未设置")
    return Path(appdata) / "Code" / "agentSessionData"


def all_sessions(root: Path) -> list[Path]:
    return sorted(p for p in root.glob("*/session.db") if p.is_file())


def resolve(root: Path, sid: str) -> Path:
    cands = [p for p in all_sessions(root) if p.parent.name.lower().startswith(sid.lower())]
    if not cands:
        sys.exit(f"找不到 sid 以 {sid!r} 开头的会话（目录 {root}）")
    if len(cands) > 1:
        sys.exit(f"{sid!r} 匹配到多个会话：" + ", ".join(p.parent.name for p in cands))
    return cands[0]


def read_state(db: Path) -> dict:
    c = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    try:
        rows = dict(c.execute("select key,value from session_metadata").fetchall())
    finally:
        c.close()
    model = None
    if rows.get(META_MODEL):
        try:
            model = json.loads(rows[META_MODEL]).get("id")
        except json.JSONDecodeError:
            model = rows[META_MODEL]
    current = None
    chat = None
    if rows.get(META_CONFIG):
        try:
            cfg = json.loads(rows[META_CONFIG]).get("vscode.modelConfiguration") or {}
            for uri, entry in cfg.items():
                cur = (entry or {}).get("current") or {}
                if cur.get("id"):
                    chat, current = uri, cur["id"]
        except json.JSONDecodeError:
            pass
    return {
        "db": db,
        "sid": db.parent.name,
        "title": rows.get("customTitle"),
        "copilot.model": model,
        "configValues.current": current,
        "chat": chat,
        # 只有「两边都有值但不同」才算分裂。current 为 None 表示这个会话从未
        # 在 UI 里切过模型（configValues 里没有 current 条目），恢复时会回落到
        # copilot.model，不存在两个值打架的问题 —— 早期版本把它也算成 SPLIT，
        # 是判据缺陷（会凭空报出 5 个假阳性）。
        "split": bool(model) and bool(current) and model != current,
        "agree": (not current) or (model == current),
    }


def report(st: dict) -> str:
    if st["split"]:
        flag = "SPLIT"
    elif st["configValues.current"] is None:
        flag = "NO-CUR"
    else:
        flag = "OK   "
    return (f"[{flag}] {st['sid'][:8]}  copilot.model={st['copilot.model']}  "
            f"current={st['configValues.current']}  | {st['title'] or ''}")


def write_model(db: Path, model: str, chat_uri: str | None) -> dict:
    backup = Path(tempfile.gettempdir()) / f"{db.parent.name[:8]}_session.db.bak"
    shutil.copy2(db, backup)

    c = sqlite3.connect(str(db), timeout=10)
    c.isolation_level = None
    try:
        rows = dict(c.execute("select key,value from session_metadata").fetchall())
        old_model = json.loads(rows[META_MODEL]) if rows.get(META_MODEL) else {}
        cfg = json.loads(rows[META_CONFIG]) if rows.get(META_CONFIG) else {}
        per_chat = cfg.get("vscode.modelConfiguration") or {}
        if not per_chat:
            sys.exit("该会话没有 vscode.modelConfiguration，无法定位 chat 条目")
        if chat_uri is None:
            chat_uri = next(iter(per_chat))
        if chat_uri not in per_chat:
            sys.exit(f"configValues 里没有 chat {chat_uri!r}")

        cur = per_chat[chat_uri].get("current") or {}
        before = {"copilot.model": old_model.get("id"), "current": cur.get("id")}

        c.execute("BEGIN IMMEDIATE")
        c.execute(
            f"update session_metadata set value=? where key='{META_MODEL}'",
            (json.dumps({"id": model, "config": old_model.get("config") or {}},
                        separators=(",", ":")),),
        )
        per_chat[chat_uri]["current"] = {"id": model, "config": cur.get("config") or {}}
        c.execute(
            f"update session_metadata set value=? where key='{META_CONFIG}'",
            (json.dumps(cfg, separators=(",", ":"), ensure_ascii=False),),
        )
        c.execute("COMMIT")
    finally:
        c.close()

    chk = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    try:
        integrity = chk.execute("pragma integrity_check").fetchone()[0]
        meta_rows = chk.execute("select count(*) from session_metadata").fetchone()[0]
        turns = chk.execute("select count(*) from turns").fetchone()[0]
    finally:
        chk.close()

    after = read_state(db)
    return {
        "before": before,
        "after": {"copilot.model": after["copilot.model"],
                  "current": after["configValues.current"]},
        "agree": after["agree"],
        "integrity": integrity,
        "meta_rows": meta_rows,
        "turns": turns,
        "backup": backup,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="检查/修复会话模型两个字段分裂")
    ap.add_argument("--list", action="store_true", help="列出所有会话的模型状态（含分裂标记）")
    ap.add_argument("--check", metavar="SID", help="只看某一个会话")
    ap.add_argument("--set", metavar="SID", help="把两个字段都写成 --model")
    ap.add_argument("--sync-from-copilot-model", metavar="SID",
                    help="以 copilot.model 为准，把它同步进 configValues.current")
    ap.add_argument("--model", help="--set 时要写入的模型 id")
    ap.add_argument("--dir", type=Path, help="会话根目录（默认 %%APPDATA%%\\Code\\agentSessionData）")
    a = ap.parse_args()

    root = a.dir or session_root()
    if a.list:
        split = 0
        nocur = 0
        for db in all_sessions(root):
            try:
                st = read_state(db)
            except Exception as e:  # noqa: BLE001 - 单库读失败不该中断整个列表
                print(f"[ERR  ] {db.parent.name[:8]}  {type(e).__name__}: {e}")
                continue
            if st["copilot.model"] is None and st["configValues.current"] is None:
                continue
            print(report(st))
            if st["split"]:
                split += 1
            elif st["configValues.current"] is None:
                nocur += 1
        print(f"\n分裂（两边都有值但不同）: {split}")
        print(f"未切过模型（无 current，恢复时用 copilot.model，不算问题）: {nocur}")
        return 0 if split == 0 else 1

    if a.check:
        print(report(read_state(resolve(root, a.check))))
        return 0

    if a.sync_from_copilot_model:
        db = resolve(root, a.sync_from_copilot_model)
        st = read_state(db)
        if not st["copilot.model"]:
            sys.exit("copilot.model 为空，无法以其为准")
        model, chat = st["copilot.model"], st["chat"]
    elif a.set:
        db = resolve(root, a.set)
        if not a.model:
            sys.exit("--set 需要同时给 --model")
        st = read_state(db)
        model, chat = a.model, st["chat"]
    else:
        ap.print_help()
        return 2

    r = write_model(db, model, chat)
    print(f"会话      : {db.parent.name}")
    print(f"备份      : {r['backup']}")
    print(f"before    : {r['before']}")
    print(f"after     : {r['after']}")
    print(f"一致      : {r['agree']}")
    print(f"integrity : {r['integrity']}   metadata={r['meta_rows']} 行  turns={r['turns']} 行")
    if not r["agree"] or r["integrity"] != "ok":
        print("\n[FAIL] 写入后仍不一致或完整性异常")
        return 1
    print("\n[OK] 两个字段已对齐。请重新打开该会话（并确认 VS Code 已重新加载扩展）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
