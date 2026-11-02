# Infinite-Canvas 修复工作计划（执行台账）

> 建立：2026-11-02；执行目标：`main`。  
> 当前状态：`S00 计划评审中`；**未获远端评审通过，不启动 S01 或后续阶段**。  
> 本台账是长期执行清单；每推进一个阶段，必须随该阶段 PR 更新状态、测试证据、风险和回滚记录。

## 一、工作规则（强制）

1. **单阶段、单实施分支、单 PR**。以已批准的上一个 `main` HEAD 为基础；不在未审查分支上继续叠加下一阶段代码。
2. 每阶段顺序：`建立分支 → 先写失败回归测试/复现 → 小范围修改 → 本地验证 → 推送 PR → CI → 远端 Code Review → 修复所有阻断项 → 合并 → 记录交接 → 下一阶段`。
3. 下一阶段的解锁条件：本阶段 PR **已 merge 到 main**，GitHub Actions 必须 success，明确的 Review 结论通过且没有 unresolved blocking comments。**PR 创建、CI success、Codex Review Summary 显示 running 均不等于审查通过**。
4. 若没有提交的 Review approval，可由项目维护者作出明确的人工审查决定，并把结论、证据、理由和仍存风险写入 PR；不能由执行者自己宣称“远端审查通过”。
5. 每次提交前 `git diff` 审查、最小改动、安全敏感字符串检查；修复失败优先在同一 PR 处理。严禁强推 `main`；严禁修改真实用户 API Key、用户画布或使用真实付费额度做自动测试。
6. 新发现的严重安全缺陷可标记 `BLOCKED/SECURITY`，修改计划后按新顺序执行；不得悄悄扩大当前阶段范围。
7. 任何阶段若变更超出当前计划，先更新方案/验收条款并在 PR 上明确说明，再编写代码。
8. 阶段 PR 均以 `main` 为 base。`zcode/iteration-01` 是当前仓库默认分支，直到单独审议默认分支调整前不修改；必须在 PR 说明里标明这一点。
9. **持续推进的含义是按审查关卡逐段推进，不是跳过等待；未得到新审查结果时应停在 gate 并报告状态。** 不在未获批准时自动合并或展开下一阶段。

## 二、阶段路线图

| 阶段 | 状态 | 目标 | 主文件 | 交付与验收 |
| --- | --- | --- | --- | --- |
| S00 | IN_REVIEW | 固定修复基线，提交技术方案、执行台账、评审规范 | `docs/remediation/2026-11-02/*.md` | 文档 PR 被认可后，解锁 S01 |
| S01 | BLOCKED_BY_S00 | 阻止保存的 API Key 被任意 `base_url` 带出（SEC-01） | `main.py`、`tests/test_provider_security.py` | saved key 不发往任意目标；正常 provider 测试可用；Mock 无真实请求 |
| S02 | NOT_STARTED | 权限/CORS/ModelScope Token 路径（SEC-02） | `main.py`、`static/zimage.html`、`static/angle.html`、Chrome/Photoshop 连接器 | 未授权访问失败、合法 LAN/插件/ModelScope 功能正常 |
| S03 | NOT_STARTED | 存储根访问控制、SSRF、下载 ZIP 配额（SEC-03/04/05） | `main.py`、素材管理相关前端和测试 | 任意文件/内网 URL 被拒，合法自定义存储仍可使用 |
| S04 | NOT_STARTED | 画布 409 覆盖 R1、元数据回滚 R6 | `static/js/canvas.js`、`main.py`、画布测试 | 双页面增/改/删、改名均不丢数据，草稿可恢复 |
| S05 | NOT_STARTED | Skill 编辑 frontmatter R2、variant ID R7 | `main.py`、`static/js/skill-manager.js`、Skill 测试 | 保存不丢元数据、不改稳定 ID、旧画布引用有效 |
| S06 | NOT_STARTED | PyYAML 正式依赖 R4、GitHub Skill tracking ref R3 | `requirements.txt`、安装脚本、`main.py`、Skill 测试 | 全新环境正确安装；A→B→C 升级可跟踪；缺依赖无半次写 |
| S07 | NOT_STARTED | Codex 自定义存储参考图 R5 | `main.py`、Codex 测试 | 默认/自定义路径均可解析，非法引用拒绝 |
| S08 | NOT_STARTED | 跨模块回归、Windows/LAN/插件联调与发布质量门 | CI、测试、文档、最小必要的修复文件 | 完整回归、发布报告及残余风险列表 |

优先级解释：安全 P0 首先修；画布数据丢失 R1 在 S04 专项完整解决；每阶段风险以隔离环境复现结果重新评定，不能仅靠既往静态结论。

## 三、阶段任务卡与完成定义

### S00 — 计划/治理

- [x] 已将 `2fd89fb` 的 `run.bat` 内容等效移植到 `main`，新提交 `0330be0a`。
- [x] 确认 `main` 与 `zcode/iteration-01` 最终文件差异原先只有 `run.bat`，但提交历史有分叉。
- [x] 引用 PR #2 七项缺陷，区分已隔离复现与独立静态风险。
- [x] 制定分阶段技术方案、验收方法、回滚与 gate。
- [ ] 创建并审查计划 PR。
- [ ] 计划 PR 合入 `main` 并确认 CI 成功与 review gate 满足。

### S01 — API 凭据出站限制（SEC-01）

- [ ] 查全所有使用 `api_key_from_payload` 的路由、运行协议、跳转/二次 probe。
- [ ] 先添加“恶意自选 URL + 已存 Key”回归，确保改动前失败且不会真的联网。
- [ ] 对已保存 Key 使用 provider 已保存绑定 URL；临时 URL 必须搭配请求中的临时 Key；日志脱敏。
- [ ] 覆盖 OpenAI-compatible / Gemini / Volcengine / RunningHub / Async 模式。
- [ ] 提交实施 PR，填写风险、兼容性说明与验证证据。
- [ ] 远端审查通过，合入后才能解锁 S02。

### S02 — 身份和 Token（SEC-02）

- [ ] 画出 HTTP、WebSocket、zimage/angle、Chrome、PS 的调用关系。
- [ ] 安全变更前建立 LAN 与插件联调样例。
- [ ] 引入访问认证与 Origin/CSRF 策略；同源 Token 返回或后端代理方案须经实际功能验证。
- [ ] 加入未授权读 Token、更新/删除、跨源和授权功能测试。
- [ ] 提交 PR、审查、合并后解锁 S03。

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
GitHub Actions URL and status:
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
