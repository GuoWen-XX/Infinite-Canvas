# S08 发布前验收门禁与证据（2026-11-03）

> 基线：S07 已合并 `main@a8834ef0c9c8c8795b3fd73cc27427ea0912e5be`。本文件记录**已核实证据与尚未执行的验证**。不等于发布许可。
> 不运行 GitHub Actions；不访问真实 API Key、用户画布或付费模型。正式联调须在隔离副本中进行。
> **最新交接与职责划分**：参见 [S08_FINAL_ACCEPTANCE_HANDOFF.md](S08_FINAL_ACCEPTANCE_HANDOFF.md)。已知代码修复完成，最新合并后 `main@98a1f705` 原生 Python **310/310 PASS**、Node.js **87/87 PASS**（2026-11-09，详见 §22；此前历史见 §20）；Windows/设备端真实联调仍待验证。最终发布状态仍 **DEVICE_VALIDATION_PENDING / RELEASE_BLOCKED**。

## 1. 可选依赖安装脚本的 wheel 清单核查（不作为免安装画布发布阻断）

已从 GitHub S08 分支读取 `requirements.txt`、`python/` 与 `packages/` 实际文件名：仓库自带 `python310.dll`（Python 3.10），`packages/` 目前有 22 个 wheel，但多项与锁定依赖不符。仅以真实清单的文件名、锁定版本和 DLL 名构造离线镜像夹，调用 `tools/check_s08_wheelhouse.py --root <mirror> --json`，得到 **8 个直接依赖中 2 匹配、6 不匹配**。这是静态文件名/标签审计，**尚未执行 pip，也未核验 wheel 内容完整性**。它只反映可选手动安装脚本所用缓存包的状态；`run.bat` 不调用该脚本，不能据此宣称便携画布启动失败或阻止阶段 PR 合并。

| 锁定依赖 | packages 实际 wheel | 结论 |
| --- | --- | --- |
| fastapi==0.141.1 | fastapi 0.136.1 | 版本不符 |
| uvicorn==0.52.1 | uvicorn 0.46.0 | 版本不符 |
| requests==2.34.2 | requests 2.33.1 | 版本不符 |
| python-multipart==0.0.32 | python-multipart 0.0.27 | 版本不符 |
| pillow==12.3.0 | pillow 12.2.0 cp314-win_amd64 | 版本与 Python ABI 均不符 |
| PyYAML==6.0.3 | 未提供 | 缺失 |
| httpx==0.28.1 | httpx 0.28.1 py3-none-any | 直接锁定项匹配 |
| pydantic==2.13.4 | pydantic 2.13.4 py3-none-any | 直接锁定项匹配 |

额外转移依赖风险：`charset_normalizer-3.4.7-cp314-cp314-win_amd64.whl` 和 `pydantic_core-2.46.4-cp314-cp314-win_amd64.whl` 无法供 Python 3.10 直接使用。**即使 8 个直接依赖全部匹配，也仍需 pip 实际解析所有传递依赖。**

**可选维护事项（不作为 S08 合并前置条件）：** 如确需维护手动依赖安装脚本，先确定正式 Windows Python 版本（当前随仓库是 3.10），按已锁定 `requirements.txt` 使用匹配 Python ABI/平台重新准备完整离线 wheelhouse；不得为了让旧包通过而悄悄降级锁定版本。准备完后依次执行：

```bash
python tools/check_s08_wheelhouse.py --json
python -m pip install --no-index --find-links=packages -r requirements.txt
python -m pip check
```

只有实际需要验证**可选依赖安装/修复流程**时才执行上述 pip 命令，且必须在一次性隔离环境中运行；不得改用户现有 `python/` 或真实安装目录。**正常画布验收以原始便携包直接启动和功能回归为准，不强制运行 pip。**

## 2. S08 核查工具和本轮可核实结果

- [x] 创建 `tools/check_s08_wheelhouse.py`：只读取文件名、版本、Python tag/ABI tag、bundled `python3xx.dll`；可输出 JSON，任一直接锁定项缺失、不符返回非零退出码。
- [x] 创建 `tests/test_s08_wheelhouse.py`：6 项合成 fixture 测试（Python 3.10 检测、缺包、版本、cp314 ABI、不锁定依赖、兼容 ABI）。
- [x] 在本机 Python 3.13 对该检查器的同等隔离版本执行 `python -m unittest -v /mnt/data/test_s08_wheelhouse.py`：**6/6 PASS**；并用来自仓库内容的镜像文件名执行静态审计，返回 FAIL（命中六个直接依赖问题）。**这些不是完整 repo checkout 上的测试**。
- [x] 2026-11-09 已在完整 checkout 中运行 `python -m unittest discover -s tests -p 'test_*.py' -v`，24 个 Python 文件 **310/310 PASS**，退出码 0；修复测试夹具后对合并后的 `main` 复测通过，见 §20。
- [x] 2026-11-09 在完整 checkout 原生执行 `node --test tests/*.cjs`，16 个 CJS 文件 **86/86 PASS**，退出码 0，见 §20；这不代表 Windows/真实浏览器已验收。
- [ ] 免安装场景下在隔离 Windows 副本直接运行 `run.bat`，核实服务启动、页面访问与核心功能。`安装依赖.bat` 属于可选维护入口，不作为正常启动的必经测试，也不要求重新安装依赖。
- [ ] 双标签 Chrome：画布增/改/删、元数据改名、409 草稿/恢复，智能画布并发保存、文件下载与 Range 断点续传。
- [ ] LAN、Photoshop/Chrome 扩展、ModelScope Token 的授权/跨域场景在可控测试账号进行，禁止把真实用户 token 放入日志或测试夹。
- [ ] S02 28 项与 S03 45 项延期回归、Windows UNC/junction、Skill 版本追踪 A→B→C、Codex 自定义媒体路径真实 Windows 安全验收。
- [x] 核对并修复本仓库新版 `main.py` 更新源：PR #12 更新 URL，收尾修复同步将分支更新为 `main`，共同使 GitHub 更新目标指向 `GuoWen-XX/Infinite-Canvas@main`。原安装中的旧客户端仍可能指向旧来源，**真实升级迁移 NOT_RUN**；未修改默认分支。
- [ ] 必须有发布前残余风险报告；未消除的高风险失败或缺失的必要测试阻止发布。

## 3. 自动更新源一致性：源码修复已提交，旧客户端迁移仍需注意

已从 S08 基线的 `main.py` 实际源码读取：
- `GITHUB_REPO_URL = "https://github.com/benkwok1983-cmd/Infinite-Canvas"`
- `GITHUB_BRANCH = "zcode/iteration-01"`

修复工程实际合入 `GuoWen-XX/Infinite-Canvas@main`。**上文为修复前基线**：当时 updater 仍指向旧来源，存在覆盖安全修复的风险。PR #12 将仓库 URL 改为 `GuoWen-XX/Infinite-Canvas`，但保留旧 `GITHUB_BRANCH`；S08 收尾复核发现并在随后的收尾 PR 将该分支常量修正为 `main`，两者合并后新版 updater 才完整指向 `GuoWen-XX/Infinite-Canvas@main`；**旧客户端仍保留其已有更新源，不能把新代码中的修改误称旧版客户端已自动升级**。未变更仓库默认分支，未发布外部安装包。

- [x] 新增 `tools/check_s08_release_source.py`：使用 `ast.parse` 静态读取更新器常量（绝不 import/启动 `main.py`），将 repo/branch 与明确期待的发布目标进行比对；不符返回失败退出码。
- [x] `tests/test_s08_release_source.py` 4 项模拟测试：正确源通过，错误仓库、错误分支、动态未审计常量都必须拒绝。Python 3.13 在本地等价实现执行 **4/4 PASS**，仅模拟/静态检查；不代表真实旧客户端升级成功。
- [x] 将仓库当前已确认的常量在本地镜像执行，结果 **FAIL**。这不是一个可以仅标“延期测试”就允许发布的问题；必须先制定/执行实际更新渠道切换或安全禁用策略，并从真实旧客户端到目标包完整验证后方可解除阻断。

```bash
python tools/check_s08_release_source.py --expected-repo GuoWen-XX/Infinite-Canvas --expected-branch main --json
```

**2026-11-04 更新（S08 修复及收尾分支）：** PR #12 更正了 GitHub 仓库 URL，收尾复核又发现并修正了 `GITHUB_BRANCH` 未同步的遗漏。包括 3 条派生下载地址在内，合并这两次修复后才会统一指向 `GuoWen-XX/Infinite-Canvas@main`；扩展 `tests/test_s08_release_source.py` 静态回归检查。原旧源常量属于修复前基线记录，不代表此候选分支现在仍使用旧源。**这只修复新代码的更新指向，不代表已经把旧版客户端的更新配置自动改过来，亦不冒充 Windows 端到端升级测试。** ModelScope 上游更新回退继续禁用。源码修复不要求增加任何安装步骤。

## 4. 状态结论

当前：**S00–S08 计划内代码阶段已合并**（S08 PR #11 与修复 PR #12 均在 main）。可选 wheelhouse 静态问题不阻断免安装便携运行或阶段 PR 合并。本仓库更新源 URL 已由 PR #12 修复，分支常量由本轮收尾 PR 补修；两者必须都合并才算新版源码正确。旧客户端历史配置不会被自动覆盖。**正式发布前系统/设备验收仍为 NOT_VERIFIED**：尚无 Windows 便携实际启动、完整 checkout 全量 Python/Node、Chrome/PS/LAN/ModelScope 等联调和旧客户端升级记录；不得写作全绿或已正式发布。GitHub Actions 仍保持不主动触发。

## 5. 2026-11-04 验收范围纠偏

- 已核对 `run.bat`：调用自带 `python/python.exe` 执行 `main.py`，不自动安装依赖。
- `安装依赖.bat` 是可选修复脚本，其 wheelhouse 版本不匹配不等于免安装画布不可运行。
- 撤销误加的 `tools/prepare_s08_wheelhouse.py` 与 `tests/test_prepare_s08_wheelhouse.py`，不要求使用者为 S08 额外安装软件。
- S08 优先验证原始便携包直接启动、既有安全回归以及旧更新源覆盖风险；不以可选安装脚本的 pip 验证作为阶段 PR 的合并门槛。
- 对尚未运行的 Windows/跨模块测试如实标记，不虚报通过；可以按已验证的阶段性范围合并 PR，最终发布验收另行判定。

## 6. 阶段收尾和证据边界（2026-11-04）

- PR #11 已合并：`d6858396e2376b581c02afda1686097402a44e20`。内容为 S08 检查工具、测试与验收台账；不会修改画布业务代码。
- PR #12 已合并：`94295d06bcd9f67da621ce579e3f58c3d9359b97`。内容为 GitHub 更新仓库 URL、静态回归测试及说明；后续收尾核查发现 `GITHUB_BRANCH` 未同步，已在收尾 PR 中修复为 `main`。ModelScope 上游 fallback 继续禁用。
- **完成定义**：S00–S08 代码阶段及这些 PR 合并完成；**未核验定义**：真实 Windows 免安装启动、完整 Python/Node、浏览器与设备、旧客户端安全迁移不得标记为通过。**不追加 pip 安装任务**。

## 7. 2026-11-06 S08 原生隔离回归与回滚故障修复

- **GitHub 状态复核**：开始本轮时 `main@fd1a86ebf28e46b23d9cd9d61890d0263cf369c8`，打开的 PR 为 0；默认分支仍为 `zcode/iteration-01`，修复目标为 `main`。
- **真实文件校验和 Node 原生测试（PASS）**：GitHub 连接器取得 `static/js/canvas-conflict-recovery.js` 和 `tests/test_canvas_conflict_recovery.cjs`，重建的两份文件通过 `git hash-object` 与 GitHub Blob SHA 精确比对（`e38769e819ba7a4a0622574c5023a8b0b1bfbcd0` / `8b806f84a02eb30e5e220eeac22de358e7efac34`）；Node v22.16.0 原生 `node --test tests/test_canvas_conflict_recovery.cjs`：**8/8 PASS**。只覆盖这两个真实文件及其隔离模拟，不是全量 CJS、Chrome 双标签或系统验收。
- **发现实际回滚故障**：从 `main.py` 的 `rollback_update` 函数提取并在 Python 3.13 的独立临时目录模拟复制失败和根文件替换失败。原版测试 **2 FAIL / 1 PASS**：`static/` 复制失败后现行页面文件消失；根文件失败后留下旧/新混合内容与临时文件。
- **修复及回归（隔离 PASS）**：在失败路径使用已创建的 `rollback_safety` 快照恢复现行 `static/` 和根文件；正常成功路径不改变。故障注入测试 `tests/test_s08_rollback_safety.py` **3/3 PASS**，本地提取函数的 `py_compile` PASS。属于实际文件 I/O 的隔离回归，不是 Windows 原生发布包测试。
- **仍为 NOT_RUN**：完整仓库 Python unittest、所有 Node CJS、Windows `run.bat`、真实浏览器/Photoshop/LAN/ModelScope 联调、旧客户端迁移和下载校验端到端演练。当前容器具备 Python/Node，但无完整 checkout，直接访问 GitHub 域名时 DNS 失败。不得把上述隔离结果冒充全量通过。
- **Actions**：未手动触发；不添加依赖、不执行 `pip install`、不使用生产画布/真实 Key，不修改默认分支或正式发布。

## 8. 2026-11-06 S08 GitHub 更新包完整性回归

- **发现缺陷（已隔离复现）**：既有 `github_update_file_list` 不拒绝 GitHub Tree `truncated=true`，缺少 `main.py`/`VERSION` 时会凭空补列；`download_github_update_files` 未比对 GitHub Tree 提供的每个 Blob SHA。由此，截断清单可能导致替换成不完整的 `static/`，分支下载内容漂移或 HTTP 200 错误页也可能进入暂存。无需触及用户数据即可用 Mock 复现。
- **先测后修**：新增 `tests/test_s08_github_update_integrity.py`，从 `main.py` AST 提取实际两项函数，Python 3.13 原生 `unittest`，修改前 **1 PASS / 5 FAIL**；修改后 **6/6 PASS**。覆盖正常完整下载、截断 Tree、缺必要根文件、缺 Blob SHA、分支漂移和 HTTP 成功但内容损坏。
- **修复**：要求 Tree 完整且具备必要文件、有效 Blob SHA；按 Git Blob 内容哈希验证每个下载文件，异常时拒绝暂存并由现有更新入口中止安装。Github 分支在 Tree 与 raw 之间发生变动时将安全失败，用户可稍后重试；本修复不声称已取得固定提交的端到端在线下载证据。
- **证据边界**：本轮 Python 模拟回归通过，真实 GitHub 在线全量下载、原生全仓库 Python/Node 和 Windows 完整发布升级仍 **NOT_RUN**。不触发 GitHub Actions、不添加依赖、不修改默认分支。

## 9. 2026-11-06 S03 存储句柄及 S02 启动脚本原生回归

- **S03 POSIX/Linux 原生回归 PASS**：GitHub 连接器取得 `storage_guard.py` 和 `tests/test_storage_handles.py`，本地逐文件 `git hash-object` 与 `main` Blob SHA 完全一致（分别 `df2f8c48b3ad2fb85b19ddfc43dc39eb424d2ffa` 和 `a9283409768c5e75eb81e973d676cd31cca1b00c`）。在 Linux/Python 3.13 执行 `PYTHONPATH=. python -m unittest discover -s tests -p test_storage_handles.py -v`：**13/13 PASS，0 FAIL，0 SKIP**。测试范围包括真实 FD、符号链接/根目录竞态、FIFO、删除句柄和受限目录可达性；Windows UNC 路径规范化/句柄比较只在该环境运行了纯函数模拟，**Windows UNC/junction 实机测试仍 NOT_RUN**。
- **S02/macOS 启动脚本隔离 PASS**：GitHub 原始 `mac-启动服务.sh` 和 `tests/test_mac_launcher.py` 均通过本地 Git Blob SHA 精确校验（`33dc6f9f28577e68238ef45fb44ff853b4f37b61`、`e3d42c6c3d2ab22a2e6727dc010ed2d95d257c3b`）。Python 3.13 原生测试 **2/2 PASS**，包含 bash 语法和 Mock LAN 地址下仍打开 `127.0.0.1:3000`；**macOS 实机启动及 S02 LAN/Chrome/Photoshop 真正集成仍 NOT_RUN**。
- 本记录只补充已经真正运行的原生测试，不把它们冒充完整仓库回归或 S08 正式 ACCEPTED。没有触发 GitHub Actions、安装依赖或读取真实用户数据。

## 10. 2026-11-06 旧更新器首次升级兼容导入（隔离测试）

- 从 `main.py` 读取真实 `storage_guard` → `static.storage_guard` 兼容导入代码；两份模块的 Git Blob SHA 均为 `df2f8c48b3ad2fb85b19ddfc43dc39eb424d2ffa`。`tests/test_s03_legacy_updater.py` 原始 Git Blob SHA 校验一致：`dac191652e81737cb925433b0792b072df80120f`。
- 在仅包含该真实导入代码块与上述原始文件的最小 Linux/Python 3.13 fixture 执行仓库既有 `unittest`：**3/3 PASS**，包括字节一致性、旧更新器静态文件白名单、独立进程导入兼容副本。
- 这确认有限的向后兼容导入机制，不是完整旧客户端真实升级、重启、下载、回滚或迁移测试；上述端到端操作仍 **NOT_RUN**。另外对 SHA 校验一致的 `static/js/canvas-conflict-recovery.js` 执行 `node --check`：**PASS**，不代表所有应用 JavaScript 都已完成语法检查。
- 本轮未运行 GitHub Actions、没有依赖安装、没有真实用户数据或发布操作；**S08 SYSTEM ACCEPTANCE 尚未完成**。


## 11. 2026-11-06 还原点路径选择安全回归

- **根因**：现有 `/api/update-rollback` 仅检查 `abspath/commonpath`。传入 `.` 会将整个 `data/update_backups/` 当作备份点；嵌套路径、路径折叠和指向备份根以外目录的 symlink 也可通过检查，可能使回滚过程扫描非目标恢复点。
- **修复**：仅允许单级真实备份目录名；拒绝 `.`、`..`、斜杠、反斜杠、NUL 和符号链接目录，且保留原有备份存在性、清单状态和锁机制。
- **回归**：新增 `tests/test_s08_rollback_selector.py`，独立 AST 提取 `main.py` 中的真实 `rollback_update` 函数，使用临时目录和桩函数阻止磁盘恢复写入。Linux/Python 3.13：原入口校验的隔离复现 **6 FAIL / 6 PASS**；修复后 **12/12 PASS**。测试文件已用本地 `git hash-object` 与 PR 分支 GitHub Blob SHA `a85e5da98c2f1f5c56c956a766bb1028dd081575` 精确核对。
- 这是路径选择前置校验的隔离测试，不是全量 Python、Windows 实机、真实回滚/重启 PASS；这些项目仍为 **NOT_RUN**。无安装任务、无 GitHub Actions、无真实用户画布、无正式发布。


## 12. 2026-11-06 S04 智能画布：网络失败与浏览器存储同时失败

- **发现并复现**：Smart Canvas 的 `saveCanvas` 在 5xx 或网络异常后调用 `persistSmartConflictDraft`；若 `localStorage.setItem` 因配额/隐私模式失败，虽然记录设置了 `persistence_error`，原 UI 仍显示「本地草稿已保留」并且不显示可导出的恢复面板。旧逻辑的新增故障用例 **2 FAIL / 5 PASS**。
- **修复**：两条暂时性保存失败路径统一调用 `preserveSmartFailedSaveDraft`，存储成功时保持原提示；存储失败时用内存中的记录弹出已有 CanvasConflictRecovery 导出/副本 UI，明确警告刷新可能丢失修改。更新 `static/smart-canvas.html` 的 JS 缓存版本。
- **隔离 Node.js 回归 PASS**：原仓库 `tests/test_smart_canvas_save_serialization.cjs` 新增 503+localStorage 不可写及网络异常+localStorage 不可写两项；更新后 **7/7 PASS**。原仓库 `tests/test_smart_canvas_remote_merge.cjs` **6/6 PASS**，同批 `tests/test_index_update_fallback.cjs` **3/3 PASS**、`tests/test_canvas_metadata_routes.cjs` **3/3 PASS**。测试文件逐个 `git hash-object` 校验与 Github Blob SHA 一致；执行时源 JS 使用从 `main` GitHub 文件提取的相关真实函数片段，并非完整 800–950 KB 文件，故属原生 Node 隔离回归，不能冒称全仓库原生运行。
- **剩余 NOT_RUN**：正式 Windows 包、完整仓库全部 Python/Node 测试、浏览器真实 quota/private-mode、双标签/LAN/Photoshop、旧版更新重启恢复。未运行 Actions，未安装依赖，未使用真实 Key/画布。

## 13. 2026-11-08 全套 CJS 隔离测试、JavaScript/HTML 语法及静态资源检查

- **基线**：`main@706b4f449d79dc43ef0f8e746cb9f9aff2507f3b`（PR #25 已合并）；本轮全部从 GitHub `main` 的真实 Blob 内容读取测试和被测脚本，包括经典画布约 803 KB、智能画布约 953 KB 两份完整源码，读取时保留 GitHub 返回的 Blob SHA。
- **全部 15 份 CJS 测试在 V8 隔离沙箱内执行：85/85 PASS**。使用 `node:test` 注册器、`node:assert/strict`、`node:fs`、`node:path`、`node:vm` 的轻量替身；首次双标签测试因沙箱缺失 `structuredClone` 无法执行，补齐兼容替身后 **3/3 PASS**，其余用例 **82/82 PASS**。这些结果说明现有真实测试函数在隔离上下文中通过，**不是原生 `node --test`**，不可作为完整 Node 发布门禁的 PASS。
- **代码语法检查 PASS**：应用 `static/js/` 下全部 **22/22** 份 JS、Chrome/Photoshop 工具 `tools/` 下全部 **11/11** 份 JS，共 **33/33** 份第一方 JS，使用 V8 `new Function` 仅解析（不执行程序）。HTML **17/17** 个文件中的 **22/22** 段非 module 内联脚本语法解析 PASS。`lucide.js` 与 `tailwindcss-cdn.js` 2 个第三方经典脚本解析 PASS。`three-0.160.0.module.js` 为 ES module，GitHub 文件接口本轮未返回可解析内容（空内容）；不标 PASS。
- **本地资源静态链接验证 PASS**：扫描仓库 17 个 HTML 的 `<script>/<link>/<img>` 字面量本地路径，**108/108 引用存在**；动态插值链接按运行时变量排除。新增无依赖 `tests/test_s08_static_asset_references.cjs`，可在完整 checkout 上执行 `node --test`；其真实源文件在 V8+虚拟 `fs/path`、真实 GitHub HTML/目录树中 **1/1 PASS**。这不是浏览器资源可加载性的端到端证明。
- **更新路径静态核查 PASS（仅字面量）**：`main.py` 的 GitHub 仓库和分支均指向 `GuoWen-XX/Infinite-Canvas@main`；6 个更新源常量仅赋值一次、ModelScope 上游更新开关为 `False`；PR #24 的回滚路径名检查、PR #25 的草稿恢复 helper 和 HTML JS 缓存版本均存在。以上静态证据不取代 Python AST 门禁、真实在线更新或备份恢复测试。
- **剩余 NOT_RUN**：完整仓库原生 Python unittest、原生 Node `--test`、Windows `run.bat`/完整便携包、真实双标签浏览器/LAN/Chrome/Photoshop、浏览器 localStorage 配额/私密模式和旧客户端升级回滚。当前测试容器 DNS 无法解析 GitHub 相关域名且无完整源码 checkout；未请求安装、未触发 GitHub Actions、未用真实用户文件/Key 或付费服务。

## 14. 2026-11-08 Chromium 浏览器真实 DOM/下载隔离验证

- **执行环境**：容器内 Chromium（`/usr/bin/chromium`）+ 已提供的 Python Playwright；没有安装依赖。Chromium 的网络与 `file://` 导航受宿主策略阻断，使用 `page.set_content` 在 `about:blank` 建立纯内存页面，不连接真实服务。
- **被测代码**：从 PR #25 合并后的 GitHub `static/js/smart-canvas.js` 提取 `persistSmartConflictDraft`、`preserveSmartFailedSaveDraft`；从 `static/js/canvas-conflict-recovery.js` 提取 `button` 和 `show`，在浏览器执行；只替身化编辑器状态、保存请求上下文及 `createIndependentCopy`，不加载真实画布/Key/用户文件。
- **3/3 PASS（真实 Chromium DOM 与下载）**：① 在 `about:blank` 浏览器存储不可用时，保存失败恢复流程显示带警告的可见面板和导出按钮；② 真实点击导出按钮并读取浏览器生成的 JSON，核实 `canvas_id=smart-one`、`persistence_error=true`，以及未保存节点 `local-unsaved-node` 未丢失；③ 将 `localStorage` 替换为可写内存模拟后，草稿记录成功且不误弹恢复面板。
- **范围限制**：这验证了浏览器 DOM/Blob/download 交互和原始恢复函数的片段行为，但**不是**整页 Smart Canvas/真实浏览器多标签与后端 HTTP 409、真实 quota/private-mode 或 Windows 发布包验收。`about:blank` 的存储不可用来自页面 origin 限制，成功写入分支使用内存 mock；不得标记全部浏览器场景 PASS。真实环境仍保留 NOT_RUN。


## 15. 2026-11-08 S08 更新中途删除/替换故障自动恢复

- **发现问题**：`update_from_github` 在 `shutil.rmtree(static_dir)` 返回前就删除了部分线上页面文件时抛出异常，而原恢复 `except` 仅覆盖后续 `copytree`，故当前 `static/` 可能缺失文件；此外根文件 `os.replace` 失败会留在应用目录中 `.update_tmp`。
- **修复**：将删除旧 `static/` 纳入已有的异常恢复 `try`，确保失败时用完整备份恢复原静态目录；根文件的复制/原子替换使用 `finally` 清理失败遗留的 `.update_tmp`，避免部分代码文件堆积或被误用。
- **回归证据**：在本地 Linux/Python 3.13 临时应用目录，通过 AST 提取当前 GitHub `main.py` 的 `update_from_github` 函数，并用受控网络/备份桩及真实 `shutil`/`os.replace` 模拟更新。覆盖正常安装、删除静态目录途中失败、静态复制途中失败、根文件原子替换失败；修复前 **2/4 PASS，2 FAIL**，修复后 **4/4 PASS**。已将回归测试纳入仓库 `tests/test_s08_update_static_failure.py`。
- **范围边界**：属于完整更新入口的单函数 AST 隔离和真实文件 I/O 故障注入，非全仓库原生 unittest、真实在线下载、Windows 文件锁/ACL、旧客户端升级与重启验证。未运行 GitHub Actions、pip 安装或触碰实际用户画布和密钥；剩余实机任务仍为 NOT_RUN。


## 16. 2026-11-08 更新→回滚→回滚安全备份反向恢复闭环

- **单函数真实 I/O 组合测试 PASS**：复用 `tests/test_s08_update_static_failure.py` 的临时目录，提取 `main.py` 当前 `update_from_github` 及 `rollback_update` 两个真实 AST 函数。使用测试专用的下载/备份清单桩，依次执行成功安装、按备份恢复旧版本、再通过回滚安全备份恢复新版本；三次实际磁盘文件状态均精确一致。
- **故障注入＋闭环共 5/5 PASS**：包含此前的静态删除中断、静态复制中断、根文件替换中断、正常安装；本轮新增版本往返测试 1 项。Python 3.13/Linux 独立临时目录，未修改用户数据、未访问网络或触发 Actions。
- **证据边界**：这验证了两个真实函数的模拟下载及模拟备份清单组成的 I/O 过程，不代表完整应用/真实 GitHub 下载、Windows 原生更新、旧客户端在线升级/重启、真实备份持久化格式验证。后者仍 NOT_RUN。


## 17. 2026-11-08 新增根模块跨版本回滚及复制失败清理

- 在 `tests/test_s08_update_static_failure.py` 补充 2 项独立临时目录测试：① 旧版缺少 `storage_guard.py`，新版新增该根模块，执行更新→回滚会恢复旧版并删除新模块，随后回滚安全备份可将新版模块恢复；② 更新根文件的 `shutil.copy2` 写入一半失败时，`.update_tmp` 被清理，原版 `VERSION`、`main.py`、`static/` 全部保持原样。
- **隔离原生 Python 3.13/Linux：7/7 PASS**（之前 5 项＋新增 2 项）。从 `main.py` 中抽取真实 `update_from_github` 和 `rollback_update` 函数代码进行临时目录 I/O；经函数长度和 FNV32 摘要与 GitHub `main` 对比确认本地提取函数逐字符一致（非完整 `main.py` checkout）。
- 测试下载器及备份 manifest 仍使用受控桩，不涉及真实 GitHub 在线下载或旧客户端安装包；**旧版真实升级/Windows 启动、全量 Python/Node 仍 NOT_RUN**。未运行 Actions、未安装依赖、未使用生产画布/Key。


## 18. 2026-11-08 回滚恢复点 Windows 联接点防护补强

- **安全缺陷**：`os.path.islink()` 无法在所有捆绑 Python/Windows 版本上识别目录 junction/reparse point。单靠它阻止备份符号链接，仍可能通过 `name` 选中指向备份根外部的真实目录，在回滚时读取外部数据。
- **修复**：保留单级恢复点名称、`commonpath` 和 `islink` 检查，新增基于 `os.path.realpath` 的恢复点真实目录与可信备份根的直接子目录比对，且使用 `normcase` 兼容 Windows 大小写。将检测放在读取清单、创建安全备份及文件替换之前。
- **回归**：在 `tests/test_s08_rollback_selector.py` 新增 `test_rejects_reparse_point_even_when_islink_reports_false`，用临时目录符号链接和 `unittest.mock.patch` 模拟 Windows junction 不被 `islink` 识别的情形。Linux/Python 3.13 使用与真实入口一致的前置校验语句在独立 fixture 运行：**4/4 PASS**（正常目录、非法路径、普通 symlink、`islink=False` 伪装的 junction）。修复前模拟可错误放行，修复后拒绝。
- **范围**：4 项是使用源码校验语句的临时夹具，**不是**完整源文件上的原生 `unittest` 或 Windows junction 实机结果。实际 Windows reparse point/UNC、全量 Python/Node、设备端到端仍 `NOT_RUN`，未触发 GitHub Actions、安装依赖或读取用户数据。


## 19. 2026-11-08 原生 Python 回归小批次：逐文件校验 Git Blob SHA

- **网络诊断**：Linux 容器 `getent hosts github.com` 无记录，`git ls-remote` 和 `curl https://api.github.com` 因 DNS 失败；直接 `curl --resolve` 指定 GitHub IP 也被网络拒绝。GitHub MCP 连接器能正常读取 `main`，但与执行 Python/Node 的容器不共享完整 checkout。系运行环境的网络隔离，不是仓库无法访问。
- **本轮原生 Python 测试 PASS：25/25，0 FAIL、0 ERROR、0 SKIP**。经 GitHub MCP 取得六份原文件并在 Linux/Python 3.13.5 临时目录逐字重建，逐一 `git hash-object` 对比 GitHub `main` Blob SHA 全部一致，再用原生 unittest 执行：
  - `tests/test_s08_wheelhouse.py`（`65e9bfca73f8e41ff56503c2debfe8ecb9b2e5a1`）与 `tools/check_s08_wheelhouse.py`（`1ff3bca244dfd553d6fd383264f308dfcbf9dbcc`）：**8/8 PASS**。
  - `tests/test_s08_release_source.py`（`be018d7d5eae9e6ae16eff186476796b70249286`）与 `tools/check_s08_release_source.py`（`d97d70b33eb0d80eeba63feb8301ea462f0787b5`）：**15/15 PASS**。其第 16 项 `test_live_main_file_uses_safe_github_urls` 依赖完整 `main.py`，本次**未执行**，没有以简化或虚构 main.py 冒充真实源码。
  - `tests/test_mac_launcher.py`（`e3d42c6c3d2ab22a2e6727dc010ed2d95d257c3b`）与 `mac-启动服务.sh`（`33dc6f9f28577e68238ef45fb44ff853b4f37b61`）：**2/2 PASS**，Mock 外部命令，没有真实启动服务器。
- **证据边界**：这是真正的 Python 3.13.5 + unittest 原生测试，不是 V8 模拟；但是只覆盖 25 个不依赖完整后端代码的用例，不是全仓 24 Python 模块的原生 `unittest discover`。16 个 CJS 文件原生 `node --test`、Windows/浏览器/LAN/插件/旧版在线升级仍为 `NOT_RUN`。本轮没有运行 GitHub Actions、pip 安装、付费服务或真实用户内容。


## 20. 2026-11-09 全仓原生 Node/Python 门禁已取得实际执行结果

- **真实完整源码**：在单独的、短时云端 Linux 测试沙箱从公开 GitHub 仓库检出 `main@1fc1df6e48d7e453a11b7782f57dfbe08dc9fa5a`，核实 `tests/` 含 **24 个 Python `test_*.py`** 与 **16 个 Node `.cjs`**，不是文件片段/AST/V8 模拟；原始源码不涉及用户工作目录或 API Key。
- **原生 Node.js PASS**：Node v24.22.1，运行 `node --test tests/*.cjs`，**86/86 PASS，0 FAIL，0 SKIP，退出码 0**，完整覆盖 16 个 CJS 测试文件。未使用 GitHub Actions。
- **原生 Python 初测**：Python 3.14.4；在沙箱中临时安装仓库 `requirements.txt` 所锁定的依赖（仅隔离测试环境，不改变免安装画布），运行 `python -m unittest discover -s tests -p 'test_*.py' -v`，**310 项执行，2 FAIL，退出码 1**。第一项 `tests/test_skill_library.py::test_create_list_update_delete_flow` 没带 `base_sha256`，与当前安全版 Skill PUT 的既有乐观锁协议不符；第二项 POSIX 搜索权限目录在 Vercel 沙箱的 non-root 进程仍拥有 DAC override 能力，产生内核权限前提不成立的环境性假失败。
- **真实修复与复测**：仅在 `tests/test_skill_library.py` 的 PUT 用例增加从 GET detail `content_sha256` 传入 `base_sha256`；该原始测试文件的新 Git blob 为 `812e3732f026dd1fef44db968f0a35874d8425b7`。已本地原生执行 `test_skill_library.py` **29/29 PASS**。权限测试按其既有设计在 root 主进程创建临时夹具、子进程主动降权至 nobody，再执行搜索权限检测；`test_storage_handles.py` **13/13 PASS**。没有为了绿灯修改任何生产代码，也没有对存储安全测试虚构成功。
- **完整 Python 复测 PASS**：使用与 GitHub 提交完全一致的上述测试文件、新鲜临时依赖环境，在同一完整 checkout 执行 `sudo env PYTHONPATH=<sandbox user-site> python -m unittest discover -s tests -p 'test_*.py' -v`，**310/310 PASS，0 FAIL，0 ERROR，0 SKIP，退出码 0**。其中 `test_skill_upgrade_tracking.py` **13/13**、`test_storage_safety.py` **16/16**，两个此前无法下载的文件已在完整测试中通过。
- **证据边界**：这是完整 Linux/Python 3.14 + Node 24 原生测试，但不是 Windows 自带 Python 3.10 的实机测试；Windows `run.bat` 便携启动、Chrome 双标签、LAN、PS/Chrome 插件、ModelScope 和旧客户端在线升级仍属 `DEVICE_VALIDATION_PENDING`。CI/Actions 仍未运行；安装依赖仅发生在一次性隔离沙箱，不要求用户安装任何程序。

## 21. 2026-11-09 原生 Chromium 冲突恢复面板交互回归

- **真实前端文件**：从 `main` 读取 `static/js/canvas-conflict-recovery.js`，`git hash-object` 核对修复前 Blob `e38769e819ba7a4a0622574c5023a8b0b1bfbcd0` 与 GitHub 完全一致；修复后 Blob 为 `f4b7b8d3959e45a307680f38badce847107f6faf`，并与 PR 文件核对。
- **发现真实 UI 缺陷**：原“收起”仅设置 `actions.hidden = true`，但操作容器具有内联 `display:flex`，浏览器实际仍显示按钮；隔离 Chromium + Playwright 原始 JS 交互测试 **5/6 PASS，1 FAIL**（失败项为收起/展开）。
- **最小修复**：收起时显式把 `actions.style.display` 改为 `none`，展开时恢复 `flex`；不改变冲突检测、保存 CAS、导出内容及更新器逻辑。
- **复测**：Linux 上的系统 Chromium + Playwright，在真实 DOM 和下载行为中运行 6 项隔离交互场景，修复后 **6/6 PASS**（独立副本不会 PUT 原画布、JSON 下载、内存草稿丢失警告与收起/展开、写副本失败留存草稿、属性 409 之后明确确认的 CAS 重试、智能画布恢复链接）。测试使用内存模拟的 localStorage 和请求返回；**不是完整画布页面、真实 HTTP 后端、两标签端到端或 Windows 验收**。
- **无额外依赖回归**：新增 `tests/test_canvas_recovery_ui.cjs`，原始 JS 上 Node v22.16.0 **1 FAIL**；修复后真实 `node --test tests/test_canvas_recovery_ui.cjs` **1/1 PASS，退出码 0**，两份修改文件的 Git Blob SHA 均与本地执行副本一致；`node --check` PASS。此处新增 1 项测试不冒称重新执行全仓 `node --test tests/*.cjs`；此前完整 Linux 原生 86/86 证据仍以 PR #34 为准。
- **发布边界**：Windows 免安装 `run.bat`、真实 Chrome 双标签、LAN/插件、旧客户端升级仍然 `DEVICE_VALIDATION_PENDING`。本轮没有 GitHub Actions、用户画布、真实 API Key、额外安装步骤或付费模型调用。

## 22. 2026-11-09 PR #36 合并后的最新 main 全仓原生回归：工程方收尾完成

- **唯一测试基线**：在原有 S08 测试用的独立云端 Linux 沙箱项目中，重新从公开 GitHub 仓库检出完整 `main@98a1f7054b6b8a642c9d8ee7b2be2c497f82bde6`（PR #36 合并提交）。`git rev-parse HEAD` 精确一致；真实 `tests/` 目录有 **24 个 Python 测试文件**和 **17 个 CJS 测试文件**。测试运行使用 Node v24.22.1、Python 3.14.4，不是 V8/AST 等价模拟。
- **原生 Node.js**：在完整 checkout 执行 `node --test tests/*.cjs`，**87/87 PASS、0 FAIL、0 SKIP、exit 0**（实际日志 `/tmp/s08-node.log` 的 SHA-256：`0eaedd97c0979a4d28499bdc0a89abb5ae135732a99419a0e24535851e8b1abb`）；覆盖 PR #36 新增的 `tests/test_canvas_recovery_ui.cjs`。Python 测试运行后的 Node 再次执行也是 **87/87 PASS、exit 0**（日志 SHA-256：`d4659f07a762712c07c92b63ae96a4b33f7bf41d169e4323089bc43b5eb28804`）。
- **原生 Python**：只在短时隔离沙箱临时安装 GitHub `requirements.txt` 锁定依赖，不更改用户现有免安装画布。实际执行 `sudo env PYTHONPATH="$(python -m site --user-site)" python -m unittest discover -s tests -p 'test_*.py' -v`，**310/310 PASS、0 FAIL、0 ERROR、0 SKIP、exit 0**；日志 `Ran 310 tests in 7.798s / OK`（SHA-256：`fd7c5ee85cd2d02b97bf94463b23b4259c7ba167478c608f723675753d123b55`）。其中 Skill upgrade tracking **13/13**，storage safety **16/16**，Skill library **29/29**。权限测试沿用现有 root→nobody 降权路线。
- **工作树与副作用核查**：启动/导入后现有缓存版本同步逻辑改写测试 checkout 中 14 个 HTML 的资源 `?v=` 时间戳（不是本轮代码修改，也不是失败测试）。仅在一次性沙箱中将这些生成变动恢复为仓库原文，`git status --porcelain` 为空；没有向仓库提交它们，也没有动用户文件。
- **工程结论**：最新 `main` 的全部原生 Linux Python/Node 自动化回归 **397/397 PASS**；PR #36 合并后的 87 项 Node 全量补验与 310 项 Python 全量复验均已完成，**工程方此项无遗留 NOT_RUN**。仅存 **Windows 自带 Python 3.10 便携启动、真实浏览器双标签、按实际使用的 LAN/PS/Chrome 插件及旧版在线迁移** 的设备端实测，依然 `DEVICE_VALIDATION_PENDING`，不宣称正式发布已通过。
- **费用与约束**：没有 GitHub Actions、生产画布、真实凭据、付费 AI、或对用户的安装要求；只在临时 Linux 测试沙箱安装了必要锁定依赖，不修改 `run.bat`、安装流程或默认分支。
