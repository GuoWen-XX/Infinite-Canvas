# S08 发布前验收门禁与证据（2026-11-03）

> 基线：S07 已合并 `main@a8834ef0c9c8c8795b3fd73cc27427ea0912e5be`。本文件记录**已核实证据与尚未执行的验证**。不等于发布许可。
> 不运行 GitHub Actions；不访问真实 API Key、用户画布或付费模型。正式联调须在隔离副本中进行。

## 1. 本轮核查：离线安装依赖 **FAIL（发布阻断）**

已从 GitHub S08 分支读取 `requirements.txt`、`python/` 与 `packages/` 实际文件名：仓库自带 `python310.dll`（Python 3.10），`packages/` 目前有 22 个 wheel，但多项与锁定依赖不符。仅以真实清单的文件名、锁定版本和 DLL 名构造离线镜像夹，调用 `tools/check_s08_wheelhouse.py --root <mirror> --json`，得到 **8 个直接依赖中 2 匹配、6 不匹配**。这是静态文件名/标签审计，**尚未执行 pip，也未核验 wheel 内容完整性**。

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

**修复要求：** 确定正式 Windows Python 版本（当前随仓库是 3.10），按已锁定 `requirements.txt` 使用匹配 Python ABI/平台重新准备完整离线 wheelhouse；不得为了让旧包通过而悄悄降级锁定版本。准备完后依次执行：

```bash
python tools/check_s08_wheelhouse.py --json
python -m pip install --no-index --find-links=packages -r requirements.txt
python -m pip check
```

第二、三条必须在一次性、与用户环境隔离的 Windows Python 3.10 环境执行；不得直接改用户已有 `python/` 或真实安装目录。

## 2. S08 核查工具和本轮可核实结果

- [x] 创建 `tools/check_s08_wheelhouse.py`：只读取文件名、版本、Python tag/ABI tag、bundled `python3xx.dll`；可输出 JSON，任一直接锁定项缺失、不符返回非零退出码。
- [x] 创建 `tests/test_s08_wheelhouse.py`：6 项合成 fixture 测试（Python 3.10 检测、缺包、版本、cp314 ABI、不锁定依赖、兼容 ABI）。
- [x] 在本机 Python 3.13 对该检查器的同等隔离版本执行 `python -m unittest -v /mnt/data/test_s08_wheelhouse.py`：**6/6 PASS**；并用来自仓库内容的镜像文件名执行静态审计，返回 FAIL（命中六个直接依赖问题）。**这些不是完整 repo checkout 上的测试**。
- [ ] 从 S08 最新 HEAD 完整检出仓库执行 `python -m unittest discover -s tests -p 'test_*.py' -v` 并记录退出码与失败栈。
- [ ] 原生 Node.js：`node --test tests/*.cjs`（应在真实仓库目录运行；若 Windows shell glob 不展开则使用脚本逐文件枚举）。
- [ ] Windows 启动器 `run.bat`、`安装依赖.bat` 在隔离副本验证；检查 `python310.dll` 与 wheelhouse/解释器一致性。
- [ ] 双标签 Chrome：画布增/改/删、元数据改名、409 草稿/恢复，智能画布并发保存、文件下载与 Range 断点续传。
- [ ] LAN、Photoshop/Chrome 扩展、ModelScope Token 的授权/跨域场景在可控测试账号进行，禁止把真实用户 token 放入日志或测试夹。
- [ ] S02 28 项与 S03 45 项延期回归、Windows UNC/junction、Skill 版本追踪 A→B→C、Codex 自定义媒体路径真实 Windows 安全验收。
- [ ] 核对 `main.py` 自动更新源与仓库目标分支；当前已知旧更新渠道指向 `benkwok1983-cmd/Infinite-Canvas@zcode/iteration-01`，不能因本仓库 `main` 合并就宣称旧版用户已经收到修复。**禁止在没有单独发布决策时擅改来源/default branch。**
- [ ] 必须有发布前残余风险报告；未消除的高风险失败或缺失的必要测试阻止发布。

## 3. 自动更新源一致性 **FAIL（发布阻断）**

已从 S08 基线的 `main.py` 实际源码读取：
- `GITHUB_REPO_URL = "https://github.com/benkwok1983-cmd/Infinite-Canvas"`
- `GITHUB_BRANCH = "zcode/iteration-01"`

修复工程实际合入 `GuoWen-XX/Infinite-Canvas@main`。当前 updater 并非指向本修复来源；若用户更新，它可能用其他仓库/分支的文件覆盖此次合入的安全修复。**未经独立发布方案批准，不擅自修改默认分支、更新来源或上线设置。**

- [x] 新增 `tools/check_s08_release_source.py`：使用 `ast.parse` 静态读取更新器常量（绝不 import/启动 `main.py`），将 repo/branch 与明确期待的发布目标进行比对；不符返回失败退出码。
- [x] `tests/test_s08_release_source.py` 4 项模拟测试：正确源通过，错误仓库、错误分支、动态未审计常量都必须拒绝。Python 3.13 在本地等价实现执行 **4/4 PASS**，仅模拟/静态检查；不代表真实旧客户端升级成功。
- [x] 将仓库当前已确认的常量在本地镜像执行，结果 **FAIL**。这不是一个可以仅标“延期测试”就允许发布的问题；必须先制定/执行实际更新渠道切换或安全禁用策略，并从真实旧客户端到目标包完整验证后方可解除阻断。

```bash
python tools/check_s08_release_source.py --expected-repo GuoWen-XX/Infinite-Canvas --expected-branch main --json
```

## 4. 状态结论

当前：`S08 IN_PROGRESS / RELEASE_BLOCKED`。**S00–S07 阶段已合并，不等于最终验收。** 本仓库缺少能运行完整 checkout 的环境；GitHub Actions 不自动运行也不手动触发。必须保留未执行项目的真实状态，禁止填写“全绿”。

## 5. 2026-11-03 依赖修复推进：隔离下载方案已提交（未发布）

- [x] 新增 `tools/prepare_s08_wheelhouse.py`：使用 `pip download --only-binary=:all: --implementation cp --python-version 3.10 --abi cp310 --platform win_amd64`，包含传递依赖，输出只能是仓库外全新/空目录，拒绝写入现有 `packages/`。
- [x] 新增 `tests/test_prepare_s08_wheelhouse.py` 的 5 个合成测试；在独立本机目录以 Python unittest 执行 **5/5 PASS**。仅验证命令和失败保护，未下载真实 wheel。
- [ ] 在联网的可信构建环境运行 `python tools/prepare_s08_wheelhouse.py --output <仓库外空目录>`；不要在开发者现有 Python 或正式安装目录直接修改依赖。
- [ ] 下载成功后人工清点、校验 wheel 完整性，并在隔离的 Windows Python 3.10 环境使用 `python -m pip install --no-index --find-links=<候选目录> -r requirements.txt` 及 `python -m pip check`，记录完整执行日志。
- [ ] 若依赖不存在对应 Windows cp310 wheel，则**记录失败并提出明确的锁定版本/运行时升级方案**；禁止以静态检查通过替代完整安装。
- [ ] 既有更新渠道仍与修复目标不一致，且 S08 原有跨模块/设备测试仍未完成；PR #11 保持 draft，不得据此合并或发布。

此工具是**复现和修复手段**，不是实际准备完成的 wheelhouse；发布判断仍为 `RELEASE_BLOCKED`。
