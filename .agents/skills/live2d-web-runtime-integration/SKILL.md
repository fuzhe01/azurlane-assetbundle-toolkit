---
name: live2d-web-runtime-integration
description: 在网页里集成 Live2D Cubism Web 运行时做模型渲染与动作播放（pixi 6.5.2 + live2dcubismcore 5.1.0 + pixi-live2d-display 0.4.0 组合），覆盖 model3.json 加载、动作触发（startMotion 传参陷阱）、按部位点击触发（HitAreas 命中判定）、模型尺寸与 fit 基准、交互层反模式、内存销毁与无头 CDP 验证判据，**以及"点模型说话 + 台词字幕"层（§9：语音被下一条动作 dispose、首播竞态、按皮肤序号取词、正文与音频同源、字幕要在全屏目标内、开关验收要反向证据、"这一格没声"要先分清是没接上还是上游没下发）**。当需要让 .moc3/.model3 模型在浏览器里"真的动起来"、或反馈"模型不动/乱抖/点不出动作/显示不全"、或要在国内网络下载 Live2D 运行时库时使用。触发词：Live2D 网页播放、Cubism 运行时、pixi-live2d-display、Live2DModel 动作、模型点不动、idle 不播、HitAreas 点击、播完动作就卡死、判定区全丢、参数残留复位、模型画面是碎片堆、部件乱叠在一起、贴图错绑、Textures 顺序、加载成功但画面错乱、话没说完就被掐、一点声音都没有、台词字幕、点立绘出声、全屏没字幕、有声没字幕、audio 播放器看不见。不适用于 Live2D 模型文件的 AssetBundle 逆向还原（那是 unity-assetbundle-painting-restore）与纯截图导出（headless-chrome-cdp-batch-export）。
version: 1.10.19
---

# Live2D 网页运行时集成

## Overview

把 Cubism 4 的 `.model3.json` 模型在浏览器里渲染成可交互、会播动作的 Live2D。核心难点不在"加载出来"，而在**动作真的在播**、**点击部位触发对应反应**、**构图不越界**——这三处各有一个会静默失败的陷阱。

## 适用判断

- 页面里已有/可放 `live2dcubismcore.min.js` 等运行时，要让模型动起来 → 用本流程
- 只是把模型贴图当静态图展示 → 不需要运行时，直接 `<img src="texture_00.png">`
- 要产出的不是"网页里的模型"而是从游戏包还原模型文件本身 → 先走 `unity-assetbundle-painting-restore`

## 1. 运行时三件套与版本组合

必须**按序**加载，且版本要成对（新 pixi 会破坏 display 适配层）：

1. `live2dcubismcore.min.js`（Cubism Core，实测 5.1.0）
2. `pixi.min.js`（实测 **6.5.2**）
3. `pixi-live2d-display-cubism4.min.js`（实测 **0.4.0**）

- **别用 pixi 7 / display 0.5**：本项目实测 pixi 6.5.2 + display 0.4.0 是可用组合。
- 国内网络：`live2dcubismcore.min.js` 可从 l2d 系站点直链取；pixi 与 display 走 npmmirror 的 **tgz 下载后解包取 `dist/`**（registry 元数据接口可能被拦）。下载细节见 `cn-blocked-resource-mirror-fetch`。
- 全部放本地 `vendor/live2d/`，**别用 `P`（资源相对路径前缀）拼 vendor**：若 vendor 与页面同目录，用 `./vendor/live2d/…`。判定办法是在页面里 `fetch('../vendor/…')` 与 `fetch('/<页面目录>/vendor/…')` 对比状态码，**别信 curl 的绝对路径**（curl 的 200 会掩盖相对路径错误）。
- 懒加载（点标签才加载）比顶部 `<script>` 好：用 `loadScriptOnce(src)`（按 `script[data-x]` 去重并缓存 Promise），避免首屏拖慢与重复注入。

## 2. 加载模型

```js
const mdl = await PIXI.live2d.Live2DModel.from('<dir>/<name>.model3.json', { autoInteract: false });
app.stage.addChild(mdl);
```

- `autoInteract: false` 时库自带的 hit test/视线跟随都关掉，交互自己实现（见 §4）。
- 需要 `FileReferences.Motions` 的组名列表：`mdl.internalModel.motionManager.definitions`（键即组名）。

## 3. 动作播放：八个必踩陷阱（3.1–3.8）

### 3.1 `startMotion` 的 index 不能传 `null`

```js
mm.startMotion(group, null, false)   // ✗ 静默失败，什么都不播
mm.startMotion(group, 0, MP.FORCE)   // ✓
```

库内部会取 `motion[group][index]`；传 `null` 得到 `undefined` 后**直接 return false，不报错**。`priority` 也不能传 `false`——会被当成 0，低于当前优先级同样被拒。用 `PIXI.live2d.MotionPriority.FORCE`（枚举 NONE/IDLE/NORMAL/FORCE = 0/1/2/3）。

### 3.2 判"有没有在播"要读运行时状态，且要等一拍

`startMotion` 内部要 `fetch` 动作 JSON，调用后立刻读会拿到空值：

```js
mm.startMotion(g, 0, MP.FORCE);
await new Promise(r => setTimeout(r, 1500));
const playing = mm.state.currentGroup === g;   // 唯一可靠判据
```

**帧哈希/drawImage 比对不能当判据**：无头环境 rAF 被节流会**假阴性**；而 physics 与眨眼会让画面逐帧变化，造成"动作在播"的**假阳性**。另外注意：idle 播完后 `state.currentGroup` 会**自动归 null**，所以"值变了"才说明有东西被触发。

### 3.3 `Meta.Loop` 被忽略 → 但**不要**用前端定时器假装循环

vendored 0.4.0 的 cubism4 模块里 `setIsLoop()` **有定义、全 bundle 无调用点**，`Meta.Loop:true` 被无视，
动作播完即停。用定时器"到点重开"是**陷阱**：`startMotion` 是 async（返回 Promise），
`mm.startMotion(...) !== false` **恒成立**，于是被 `state.reserve()` 以
`"Motion is already playing"` 拒绝时前端完全无感，而重开定时器又照原周期重新武装 →
实测 idle 播 9.1s 后**冻结 9.2s**（`currentGroup=null`、队列 0 条、参数纹丝不动），50% 占空比。

正确修法（三行，交回运行时）：
```js
// ① 把 Meta.Loop 灌进 CubismMotion 本体（核心会自己做时间回绕：f>duration 就减 duration）
const orig = mm.createMotion.bind(mm);
mm.createMotion = (json, group, def) => { const m = orig(json, group, def);
  if (group === idleGroup && json?.Meta?.Loop && m.setIsLoop) {
    m.setIsLoop(true); m.setIsLoopFadeIn?.(false); }   // ← 后者必须设！
  return m; };
// ② 对齐库自带的"播完自动回 idle"：默认值是 'Idle'，与我们的 'idle' 不匹配 → 一直静默失效
mm.groups.idle = idleGroup;
```
⚠️ **`setIsLoopFadeIn(false)` 不能漏**：否则每次回绕都会 `setFadeInStartTime(now)`，
淡入权重每循环归零重爬一遍，观感 = "每隔 N 秒身子被拽回去"。
设了 ①② 之后**前端不需要任何动作计时器**，回落 idle 由库逐帧接管。

### 3.4 `_startMotion` 里的 `stopAllMotions()` 让动作切换**完全没有交叉淡化**

库的 cubism4 管理器每次起动作都先 `queueManager.stopAllMotions()` → 旧动作被瞬间掐死，
姿态硬跳（观感 = "动作不对、身子拧着、穿模"）。而队列管理器自己的 `startMotion`
**本来就会给现存条目 `setFadeOut()`** —— 所以只要不再调 stop 就恢复官方交叉淡化：
```js
mm._startMotion = (m, onFinished) => { try{ m.setFinishedMotionHandler(onFinished); }catch(e){}
  return mm.queueManager.startMotion(m, false, performance.now()); };
```
配合 3.3 的循环动作要注意：`_isLoop=true` 时 `getDuration()` 返回 −1 → `endTime=-1` →
淡出权重恒 1；但条目被 `setFadeOut` 触发淡出时 `startFadeOut` 会把 `endTime<0` 改成
`now+fadeOut`，所以**循环动作仍能正常淡出退场**，不会赖着不走。

### 3.5 运行时自加的 Cubism2 式「呼吸层」——Cubism4 模型必须关掉

`Cubism4InternalModel` **无条件**挂 `CubismBreath`，每帧在动作**之后**再 ADD 五个参数：
`ParamAngleX ±7.5°@6.5s / Y ±4°@3.5s / Z ±5°@5.5s / ParamBodyAngleX ±2°@15.5s / ParamBreath ±0.25@3.2s`。
而 Cubism4 模型的动作**本来就自带**这些参数的动画（碧蓝全库 74~85% 的 idle 有）→ **头部双驱动**，
观感 = "一直在有点快地动、不自然"。铁证：游戏侧 bundle 的 MonoBehaviour 组件清单
（`CubismMoc/Model/Parameter/PhysicsController/Raycaster/MouthController/Live2dChar`）里**根本没有 Breath**。
```js
internalModel.breath?.setParameters([]);   // 关掉，播放完全等于动作数据本身
```
（`updateFocus()` 也是每帧 ADD，但 `autoInteract:false` 时 focusController 恒为 0，无害。）

### 3.6 判定区/淡入淡出/Groups 别自己拍脑袋，跟权威实现对齐

model3.json 里三处最容易自以为是：
- **淡入淡出**：给每条动作硬写 `FadeInTime/FadeOutTime:0.5` 会让"回落 idle"比运行时默认
  （idle 组 **2s**、其余 0.5s）快 4 倍 → 反应没收尾就被拽回去。**不写**才交给运行时默认。
  若 idle 带大量定值曲线，2s 淡出会在点击后继续拖尾 2 秒把参数往回拽 → 显式拆开
  `FadeInTime:2.0, FadeOutTime:0.5`（库里这两值默认共用同一个 idle 常量，只能显式覆盖）。
- **`Groups`** 缺 `EyeBlink`/`LipSync` 时 `internalModel.eyeBlink` 直接是 undefined（模型不眨眼）。
- **`HitAreas` 不止 Head/Body/Special**：moc3 里可能有几十个 `Touch*` 标记（碧蓝安土有 76 个：
  `TouchDrag1-24`、`TouchIdle1-47`）。只登记三个 → 点其它区域毫无反应。
  补登时务必实测**新框与核心框是否重叠**（安土实测零重叠才敢上）。

### 3.7 销毁与泄漏

`app.destroy(true,{children:true,baseTexture:true,texture:true})` 不会移除 `window` 级监听。把所有监听存进状态对象并提供 `off()`，切换标签/关闭弹窗时统一调用：

```js
state.off = () => { ro.disconnect(); wrap.removeEventListener(...); window.removeEventListener('pointermove', onMove); ... };
```

### 3.8 clip 驱动过的参数无人回写 → 模型整体移位、判定区全丢（"进去就出不来"）

**症状**：某个动作（安土 `touch_idle1`）播完之后判定区集体失效。实测画布 20×16 模型单位，静止态 57 个判定区已有 53 个在画布外（只有核心 3 个 + `touch_idle1` 真可点）；播完这条 clip 后 **57 个全部出画**，核心三个一起被甩到同一点 `(-36.37,-52.81)`，回到 idle 也不恢复。
> ⚠️ **别把"静止态出画"当成脏数据**（2026-09-27 实测否证过一次误判）：那些出画的 `TouchIdle*/TouchDrag*`
> 往往是**换装/互动按钮的停放位**——它们挂在会动的道具上，播对应动作时才随部件进画面。
> 判别方法：逐动作组播一遍、每组重新量"有几个标记落回画布内"（本项目 `l2d_hit_offcanvas.py --sweep`）；
> 静止态 4/26 → 播某些组时 7~10 个，即证明是动画驱动，**不可按几何位置批量删除**。
> 换装状态的落地形态是「各 clip 用定值曲线锁住 `TouchSiwa`/`Paramaixin` 这类开关参数」，
> 所以按钮的 `HitAreas[].Name` 就是那条动作组名，与"随机取同组另一条"的命中规则天然兼容。

**根因**：Cubism 只对"本 clip 有曲线的"参数施权，**缺曲线的参数停在上一个动作留下的值上**。该 clip 252 条曲线里 **15 条 `idle` 从不驱动**（含整体位移）→ clip 末帧值永久残留。游戏侧靠 `change_in`/`home` 状态机复位，Web 运行时没有状态机，所以同一份数据在游戏里不暴露。（导出侧同一条机制见 §6.5「`m_ConstantClip` 定值曲线不是惰性的」。）

**定位 = 参数集求差，不靠猜**：对 motion3.json 取 `{c.Id | c.Target=="Parameter"}`，算 `clip集 − idle集`。
⚠️ `Id` 有两种形态，纯字符串 或 `{string:"ParamX"}`，判据要兜两种：
```js
const curveId = c => typeof c.Id === 'string' ? c.Id : (c.Id && c.Id.string) || null;
```
差集非空即锁定嫌疑人。

**修法**：复用 §3.3 那个 `createMotion` 补丁顺手登记每组参数集（零额外请求），`play()` 里 `if (g !== idleGroup) played.add(g)`，再用一个 ticker 回写：

```js
const restTick = () => { const cg = mm.state?.currentGroup;
  if (cg && cg !== idleGroup) { rest = null; return; }               // ② 只在回 idle/队列空时才动
  if (!rest) { const idleS = paramSets[idleGroup]; if (!idleS || !played.size) return;
    const want = new Set();                                          // ① 只碰播过的 clip 驱动过的参数
    played.forEach(g => (paramSets[g] || new Set()).forEach(p => { if (!idleS.has(p)) want.add(p); }));
    played.clear(); const items = [];
    want.forEach(p => { let i = -1; try { i = cm.getParameterIndex(p); } catch (e) {}
      if (i >= 0) try { items.push([i, cm.getParameterValueByIndex(i), cm.getParameterDefaultValue(i)]); } catch (e) {} });
    if (!items.length) return;
    rest = { items, t0: performance.now() + REST_DELAY }; return; }  // ③ 先等上一条淡出跑完
  const el = performance.now() - rest.t0; if (el < 0) return;
  const k = Math.min(1, el / REST_MS);
  for (const it of rest.items) try { cm.setParameterValueByIndex(it[0], it[1] + (it[2] - it[1]) * k); } catch (e) {}
  if (k >= 1) rest = null; };
app.ticker.add(restTick);   // REST_DELAY=400, REST_MS=700
```

三道防误伤约束：① 只处理「播过的 clip 驱动、idle 不驱动」的参数，物理/眨眼/口型等 clip 无关参数一律不动；
② 只在回到 idle（或队列空）时触发；③ 先等 `REST_DELAY` 让淡出跑完，再线性渐变过去（硬赋值会跳帧）。
目标值取 **moc3 默认值**（`getParameterDefaultValue`）而非"进动作前的快照"：这些参数在静止态本就没人动，
默认值 ≡ 静止位，且与快照时机无关。

**坑：`paramSets[idleGroup]` 为空 ⇒ 复位永远不触发**（那个 `if (!idleS) return` 是静默的）。
当 idle 的 motion 在补丁挂上**之前**就被创建时发生——库的预加载分支是
`switch (config.motionPreload) { default: e = [this.groups.idle] }`，所以 `motionPreload:'ALL'`
或组名恰为库默认的 `Idle` 时必踩。本项目组名是小写 `idle` 而 `mm.groups.idle` 要到 §3.3 的补丁里才被改成小写，
默认路径不预加载、侥幸躲过——但**判据必须显式断言 `paramSets[idleGroup]?.size > 0`**。
兜底做法：另 fetch 一次 idle 各条 json 登记参数集，顺带补 `Meta.Loop`（同一份 json，别开第二条管线）。

## 4. 按部位点击触发（HitAreas）

游戏里的 Live2D 是**点击部位**触发（不是悬停）。数据在 `model3.json` 顶层 `HitAreas`：

```json
[{"Id":"TouchHead","Name":"Head"}, {"Id":"TouchBody","Name":"Body"}, {"Id":"TouchSpecial","Name":"Special"}]
```

- **`HitAreas[].Name` 通常就是动作组名**（本项目 256 模型 768 个判定区对 `FileReferences.Motions` 键 **768/768 精确匹配**）。先跑一次全库统计验证这个假设，别凭直觉找 `tap*` 组——多数模型根本没有裸 `tap` 组，于是"点哪儿都不动"。
- 取判定几何：`idx = coreModel.getDrawableIndex(a.Id)`，再 `coreModel.getDrawableVertexPositions(idx)`（模型单位，x/y 交替）。**点击瞬间实时读，不要缓存**——框会随呼吸/物理每帧位移，缓存坐标会点空。
- 坐标换算：`const lp = mdl.toLocal(new PIXI.Point(屏幕x - wrapRect.left, 屏幕y - wrapRect.top)); const 单位 = lp.x / internalModel.pixelsPerUnit`。
- **判定形状 = 部件的真实四边形（两三角），不是它的轴对齐包围盒**（2026-09-23 二次修订，推翻本条旧结论）。
  游戏侧 `CubismRaycaster` 就是对 `Touch*` 部件做三角形 raycast。这些标记是 4 顶点不可见 quad，
  **部分模型的 quad 是斜的**：四边形面积/包围盒面积比 = `yingrui_3` 0.489~0.755、`z46_3` 0.645~0.942，
  用包围盒等于把判定区放大最多 2 倍 → 点旁边空地也触发（用户报"有些点击不准"）。
  正矩形模型（碧蓝安土 `antu_2` 等，比值 1.000）两种判定**逐点等价**，零行为变化。
  ⚠️ **本条旧结论"三角面反而更差、包围盒 767/768"是错的**：那次实测是在**坐标系换算还没修对**时做的，
  且试图用 `coreModel.getDrawableIndices()` —— **该方法在 live2dcubismcore 的 Model 包装上根本不存在**
  （只有 `core.drawables.indices[i]`），拿到 undefined 后判定全崩，被误当成"三角面数据不规整"。
  正确做法：4 顶点按**三角带序**拆成 `(v0,v1,v2)+(v1,v3,v2)`，无需索引缓冲；实测 5 个模型
  `带序面积 == 凸包面积`，证明带序假设成立。包围盒只当**快速预筛**用。
- **顶点序是三角带，画多边形必须换环序**：`getDrawableVertexPositions` 给的是 `(TR,TL,BR,BL)` 带序，
  直接 `drawPolygon(v0,v1,v2,v3)` 会连成**自交蝴蝶结**。无自交环序是 `[0,1,3,2]`。
- 多个框同时包含时（部位框常重叠/嵌套）取**面积最小的框**（最具体的部位优先）。
  旧的"归一化中心距离就近取"在嵌套框上会选到大框；改最小面积后安土等正矩形模型行为不变，
  `yingrui_3`/`z46_3` 的斜框误伤被剔掉（实测收窄 26.4%）。
- 容差只给 **2%**（吸收测试派发延迟的几十毫秒位移）。给到 8% 会把视觉上明显空白的角落判成命中——Live2D 画布四周有大量透明边距，模型单位范围比可见内容大得多。
- **兜底动作只给没有 `HitAreas` 的模型**。有判定区却点框外，就什么都不播（与游戏一致）。否则点哪儿都蹦一个 `touch_drag*`，观感极差。前端配套：`fallbackG = hitAreas.length ? null : <兜底组>`——`hitAreas` 非空时把兜底组设为 `null`，才会出现"点框外不播"；否则形同空壳。

## 4.5 生成真实 HitAreas（修补占位 Id，2026-09-22 碧蓝航线实测）

§4 讲的是**消费**已有 HitAreas；本节讲**如何为占位模型批量生成正确 HitAreas**（`fix_model3.py` 一类管线）。典型根因：还原管线早期只往 `model3.json` 补占位 Id `HitArea/HitArea2`，而前端 `getDrawableIndex("HitArea")` 取不到 drawable → 判定区被过滤成空 → 点部位退化成兜底乱播。

- **保守只替换占位 Id**：仅当某模型现有 `HitAreas[].Id ⊆ {HitArea, HitArea2}` 时才改写；已带正确 Id 的模型**一律不动**。这样"256 个既有模型零回退"是**构造性保证**（压根不进改写分支），不靠事后校验兜底。
- **`Id`**：碧蓝统一用 `TouchHead/TouchBody/TouchSpecial`，须能被 `getDrawableIndex(a.Id)` 解析（返回值 `≥0`）。**改写前先逐字节探针确认该 drawable 真的在 moc3 里**——判据是 `getDrawableIndex("TouchHead") >= 0` **且** `getDrawableVertexPositions(idx)` 非空（如 4 点 = `vlen=8`）。只有**部件名**（Part）不算，必须是**drawable**，否则前端仍取不到框。
- **`Name`**：必须是**该模型真实存在的动作组**，即能在 `FileReferences.Motions` 的键里找到。按候选顺序取第一个命中的（小写回落，兼容不同命名世代）：
  - `Head → [Head, head, tapHead, taphead, tap_head, touch_head, TapHead]`
  - `Body → [Body, body, tapBody, tapbody, tap_body, touch_body, TapBody]`
  - `Special → [Special, special, tapSpecial, tapspecial, tap_special, touch_special, TapSpecial]`
  经验：老模型组名是 `Head/Body/Special`，新换入模型是 `touch_head/touch_body/touch_special`——两代都要覆盖，只认其一就是"点哪儿都不动"的来源。
- **改后必须证"仅该字段变"**：跑前对全部 `model3.json` 快照 `(path, mtime, sha256)` 清单，跑 `fix_model3` 后 diff → 断言"**仅 N 个文件变、且每个文件仅 `HitAreas` 字段变**"（顶层键集合不变、`changed_fields == ['HitAreas']`）。任何其它字段被顺带改动 = 回退，立即排查。
- **收尾**：`hit_verify --only <这批 key>` 逐个证 **3/3 命中**（点击各 drawable 框中心 → `state.currentGroup == HitAreas[].Name`）；再全库复跑确认命中数增量 == 新启用的判定区数（本项目 13 模型 × 3 = +39，768→807、767→806，同一 `z46_3` 嵌套框歧义为既有非回退项）。
- **⚠️ 静止态落在画布外的 `Touch*` 不等于脏数据，不许按几何位置批量过滤或删除**。这类标记常挂在**会动的道具**上（按钮/绳索/手持物），静止态被停在画布外几千像素处，播对应动作时才随部件进画面才可点。判别式只有一个：**逐动作组播一遍（走页面自己的 `play()`，别直接 `startMotion`），每组重新量"落回画布内"的标记数**——静止态 4/26、播某些组时 7~10 个即证明是动画驱动。
- **换装/开关类交互的落地形态是"各 clip 用定值曲线锁住开关参数"**（如 `TouchSiwa`/`Paramaixin` 这类 Parameter，`touch_idle31` 里 `Paramaixin=1.6` 就是爱心眼）。所以按钮的 `HitAreas[].Name` 本来就是那条动作组名，**不需要另造切换机制**；反过来，一个 `Touch<X>` 若没有同名动作组，多半是"开关参数 + 停放标记"，而不是可点部位。

## 5. 构图与 fit 的两个陷阱

1. **别用 `mdl.width` 当模型尺寸**：pixi-live2d-display 下它可能返回 1 或被污染的包围盒（个别模型被巨型离屏 quad 撑到百万像素）。可靠基准是 `internalModel.width / internalModel.height`（= Cubism 画布单位 × `pixelsPerUnit`，如 8000×8000）。
2. **`fit()` 必须幂等**：`DisplayObject.width` 已含 `scale`。若在 fit 里用 `mdl.width` 算缩放，`ResizeObserver` 二次触发时会**正反馈放大**，画面糊成局部特写。做法：加载后缓存未缩放尺寸（或直接用 `internalModel.width`），维护 `baseK(适配) × z(用户缩放)` 与偏移 `ox/oy`，`apply()` 统一由这三者算 scale 与位置；`fit()` 只是把 `z/ox/oy` 归零后 `apply()`。

## 6. 交互层反模式

- **不要 `preventDefault` 劫持裸滚轮**。鼠标经过模型时用户可能正在滚页面，被劫持后页面不动、模型一路放大并累积平移，看起来像"模型自己乱动、位置不对"。改成 **Ctrl/⌘/Alt + 滚轮**才缩放，并在提示文案里写明。
- 拖拽必须处理 `pointercancel` 与 `window blur`，否则拖拽态卡住，之后每次鼠标移动都在平移模型。
- 平移量要钳制（如 `max(wrapW,wrapH)*0.6`），防止把模型拖出视野再也找不回。
- 位移 < 6px 视为"点击"而非"拖拽"，用来触发动作。

## 6.5 motion 数据从哪来：Unity AnimationClip → motion3.json 的权威映射

（从 Unity AssetBundle 侧还原动作时的正确姿势，2026-09-21 碧蓝航线实测）

- **curve index ↔ `m_ClipBindingConstant.genericBindings[i]` 同序**；且
  `genericBindings[i].path = crc32("Parameters/<GameObject名>")`，部件是 `crc32("Parts/"+名)`。
  实测 946274 个绑定的解析率 99.77%（未解析的 0.226% 是第三类属性哈希，运行时无对应 motion target，只能跳过）。
  不是 sdbm/djb2/FNV——别再试别的哈希函数。
- `CubismParameter` 组件的 `m_Name` 是**空**的：真名挂在 **GameObject** 上，`_unmanagedIndex` 才是
  moc3 参数序号。被动画化的序号是**稀疏**的（实测 `lingbo/idle` = 0,1,2,8,9,12,13,14,15,18,…），
  所以**绝不能假设 "curve idx == 参数序号（从 0 连续）"**——这是"眼睛数据写进眉毛参数"的来源，
  模型会照常动，只是动得面目全非（乱飘/乱闪/个别没反应）。按组件枚举顺序取参数名同样是错的。
- StreamedClip 的**帧 0 是 `time=-3.4e38` 的参考姿态帧，一帧合法写完全部曲线**（大模型一帧 380~520 个 key）。
  任何 `if numKeys > N: break` 之类的"合理性护栏"都会在帧 0 崩掉整条动作；
  只能靠 `+inf` 结束符 + 缓冲区边界停。该帧要当作各曲线 t=0 的基准值，而不是当普通关键帧丢掉。
- **⚠️⚠️ 贝塞尔控制点是「绝对 (时间, 值)」，不是归一化分数**（2026-09-23 血泪根因）。
  段序仍是 `[1, c1x, c1y, c2x, c2y, 终点time, 终点value]`（终点在最后，官方没有第 5 个
  "interpolation" 字段），但运行时解析器是**直读不做任何还原**：
  ```js
  case Bezier:
    points[a]   = new j(seg[l+1], seg[l+2])   // (时间, 值) —— 绝对坐标
    points[a+1] = new j(seg[l+3], seg[l+4])
    points[a+2] = new j(seg[l+5], seg[l+6])
  ```
  若按归一化写 `[1, 1/3, by1, 2/3, by2, t, v]`，控制点会被读成「t=0.333 **秒**、值=0.667」——
  落在段外且值接近 0 → **每条贝塞尔都先猛蹿到≈0 再跳到目标值**。表现为"部件各动各的、
  像刚学建模的人做的、穿模"，而**曲线数/时长/参数名/量程全部校验都能通过**，极难自察。
  正确写法 = Unity 三次 Hermite 的等价控制多边形：
  `c1=(t0+dt/3, v0+outSlope·dt/3)`、`c2=(t1−dt/3, v1−inSlope·dt/3)`。
- **但"格式正确"≠"效果正确"**：Unity **密集键**（相邻键 ≪ 周期）的那对切线字段本就不该当 Hermite
  切线用，照上面算会飞出几百个参数单位。碧蓝实测三种写法对权威基准的逐曲线偏差（121 点采样）：
  | 写法 | 偏差中位 | 偏差>0.5 的曲线 | 最甚 |
  |---|---|---|---|
  | 归一化控制点 | 1.376 | 92/98 | 9.35 |
  | 绝对控制点·全贝塞尔 | 0 | 88/278 | **296** |
  | **关键帧 + 线性**（采用） | 0 | 11/278 | 1.95 |
  → 从 Unity AnimationClip 反解时，**默认就该发线性段**；`|dv|<1e-3·max(1,|v0|,|v1|)` 的退化线性
  与 `|by|>3` 拉直都是掩盖格式错误的权宜，别当成优化保留。
- **`Meta` 要对齐**：`Fps` 取 `AnimationClip.m_SampleRate`（别硬编码 30）；`AreBeziersRestricted:true`
  的含义是"控制点横向恒在 1/3、2/3"→ 运行时走朴素参数化求值（不解三次方程），与上面的发法自洽。
- **⚠️ Unity 曲线分装在三个容器，只读 `m_StreamedClip` 会丢数据**：
  `m_Clip.data` 有 `m_StreamedClip` / `m_DenseClip` / `m_ConstantClip`，
  而 `genericBindings` 的顺序 = **[streamed][dense][constant]**（实测 98+0+180=278 且名字零冲突）。
  `m_ConstantClip` 是"整段保持定值"的曲线，**不是惰性的**：Cubism 只对"本 clip 有曲线的"参数施权，
  缺曲线的参数在切动作时**停在上一个动作留下的值上** → 被 `touch_*` 动过的手臂回不到静止位 → 部件错位。
  参考实现的 `idle` 曲线数正是 streamed+constant 之和。**务必一并导出定值曲线**
  （`Segments:[0, v, 0, duration, v]`，每条 1 段 2 点）。
- 运行时**完全不读 `pose3.json` / model3 的 `Pose` 键**（该字符串在 pixi-live2d-display 里出现 0 次），
  但支持 motion3 的 `Target:"PartOpacity"` → 换装/部件可见性只能写进 motion3.json，出 pose3 是死路。

### 6.6 `Textures` 清单是**按索引**消费的：枚举序必须显式归一 + 闸门 + 看图

`model3.json` 的 `FileReferences.Textures` 数组，运行时把第 i 项绑给 moc3 的**纹理索引 i**。
moc3 文件里**不含任何贴图名**（碧蓝 269 个 moc3 全量搜不到 `texture_*.png` 字符串），
所以"哪张图是索引 0"这件事**只能由清单顺序决定**，错了不会报错、只会画面碎。

- **典型症状**：模型加载成功、动作在播、参数在动，但画面是"几十个部件碎片叠一堆"
  ——每个 art mesh 从别的图集里采样。背景层（往往集中在某一张图）看起来还大体成形，
  这反而最容易骗人："渲染出东西了"被当成"渲染对了"。
- **导出侧的坑**：从 Unity bundle 落贴图时用的是序列化对象的**枚举顺序**，
  它 ≠ 索引顺序。碧蓝实测 **51/269 个模型两者不一致**（最狠的一个 6 张图枚举成 `[02,05,00,03,04,01]`）。
  也就是说这一步**必须在写完后显式归一**，不能指望生产方的迭代顺序；
  归一化是承重步骤，不是装饰。
- **归一规则**：按名中数字排（`texture_%02d` 的编号即索引），无数字者排在带数字之后按名称序。
  前提是先全量确认命名齐整（碧蓝：`非 texture_%02d 命名 = 0`），否则"编号即索引"这条约定不成立。
- **闸门**（退出码即判据，只读检查、`--apply` 才写）：`l2d_texorder_check.py`。
- **完整性对账**（另一类静默失败：解码 `except: continue` 悄悄少一张，结构仍合法）：
  逐模型比 源 bundle 的 `Texture2D` 清单 vs 磁盘 PNG，报 `missing / extra / 命名异常`。
- **⚠️ 验收必须包含"逐张看图"**：加载成功、`getDrawableCount()`、参数跨帧 min/max、帧哈希在变——
  在错绑这一类故障下**全部为真**。代理指标只能证"没死"，不能证"对"。
  看图工具要现成（否则它自然被代理指标顶替），且**判据要写明"和什么比"**：
  本技能实测把一张"人躺在地上、腿朝镜头"的正常前缩透视误判过一次"姿势反常"，
  拿同皮肤的静态立绘一比即证伪。可比对象优先级：同皮肤静态立绘 > 同批未改动对照组 > 权威外部实现。

## 7. 无头验证判据（配合 CDP）

### 7.0 自研管线必须找**外部权威实现**做基准，自证清白一定会漏

**教训**：碧蓝 Live2D 的 motion3.json 控制点格式错了整整一个量级（见 §6.5），但
曲线数、时长、参数名映射、量程、空壳率**全部校验通过**，`hit_verify` 也是 806/807 全绿——
因为这些都只验证"结构自洽"，不验证"和原作一样"。用户反馈"部件各动各的、像刚学建模的人做的"
持续了好几轮，我先后误判成呼吸层、误判成插值护栏，**直到拿到同模型的权威导出才一次锁定**。

可用的外部基准（同一批游戏模型、成熟 Cubism 实现）：
```
https://static.l2d.su/azurlane/live2d/<key>/<key>.model3.json
https://static.l2d.su/azurlane/live2d/<key>/motions/<组>.motion3.json   # 注意 motions/ 复数
```
路径规律是从它的 SPA bundle（`/assets/index-*.js`）里 grep `model3.json` 模板反查出来的；
只覆盖部分模型（抽样 8/14），404 就跳过。比对**逐曲线按运行时真实语义采样求值**
（linear 插值 / stepped 取起点 / bezier 在 `AreBeziersRestricted` 下用归一化时间直接当贝塞尔参数），
判据：组与曲线集合零缺失、**关键帧零不一致**、偏差中位 ≤0.5、偏差>0.5 占比 ≤12%
（12% 是按"结构完全正确时的真实残差"校准的，不是拍脑袋）。

**没有外部基准时的次优锚点**：① 目标实现的录屏/截图做目视基准；② 用**不经过被测映射**的
可见语义点反查（如"屏幕上的头/胸/髋三点应分别落入对应判定框"）；③ 逐字段 diff 对照组证零回退。
只做"自己算一遍再和自己比"的回归 = 验证自洽性，不是验证正确性。

- **判"动作真的有效"要同时满足两条**：① 正在播的 motion 的 `_motionData.curveCount > 0`；
  ② 取该 motion 自己的曲线 Id，`getParameterValueById` / `getPartOpacityById` 的值随时间变化。
  只看 `state.currentGroup` 变了没有，会让 `"Curves": []` 的空壳全部绿灯通过
  （本项目就曾因此报出"260/260 全通过"，而实际 57% 是空壳、其余曲线名全错）。
  按部位点击的断言同理：别只断言组名标签，要断言内容。
- **采样必须在 clip 时长内高频密采，不能在载入若干秒后才比对两点**：本项目运行时把**每条 idle 都解析成 `isLoop:false`**（与 motion3 的 `Meta.Loop:true` 无关），idle 播完一遍即回静帧、`state.currentGroup` 归 null、参数回落到基准。若"载入→等 9~12s→两次快照逐参数相减"，短 idle（5~8s）早已播完 ⇒ 假报 `moved=0`（曾据此误判新换入的 `bunao_3`/`guanghui_9` 坏了）。**正确做法**：载入并进入该 clip 后，每 ~420ms 推一帧（手动 `PIXI.Ticker.shared.tick()+app.render()`）、**累积每个参数跨帧 min/max**，判据=「播放窗口内 `max-min>1e-3` 的参数条数 > 0」。另注意手动 `startMotion(group,0,FORCE)` 会与页面自动播相互打断，验证"用户打开即所见"时**别再手动 startMotion**，直接密采。

批量验证 260 个模型时的做法（驱动细节见 `headless-chrome-cdp-batch-export`）：

- 页面内串行遍历：`await renderLive2D(ship, sk)` → 等 1.5~2s → 读 `state.currentGroup` 与 `motionManager.definitions` 数。每轮先 `stopLive2D()` 释放，否则 WebGL 上下文/纹理堆积。
- 断言落在**产品语义**上，不要落在"我猜它不该命中"上。例：断言"有判定区的模型任何点击都不该播出 `touch_*/tap*` 兜底组"，而不是"点某个自算的空白点不该有反应"——后者会因 `toGlobal → 屏幕坐标 → toLocal` 往返误差在极端点被放大而恒失败。
- 冷启动（删过 profile 后）页面里访问 `window.GALLERY` 之类全局数据要先轮询等待，否则 `ReferenceError`。
- **两个 chrome 实例并发跑 CDP 会互相抢**，报 `Execution context was destroyed`；批量验证要串行。
- 清理残留 chrome 必须按 `--user-data-dir` 精确匹配进程命令行再 kill，**绝不能按进程名全杀**（会误杀用户自己的浏览器）。

### 7.1 全库规模（数百模型）必须分批起新 Chrome

上面"每轮 `stopLive2D()` 释放"只能撑一小段：**单个 headless Chrome 顺序加载约 110 个模型后 WebGL 上下文耗尽**，CDP 连接断，报 `Connection to remote host was lost`（标签崩溃），与 `l2d_sweep` 的"单次 evaluate 卡住/断连"同类。靠单进程 + 手动释放扛不住全库，必须**换成分批新进程**：

- **切批**：用 `--only "k1,k2,..."` 逗号清单把模型切成 **~40 个一批**（本项目 269 → 4 批），**每批一个全新 Chrome**（每次调用只起一次进程），而不是一个长循环从头跑到尾。
- **冷启动首模型易报错**：每批新进程加载的第一个模型常撞 `window.GALLERY 未就绪` / `stopLive2D is not defined`（harness artifact，非模型问题）。对策：给每批 `--only` 清单**头部塞一个已知良好的预热模型**（如 `lingbo`，不计入统计），或对报错的首项单独复跑；一旦 warm 起来同模型即 3/3。
- **汇总口径 = 按 key 去重取最优**：合并所有分批日志，同一模型 key 在任一批 `ok` 即算 `ok`，避免某批崩溃漏记被误判成回退。
- 实测：分批后 **269/269 覆盖、806/807 命中**，唯一 miss `z46_3`（Special 框嵌套在 Body 内）是 §4 记录的既有"归一化中心距离"歧义，非本轮回退。

### 7.2 验证前端自己挂的逻辑，必须驱动页面的真实入口

复位、淡出、随机变体这类逻辑挂在页面的 `play()` 上（下拉框 onchange / 点击 handler / 按钮）。
探针直接 `mm.startMotion(g,0,FORCE)` 会**整层绕过它**，于是"复位没生效"其实是"根本没进被改的那段代码"——
2026-09-23 本项目就据此把一个**正确的**修复误判成无效。

```js
const sel = document.getElementById('l2Motion');
if (!sel) return JSON.stringify({ err: '动作下拉框不存在，无法走真实播放路径' });  // 不许回落假路径
sel.value = grp; sel.onchange();                        // ✓ 真实路径
// mm.startMotion(grp, 0, MP.FORCE);                    // ✗ 绕过前端交互层
const started = mm.state.currentGroup;                  // 必须回读：区分「静默失败」与「没复位」
```

handler 缺失时探针要**显式报错**，绝不回落到 `mm.startMotion` 继续测——回落等于自造假阴性。
验收判据（工具 `scripts/diag/l2d_touchidle_probe.py`）：before 出画 53 → mid 57（clip 生效）→
after **53（与 before 相等）**，且位移 >0.3 的判定区数 = **0**。

### 7.3 CDP 就绪必须三件同时成立——`about:blank` 的 `readyState` 天生就是 `'complete'`

**症状**（会被误判成产品坏了）：探针一连上就报
`ERR openShip is not defined` / `openShip is undefined` /
`Cannot read properties of undefined (reading 'internalModel')` / `Execution context was destroyed`。

**根因**：CDP 连上 tab 的瞬间，执行上下文可能还是 `about:blank`，而
`about:blank` 的 `document.readyState` **天生就是 `'complete'`**。于是

```js
while (document.readyState !== 'complete') sleep();   // ✗ 第一次判就放行
```

这个门槛形同不存在，后续所有 `Runtime.evaluate` 都打在空白页上。

**实测指纹**（空白上下文 vs 真实页面）：

| 判据 | `about:blank` | 真实页面 |
|---|---|---|
| `document.URL` | `about:blank` | 目标 URL |
| `document.scripts.length` | 0 | 多个 |
| `document.documentElement.outerHTML.length` | 39 | 数十万 |
| `window.GALLERY` | `false`/undefined | 对象 |
| 时间线 | 连上即刻 | **41~43 秒**才 complete（263KB html + vendor + 索引） |

**正确判据（三件同时成立，缺一不可）**：

1. `location.href` 真的等于目标（含 query / `#` 差异归一）
2. `document.readyState === 'complete'`
3. **业务标志在**（如 `typeof window.GALLERY === 'object'`）—— 这一条才是真正区分
   「页面加载完了」与「执行上下文还没换过去」的判据

固化实现：`scripts/diag/cdp_wait.py` 的 `wait_ready(ev, want_url, budget, flag)`，
返回 `ok` + 实际耗时，超时给出最后观测到的三项状态。踩坑补充：

- 等待中的 `continue` **不要计入重试预算**，否则慢页面（本项目 41s）会被判超时。
- 连 `/json` 列表时 `chrome-extension` 的 `background_page` 会混进来，
  **必须按目标 URL 子串过滤 tab**（如 `gallery_v2`），不能取列表第 0 个。
- 页面级就绪 ≠ 模型级就绪：本项目点完 live2d tab 后模型进舞台还要更久，
  「45s 内模型未进入舞台」是模型级超时，别拿它反推页面没加载好。

## 8. 落地检查清单

- [ ] 三件套版本成对且按序加载；vendor 相对路径在页面上下文里 `fetch` 验证过
- [ ] `startMotion` 显式 index + `MotionPriority.FORCE`
- [ ] 用 `state.currentGroup`（等待后）证明动作真的在播，不靠帧比对
- [ ] fit 基准取 `internalModel.width`，且 fit 幂等（ResizeObserver 多次触发不放大）
- [ ] 部位命中实时读框；兜底只给无 HitAreas 的模型；容差 2%
- [ ] 裸滚轮不被劫持；`pointercancel`/`blur` 解除拖拽；平移钳制
- [ ] `stopLive2D()` 里 `app.destroy()` + `off()` 都做
- [ ] 无头批量验证：全量命中率与失败清单，含"无判定区"模型列表
- [ ] 参数残留复位：断言 `paramSets[idleGroup]` 非空；「clip 驱动 − idle 驱动」差集写回 moc3 默认值；复位探针走页面 `play()` 入口，after 出画数 == before 出画数
- [ ] 全库规模（数百模型）分批起新 Chrome（~40/批），首模型预热重跑、各批日志按 key 去重取最优
- [ ] 补占位 HitAreas：Id 逐字节确认是 moc3 drawable、Name 取该模型真实存在的组（候选小写回落）、仅替换 Id⊆{HitArea,HitArea2}、改后 sha256 清单证"仅 N 文件且仅 HitAreas 字段变"
- [ ] `Textures` 清单按名中数字归一 + 闸门跑到退出码 0；源 bundle `Texture2D` 清单与磁盘 PNG 对账 missing/extra/命名异常全为 0
- [ ] **逐张看图**（走页面真实入口、按 canvas 裁剪只截模型区）：新 bundle 换入后必做，且指明"和什么比"；代理指标全绿不构成完成证据
- [ ] 接了语音/台词层 → 过 §9 的九条（自持 Audio、等表再开播、按皮肤序号直取、正文与音频同源、字幕在全屏目标内、audio 可见高度、CDP 反向证据 + 阴性对照、"有正文无音频"独立一档不造假控件、"没声"先分清是没接上还是上游没下发）

## 9. 动作语音与台词层（2026-09-27 补；此前这条只写在决议里，技能一直停在 §8）

模型动起来之后下一层是"点它会说话、说的有字幕"。八条，每条都对应一次真实返工：

1. **不要用运行时库的 Sound 通道**（`definitions[g][0].Sound`）。那条由 SoundManager 托管，**下一条动作一 `startMotion` 就把上一条 dispose 掉**；而 idle 播完会自动回落 idle ⇒ 凡是"动作时长 < 语音时长"的组都会话说一半被掐（实测 `touch_head` 动作 5.17s、语音 9.24s，在 `currentTime=4.48s` 处被 `pause`）。改成**页面自持一个 Audio 元素**：只有用户再次触发、切标签、换皮肤才打断，运行时回落 idle 不打断。⚠️ 动作时长本身是忠实的（`Meta.Duration` == 曲线末帧 == 源 clip），别去数据层找原因。
2. **首播竞态**：语音表是异步 `fetch` 的，模型就绪那一瞬播的动作拿不到 Sound ⇒ 表现成"第一个动作没声音，之后才有"。开播前 `await` 表到位。**加了台词层之后要把正文表一起等**，否则同样的位置换成"有声没字幕"。
3. **取词按皮肤序号，不许随机抽**：cue 名尾部的 `_N` 是**该语音包内的皮肤档位**，不是"同一条台词的随机变体"。导出侧按本皮肤档位选档，前端一律直取。当成变体随机抽的后果：三皮肤船有 2/3 概率播到**别的皮肤**的台词，且 `_9`（改造皮肤）永远取不到。⚠️ 但**这个档位不等于皮肤行 id 的末位**——皮肤序号 ≥10 之后游戏给新皮肤换了号段（第二位 0→3，末位变成批次内顺序号），把两者当同一个数就是 §86 那次整页台词派错船的起点。另：**画法变体（同一张皮肤的另一幅画，如 `_n`/`_hx` 后缀）不是另一张皮肤**，做"一个目录名分一个档位"这类分配时要把它们排除、直接继承本皮肤，否则变体占掉别人的档。
4. **正文与音频必须同源——"同一档位"，不是"同一行"**：❌ 旧写法 `皮肤行id = cv*10 + idx`（拿语音包号和档位反推主键）在皮肤序号 ≥10 处会**进位撞进下一艘船的那一行**：行存在、正文非空，`if not row` 这类护栏根本不响，只有"字幕比语音短"这种人耳判得住的矛盾会露出来。⇒ 行 id 要**按皮肤名查权威表得到**（查到后回查那一行的归属是不是本皮肤），且台词表里存 `cv`/`idx` 字段的情况极少，别指望反推。
   两层取值规则：音频用的是**本皮肤档**文件的槽位 ⇒ 正文只许取这一档自己的词，取不到就**空着**（宁缺勿错派）；音频落在**基础档**的船级类别（誓约/资料/委托/强化，皮肤行里通常没这些字段）⇒ 回退到本体那一行。同一 painting 有多行时（META/联动另开一档），要**优先取与音频同一个语音包**的那一行。
   类别名之间的对应（cue 类别 / Live2D 动作组 / 触摸槽 / 台词正文字段）全查 `character_voice` 的 `key ↔ resource_key ↔ l2d_action`，**先断言一个运行时名不对多个字段**（有歧义就拒绝，别猜）。
   ⚠️ 还有一类没有来源的：**活动限定变体**（cue 名带 `_ex<code>`，与本体同 `cat`）在台词表里通常**没有**对应字段 ⇒ 前端必须给它独立标签且**不配字幕**，并按 `cat` 取值的地方把它排除掉；否则同一个类别出两行、字幕一模一样（实测 15319 行）。
5. **字幕条必须挂在"会被 `requestFullscreen()` 的那个元素"里面**。各视图通常把自己的全屏按钮做成 `容器.requestFullscreen()`，全屏时**只有那棵子树**被渲染出去；字幕若挂在容器外面（例如挂在上一层 flex 容器上）就是"全屏没台词"。又因为各视图会 `el.innerHTML=...` 整块重写，这个节点要**按需取用/重建**，不能常驻在骨架里。
6. **`<audio controls>` 在列向 flex 容器里会被压成 0 高**：`flex:1` 展开是 `flex-basis:0%`，容器高度由内容决定时没有剩余空间可长 ⇒ 播放器看不见（点都点不到），但行还在。写 `flex:none` + 固定高，判据量 `getBoundingClientRect().height`。
7. **验收（CDP 无头）七条判据**：① 走真实 UI 路径（点语音按钮 / 点画面 / 点部位），不直接调 `startMotion` 或页面内部函数；② 在页面脚本执行前包住 `window.Audio`，断言新实例的 `src` **属于本皮肤档位**且 `currentTime` 在涨——**轮询到真的走秒**，固定等 1.5s 会把正常文件读成 `cur=0` 报假失败；③ 字幕**逐字**等于表里该槽位正文，且"谁在说"那行是中文类别名（内部键 `complete`/`touch_body` 等于把实现细节露给用户）；④ 开关类改动必须拿到**反向证据**：关 A ⇒ 只剩 B、关 B ⇒ 只剩 A，只验"开着时能用"不算；⑤ 挑一条"**有音频但游戏本来没写词**"的槽位做阴性对照（必须出声且**不弹空字幕框**，这同时挡住"字幕残留上一条"）；⑥ 探针不许依赖上一轮状态——无头 Chrome 被 kill 时不保证把 `localStorage` 落盘，下一轮开局开关可能是关的，**每轮先设基线**；⑦ 取不到页面状态要**硬失败**（顶层 `let` 不挂 `window`，用裸名取；返回非 JSON 直接 raise），绝不让"没测到"长得像"测过了"。
8. **"有正文、没有音频"要有独立一档，且绝对不许伪造播放器**（2026-09-27）：一批皮肤的语音主包没随资产下发、台词表里却齐全。
   三处一起改才通：词表要**多跑一趟**（这类皮肤不在语音表里 ⇒ 由语音表派生的键表收不到它们）、索引要有一个
   "只有文本"的计数位（`voiceText`，且**只在无音频条目上写**，别改动 `voiceCount` 的语义）、标签页的放行判据换成
   `有音频 || 有文本`。渲染时这类行**不生成 `<audio>`**——装了就是个点了不响的假控件；验收把这条当反向证据
   （页面 audio 数只允许等于"确实有文件"那一节的条数）。另：文本类内容要有一条**内容形状断言**（页面上不许出现
   `{namecode:NN}` 这类运行时占位符），结构判据全绿也拦不住"把占位符直接端给用户"。
9. **"这一格没声"有两种，别用一条推理打包回答**（2026-10-02）：**我们没接上**（权威表里有这一行、包也在，只是归属
   算错）vs **上游根本没给这个实体下发录音**（有自己的行但包号不在盘上）——修法完全相反，前者改代码、后者改了就是
   造假。分开它要用**两条互相独立的事实**：表里那一行的主键（→ 包号）逐号去源包目录与已解码目录各查一次。
   ⚠️ 两个代理指标都不许当证据：`voice_actor=-1` 在剧情/变体实体上是哨兵值（不等于无 CV）；"整个号段都不在"是
   按前缀归纳，同一个大段里往往有别的号是下发的 ⇒ 只能**逐包号**判。

## 10. 单模型目视页（l2d_visual.html）的 motion 播放 与 model3 资源重写（2026-10-16，version 1.7.0）

- **动画组来源**：model3 的 **`FileReferences.Motions`**（`{组名:[{url}]}`）**不在顶层 `motions`**；运行时读
  `motionManager.definitions`（键即组名）。
- **选组只认键集存在性**（`clip in definitions`）。⚠️ **`definitions[g].length` 懒加载前恒 0**，拿它当
  「组存在」判据会误杀真实组（`main_1`/`idle3`）→ fallback 播成 `idle6`/`idle2` → 表现成「动作不对应
  所请求 clip」。**切勿用 length/返回值判「组是否存在」，只看键在不在。**
- **播放直呼** `model.motion(group, idx)`（priority 默认 2）；不要遍历候选组 / 定时重试 / 自选 idx。
  **不要 FORCE(3)**：强制打断当前动作、整体换行为，常被用户拒。
- **资源 404 → 黑屏**：pixi 把 model3 **完整 URL（含文件名）当资源 base 目录**，请求
  `<dir>/<name>.model3.json/<res>`；server 需 rewrite 回 `<dir>/<res>` + 尾斜杠兜底（`scripts/diag/serve_live2d.py`）。
- **验证走页面启动路径**：`scripts/diag/vis_auto_l2d.py` 不手动调 play，只等页面 `setTimeout` 自动播、
  再轮询参数振幅；**headless 过 ≠ 实机过**，中间只差缓存（实机硬刷/无痕后再判）。
- 完整根因、排除假设与三链接验收见 `docs/TROUBLESHOOTING.md` §117、操作流程见 WORKFLOWS WF-30。

## 11. 画质：渲染分辨率（DPR）怎么提、怎么验（2026-10-17，version 1.8.0）

场景：Live2D/Spine 在高 DPI 屏糊了，要把渲染 buffer 从 1x 提到 ≥2x。判据量 **canvas buffer**，
不靠截图（headless DPR=1 看不出 2x）。

- **Live2D**：`new PIXI.Application({..., resolution:Math.max(2, dpr), autoDensity:true})`。
  vendored pixi `RESOLUTION` 默认 **1**，不显式传 resolution 就是 1x；`autoDensity` 必须成对
  （只加 resolution 会让 canvas CSS 尺寸撑垮布局）。P1440/4K 屏 dpr>2 时取 dpr 倍率。
- **Spine**：`resize()` 里 `cv.width = round(wrap.clientWidth*dpr)`；且帧循环**每帧**比对
  `buffer vs CSS×DPR` 偏差即重建（拖动跨 DPR 显示器、全屏进出会变，用事件监听会漏）。
- **命中/取景不受影响**：Live2D 命中走 `mdl.toLocal(clientX-rect.left, clientY-rect.top)`
  （pixi 官方坐标转换自动处理 resolution），取景用 CSS `clientWidth/Height`——跟渲染 buffer 解耦，
  所以 resolution/autoDensity **不会**破坏命中几何。Spine `fit()/pixelFit()` 用 `cv.width`
  自身乘 DPR 内部自洽，构图不变。
- **验收探针**：`scripts/diag/l2d_spine_dpr_verify.py`（真实点击路径读 `app.view.width` /
  `spcwrap canvas.width` 对比 CSS×DPR，4 样本：live2d=2x、spine=CSS×DPR 全 PASS）。
- **⚠️ 无头只验到「≥2x 成立」**（dpr=1 时 `want=max(2,1)=2`）；真实高 DPI 观感须用户真机确认。
- **踩坑**：本机可能没 Chrome（只有 Edge），项目多数无头脚本硬编码 Chrome 路径 →
  `FileNotFoundError [WinError 2]`（wf16 全挂）。**别当成产品缺陷**；自建探针带 Chrome/Edge 候选列表。
- 完整判据/步骤/排除假设见 `docs/TROUBLESHOOTING.md` §118、操作流程见 WORKFLOWS WF-31。

## 12. 动作回落语义：idle 变体判定与映射表（2026-10-17，version 1.9.0）

场景：非 idle 动作播完，想回落「最衔接的待机变体」（方案 B），而不是固定回落 idle。要点在三层回落语义 +
idle 变体判定。

- **idle 待机变体 = 只认 `^(idle\d*)$`**。home/main_*/login 是**场景长动画**（宿舍/主界面滑/登录），
  **不是**循环站姿变体——别把它们塞进 idleSet：用户实测播 home/main_1/2/3 会「无限自循环停不下来」。
  数据侧 `scripts/build_motion_chain_map.py` 的 `IDLE_RE` 决定此判定，写进 `motion_chain.json` 的
  `idle_groups`，前端 `idleSet = new Set(idle_groups)` 直接用。
- **三层回落语义**（在 `mm.startRandomMotion` 接管回调里，按 `lastGroup` 分类）：
  ① `touch_drag*` → 回落 drag 自身（配合 `createMotion` 对 idle/drag 组 `setIsLoop` 持续循环）；
  ② 长动画（`!idleSet.has(lg) && !/^touch_idle/`）→ 2026-10-19 前是固定回 `idleGroup`；**新语义见 §12.1**；
  ③ `touch_idle*` → 查 `chainModel.chain[lg].best`（末帧 vs 待机首帧差异度，口径见 WF-32）。
  回落目标确定后同步更新 bar 的 `#l2Curr` 动态标签（播动作显示动作名、回落后显示待机组名）。
- **回落必须直接 `mm.startMotion(best, idx, IDLE优先级)`**，**不能**调库 `startRandomMotion`：它只在
  「已加载进 motionGroups」的条目里筛（见 §3），变体组从未播过 → motionGroups 空 → 静默返回 false，
  回落永不触发，currentGroup 卡在动作组。
- **`.includes` 空数组恒 false**：全量启用闸若写成 `SAMPLE_ONLY.includes(sk.key)`，在 `SAMPLE_ONLY=[]`
  时**全库禁用**（`[].includes(x)` 恒 false → chainSrc=null → idleSet 只剩 idleGroup，所有 touch_idle
  退化成默认 idle）。正确写法 `SAMPLE_ONLY.length===0 || SAMPLE_ONLY.includes(sk.key)`。
- **启发式 best 会随候选集漂移**：idle_groups 候选数一变（如剔除 home/main_*/login），norm 重排后 best
  可能改变（aersasi_2 touch_idle1：idle3→idle）。因此**验证探针的 expected 必须从表动态读 best**，
  别手写一个会漂的值。
- **无头验证回落**：headless 软渲染帧率低（1~2fps），长动画墙钟播不完 → `isFinished` 永不 true →
  自然回落不触发（**非产品 bug**，真机 60fps 正常）。探针用 `mm.queueManager.stopAllMotions()` 模拟
  动作结束，触发与自然播完**完全一致**的 complete→shouldRequestIdleMotion→startRandomMotion 回调链。
- 完整判据/踩坑：docs/TROUBLESHOOTING.md §120、操作流程见 WORKFLOWS WF-33。

### 12.1 2026-10-19 追加：best 要加「明显更优」闸门；黑屏/无候选回默认（version 1.9.1）

只按 `chainModel.chain[lg].best` 无条件回落，会在两种情况下害人：best 只比默认 idle 好 1~2%（伪最优，
等于在两帧几乎一样的姿态里抛硬币）；或 best 组没加载/条目是 fallback（静默失败 ⇒ 画面停在空状态，
用户看到「黑屏」）。落成前端 `_pickFallback`：

1. 条目不存在 / `fallback:true`（无待机候选）→ 默认 `idleGroup`；
2. best 组不在 `definitions` 或长度为 0（懒加载前）→ 默认；
3. 默认 `idleGroup` 也在 `runners_up` 时，必须 `best_norm < 0.85 × default_norm`，否则回默认；
4. 默认组不在候选（没有共同驱动参数）→ 允许 best（如 `zhenzhuhao_2 touch_idle25` nb=0 → idle20）；
5. **`touch_idle*` 例外：即使只差 1% 也必须回 best**（用户 2026-10-19 判据：别把 `touch_idleN` 吞回 `idle`）。
   全库 1,945 个 touch_idle 条目，其中 148 个因此从默认 idle 切到对应变体（aersasi_2 touch_idle2→idle5、
   aersasi_3 touch_idle31→idle1）。

**判据/数据**：aersasi_2 touch_head 的 best=idle5 只比 idle 好 2% → 回 idle；jianye_4 mail 的 best=idle3
（nb 0.0145 vs idle 8866.9）→ 必须走 idle3；z46_4 mission 是 fallback → 回 idle。全库 3,688 个长动作、
810 个 best≠默认，只有明显更优的才采用。**探针 expected 必须用同一套闸门动态算**（旧版把「长动作=idle」
写死，14 条全 PASS 却掩盖了 810 个动作）。

**「黑屏」取证**：全库 8,051 个 motion3 中 0 条以「所有 PartOpacity 归零」结束、1,033 条 Model/Opacity
曲线也 0 条以 0 结束 ⇒ 数据层没有「淡出到黑」的 clip；黑屏更像回落到未加载组后 startRandomMotion
静默失败。无头 ~2fps 不足以判高频观感，需真机对照。

**回落竞态（2026-10-19 实修）**：目标变体未预加载时 `startMotion` 要 fetch，期间库每帧再请求随机待机，
默认 idle 会抢先（label 已是 idle2、currentGroup 仍是 idle）。三件套：回落前 `mm.state.complete()`；
`startMotion(..., NORMAL=2)` 压过正在播的 IDLE(1)；记 pending 目标、最多 10s 内拒绝后续 `startRandomMotion`。
探针 `forceEnd` 也要先 `state.complete()` 再 `stopAllMotions()`，否则优先级残留 = 假 FAIL。完整判据：§124 / WF-37。


## 13. MultiplyColor / ScreenColor：0.4.0 运行时会整层丢色（2026-10-19，version 1.9.2）

moc3 4.2+ 给每个 drawable 存了 `MultiplyColor` 与 `ScreenColor`。游戏里大量用它们做：
- **multiply=[0,0,0,1]**：阴影/描边/分屏遮罩层（应压黑）；
- **screen=[1,1,1,1]**：白色填充的剪影（本例倒酒的白瓶白杯）。

`pixi-live2d-display 0.4.0` 的 Cubism 渲染器**只认模型级 u_baseColor**，全文搜 `multiplyColor` 0 命中；颜色数组其实在 `coreModel._model.drawables.multiplyColors / .screenColors`（`Float32Array`）。丢弃的后果：该黑的层被画成原色 → **分割线虚影/白边**；该白填充的层被画成贴图 → **和游戏画面不一致**。

**修法（最小补丁，别换栈）**：三个 fragment shader 加 `u_multiplyColor/u_screenColor`，`setupShaderProgram` 按 `renderer._drawableIndex` 取色，`doDrawModel` 每次 `drawMesh` 前记索引。公式：

```
texColor.rgb = texColor.rgb * u_multiplyColor.rgb;
texColor.rgb = (texColor.rgb + u_screenColor.rgb * texColor.a) - (texColor.rgb * u_screenColor.rgb);
```

**红线**：颜色数组缺失时必须回落 `multiply=[1,1,1,1] / screen=[0,0,0,1]`，否则默认模型整块变黑（首版实测）。读色层级是 `renderer.getModel()._model.drawables`，不是 `renderer.getModel().drawables`。

**不要升 0.5.0-beta**：它支持颜色但要 Pixi 7；当前栈 6.5.2，换上后 `Live2DModel.from` 不 resolve。补丁版要入库（`gallery_src/vendor/live2d/...-patched.js`）+ MANIFEST `local` 源，否则换机器 fetch 会拉回原版。

**验收**：`ougen_8 idle8` 分割线虚影消失、`touch_idle17` 白瓶白杯出现；再抽 3 个默认色模型确认没变黑；`hit_verify.py --only ougen_8` WIRING=0。完整取证：§125 / WF-38。

## 14. 回落三层语义 / 看门狗 / 自动刷新 / login / 眼动（2026-10-19，version 1.9.4）

**回落（唯一定义）**：touch_idle* 用 `norm`、touch_drag* 用 `raw_sse` 查表 best；**不做覆盖度排除**（覆盖度会误杀 idle9 这种低覆盖但末帧完全重合的候选，反而选 idle11）。touch_drag* 按住时强制 loop、松手回表 best；其它长动作默认 idle；只有 idle* 自循环。不要给长动作加“最佳衔接”闸门/覆盖度排序（2026-10-19 试过，ougen 会从 idle9 变 idle13，用户判不衔接，已回退）。

**卡最后一帧**：库的 `shouldRequestIdleMotion` 不一定及时触发；在 `app.ticker` 检测 `currentGroup==null` 且不在回落中 → 下一帧 `startMotion(dst,0,NORMAL)`。

**自动更新**：索引重建（`build_gallery_index.py`）写 index 前跑 `build_motion_chain_map.py --write`，失败拒绝写 index。

**开场 login**：`OPT.login` 默认关；FORCE 启动（NORMAL 压不过初始 idle），用户切动作前 `state.complete()`。

**眼神**：`OPT.eye` 默认开；LOW 优先级 ticker 直接写 `ParamEyeBallX/Y`（写在 update 里会被 `loadParameters()` 覆盖）；判据指针右上 → +0.7/+0.6，关闭回 0。

**分屏阶梯**：mask 256→1024/2048 只变细；4x+4096+2D 降采样仍存在，是 artmesh 硬 alpha 露出 (0,0,0) 底色。CSS blur 0.55 可消但整体软；彻底修需改模型 mask/artmesh，运行时不要谎称已根治。

完整取证：§127/§128、WF-40。

**2026-10-19 追加**：mask 缓冲不能固定 1024/2048 —— Cubism 把多个 mask 铺在一张方 RT 上，N 必须 ≥ 画布长边 × √maskCount；按模型自动取 2 的幂（ougen_8 maskCount=9 → 8192）。拖拽互动：把 moc3 的 TouchDrag* 补成互动区（ougen 30+14=44），**Ctrl/⌘+左键拖拽**才触发（普通左键平移），松手按距离播 touch_drag*。

**HitAreas 完整性（2026-10-19）**：`fix_model3.py` 补 moc3 的 `Touch*` 时，动作组先查 `touch_<x>`，没有再退回 `<x>`（TouchIdle6→idle6 这种脱鞋/换装按钮就是被旧规则丢掉的）；TouchDragN 默认播 drag 动作：有 touch_dragN 用同名组，没有按编号轮转现有 drag 组；不能改播 idleN（~~脱鞋是 idle6~~ 误判已修正——见 §15，脱鞋是状态切换不是任何 motion）。

## 15. TouchDragN 不全是动作：状态开关的识别、接线与验证信源（2026-10-20，version 1.10.7）

**识别判据（缺一不可）**：某 TouchDragN 交互对应的参数 ① 在该模型全部 motion3.json 曲线里**零驱动** ② 零 physics3.json Output 驱动 ③ 0..1 值域开关 ④ 参数 Id 与区名同名或显示名是开关语义（「脱鞋」「墨镜」「××on/off」）。游戏里这类交互 = 播 motion（若有）+ **游戏代码直接 set 参数**，视觉过渡由 moc3 keyform 随参数渐变自然产生。碧蓝两种形态：区名→参数名不对应（ougen_8 TouchDrag17→ShoseOff，稀少）与**区名同名参数**（aersasi_2/3、antu_2 通用：点 TouchDragN = 播同名 motion + set 同名 `touch_dragN` 参数）。全库扫描器模式：join `CubismParameter`(GO 名=参数Id) + `CubismDisplayInfoParameterName`(显示名) + `CubismRaycastable`(区名)，三条判据过滤（实例 `scripts/diag/l2d_state_param_scan.py`）。

**接线（零 monkey-patch）**：配置表（模型→[{trigger,id,off,on,dur,label}]）+ `stateApply` 挂 `internalModel` 的 **`beforeModelUpdate`** 事件（vendor 在 physics/pose 之后、`model.update()` 渲染之前 emit）——帧末 `loadParameters()` 会把参数拉回 motion 末态，但下一帧事件里再写，**渲染永远读到状态值**，不与 motionManager 抢管线。切换动画 = tween 逐帧写中间值（easeInOutQuad 0.5s）。⚠️ 配置表是模块级常量时，运行态（`_on`/`_tw`）挂条目对象上会**跨模型实例残留**——每次进模型必须重置，否则重进皮肤带着上一场状态。

**验证信源的选择（截图法三层假阴性，按成本递增别走弯路）**：
1. 全图截图差分：idle 基线抖动（碧蓝大 idle 模型 21~44%）常常 ≥ 状态差异 → 假阴性；
2. 区域化裁剪：裁剪盒若取「点击标记」而非「形变 drawable」的盒照样漏；布局抖动还会让两张截图尺寸不一致；
3. 冻结 ticker + `core.update()` 手动步进：core.update 两帧对比自身不幂等，基线反而 45%，弃。
**两种干净信源**：① **顶点直读**——`setParameterValueById` + `core.update()` + `getDrawableVertexPositions()` 前后对比（形变 drawable 数即证据，配一条必驱动参数如 ParamAngleX 做阳性对照）；② **beforeModelUpdate 探针 listener**（排在产品 stateApply 之后注册）逐帧记录渲染前参数值——看到 tween 中间值与终态往复即闭环「渲染必读到」。形变大（换装/戴墨镜级别）时截图法才可直接用。

**探针时序坑**：算好点击坐标→等几秒→用旧坐标点击 = 假阴性（idle 演进让判定区移位，远超 2% 包围盒容差）。坐标计算与派发必须在**同一次 evaluate 里零间隔完成**。同理，读「参数当前值」要想到帧末 `loadParameters` 拉回——渲染前一刻才是真值。

完整取证：§132；实例 ougen_8 脱鞋 + aersasi_2 墨镜。

## 16. 残留复位竞态 + headless 时钟伪影（2026-10-20，version 1.10.8）

### 16.1 「消费型状态机 + async 登记」竞态（动作播完不复位的通型）

**通型**：页面侧有「播过什么 → 之后怎么处理」的消费型状态（如残留复位 restTick 的 `played` 集合）。`mm.startMotion` 是 **async**（未预载组先 fetch 再 createMotion，页面侧的登记（如 paramSets）在 resolve 后才发生）。若消费逻辑按帧跑且触发条件（currentGroup 回到 idleSet）在**加载窗口内就成立**（切组是 async、旧组还在），消费会读到**未登记的空集** → 按空集处理 → **这组动作被吞**，后续一切依赖该登记的逻辑静默失效。

**判据（日志形态）**：消费日志出现 `built ... 0`（want 为空）+ 随后 `empty`，而这组动作明明刚播过——不是没播，是被吞了。

**修法**：登记时刻用 `playedAt[g]=performance.now()` 之类的**独立时间戳**；消费前检查「登记未完成 && 加载占位（`motionGroups[g][0]===undefined`）&& 距 play < 超时」→ 本帧跳过不消费；超时按空集消费防死等。超时取网络加载上限量级（本地服务 5s 足够）。

### 16.2 headless 时钟伪影：动作「播不完/不回落」先查时钟再查逻辑

**机制**：vendored pixi-live2d-display 的动作时钟不是 `performance.now()`，是 `elapsedTime += Ticker.shared.deltaMS`（onTickerUpdate 累计、_render 时传 internalModel.update）。**PIXI Ticker 低帧率下 deltaMS 被 maxElapsedMS cap**（headless swiftshader ~1.2s/帧）→ 动作时钟慢于真实时间数倍 → entry 的 `endTime < userTime` finished 判定迟迟不达 → 动作不结束、不回落、与复位渐变交错的稳态残差。

**识别法（三个信号）**：
- entry 快照 `et` 固定、真实时间远超 `st+dur` 仍 `fin:0`；
- `queueManager._userTimeSeconds` 恒 0（该字段不走主时钟，别用它判推进）；
- fadeWeight 却正常推进（0→1）——updateParameters 在跑，只是时钟刻度慢。

**绕开法（验证时序敏感逻辑的标准姿势）**：不要等动作自然 finished——**直接切一个 idleSet 组**（`play('idleX')`）让消费逻辑的触发条件立即成立；开场 login 的 300ms 定时器竞态用 `localStorage.setItem('gallery.opt.v1', '{"login":false}')` + reload 排除。entry/state/调用流三层插桩模板见 `scripts/diag/l2d_motion_state_trace.py`（包 mm.startMotion/startRandomMotion/state.reserve/setCurrent/complete 记调用流 + queueManager._motions 快照）。

**已排除的假设（别重跑）**：restTick 写入被 loadParameters 覆盖（同帧写后读回即推翻——save→load 在同一调用栈，外部 ticker 插不进中间）；cm 实例不同/方法遮蔽（`cm===stage.children[0].internalModel.coreModel` + 原型方法 hasOwnProperty 判定）；FadeOutTime 过长导致对抗（全库缺省=-1 → endTime=ut-1 即时掐，对抗仅 1-2 帧）；物理/呼吸/focus 写 Angle 参数（物理输出不含、breath 已关、focus 写在 save 后被 load 撤销）。

完整取证：§133。

## 17. 状态开关的值域坑 / slider 模式 / restTick 开关豁免（2026-10-21，version 1.10.9）

### 17.1 on/off 不能硬编码——值域坑（墨镜只变深浅的根因）

状态开关参数的值域**不是统一的 0..1**：aersasi_2/touch_drag1 实测范围 **0..10**（`core.getParameterMaximumValue`），硬编码 `on:1` 只到 10% 渐变位 → 观感「只变深浅不是穿戴」。**配置表必须省略 on/off、运行时解析**（on=max、off=min，`getParameterIndex` 拿 ix 后读 min/max）。验证信源：产品逻辑态（`STATE_TOGGLES[key][i]._on` 从 off 变 max）+ 顶点直读形变数（墨镜 on 态 609 drawable 形变）。**帧末 evaluate 读参数值=假阴性**（loadParameters 拉回、stateApply 下一帧才重申）——别用参数直读验证状态切换。

### 17.2 slider 型 drag：拖动调值不是开关

需求形态：某些 TouchDragN 是**拖动位移连续调参数**（颜色深浅类），非穿戴开关。实现要点：条目加 `mode:'slider'`；onDown 时记 `参数初值+起点 x`；onMove 按 `(cx-x0)/240*(max-min)` 连续写值并同步更新 `_on` 快照（stateApply 的每帧重申消费它——闭环成立）；onUp 只结束拖动、值保持。点击（非拖动）slider 区走原 toggle 两端切换。**哪些模型哪些参数是 slider 语义要扫描+游戏对照确认，别拍脑袋接线**。

### 17.3 restTick 必须豁免「形态开关」参数（回落断崖真根因）

**通型**：残留复位逻辑（§21 restTick）把「播过的 clip 驱动、idle 不驱动的参数」拉回默认值。**两态装饰开关**（数据侧识别：≥5 组以定值出现且值集恰 {0, V}，如 antu_2/Param148 ∈{0,10}）也是「idle 不驱动」成员 → 切回 idle 被拉回 0 → **装饰瞬间消失 = 用户报的「回落完全不衔接」**。游戏语义是**状态保持**（拖完戴着）。修法：`build_motion_chain_map.py` 的 `find_switch_params` 把开关集写进表（v2 的 `switch_params`），前端 restTick 的 want 构造排除 `switchParams`。**注意与姿势参数的区分**：姿势基态参数（每个 idle 变体不同值、多态）不满足两态判据，仍正常复位。

### 17.4 回落选组的「漏参数断崖」盲区（计分口径）

只对「动作与 idle 共有参数」求差异的 metric，对**漏参数（idle 无曲线、被拉回 0）的断崖完全盲**——低覆盖候选（leak 84/293）赢过高覆盖（leak 4）。正确口径：**全参数计分**，漏参数按 `(end-0)²` 计入（开关参数例外：前端豁免保持，断崖=0 跳过）。**硬约束方案已否证**：把开关匹配当 idle 候选的硬排除——姿势组合参数混进开关集 → 全候选被排除 → 退回软分 = 约束白做；且排除路径返回占位分 0.0 会污染排序。

完整取证：§135；判据工具 `scripts/diag/l2d_pose_anchor_pick.py`（锚点）+ motion_chain.json v2。

## 18. 真实浏览器取证通路 + 渲染路径偏差（2026-10-23，version 1.10.10）

**为什么需要**：模型在 headless 全绿、用户真实浏览器却有部件缺失时，继续在 headless 里换参数只是空转。
缺的往往不是"更多假说"，而是**在用户那一层环境里取数**的能力。

### 18.1 页面侧三个取证参数（正本 `gallery_src/index.html` 末尾初始化段）
- `?ship=<id>`：打开即直达模型（+自动切 Live2D 标签）。
- `?motion=<组名>`：模型就绪后**走页面自己的 `window.__l2play`** 自动播该动作。
  ⚠️ 诊断脚本直接调 `motionManager.startMotion` 会绕过语音/标签/回落映射，是典型假阴性（本项目 AGENTS.md 明令禁止）。
- `?diagpost=<url>&diagframes=N&diagstep=ms`：把**全部 drawable** 的 `op/vis/ro/bbox` + WebGL
  vendor/renderer + Hand 参数值 POST 回本地接收端（`scripts/diag/hand_diag_sink.py`）。
  ⇒ 用户/默认 profile 环境**零操作**就能拿到与 headless 同格式的数据做逐一对照。
- 参数不支持时的表现：不带 `ship` 也要能执行 `diagpost`（把两者放在同一个 IIFE 里时，
  早退 `if(!sp) return;` 会让回传代码整段失效——本项目踩过）。

### 18.2 判据：headless 对账必须走真 GPU
`--use-angle=swiftshader`（软件渲染）与真 GPU（D3D11）在 **drawable 的 `vis` 上会不同**：
实测同一模型同一动作，`ArtMesh255~258`（op=1）在 SwiftShader 下 `vis=1`、真 GPU 下 `vis=0`，
真 GPU 与用户浏览器（ANGLE/NVIDIA D3D11）一致。
⇒ 凡是对账「可见性 / 像素」，headless 必须 `--gpu`；把 `WEBGL_debug_renderer_info` 的 renderer 字符串
随数据一起回传，当场就能核对两侧是否同一路径。**不要用软件渲染的绿旗去否证真实浏览器的问题。**

### 18.3 判据必须落在正确的 mesh 上（否则一直是盲的）
用手指/手掌这类无语义命名的 mesh 时，"猜一组 ArtMesh 编号当手部"会静默失效：本项目 §136 猜的
7 个 ArtMesh 全部不是皮肤部件，据此得出的"手部正常"结论无意义。
⇒ 用**逐 mesh 隔离渲染扫描**（patch `getDrawableOpacity` 只留目标 → render → 统计肤色占比）。
肤色占比 >0.9 的才是皮肤部件；再按 bbox 位置区分脸/手。
对"op=1 却 vis=0"的部件，用**叠加式强制显示**（只把目标 `getDrawableDynamicFlagIsVisible` patch 成 true，
其余保持原值，比较 patch 前后像素差异）定性：差异区就是该部件本身，避免把遮罩关系打乱。

### 18.4 坑：解构方法引用会丢 this，诊断 ticker 静默死亡
```js
const dvis = core.getDrawableDynamicFlagIsVisible;  // ✗ this 丢失，内部 this._model 报错
const dvis = (i) => core.getDrawableDynamicFlagIsVisible(i);  // ✓
```
外层再套 `try{...}catch(e){}` 空吞 → 诊断面板永远空白，看起来像"没有异常"。
⇒ 诊断/调试代码的 catch **必须把异常写进可读位置**（本项目把 `e.stack` 前两行写进诊断面板后一眼定位）。

### 18.5 用户环境复现失败时的正确交付
1. 先穷举**可自动化**的维度并逐条否证（DPR/有头/系统 DPI/全屏/动作切换残留/完整周期/数据版本/mask/model3），
   把否证结论连同"判据方法"一起入库——否证本身也是资产。
2. 打通 `?ship=&motion=&diagpost=` 后，剩下唯一一环是**人眼确认现象是否仍存在**；
   这时向用户要的不是"帮我跑脚本"，而是"打开这个链接看一眼，红框落在哪/数值板最后一行是多少"。

**涉及**：`gallery_src/index.html`（三个取证参数）、`scripts/diag/l2d_hand_probe.py`、
`scripts/diag/hand_diag_sink.py`、`scripts/diag/l2d_motion_curve_diff.py`、`scripts/diag/hand_skin_map.py`。

## 19. 部件「该显示却不显示」先找参数，不要先怀疑渲染（2026-10-23，version 1.10.11）

### 19.1 判据：`--findop` 直接点名控制参数
Cubism 高层 API 不暴露「哪个参数控制这个 drawable 的透明度」。做法是**逐参数试极值**：
对每个 `parameters.ids` 设 `min`/`max` → `core.update()` → 读 `getDrawableOpacity`，
`opacity` 或 `dynamicFlagIsVisible` 翻转的就是控制参数。一次扫描（582 参数）即可点名，
比逐帧截图差分快一个数量级。

实证（ougen_8 左腿）：`Param211=30 → 腿 op=1`；`=0 → op=0`。
再回 motion3.json 比对：`home`/`login` 把它钉在 30，idle 系列只写 `[0,8]` 残值
⇒ 「进模型少条腿、点某个区反而出现」的完整因果。

### 19.2 场景级姿势开关要「钉基线」，且只钉未驱动项
换装/场景类参数（腿、道具、装饰）的正确值常由**主界面动作**（home/login）决定，
在待机 idle 里只留接近 0 的残值。播放器从 idle 起步就会缺件。
修法：每帧在 `beforeModelUpdate`（motion 之后、渲染之前）钉回基线值，
**但必须跳过「当前动作组有曲线驱动」的参数**，否则会盖掉动作本身的曲线。

### 19.3 回落口径：raw_sse 与 norm 会背离，别假设归一化更合理
`norm = Σ(d/range)²/N`（range = 该参数在各待机候选首帧间的值域）会让
**实际几何差异最大的候选**拿到最小 norm：ougen_8/touch_idle14 的 idle5 raw 排名 11 / norm 排名 1，
而正确答案 idle9 raw 排名 1 / norm 排名 11。
判据：把两个口径的完整排行都打出来看是否背离（`l2d_fallback_rank.py`），
背离时**以用户/游戏观感为准**，不要拿 norm 值大小当正确性证据。
全库切换口径前先量影响面（`l2d_fallback_metric_ab.py`：本项目 1945 条里 363 条会变 = 18.7%），
影响面大就先用「手工修正表 + `__hold__`（播完不回落）」逐条兜，别一次全切。

### 19.4 `__hold__`：不是所有动作都该回落
`effect` 这类语义是「暂停当前动作」的组，回落反而打断它。回落表要能表达「保持不回落」，
而不只是「回落到哪个组」。

**涉及**：`scripts/diag/l2d_hand_probe.py`（--findop/--abparam/--params/--follow）、
`scripts/diag/l2d_fallback_rank.py`、`scripts/diag/l2d_fallback_metric_ab.py`、
`gallery_src/index.html`（BASE_PINS / FALLBACK_FIX）。

### 19.5 更正：`--findop` 的结论不足以判定「显示开关」（2026-10-23 实测翻车）
`--findop` 能证明「改参数 X 会让 mesh M 的 opacity 变化」，但**姿势参数同样会让 opacity 变化**
（换 keyform 改变形状/遮挡 → 可见性跟着变）。本项目据此把 `Param211` 当显示开关钉死 30，
结果**把 idle 的双腿动画直接改了**，而缺的部件仍未出现。

判据修正 —— 确认「显示开关」必须**同时**满足：
1. 改它能观察到目标部件出现；
2. **不破坏该动作自身其它部件的表现**（后者才是区分「开关」与「姿势」的关键）。

定量辅助：同帧 A/B（`--abparam`）看差异面。
- 差异面小且集中在局部（ougen_8 的 ShoseOff：0.64%）→ 局部开关/换装
- 差异面大、横跨整片肢体（Param211：4.6%）→ 姿势/形态参数，**不许钉值**

另：部件"不显示"还可能因为它**根本没有对应曲线**——ougen_8 的 idle9 是 12 个 idle 变体里
唯一不写 `Param211` 的那个，于是它保持上一个动作的残值。查「该组有没有这条曲线」比猜参数含义快。

### 19.6 回落表重算必须带 `--write`（否则静默不落盘）
`build_motion_chain_map.py` 不带 `--write` 只打印统计、**不写产物**；终端最后一行出现
`[chain] 已写 <path>` 才是真写了。同类坑：CDP 探针会命中 `http.server` 的 Last-Modified 缓存，
改完前端/数据后仍读到旧文件 → 假阴性。修法：探针 URL 加毫秒时间戳 + `Network.setCacheDisabled(true)`。


## 20. 互动区（Touch*）与换装参数：信号源选择与验收判据（2026-10-23，version 1.10.13）

### 20.1 找互动区要用 moc3 的 Touch* drawable，不要用参数曲线
**错误做法**：扫 motion3.json，按「参数在不同动作间有多档取值」筛互动项。
**为什么错**：换装开关（脱鞋/戴眼镜/戴手套）在游戏里是**运行时代码 `setParameterValueById` 写的**，
动作曲线里恒为常量。实测 `ShoseOff` 在 **46 个动作**里全部是 0 —— 从曲线看"只有 1 档"，
被"恒定值无可调空间"规则整类剔除。用硬编码个案（如 `touchdrag17 → ShoseOff`）补，
只能补到你发现的那一个。

**正确信号源**：**moc3 里的 `Touch*` drawable**（互动区本体，模型自带按钮部件）。
它与 model3.json 的 HitAreas 是否登记无关 —— 实测某模型 moc3 有 44 个 Touch drawable，
HitAreas 只登记 3 个，**1299/4085 个互动区存在但前端点不到**。
moc3 是二进制，但字符串池里 drawable id 可直接
`re.finditer(rb'Touch[A-Za-z0-9_]{0,24}', raw)` 捞出，不需要解析库。

### 20.2 三层信息要分开，别混为一谈
| 层 | 来源 | 回答什么 |
|---|---|---|
| 互动区存在 | moc3 的 Touch* | 有哪些按钮 |
| 能否点中 | model3.json HitAreas | 前端认不认 |
| 点了做什么 | **只在游戏代码里** | 效果语义 |

`--findop <TouchDrawable>` 只返回**该 drawable 自身的显隐参数**（实测 `TouchDrag17 → Param500`），
**与它触发的业务参数无数据关联**。⇒ 自动提取只能做到"发现 + 定位"，
效果语义必须目视确认或用户标注，别宣称能自动推导。

### 20.3 「这个参数改了有没有效果」的唯一可靠判据
三个假象（都踩过）：
1. **画布像素哈希**：headless(`--gpu`) 下 `drawImage(app.view,…)` 取到**全 0 缓冲**
   （哈希里可加非零像素计数自检，`nz0` = 0 个非零），此时"模型右移 40px"都判无变化。
2. **前后两次全量 drawable 快照直接比**：呼吸/眨眼会在两次采样间改变状态 → **假阳性**
   （曾让一个"改动 0 个 drawable"的参数显示"有变化"）。
3. **写入后立即回读**：前端 pin 由 ticker 下一帧才重申，立即读必然读到动作铺回的值 → **假阴性**。

**可靠判据**：把参数写到两端值 → 中间 `core.update()+render` →
**逐 drawable 对比 opacity / dynamicFlagIsVisible，并要求能点名出具体部件**（changed > 0）。
停动作能消除动画干扰；点名则排除假阳性。
实测产出：某参数改动 16 个 drawable、另一个改动 2 个，各自可复核。

### 20.4 参数「可写性」也要验，别把钉死参数当交互
部分参数的 `min == max == default`（moc3 把它们钉死），前端放个按钮点了也不生效。
上游筛选时必须跑一次运行时验证：写入后连推数帧再读，稳定保持才算可写。

**涉及**：`scripts/diag/l2d_touch_drawable_scan.py`、`l2d_toucharea_export.py`、
`l2d_toucharea_ui_verify.py`、`l2d_costume_writable_probe.py`、`l2d_canvas_hash_diag.py`。

## 21. 非循环动作播完不回 idle：库的回落通道可能整条失效，别改 vendor 库（2026-10-24，version 1.10.14）

**症状三连**（同一个根因的不同表现，容易被当成三个 bug）：
点动作后画面「定住」；开场 login 播完角色「逐渐走出画面只剩背景」；「当前动作」标签一直停在刚播的组名。

### 先分清三条通道，别混着查

| 想做的事 | 依赖什么 | 失效表现 |
|---|---|---|
| 动作播完自动回 idle | `MotionManager.update()` 里 `isFinished()` → `state.complete()` → `shouldRequestIdleMotion()` → `startRandomMotion(idle, IDLE)` | 停末帧、永不回落 |
| 「当前动作」标签正确 | 前端自己写 DOM（库回落**不**经过前端 `play()`） | 画面已回落但标签还是旧组名 |
| 用代码强制切动作 | `MotionState.start()` 的优先级规则 | `startMotion` 静默失败、`state` 纹丝不动 |

### 判「有没有回落」不能用 UI 标签

标签只在**前端主动播**时写入；库自己回落时不刷新它。据标签判「未回落」必然误判。
可靠判据只有两个：读 `mm.state.currentGroup`（回落成功后它会变成 idle 组），
或用参数直读看姿势定值是否回到 idle 组的值。截图像素比对**不可用于此**——
idle 有呼吸循环，同状态两张截图的差异本底就有 20~80，基准不稳时判据会给出任意结论。

### 别改 vendor 库，用时长自己安排

`isFinished()` 走 `queueManager` 条目的 `_finished` 标志；实测某些模型/库版本下
`getEndTime()` 恒为 `-1`、`_finished` 从不置位、`motionFinish` 从不 emit。
这时改库要动 vendor 文件（下次换版本全丢），而「按 `Meta.Duration` 定时回落」几行就够：

1. 索引侧把每个动作组的 `Meta.Duration` 带进 `motion_chain.json`（库的 `definitions` 里只有 `File`，
   取不到时长）。
2. `play()` 里 `setTimeout(duration + 0.6s)` 调回落；`play()` 每次先 `clearTimeout` 防叠加；
   语义上「播完停在末帧」的动作（如 `effect`）用白名单跳过。
3. 回落时 **`state.complete()` 之后必须把 `currentPriority` / `reservePriority` 归零**，
   否则上一动作的 FORCE(3) 会让回落请求被 `reserveMotion` 拒掉。

### `startMotion` 的优先级陷阱（最耗时的一条）

`MotionState.start()` 的真实规则：

```js
if (priority === 1) {                      // IDLE
  if (this.currentPriority !== 0) return false;
} else {                                    // NORMAL(2) / FORCE(3)
  if (group !== this.reservedGroup || index !== this.reservedIndex) return false;
}
```

**非 IDLE 优先级要求先 reserve**。没走 `reserve` 流程时传 2/3 必被拒，
而且 `startMotion` 是 async，返回的是 Promise，`sync` 读状态永远读到旧值 ——
现象就是「返回值看着正常、`state` 一点没变」。**代码里主动切动作时优先用 IDLE(1)。**

### 附带的两个坑

- **`#l2Curr` 的 DOM 引用会失效**：工具条用 `bar.innerHTML=...` 重建时，旧节点脱离文档；
  此前抓的引用写 `textContent` 写进孤儿节点，页面上看不见。每次 `getElementById` 重查。
- **旧产物可能是靠数据错误绕过问题的**：对照旧画廊发现它 41/55 个 clip 的 `Meta.Loop=True`，
  而 Unity `m_LoopTime` 真值是 `False`。旧版「从不回落」正是因为动作永不结束。
  **数据侧忠于源数据、功能侧自己补回落**，不要抄错误标记。

### 回落目标别写成默认组（2026-10-24 实测）

索引侧（motion_chain.json）会为每个动作算出 est = 「本动作末帧 vs 各待机变体首帧」
衔接最优的那个组，实测 42 组里 27 组的 best 指向**具体变体**而非默认 idle。
回落逻辑若图省事写死 idleGroup，这 27 组会全部跳回不衔接的待机
（用户可见症状：脱完鞋/摆好姿势后人物「跳一下」回到另一个姿势）。

优先级应为：手工覆盖表 > chain[组].best > idleGroup 兜底。
验证用 erify_touch14.py <模型> <组名>，它同时打印「索引期望」与「实际停留」。

### 「部件消失」先与基准逐 drawable 比，别数不可见数量

getDrawableOpacity 里「842 个 drawable 中 530 个透明度≈0」看着像严重故障，
其实是 Live2D 常态：模型同时准备正反面两套肢体（Zhengmian_* / Beimian_*），
同一时刻只有一面可见。**不可见部件数不是缺陷判据。**

正确判据是「同动作下，与可信基准逐 drawable 比不透明度」：一致则属源模型特性，
不一致才是回归。实测 ougen_8 新旧 842 个里 841 个一致、仅 1 个 0.034→0.019，
两边画面肉眼等同——用户报的「左腿缺失」在旧画廊里同样存在。
工具：scripts/diag/ab_part_opacity.py。

### 验证要点

- 播一个时长 T 的非循环动作，在 T+1~2s 时断言 `state.currentGroup` 已变成 idle 组、
  且标签同步更新；再对 2~3 个模型重复（不同模型组数/时长差异大）。
- 服务进程会静默消失，探测读到白屏会算出「完全一致」的假结论。
  **每次验证前先探活 + 渲染门禁**，不过就报 INVALID，不输出结论。
- 一次偶发的 `xhr.onabort` 不能定性为缺陷，重试 2~3 次再判。

## 22. 「回落成功却闪回默认待机」：先看目标 idle 的曲线数（2026-10-24，version 1.10.16）

**症状**：动作播完、`state.currentGroup` 确实变成了正确的 idle 变体，标签也对，
但回落那一瞬间姿势猛地塌回「直立正面」。用户会说「回落后立马闪回初始默认 idle」。

### 判据：末帧 vs idle 首帧的逐参数差值，不要看覆盖率

模型库里常见**分层 idle**：一个 idle 变体只负责一部分参数（呼吸），姿势由动作末帧提供。
判「衔接对不对」只看一件事：

```python
common = set(action_end) & set(idle_start)
sse = sum((action_end[p] - idle_start[p]) ** 2 for p in common)
```

**`sse == 0.0` 且共同参数只有几十个，就是正确答案**，不是错误。
两个独立 `.motion3.json` 的浮点值逐一精确相等，只可能是制作方刻意对齐。
附带判据：正确的目标 idle 往往**首尾闭合率极高**（呼吸层特征，实测 `idle9` 109 条里 108 条首尾相同）。

⚠️ **`best_coverage` 低不是缺陷**。实测 `touch_idle14 -> idle9` 覆盖率仅 26.2%，
一度据此提议「排除低覆盖候选」，被用户当场纠正。覆盖率低**恰恰说明**该 idle 只驱动
一小部分参数，剩下的 305 个靠动作末帧续着。选 100% 覆盖但 `sse=728` 的候选，
只是用「多比较了不该比较的参数」把正确答案挤掉。

### 缺口在哪里：`end_val` 有、目标 idle 无曲线的那些参数

```python
cliff = {p: v for p, v in action_end.items()
         if p not in idle_start and abs(v) > 0.5}
```

这批参数在回落瞬间会被 `model.loadParameters()` 按 moc3 默认值复位成 0。
`ParamAngleX = -18.367 -> 0` 就是「视角翻转」的直接来源。

### 修法：pose_keep + LOW ticker pin（两个执行者都要处理）

1. **索引侧**（建表脚本）给每个动作输出 `pose_keep`：
   `末值非零 且 目标 idle 无曲线 且 非开关参数 且 非运行时驱动参数`。
   - 必须排除 `ParamEyeL/R/BOpen` / `ParamEyeBallX/Y` / `ParamMouthOpenY` / `ParamMouthForm` /
     `ParamBreath` —— EyeBlink / LipSync / CubismBreath 每帧写，pin 住会让模型**永不眨眼**。
   - `ParamAngleX/Y/Z` **不能**排除：它们同时是真实姿态参数，pin 覆盖呼吸小偏移是预期行为。
2. **前端**：
   - 回落时把 `pose_keep` 写进 `__posePinsByModel[skinKey]`，key 另记一份 `__poseKeepKeys`。
   - ⚠️ **动作组名要在 `lastGroup = <回落目标>` 改写之前抓走**。回落函数末尾通常会把
     `lastGroup` 覆盖成目标组，用错变量就拿不到本动作的 pose_keep。
   - ⚠️ **参数残留复位（`restTick` 那类「拉回默认值」的逻辑）必须排除这批 key**，
     否则 pin 与复位渐变每帧互写，肉眼是姿势抖动。
   - pin ticker 挂 **LOW 优先级**（模型 `update()` 含 `loadParameters()` 之后、渲染之前），
     且**只在待机组生效** —— 动作播放中要让曲线自由驱动，不能把自己该动的参数钉住。

### 探针纪律：三个反复踩的陷阱，都会产出「参数恒 0」的假象

| 陷阱 | 表现 | 正解 |
|---|---|---|
| 读 `mm._motions` | 永远 0 条，误判「队列空」 | `mm.queueManager._motions` |
| 用 `qm._userTimeSeconds` 算 fadeIn | 恒 0 → `fin=0` → 误判「权重为 0」 | 该值**不参与** `Cubism4MotionManager.updateParameters(model, now)`，恒 0 是正常的 |
| `addChild` hook 抓到的模型 | 切皮肤会重建，旧实例 `destroyed=true` 仍占着 `window.__xxx` | 过滤 `destroyed !== true` |
| 在 `setParameterValueByIndex` 里抓 `Error().stack` | 主循环从 ~150 次/秒压到 4 次/2.6s → 假数据 | 只读采样，不改写路径 |

### 上游库 `curves.push` 冗余：确认无害，别改

某版本 `CubismMotion.parse()` 先 `Array.from({length: curveCount})` 预分配，
每轮循环末尾又 `curves.push(curve)`，导致 `curves.length == 2 * curveCount`，
且**前后两半是同一对象引用**。实测 `doUpdateParameters` 只走前 `curveCount` 条，
`baseSegmentIndex` / `segmentCount` 与 JSON 逐条一致、points 值正确，
**不影响求值**。看到 `length` 翻倍不要当成元凶去动 vendor 文件。

## 23. 参数型互动区（点局部换装）：命中判定的三个坑（2026-10-25，version 1.10.17）

需求形态：点画面上的鞋/丝袜/衣角/戒指，切换对应 Cubism 参数两态，**不播 motion**
（播动作会把姿态一起改掉）。数据侧 = 「参数 → 驱动 drawable 索引」映射，
热区 = 这些 drawable 顶点包围盒的并集。

### 坑一：面积最小者的命中规则会被极小盒劫持

命中判定若实现成「落进盒子的候选里取 `area` 最小者」（最具体优先，这是对的），
则**只驱动 1 个 drawable 的参数**会成为灾难：它的包围盒极小，
于是任何落在大盒子里的点都被它以「面积最小」抢走。

实测：`Paramring`（1 个 drawable，`w=0.293 h=0.175 area=0.051`）
比第二名 `Cloth1`（area=1.68）小 33 倍 →
`__costumeScreenOf` 反解出的 ShoseOff / Stock1 / Cloth1 三个屏幕点**全部命中 Paramring**。

```js
// 错：只挡「严格退化成一点」
if(!(w>1e-3)||!(h>1e-3)) continue;
// 对：扩张到最小可点击尺寸，中心不变
const COS_MIN_SIDE=0.5;
if(w<COS_MIN_SIDE){ const c=(x0+x1)/2; x0=c-COS_MIN_SIDE/2; x1=c+COS_MIN_SIDE/2; w=COS_MIN_SIDE; }
if(h<COS_MIN_SIDE){ const c=(y0+y1)/2; y0=c-COS_MIN_SIDE/2; y1=c+COS_MIN_SIDE/2; h=COS_MIN_SIDE; }
```

**为什么扩张而不是丢弃**：丢弃会让戒指/项圈彻底点不到，等于砍功能。
扩张后它仍是最小者、优先级最高，但只在**自己周围**获胜，不再劫持远处的大热区。
阈值取「其余参数 min(w,h) 最小值的一半」（实测其余 ≥1.05 → 取 0.5）。

### 坑二：`__costumeScreenOf` 返回的是几何中心，不是真实命中点

判命中正确性是分两层的，混用会得出错误结论：

| 函数 | 返回 | 用途 |
|---|---|---|
| `boxOf(param)` | V 空间包围盒 | 搜索范围 |
| 屏幕中心 `(x0+x1)/2` | **几何中心** | **不能**直接当命中点用 |
| 区域内逐点 `hitAt(x,y)` | 真实命中者的 id | 这才是判据 |

实测：`ScreenOf('ShoseOff')` 报 `n=238`（区域内 238 点命中它），
但把返回的几何中心喂给 `hitAt` → 得到 `Paramring`。因为中心可能落在别的参数地盘。
**验收必须在区域内逐点扫、统计每个 id 被命中多少次**，再取一个真正命中的点。

```js
// 正确做法：区域内逐点扫，找第一个真正命中目标的点
for (let y = box[1]; y <= box[3]; y += 3)
  for (let x = box[0]; x <= box[2]; x += 3){
    const h = hitAt(x, y);
    if (h && h.id === want) { point = [x, y]; }
  }
```

### 坑三：换装改的是顶点，不是不透明度

判「参数写入有没有到达渲染」不能用不透明度：换装多是把部件**挪走/缩放**，
opacity 可能全程为 1。用顶点包围盒（`getDrawableVertexPositions` 求 w/h/x0/y0）
才看得见变化。

实测 ShoseOff `0→1`：drawable 460 `w 2.4017→2.4449`、`x0 -9.9973→-10.2100`、
`y0 -1.2680→-1.3589`；drawable 461 同步。变化集合与 `param_drawables` 的交集
正是 `[460,461]`。
之前"pins lo vs hi 逐 drawable 比对 0 差异"的矛盾就是这么来的——比的是透明度。

### 验收四层（缺一不可，全部走产品入口）

1. **数据层**：参数表与 drawable 映射能加载，条数与驱动数都 > 0
2. **热区**：能列出热区，每个都有可点面积
3. **写入到达渲染**：toggle 后驱动部件**顶点**确实变化（非 opacity）
4. **真实点击**：用 CDP `Input.dispatchMouseEvent` 派发 mousePressed + mouseReleased
   （**不调内部 toggle 函数**），断言参数 `lo→hi` 且 `state.currentGroup` 未变成
   动作组（否则说明点歪进了动作分支）

只在第 4 层才能发现「函数好用但用户点不到」——`onUp` 里的接续顺序
（命中判定 → 动作分支）写反了，前三层全绿而真实点击无效。

## 24. 跨动作持久状态 ≠ 回落姿势：分表、离开动作时捕获、唯一 LOW 出口（2026-10-27，version 1.10.19）

### 先分三类，混在一起必然误伤

| 类 | 例 | 生命周期 | 新动作能否接管 |
|---|---|---|---|
| 装扮状态 | 鞋/丝袜/衣服/戒指 | 直到用户再次互动 | 否（用户操作优先） |
| 动作产生的独立状态 | 吻痕/口红印/身体印记 | 直到动作明确改成另一非零态/显式清除 | 否 |
| 姿势/表情 | 手臂、身体角度、眨眼、口型 | 当前动作/回落阶段 | **是** |

`pose_keep` 只解决「动作末帧 → 呼吸 idle」的姿势塌陷，不能拿来做永久状态；
把 A 有、B 没有的所有非零参数都 pin 住，会把旧手臂/身体姿势拖进 B，造成部件错位。

### 数据判据：白名单，不按名称猜

- 装扮状态只认已验证的 `costume_params.json`，且 `n_drawables>0`；
- 动作状态只认逐动作实证后的显式白名单；**禁止**模糊匹配 `Eye* / Heart*`
  （会混入眨眼、眼球、物理参数）；
- 只把动作末值 `abs(v)>0.5` 记录进 `state_set_by_group`；普通动作填充的 0 曲线不清状态；
- `state_params/state_set_by_group` 与 `pose_keep` 分表，前端 `restTick` 豁免 `state_params`。

### 时机：不能在 play(A) 时预写末值

吻痕动作内部有自己的 0→非零过渡。若 `play(A)` 时直接把最终值 7 写进 pin，吻痕会瞬间出现，
局部过渡被绕掉。正确出口：**离开 A 的那一刻**（直接 A→B / A 回落 idle）从 coreModel
读取当时实际值，非零才写进 `__actionStatePinsByModel[skinKey]`。

### 唯一 LOW ticker

`loadParameters()` 在模型 update 末尾覆盖参数，所以状态重申必须在 app ticker 的 LOW 优先级
（update 后、render 前）。全模型只许一个 `app.__statePinTick`：

1. 先写 action-state pins；
2. 后写 costume pins（用户主动互动优先）；
3. `pose_keep` 仍走自己的回落姿势出口。

真实事故：同一页面曾有两份逐字相同的 costume ticker，参数面板又注册第三份——每帧写 3 遍，
不仅浪费，还让“谁最后写”变得依赖注册顺序。修法不是加 guard，而是合并成唯一出口。

### 验收（缺一不可）

- 动作开播早期状态仍低值（证明没有提前 pin 末值）；
- 动作完成捕获后，用户直接选普通动作，独立状态保持；
- 新动作 `ParamAngleX` 等姿势参数仍变化（证明没有把旧姿势锁死）；
- 真实点击装扮热区后连切两动作仍保持；
- 同一个 core 写 0 干扰做 A/B：stateTick 开→恢复，移除→保持 0（阴性对照有区分力）；
- 静态断言 `__statePinTick=true` 且旧 `__costumePinTick=false`。

⚠️ headless SwiftShader 下动作时间轴可能慢于 wall-clock 回落定时器，曲线未到状态段就被抢先回落。
探针可重播并打印 RETRY 做仪器稳定化，但不能据此断言真 GPU 用户环境也有同样低帧率缺陷。
