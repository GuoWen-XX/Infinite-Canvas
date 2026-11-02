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

## 先测试再修复的工作次序

- [ ] 软链接跳出自定义目录：读取/删除、按文件 URL 取本地素材、列表元数据；合法自定义外置目录不误拒，Windows 盘符/UNC 不被词法误判。
- [ ] 远程下载：直接内网/IPv6/DNS 重绑定、公共站点跳转私网、越权端口、超大 Content-Length 与实际超长响应；全部 Mock，不接触任何真实网络目标。
- [ ] ZIP：文件数、单文件、总解压/归档字节、下载失败、取消及资源清理；Mock 和小型临时 fixture。
- [ ] 同一 PR 实现最小修复，独立审查并修意见；可执行范围内记录真正的运行结果及 SHA；无法执行的项目完整测试继续保留风险而非自报 PASS。

## S02 延期验证接续

S02 已经以明确风险说明合并，不代表全部验证通过。S08 **发布验收不可省略** S02 正确版本 28 项主程序集成测试与 Windows/LAN/Chrome/Photoshop 联调；见 PR #5 风险放行决定。
