# Infinite-Canvas 修复工程 · 新会话交接（Handoff）

## 2026-11-10 实时状态（本节为当前权威记录，覆盖下方旧快照）

- **实时仓库状态**：目标分支为 `main`，HEAD `cf488ab4347f4239cb391fff98befd7ea5774614`。仓库默认分支仍为 `zcode/iteration-01`，没有修改默认分支。初次核查时开放 PR 为 0；PR #37 是最新已合并 PR，Codex Review Summary 对其 HEAD `1035290b2029d2242f771e82b940bf3b73778fbb` 显示 `completed / 0 findings / 0 unresolved`。
- **当前阶段**：S00–S08 的计划内实施均已合并。S03 PR #6 已于 2026-11-02 合并，代码 HEAD `744a3a152cda8503f9ec2296d4217e5d48622b65`，merge SHA `081edae763ec73505bed9f82e4274bfeaabc16c3`；该 HEAD 的 Codex 复审无重大问题，14/14 review threads 已 resolved。PR #6 的有限风险合并记录明确说明这不是 S03 测试 PASS 或发布许可。
- **Linux 全仓原生回归**：S08 §22 记录的完整 checkout 基线为 `main@98a1f7054b6b8a642c9d8ee7b2be2c497f82bde6`，Python 24 个测试文件 **310/310 PASS**、Node 17 个 CJS 文件 **87/87 PASS**，0 FAIL/ERROR/SKIP、退出码 0。当前 `main@cf488ab` 是 PR #37 合并提交，其第一父提交正是 `98a1f705...`；PR #37 只改三份 Markdown 证据/台账文件，没有应用代码、测试代码或依赖变化，因此 §22 的 397 项 Linux 原生结果仍适用于当前代码/测试树。
- **延期测试闭环**：S02 的 `tests/test_access_boundary.py` 28 项、S03 的 45 项 Python 回归均在上述 24 文件的 `unittest discover` 中执行；S03 组成是 storage safety 16、storage handles 13、remote media 8、canvas ZIP budget 5、legacy updater 3。Skill tracking A→B→C 的 `test_skill_upgrade_tracking.py` 13 项也在同一全量结果中通过。这关闭的是 Linux 原生自动化测试缺口，不代表 Windows/设备集成已通过。
- **仍然阻止正式发布的事项**：Windows 自带 Python 3.10 免安装 `run.bat` 实机启动；Windows WinAPI HANDLE、UNC/junction/外置盘安全行为；真实 Chrome 双标签画布/智能画布冲突、草稿恢复、Range 下载；实际使用的 LAN 授权、Chrome 扩展、Photoshop 连接器、ModelScope Token 场景；旧客户端从其现有更新源升级、重启、回滚/反向恢复。FFmpeg 与真实流式媒体兼容也需按 Windows/实际平台验收。
- **发布状态**：`NOT_VERIFIED / DEVICE_VALIDATION_PENDING / RELEASE_BLOCKED`。不因 S00–S08 代码合并或 Linux 397/397 通过而宣布发布。
- **执行约束**：不运行或重跑 GitHub Actions；不触碰真实 Key、用户画布或生产配置；不调用计费 AI；不擅自修改默认分支。下一步应取得隔离设备验收证据，若验收发现新缺陷，再按单阶段、单分支、单 PR 修复。

---


## 历史快照：2026-11-03 S08 状态（已被 2026-11-10 实时状态取代）

- S00–S07 均已 **合并到 main**，S07 PR #10 merge SHA `a8834ef0c9c8c8795b3fd73cc27427ea0912e5be`。历史 S04/S05/S06 的 DRAFT 字样均是过时快照，不要阻止 S08 工作。
- 当前分支 `fix/S08-release-validation`，Draft [PR #11](https://github.com/GuoWen-XX/Infinite-Canvas/pull/11)，base main=S07 merge。必须先取 PR 实时 HEAD，再继续。
- S08 已新增静态发布门禁工具 `tools/check_s08_wheelhouse.py`、`tools/check_s08_release_source.py`，及各自的合成回归、[S08_RELEASE_GATE.md](S08_RELEASE_GATE.md)。
- **已确认发布阻断 A**：仓库内 `python310.dll` 对应 Python 3.10，但 packages 含 cp314 Windows 二进制 wheel；8 项 requirements 锁定依赖仅 2 项有匹配 wheel，缺 PyYAML 6.0.3 且有五项版本不符。基于真实 GitHub 文件名的离线清单镜像检查 FAIL，不是真实 pip 安装。
- **已确认发布阻断 B**：`main.py` 实际 `GITHUB_REPO_URL` 指向 `benkwok1983-cmd/Infinite-Canvas`，`GITHUB_BRANCH` 指向 `zcode/iteration-01`；修复工程目标是 `GuoWen-XX/Infinite-Canvas@main`。静态检查 FAIL；不擅自调整线上更新源或默认分支。
- Python 3.13 本机隔离模拟：wheelhouse 6/6 PASS，updater checker 4/4 PASS；这些都是工具合成单测，不是全仓/Windows 测试。正确 repo HEAD 的完整 Python unittest、Node、Windows、Chrome 双标签、LAN、Photoshop、ModelScope、Skill A→B→C、Codex 自定义目录联调均 NOT_RUN。禁止将 S00–S07 有限风险合并误称为 S08 发布验收通过。
- 约束：不主动运行 GitHub Actions、不手动请求 Codex Review、不触碰真实用户文件/密钥/付费模型。Codex Review bot 曾要求仓库环境设置，因此独立 review 仍可能无结果。
- **下一步**：在真实隔离 Windows 环境重构匹配 CPython 3.10 的完整 wheelhouse，做 pip install/pip check；另行审议更新来源安全迁移；全仓本机/Windows/浏览器/插件验收留完整退出码和日志。发布前门禁不满足，PR #11 不应作为最终验收合并。

---


## S04 增量：离线/5xx 元数据编辑恢复（2026-11-02，最新代码以 PR 实时 HEAD 为准）

- 本轮 GitHub 实时核查：S03 PR #6 已合并至 main@081edae；S04 PR #7 仍 Draft，正式 reviews 0、review threads 0。Codex connector 仍要求先配置仓库 environment。
- 在 **实际 PR #7 代码** 的隔离 V8 中复现：经典编辑器 `patchCanvasMeta` 与画布列表 `persistMeta` 遇网络拒绝或 HTTP 503，均 **没有持久化元数据 patch，也没有展示恢复面板**（四种组合均 saved=0/shown=0）；UI 已先乐观更新，刷新后会丢失改名/图标等修改。
- 已在同一 S04 PR 修复两条路径：所有失败（包括网络/5xx）保存 `canvas_meta_conflict_<id>` 本地恢复记录并展示用户确认后 CAS 重试面板；保留已有 409 路径，不自动覆盖服务器版本。新增 `tests/test_canvas_meta_transport.cjs` 6 项（失败/503/成功 × 经典编辑器/画布列表）。
- 从**精确代码提交 `0cd5ecdeb879d627e943d231d3cec162f5c20213`** 读取真实两份 JS 与新增 CJS 测试，在隔离 V8 + Node built-in shims 中执行 **6/6 PASS**，两份应用 JS 语法解析 **2/2 PASS**。**不是**原生 `node --test`、真实浏览器、完整 Python `main.py` 或设备集成 PASS。S04 `test_canvas_revision.py` 目前有 21 个已编写测试方法，未在完整项目执行。
- 门禁仍为 REVIEW_BLOCKED / TEST_GATE_BLOCKED；不得合并 PR #7、启动 S05 或运行 GitHub Actions。S02/S03 延期实测仍是 S08 发布前阻断项。无真实用户数据、密钥或付费模型调用。


## S04 最新增量：远端 Smart Canvas 合并安全（2026-11-02；优先于下方历史记录）

- 在 PR #7 的实际 `static/js/smart-canvas.js` 中复现旧行为：本地 revision 4 含节点、远端 revision 5 已删除该节点时，`applyMergedServerCanvas` 仍以并集把被删除节点留在本地，并只更新 `updated_at` 而不更新 `revision`。提取真实函数的隔离 V8 复现确认了这两项结果；后续保存必遇 stale CAS 409，界面误显示被删除内容。
- 在同一 PR 实施最小修复：显式跟踪 Smart Canvas 本地未保存状态；远端新 revision 到达时，若有未保存编辑、在途/排队 PUT 或运行中的生成任务，先保存本地恢复草稿并进入人工冲突门；本地干净时精确采用远端节点集合（包含删除），同时推进 revision、时间和设置；过期 GET 及 touch-only 时间戳不触发合并。
- 新增 `tests/test_smart_canvas_remote_merge.cjs` **6 项**，并增强既有保存串行化/竞态 fixture 对 dirty 状态的断言。以 GitHub 实际已提交代码和 6 个 CJS 测试文件在受控 V8 + Node 内置模块 shim 中执行 **41/41 PASS**，4 个 JS 模块语法解析 **4/4 PASS**；这仍**不是**原生 `node --test`、真实浏览器双标签或完整 Python 主程序验收。
- PR #7 仍为 Draft，尚无独立 Review（Codex 环境待配置）；完整 Python `tests/test_canvas_revision.py` 18 项、原生 Node、浏览器及跨平台验证仍未运行。S02/S03 的延期测试继续属于 S08 发布门禁。不得合并 S04、启动 S05、运行 GitHub Actions 或接触真实用户数据/密钥/付费模型。

## 2026-11-03 S04 最新执行记录（本节优先于下方旧快照）

- S04 [PR #7](https://github.com/GuoWen-XX/Infinite-Canvas/pull/7)，工作分支 `fix/S04-canvas-conflicts`。S03 已合并至 `main@081edae763ec73505bed9f82e4274bfeaabc16c3`，S04 尚未合并。
- S04 新增锁内版本化软删除与永久 purge、恢复冲突 409、无版本拒绝、classic 未传 `settings` 时保留原设置、classic/smart 远端删除（404/410）保存本地草稿、smart 保存串行化及新编辑排队。用户画布、真实密钥与付费模型未接触。
- 准确代码 HEAD `6bdbfa13abde05f38f2a449e4ca797b332f690e6`：从 GitHub 读取实际 JS 与测试原文，隔离 V8 mock 中 **33/33 用例通过**、4/4 模块语法解析通过（共 37/37 有限检查）。不是原生 Node、浏览器或完整 Python PASS。新 `tests/test_canvas_revision.py` 共 **18 项已编写，未实际运行**，同样不得称通过。
- **S04 REVIEW_GATE_BLOCKED / TEST_GATE_BLOCKED**：PR #7 Draft，无正式独立 Review；自动审查机器人提示需要为仓库创建 Codex environment。正确 HEAD 完整 Python `main.py`、Node CLI、双标签浏览器和平台联调缺运行证据；当前本地环境 `github.com` DNS 不通，不能把源码静态读取替代执行。不要手动发 `@codex review`，不运行 GitHub Actions。需有可信验证与审查后方可合并并启动 S05。
- S02 28 项及 LAN/Chrome/Photoshop/ModelScope、S03 45 项与 Windows/UNC/FFmpeg/Range/发布更新源等延期验收仍为 **S08 发布门禁**。禁止把 S03 风险例外重复称为通过。

## S04 最新增量：Smart Canvas 并发保存（2026-11-02）

- 以实时 GitHub PR #7 HEAD 为准；本次代码修复提交 `5c98abbc9ca24b8057003b62ed5c7c74589b1233`，之后另有台账提交。
- 在真实仓库 Smart Canvas 保存函数的隔离 V8 执行中，修复前两个 PUT 并发使用同一 revision，409 草稿仅保存旧节点，可能丢失请求期间的新编辑。已在同一 PR 串行化保存，排队使用已确认 revision 的后续 PUT，409/404/410 保存最新草稿，并避免切换画布后的迟到响应污染新画布；临时网络失败也保留本地草稿。
- 新增 `tests/test_smart_canvas_save_serialization.cjs` 5 项。精确 GitHub 代码与 CJS 测试原文经 V8/Node built-in shim 执行合计 **32/32 PASS**，不等于真实 Node、浏览器或完整 Python 回归。正式 Python、双标签及跨平台联调尚未执行。
- PR #7 仍 Draft，0 个正式 Review、0 个行内线程；Codex connector bot 要求先为该仓库创建 environment。无独立审查和完整必要验证，不能合并或启动 S05。S02/S03 的延期验证仍是 S08 发布前阻断。
- 不运行/重跑 GitHub Actions；workflow_dispatch-only；不碰真实 Key、用户画布、付费模型。下一步优先补正确 HEAD 的真实 Node/Python/浏览器测试与独立审查，并在同一 PR 闭环发现的问题。



## 最新实时核查与 S04 续接（2026-11-02；优先于以下历史快照）

- `main@081edae763ec73505bed9f82e4274bfeaabc16c3`：S03 PR #6 于 2026-11-02 15:00:18 UTC 合并，代码 HEAD `744a3a152cda8503f9ec2296d4217e5d48622b65`；独立 Codex Review 0 findings、14/14 threads resolved。维护者明确记录 **DEFERRED_VALIDATION** 风险例外，S03 的 45 项新增测试及完整主程序/Windows UNC/FFmpeg/Range/更新渠道实测尚未执行；不得视为 TEST_GATE_PASS。S02 的 28 项及 LAN/Chrome/Photoshop/ModelScope 延期验收仍须 S08 发布前补齐。
- **当前阶段 S04**：Draft [PR #7](https://github.com/GuoWen-XX/Infinite-Canvas/pull/7)，`fix/S04-canvas-conflicts` → `main`。首批已防止普通画布 409 盲目重试及未保存编辑被同步覆盖；本次进一步新增 `tests/test_canvas_revision.py`，`main.py` revision/CAS、元数据改名兼容、`canvas.js` / `canvas-list.js` / `smart-canvas.js` revision 与冲突草稿保存。每次仍须读取 PR 最新 HEAD，不复用本文 SHA。
- **审查阻断**：PR #7 自动审查评论要求先创建 Codex environment，当前无正式 review；不要误称独立审查通过。**测试阻断**：本地容器 `git ls-remote` 再次证实 `Could not resolve host: github.com`；无法运行正确 HEAD 完整 Python 测试，三份 JS 仅 V8 语法解析 PASS，不能当成 UI PASS。
- **下一步只做 S04**：完整评估并实现可见的冲突恢复/人工决策 UI，双标签新增/删除/重命名、智能画布 409、元数据版本/并发与旧客户端兼容测试；可用环境运行 `python -m unittest discover -s tests -p 'test_*.py' -v` 和浏览器用例，修复发现的问题；取得独立 Review 和无 blocking threads 后才能合并 PR #7。**不得启动 S05。**
- **硬约束**：不运行/重跑 GitHub Actions，不恢复自动触发；不修改真实用户画布、密钥、更新源或默认分支，不调用计费 AI。旧版 updater 仍指向其他仓库分支，S08 发布前必须验证实际部署路径。

---


## 2026-11-02 最新 S03 Review 门禁（独立核查后更新）

- GitHub `main` 在本次核查为 `ae042d816c7881005a6e180a8e38aeaa8f9f07f5`；S03 PR #6（draft、base main）在本次**文档更新前** HEAD 为 `b3b02ae56d9d4c604439337c192b006e59ff1d86`。
- Codex 对该代码 HEAD 的 Code Review Summary 为 **completed / 0 findings / 0 unresolved findings**（2026-11-02 14:07:51 UTC）；已核查并解决全部历史 10 条未关闭线程，当前共 14/14 resolved。此处仅表示**代码审查意见已处理**，不表示执行测试通过；后续提交须重新核对最新 HEAD Review。
- **TEST_GATE 仍 BLOCKED**：S03 新增 45 项测试为源码编写数量，完整 `main.py` / `python -m unittest discover -s tests -p 'test_*.py' -v` 未运行；Windows WinAPI、junction、UNC、FFmpeg、Range/Streaming 真实集成仍未验证。原独立 Linux syscall/Mock 实验不能替代完整项目测试。S02 的 28 项与 LAN/Windows/Chrome/Photoshop/ModelScope 延期验证仍是 S08 发布前阻断项。
- 本次执行容器中 `/mnt/data` 无仓库 checkout，`github.com` DNS 仍失败；不得凭连接器读到源码就宣称已在本地运行全仓。未触发/重跑 GitHub Actions，未使用真实用户文件、Key 或付费 AI。
- PR #6 **不合并，不启动 S04**；先获取可核实的正确 HEAD 离线/完整项目测试与 Windows/UNC 兼容证据，若需有限风险例外须明确列出不可延期的安全验证及 S08 前补测责任，不能把审查 0 findings 当成 TEST_GATE_PASS。


> 记录日期：2026-11-02。**这是执行快照，不是“所有测试通过”的报告。**
> 新会话必须首先读取 GitHub 最新状态；本文中提交 SHA 可能过时。

## 最新复审增量：搜索权限回归测试修复（2026-11-02）

- PR #6 在 HEAD `cb702594aa7169ab2b619cecadab0700b430d9d0` 的 Codex Review **completed / findings=true**；新增 P2 thread `PRRT_kwDOUaWIpM6ysRGk`：原 `0711` 测试给文件所有者保留目录读取权限，无法捕获旧 `O_RDONLY` 回归。此前 6 条待复核的旧线程仍 open；**不得合并/启动 S04**。
- 已在同一 S03 PR 的 `tests/test_storage_handles.py` 把测试目录权限改为 `0311`（所有者仅写+搜索，无读取），非 root 执行前先断言旧 `O_RDONLY|O_DIRECTORY|O_NOFOLLOW` 返回 PermissionError，然后验证 `O_PATH/O_SEARCH` 安全读取及 `dir_fd` unlink；root 环境明确 skip 权限断言，不再产生假阳性。
- **独立真实 POSIX 权限 fixture**：当前容器以 uid 1000 执行同等操作，确认旧 O_RDONLY 失败、O_PATH read + dir_fd unlink 成功；这不是 GitHub 分支完整 `tests/test_storage_handles.py` 的实际运行，也不是 Windows/UNC 或主程序全量 PASS。root uid 0 的同等 fixture 不具备验证意义（确实误通过），已排除。
- 后续必须核查最新 HEAD 独立复审、7 条尚未关闭线程及 S03 45 项实际全仓测试；旧 updater 实际发布源仍指向另一仓库分支，S08 发布前必须解决。GitHub Actions 0 次新增、无真实 Key/数据/计费模型。

## 最新执行增量（2026-11-02；覆盖下方旧版 HEAD 快照）

- S03 PR #6 `5a49add` 的 Codex Code Review 已完成，**发现 3 条新增 blocking threads**：旧版本 updater 首次升级丢失 root `storage_guard.py`（P1，`PRRT_kwDOUaWIpM6yrs0v`）；POSIX FIFO 阻塞 `os.open`（P2，`PRRT_kwDOUaWIpM6yrs00`）；If-Range 未校验导致旧/新文件错误续传（P2，`PRRT_kwDOUaWIpM6yrs04`）。旧 TOCTOU P2 `PRRT_kwDOUaWIpM6yq3uo` 仍 open，其他初轮 4 条仍 resolved。**共 4 条须在后续独立复审核对后解决。**
- 已在 **同一 S03 分支/PR** 提交实质修复：保留原 root `storage_guard.py`，新增字节一致的 `static/storage_guard.py` 及 `main.py` 缺 root helper 时的安全导入回退（S02 老 updater 仍会下载 `static/*`）；新版 staging 校验 root/static 同步。POSIX 最终文件打开加 `O_NONBLOCK` + `fstat` 文件类型拒绝；HTTP Range 为已打开句柄生成 ETag/Last-Modified 并检查 `If-Range`，不符时完整 200。
- 回归测试已**编写合计 42 项**：`tests/test_storage_safety.py` 16、`tests/test_storage_handles.py` 10、`tests/test_remote_media_security.py` 8、`tests/test_canvas_zip_budget.py` 5、`tests/test_s03_legacy_updater.py` 3；本轮新增 9 项覆盖 FIFO（2）、If-Range（4）、旧 updater（3）。**尚未在完整仓库运行**；此前独立提取 7/7 仅适用于旧修复方案的 POSIX 子集，不代表新 42 项通过。
- 必须重新取得 PR #6 **本轮最终提交 HEAD** 的复审结论，若 Code Review 还有 P1/P2 就继续同 PR 修复、补回归、复审；在无 unresolved blocking、可信正确 HEAD 验证和风险门禁前 **不得合并或启动 S04**。本次仅使用 GitHub 连接器提交代码/文档，没有重新运行 Actions、没有真实 Key、用户画布或付费模型调用。
- 本地 `git ls-remote` 仍报告 `Could not resolve host: github.com`。无需强求 Actions，优先寻求不收费的正确 HEAD 执行环境；不能虚构完整 unittest 或 Windows/UNC 实测。S02 延期验收仍须在 S08 发布门补齐。

## 最新复审增量：Windows 根身份 + POSIX 搜索权限（2026-11-02）

- `216cec7` 的 Codex 复审 **completed / findings=true / unresolved=true**；新增两项 P2：Windows 校验后重新 `realpath(root)` 会接受 root/junction 重绑（`PRRT_kwDOUaWIpM6yr_6S`）；POSIX 使用 `O_RDONLY` 打开可搜索但不可列目录的祖先（如 0711）会破坏合法访问（`PRRT_kwDOUaWIpM6yr_6f`）。
- 已在同一 S03 PR #6 进一步修改：Windows 提前固定 `trusted_root`，pin 可信根 HANDLE 与文件/删除 HANDLE，不重新解析授权根；POSIX 使用 `O_PATH` / `O_SEARCH` 逐级访问可搜索目录（平台支持时），仍禁止跟随符号链接。根目录 `storage_guard.py` 与 `static/storage_guard.py` 已同步更新，防止旧版本首次升级回退到不安全代码。
- 增加 POSIX 根目录换链、0711 目录搜索/删除与 Windows 固定根比较 Mock 3 项测试；本阶段新增 **45 项源码已编写，未完整执行**（storage safety 16、handles 13、remote 8、ZIP 5、legacy updater 3）。未执行 Windows 真实 junction/UNC，未经审查不得视作已过门禁。
- 安全发布的重要限制：现有 `main.py` 的自动更新源硬编码为 `benkwok1983-cmd/Infinite-Canvas@zcode/iteration-01`，而本次 PR 合并目标为 `GuoWen-XX/Infinite-Canvas@main`，因此只有修复代码实际被发布到客户端使用的源时旧 updater 才能收到 `static/storage_guard.py`。这是 S08 更新渠道验收的明确阻断事项，不能将“兼容策略已写”称为“老客户端已经能自动升级”，也不要擅自改线上发布源。
- 下一步：对最终 HEAD 请求独立 Codex Review；核对旧 TOCTOU、首轮三条新发现、Windows/权限两条新发现及全部线程状态，有新问题必须继续同 PR 修复。完整项目、Windows/UNC、Chrome/Photoshop/LAN 等仍缺证据，S02 的延期联调必须在 S08 发布前补齐。禁止 GitHub Actions、真实用户画布、真实 Key、付费模型。

## 第三次复审与权限测试修复（2026-11-02）

- Codex 对 `cb702594aa7169ab2b619cecadab0700b430d9d0` 的审查 **completed / findings=true / unresolved=true**。新增 P2 `PRRT_kwDOUaWIpM6ysRGk`：此前所谓 0711 搜索权限测试仍由拥有目录读取权限的所有者执行，不能证明修复。
- 已在 `tests/test_storage_handles.py` 将该 fixture 修订为可复现测试：非 root 时 chmod 0311（拥有者只有 write/search）；root 时在仅含临时 fixture 的子进程 `setgroups([]); setgid(nobody); setuid(nobody)` 并使目标目录权限 0733（other write/search，无 read）。子进程先断言**旧 `os.O_RDONLY|O_DIRECTORY|O_NOFOLLOW` 打开必然 PermissionError**，随后使用源码相同的 `storage_guard.open_scoped_file` 安全读取，并使用 `unlink_scoped_file` 删除临时测试文件。不能把这项源码更新冒充执行 PASS。
- 本阶段回归代码总数仍为 **45**，完整项目、Windows/UNC/LAN/插件/FFmpeg 未完成。所有 7 条未解决审查线程需最新 HEAD 核验后才能逐条标记解决。S03 PR #6 仍为 draft，未合并；切勿提前开始 S04，不要运行 Actions 或真实/计费链路。

## 最新权限测试兼容复审与修复（2026-11-02）

- Codex 对 `5ae5f710b78afc83317333c9884fb5d93fefe835` 的复审 `completed / findings=true / unresolved=true`：新增 2 条 P2，`PRRT_kwDOUaWIpM6ysc4e`（先降权导致私有 Python 解释器无法启动）、`PRRT_kwDOUaWIpM6ysc4n`（私有 TMPDIR 祖先不能被 nobody 搜索）。这两条指向**测试环境 fixture**，不是在 S03 生产代码中发现新的安全缺陷。
- 已在同一 PR 修复：不使用 `preexec_fn`，先以当前身份启动 Python `-I`、明确导入位于专用测试目录的安全模块，再在子进程脚本中降权；为完整测试 fixture 选用 /tmp 且检查其真实祖先允许搜索，不 chmod 用户配置 TMPDIR，使用 TemporaryDirectory 自动清理并恢复目标目录权限。非 root 测试继续使用 0311，root 测试使用 0733 + 降权 nobody；同一受限进程先断言旧 O_RDONLY 失败，再调用真实 secure handle 读取/删除临时文件。
- 下一步必须先取最新提交 HEAD 并 @codex review；若通过审查才逐项处理 9 条 review 线程，且正确 HEAD 全量验证 / Windows / UNC 仍缺时不得误报 S03 通过。S03 回归 45 项仍为**编写数量**，并非全部执行。先前独立 Linux euid1000 权限系统调用验证不代表全仓 PASS。PR #6 仍 draft、未合并，S04 不得提前开始。

## 一、仓库、分支、已完成阶段

- 仓库：[GuoWen-XX/Infinite-Canvas](https://github.com/GuoWen-XX/Infinite-Canvas)。
- **所有修复 PR 的目标分支是 `main`**。仓库默认分支仍为 `zcode/iteration-01`，**不要误将默认分支的 CI 成功当作 main 或修复分支的测试结果，也不要擅自调整默认分支**。
- 计划、门禁、技术方案：`docs/remediation/2026-11-02/{WORKPLAN.md,REVIEW_GATE.md,TECHNICAL_PLAN.md}`。
- S00 [PR #3](https://github.com/GuoWen-XX/Infinite-Canvas/pull/3) 已合并。
- S01 [PR #4](https://github.com/GuoWen-XX/Infinite-Canvas/pull/4) 已合并。
- S02 [PR #5](https://github.com/GuoWen-XX/Infinite-Canvas/pull/5) 已合并；`main` 在本次 S03 启动时为 `ae042d816c7881005a6e180a8e38aeaa8f9f07f5`。**S02 是有限风险例外合并**：正确分支下完整 `tests/test_access_boundary.py` 28 项、全套后端测试和 Windows/LAN/Chrome/Photoshop/ModelScope 兼容联调未实际执行，必须在 S08 发布门禁补齐。放行解释见 [PR #5 评论](https://github.com/GuoWen-XX/Infinite-Canvas/pull/5#issuecomment-6577109854)。
- 现阶段 S03：[PR #6](https://github.com/GuoWen-XX/Infinite-Canvas/pull/6)，工作分支 `fix/S03-storage-ssrf`，目标 `main`。编写本文时仍是 **draft / open / not merged**；**务必先重新读取 PR head、Codex Review Summary 和所有 threads**。
- S04–S08 尚未实施。

## 二、S03 已实现的代码与测试

S03 目标：SEC-03 本地存储路径越权、SEC-04 SSRF/重定向、SEC-05 ZIP 资源限制。

1. 存储访问：`main.py` 原 `realpath/commonpath` 用于软链接路径越权检查；已修复根内软链接别名删除误删目标的问题；新增独立文件 `storage_guard.py`，真正打开文件时按 root 限制（POSIX：从根的目录 FD 链逐级 `O_NOFOLLOW`、最后使用 pinned file FD，删除按 pinned parent dir_fd；Windows：文件打开后 `GetFinalPathNameByHandleW` 核对实际句柄目标，删除使用 WinAPI HANDLE）；`main.py` 的存储 GET、共享文件 GET、`/api/download-output` 本地分支、素材 ZIP、workflow ZIP、媒体预览/JPEG/视频输入改用受约束句柄。文件发送以 `StreamingResponse` 保留单段 HTTP Range。**Windows 真实句柄/UNC 删除行为未验证，必须做平台联调**。
2. 新文件部署：自更新 `update_allowed_file` 允许 `storage_guard.py` 且 `validate_staged_update` 对新模块做存在性/编译验证，避免 main.py 更新后找不到依赖。
3. 远程媒体：`validate_remote_media_target` / `open_safe_remote_media_stream` 检查公网 DNS 和每跳重定向，禁用环境代理，自定义 urllib3 HTTP/HTTPS connection 在 TCP 建连后、HTTP 请求和 TLS 握手前拒绝实际 socket peer 非公网 IP。请复查 HTTPS SNI/证书、真实代理设置及全量调用方。
4. ZIP：canvas-assets 导出使用 `SpooledTemporaryFile` + 流式响应，250 文件、单项 200 MiB、总输入 512 MiB、ZIP 输出 550 MiB 配额；本地文件按实际读取字节计量。workflow ZIP 同样对素材使用 pinned 文件句柄与单项/总量配额。
5. 当前新增 S03 测试文件：`tests/test_storage_safety.py` **12 项**，`tests/test_storage_handles.py` **8 项**，`tests/test_remote_media_security.py` **8 项**，`tests/test_canvas_zip_budget.py` **5 项**，总计 **33 项**。这些测试**未在完整仓库主程序中跑完**；不能把“已编写”当成“通过”。
6. 已有一份独立的 POSIX FD 操作提取验证：`python -m unittest -v /mnt/data/s03_handle_repro/test_handle_races.py` 的结果 `Ran 7 tests / OK`，**不代表 GitHub 仓库 33 项实际 PASS**。原代码和风险记录见 `S03_AUDIT.md`、`S03_TOCTOU_HANDLE_PLAN.md`。

## 三、审查历史与未解决风险

PR #6 初轮 Code Review 曾有 5 个安全线程：P1 DNS rebinding、P1 删除别名误删原目标、P2 文件句柄 TOCTOU、P2 ZIP stale size、P2 redirect 测试 DNS mock 错误。其中 DNS、别名、ZIP、DNS mock 四项已有修复并标记 resolved。

第五项 P2 TOCTOU 线程 ID：`PRRT_kwDOUaWIpM6yq3uo`。**本次新代码已做 pinned-FD / Windows HANDLE 修复，但仍须等待最新 HEAD 独立 Codex 复审、验证测试和核查是否产生新 P1/P2 才能关闭**。不要把旧提交 Review Summary 上的 “completed” 当成新提交审查通过。尤其需要检查新的 `storage_guard.py` 跨平台行为、Image.open/FFmpeg 兼容性、HTTP Range、文件句柄释放、自动更新回滚的完整性。

如 review 报新 findings，严格同一 PR #6 修复、加失败回归、提交、`@codex review` 复审，再检查 Review Summary 最新 HEAD、全部 threads 与真正测试证据。

## 四、测试设施和成本约束

- **绝不自动启动或重跑 GitHub Actions**。用户此前授权的唯一一次手动 Actions [#41439808653](https://github.com/GuoWen-XX/Infinite-Canvas/actions/runs/41439808653) 成功 78 项，但检出 `zcode/iteration-01@bb778e26`，**不是 S02/S03 的正确 HEAD**；不得复用绿灯。已有 Actions workflow 为 `workflow_dispatch` only。
- 先前本地执行容器对 github.com DNS 解析失败；Vercel sandbox 创建返回 403，故真实完整仓库 checkout 尚无证据。若新会话具备可用的安全执行环境，应在**PR #6 精确 HEAD**运行 `python -m unittest discover -s tests -p 'test_*.py' -v`、安全独立测试、启动器/浏览器/Windows-UNC 兼容验证；记录命令、SHA、返回码和日志。禁止虚构全套测试结果。
- 不修改真实用户画布、Key、生产配置；不调用计费生图或真实恶意网络目标。测试网络、DNS/metadata、ZIP 等全部 Mock 或本地临时 fixture。
- 为避免技术环境无穷期阻断，可以公开评估有限风险与延期验收，但**不得对已知阻断性安全问题无条件放行**，且 S08 发布门必须补齐 S01/S02/S03 遗留真实测试。

## 五、后续阶段依序推进

| 阶段 | 工作 |
|---|---|
| S03 | 最新 HEAD 独立复审 → 逐条解决 blocking threads → 正确 HEAD 可信验证 → 按门禁合并 PR #6 main → 更新 WORKPLAN 合并 SHA |
| S04 | 画布并发数据丢失 R1、标题/图标 revision R6；两标签增改删/重命名冲突、保留草稿与 409，独立 PR |
| S05 | Skill frontmatter 未知字段和编辑 body 稳定 R2、variant ID 稳定 R7，独立 PR |
| S06 | PyYAML 生产依赖 R4、GitHub Skill tracking_ref 与 commit_sha R3，ZIP/覆盖/更新回滚，独立 PR |
| S07 | Codex 自定义存储媒体路径 R5，Mock Codex，独立 PR |
| S08 | 全套 Python/JS/浏览器、Windows/Linux/macOS、LAN/Chrome/Photoshop/ModelScope、自动更新/安装发布质量门与残余风险报告；**发布前必须补完之前延期的联调** |

## 六、直接复制到下一会话的提示词

```text
继续处理 GitHub 仓库 GuoWen-XX/Infinite-Canvas 的无限画布 S00-S08 修复工程。先实际读取 main、PR #6 最新 HEAD、最新 Codex Review Summary、所有 review threads，并读取仓库 docs/remediation/2026-11-02/HANDOFF_NEXT_SESSION.md、WORKPLAN.md、REVIEW_GATE.md、S03_AUDIT.md 和 S03_TOCTOU_HANDLE_PLAN.md（handoff 在 fix/S03-storage-ssrf 分支，若 PR #6 已合并则在 main）。不要用旧 SHA 代替实时状态。

S00–S02 已合并；S02 以明确延期完整测试/Windows/LAN/Chrome/Photoshop 联调的有限风险例外合并，必须在 S08 发布前补齐。S03 draft PR #6 已实施存储软链接/TOCTOU pinned 文件句柄修复、连接时公网 peer IP 检查防 DNS rebinding、ZIP 限额与分块复制，新增 S03 测试 33 项。旧评审 5 条中 4 条已 resolved；文件句柄 TOCTOU P2 thread PRRT_kwDOUaWIpM6yq3uo 本次已提交修复但尚未经过最新 HEAD 验证。请先核对最新 HEAD 审查：如有 P1/P2，直接同 PR 修复并补回归、请求 Codex 最新 HEAD 复审、继续检查结果；若独立审查、必要可信验证及风险门禁已满足，立刻合并 PR #6 到 main 并记录 merge SHA，然后创建独立 S04 分支/PR，依序持续推进 S04–S08。每阶段修改后提交、主动检查 review/threads、解决后继续，不要反复等我催促。

不自动触发/重跑 GitHub Actions；之前单次授权已消耗在错误默认分支，GitHub 仓库默认 zcode/iteration-01 不等于目标 main。禁止真实 Key、用户数据、计费 AI 调用。完整 repo 测试环境先前因 GitHub DNS 与云 sandbox 403 不可用；继续寻找无额外费用的执行办法，但绝不把隔离 Mock 当成全套 PASS；可文档化明确可接受的延期验收风险，**不能跳过已确认的阻断性安全缺陷**。及时在 GitHub 实际操作并更新仓库台账/交接文档。 
```

## 七、链接

- [S03 PR #6](https://github.com/GuoWen-XX/Infinite-Canvas/pull/6)
- [S02 PR #5](https://github.com/GuoWen-XX/Infinite-Canvas/pull/5)
- [S03 review thread](https://github.com/GuoWen-XX/Infinite-Canvas/pull/6/files)
- 本文：`docs/remediation/2026-11-02/HANDOFF_NEXT_SESSION.md`。


## S04 recovery UI increment — 2026-11-02

- S04 PR #7 remains **DRAFT / NOT MERGED**, target `main@081edae763ec73505bed9f82e4274bfeaabc16c3`. Previous S03 merge is not proof that deferred tests passed.
- Added `static/js/canvas-conflict-recovery.js` and loaded it in the classic editor, smart editor and canvas list. A 409 now exposes an actionable, non-destructive panel: export the local JSON draft, create a **new independent canvas** (POST new ID then revision-checked PUT to that new ID only), or inspect the current server canvas in another tab. Original canvas is never automatically overwritten. Conflict drafts remain in localStorage, including across reload; smart-canvas edits after 409 refresh the local recovery snapshot. Metadata conflicts offer an explicit latest-revision CAS retry and keep the patch until success.
- Added `tests/test_canvas_conflict_recovery.cjs` (**8 authored tests**). The exact committed helper and test source were executed in an **isolated V8 mock harness: 8/8 PASS**, covering independent copy, smart settings, failures, metadata CAS and persisted smart-draft discovery. This is **not a Node test run or a browser/UI integration pass**. The three modified application JS files were parsed in V8 (syntax only); Python `tests/test_canvas_revision.py` **8 authored cases NOT_RUN** on full `main.py`. Actual `node --test tests/test_canvas_conflict_recovery.cjs`, browser two-tab races, recovery UI, Windows/LAN/plugin and full Python regression remain **NOT_RUN**.
- The GitHub workflow remains `workflow_dispatch`-only; no Actions runs or paid AI were triggered. The local container still cannot resolve github.com and lacks a full checkout.
- **REVIEW_BLOCKED:** PR #7 has no formal reviews and no inline threads; the Codex connector bot requires creating a repository Codex environment. This requires user-side configuration or an alternative independent reviewer. Do not self-approve or merge S04.
- Further S04 verification: two-tab simultaneous add/edit/delete, same-node delete-vs-edit, title/icon changes, explicit recovery-copy flow, stale draft retention, smart-canvas background saves and cross-tab revisions. S02/S03 deferred full tests remain S08 release blockers.


## 2026-11-02 S04 latest incremental handoff — classic GET/touch revision race

- **Current stage**: S04 PR #7 `fix/S04-canvas-conflicts` → `main`, still DRAFT / REVIEW_BLOCKED / TEST_GATE_BLOCKED. Main at last verification: `081edae763ec73505bed9f82e4274bfeaabc16c3`. Re-read both HEADs live next run.
- **New substantive fix**: `static/js/canvas.js::openCanvas` previously paired stale GET nodes at revision 4 with revision 5 returned by a later `touch` after another editor's save. This could cause an undetected same-ID overwrite on the next PUT. Isolated old-function reproduction confirmed the unsafe pairing; new `tests/test_canvas_open_touch_race.cjs` had expected pre-fix **1 FAIL / 1 PASS**. The fixed code re-fetches the entire canvas if touch reports a different revision; it does not promote only the CAS token, and re-checks pending local edits after awaits.
- **Exact-code limited verification**: on code commit `203705615a86574eed6cb3e714171a9fea572a6c`, fetched 4 application JS files and 7 CJS test suites directly from GitHub; isolated V8 with Node built-in shims **43/43 PASS**, 4/4 syntax parses PASS. **Not** native `node --test`, two-tab browser, full Python `main.py`, Windows, or complete integration PASS. The next documentation-only commits do not change tested application code.
- **Review**: PR #7 has 0 formal reviews and 0 inline threads at last read; Codex bot requires repository environment configuration. Do not self-approve or merge without an independent review / explicit maintainer decision and sufficient real test evidence.
- **Outstanding**: correct-ref Python 18 cases and full unittest discover, native Node CJS suites, real browser two-tab + Smart Canvas workflows, S02 28 tests/LAN/Chrome/Photoshop/ModelScope, S03 45 tests/Windows UNC/FFmpeg/Range/legacy updater before S08 release. No GitHub Actions, paid AI, user files, or real credentials were used. S05 remains locked.


## S04 最新增量交接 — classic save 网络失败/离开页面保护（2026-11-02）

- 当前阶段 **S04 Draft PR #7**，目标 `main@081edae763ec73505bed9f82e4274bfeaabc16c3`，每轮重新读取实时 HEAD。S03 PR #6 已合并；本文件前文旧 S03 草稿状态是历史记录，不能用于当前 gate。
- 从精确旧代码 HEAD `89af5ac4` 的 `static/js/canvas.js` 复现两条 R1 丢草稿路径：保存请求尚未完成时返回管理页直接导航；网络异常时 `saveCanvas` 不做本地草稿持久化。两项旧行为隔离 V8 测试 FAIL。
- 同一 PR 提交修复 `206388b5aaaa8ac622869983629a85502d7e0d3f`，新增回归 `tests/test_canvas_navigation_failure.cjs` 于 `a792a08484b129333125fab95d7fbe9f8cc07d65`。后端业务未改。最新编辑器在保存中/脏数据/冲突状态返回时展示草稿恢复并阻止丢数据；beforeunload 保存并请求确认；传输异常保留草稿并进入人工恢复门，不盲目 CAS 重试。
- 从准确 `a792a08` 读取实际 JS/CJS，独立 V8 4/4 行为检查 PASS，2/2 文件语法检查 PASS。**不等于原生 `node --test`、完整 Python 主程序集成、真实浏览器/Windows 测试**。正确 HEAD 需运行新增 CJS 和既有 8 份 CJS 回归，并执行 `tests/test_canvas_revision.py`（已编写 21 项）及全量测试。
- 远端独立审查尚缺 Codex repository environment，PR #7 继续 REVIEW_BLOCKED / TEST_GATE_BLOCKED；不能合并，S05 仍锁定。GitHub Actions `workflow_dispatch` only，未触发；不使用真实 Key、用户画布或付费 AI。


## S04 连续元数据失败草稿合并（2026-11-03）

- 真实旧函数隔离复现：离线先改名再改图标，两次失败共用 canvas_meta_conflict_<id> 键，后一次覆盖前一次，恢复草稿仅剩 icon，丢失 title。
- 已在 classic patchCanvasMeta 与列表 persistMeta 修复：按字段合并既有失败草稿，同字段最新编辑优先；localStorage 不可写时恢复面板明确警告，并提供属性 JSON 导出；更新 HTML 资源版本避免旧缓存。
- 扩展 tests/test_canvas_meta_transport.cjs，由 6 至 12 项。实际从 PR #7 分支读取最新应用 JS 与 CJS 测试，在隔离 V8 + Node built-in shims 运行 **12/12 PASS**，4 个 JS 文件语法解析 **4/4 PASS**；不是原生 node --test、完整 Python、真实浏览器或 Windows PASS。
- S04 独立 Review 仍未取得，完整测试门禁未过；PR #7 保持 Draft，S05 不启动。GitHub Actions 保持 workflow_dispatch-only、未触发；没有真实 Key、用户画布或计费 AI。


## S04 回收站恢复 CAS 增量与有限验证（2026-11-03 UTC，后续以实时 HEAD 为准）

- PR #7 代码 HEAD `87ae3378b96c6e45cd956e43940430dc47a9790a`；`main@081edae763ec73505bed9f82e4274bfeaabc16c3`，PR Draft、正式 reviews 0、inline review threads 0。前文把 S03 称为 Draft 的内容为历史快照：S03 PR #6 已合并，延期验证未完成。
- 自前一记录的 `c9dc5fae33132cc7a875f089c9e62c7310813532` 起，S04 又有 5 次提交，变更 `main.py`、`static/js/canvas.js`、`static/js/canvas-list.js`、`tests/test_canvas_revision.py`，新增 `tests/test_canvas_restore_cas.cjs`。本阶段新增了回收站恢复的 revision CAS：后端在画布锁内检查所选回收站条目版本；经典编辑器与画布列表均携带所观察到的 revision，缺失 token 拒绝请求，409 时刷新回收站，不静默恢复过期条目。永久删除/软删除 CAS 仍按先前实现。
- 本轮通过 GitHub 连接器读取**准确代码 HEAD** 的两份实际 JS，抽取原文 `restoreCanvas` 函数在隔离 V8 + mock fetch 中运行成功、缺少 revision、HTTP 409、HTTP 503 四种情形 × 经典/画布列表，共 **8/8 PASS**；两份完整 JS 原文经 V8 `new Function` **2/2 语法解析 PASS**。**这是提取函数行为与语法检查，不是仓库原生 `node --test`、浏览器双标签或完整 Python 主程序集成 PASS**。
- `tests/test_canvas_revision.py` 当前有 **24 个已编写的 `test_` 方法，未在完整 `main.py` 运行**；新增 CJS 文件的 6 个用例亦未执行原生 Node CLI。完整 Python unittest discover、原生 Node、浏览器双标签、Windows/LAN/插件联调仍缺正确 HEAD 的可信执行证据。GitHub Actions workflow 保持 `workflow_dispatch` only，未触发。
- **REVIEW_BLOCKED / TEST_GATE_BLOCKED**：没有独立审查结论，Codex environment 配置仍需处理；PR #7 保持 Draft，**不得合并或启动 S05**。S02 28 项、S03 45 项及对应平台验证仍为 S08 发布前阻断。未使用真实用户画布、密钥或计费 AI。
