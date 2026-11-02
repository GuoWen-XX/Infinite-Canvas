# Infinite-Canvas 源码缺陷修复技术方案

> 创建日期：2026-11-02  
> 规范仓库：`GuoWen-XX/Infinite-Canvas`（旧链接 `benkwok1983-cmd/Infinite-Canvas` 当前由 GitHub 重定向）  
> 修复目标基线：`main@0330be0a0e72842df52b1569fd2dad1a6f2f9a5c`  
> 审查来源：PR #2，基线 `zcode/iteration-01@2fd89fb3c7555a05a8a3f6352fe67dc5464fcee2`；以及 2026-11-02 对后端/前端安全边界的独立只读审查。  
> 文档约定：R1–R7 是 PR #2 的已复现缺陷；SEC-01…SEC-05 为静态审查发现，实施前必须在隔离环境中确认实际影响。不要将静态发现误写为生产事故。

## 0. 范围与当前状态

- `main` 已等效 cherry-pick `2fd89fb` 的 `run.bat` 修复，产生 `0330be0a`；其他文件内容未变。该操作已完成，不属于后续阶段 PR。
- `main` 和 `zcode/iteration-01` 的内容树已验证仅 `run.bat` 不同（修复后应相同）；但历史各自独有提交，不要整分支 merge 来实现文件同步。
- 仓库当前默认分支为 `zcode/iteration-01`；**本计划不擅自变更默认分支**。全部修复 PR 统一以 `main` 为目标分支；每阶段开始前确认 `main` 的 HEAD，结束后检查是否需要同步其他长期分支。
- PR #2 仅包括报告和复现证据，不包含代码修复。后续要把“缺陷复现测试（修复前应失败）”改造为“正确行为回归测试（修复后通过）”，不得把原 probe 的通过误当作缺陷已修复。

## 1. 风险等级与追踪清单

| ID | 优先级 | 缺陷与路径 | 主要影响 | 修复阶段 |
| --- | --- | --- | --- | --- |
| SEC-01 | Critical | `/api/providers/test-connection` 等连接测试接口可能组合客户端 `base_url` 与服务器保存的 provider key；`main.py` `api_key_from_payload` | 已保存 Key 被发往任意 HTTP(S) 接收者 | S01 |
| SEC-02 | Critical | `/api/config/token` 直接返回完整 ModelScope Token；全局 CORS `*`、HTTP API 缺少统一鉴权、默认 `0.0.0.0` | 局域网/跨源暴露敏感凭据和高权限操作 | S02 |
| SEC-03 | Critical | `PATCH /api/storage-settings` 可修改存储信任根为任意目录，`GET /api/storage-files/...` 和删除接口再以其为根访问 | 用户进程权限内的任意文件读取/删除风险 | S03 |
| SEC-04 | High | `fetch_remote_media_bytes` 和 `/api/canvas-assets/download` 可抓取不受约束的 URL | SSRF、可能的内网响应回传 | S03 |
| SEC-05 | High | 远程文件单项上限高、最多 1000 项、ZIP 使用内存 `BytesIO`，无累计配额 | 进程内存耗尽/拒绝服务 | S03 |
| R1 | P1 | 经典画布保存 409 后把远端版本号赋给旧本地快照继续自动 PUT | 其他页面新增/删除的节点被覆盖 | S04 |
| R6 | P2 | `/meta` 改标题/图标不递增冲突版本，旧编辑页面 PUT 覆盖新元数据 | 标题/图标静默回滚 | S04 |
| R2 | P2 | Skill 正文编辑先覆盖整份 `SKILL.md`，丢失 frontmatter | name/license/version 元信息丢失 | S05 |
| R7 | P2 | Skill variant 编辑只回传 label/prompt、不保留 ID | 已保存画布的 variant 引用失效 | S05 |
| R4 | P2 | 正式运行依赖漏 PyYAML，CI 单独补装隐藏差异 | 样式丢失、编辑 500、文件已变更 | S06 |
| R3 | P2 | Skill 安装持久化 `commit SHA` 为 `ref` | 不再跟踪 GitHub 分支后续更新 | S06 |
| R5 | P2 | Codex 本地参考图函数拒绝合法的 `/api/storage-files/...` URL | 自定义上传/生成目录不能用于参考图 | S07 |

安全入口与异常响应涉及其他路径，阶段中必须做相邻调用链审计，而不能只机械修改上表中的单个函数。

## 2. 设计规则

1. **不丢用户数据**：画布、Skill、配置文件变更需先对照现有兼容用例，使用原子更新；失败不得留下半次操作。
2. **不跨越信任边界**：服务端保存的 API Key 只能发送到与其绑定且经过校验的 provider 目标；HTTP 客户端自选地址时必须提供独立临时 Key。
3. **局域网协作兼容**：当前工作室需要本机、LAN、Chrome 扩展、Photoshop 连接器。访问控制方案不得以无说明地禁用 LAN 代替安全设计，须提供显式配置、验证和迁移说明；默认最小权限。
4. **保存 revision 与 UI 排序时间解耦**：对于画布任何需要冲突检测的变更都递增单调 revision；打开画布、置顶等操作可以有独立的 `last_opened_at` / `sort_updated_at`。
5. **保留 Skill 稳定标识**：修改 display label 不修改已经持久化的 variant ID；旧画布引用不存在的 ID 时明确提示，不静默降级。
6. **数据来源安全**：远程下载只允许 HTTP(S)、校验 DNS 解析及每次跳转目标，阻断 loopback/private/link-local/metadata 等地址；限制单文件、总字节、条目数、超时与并发；流式/临时文件 ZIP。
7. **兼容性与可撤回**：每个 PR 只涉及本阶段；不得为了修复安全问题悄悄取消正常生图、跨程序连接或自定义存储能力。提交前提供适配/迁移和回滚步骤。

## 3. 逐阶段代码方案

### S01 — 凭据外送阻断（SEC-01）

- 定位所有 `TestConnectionPayload`、`api_key_from_payload`、`upstream_models_url`、`probe-async`、`fetch-models`、RunningHub/Volcengine 特殊路径。
- 把“用户本次填写的新 URL + 临时 Key”和“已保存 provider 的绑定 URL + 保存 Key”分成互斥分支；未提供临时 Key 时，不允许将保存 Key 发往任意自选 host。
- 目标必须按规范化 scheme/host/port/path 与已存配置比对，不能只做字符串 contains/suffix 匹配；校验重定向及内部探测。保留合法已配置 provider 的连接测试能力。
- 错误、日志、模型返回体不得泄露 Authorization、Key、完整敏感 argv。
- 回归：自选恶意 URL + 已保存 Key 被拒绝；已配置 URL + 保存 Key 可用；自选 URL + 显式临时 Key 可用；错误/重定向/不同协议无泄露。模拟 httpx，不发送真实流量。

### S02 — 服务访问边界与 Token 路由（SEC-02）

- 盘点 `/api/config/token` 对 `static/zimage.html`、`static/angle.html`、外部 ModelScope 生图接口的实际依赖，设计后端中转或同源受控会话方案，不允许简单删除致使现有功能中断。
- 为所有敏感 GET/状态变更接口建立统一的访问策略；LAN 模式采用显式启用、认证及合理 Origin/CSRF 验证，保留 Chrome/Photoshop 专用连接机制。
- 不能仅靠客户端 IP 是私网或访问 warning 代替认证；避免全局 `allow_origins=["*"]` 与可读 token 接口组合。
- 回归：未认证来源不能读 token/配置/执行更新；授权浏览器与扩展连接正常；跨源/WS/重连/视频模型不回归。真实联调应在本地无真实额度的隔离环境完成。

### S03 — 存储访问与媒体抓取（SEC-03/04/05）

- 存储目录变更仅允许经授权的“用户显式选择目录”动作；限制可访问的物理根和类型，符号链接/UNC/跨盘路径均按真实路径核验。拒绝对非媒体文件的越权读、删。
- 遍历、下载、删除 API 使用统一 canonical path 策略，与已有合法自定义目录保持兼容。
- 对远程媒体 URL 执行解析、DNS、重定向校验；禁止服务端访问本机、私网、云元数据地址；设单文件、请求总容量及条目数硬上限。
- ZIP 改临时文件或受限流式输出；上游错误无需把内部内容原样写回前端。
- 回归：绝对根、`..`、符号链接、private IP、跳转到本机、DNS 异常、大文件、累计配额、正常远程图片及自定义上传目录。

### S04 — 经典画布冲突与元数据（R1/R6）

- 409 时**绝不**单纯提高 `base_updated_at` 后自动重传过期节点。保留本地草稿，在 UI 提示冲突；设计基线三方合并或明确人工选择，删除操作必须保有语义。
- 后端以单调 `revision` 为所有数据变更的冲突依据，不依赖 UI 排序时间；`/meta` 的 title/icon 更新不能被旧保存覆盖。检查 `/touch`、canvas-list 调用。
- 回归：两个页面分别增、改、删不同节点以及同一节点冲突；标题/图标被另一标签改动；本地草稿可恢复；没有静默丢节点。

### S05 — Skill 元数据及变体稳定性（R2/R7）

- 编辑接口明确区分 `content_body` 和完整文件；从原始文件读取 frontmatter，保留 name/description/version/license/未知字段并安全合并 variants；校验后原子替换。
- 前端修改旧变体保留 `variant.id`；新增变体才生成新 ID；已保存画布引用旧 ID 时提供明确异常/迁移提示。
- 回归：打开不修改直接保存、修改正文、修改 label、多语言 ID/label、意外写入失败；旧画布引用仍有效。

### S06 — Skill 安装、依赖与更新跟踪（R3/R4）

- 正式 requirements 与 CI 安装方式对齐，显式加入兼容锁定的 PyYAML。缺依赖时在写入前报错，不发生半次保存。
- 安装需要分别持久化 `tracking_ref`（branch/tag）与 `commit_sha`（锁定安装内容），检测更新时解析前者；保持 commit-pinning 防 TOCTOU。
- 回归：A→B→C 连续升级、指定非默认分支、独立 commit pin（不追踪模式）、缺 yaml、新装环境、ZIP/GitHub 安装回滚。

### S07 — Codex 媒体引用兼容（R5）

- `codex_prepare_local_media` 复用经 S03 收敛的本地媒体 URL 解析器；支持合法 `/api/storage-files/upload` / `generated`，拒绝非法路径与非授权根。
- 回归：默认目录/自定义同盘/跨盘、URL 编码、路径越界、图像不合法；mock Codex 无额度消耗。

### S08 — 整体验收与发布检查

- 加入所有修复的回归测试，Python `unittest discover`、JS 浏览器级回归、最低 Windows 启动 smoke、LAN/扩展/PS smoke。
- 对齐 CI 与正式安装依赖，检查 secret scanner、版本与更新源，验证文档和回滚。
- 审查没有未解决 P1/P2；阶段通过后才提出版本发布和默认分支调整建议，不自动执行发布。

## 4. 主要风险与回滚

| 变更 | 潜在回归 | 预防/回滚 |
| --- | --- | --- |
| 凭据目标限制 | 合法自定义 API 连接测试误拒 | Mock 覆盖协议/URL 变体；必要时回滚单阶段 PR |
| LAN 认证/Token | 插件断连、ModelScope 生图失败 | 先测三种客户端；受控兼容迁移；保留先前 `main` 快照 |
| 存储根与 SSRF 限制 | 用户素材路径不可访问 | 启用前备份配置；提供显式目录授权与迁移步骤 |
| Canvas 冲突合并 | 草稿丢失/节点复活 | 双客户端新增/删除回归；冲突保留草稿 |
| Skill frontmatter/ID | 老 Skill 的扩展字段被重写 | 原样保留未知字段；真实 round-trip |
| 依赖锁定 | Windows 自带 Python/离线安装不兼容 | 正式安装脚本及 Windows 冒烟测试 |

## 5. 外部验收与引用

- PR #2：https://github.com/GuoWen-XX/Infinite-Canvas/pull/2
- PR #2 详细报告：`docs/reviews/2026-10-30/code-review.md`（位于 PR 的审查分支；未合入目标分支）。
- 复现证据：`review_backend_probes.py`、`review_conflict_probe.cjs`；只能在隔离副本运行。**复现脚本通过 = 缺陷存在，不是修复完成。**
- 每个实施阶段对应独立 PR；详细 gate、交接格式与当前状态见同目录 `WORKPLAN.md` 和 `REVIEW_GATE.md`。
