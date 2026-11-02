# Infinite-Canvas 修复工作计划（执行台账）

> 建立：2026-11-02；执行目标：`main`。  
> 当前状态：`S00 MERGED → S01 MERGED → S02 MERGED_WITH_DEFERRED_VALIDATION → S03 MERGED_WITH_DEFERRED_VALIDATION → S04 PR_OPEN / REVIEW_BLOCKED / TEST_GATE_BLOCKED`。S02/S03 正确版本全量与设备验证均必须在 S08 发布前补齐；S04 仍未达到审查/测试门禁。
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
| S02 | MERGED / DEFERRED VALIDATION | 权限/CORS/ModelScope Token 路径（SEC-02） | `main.py`、`static/zimage.html`、`static/angle.html`、Chrome/Photoshop 连接器 | 未授权访问失败、合法 LAN/插件/ModelScope 功能正常 |
| S03 | MERGED / DEFERRED VALIDATION | 存储根访问控制、SSRF、下载 ZIP 配额（SEC-03/04/05） | `main.py`、素材管理相关前端和测试 | 任意文件/内网 URL 被拒，合法自定义存储仍可使用 |
| S04 | IN_PROGRESS | 画布 409 覆盖 R1、元数据回滚 R6 | `static/js/canvas.js`、`main.py`、画布测试 | 双页面增/改/删、改名均不丢数据，草稿可恢复 |
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
- [x] 新增 `tests/test_access_boundary.py`：LAN、Host、Origin、Basic、Cookie、Token 不回传与旧配置服务器读取测试；**当前 28 项（新增真实 ASGI LAN Basic/Session、两项 WebSocket 拒绝与已认证连接检查），尚未在完整仓库执行。**
- [x] 创建 [S02 PR #5](https://github.com/GuoWen-XX/Infinite-Canvas/pull/5)，目标 main。最新 HEAD `e68ca0e5980c0f894f68de44ca19f5dc536c9431` 的 Codex 独立 Code Review 已完成、0 findings，全部 6 条 inline review threads 已 resolved。GitHub Actions 曾由用户授权手动运行 1 次，但实际选中默认分支 `zcode/iteration-01`，不是 S02，不能用于本阶段验收。
- [x] 对初轮 Review 的三个 P2 已提交修复：API/.env 加载后初始化 LAN/CORS；Basic 非 ASCII 密码改成 UTF-8 字节恒定时间比较；公网媒体变为绑定 `/assets/` / `/output/` 单文件、30 分钟的 HMAC 签名 GET/HEAD。补充安全回归与迁移说明。
- [x] 第二轮 Review 对签名 URL 的二次解码及字面 `%` 文件名提出 2 个 P2。已修复为“生成端 URL 解码一次 / 验证端使用已解码 ASGI 路径原样签名”，并修正 URL 序列化对字面 `%` 的重新编码；新增 `%23` / `%3F` / `%2520` 回归；提取安全函数隔离测试 **9/9 PASS**。完整后端与实际 LAN/插件联调**尚未运行**。
- [x] 2026-11-02 新增真实 ASGI 路径边界修复：Starlette `Request.url.path` 在已解码的文件名含 `#` / `?` 时会截断，导致普通文件的有效签名可授权读取另一文件；签名校验现使用与 StaticFiles 一致的 `request.scope["path"]`。新增 `TestClient` 回归。**隔离 FastAPI/Starlette ASGI 实测：旧实现可错误读取文件，新实现拒绝跨文件复用且允许正确签名，3/3 PASS**（`/mnt/data/ic_review/s02_asgi_path_regression.py`；该脚本是独立提取验证，不是完整仓库测试）。
- [x] 2026-11-02 最新 HEAD `e68ca0e5980c0f894f68de44ca19f5dc536c9431` 的独立 Codex Review `completed / has_any_findings=false / has_unresolved_findings=false`，6/6 旧线程已 resolved；补充 macOS 启动脚本与 `tests/test_mac_launcher.py`，隔离 Mock `2/2 PASS` 和 `bash -n` PASS。
- [x] 2026-11-02 使用 GitHub 连接器读取 S02 HEAD `e68ca0e`，完成 17 项源码策略不变量检查（`17/17 PASS`：Host/Origin/CORS/WS、Token 后端保密、签名媒体路径、URL 编码、前端本地 Token 清理、macOS loopback、workflow manual-only 等）。**此为静态结构检查，不能替代执行 28 项真实后端测试。**
- [x] 用户明确授权并亲自启动 [Actions Tests #41439808653](https://github.com/GuoWen-XX/Infinite-Canvas/actions/runs/41439808653)：`success`，`78/78`；但工作流实际检出 `zcode/iteration-01@bb778e26a9b84d63d059c83ff511dbb0dc2e7067`，不是 S02 分支，不可用于 S02 的全量回归证据。未启动第二次 Actions。
- [x] 2026-11-02 已补充 `tests/test_access_boundary.py` 真实 ASGI 边界回归 4 项：LAN Basic 认证授予 Session 后的 token 保密、跨源 WebSocket 1008 拒绝、无认证 LAN WebSocket 1008 拒绝、合法 Session 允许 LAN WebSocket 连接；新测试代码通过 Python AST 语法检查，但**未能在完整 `main.py` 环境实际执行**。
- [ ] S02 **TEST_GATE_BLOCKED**：尚缺在准确 HEAD 上导入 `main.py` 后执行 `tests/test_access_boundary.py`（28 项）及 `unittest discover` 的成功记录；真正的 LAN/Chrome/Photoshop/ModelScope Mock 兼容性验证也未完成。当前本地容器 DNS 无法访问 GitHub；替代隔离云环境不具备创建权限。禁止以错误分支的 78 项旧测试绿灯放行，禁止为绕过门禁自动重跑 Actions。S02 已以记录完整残余风险的有限例外合并 main，S03 可实施；正确分支全量/兼容性验证必须在 S08 发布前补齐。

**S02 合并/风险交接（2026-11-02）：** [PR #5](https://github.com/GuoWen-XX/Infinite-Canvas/pull/5) 已合并为 `main@ae042d816c7881005a6e180a8e38aeaa8f9f07f5`。合并时 HEAD `43b7f48` Code Review `completed / 0 findings`、6 条历史线程 resolved；S02 的 28 项完整模块回归及 Windows/LAN/Chrome/Photoshop 联调仍未实际执行，属于 **DEFERRED_VALIDATION**，不等于 PASS。风险和 S08 必补项目见 [PR #5 放行决定](https://github.com/GuoWen-XX/Infinite-Canvas/pull/5#issuecomment-6577109854)。原唯一一次 Actions 78 项通过的是错误默认分支，不可记为 S02 成功。为避免未知环境限制无限期阻断早期安全修复，S02 以一次性例外合并；在 S08 发布前必须针对正确版本完成完整测试与设备兼容验证。

### S03 — 本地文件及远程下载（SEC-03–05）

- [x] 2026-11-02 按 PR #6 Codex TOCTOU P2 增补 `storage_guard.py` 句柄级安全层：POSIX `dir_fd/O_NOFOLLOW` 目录链与目标 FD、目录 FD 下删除；Windows 打开句柄后 `GetFinalPathNameByHandleW` 边界校验与句柄删除。已替换存储/共享文件 HTTP、下载、素材及 workflow ZIP、媒体预览/PIL/ffmpeg 等重新打开路径的关键调用，保留单段 HTTP Range；新模块加入更新器白名单和 staged update 校验，见 `S03_TOCTOU_HANDLE_PLAN.md`。
- [x] 新增纯句柄级 `tests/test_storage_handles.py` 8 项，`tests/test_storage_safety.py` 扩充至 12 项；配合远程安全 8 项、ZIP 5 项，本阶段新增测试**共 33 项**，并非全部通过：本地仅有提取 POSIX 逻辑竞态测试 `7/7 PASS`，完整版 `main.py` 未实际运行，Windows/UNC 亦未联调。
- [x] 已将 Codex 原 5 条 review threads 中针对 DNS rebinding、根内 symlink alias 删除、ZIP stale-size、重定向 DNS mock 的 4 条标记 resolved；第五条 **P2 文件句柄 TOCTOU** 原审查仍标 unresolved，已经提交安全修复，需最新 HEAD 独立复审确认才可关闭。PR #6 仍为 draft，不能凭未执行测试或旧审查直接合并。
- [x] 已添加 `HANDOFF_NEXT_SESSION.md`，包含准确仓库状态、未完成项、费用约束、S04–S08 路线图及新会话可直接复制的续接提示词。


- [x] PR #6（`fix/S03-storage-ssrf`）已建立为 draft，独立于已合并 S02 的 `main@ae042d8`。S03 审计见 `S03_AUDIT.md`，逐项记录已确认源码调用链。
- [x] 第一批 SEC-03 改动：真实路径边界校验应用到存储文件读取/删除、旧 URL 解析、本地素材 basename 回退和列表，保留自定义绝对/UNC 存储路径；12 项临时文件回归已编写，**未运行完整项目**。
- [x] 第一批 SEC-04 改动：公网上游 DNS/IP 入口与每跳手动重定向检查，覆盖 `fetch_remote_media_bytes` 和 `/api/download-output`；8 项 Mock 网络回归已编写；增加了 connect 后、HTTP/TLS 握手前的实际 socket peer IP 公网校验与 `trust_env=False`，本地独立 HTTPServer 实验阻断本地 HTTP 请求，仍须完整项目与独立安全审查。
- [x] 第一批 SEC-05 改动：画布导出 ZIP 改用 `SpooledTemporaryFile`，250 文件 / 单文件 200 MiB / 累计输入 512 MiB 上限；5 项临时/Mock 回归已编写。新增测试目前合计 33 项，**未在完整 `main.py` 环境执行**。
- [ ] Codex S03 初审报告 P1 DNS rebinding / P1 symlink alias deletion / P2 TOCTOU / P2 ZIP size growth / P2 redirect test DNS mock。已修复或减缓前述四项，**文件句柄 TOCTOU P2 已提交句柄级修复，等待最新审查确认**，需要最新 HEAD 复审；运行正确分支测试、UNC/外置盘与下载兼容回归后，再考虑 PR #6 merge；不得复用 S02 风险例外去自动放行所有后续阶段。


- [x] S02 已合并至 `main@ae042d8`，S03 从此 SHA 建立 `fix/S03-storage-ssrf`，开始只读基线与回归设计。

- [ ] 先补恶意存储 root、符号链接/路径逃逸、SSRF/redirect、超大 ZIP 的失败测试。
- [ ] 合法自定义目录、UNC/跨盘路径及用户素材保留。
- [ ] 最小必要修复路径信任根、目标 URL、资源配额、ZIP 文件流。
- [ ] PR 审查 + 无未解决安全问题后解锁 S04。

**S03 最新复审与修复记录（2026-11-02，PR #6）**：

- [x] Codex 对 `5a49add6976d5518e46988af26d701bd340df6c1` 的评审 `completed / has_any_findings=true / has_unresolved_findings=true`，新增三条阻断项：P1 旧版 updater 不会下载 root `storage_guard.py`；P2 POSIX FIFO 阻塞打开；P2 `If-Range` 未验证而错误返回 206。
- [x] **已实际提交修复**：`main.py` 在 root helper 缺失时安全回退到 `static.storage_guard`；新增 `static/storage_guard.py` 与 root 文件字节一致，利用 S02 旧更新器一直支持的 `static/*` allowlist 首次升级；新版 staging 校验同时要求 root/static 模块相同。POSIX 最终句柄使用 `O_NONBLOCK | O_NOFOLLOW` 并 `fstat` 拒绝非普通文件。单段 Range 使用已打开 FD 的强 ETag/Last-Modified，`If-Range` 不匹配返回完整 200（日期仅在满足保守强验证条件时允许 206）。
- [x] 新增回归代码：无写端 FIFO 与文件换 FIFO **2 项**；If-Range 匹配 ETag、过期 ETag、匹配稳定日期、过期日期 **4 项**；旧版更新器 allowlist/字节一致性/仅有 static helper 的隔离启动 **3 项**。S03 新增测试现为 **42 项源码**（storage safety 16、handles 10、remote security 8、ZIP budget 5、legacy updater 3）；这些新增回归**尚未在完整仓库执行，不能写成 PASS**。
- [ ] 对 **最新修复 HEAD** 重新请求独立 Codex 评审；逐一关闭旧 TOCTOU + 新发现的 3 条线程，前提是确认问题确已修复且无新增阻断项。禁止提前关闭/合并。
- [ ] 正确 HEAD 上实际运行完整 Python unittest discover、必要 HTTP/Range/ZIP/自动更新和 Windows/UNC/FFmpeg 验证；当前本地执行容器 `git ls-remote` 因 github.com DNS 失败，仍没有可核实全仓 PASS。不得使用原 `zcode/iteration-01` Actions 成功作为证据；**不得自动运行 Actions**。
- [ ] 审查与必要门禁通过后方可 merge PR #6 → main，记录实际 merge SHA，再新建 `fix/S04-canvas-conflicts` 分支/PR。

**S03 再次安全复审（2026-11-02）**：

- [x] `216cec7f222d580df1d03f08966edaa4f7030b13` 的 Codex 审查 `completed / findings=true / unresolved=true`，三项旧版 updater / FIFO / If-Range 修复未被再次提出，但新增 **P2 Windows root/junction 竞态**（`PRRT_kwDOUaWIpM6yr_6S`）和 **P2 POSIX 搜索权限目录兼容**（`PRRT_kwDOUaWIpM6yr_6f`）。原 TOCTOU P2 和前三项线程尚待最新审查确认，绝不提前按已通过处理。
- [x] 实施：`storage_guard.py` Windows 开始使用 pre-open 捕获的 `trusted_root`，在 child open 前固定根目录 HANDLE，并检查 Win32 文件/删除句柄相对于可信根而不再次 `realpath(root)`；POSIX 目录链接逐级打开使用平台允许时的 `O_PATH/O_SEARCH` 替代要求读权限的 `O_RDONLY`。同步 `static/storage_guard.py`，避免旧版首次升级回退到有漏洞的副本。
- [x] 增加 **3 项**句柄测试：根目录换成 symlink 不能读根外文件（POSIX）；0711 搜索权限目录可读取和 unlink（POSIX）；Win32 opened-handle 校验不跟随后来变化的根（Mock 函数级）。S03 目前 **45 项已编写**（storage safety 16，handles 13，remote 8，ZIP 5，legacy updater 3），**并非完整仓库 45/45 通过**，Windows junction/UNC 仍须真实设备验收。
- [ ] 已发现 `main.py` 自动更新源常量当前指向 `benkwok1983-cmd/Infinite-Canvas@zcode/iteration-01`，与本修复 PR 的目标 `GuoWen-XX/Infinite-Canvas@main` 不同；**S03 兼容修复仅在发布来源实际含 static helper 时生效**。这属于 S08 发布/更新源和分支一致性门禁，不能假定本 PR 合并后旧客户端会收到修复。不要擅自改线上更新源或默认分支。
- [ ] 最新 HEAD 独立复审、阻断线程核查与正确 SHA 的可靠回归仍是 S03 合并门禁；未经完成不进入 S04。禁止触发 GitHub Actions / 真实用户数据 / 付费模型。

**S03 搜索权限测试复审（2026-11-02）**：

- [x] Codex `cb702594aa7169ab2b619cecadab0700b430d9d0` 复审 `completed / findings=true / unresolved=true`，新增 **P2 测试假阳性**：之前 0711 目录的所有者依然有目录读取权限、root 测试也会绕过 ACL（`PRRT_kwDOUaWIpM6ysRGk`）。现已修改测试：非 root 场景目录使用 `0311` 使所有者拥有写入/搜索但无读取；root 场景仅在 `nobody` 账户存在时，通过子进程放弃 root 权限并将该目录设为 `0733`，保证子进程仅有写入/搜索。测试必须**先确认旧 `O_RDONLY|O_DIRECTORY|O_NOFOLLOW` 打开出现 `PermissionError`**，再由同一进程执行安全读取与 dir_fd 删除。子进程只操作 `TemporaryDirectory` 文件。
- [ ] 此改进已经实际提交，但 **仍未在此容器完整运行且未获最新 HEAD 复审**，不得以撰写测试取代通过证据；S03 新增测试源码仍为 **45 项**。需新 HEAD 独立复审后再逐项处理 7 条未解决审查线程；不自动跑 Actions。

**S03 权限回归测试跨环境兼容修复（2026-11-02）**：

- [x] `5ae5f710b78afc83317333c9884fb5d93fefe835` 最新 Codex 审查 `completed / findings=true / unresolved=true`，新提 P2 `PRRT_kwDOUaWIpM6ysc4e`：root 的私有 `sys.executable` 无法在 `preexec_fn` 降权后执行；P2 `PRRT_kwDOUaWIpM6ysc4n`：私有 `TMPDIR` 祖先不可搜索使 nobody 无法进入测试目录。
- [x] 同一 PR 已提交针对性修复：先**以当前权限启动**原 Python，传入 `-I` 隔离模块搜索路径，并从专用临时目录导入该提交的 `storage_guard.py` 兼容源码后**才在子进程内 setuid/setgid(nobody)**；整个测试目录创建于所有祖先经过 `other +x` 检查的标准 `/tmp` 下，完全不修改用户 `TMPDIR` 的权限；在同一降权身份先核实旧 `O_RDONLY` 必失败，再测试 `O_PATH/O_SEARCH` 读取和删临时文件，最后恢复目录权限以保证 `TemporaryDirectory` 可清理。non-root 时仍直接验证 0311 目录，无额外降权。
- [ ] 此次修复需要对 **最终 HEAD** 再次独立审查，九条原有未解决 findings（已提交代码修复或测试修复）不能预先关闭。S03 共 **45 项回归代码**，没有完整项目 PASS；隔离内核权限验证 1 次成功并非仓库回归测试。S02 延期实测必须在 S08 发布前补齐。


**2026-11-02 S03 合并、S04 启动记录：** PR #6 最新代码 HEAD `744a3a152cda8503f9ec2296d4217e5d48622b65` 的独立 review 0 findings、14/14 历史线程 resolved。已以明确记录的有限风险例外合并至 `main@081edae763ec73505bed9f82e4274bfeaabc16c3`；风险公告见 [PR #6 有限风险放行记录](https://github.com/GuoWen-XX/Infinite-Canvas/pull/6#issuecomment-6580377629)。**S03 45 项新增回归并未在完整仓库实际通过，Windows HANDLE/junction/UNC、FFmpeg/Range/Streaming、旧版发布源升级均为 S08 发布阻断验证，绝不可写成 PASS。** 旧更新源不指向本仓库 main，不能据合并称已发布。S02 延期的 28 项与 LAN/Chrome/Photoshop/ModelScope 联调同样是 S08 必补。已从上述 merge SHA 创建 `fix/S04-canvas-conflicts`，开始 R1/R6；GitHub Actions 未触发，不手动请求 Codex Review。

**S03 合并/延期验证记录（2026-11-02）：** PR #6 已于 15:00:18 UTC 合并至 `main@081edae763ec73505bed9f82e4274bfeaabc16c3`，代码 HEAD `744a3a152cda8503f9ec2296d4217e5d48622b65` 的 Codex 复审无新发现，14/14 review threads resolved。维护者在 PR 中公开有限风险例外；**45 项新增 S03 测试仍仅已编写，正确 HEAD 全量 unittest、Windows/UNC/junction、FFmpeg/Range/Streaming 与实际更新渠道均未完成验证**。本次合并不是 TEST_GATE_PASS，也不是发布许可；以上全部列为 S08 发布前阻断验收。GitHub Actions 本阶段 0 次主动运行。

### S04 — 画布保存（R1/R6）

- [x] S03 已合并后从 `main@081edae` 建立 `fix/S04-canvas-conflicts` 与 Draft PR #7；不触及 S05。
- [x] 首批前端修复阻止普通画布 409 盲目重试，使用本地恢复草稿，避免 WebSocket/轮询直接覆盖未保存编辑。
- [x] 新增 `tests/test_canvas_revision.py` 期望行为回归（包括元数据改名后旧编辑器拒绝覆盖、两个编辑器同 revision 仅一方可提交、touch 不引发内容假冲突、legacy timestamp 兼容）。**已编写，未在完整 main.py 环境执行。**
- [x] 后端 `write_canvas` 独立 `revision`、锁内 CAS；meta-only 更新仍递增 revision，标题/图标同时递增 `updated_at` 保护旧客户端；touch 只变活动时间；画布 GET/meta/list/touch 返回 revision。
- [x] 普通画布、列表页和智能画布传递 revision；智能画布 409 不再盲目合并重试，而保存本地冲突草稿。三份 JS 通过 V8 纯语法解析（不等于浏览器集成测试）。
- [x] 已新增可见的冲突恢复面板：导出本地 JSON、另存独立画布副本、查看服务器版本、元数据经用户确认后 CAS 重试；浏览器双标签交互尚待真实验证。
- [ ] **当前阻断：** 正确 HEAD Python `main.py` 集成测试、Node 原生命令与双标签浏览器/智能画布端到端测试尚未执行；PR #7 自动 Codex 审查提示仓库缺少 Codex environment，当前没有独立审查结论。未达到门禁，不合并、不启动 S05。


- [ ] 从 PR #2 的 `review_conflict_probe.cjs` 提炼正确行为回归（旧 probe 的“通过”不能复用）。
- [ ] 先验证本地旧版本、远端新增、远端删除、多端编辑以及改名冲突的失败。
- [ ] 实施冲突提示/草稿保留/三方合并或人工决策；标题/图标加入真正的 revision。
- [ ] UI 双标签测试、后台 Python 画布并发测试；PR 审查合并后解锁 S05。

**2026-11-03 S04 修复与可核实隔离执行（PR #7）：**

- [x] 在 PR #7 源码中复现保存中再次修改标题/图标的数据丢失：旧 PUT 响应把较新的本地标题和图标覆盖回旧值；修复为只有本次保存确认的 `revision/updated_at` 可以推进，仍保持 in-flight 后的新编辑并再次 CAS 保存，旧画布异步响应不得复活已切换的画布。返回管理页时若仍保存中/仍有未处理草稿则禁止丢弃。
- [x] 修复画布列表旧 `setCanvasIcon/setCanvasTitle` 以整画布 PUT（不带 `base_revision`）写入的缺陷，统一走 `patchCanvasMeta` 的 revision-aware POST，避免失败或覆盖节点。
- [x] 新增 `tests/test_canvas_save_races.cjs`（4 项）和 `tests/test_canvas_metadata_routes.cjs`（3 项），连同原有 `tests/test_canvas_conflict_recovery.cjs`（8 项），在**通过 GitHub 连接器取得准确 `0d99a7d950a95992d6c40f1b573e543f92a1ed68` 源码及测试正文后、隔离 V8 执行并使用 Node built-in 的受控等价 shim**，分别 **4/4、3/3、8/8 PASS（合计 15/15）**；四份 JS 文件 V8 整体语法解析 4/4 PASS。**这是在 V8 中运行了仓库实际 JS 逻辑与测试用例的有限执行，不是 `node --test`、浏览器测试或完整项目回归成功。**
- [ ] `tests/test_canvas_revision.py` 8 项、真实 Node.js `node --test tests/test_canvas_*.cjs`、浏览器双标签增/改/删与回滚、完整 Python unittest discover 未执行；正确 HEAD 完整 checkout 受 github.com DNS 阻碍，需要无费用可执行的完整环境。Codex 自动审查缺 environment；不手动触发 Review 或 Actions。

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


## S04 recovery UI increment — 2026-11-02

- S04 PR #7 remains **DRAFT / NOT MERGED**, target `main@081edae763ec73505bed9f82e4274bfeaabc16c3`. Previous S03 merge is not proof that deferred tests passed.
- Added `static/js/canvas-conflict-recovery.js` and loaded it in the classic editor, smart editor and canvas list. A 409 now exposes an actionable, non-destructive panel: export the local JSON draft, create a **new independent canvas** (POST new ID then revision-checked PUT to that new ID only), or inspect the current server canvas in another tab. Original canvas is never automatically overwritten. Conflict drafts remain in localStorage, including across reload; smart-canvas edits after 409 refresh the local recovery snapshot. Metadata conflicts offer an explicit latest-revision CAS retry and keep the patch until success.
- Added `tests/test_canvas_conflict_recovery.cjs` (**8 authored tests**). The exact committed helper and test source were executed in an **isolated V8 mock harness: 8/8 PASS**, covering independent copy, smart settings, failures, metadata CAS and persisted smart-draft discovery. This is **not a Node test run or a browser/UI integration pass**. The three modified application JS files were parsed in V8 (syntax only); Python `tests/test_canvas_revision.py` **8 authored cases NOT_RUN** on full `main.py`. Actual `node --test tests/test_canvas_conflict_recovery.cjs`, browser two-tab races, recovery UI, Windows/LAN/plugin and full Python regression remain **NOT_RUN**.
- The GitHub workflow remains `workflow_dispatch`-only; no Actions runs or paid AI were triggered. The local container still cannot resolve github.com and lacks a full checkout.
- **REVIEW_BLOCKED:** PR #7 has no formal reviews and no inline threads; the Codex connector bot requires creating a repository Codex environment. This requires user-side configuration or an alternative independent reviewer. Do not self-approve or merge S04.
- Further S04 verification: two-tab simultaneous add/edit/delete, same-node delete-vs-edit, title/icon changes, explicit recovery-copy flow, stale draft retention, smart-canvas background saves and cross-tab revisions. S02/S03 deferred full tests remain S08 release blockers.
