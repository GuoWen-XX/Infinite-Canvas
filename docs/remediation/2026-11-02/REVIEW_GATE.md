# 修复阶段 PR / 远端审查通行规则

建立：2026-11-02。适用：`docs/remediation/2026-11-02/WORKPLAN.md` 的 S00–S08。

## 1. 双层审查原则

- **代码质量门**：单元/集成测试覆盖本阶段触发条件、错误路径和跨平台兼容性；保留实际本地/隔离测试命令与输出。GitHub Actions 非默认必选项。
- **远端人工/独立审查门**：PR 存在明确已提交的有效 Review 结论，或维护者在 PR 中写下审查通过决定；逐一处理所有 blocking / unresolved comment。只有 GitHub Actions 绿灯或 Codex bot 发出的 `running` 状态评论不算通过。
- 执行者不能把自己编写的测试、自己创建的 PR、自报结果当成独立审查通过的证明。
- **不得自动 merge** 实施阶段 PR，除非有可核实的审查通过结论、足够的本地/隔离测试证据和本阶段验收记录；如经用户明确授权并实际手动运行 Actions，则该运行须通过。修复过程不在生产机器/真实用户数据上执行破坏性探针。

**费用控制硬规则**：禁止 push / pull_request 自动触发 GitHub Actions；每阶段默认不运行 Actions。只有技术上必须使用 GitHub-hosted 环境验证、且用户针对本次运行明确授权时，才使用手动 `workflow_dispatch`。不得通过频繁小提交触发 CI，不得自动 re-run。

## 2. 每阶段处理流程

1. 用 GitHub 工具读取最新 `main` head、PR 清单和已合入阶段状态；避免基于过期 SHA 修改。
2. 检查前置阶段已 merge 及 Code Review 通过，若未达到则保持 BLOCKED。
3. 在独立 `fix/Sxx-<topic>` 分支编写测试与实现，不在 `main` 直接开展阶段修改。
4. 提交同一 PR：变更摘要、关联缺陷、具体文件行号、反例验证、修复后验证、兼容性、回滚方案；PR 目标 `main`。
5. 如果远端审查指出问题，在**同一阶段 PR** 中修改并重新跑测试/审查。严禁用“下阶段再修”消化本阶段 blocking 项。
6. PR 通过后执行合并；更新工作台账中的合并 SHA、审查证据和已通过测试；之后才开始下一阶段。

## 3. 通用验收清单

- [ ] PR 只修改本阶段必要文件，无隐藏跨阶段改动
- [ ] PR base 指向 `main`，且自创建以来 main 更新已充分处理
- [ ] 有修复前失败测试（或清晰可复现的失败步骤）
- [ ] 修复后 Python unittest 自动发现通过
- [ ] 触及 JS 时有 Node 语法检查及合适浏览器行为验证
- [ ] 不触碰真实配置、密钥、用户画布或付费生图额度
- [ ] API Key 不进入异常、日志、测试输出或 PR 描述
- [ ] 跨平台 Windows/macOS/Linux 影响已说明，相关启动路径有验证
- [ ] **GitHub Actions 默认 NOT_RUN**；如确实必要，先取得用户明确许可，手动运行且附 URL、对应 commit SHA 和结果。不得因为没有 Actions 绿灯而默认阻塞通过本地验证的阶段。
- [ ] 已解决所有阻断 Review comments；明确评审结论（附 URL）
- [ ] PR 已合并至 main，记录最终合并 SHA
- [ ] 用户可按文档回滚本阶段；没有隐式数据格式破坏
- [ ] 前一阶段通过前，未提交后续阶段代码

## 4. 跨模块专用检查

- 凭据/网络：构造恶意域名、子域名、重定向、local/private IP；用虚构测试密钥；确认发往未授权 URL 的请求**没有发生**。
- 画布：两个页面/客户端跨版本冲突，节点增/改/删及 title/icon 修改；草稿不丢；不以增加版本号伪装消除冲突。
- Skill：frontmatter 未知字段完整 roundtrip，variant ID 稳定，缺依赖时原文件未改变；更新跟踪在 A→B→C 连续演进下仍正常。
- 本地文件：不同平台绝对路径、软链接、跨盘/UNC，合法图片可用而系统文件无法访问；下载总量和资源消耗有明确限制。
- Codex/ModelScope：常规回归使用 mock，不得在无额外授权时发出真实计费请求。

## 5. PR 审查状态的解释

| 看到的状态 | 是否准许下一阶段 | 处理方式 |
| --- | --- | --- |
| `open`、无 Review | 否 | 请求独立审查 |
| 仅本地/隔离测试通过，Codex Review Summary `running` | 否 | 等待实际 Review 结论 |
| Reviewer `CHANGES_REQUESTED` | 否 | 同阶段修复再提交 |
| Review `APPROVED`，本地/隔离测试失败 | 否 | 修复回归；如获许可手动运行过 CI 且失败，也需解决 |
| 审查批准 + 本地/隔离测试通过，但 PR 未合并 | 否 | 合并并核实 main |
| 审查批准 + 本地/隔离测试通过 + PR merged + 交接记录 | 是 | 进入下一阶段 |

## 6. 分支与 PR 命名

- 计划：`review/remediation-plan-20261102` → `main`。
- 阶段：`fix/S01-provider-key-binding`、`fix/S02-lan-auth-token`、`fix/S03-storage-ssrf`、`fix/S04-canvas-conflicts`、`fix/S05-skill-edit-integrity`、`fix/S06-skill-install-updates`、`fix/S07-codex-storage-media`、`fix/S08-release-verification`。
- 标题：`fix(S01): prevent stored API keys from leaving their bound provider` 等；说明必须包含 `Stage: Sxx`、关联 ID、测试和 gate。
- PR #2 为审查证据来源，不将其“探针通过”解释成实施验收成功。

## 7. 人工审核所需的重要决定

以下决策涉及兼容性，需要在对应阶段 PR 中公开，不得静默执行：

1. S02 认证方案是否允许旧版 Chrome/Photoshop 无认证访问；如果不允许，迁移提示、连接配置及切换策略是什么？
2. S02 ModelScope 直接从浏览器发请求的历史链路如何安全代理或收口？
3. S03 自定义存储目录允许哪些用户选择的外置磁盘/共享盘？持久授权如何存储？
4. S04 409 是自动三方合并还是显式冲突选择？本地草稿的恢复机制是什么？
5. S08 是否将默认分支从 `zcode/iteration-01` 改为 `main`？这与代码合并是不同的仓库操作，须独立决定。

## 8. 重要边界

这里的“严格持续推进”是**有门禁的逐步执行**，不是不经 Review 的后台连续提交。每个阶段结束即停在远端 Code Review 关卡；取得可核实的通过结果后，再继续下一阶段。自动定时查询如被设置，仅负责监测与提醒，不能替代代码评审/合并授权。
