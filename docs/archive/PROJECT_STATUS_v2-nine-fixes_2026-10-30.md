<!-- §9.3 九个系统性根因修复（v2 静态立绘管线，已闭环） | 原第 344-371 行 | 外迁日期 2026-10-30 -->

### 9.3 九个系统性根因修复 ★教训（全部代码级、零逐角色参数）
1. 无 mesh 整图部件**双重 Y 翻转** → root 背景层颠倒。修：`arr = A[rect.y : rect.y+h]`。
2. Spine atlas 页纹理需 **`flip=True`**（运行时按行0=顶采样）。
3. Windows 分离进程 stdout 默认 GBK，`print('✓')` 抛错致全量**假失败** → `sys.stdout.reconfigure('utf-8')` + 子进程 `PYTHONIOENCODING=utf-8`。
4. `layout_all` **root scale 只乘子层未乘 root 自身** → 层间比例错。修：局部空间纯 anchor 数学 + 仿射映射世界 + 自身 scale 绕 pivot（负=镜像）+ root 屏幕适配 scale 归一为 1。
5. 无 mesh 部件**误用 `mRawSpriteSize` 当画框** → i404 型视差背景带（记录切分前原图尺寸）被压窄留黑洞。修：按 UI Image 语义 textureRect 拉伸铺满 RectTransform；mesh 部件才用 frame。
6. `rasterize_mesh` **把内容钳死在画框内** → mesh 顶点合法越框的皮肤（kuersike_rw 头部伸出框顶 713px）被裁头、纹理矩形露缝。修：按内容实际 AABB 输出（±2~3 倍框安全钳），越框部分由 render() 仿射照常映射。
7. **不读 `GameObject.m_IsActive`** → 游戏里**关着**的层被一律画上去：`shadow` 纯黑剪影压在头上
   （用户报的"头黑"）、`shop_hx`/`*_shophx` "NOT ABLE TO DISPLAY" 遮挡条贴在身上、
   `chicheng_alter_rw1..4` 四份备用画法叠成四个身子。修：`parse_painting` 把「自身 + 全祖先激活」
   算在部件的 `active` 字段上，`compose` 只画开着的层；**`face` 槽豁免**（恒关、运行时才激活，
   是 §48 叠层的输入）、**过滤后一层不剩则原样保留**（4 张全层关闭的皮肤清空=静默失败）。
   全库 4488 张命中 125、画面真会变 48、逐字节不变 73（白条早被 `is_lighting` 挡着）。见 **§55**。
8. **`canvas.paste(img, box, img)` 把 alpha 通道缩放两次**（Pillow 对 RGBA 蒙版的行为，
   文档原话 "scaling the alpha channel twice"）→ 铺在空画布上时 `a → a²/255`，
   **全部 4500 张的柔边系统性偏淡**（实测在盘成品 99.81% 半透明像素命中 a²/255）；
   并连带打出 1px 透明缝（用户报的"白雪皮肤2 脖子一条细空线"）、把叠脸门控的
   `alpha>=250` 读数压低 → `gezi_2` **正式产物一直在发被误叠的错表情**。
   修：`over()` = `Image.alpha_composite`（标准 source-over）。见 **§114** / **WF-29**。
9. **画布只取 `max(x+w)`/`max(y+h)`、从不减 min** → 世界框落在负侧的部件被 paste 静默裁掉
   （`beier_rw` 丢该层 15%、`jinluhao_2` **整张画下半截没了**、`i404` 只剩偏在一角的残片）。
   修：`canvas_frame()` = **所有节点框 ∪ 各层落笔框** 的并集，min 钳在 0。
   ⚠ 两个反例都进了判据：为省内存把容器 rect 从 max 侧剔掉 → `baixue` 画布**变窄**反而新裁
   2,771 像素；只按"负侧框"筛候选 → 影响面低估为 19 张（抽样实测 **2.0% ≈ 90 张**）。见 **§114**。
> 结论再次印证：游戏数据自洽，所有错位都是解析姿势不对。第 8/9 条补一句：**"姿势"也包括
> 用什么库函数落笔、画布边界取在哪**——数据读对了，落盘算子错一样全库错，且**不报任何错**。
> （完整明细含文件行号与验证样本，见 `docs/archive/PROJECT_STATUS_历史归档.md` 末尾「完整明细存档」。）

