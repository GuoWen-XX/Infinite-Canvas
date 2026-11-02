# S02 — SEC-02 访问边界与 ModelScope Token：只读基线审计

> 审计日期：2026-11-02；基线：`main@0f661b20a0996f311cf187d93c6db2b3f939fd97`（S01 PR #4 已合并）。
> 本文件仅记录从 GitHub 读取源码所得的**静态证据**和下一步测试约束；不是运行时漏洞复现，不代表 S02 修复或验收通过。
> 实施分支：`fix/S02-lan-auth-token`，目标 PR base 必须为 `main`。GitHub Actions 仍保持手动触发，本阶段默认 0 次。

## 1. 当前调用链与安全边界（源码定位）

| 入口 | 现状（main 基线） | S02 必须验证的行为 |
| --- | --- | --- |
| `main.py:125-132` | FastAPI 全局 `CORSMiddleware` 配置 `allow_origins=["*"]`、methods/headers 为 `["*"]`。 | 未授权 Origin 不得读取敏感 API；合法同源、LAN 和插件按认证策略正常使用。 |
| `main.py:13832-13860` | `GET /api/config/token` 返回 `modelscope_api_key()` 或历史配置的明文 Token；对非 LAN 来源仅告警不拦截。 | 未认证请求不能获取原始 Token；后端不向普通浏览器暴露保存的 Token。 |
| `static/zimage.html:383-414` | 云端模式先 GET Token，回退 localStorage，然后把 `api_key` 放入 `POST /generate` 请求体。 | 保留云端生图；服务端保存 Token 不经浏览器中转。 |
| `static/angle.html:953-1025` | 同样 GET Token、localStorage fallback，再把 `api_key` 放入 `POST /api/angle/generate` 请求体。 | 保留角度图生图、上传、状态和错误提示；无明文服务端 Token 下发。 |
| `main.py:18581+` | **已存在本地后端** `POST /generate`：调用 `modelscope_api_key(req.api_key)`，由后端通过 httpx 调 ModelScope。 | 证明无需为此链路从后端向浏览器返回保存 Token；Mock 后端请求，不触发付费任务。 |
| `main.py:18487+` | **已存在本地后端** `POST /api/angle/generate`，也通过 `modelscope_api_key(req.api_key)` 取得有效 Key 并在后端请求。 | 验证服务端 Key fallback 语义，确保无浏览器泄露；检查异常体/日志不泄密。 |
| `main.py:266-278` | `/ws/stats` 在连接开始即 `accept()`，当前路径未看到握手鉴权/Origin 验证。 | 未授权 WS 连接拒绝，授权页面/插件及重连正常。 |
| `main.py:7459-7469` | `GET/PATCH /api/storage-settings` 无路由级鉴权；PATCH 直接调用保存函数。 | 未授权请求在读/写副作用前拒绝；存储路径的细粒度安全限制留在 S03。 |
| `main.py:2605+` | `POST /api/update-from-github` 为高权限更新入口。 | 未授权调用不得启动更新或修改文件。 |
| `main.py:20746` | 服务默认监听 `0.0.0.0:3000`。 | 不以禁用 LAN 代替认证；本机/LAN/Chrome/Photoshop 兼容需要明确验证。 |

**需要更正的旧注释：** `main.py:13834-13838` 声称 ModelScope `/generate` 不在本进程、Token 必须经浏览器中转；但本文件内实际存在 `@app.post("/generate")`。在确认完整调用链之前，不应以该注释为依据保留明文 Token 返回。

## 2. 下一步先写的失败回归测试（Mock/虚构配置）

1. 未认证 `GET /api/config/token`：响应不得含测试 Token（目标 401/403 或移除旧敏感接口）；不得通过 LAN/private-IP 判断放行。
2. 未认证 `PATCH /api/storage-settings` 和 `POST /api/update-from-github`：必须在任何持久化、更新或网络动作前拒绝。
3. 跨源预检及实际敏感请求：攻击者 Origin 不获 CORS 许可；Origin 缺失、伪造 Host、CSRF、DNS rebinding 情况分别验证。
4. 未授权 `/ws/stats`：握手拒绝；合法浏览器与扩展重连、消息投递、状态广播仍工作。
5. `zimage.html` 与 `angle.html`：不再请求明文保存 Token；模拟 `/generate` 与 `/api/angle/generate`，使用服务端虚构 Token 成功到达 Mock httpx，不能发真实外部请求。
6. LAN 浏览器、Chrome 扩展、Photoshop 连接器的授权/迁移样例：先查清当前调用方式，再选会话、Origin/CSRF 与插件认证方案；不得静默破坏旧客户端。
7. 保护错误响应、日志、WebSocket 事件、配置 GET，不泄露虚构测试密钥。

## 3. 设计和执行门禁

- 先补上述最小失败测试，记录**修复前失败**；再以小改动实施认证、Origin/CSRF、WS 和后端 Token 收口。不能仅删除 Token 接口或简单改 CORS 就宣称 SEC-02 完成。
- 本次审计仅基于 GitHub `main` 源码。当前执行容器不能解析 `github.com` 以 clone 全仓；未执行完整仓库 Python/JS/浏览器/LAN/插件测试。必须取得可核查的本地/隔离验证后才创建验收 PR 或合并。
- 任何测试只用 Mock/虚构 Token，禁止真实用户数据、真实 ModelScope 生图、付费额度或自动 GitHub Actions。
- PR 需附准确命令与结果、兼容性迁移方案、回滚方法、独立 Review 和所有阻断意见处理记录；未满足 gate 不进入 S03。
