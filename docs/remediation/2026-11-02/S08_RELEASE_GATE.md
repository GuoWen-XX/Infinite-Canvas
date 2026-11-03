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

## 3. 状态结论

当前：`S08 IN_PROGRESS / RELEASE_BLOCKED`。**S00–S07 阶段已合并，不等于最终验收。** 本仓库缺少能运行完整 checkout 的环境；GitHub Actions 不自动运行也不手动触发。必须保留未执行项目的真实状态，禁止填写“全绿”。
