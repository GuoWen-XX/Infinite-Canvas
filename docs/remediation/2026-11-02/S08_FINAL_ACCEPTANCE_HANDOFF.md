# S08 代码完成与最终验收交接（2026-11-09）

> **代码状态：已知修复已全部合并。最终系统/发布状态：NOT_VERIFIED / RELEASE_BLOCKED。**
> 目标仓库 `GuoWen-XX/Infinite-Canvas`，目标分支 `main`（仓库默认分支仍为 `zcode/iteration-01`）。
> 记录基线：`main@15f04e22688390238d64de9492c3a81dcfa38b48`，当时未合并 PR **0**。后续 HEAD 变化时以最新 `main` 为准。
> 2026-11-09 新增真实 Linux 全仓 Node/Python 原生测试证据，见 `S08_RELEASE_GATE.md` §20；最终 Windows/设备验收仍未通过，不等于已经正式发布。

## A. 已完成的工程工作（不要求用户重新操作）

- S00–S07 已知代码缺陷修复和实施 PR 已合并；S08 实施以及后续补修 PR #20–#31 已合并。截至基线没有未合并 PR。
- 画布防覆盖、409 草稿恢复、删除 CAS、智能画布串行保存、更新源校验、回滚故障恢复、路径安全和 Windows junction 真实路径检测等已实施。
- 既有 15 个 CJS 文件的 **85/85** 个用例在 V8 隔离沙箱及模拟内置模块中通过；第一方 JS **33/33**、内联脚本 **22/22** 语法解析通过；17 个 HTML 文件共 **108/108** 个字面量本地资源引用可定位。新增原生可执行静态资源测试，隔离执行 **1/1**。**以上不是全仓原生 Node 测试通过。**
- Chromium + Playwright 隔离恢复组件及下载验证 **3/3**；更新/回滚及新增根模块的 Linux/Python 3.13 临时文件故障注入 **7/7**；回滚恢复点 junction 条件的前置校验隔离 **4/4**。对应详细范围在发布门禁的 §7–§18。
- 这些成果未使用 GitHub Actions 额度、未运行 pip 安装、未操作真实画布/API Key 或付费平台。

## B. 全仓自动化已完成（Linux 原生；Windows 实机另行验收）

| 测试门禁 | 实际环境 | 真实执行结果 |
| --- | --- | --- |
| `python -m unittest discover -s tests -p 'test_*.py' -v` | Linux，Python 3.14.4，独立沙箱内锁定依赖；POSIX 权限用例按原设计降权 | **310/310 PASS，0 FAIL，0 ERROR，0 SKIP，退出码 0** |
| `node --test tests/*.cjs` | Linux，Node v24.22.1，全部 16 个 CJS 文件 | **86/86 PASS，0 FAIL，0 SKIP，退出码 0** |

全部 24 个 Python 测试文件均在检出的完整 GitHub 源码上运行，不再依赖 AST 片段或 V8 shim。此前缺失的 `test_skill_upgrade_tracking.py` **13/13** 和 `test_storage_safety.py` **16/16** 均通过。初测发现旧 Skill API 测试缺 `base_sha256`，在对应测试中修正为使用 GET 返回的 `content_sha256`，修复文件 Git Blob SHA `812e3732f026dd1fef44db968f0a35874d8425b7`；非 root 运行器的 DAC_OVERRIDE 能力使搜索权限用例失真，按测试既有 root→nobody 路径执行后通过。完整证据和范围见 `S08_RELEASE_GATE.md` §20。

以上已完成工程方原生自动化的 Linux 范围，不等于嵌入 Windows Python 3.10、浏览器、PS 插件或 LAN 的实机通过；不得为免安装画布增加安装步骤。没有运行 GitHub Actions。
## C. 需要真人设备验收的事项（只在独立副本中操作）

1. **Windows 免安装启动**：将当前 `main` 的完整便携程序放在独立测试文件夹，双击 `run.bat`，不运行 `安装依赖.bat`、不执行 pip。确认 `http://127.0.0.1:3000/` 打开且新建一张测试画布可以保存、关闭重开。
2. **真实双标签数据安全**：Chrome 打开同一张**测试**画布的两个标签；A 增节点并保存、B 在旧快照修改并保存，确认不会静默覆盖 A，B 可以导出草稿或另存独立画布。重复试一次改名、删除与恢复；智能画布也做一次并发/断网恢复。
3. **按实际使用场景选择性联调**：需要局域网时，按现有 LAN 授权设置验证未授权拒绝和有授权访问；实际使用 Chrome 扩展、Photoshop 连接器、ModelScope Token 时再在测试配置中验证联通性和权限。**不需要为验收额外安装你原本不使用的软件/插件。**
4. **旧版升级/回滚（如果仍有旧客户端）**：只用旧程序的**副本**检查它是否仍指向历史更新源；不要在真实工作目录中直接测试自动更新。核实更新至本仓库 `main` 版本后能启动，能回滚并保留测试数据。更新源的源码修复不会自动改变已安装旧版自身的更新配置。

**不要求**提供真实 Key、付费额度、真实画布或正式生产数据；不要求单独安装 Python/Node/其他工具。

## D. 放行规则

- **代码修复阶段**：COMPLETE（已知问题全部合并，后续新发现问题例外）。
- **全仓原生自动化**：Linux 原生 **PASS（Python 310/310、Node 86/86）**；嵌入式 Windows Python 3.10 与真实浏览器集成属于设备验收范围。
- **Windows/设备/真实浏览器/旧版迁移**：PENDING HUMAN DEVICE ACCEPTANCE。
- **整体 S08 正式系统验收/发布许可**：**NOT_VERIFIED / DEVICE_VALIDATION_PENDING**；Linux 全量自动化已通过，但 Windows/真实浏览器/插件/LAN/旧版安全升级尚未实机验收，不得提前标记 ACCEPTED。

