# Infinite-Canvas 修复工作计划（执行台账）

> 建立：2026-11-02；执行目标：`main`。  
> 当前状态：`S00 MERGED → S01 MERGED → S02 REVIEWED / TEST_GATE_BLOCKED（PR #5 最新 HEAD Codex 0 findings；缺正确分支全量回归与设备兼容验收）`。S02 尚未完成完整项目环境与 Chrome/Photoshop/LAN 联调，不得启动 S03。  
> 本台账是长期执行清单；每推进一个阶段，必须随该阶段 PR 更新状态、测试证据、风险和回滚记录。

## 一、工作规则（强制）

1. **单阶段、单实施分支、单 PR**。以已批准的上一个 `main` HEAD 为基础；不在未审查分支上继续叠加下一阶段代码。
2. 每阶段顺序：`建立分支 → 先写失败回归测试/复现 → 小范围修改 → 本地/隔离验证 → 推送 PR → 远端 Code Review → 修复所有阻断项 → 合并 → 记录交接 → 下一阶段`。
3. 下一阶段的解锁条件：本阶段 PR **已 merge 到 main**，具备可核查的本地/隔离测试记录、明确的独立 Review 通过结论且没有 unresolved blocking comments。**不以 GitHub Actions success 为普遍前提；PR 创建、Actions 绿灯、Codex Review Summary 显示 running 都不等于审查通过**。
4. 若没有提交的 Review approval，可由项目维护者作出明确的人工审查决定，并把结论、证据、理由和仍存风险写入 PR；不能由执行者自己宣称“远端审查通过”。
5. 每次提交前 `git diff` 审查、最小改动、安全敏感字符串检查；修复失败优先在同一 PR 处理。严禁强推 `main`；严禁修改真实用户 API Key、用户画布或使用真实付费额度做自动测试。
6. 新发现的严重安全缺陷可标记 `BLOCKED/SECURITY`，修改计划后按新顺序执行；不得悄悄扩大当前阶段范围。
7. 任何阶段若变更超出当前计划，先更新方案/验收条款并在 PR 上明确说明，再编写代码。
8. **GitHub Actions 用量红线**：每阶段默认 0 次 Actions 运行；只使用本地/隔离测试、静态检查与独立审查。确实必须使用 Actions 时，先说明原因并取得用户明确同意，然后只手动触发必要的单次运行；不得恢复 push / pull_request 自动触发。
9. 阶段 PR 均以 `main` 为 base。`zcode/iteration-01` 是当前仓库默认分支，直到单独审议默认分支调整前不修改；必须在 PR 说明里标明这一点。
10. **持续推进的含义是按审查关卡逐段推进，不是跳过等待；未得到新审查结果时应停在 gate 并报告状态。** 不在未获批准时自动合并或展开下一阶段。

## 二、阶段路线图

| 阶段 | 状态 | 目标 | 主文件 | 交付与验收 |
| --- | --- | --- | --- | --- |
| S00 | MERGED | 固定修复基线，提交技术方案、执行台账、评审规范 | `docs/remediation/2026-11-02/*.md` | 文档 PR 被认可后，解锁 S01 |
| S01 | MERGED | 阻止保存的 API Key 被任意 `base_url` 带出（SEC-01） | `main.py`、`tests/test_provider_security.py` | saved key 不发往任意目标；正常 provider 测试可用；Mock 无真实请求 |
| S02 | REVIEWED / BLOCKED | 权限/CORS/ModelScope Token 路径（SEC-02） | `main.py`、`static/zimage.html`、`static/angle.html`、Chrome/Photoshop 连接器 | 未授权访问失败、合法 LAN/插件/ModelScope 功能正常 |
| S03 | NOT_STARTED | 存储根访问控制、SSRF、下载 ZIP 配额（SEC-03/04/05） | `main.py`、素材管理相关前端和测试 | 任意文件/内网 URL 被拒，合法自定义存储仍可使用 |
| S04 | NOT_STARTED | 画布 409 覆盖 R1、元数据回滚 R6 | `static/js/canvas.js`、`main.py`、画布测试 | 双页面增/改/删、改名均不丢数据，草稿可恢复 |
| S05 | NOT_STARTED | Skill 编辑 frontmatter R2、variant ID R7 | `main.py`、`static/js/skill-manager.js`、Skill 测试 | 保存不丢元数据、不改稳定 ID、旧画布引用有效 |
| S06 | NOT_STARTED | PyYAML 正式依赖 R4、GitHub Skill tracking ref R3 | `requirements.txt`、安装脚本、`main.py`、Skill 测试 | 全新环境正确安装；A→B→C 升级可跟踪；缺依赖无半次写 |
| S07 | NOT_STARTED | Codex 自定义存储参考图 R5 | `main.py`、Codex 测试 | 默认/自定义路径均可解析，非法引用拒绝 |
| S08 | NOT_STARTED | 跨模块回归、Windows/LAN/插件联调与发布质量门 | 本地/隔离测试、文档、最小必要的修复文件 | 完整回归、发布报告及残余风险列表 |

优先级解释：安全 P0 首先修；画布数据丢失 R1 在 S04 专项完整解决；每阶段风险以隔离环境复现结果重新评定，不能仅靠既往静态结论。

## 三、阶段任务卡与完成定义

### S00 — 计划/治理

- [x] 已将 `2fd89fb` 的 `run.bat` 内容等效移植到 `main`，新提交 `0330be0a`。
- [x] 确认 `main` 与 `zcode/iteration-01` 最终文件差异原先只有 `run.bat`，但提交历史有分叉。
- [x] 引用 PR #2 七项缺陷，区分已隔离复现与独立静态风险。
- [x] 制定分阶段技术方案、验收方法、回滚与 gate。
- [x] 创建并审查计划 PR #3（Codex Code Review completed / no findings；Review threads 0；维护者明确要求按计划继续）。
- [x] 计划 PR #3 已合入 `main@8193b49d56cfbb0570972720c3c0c4232808d0fd`；Actions 已切换手动触发，未额外运行。

### S01 — API 凭据出站限制（SEC-01）

- [x] 已检查 `/api/providers/test-connection`、`/api/providers/probe-async`、`/api/providers/fetch-models`、GET 已存 provider 路由，以及 RunningHub 钱包 Key fallback 和 Volcengine 隐式 fallback。
- [x] 已增加虚构 Key/离线独立策略测试及 Mock 路由测试；修复前的缺陷由源码调用链确认，未在真实机器上发出恶意请求。
- [x] 使用严格 URL 基址校验并保证 mismatched URL 时尚未读取保存 Key；RunningHub 只使用已经解析/验证的本次 Key；不额外记录完整凭据。
- [x] 所有共用 `TestConnectionPayload` 的模型列表/探测入口已接入统一密钥绑定；为 Ark 无 ID 借用与 RunningHub 钱包 fallback 增加专门回归。
- [x] 已提交实施 PR #4（`fix/S01-provider-key-binding` → `main`），列明凭据出站风险、变更、离线测试、运行限制与回滚。
- [x] PR #4 最新 HEAD `856ef2de1cd3089df1d0cdae2bc237ccae145e74` 的 Codex Review completed / 0 findings，原 4 条线程已全部 resolved；2026-11-02T08:22:26Z 合并 `main@0f661b20a0996f311cf187d93c6db2b3f939fd97`。

**S01 验证与残余限制（PR #4）：** 修复三项 P1 与一项 P2 后，最新 HEAD 的 Codex Review completed / 0 findings / 0 unresolved，四条 review threads 均 resolved。隔离纯函数回归 **10/10 PASS**、CLI 分派隔离回归 **2/2 PASS**；合并前另记录了隔离 `python -m unittest discover -s tests -p 'test_provider_probe_security.py' -v` 及提取模块 `py_compile` 通过。**完整仓库 `main.py` 端点集成与全量测试尚未运行**，不应把隔离验证误称为全面通过；该限制在 S08 跨模块验收中保留。GitHub Actions：**0 次主动运行**，不得自动触发。合并证据：PR #4、merge SHA `0f661b20a0996f311cf187d93c6db2b3f939fd97`。

### S02 — 身份和 Token（SEC-02）

- [x] 在独立 `fix/S02-lan-auth-token` 分支建立只读基线审计 `S02_AUDIT.md`，确认 CORS wildcard、Token 明文接口、WebSocket 无鉴权，以及 zimage/angle 与后端现有 ModelScope 代理调用链。**这是静态证据，不是运行时测试或修复。**

- [x] 已追踪 HTTP、WebSocket、zimage/angle、Chrome/PS 源码路径；具体调用关系和迁移限制记录于 `S02_AUDIT.md` 与 `S02_LAN_ACCESS.md`。
- [ ] 按 `S02_LAN_ACCESS.md` 在独立 Windows/Chrome/Photoshop 与 LAN 环境执行真实联调；当前不能以文档代替验证。
- [x] 已新增默认 localhost 绑定、LAN 显式密码认证、Host/Origin/CORS/WS 检查，以及 `has_token` + 原后端 ModelScope 代理。**真实设备兼容性及全量回归尚未验证。**
- [x] 新增 `tests/test_access_boundary.py`：LAN、Host、Origin、Basic、Cookie、Token 不回传与旧配置服务器读取测试；**仅编写，尚未在完整仓库执行。**
- [x] 创建 [S02 PR #5](https://github.com/GuoWen-XX/Infinite-Canvas/pull/5)，目标 main。最新 HEAD `e68ca0e5980c0f894f68de44ca19f5dc536c9431` 的 Codex 独立 Code Review 已完成、0 findings，全部 6 条 inline review threads 已 resolved。GitHub Actions 曾由用户授权手动运行 1 次，但实际选中默认分支 `zcode/iteration-01`，不是 S02，不能用于本阶段验收。
- [x] 对初轮 Review 的三个 P2 已提交修复：API/.env 加载后初始化 LAN/CORS；Basic 非 ASCII 密码改成 UTF-8 字节恒定时间比较；公网媒体变为绑定 `/assets/` / `/output/` 单文件、30 分钟的 HMAC 签名 GET/HEAD。补充安全回归与迁移说明。
- [x] 第二轮 Review 对签名 URL 的二次解码及字面 `%` 文件名提出 2 个 P2。已修复为“生成端 URL 解码一次 / 验证端使用已解码 ASGI 路径原样签名”，并修正 URL 序列化对字面 `%` 的重新编码；新增 `%23` / `%3F` / `%2520` 回归；提取安全函数隔离测试 **9/9 PASS**。完整后端与实际 LAN/插件联调**尚未运行**。
- [x] 2026-11-02 新增真实 ASGI 路径边界修复：Starlette `Request.url.path` 在已解码的文件名含 `#` / `?` 时会截断，导致普通文件的有效签名可授权读取另一文件；签名校验现使用与 StaticFiles 一致的 `request.scope["path"]`。新增 `TestClient` 回归。**隔离 FastAPI/Starlette ASGI 实测：旧实现可错误读取文件，新实现拒绝跨文件复用且允许正确签名，3/3 PASS**（`/mnt/data/ic_review/s02_asgi_path_regression.py`；该脚本是独立提取验证，不是完整仓库测试）。
- [x] 2026-11-02 最新 HEAD `e68ca0e5980c0f894f68de44ca19f5dc536c9431` 的独立 Codex Review `completed / has_any_findings=false / has_unresolved_findings=false`，6/6 旧线程已 resolved；补充 macOS 启动脚本与 `tests/test_mac_launcher.py`，隔离 Mock `2/2 PASS` 和 `bash -n` PASS。
- [x] 2026-11-02 使用 GitHub 连接器读取准确 S02 HEAD，完成 17 项源码策略不变量检查（`17/17 PASS`：Host/Origin/CORS/WS、Token 后端保密、签名媒体路径、URL 编码、前端本地 Token 清理、macOS loopback、workflow manual-only 等）。**此为静态结构检查，不能替代执行 24 项真实后端测试。**
- [x] 用户明确授权并亲自启动 [Actions Tests #41439808653](https://github.com/GuoWen-XX/Infinite-Canvas/actions/runs/41439808653)：`success`，`78/78`；但工作流实际检出 `zcode/iteration-01@bb778e26a9b84d63d059c83ff511dbb0dc2e7067`，不是 S02 分支，不可用于 S02 的全量回归证据。未启动第二次 Actions。
- [ ] S02 **TEST_GATE_BLOCKED**：尚缺在准确 HEAD 上导入 `main.py` 后执行 `tests/test_access_boundary.py`（24 项）及 `unittest discover` 的成功记录；真正的 LAN/Chrome/Photoshop/ModelScope Mock 兼容性验证也未完成。当前本地容器 DNS 无法访问 GitHub；替代隔离云环境不具备创建权限。禁止以错误分支的 78 项旧测试绿灯放行，禁止为绕过门禁自动重跑 Actions。S02 正式合并 main 并补齐交接记录前，不提交 S03 实施代码。

### S03 — 本地文件及远程下载（SEC-03–05）

- [ ] 先补恶意存储 root、符号链接/路径逃逸、SSRF/redirect、超大 ZIP 的失败测试。
- [ ] 合法自定义目录、UNC/跨盘路径及用户素材保留。
- [ ] 最小必要修复路径信任根、目标 URL、资源配额、ZIP 文件流。
- [ ] PR 审查 + 无未解决安全问题后解锁 S04。

### S04 — 画布保存（R1/R6）

- [ ] 从 PR #2 的 `review_conflict_probe.cjs` 提炼正确行为回归（旧 probe 的“通过”不能复用）。
- [ ] 先验证本地旧版本、远端新增、远端删除、多端编辑以及改名冲突的失败。
- [ ] 实施冲突提示/草稿保留/三方合并或人工决策；标题/图标加入真正的 revision。
- [ ] UI 双标签测试、后台 Python 画布并发测试；PR 审查合并后解锁 S05。

### S05 — Skill 内容稳定（R2/R7）

- [ ] 复现/测试打开即保存、frontmatter 未知字段、variant 自定义 ID。
- [ ] 实施解析—合并—原子保存，前后端明确 body/完整 Markdown 契约。
- [ ] 修改标签不变更稳定 ID；不存在 ID 必须显式提示。
- [ ] PR 审查合并后解锁 S06。

### S06 — Skill 安装与升级（R3/R4）

- [ ] 在正式安装环境验证 PyYAML，不可仅 CI 临时 `pip install pyyaml`。
- [ ] 提前检查依赖，错误时不碰已有 Skill 文件。
- [ ] 分别维护 `tracking_ref` / `commit_sha`，模拟 A→B→C 更新。
- [ ] ZIP/ GitHub install rollback、覆盖安装及校验测试；PR 审查合并后解锁 S07。

### S07 — Codex 自定义存储媒体（R5）

- [ ] 默认目录/自定义目录各准备独立 fixture。
- [ ] 统一安全本地路径解析；非法 URL 拒绝、合法 URL 成功。
- [ ] 使用 Mock Codex，禁止自动实际消耗额度；PR 审查合并后解锁 S08。

### S08 — 完成验收

- [ ] 完整 Python unittest discover、JS 语法与浏览器用例、Windows 启动器实际运行。
- [ ] LAN/Chrome/Photoshop/ModelScope 与纯本机模式回归。
- [ ] 版本、自动更新源、安装流程和权限说明核对。
- [ ] 综合残余风险报告；最终 PR 审查合并；发布/调整默认分支另行决策。

## 四、证据、进度记录格式

每个阶段 PR 须在说明中包含：

```text
Stage: Sxx
Base main SHA:
Scope / issue IDs:
Changed files:
Regression tests that fail before fix:
Tests passed after fix (exact commands and results):
Manual smoke tests:
Security/privacy impact:
Compatibility risks and rollback:
GitHub Actions: NOT_RUN（默认）/ 如经用户明确许可手动触发，记录必要性与运行 URL、状态:
Code review URL, reviewer and result:
Open/blocking comments:
Final merge SHA:
```

当阶段状态更新时，提交对本 `WORKPLAN.md` 的原位修改：`NOT_STARTED → IN_PROGRESS → PR_OPEN → REVIEWED → MERGED`。若被阻塞标 `BLOCKED`，写清原因。不要使用没有远端依据的“已通过”标记。

## 五、停止条件

- 任一阻断测试失败、PR 有 unresolved blocking review、仓库 head 已更新且未重新变基；
- 计划范围外出现可能损坏画布/真实密钥的变更；
- 需要真实付费额度才能验证的动作尚未获得明确授权；
- 阶段审查 PR 仍处于 open/running 而未通过。

这些情况下只记录状态、修复本阶段问题，不前进至下一阶段。

## 六、相关链接

- 计划基线 `main@0330be0a`；启动器原始变更 `2fd89fb`。
- PR #2：https://github.com/GuoWen-XX/Infinite-Canvas/pull/2
- 技术设计：`TECHNICAL_PLAN.md`
- 审查关卡：`REVIEW_GATE.md`
