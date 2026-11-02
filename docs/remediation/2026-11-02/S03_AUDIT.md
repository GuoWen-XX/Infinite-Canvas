# S03 安全基线审计（SEC-03 / SEC-04 / SEC-05）

> 起点：S02 PR #5 合并提交 `main@ae042d816c7881005a6e180a8e38aeaa8f9f07f5`。独立分支 `fix/S03-storage-ssrf`；只做代码基线定位，不代表运行时验证。

## 范围与风险

1. **存储根/软链接越权（SEC-03）**：
   - `main.py:496-528` 的 `_storage_abs_path` / `save_storage_settings` 允许在已经认证的本机用户明确指定外置磁盘、UNC/跨盘、自定义绝对目录。这一兼容能力不能简单删除；危险在于**查询/文件路径**不能跳出当前已选根。
   - `main.py:7592-7604` `storage_file_path` 只对字符串 `abspath/commonpath` 做词法比较；根目录里的软链接可能跳到其他路径，`/api/storage-files/{kind}/{rel}` 和 `/api/storage-files/delete` 用此函数读取/删除。
   - `main.py:7606-7632` `output_file_from_url` 以及 `main.py:7861-7877` `local_media_file_by_basename` 只检查字符串路径范围，存在同类软链接问题；`/api/canvas-assets/download` 和 `/api/download-output` 会引用这些函数。
   - `list_storage_files` 遍历时可能给出根外文件 symlink 的名称/大小元数据；应该过滤非法项。
2. **远程 URL / SSRF（SEC-04）**：
   - `main.py:7884-7901` `fetch_remote_media_bytes` 仅校验 `http(s)`，直接 `requests.get(stream=True)` 且默认跟随重定向，没有拒绝 loopback、RFC1918、link-local/cloud metadata、DNS/private IP、redirect-hop。
   - `main.py:12454+` `/api/download-output` 也无目标地址信任约束，且 `Range` 用户头会转发；后续不能只修 `fetch_remote_media_bytes` 就宣称 SSRF 已解决。
3. **ZIP 资源配额（SEC-05）**：
   - `main.py:17074-17129` `/api/canvas-assets/download` 允许最多 1000 项；逐一请求远程内容（单项 max 200MiB），`BytesIO` 在内存构建 ZIP，但没有**整个响应累计上限**和单次工作量上限；需要限制已读取远程字节、总归档大小/文件数量，并防止无限膨胀。保留合法画布导出与重复文件名处理。

## 2026-11-02 初步实施与当前限制

- [x] 本阶段 PR #6 第一批实现：对 `storage_file_path`、`output_file_from_url`、`local_media_file_by_basename`、`storage_file_item` 的根目录判断改为 `realpath/commonpath`，防止目录/文件软链接穿越用户选择的根。保留用户自己配置的绝对路径和 UNC/外置盘含义。
- [x] `tests/test_storage_safety.py`：8 项回归，使用临时路径、非真实私有数据。
- [x] `validate_remote_media_target` 对 HTTP(S)、不带用户名密码、无歧义公网 IP/DNS 做入口检查；`open_safe_remote_media_stream` 禁止自动重定向，逐跳验证；共享给单文件下载与 ZIP 远程媒体读取。
- [x] `tests/test_remote_media_security.py`：5 项 Mock DNS、私网/metadata、私网跳转和超大 Content-Length、合法公网下载回归，不触网。
- [x] `/api/canvas-assets/download` 改用 `SpooledTemporaryFile` 生成 ZIP 后流式返回，限制最多 250 文件、单文件 200 MiB、所有输入合计 512 MiB；`tests/test_canvas_zip_budget.py`：5 项回归。
- [ ] 上述新增 **18 项测试尚未在完整 `main.py` 项目 checkout 实际执行**；必须继续查找可运行隔离环境或补足可核实执行证据，不可宣称 PASS。
- [ ] 目前 DNS `getaddrinfo` 验证与实际 `requests` 建立连接之间仍可能存在 DNS 重绑定时序差；本实现是初步 SSRF 减缓，**不能自称完全消除 SSRF**。需独立 Review 决定是否引入固定已验证 IP 的连接/专用出站代理或出站防火墙。已限制每个重定向目标，拒绝常见私网/metadata，但严格恶意 DNS 仍有残余风险。
- [ ] 文件系统 TOCTOU：检查后文件/软链接可能被另一本地进程替换；需要审核是否有不可信共享卷或并发攻击模型，并评估使用句柄级目录隔离的必要性。
- [ ] 正确分支回归、Linux/Windows UNC/外置盘验证、长期兼容性和实际业务浏览器联调，列入本 PR 后续验收。

## 先测试再修复的工作次序

- [ ] 软链接跳出自定义目录：读取/删除、按文件 URL 取本地素材、列表元数据；合法自定义外置目录不误拒，Windows 盘符/UNC 不被词法误判。
- [ ] 远程下载：直接内网/IPv6/DNS 重绑定、公共站点跳转私网、越权端口、超大 Content-Length 与实际超长响应；全部 Mock，不接触任何真实网络目标。
- [ ] ZIP：文件数、单文件、总解压/归档字节、下载失败、取消及资源清理；Mock 和小型临时 fixture。
- [ ] 同一 PR 实现最小修复，独立审查并修意见；可执行范围内记录真正的运行结果及 SHA；无法执行的项目完整测试继续保留风险而非自报 PASS。

## S02 延期验证接续

S02 已经以明确风险说明合并，不代表全部验证通过。S08 **发布验收不可省略** S02 正确版本 28 项主程序集成测试与 Windows/LAN/Chrome/Photoshop 联调；见 PR #5 风险放行决定。
