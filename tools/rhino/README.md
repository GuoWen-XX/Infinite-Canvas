# Rhino 视口一键直推开卷画布 (MeansCanvas Rhino Bridge)

## 快捷运行宏命令

```text
-_RunPythonScript "D:/Github/Infinite-Canvas/tools/rhino/infinite_canvas_rhino.py"
```

## Rhino 配置步骤

### 方式一：设置命令行别名（最推荐，平时敲 `IC` 回车即可）
1. 打开 Rhino 3D；
2. 点击顶部菜单 **文件**（或 **工具**）-> **选项 (Options)**；
3. 在左侧列表找到并点击 **别名 (Aliases)**；
4. 点击右侧的 **新建 (New)**：
   - **别名 (Alias)** 填入：`IC`
   - **命令 (Command)** 填入：
     ```text
     -_RunPythonScript "D:/Github/Infinite-Canvas/tools/rhino/infinite_canvas_rhino.py"
     ```
5. 点击 **确定** 保存。
6. 平时使用：在 Rhino 建模过程中，调整好视角后，直接敲 `IC` 并回车，当前活动视口就会瞬间推送到画布中央生成图片卡片。

### 方式二：添加到 Rhino 工具栏按钮
1. 按住键盘 **Shift 键 + 鼠标右键** 点击 Rhino 工具栏任意位置；
2. 在弹出的「编辑工具列按钮」窗口中：
   - **左键命令 (Left click)** 填入：
     ```text
     -_RunPythonScript "D:/Github/Infinite-Canvas/tools/rhino/infinite_canvas_rhino.py"
     ```
3. 保存后点击按钮即可推流。
