# 无限画布大工程演进方案与架构实现规划 (Implementation Plan)

本方案针对用户提出的系统开销优化诉求及 5 项核心重大工程特性，全面吸收 **Jaaz Magic Canvas (`11cafe/jaaz`)** 的交互设计精髓，并将**参考图氛围 JSON 提取**深度收敛至 **Agent 对话体系**，进行架构解耦设计、交互细节推演与技术路径规划。

> [!NOTE]
> **已先行完成的基础优化**：
> 画布连线原本携带的无限循环流动动画（`.link-pulse` 的 `linkFlowPulse` 关键帧动画）已设置为 `animation: none !important;`，连线保留优雅清晰的静态虚线风格，彻底消除了大规模连线下的 SVG 持续重绘，立即可见地降低了 CPU/GPU 占用。

---

## 一、用户需求重构与 5 大核心目标全景

### 目标 1：Sketch 涂鸦构思与几何系统（Jaaz 风格原生集成）
- **底部居中微型悬浮 Dock 栏**：
  - 工具集合：`选择 (V)`、`矩形 (R)`、`圆形/椭圆 (O)`、`箭头 (A)`、`直线 (L)`、`自由画笔 (P)`、`文本标注 (T)`、`图片快速插入 (I)`、`抓手平移 (H / 空格)`；
  - 极简性冷淡灰阶质感，单色线性矢量图标，保持高沉浸感。
- **左侧悬浮属性检查面板 (Context Property Inspector)**：
  - 选中任何画笔笔迹或几何形状时自动浮现：
    - **Stroke (描边色)**：预设低饱和建筑色系（黑、深灰、纸白、砖红、深蓝、森林绿、橙褐）+ 自定义拾色器；
    - **Background (填充色)**：透明/无填充开关 + 色块选择；
    - **Stroke width (线条粗细)**：细 (2px)、中 (4px)、粗 (8px)；
    - **Opacity (不透明度)**：0% - 100% 平滑滑块；
    - **Layers (图层层叠调序)**：置底 (Send to back)、下移一层 (Send backward)、上移一层 (Bring forward)、置顶 (Bring to front)；
    - **Actions (快速动作)**：复制 (Duplicate)、水平/垂直翻转、删除。
- **选中态变换手柄与快捷药丸**：
  - 对象选中时显示 8 个变换手柄（四角与四边缩放）+ 顶部旋转手柄；
  - 选中对象底边浮现快速操作药丸：`Add to chat ⌘↵`（或 Ctrl+Enter），一键将选中的手绘涂鸦、图形或图片节点投送至右侧 Agent 对话面板，直接展开图生图与创意推敲。

---

### 目标 2：Agent 对话原生内置“提取参考图氛围 JSON”
- **设计演进原则**：
  - 拒绝在画布图片卡片上堆砌复杂弹窗或破坏画布轻盈感；
  - **直接在右下角/侧边的 Agent 对话面板实现**，与现有的 `agentContextBar`（参考上下文）深度融合。
- **交互流程**：
  1. 用户在画布上选中图片节点（或在 Agent 对话中输入 `@` 引用图片），Agent 底部参考上下文栏即时点亮；
  2. 参考栏操作区常驻按钮：`[提取空间氛围 JSON]`（与“反推提示词”并列）；
  3. 点击后，Agent 自动附带该参考图片，调用多模态视觉模型（如已打通的 `gemini-cli` / `gemini-2.5-flash` / `gemini-2.5-flash-lite`）；
  4. 注入用户固化的 **20 年经验顶级室内设计师与建筑摄影师专属 Prompt**，严格输出 6 大维度标准 JSON；
  5. Agent 回复消息体内提供双快捷动作：
     - `[复制 JSON]`：一键拷贝纯净结构化数据；
     - `[生成提示词节点至画布]`：自动将氛围与空间拆解提炼为高质量生图 Prompt，在画布中选定图片旁生成提示词节点并自动完成 DAG 连线。

---

### 目标 3：多选 Ctrl+G 虚线包裹群组 (ComfyUI-Style Grouping)
- **快捷成组**：框选/多选任意类型的节点后按 `Ctrl+G`，自动计算所有选中节点的包围盒（Bounding Box），向外拓展预留 padding，生成带标题栏与虚线边框的空间包裹框；
- **联动平移**：拖拽群组标题栏或边框时，组内所有节点等量平移，外接连线平滑跟随；组内单独拖动某个子节点仅移动自身；
- **无损解散**：按 `Ctrl+Shift+G` 或删除群组时，仅销毁外层包裹框，内部节点与连线 100% 完好无损保留。

---

### 目标 4：多选对齐与拓扑自动整理 (Alignment & Auto-Layout Hub)
- **多选对齐悬浮条**：多选 2 个及以上节点时，顶部浮现胶囊操作条：
  - 左对齐、右对齐、顶对齐、底对齐；
  - 水平等间距分布、垂直等间距分布。
- **拓扑自动整理 (Auto Tidy)**：
  - 基于节点间连线的有向无环图（DAG），计算层级拓扑（Layer 0: 输入源 -> Layer 1: 处理与生成 -> Layer 2: 放大与产出）；
  - 消除重叠遮挡与交叉连线，平滑补间动画重排至清晰整洁的流水线格局。

---

### 目标 5：Rhino 视口一键直传桥接 (Rhino Viewport to Canvas Bridge)
- **核心模式（Rhino Python 宏脚本）**：
  - 提供单文件脚本 `infinite_canvas_rhino.py`，支持拖入 Rhino 顶部工具栏形成一键按钮（或快捷命令 `IC`）；
  - 点击后在 Rhino 内部调用 `-_ViewCaptureToFile` 导出高保真无网格截图，通过纯 Python `urllib` 发送 `POST /api/canvas/rhino-capture`；
  - 画布端通过 SSE / 广播实时接收，在当前视口中心自动创建“Rhino 视口”图片节点；
- **备选模式（剪贴板无感智能捕获）**：
  - 在 Rhino 按快捷键复制视口到剪贴板，切回画布按 `Ctrl+V` 或点击导入，自动转为节点。

---

## 二、详细技术实现架构

### 1. Sketch 系统与 Jaaz 模式深度实现

#### 1.1 架构分层
- 在画布 `#board` 的 `#world` 世界容器内建立专用矢量图层 `<svg id="sketchLayer" class="sketch-layer">` 与 HTML 浮动交互层：
  - **坐标系契约**：所有矢量点 `(x, y)` 均实时换算为画布世界坐标 `worldCoord = (screenCoord - pan) / zoom`；无论画板如何无限缩放或平移，笔迹、几何形状与节点始终严格重合；
  - **矢量数据对象模型**：
    ```javascript
    {
      id: "elem_xxxx",
      type: "path" | "rect" | "ellipse" | "arrow" | "line" | "text",
      x: 100, y: 150, w: 200, h: 120, // 包围盒尺寸
      rotation: 0,                   // 旋转角度
      stroke: "#2a2520",             // 描边颜色
      strokeWidth: 3,                // 线宽
      fill: "transparent",           // 填充色
      opacity: 1.0,                  // 不透明度
      points: [ ... ],               // 笔画点序列（手绘）
      pathData: "M ...",             // SVG 贝塞尔平滑路径
      zIndex: 5
    }
    ```

#### 1.2 底部悬浮 Dock (`#canvasToolDock`)
- 位于画布视口底部居中（`bottom: 24px; left: 50%; transform: translateX(-50%)`）；
- 按钮状态机：`activeTool = 'select' | 'rect' | 'ellipse' | 'arrow' | 'line' | 'pen' | 'text'`；
- 快捷键映射：`V` (Select), `R` (Rect), `O` (Ellipse), `A` (Arrow), `L` (Line), `P` (Pen), `T` (Text), `H / Space` (Pan)。

#### 1.3 左侧悬浮属性检查面板 (`#sketchPropertyInspector`)
- 当选中手绘笔画或几何对象时以极简卡片形式浮现于画布左上侧；
- 包含极简色彩矩阵（7 种性冷淡色阶 + 拾色器）、填充透明度切换、线宽 3 档（2px/4px/8px）、Opacity 滑块、以及 Layers 4 个层叠控制按钮；
- 属性调整实时响应并记录进撤销栈（Undo/Redo）。

#### 1.4 `Add to chat ⌘↵` 闭环联动
- 选中任何 Sketch 元素、框选组合或图片节点时，对象边框底端浮现胶囊药丸 `[Add to chat ⌘↵]`；
- 点击或按 `Ctrl+Enter`：
  1. 若选中的是手绘草图/几何图形：自动在前端将该包围区域栅格化为带白底的高清 PNG Base64；
  2. 调用 `CanvasAgent.addReferencedNode(...)` 自动将当前草图加入 Agent 参考上下文；
  3. 自动展开右侧 Agent 对话面板并聚焦输入框，用户直接输入创意（如“参考这个空间平面构思，生成一张现代侘寂风客厅效果图”），直接触发 AI 生图！

---

### 2. Agent 原生“提取参考图氛围 JSON”实现

#### 2.1 固化的 20 年室内设计与建筑摄影师 Prompt
在 Agent 处理该指令时，完全注入用户已固化的标准规范：
```markdown
You are a top-tier interior designer and architectural photographer with 20 years of experience. You excel at deconstructing spaces through materials, lighting, and cinematic language. Please analyze the reference image I provide and strictly follow the JSON format below to output the analysis results. Do not miss any details; ensure that the scene can be reproduced 1:1 in AI drawing through your description.

Output Format: JSON Code Block only.
```

#### 2.2 严格固化的 6 大维度 JSON 契约
```json
{
  "style_and_atmosphere": {
    "design_style": "e.g., Japandi, Industrial Loft, Mid-century Modern",
    "era_vibe": "e.g., 2020s Contemporary, 1960s Retro, Futuristic",
    "emotional_mood": "e.g., Serene, Moody, Clinical, Inviting"
  },
  "composition_and_perspective": {
    "visual_center": "Where is the visual focal point? e.g., The central red sofa, the distant window view",
    "perspective_type": "e.g., 1-Point Perspective, 2-Point Perspective, Isometric",
    "framing_composition": "e.g., Rule of Thirds, Symmetrical, Frame-within-a-frame",
    "depth_layering": "Describe the relationship between foreground, midground, and background. e.g., Blurred plants in foreground, dining table in midground, kitchen in background"
  },
  "camera_parameters": {
    "shot_type": "e.g., Wide Angle, Medium Shot, Close-up",
    "camera_angle": "e.g., Eye-level, Low Angle, High Angle",
    "lens_characteristics": "e.g., 35mm (Standard Wide), 85mm (Compression), Fisheye",
    "depth_of_field": "e.g., f/16 (Deep focus, all sharp), f/1.8 (Shallow depth of field/Bokeh)"
  },
  "lighting_physics": {
    "primary_source": "e.g., Natural sunlight from large window (left)",
    "light_quality": "e.g., Soft diffused, Hard directional, Dappled shadows",
    "color_temperature": "e.g., 6000K (Daylight Cool), 2700K (Warm Tungsten)",
    "volumetric_effects": "Are light beams/dust particles visible? (God rays, Haziness)"
  },
  "spatial_content_breakdown": {
    "architectural_shell": {
      "ceiling": "e.g., Exposed concrete beams, Drop ceiling with cove lights",
      "walls": "e.g., White plaster, Wood slats, Brick texture",
      "flooring": "e.g., Polished concrete, Chevron wood floor"
    },
    "key_objects": [
      {
        "object": "Describe the main furniture",
        "material": "Detailed material, e.g., Distressed brown leather",
        "color": "Hex code or specific name",
        "position": "Location in frame"
      },
      {
        "object": "Describe secondary decor",
        "material": "e.g., Brushed brass",
        "position": "Location"
      }
    ]
  },
  "color_palette_extraction": {
    "dominant_hues": ["Dominant Color 1", "Dominant Color 2"],
    "accent_hues": ["Accent Color 1"],
    "global_tone": "e.g., Desaturated, High Contrast, Pastel"
  }
}
```

#### 2.3 Agent 端界面改造与闭环动作
- 在 `static/canvas.html` 的 `#agentContextBar` 内新增操作按钮：
  ```html
  <button id="agentExtractAtmosphereBtn" class="agent-context-action-btn" type="button" title="提取空间氛围 JSON (20年设计摄影大师分析)">
      <i data-lucide="palette" class="w-3.5 h-3.5"></i>
      <span>提取空间氛围 JSON</span>
  </button>
  ```
- 在 `static/js/canvas-agent.js` 中新增 `handleExtractAtmosphere()`：
  - 校验当前选中的图片引用；
  - 携带图像数据及上述 Prompt 投递多模态视觉接口；
  - 在输出的 JSON 代码块下方动态挂载：
    - `[复制 JSON]`：直接写入剪贴板；
    - `[生成提示词节点至画布]`：从 JSON 中提炼精炼的 Prompt，调用 `addPromptNodeToCanvas(...)`，在原图片右侧生成提示词节点并自动连线。

---

### 3. 多选 Ctrl+G 虚线群组实现

- **数据契约**：
  ```javascript
  {
    id: "grp_xxxx",
    type: "frame_group",
    title: "空间功能推敲组",
    x: 100, y: 80, w: 680, h: 460,
    color: "rgba(201, 123, 90, 0.08)",
    borderColor: "var(--line-strong)",
    borderStyle: "dashed",
    items: ["node_1", "node_2", "node_3"]
  }
  ```
- **交互边界**：
  - 拖拽群组标题栏或虚线框时，组内所有 `items` 节点产生等量 `(dx, dy)` 位移，连线随之平滑跟随；
  - `Ctrl+Shift+G` 或删除边框时，只移除 `frame_group` 容器，内部节点与连线 100% 保持不动。

---

### 4. 多选对齐与拓扑自动整理实现

- **悬浮对齐胶囊 (`#selectionAlignHub`)**：
  - 选中 2 个及以上节点时自动在选区上方悬浮展现；
  - 提供：左对齐、右对齐、顶对齐、底对齐、水平等间距、垂直等间距；
- **拓扑自动整理 (Auto Tidy)**：
  - 基于 Kahn 拓扑排序算法，根据连线关系分层计算排布：输入层 -> 处理层 -> 输出层；
  - 消除交叉，平滑补间过渡。

---

### 5. Rhino 视口直传桥接实现

- **后端路由**：`routers/canvas.py` 增设 `POST /api/canvas/rhino-capture`；
- **前端广播**：通过广播或 SSE 触发 `addNode('image', { url: ..., name: 'Rhino 视口' })`；
- **Rhino 端**：提供即拷即用的纯 Python 宏脚本 `infinite_canvas_rhino.py`，1 秒配置完成。

---

## 三、推荐分步实施路线 (Milestones)

按照奥卡姆剃刀与 Karpathy 闭环验证军规，分 3 阶段稳步推进：

| 阶段 | 交付核心特性 | 验证标准 |
| :--- | :--- | :--- |
| **Phase 1: Agent 空间氛围提取与节点连线闭环** | **特性 2（Agent 原生提取参考图氛围 JSON 按钮 + 复制 + 生成提示词节点连线）** | 在画布选中图片，点击 Agent 提取氛围按钮，成功调用视觉大模型输出 6 大维度 JSON；点击生成提示词节点可在画布中生成并连线。 |
| **Phase 2: 编排效率核心 (群组与对齐整理)** | **特性 3（Ctrl+G 虚线包裹群组）** + **特性 4（多选对齐与拓扑自动整理）** | 多选按 Ctrl+G 成组，拖拽标题整组平移，Ctrl+Shift+G 解散；多选左/右/顶/底对齐及自动拓扑整理实测通过。 |
| **Phase 3: 创意表现层 (Jaaz 风格手绘与 Rhino 桥接)** | **特性 1（底部悬浮 Dock + 左侧属性浮窗 + 手绘/几何图形 + Add to chat 药丸）** + **特性 5（Rhino 视口一键直传）** | 底部 Dock 工具切换流畅，自由手绘笔迹世界坐标对齐且持久化落盘，可一键 Add to chat；Rhino 脚本一键直传视口图片入画。 |
