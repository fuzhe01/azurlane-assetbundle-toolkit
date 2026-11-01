---
name: llm-relay-channel-alias-triage
description: 通过「本地中转层 / OpenAI 兼容代理」调用 LLM 时的通道排障流程——当同一个会话反复报同一句上游错误（422 empty response / 502 QUOTA_EXCEEDED / 429），且「改模型」「打补丁」「换通道」看起来都不生效时使用。核心是三条判据：① 台账（限流记录）不可当判据，必须实测一发；② 流式限流常伪装成 **HTTP 200 + 空 choices + 流内 error + 0 字符正文**，只看状态行会得假绿灯；③ 模型名→通道的**别名/重定向链是单点**，给一个本来能用的名字加跳等于主动放弃它。含真实请求体重放探针、阴性对照、以及"改完别名必须交叉核对会话模型名是否都在表里"的收尾闸门。触发词：中转层、relay、gateway、oaicopilot、模型别名、modelAliases、别名链、重定向、502 QUOTA_EXCEEDED、422 empty response、exceeds the model's context window、改模型不生效、切不回去、限流解禁、state.json modelRateLimits、假绿灯、SSE 流内错误。
description_en: Triage pipeline for LLM relay/gateway channel failures — rate-limit records are not evidence, streaming quota errors masquerade as HTTP 200 with 0-char body, and model-alias redirect chains are single points of failure.
description_zh: 本地中转层/OpenAI 兼容代理的通道排障：台账不可当判据、流式限流伪装成 200+0 字符、别名链是单点，附真实请求体重放与阴性对照。
argument-hint: Give the repeated upstream error text, the relay base URL, the model id(s) in play, and the relay log path
argument-hint_en: Give the repeated upstream error text, relay base URL, model id(s), and the relay log path
user-invocable: true
version: 1.0.0
---

# 中转层通道与模型别名排障

## 何时使用

- 同一会话**反复**报同一句上游错误，重试若干次后失败（`Failed to get response from the AI model; retried N times`）。
- 报错文案可疑：「exceeds the model's context window」出现在**明显没超长**的对话上；或 `422 empty response`、`502 QUOTA_EXCEEDED`、`429`。
- **改模型无效**：UI 里换了模型，行为/报错一点没变；或「失败后连手动切模型都切不回去」。
- 已经加了「绕过限流」的重定向/别名/兜底，**修好过又复发**。

## 不适用

- 中转层本身没起来（连接被拒 / 端口不通）→ 先查服务进程与端口，不是本流程。
- 缺 API key / 账号未登录 → 先补齐凭据。
- 请求体格式非法（400 参数错误，且报文明确指向某字段）→ 直接改请求方。

## 第 0 步：先把「谁在真正处理请求」钉住

三件事必须同时确认，缺一个就会开始猜：

1. **中转层活着且端口对**：`netstat -ano | findstr :<port>` → 查 PID 属主进程名。
2. **密钥从哪读**：常见的 `~/.dsh/<gateway>/api-key` 之类文件；**别把它写进仓库**。
3. **日志在哪**：中转层自己的日志（而不是宿主/编辑器的日志）。
   例：`~/.copilot/oaicopilot/logs/oaicopilot-<date>.log`，
   里面有 `request.body`（可抽**真实请求体**）、`request.headers`、`openai.stream.error`、
   `request.error`（含 `messageCount`）。

> **报错文案永远不能当结论。** 同一条排查链上，`429 频率`、`配额耗尽`、`体积上限`、
> `通道切换` 四种完全不同的原因**都会表现成同一句**。必须落到日志里看**实际发出去的 model id 是谁**。

## 第 1 步：判「是不是加密/格式问题」之前先判「是不是这一发被拒」

用**最小请求**扫一遍候选模型，得到「哪些通道此刻活着」：

```bash
py -3 scripts/diag/probe_relay_models.py --model A --model B --model C
```

⚠️ **必须至少有一个预期失败的候选当阴性对照**。如果全部 200，这个探测**没有区分力**，
不能据此下任何结论。

## 第 2 步：用真实请求体重放（这一步才是判据）

最小请求过了不代表长会话能过——体积上限类通道就是典型的「小请求全 200，到 400 条消息瞬时 502」。

从日志里抽该会话**真实**的请求体存成文件，然后：

```bash
py -3 scripts/diag/probe_relay_models.py --body real_body.json --model A --model B
```

同一份体积、两个通道、一个 200 一个挂 ⇒ 体积不是原因，**通道才是**。这条对照是本流程的核心。

## 第 3 步：识破「假 422」——流式限流是 HTTP 200

上游限流时，中转层**不会**回 429/502 错误码。因为 SSE 响应头早已写出，
只能在流里塞一条 error，状态行仍恒为 **200**：

```
HTTP 200
data: {"choices":[], "error": {"code":"QUOTA_EXCEEDED", ...}}
data: [DONE]
→ 正文 0 字符
```

⇒ **流式探针必须解析流内 `error` 字段**。只看状态行 = 假绿灯（本流程最常见的翻车点）。
`scripts/diag/probe_relay_models.py` 已按此实现，并在「一个都没报错」时警告缺阴性对照。

**反过来也有用**：如果最终报错文案长得像上游原始错误（带 `[502] QUOTA_EXCEEDED` 这种方括号码），
那是「把流内错误转成真异常」的补丁**在起作用**的证据。没有这个补丁，
它会退化成宿主自己的那句假「exceeds the model's context window」。
→ **报错变具体了，是补丁生效，不是新故障。**

## 第 4 步：台账不可当判据 ⚠️

中转层/打包器的 state 文件里常有 `accounts[].modelRateLimits`（通常 unix-ms）。
**它只记录「上游曾经说过正在限流」，解禁后条目不会自动消失。**

实例：某账号的 `deepseek-v4.1-flash` 条目停在 `10-31 10:43`（已过期），条目却还在；
若照它判断，会得「这个通道还在限流」的错误结论，进而做出错误的重定向决策。

⇒ 判据只有一个：**现在实测一发**（第 1~2 步）。

## 第 5 步：别名/重定向链**是单点**（本流程最贵的一课）

### 机制

为了「让某个名字绕过限流」而给它加一跳：

```jsonc
"modelAliases": {
  "qoder/dfmodel": "A",   // 没有出口的名字 → 指向 A（合理）
  "A": "B"                // 为躲 A 的限流而加的一跳（危险）
}
```

于是 `qoder/dfmodel → A → B`。**A 自己再也不会被用到**，`B` 变成**全部请求的唯一致命点**。

### 反噬条件（真实事故）

```
t0：A 限流、B 健康   → 加 A→B，问题消失 ✅
t1：A 解禁、B 开始限流 → 链路反向把健康请求全送到唯一挂掉的 B ⇒ 复发
```

**一跳都不是「安全兜底」，它把「两个通道各自的可用性」降级成「单一通道的可用性」。**

### 三条纪律

1. **加别名前先实测终点**（`--probe`），不要按「名字看起来更稳」猜。
2. **只在「某模型名根本没有出口」时才留一跳**（如只有代号、没有真实模型的别名）。
   已经 200 的名字**不要**再套一层。
3. 必然要兜底时才用可传递链，且**每次改完都要复核：链终点没有被别的跳再重定向**。
   `--selftest` 会拿真实表逐条打印链路并判这一点（链终点 ∈ 表内 = FAIL）。

### 改别名的收尾闸门（漏了这个必然复发）

**不在别名表里的模型名 = 请求直接失败**，不是「回退到原名」。

上一轮只给 `qoder*` 两条加了别名，却漏掉一个会话直接写在 `-sg` 这个名字上，
于是它一直挂着。⇒ **改完别名必须交叉核对每个会话实际用的模型名**：

```bash
py -3 scripts/diag/sync_session_model.py --list   # 标 OK / NO-CUR / SPLIT
```

- `NO-CUR` **不算**分裂——只表示从没在 UI 里切过，恢复时回落 `copilot.model`。
- 「不一致」必须定义成「**两边都有值且不同**」，否则会误报一堆分裂。

### 改完必须重载

宿主（VS Code 等）把模型解析器加载在进程内存里，**配置文件改了不重载不生效**。
改完要「重新加载窗口」，并明确告知用户这一点——否则他会以为没修好。

## 验证链（三件齐做，缺一不可）

| # | 内容 | 判据 |
|---|---|---|
| ① | 计数 | 补丁写入点在源码里出现 N 次、旧写法归零（`--check`） |
| ② | 带阴性对照的语法检查 | 必须能跑出**失败**退出码（故意坏一个），否则「绿」没有意义 |
| ③ | **行为用例** | 从文件里**原样抽出**补丁代码跑多用例（`--selftest`），不是「看代码对不对」 |

③ 的做法：`const` 不外泄 ⇒ 包一层 `new Function` / IIFE 再取返回值；
用例至少覆盖 **命中 / 未命中 / 空表 / 空值 / 自环 / 成环 / 多跳（有界）**，
外加一次**拿真实配置跑单点自检**。三次假绿灯都是「只做了 ①②、跳过了 ③」造成的。

## 已排除的假设（写进文档，别再重跑）

排查这类问题时，以下假设必须**逐条带反证**排除，否则下个会话会原样重跑：

| 假设 | 反证方式 |
|---|---|
| 上下文超限 | 同一份真实长请求体在另一个通道 200 |
| 补丁失效/被覆盖 | 报错文案是补丁自己的格式；`--check` 全绿 |
| 工作树被回退导致脚本变旧 | `git status` + 与 `HEAD` 逐文件比对 |
| 某个替代模型可用 | 实测一发（常见 402 积分不足 / 502 egress 不服务） |
| 台账说还在限流 | 实测一发（条目解禁后不消失） |

## Pitfalls

- **只看 HTTP 状态行** ⇒ 限流伪装成 200，全部假绿灯。
- **没有阴性对照的探测** ⇒ 全 200 时无法区分「都健康」与「探针根本没生效」。
- **拿最小请求下结论** ⇒ 体积上限类通道骗过你。
- **给能用的名字加跳** ⇒ 把双通道可用性降级成单点。
- **改完别名不核对会话模型名** ⇒ 漏网会话一直挂着，看起来「修了没用」。
- **改完不重载宿主** ⇒ 配置正确但运行时仍旧。
- **Windows/PowerShell**：`py -3 -c "..."` 里带 `[`/换行会被 PowerShell 解析坏 ⇒ 用 here-string 或直接写脚本文件；
  here-string 里的 `{}` 与 emoji 会被损坏 ⇒ 用文件写入工具而非 here-string。
- 用 Electron 提供的 node 时（本机无独立 node）：`ELECTRON_RUN_AS_NODE=1` + `Code.exe --check`；
  `--check` **异步返回**，必须等退出码，否则拿到的是假「通过」。

## 涉及脚本（本仓库）

| 脚本 | 用途 |
|---|---|
| `scripts/diag/probe_relay_models.py` | 通道可用性实测；`--body` 真实请求体重放；解析流内 error |
| `scripts/diag/apply_oaicopilot_model_alias.py` | 别名重定向补丁；`--probe`（改前实测）/`--alias`/`--unalias`/`--selftest`（行为用例）/`--check`/`--revert` |
| `scripts/diag/sync_session_model.py` | 会话双模型字段诊断与对齐；`--list` 是「别名覆盖度」的交叉核对器 |
| `scripts/diag/patch_oaicopilot_sse_error.py` | SSE 流内错误转真异常（根治补丁） |

> ⚠️ 脚本默认指向本机某个具体扩展/中转层路径。换机器时按 `--help` 里的默认值调整，
> **不要**把 `api-key` 之类凭据写进仓库。
