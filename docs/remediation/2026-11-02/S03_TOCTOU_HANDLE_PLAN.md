# S03 文件句柄 TOCTOU 修复说明与验证台账

> 原始实现与验证计划写于 PR #6 draft 阶段。**当前状态（2026-11-10）**：PR #6 已合并，代码 HEAD `744a3a152cda8503f9ec2296d4217e5d48622b65`，merge SHA `081edae763ec73505bed9f82e4274bfeaabc16c3`；该 HEAD 的最终 Codex 复审无重大问题，14/14 review threads resolved。
>
> 后续全仓 Linux 验证已覆盖 S03 全部 45 项 Python 回归（16+13+8+5+3），并随完整 24 文件测试集在 `main@98a1f7054b6b8a642c9d8ee7b2be2c497f82bde6` 得到 **310/310 PASS**。当前 `main@cf488ab4347f4239cb391fff98befd7ea5774614` 是 docs-only PR #37 merge，代码/测试树相同。**本记录仍不宣称 Windows HANDLE、UNC/junction、FFmpeg、真实 Range/Streaming 客户端或旧客户端升级已验收**；整体发布继续 BLOCKED。
>
> 下方“尚需门禁”与 33 项测试数量属于早期设计时快照；后续测试扩展到 45 项，Linux 全仓执行结果以上述 S08 §22 为准，平台验收边界不变。

## 问题

先前 `realpath/commonpath` 的字符串检查虽拒绝直接软链接越界，但文件/目录可能在检查到 `FileResponse`、`open(path)`、`zf.write(path)` 或 `os.remove(path)` 之间被可写共享卷上的其他进程替换。Codex 将此评为 P2（review thread `PRRT_kwDOUaWIpM6yq3uo`）。这是实际安全问题而非普通测试设施问题。

## 新代码

- 新增根目录句柄模块 `storage_guard.py`：`open_scoped_file(root,path)` 返回已验证、绑定实际文件的 read-only 文件句柄，`unlink_scoped_file(root,path)` 删除被选择的目录项而非软链接目标。
- POSIX：每层目录从根 `/` 出发通过 `dir_fd` + `O_DIRECTORY|O_NOFOLLOW` 打开；最终文件同样 `O_NOFOLLOW`，不允许检查后再通过可变路径获取内容。删除使用父目录 FD 的 `unlink(..., dir_fd=...)`。合法用户选择的外置盘/目录本身仍可用，但位于其内部、可能跳过根的符号链接不会被信任；别名可通过先解析到同根内目标读入。
- Windows：read-only 文件 FD 在打开后通过 `GetFinalPathNameByHandleW` 取得**实际已打开文件句柄路径**，与用户指定 root 比较后才读。删除使用 `CreateFileW(..., FILE_FLAG_OPEN_REPARSE_POINT)` + `SetFileInformationByHandle` 绑定被选条目；保留 UNC 路径规范化。Windows 真实系统验证尚未执行。
- `main.py` 改动：`/api/storage-files/{kind}/{rel}`、`/api/download-output` 本地分支、共享文件夹读取等返回从已打开句柄流式发送，保留单段 HTTP Range；canvas 图片 ZIP 与 workflow ZIP 逐块读取受约束文件 FD 并核对实际字节配额；图片预览/JPEG 从安全 FD 读取，视频 ffmpeg 在 POSIX 使用继承的 FD 路径，在无 FD 特性的系统采用有上限的私有临时副本。避免先检查后重新用可变路径打开。
- **更新器兼容性**：必须将 `storage_guard.py` 同 `main.py` 一起更新。已将其加入 `update_allowed_file` 且在 `validate_staged_update` 检查新模块存在并可 `compile`，防止自动更新后 `ModuleNotFoundError`。

## 测试证据

- 新增 `tests/test_storage_handles.py`，8 项以 Python stdlib 和该模块验证嵌套合法读、外链拒绝、已打开句柄稳定性、目录换链、根内链接别名删除、根外链接删除拒绝、父目录改名后的受约束删除、UNC 前缀规范化。
- `tests/test_storage_safety.py` 增加了 HTTP 206 Range、生成 StreamingResponse 后替换符号链接仍输出旧句柄内容、非法符号链接 GET 拒绝；现有 12 项。
- S03 其他测试：`tests/test_remote_media_security.py` 8 项；`tests/test_canvas_zip_budget.py` 5 项。本阶段现有新增测试 **33 项**，其中多数**尚未在完整 main.py 项目环境执行**。
- **独立隔离逻辑验证**：2026-11-02 `python -m unittest -v /mnt/data/s03_handle_repro/test_handle_races.py` 得到 `Ran 7 tests ... OK`；它是对 `storage_guard.py` POSIX 操作的提取复现，**不是完整仓库 33 项已通过**。
- 没有触发新的 GitHub Actions。用户已授权的单次 Actions #41439808653 跑的是错误的 `zcode/iteration-01` 默认分支，不能当 S02/S03 的成功证据。

## 尚需门禁

1. 最新 HEAD Codex Review 必须确认句柄安全方案，没有新增 P1/P2；只有这时才能考虑解决原 `PRRT_kwDOUaWIpM6yq3uo` review thread。
2. 在 Windows + UNC/共享路径确认真实 WinAPI 行为；检查 `GetFinalPathNameByHandleW` 返回路径与重解析点/UNC 是否一致，Windows 删除时是否满足原语义；如有回归优先同 PR 修复。
3. 运行主程序 `python -m unittest discover -s tests -p 'test_*.py' -v`、浏览器/Photoshop 接口与合适的 Range/媒体回归，记录准确 HEAD/命令/退出码；本地当前因 GitHub DNS 失败无法 checkout 完整仓库，不能虚构通过。
4. PR #6 原先 5 个评审线程中 4 个已有代码修复且已解决，TOCTOU P2 一条暂留未解决直到最新复审与适用范围确认。
5. 任何风险例外都必须公开记录并明确推迟发布验证，不能静默跳过安全风险。S04–S08 不得重跑 Actions（除非用户重新明确授权）。
