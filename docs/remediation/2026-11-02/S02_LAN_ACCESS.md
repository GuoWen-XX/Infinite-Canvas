# S02 — LAN、Origin 与 ModelScope 凭据防护迁移说明

目标：关闭默认匿名 LAN 服务和 wildcard CORS；将 ModelScope Token 保存在后端；为确实需要局域网连接的工作室提供显式的认证模式。此文档属于 PR #S02 的实施验收要求。

## 1. 行为变更

| 入口 | 原行为 | S02 新行为 |
| --- | --- | --- |
| `python main.py` | 默认绑定 `0.0.0.0:3000` | 默认绑定 `127.0.0.1:3000`，优先保护单机 |
| LAN 访问 | 默认开放、无认证 | 必须显式设置 `INFINITE_CANVAS_LAN=1` 和 12+ 字符密码，LAN 浏览器提示 HTTP Basic 登录 |
| HTTP API | 任意来源访问 | 本机只允许可信 Host/Origin；LAN 要求认证，防止浏览器跨站读取/操作 |
| WebSocket `/ws/stats` | 任意来源连接 | 与 HTTP 使用相同 Host/Origin/会话验证；未授权连接拒绝 |
| CORS | `allow_origins=["*"]` | 默认无跨源许可，合法扩展 Origin 必须显式列出 |
| `/api/config/token` | 响应完整 ModelScope Token | 仅响应 `{"has_token":true/false,"token":""}`；不下发实际密钥 |
| zimage / angle | 前端先从 API 获取 Token 再发回本机后端 | 前端以 `has_token` 判断；云端请求中的 `api_key` 为空，后端直接使用已保存 Token |
| 旧版浏览器本地 Key | localStorage 兜底 | 过渡期保留旧本地手动 Key，已有后端 Key 时会清理旧缓存 |
| 旧版 global_config.json | token 接口兜底读取 | 完整 Token 仅由后端 `modelscope_api_key()` 读取，支持旧配置兼容 |

## 2. LAN 用户迁移

**默认无需配置**，打开 `http://127.0.0.1:3000/` 即可使用本机画布；使用 `localhost` 也可。

工作室确实要给其他设备访问，启动前在环境变量中设置：

```bash
INFINITE_CANVAS_LAN=1
INFINITE_CANVAS_LAN_PASSWORD=<由用户自己生成的12字符以上强密码>
```

上面是变量名示例，尖括号中的内容不能直接当密码使用，不要把密码写到 Git 仓库或 PR。然后在服务器电脑上执行 `python main.py`，LAN 内其他设备打开 `http://<服务器局域网IP>:3000/`。首次访问会出现浏览器 HTTP Basic 登录窗口：用户名固定 `canvas`，密码为配置的值。成功后 HttpOnly/SameSite 会话 Cookie 为 HTTP 和 WebSocket 提供会话认证（最长 12 小时）。

**网络安全限制**：HTTP Basic 在明文 HTTP 链接上无法抵抗网络嗅探；不应将服务暴露到公网。在不可信 LAN、公共 Wi-Fi 或跨区域访问时，必须通过 HTTPS 反向代理/VPN 等加密链路保护，不能把 LAN 密码当作端到端传输加密。

在手动以 `uvicorn main:app --host 0.0.0.0` 运行时也仍受全局 HTTP/WS 中间件的 LAN 检查；不能借命令行绑定绕开认证。

反向代理从本机 `127.0.0.1` 连接后端时，也不会仅凭代理 TCP 连接来自 loopback 就跳过 LAN 密码；若 HTTP Host 为局域网 IP 或显式授权的 LAN 主机名，仍将执行 LAN 身份检查。代理配置应保留正确的 `Host` 与 `Origin`，建议使用 HTTPS。

## 3. Chrome / Photoshop 兼容要求

- 正常的**本机同源 HTML 页面**直接继续工作，无需向 JS 注入密码。
- Chrome 扩展可能以 `chrome-extension://<extension-id>` 作为 Origin。仅在明确可信时，将它写入环境变量 `INFINITE_CANVAS_TRUSTED_ORIGINS`，多个 Origin 以英文逗号分隔；不能重新打开 wildcard CORS。
- Photoshop UXP 的本机连接器若不发送 Origin，可继续通过 `127.0.0.1` 本地访问；若带有 Origin，则需要将其确切 Origin 加入上述列表。
- LAN 远程扩展/脚本除了可信 Origin，还需要显式 Basic 认证；不能自动从服务器下载共享密码，也不能通过 URL query 传密码。
- WebSocket 客户端不一定都自动附带浏览器 Basic 凭据；同源浏览器使用收到的 HttpOnly Session Cookie。非浏览器连接器如使用远端 LAN，应在其独立客户端实现安全会话/凭据提供，并做联调后才能标记为兼容通过。
- **无法验证的部分**：此阶段的真实 Windows Photoshop/Chrome 插件联调尚须在运行环境执行，不能将配置说明当作实际联调成功。

## 4. 云端素材下载：最小权限临时授权

在使用 API Mart/视频服务的本地音视频参考素材时，云端服务可能需要回调下载 `/assets/...` 或 `/output/...`。这些服务不会携带浏览器 LAN Basic 密码和 HttpOnly Cookie，因此 S02 提供**只读、只限一个文件、30 分钟有效**的签名链接：

- 需要同时配置 `PUBLIC_MEDIA_BASE_URL`（或 `PUBLIC_BASE_URL`）及**至少 24 字符的私密随机密钥** `PUBLIC_MEDIA_TOKEN`；密钥仅在服务端签名，不再直接出现在 URL 中。
- `local_asset_public_url()` 自动生成 `?ic_exp=到期时间&ic_sig=HMAC签名`；签名包括文件路径与到期时间。只允许 GET/HEAD 访问准确的 `/assets/` 或 `/output/` 文件，其他 API、其他文件、到期请求均不能复用授权。
- 公网反向代理仍需保护其余路径，且明确设置 `INFINITE_CANVAS_TRUSTED_HOSTS` 包含实际公网媒体主机名；不要因公网下载需求开放未授权 API。
- 没有配置足够强的 `PUBLIC_MEDIA_TOKEN`，则不产生此类可被云端下载的公网回调链接；应改用已存在的上传素材服务作为替代。
- URL 属于暂时的、可转发的只读授权；云端请求日志可能记录它，所以不要把带签名的 URL 长期保存、公开或放入代码仓库。旧 `?token=<固定密钥>` 形式不再被认可，需要重新生成 URL。
- 此处只解决 S02 回调下载权限，不替代 S03 的存储路径、符号链接、SSRF 和大小/总量限制。

## 5. 验收计划与回滚

隔离测试：Host/DNS rebinding、loopback、非 loopback、Basic（含畸形）、Cookie 生命周期、跨源、合法扩展 Origin、WebSocket 鉴权；Mock ModelScope Token，不调用真实生成接口。必须验证 `/api/config/token` 响应不含原始 Token，并确认 `/generate` 和 `/api/angle/generate` 能使用服务端保存的 Token。

运行时 smoke：单机 Chrome 画布、同源 zimage/angle、Chrome 扩展、Photoshop UXP；带密码的 LAN 浏览器登录及 WebSocket 重连。自动测试不能消费真实 ModelScope 额度。

如认证造成连接器回归，应在 S02 PR 内修复或提出安全的迁移实现，不应退回 `allow_origins=["*"]` / 公开 Token 的旧状态。为回滚做单阶段 revert 前须确认是否会重新开放风险。

## 6. 尚未覆盖的风险

S02 不解决 S03 的存储路径越权与 SSRF，也不解决 S04 画布并发写入；`127.0.0.1` 的本机访问允许无密码，但对本机恶意进程不构成安全边界。LAN HTTP Basic 的防嗅探依赖 HTTPS/VPN；不要把缺失实际设备联调结果标记为已通过。
