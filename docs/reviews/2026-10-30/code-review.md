# Infinite-Canvas 代码审查报告

- 审查日期：2026-10-30（Asia/Shanghai；审查开始于 10 月 29 日）。
- 仓库：GuoWen-XX/Infinite-Canvas。
- 基线：默认分支 `zcode/iteration-01`，提交 `2fd89fb3c7555a05a8a3f6352fe67dc5464fcee2`。发布报告前重新检查，基线未变化。
- 交付范围：审查结论与隔离复现脚本；本 PR 不包含业务代码修复。
- 总结：确认 **1 项 P1、6 项 P2**。建议优先修复经典画布冲突后的覆盖行为，再处理 Skill 元数据和更新跟踪。现有测试通过不足以证明这些链路正确。

## 范围与方法

读取仓库目录树、历史审查修复交接、CI 配置、全部 4 个现有 Python 测试文件，并重点审查 main.py 中的画布持久化、Skill CRUD/导入/升级/编译、Codex 图片通道、存储 URL 与更新逻辑，以及经典画布、智能画布和 Skill 管理器的对应 JavaScript。启动脚本、安装依赖清单也纳入核查。仓库树中未发现 AGENTS.md。

Git 克隆及归档下载未能完成，已停止本次挂起的下载进程；通过 GitHub 连接器按固定提交读取上述源码到工作区。因此这是关键路径代码审查，不宣称逐行覆盖整个仓库，也不是渗透测试或真实服务验收。以下问题均有当前源码依据；不把历史报告中的问题直接当作当前缺陷。

## 发现清单

| 编号 | 优先级 | 问题 | 验证 |
|---|---|---|---|
| R1 | P1 | 经典画布在 409 后仅更新版本号重试，覆盖远端新增节点 | 原始 JS 函数 + 模拟服务器 |
| R2 | P2 | Skill 编辑将正文当成整个文件保存，丢失 frontmatter | 真实后端函数 + 临时目录 |
| R3 | P2 | GitHub Skill 安装把提交 SHA 当成更新跟踪 ref | 真实安装/检查函数 + 模拟 GitHub |
| R4 | P2 | 安装依赖遗漏 PyYAML，样式丢失且编辑在写入后报错 | 模拟 yaml 缺失执行真实函数 |
| R5 | P2 | Codex 参考图不接受系统产生的自定义存储 URL | 真实 URL/参考图函数 + 临时文件 |
| R6 | P2 | 元数据改名不递增版本，旧编辑页面保存回滚标题 | 真实元数据/保存函数顺序调用 |
| R7 | P2 | Skill 编辑未保留 variant ID，已有画布样式选择失效 | 真实编辑/编译函数 + UI 等价载荷 |

P1 表示应优先处理的数据丢失风险；P2 表示有明确触发条件的功能错误。R2 和 R7 分别对应元数据覆盖与变体标识丢失，修复其中一个不能自动修复另一个。

## R1 [P1] 不应在冲突后给旧节点集合换上新版本号重存

**位置：** [static/js/canvas.js:1506–1509](https://github.com/GuoWen-XX/Infinite-Canvas/blob/2fd89fb3c7555a05a8a3f6352fe67dc5464fcee2/static/js/canvas.js#L1506-L1509)，重试调度见 [1533–1539](https://github.com/GuoWen-XX/Infinite-Canvas/blob/2fd89fb3c7555a05a8a3f6352fe67dc5464fcee2/static/js/canvas.js#L1533-L1539)。

两页同时编辑同一经典画布：B 先保存新增节点，A 持有旧版本且存在本地修改。A 收到 409 时，`localCanvasDirty` 分支只把 `lastCanvasUpdatedAt` 更新成服务器版本，保留原来的本地节点并安排重试。第二次 PUT 使用新版本号和旧节点集合，通过后端乐观锁检查，B 的新增节点被整份覆盖。后端事务锁无法解决客户端主动使用新版本号提交旧快照的问题。

**复现证据：** `review_conflict_probe.cjs` 从仓库源码直接提取 `saveCanvas()`，模拟远端版本 2 含 `remote-added`、本地版本 1 含 `local-added`。实际请求版本依次为 `[1,2]`，最终远端只剩 `local-added`。这是函数级复现，未运行浏览器或真实多人服务器。

**修复建议：** 冲突时保留本地草稿，进行基于基线的合并或让用户明确选择；未解决冲突前不能自动替换 base 版本号重存。不要简单采用节点并集，否则删除操作会复活。

**回归验收：** 两客户端分别新增、修改和删除不同节点，制造 409；验证远端改动不丢、本地草稿可恢复，且删除语义正确。

## R2 [P2] 编辑正文必须保留原 SKILL.md frontmatter

**位置：** [main.py:19887–19891](https://github.com/GuoWen-XX/Infinite-Canvas/blob/2fd89fb3c7555a05a8a3f6352fe67dc5464fcee2/main.py#L19887-L19891)；前端载荷见 [skill-manager.js:155–162](https://github.com/GuoWen-XX/Infinite-Canvas/blob/2fd89fb3c7555a05a8a3f6352fe67dc5464fcee2/static/js/skill-manager.js#L155-L162) 和 [184–191](https://github.com/GuoWen-XX/Infinite-Canvas/blob/2fd89fb3c7555a05a8a3f6352fe67dc5464fcee2/static/js/skill-manager.js#L184-L191)。

编辑器显示“仅替换正文”，读取的是 `detail.body`，保存也只提交正文。后端却先以 `w` 模式覆盖整个 SKILL.md，再从这个已丢失头部的文件重写 variants。普通编辑一次就会移除 name、description、version、license 等原有 frontmatter，界面名称退回目录 ID，版本和许可信息丢失。

**复现证据：** R2 探针创建含上述元数据的 Skill，按 UI 载荷编辑后，frontmatter 只剩 `variants`。

**修复建议：** 读取原文件，将正文和原 frontmatter 分开，合并 variants 后一次性原子写入。明确接口 content 是正文还是完整文件，保持前后端一致。

**回归验收：** 通过真实编辑页执行“打开→不改→保存”及修改正文，确认所有非编辑字段保持原值。

## R3 [P2] 固定安装版本与更新跟踪分支必须分别保存

**位置：** [main.py:20213–20218](https://github.com/GuoWen-XX/Infinite-Canvas/blob/2fd89fb3c7555a05a8a3f6352fe67dc5464fcee2/main.py#L20213-L20218)；上游来源见 [20191](https://github.com/GuoWen-XX/Infinite-Canvas/blob/2fd89fb3c7555a05a8a3f6352fe67dc5464fcee2/main.py#L20191)、[19946–19964](https://github.com/GuoWen-XX/Infinite-Canvas/blob/2fd89fb3c7555a05a8a3f6352fe67dc5464fcee2/main.py#L19946-L19964)；检查入口见 [20290–20297](https://github.com/GuoWen-XX/Infinite-Canvas/blob/2fd89fb3c7555a05a8a3f6352fe67dc5464fcee2/main.py#L20290-L20297)。

前端安装提交预览得到的 SHA，不提交预览分支 ref。安装将 SHA 传给下载/解析函数，该函数返回的 `info.ref` 就是输入 SHA；元数据把它持久化为 ref。检查更新随后继续查询此固定 SHA，得到原提交并显示“已是最新”，即使源分支已经更新。升级也沿用这一 ref；不能跟随分支前进。

**复现证据：** R3 探针模拟 GitHub 下载和提交解析，执行真实安装及检查函数。源分支设为新提交 B，安装提交为 A，落盘 ref=A，检查仍返回 A、`up_to_date=true`。GitHub 网络响应为模拟，未声称在线导入验收。

**修复建议：** 将 `tracking_ref`（预览时解析出的默认/指定分支）与 `commit_sha` 分开传递、验证和保存；下载安装仍固定 SHA，更新检查解析 tracking_ref。升级后保留 tracking_ref，不覆盖成 SHA。

**回归验收：** 分支 A→B→C 连续推进，安装 A 后能发现 B，升级 B 后仍能发现 C；同时覆盖非默认分支。

## R4 [P2] 用户安装清单缺少 Skill 样式所需的 PyYAML

**位置：** [requirements.txt:11–17](https://github.com/GuoWen-XX/Infinite-Canvas/blob/2fd89fb3c7555a05a8a3f6352fe67dc5464fcee2/requirements.txt#L11-L17)、[main.py:19595–19596](https://github.com/GuoWen-XX/Infinite-Canvas/blob/2fd89fb3c7555a05a8a3f6352fe67dc5464fcee2/main.py#L19595-L19596)。CI 在 [tests.yml:16](https://github.com/GuoWen-XX/Infinite-Canvas/blob/2fd89fb3c7555a05a8a3f6352fe67dc5464fcee2/.github/workflows/tests.yml#L16) 额外安装 pyyaml，用户安装脚本只安装 requirements（Windows 额外安装 uvicorn standard）。

全新环境按清单安装后，yaml 导入失败被吞掉。创建 Skill 的 fallback 不写 variants，用户输入的样式会丢失；编辑器每次保存都发送 variants 数组，即便是空数组，后端先覆盖正文，再调用必须依赖 yaml 的重写函数并返回 500。因此不仅功能不可用，还存在“报错但文件已经改变”的不一致。

**复现证据：** R4 将 `_skill_yaml` 设置为 None，真实创建成功但文件无 variants；真实编辑返回 500，同时文件已经变成提交的正文。

**修复建议：** 将 PyYAML 加入正式运行依赖并统一 CI/用户安装路径；编辑在验证依赖、解析和构造最终文件成功后再提交写入。

**回归验收：** 全新环境仅按正式安装清单安装，执行带样式创建、编辑保存、重新读取；对缺依赖失败验证原文件不变。

## R5 [P2] Codex 参考图解析遗漏自定义存储地址

**位置：** [main.py:5806–5810](https://github.com/GuoWen-XX/Infinite-Canvas/blob/2fd89fb3c7555a05a8a3f6352fe67dc5464fcee2/main.py#L5806-L5810)；合法 URL 产生及解析见 [7304–7314](https://github.com/GuoWen-XX/Infinite-Canvas/blob/2fd89fb3c7555a05a8a3f6352fe67dc5464fcee2/main.py#L7304-L7314)、[7350–7355](https://github.com/GuoWen-XX/Infinite-Canvas/blob/2fd89fb3c7555a05a8a3f6352fe67dc5464fcee2/main.py#L7350-L7355)。

当上传/生成目录设在 ASSETS_DIR 以外时，系统返回 `/api/storage-files/upload/...` 或 `generated/...`。通用 `output_file_from_url` 已支持这些地址，但 Codex 的 `codex_prepare_local_media` 仅对 /output/ 和 /assets/ 调用它，其他相对 URL 最后抛 400。用户自定义存储目录后，原本有效的本地图片无法作为 Codex 参考图。

**复现证据：** R5 在临时自定义上传目录创建文件，`output_url_for` 产生合法 storage-files URL，`output_file_from_url` 可正确定位文件，但 Codex 参考图函数拒绝该 URL。未调用真实 Codex、未消耗生成额度。

**修复建议：** 对受支持的本地资源 URL 统一使用现有的安全路径解析函数，包含 storage-files 路径，保留目录边界验证。

**回归验收：** 默认路径、自定义同盘目录、异盘/UNC 目录下的上传和生成图片都能解析为正确参考图；非法路径仍被拒绝。

## R6 [P2] 标题/图标变更不能绕过保存版本检测

**位置：** [main.py:16656](https://github.com/GuoWen-XX/Infinite-Canvas/blob/2fd89fb3c7555a05a8a3f6352fe67dc5464fcee2/main.py#L16656)，覆盖写入见 [17771–17779](https://github.com/GuoWen-XX/Infinite-Canvas/blob/2fd89fb3c7555a05a8a3f6352fe67dc5464fcee2/main.py#L17771-L17779)。

/meta 同时支持标题、图标等修改，却统一使用 `bump_updated_at=False`。如果一页改名，另一旧编辑页随后保存节点，版本比较仍通过，其旧 title/icon 将覆盖最新元数据。即使两个请求完全串行执行，也会发生；与 R1 的 409 自动重试问题相互独立。

**复现证据：** R6 创建 Old title，调用 /meta 对应函数改为 New title，验证版本号未变；使用旧版本和 Old title 保存成功，标题恢复为 Old title，没有 409。

**修复建议：** 把用于冲突检查的 revision 与用于排序的时间分开，标题/图标修改也增加 revision；或让节点保存只更新节点相关字段、将元数据专门管理。保持“不因置顶调整列表时间”的产品行为不必以禁用冲突检测为代价。

**回归验收：** 一页改名/改图标，另一页保存节点，既保留元数据也保留节点；不能静默回滚。

## R7 [P2] 编辑样式时保留 variant 的稳定 ID

**位置：** [static/js/skill-manager.js:161–162](https://github.com/GuoWen-XX/Infinite-Canvas/blob/2fd89fb3c7555a05a8a3f6352fe67dc5464fcee2/static/js/skill-manager.js#L161-L162)、[177–181](https://github.com/GuoWen-XX/Infinite-Canvas/blob/2fd89fb3c7555a05a8a3f6352fe67dc5464fcee2/static/js/skill-manager.js#L177-L181)，后端 ID 推导见 [main.py:19567](https://github.com/GuoWen-XX/Infinite-Canvas/blob/2fd89fb3c7555a05a8a3f6352fe67dc5464fcee2/main.py#L19567)。

前端加载样式行时只传 label/prompt，收集表单也不带 id。后端因此按 label 重新生成 ID。对于导入 Skill 中 id 与 label 不同的样式（例如 id=cobalt、label=Blue Style），即使不修改内容，保存后也变为 blue-style。画布持久化的 skillVariant=cobalt 不再匹配，编译器静默回到无样式，生成提示词缺失原样式指令。

**复现证据：** R7 按编辑器字段回传保存，随后以旧 cobalt ID 调用真实快速编译；返回 `skill_used.variant=null`，提示词不含 COBALT_DIRECTIVE。

**修复建议：** 样式行保留现有 id，新建样式才推导 id；修改 label 不改变已持久化 ID。不存在的旧 ID 应给出可操作提示，不能静默降级。

**回归验收：** 导入含英文 ID/中文或不同英文标签的 variants，编辑保存后原画布仍选择同一样式；修改标签也不改变 ID。

## 验证记录与限制

1. 固定基线对应 [GitHub Actions 运行 38670750648](https://github.com/GuoWen-XX/Infinite-Canvas/actions/runs/38670750648) 状态为 completed/success；这是读取远端状态，不是本次重新触发 CI。
2. 本地尝试按锁定 requirements 安装，当前包源未提供 `pydantic-core==2.46.4`，安装失败。初次还遇到旧 pip 在 GBK 环境解码中文注释失败，启用 PYTHONUTF8 后越过该问题。未据此断言生产环境不可安装。
3. 为完成函数级验证，仅在工作区隔离虚拟环境安装兼容依赖：Python 3.11、FastAPI 0.115.12、Pydantic 2.11.7 / core 2.33.2、Starlette 0.46.2、httpx 0.28.1、PyYAML 6.0.3、Pillow 13.0.0。**这不是 requirements 锁定版本验收**。
4. 本地原有测试：`python -m unittest discover -s tests -p "test_*.py" -v`，**78/78 通过**。
5. 后端缺陷复现探针：**6/6 通过**，表示成功观察到 R2–R7 的缺陷，不表示这些缺陷已经修复。
6. JavaScript 探针：R1 成功复现；Node 24.16.0 对 canvas.js、smart-canvas.js、skill-manager.js 的语法检查通过。
7. 未启动浏览器、未使用 Computer Use、未访问真实 Codex/ComfyUI/生图服务，未使用真实用户数据或生产目录。GitHub 升级的网络部分为模拟。
8. 本报告不认定实际账户泄露、生产事故或真实用户数据已经丢失；描述的是代码及隔离验证确认的触发路径。

## 复现脚本与运行方式

同目录附：
- `review_backend_probes.py`：直接调用仓库 main.py，使用独立临时数据和 mock。
- `review_conflict_probe.cjs`：从经典画布源码提取原始保存函数，模拟 409 与重试。

请在**一次性仓库副本**根目录运行，不要在生产目录运行。main.py 导入会在副本中初始化运行目录/配置；探针临时文件保存在副本的 .review-tmp。复现脚本是审查证据，断言当前缺陷存在；修复后应把断言改成期望行为，再纳入正式测试。

```text
python docs/reviews/2026-10-30/review_backend_probes.py
node docs/reviews/2026-10-30/review_conflict_probe.cjs
```

建议修复顺序：R1 → R2/R7 → R3/R4 → R5/R6；逐项增加覆盖上述触发路径的回归测试。修复后再执行真实浏览器双页面和目标存储目录验收。
