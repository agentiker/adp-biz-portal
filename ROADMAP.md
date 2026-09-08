# 统一业务接入平台 ROADMAP

> 关联方案：[docs/plans/2026-09-04-unified-business-platform-design.md](docs/plans/2026-09-04-unified-business-platform-design.md)

更新时间：2026-09-08
总目标：完成统一业务接入平台方案落地，并完成前端 UI/UX 收尾。

## 状态规则

- `DONE`：实现已合入工作区，并有对应测试、验收记录或可复现命令。
- `IN PROGRESS`：已经开始实现，但尚未达到该 TODO 的验收条件。
- `TODO`：尚未开始实现。
- `BLOCKED`：实现需要外部账号、文档、权限或样本；阻塞原因必须写清楚。
- 本地 Mock、单元测试和测试数据库只证明本地行为，不得标记真实 M3、ADP 或微信联调完成。

## 当前快照

| 里程碑 | 状态 | 已处理 | 未处理重点 |
|---|---|---|---|
| M0 技术验证与风险收敛 | 部分完成 | 风险边界和验证清单已整理 | M3/渠道/ADP 的真实文档、权限、样本和联调 |
| M1 业务底座与后台 | 本地第一版和安全回归完成 | 企业、用户、角色、范围、登录、配置、ADP Chat 调试入口、后台浏览器验收和响应式收尾；旧路径安全回归和版本化迁移已完成 | 上游 Workspace 归属闭环、真实跨企业隔离证据、生产多实例限流存储 |
| M2 官网 + M3 只读闭环 | 本地 Worker/Portal 编排和 ADP Provider 边界完成，真实第三方闭环未完成 | 执行上下文、服务端 Agent 映射、ADP SSE/证据边界、M3 受控 Provider、任务队列、可运行 Worker、API 接线、Portal 会话持久化、隔离验收、重试边界和撤权后的待发送任务失效 | 真实渠道接入、真实 ADP Agent 联调、真实 M3 |
| M3 多渠道接入 | 本地统一框架与 Web 渠道 E2E 已完成，微信服务号明文/AES 协议边界已覆盖，真实渠道协议未联调 | 渠道契约/能力声明/注册表、标准入站出站边界、Web 异步入站状态查询、durable inbound -> Worker -> Agent/M3 Provider -> Portal 回复闭环、重复消息幂等和本地隔离验证；平台级渠道凭据边界已完成，渠道身份的平台用户级作用域正在纠偏；微信服务号支持明文与安全模式回调验签/解密/AppID 校验 | 微信客服、企微适配器、真实身份样本、发送协议和真实联调；跨进程重放保护 |
| M4 试运行与交付 | 本地部署基线、文档、发布基础、账号开通材料和安全专项回归完成，生产交付未开始 | OpenAPI/前端类型契约已生成并校验；Docker Compose、环境模板、健康探针、数据字典、排障手册、发布/迁移/回滚运行手册、账号开通 SOP/验收/培训材料已补齐；迁移 CLI、本地隔离 schema 演练和日志/密钥/口令脱敏与权限回归已完成 | 生产部署权限、真实备份恢复、RPO/RTO、压测、正式发布和真实第三方培训交付 |

当前验证基线：本轮部署基线已通过 Compose 配置解析、健康探针定向测试、Python 编译、OpenAPI/前端类型契约检查、渠道框架单测、Web PostgreSQL E2E、一次本地 PostgreSQL 备份恢复演练和 `git diff --check`；验证均为与变更直接相关的定向命令，不重复全量后端或浏览器测试。真实 ADP/M3/渠道联调仍不在本地验证范围内。

部署进展（2026-09-07）：已将当前提交部署到火山引擎 `xdimspace-01:/opt/tencent-adp-gateway`；服务器重启后重新构建应用镜像并执行迁移到 schema revision 10，Compose 的 PostgreSQL、API、Worker 和反向代理均已健康运行。公网 `https://adp.xdimspace.cn/healthz` 与 `/readyz` 均返回 200，首页直接返回新版静态 HTML；Let’s Encrypt 证书的 SAN 为 `adp.xdimspace.cn`，有效期至 2026-12-06。服务器 `.env`、PostgreSQL 数据卷和证书均未覆盖。已停止该服务器上的全部 `aifrelo-*` 容器，并删除 `dk_wordpress-wordpress-1`、`dk_wordpress-db-1` 及其绑定目录；WordPress 数据不可恢复。

微信固定回调（2026-09-07）：新增 `/wechat/callback` 和 `/api/v1/channels/wechat-official-account/callback`。固定入口仅在恰好一个启用的微信服务号实例时工作；微信服务号 XML 回调不携带 AppID，无法安全地凭 AppID 在多个 Token 之间猜测，因此多实例场景继续使用带固定实例 ID 的 URL。

当前任务计数：`47 / 63` 项已完成，`16` 项未完成（其中 `7` 项 `BLOCKED`、`5` 项 `IN PROGRESS`、`4` 项 `TODO`）。新增 `M2-ADP-ROUTE-01`（DONE，Worker 默认路由平台唯一 ADP 应用、不以 M3 为前置）与 `M3-WECHAT-OA-03`（IN PROGRESS，ACK+流式+Markdown+图文卡片，对齐 ADP 原生体感，含一处有意的证据校验范围变更）。首个真实微信认证服务号已接入并完成绑定/入站/出站真实联调。新增 `M3-REFACTOR-01`（渠道适配层结构化 + 契约中性化 + crypto 统一 + `channel_ingress` seam，作为微信客服/企微适配器前置）。多渠道适配参考调研（openclaw-china / AstrBot / LangBot）已完成并定为库级借鉴、不迁宿主：见 `docs/plans/2026-09-08-channel-adapter-reference-research.md`。`M3-PLATFORM-SCOPE-01` 已完成：平台唯一 ADP 应用由服务器 `.env` 提供，渠道实例独立于企业，企业范围只在消息身份鉴权和业务执行阶段生效。新增并完成 `M2-CHANNEL-FIX-01`（渠道投递与企业范围偏差纠正）和 `M2-TEST-FIX-01`（测试基座路由重复注册修复）。`M3-IDENTITY-01` 正在纠正历史实现中渠道身份固定关联企业、以及渠道执行依赖浏览器登录态的偏差；真实 ADP/M3/微信第三方联调仍未完成。

## M0：技术验证与风险收敛

### 已处理

- [x] `M0-DOC-01` 整理 ADP、M3 和多渠道接入的边界、风险和验证项。
  - 完成证据（2026-09-05）：方案文档第 5-7、14-17 节。
- [x] `M0-DOC-02` 在方案中明确 Mock/本地验证与真实第三方联调的区别。
  - 完成证据（2026-09-05）：方案状态和实施进度表；ROADMAP 状态规则。
- [x] `M0-DOC-03` 建立统一 ROADMAP，并把 TODO 状态同步规范写入代理协作说明。
  - 完成证据（2026-09-05）：`ROADMAP.md`、`AGENTS.md`、`CLAUDE.md`。

### 未处理 TODO

- [ ] `M0-EXT-01` 获取正式 M3 API 文档、测试权限、字段归属规则、分页、限流、错误码和 Token 生命周期。
  - 状态：`BLOCKED`
  - 依赖：客户提供 M3 测试环境和权限。
  - 验收：形成 M3 字段清单、接口契约、错误码映射和权限映射记录。
- [ ] `M0-EXT-02` 获取至少两家企业的隔离测试数据，验证客户编码和记录归属。
  - 状态：`BLOCKED`
  - 依赖：脱敏测试数据和企业授权。
  - 验收：A 企业无法读取 B 企业记录，混合归属和无归属记录有明确安全处理。
- [ ] `M0-ADP-01` 联调当前 ADP 应用模式的隐藏运行参数：`ApplicationId`、`ConversationId`、`IsChannel`、`CustomVariables`。
  - 状态：`BLOCKED`
  - 依赖：ADP 测试应用、回调地址和工具调用权限。
  - 验收：记录真实请求/回调契约、服务身份校验方式和结构化结果行为。
- [ ] `M0-CHANNEL-01` 获取真实渠道回调样本，确认发送者身份、回复窗口、回调验签/解密和长连接或回调模式。
  - 状态：`BLOCKED`
  - 依赖：微信服务号、微信客服和企微账号权限。
  - 验收：每个渠道形成协议样本、身份映射键和失败重试边界。
- [x] `M0-ADP-02` 排查 ADP 管理 API 元信息异常，并与聊天能力分开记录降级行为。
  - 状态：`DONE`（2026-09-06，本地降级边界）
  - 完成证据：`server/middleware/application.py` 对每个应用独立刷新元信息；单个 `get_info()` 异常不会阻断启动刷新、其他应用或聊天路由；保留上次成功元信息，并在 `metadata_status` 标记 `degraded` 与 `chatStatus=unchanged`；错误类型和脱敏原因写入 `PlatformAuditEvent`，动作是 `adp.metadata.refresh`，处理策略记录为 `last_known_metadata_or_application_id`。
  - 验证命令与结果：`server/.venv/bin/pytest server/test/unit_test/test_application_metadata.py -q` 为 `2 passed`；`server/.venv/bin/python -m py_compile server/middleware/application.py server/test/unit_test/test_application_metadata.py`、`git diff --check` 通过。
  - 遗留风险：本地用例覆盖异常隔离和审计落库契约；真实 ADP 管理 API 错误码、元信息字段和账号权限仍需 `M0-ADP-01` 的正式联调确认。
- [ ] `M0-M3-01` 确认 M3 只读接口支持企业范围/记录归属校验；若不支持，确定网关内的安全过滤方案。
  - 状态：`BLOCKED`
  - 依赖：`M0-EXT-01` 和 `M0-EXT-02`。
  - 验收：权限判断不依赖提示词，字段过滤和归属校验可测试。

## M1：业务底座与可用后台

### 已处理

- [x] `M1-DATA-01` 建立企业、用户、成员、角色、企业范围、账号状态和平台会话相关模型。
  - 完成证据（2026-09-05，本地）：`server/model/platform.py`、`server/model/__init__.py`、`server/core/migration.py`。
- [x] `M1-AUTH-01` 完成本地手机号登录、平台会话和管理员调试账号引导能力。
  - 完成证据（2026-09-05，本地）：`server/router/platform.py` 的登录/会话 API、`client/packages/app/src/pages/Login.vue`、`script/bootstrap-local-admin.py`。
- [x] `M1-AUTH-02` 支持管理员重置密码和停用账号；权限变化可使旧执行上下文失效。
  - 完成证据（2026-09-05，本地）：`server/core/platform.py`、`server/test/unit_test/test_platform_config.py`。
- [x] `M1-ADMIN-01` 完成企业/用户/角色/范围的后台 API 与前端第一版骨架。
  - 完成证据（2026-09-05，本地）：`server/router/platform.py`、`client/packages/app/src/pages/Admin.vue`、`client/packages/app/src/platform/platformService.ts`。
- [x] `M1-CONFIG-01` 完成配置草稿校验、发布、回滚和基础审计能力的本地实现。
  - 完成证据（2026-09-05，本地）：`server/core/platform.py`、`server/test/unit_test/test_platform_config.py`；发布/回滚单测通过。

### 未处理 TODO

- [x] `M1-ADMIN-02` 将旧 ADP Chat 页面迁移到 OceanDesk Admin，提供受权限保护的 ADP API 调试入口。
  - 状态：`DONE`（2026-09-06，本地实现与真实浏览器验收）
  - 完成证据：新增 `client/packages/app/src/pages/AdminAdpChat.vue` 和 `admin-adp-chat` 路由，接入 Admin 侧栏；复用旧 ADP Chat 组件，支持应用列表、应用切换、会话恢复/新建、URL 同步、消息发送和文件上传入口。
  - 认证边界：`POST /api/v1/admin/adp-chat/context` 仅允许当前 Platform Session 且要求 `platform.manage`；签发 5 分钟短时 `admin_adp_chat` 调试 Token，并要求 `X-Admin-ADP-Context: 1` 才能访问旧兼容接口；`platform_login` 明确不能访问旧 ADP 路径；上下文签发写入 `adp.admin_debug_context.issue` 审计事件。
  - 代理与前端收尾：`client/packages/app/vite.config.ts` 保留 `/api/v1/*` 完整路径并兼容旧 `/api/*`；Admin Chat 使用独立调试 Token，401 不触发平台全局登出；页面包含无应用、上下文失败和请求错误状态，窄屏侧栏可折叠且无横向溢出。
  - 验收证据（2026-09-06，真实 Chrome/Playwright + 用户手测）：管理员登录后从后台导航进入调试页，已绑定应用加载成功，会话列表/历史消息加载成功，新建会话并发送 `hi` 后收到 ADP 回复；桌面和 `390x844` 移动端截图保存在 `output/playwright/admin-adp-chat-desktop.png`、`output/playwright/admin-adp-chat-mobile.png`；浏览器控制台 `0 errors / 1 warning`，唯一告警为编辑器高度提示，不影响功能或布局。
  - 验证命令与结果：`cd client/packages/app && npm run type-check` 通过；后端 `python -m compileall -q server/core/platform.py server/router/__init__.py server/router/platform.py` 通过；用户已完成手动功能验收。真实 ADP/M3/渠道协议联调仍由对应 `BLOCKED`/`IN PROGRESS` 项负责。

- [x] `M1-SEC-01` 回归所有旧登录后路径，确认普通用户不能通过旧 forward/chat/action 参数绕过管理权限或企业范围。
  - 状态：`DONE`（2026-09-06，本地安全边界完成）
  - 验收：直接调用管理 API、伪造 `enterprise_id`/`ApplicationId`/`ConversationId` 等均被拒绝或忽略。
  - 本轮完成（2026-09-06，本地）：`server/router/legacy_security.py` 建立旧 Action 显式白名单、管理员 Action 隔离、客户端身份字段清洗、会话归属和应用归属校验；`server/router/forward.py`、`server/router/file_download.py` 增加文件应用 ID、Workspace/路径格式和路径穿越校验；`server/router/reference.py` 的公开分享引用详情使用服务端保存的 `ApplicationId`，不信任客户端值。
  - 回归证据：`test/unit_test/test_legacy_route_security.py`、`test/unit_test/test_legacy_route_security_api.py`、`test/unit_test/test_reference.py` 及 `test/unit_test/test_chat.py` 定向回归 `17 passed`（2026-09-06）；覆盖普通账号的管理 Action 拒绝、伪造 ApplicationId/ConversationId/WorkspaceId/AppId 拒绝、IsChannel/CustomVariables 身份冒用拒绝、路径穿越拒绝，以及管理员显式 Action 白名单和兼容回退路径。数据库 schema revision `7` 已升级并通过启动守卫；`./.venv/bin/python -m compileall -q server`、`git diff --check` 通过。
  - 遗留风险：平台侧 Workspace 绑定模型已由 `M1-SEC-03` 补齐，但真实 ADP Workspace 的第三方归属和跨企业隔离样本仍缺失，无法仅凭本地代码证明上游数据不会混租；需要正式 ADP 契约、企业隔离测试数据和数据库可用的 API 回归。真实 ADP 联调仍未完成，不能将本地 Mock/单测视为完成。
  - 额外边界：旧 `/application/list`、`/chat/message`、`/adp/<action>`、`/file/parse`、`/file/download` 现在均通过服务端 active binding 过滤，客户端可见应用列表和 `ApplicationId`/`WorkspaceId` 只作为选择器，不是授权证据；本机 PostgreSQL 已恢复，revision `7` 下的 API 级回归已补跑并通过。
- [x] `M1-SEC-03` 建立旧应用与企业 Workspace 的服务端绑定模型，并让旧兼容路由统一按绑定解析应用和 Workspace。
  - 状态：`DONE`（2026-09-06，本地实现）
  - 目标：`/application/list`、`/chat/message`、`/adp/<action>`、`/file/parse`、`/file/download` 不再把客户端提交的 `ApplicationId`/`WorkspaceId` 当作授权依据；绑定停用后立即失效，并留下管理审计记录。
  - 完成证据（2026-09-06，本地）：新增 `IntegrationConnection`、`EnterpriseExternalAccount` 和 migration revision `7`；`server/core/legacy_binding.py` 统一按 active 账号、企业、应用和 Workspace 解析绑定；旧 application/chat/adp/file 路由已接入；新增管理员绑定列表、创建和停用 API，停用立即失效并写入 `integration.binding.disable` 审计事件。
  - 定向验证：`server/.venv/bin/pytest server/test/unit_test/test_platform_migration.py -q`（4 passed）；`server/.venv/bin/pytest server/test/unit_test/test_legacy_binding.py -q`（3 passed）；`server/.venv/bin/pytest server/test/unit_test/test_legacy_route_security.py -q`（7 passed）；输出保存在 `output/tests/m1-sec-03-platform-migration-targeted.txt`、`output/tests/m1-sec-03-legacy-binding-targeted.txt` 和 `output/tests/m1-sec-03-legacy-route-unit-targeted.txt`。`server/.venv/bin/python -m compileall -q server`、`git diff --check` 已通过。
  - 验证边界：此前一次带 Sanic/数据库启动的 API 回归因本机 PostgreSQL `127.0.0.1:5433` 未运行而停在 fixture setup，未将其误计为代码断言失败；数据库恢复到 `127.0.0.1:5432` 且 revision `7` 后，已由 `M1-SEC-01` 定向补跑旧路由 API 回归。真实 ADP Workspace 第三方归属、跨企业样本仍由 `M0-ADP-01`/`M0-EXT-02` 阻塞，不能以本地测试宣称真实第三方联调完成。
- [x] `M1-QA-01` 使用真实浏览器验收 `/admin#/admin/enterprises`、用户、角色和配置页面。
  - 完成证据（2026-09-05，真实 Chrome/Playwright）：管理员登录后验收 `/admin#/admin`、`/admin#/admin/enterprises`、`/admin#/admin/agents-tools`、`/admin#/admin/bindings`、`/admin#/admin/channels`、`/admin#/admin/audit`；覆盖配置编辑/保存草稿、企业详情、用户详情、新增企业、重复 M3 编码错误、新增用户、初始密码仅显示一次、重置密码、停用用户、停用状态刷新和访问范围编辑。
  - 验收结果：列表、创建、编辑、停用、错误提示和刷新均可操作；停用用户显示“已停用”且相关操作禁用；重复编码显示后端业务错误 `M3 客户编码已存在`；浏览器控制台在初次基线为 `0 errors / 2 warnings`，告警已在本轮 `M1-UI-01` 收口并复核为 `0 errors / 0 warnings`。
  - 截图证据：`output/playwright/admin-overview-desktop.png`、`admin-enterprises-clean-desktop.png`、`admin-enterprises-clean-mobile.png`、`admin-config-editor-desktop.png`、`admin-access-editor-mobile.png`。
- [x] `M1-UI-01` 校正企业与用户页面按钮间距、对齐、工具栏密度和窄屏响应式表现。
  - 完成证据（2026-09-06）：`client/packages/app/src/pages/Admin.vue` 统一间距 token、控件高度和行操作触控区域；新增概览双栏 grid item 的 `min-width: 0`、长文本断词和审计时间省略规则，修复 320px 配置编辑弹窗打开时底层面板被撑宽的问题。
  - 交互收尾（2026-09-06）：新增企业/用户提交期间锁定关闭、取消和重复提交；用户重置/停用仅锁定当前行并显示处理中状态；访问范围弹窗沿用提交锁定；Portal 查询区分无授权与查询中状态并显示对应光标。
  - 验证命令：`cd client/packages/app && npm run type-check`（通过）；`npm run build-only`（通过，仅保留既有大 chunk warning）；`node /Users/jyxc-dz-0100610/.codex/skills/impeccable/scripts/detect.mjs --json --scope layout client/packages/app/src/pages/Admin.vue client/packages/app/src/components/PlatformShell.vue client/packages/app/src/assets/main.css`（输出 `[]`）。
  - 浏览器验收（本地 `http://127.0.0.1:5175`，真实 Chrome/Playwright）：企业/用户页覆盖 `320x844`、`390x844`、`768x900`、`1280x900`；配置编辑弹窗覆盖 `320x844`、`390x844`；访问范围弹窗覆盖 `320x844`、`390x844`。所有场景 `document.documentElement.scrollWidth - innerWidth === 0`，顶部操作、行操作、关闭和弹窗 footer 按钮均至少 `44px` 高，配置/访问范围弹窗 footer 未遮挡内容；本轮刷新复核控制台为 `0 errors / 0 warnings`。
  - 截图证据：`output/playwright/m1-ui-01-config-320-final.png`、`m1-ui-01-config-390.png`、`m1-ui-01-access-320-final.png`、`m1-ui-01-access-390-final.png`、`m1-ui-01-enterprises-390.png`、`m1-ui-01-enterprises-1280.png`。
  - 告警收口（2026-09-06）：`client/packages/app/src/App.vue` 显式注册 TDesign `ConfigProvider`；`client/packages/adp-chat-component/src/components/FileDir/index.vue` 删除无对应 Props 的 `emptyText` 默认值。复核页面控制台为 `0 errors / 0 warnings`；旧样式块仍保留少量非 4pt 间距值，但不影响本次验收的布局、触控尺寸和响应式表现。
  - 本轮定向复核（2026-09-06）：复用真实 Chrome 会话刷新企业页，`scrollWidth === clientWidth`，控制台 `0 errors / 0 warnings`；`npm run type-check`、`git diff --check` 通过。本轮未重复全量后端或浏览器测试。
- [x] `M1-SEC-02` 核查初始 6 位口令的随机生成、哈希保存、限流/锁定及日志脱敏。
  - 状态：`DONE`（2026-09-06）
  - 完成证据（2026-09-06，本地）：`server/core/platform.py` 使用 `secrets.randbelow()` 生成 6 位数字，使用独立随机 salt + PBKDF2 保存 `PasswordHash`/`PasswordSalt`，新账号 `MustReset=True`；认证查询凭据使用 `with_for_update()`，连续 5 次失败锁定 15 分钟，成功登录清零失败计数并解除过期锁定状态；来源组合限流按规范化手机号 + IP 执行 10 次/15 分钟。
  - 审计与脱敏证据（2026-09-06，本地）：`server/router/platform.py` 的登录失败审计仅记录 `phone=provided/missing` 与 `rateLimited`，不写入手机号值、口令或 Token；错误响应、异常文本和捕获日志回归确认不含提交口令。
  - 测试证据：`server/test/unit_test/test_platform_auth_security.py` 覆盖 6 位随机性、哈希验证/明文不落库、`MustReset`、5 次失败锁定、锁定期正确口令拒绝、成功清零、手机号 + IP 第 11 次触发限流、普通失败/限流审计脱敏；专项 `./.venv/bin/pytest test/unit_test/test_platform_auth_security.py -q` 为 `7 passed`；配置回归 `./.venv/bin/pytest test/unit_test/test_platform_config.py -q` 为 `27 passed`；全量 `./.venv/bin/pytest -q` 为 `76 passed, 5 skipped`；`./.venv/bin/python -m compileall -q .`、`git diff --check` 通过。
  - 测试产物：`output/tests/m1-sec-02-auth.json`。
  - 遗留风险：当前来源限流使用进程内 `limits.aio.storage.MemoryStorage`，多 Worker/多实例生产环境必须替换为共享 Redis 或数据库限流存储，并补充跨实例验收；账号级失败锁定已通过数据库行锁持久化，可跨进程生效。
- [x] `M1-MIG-01` 将启动时建表逻辑迁移为有版本的数据库迁移流程。
  - 状态：`DONE`（2026-09-06）
  - 完成证据：`server/core/migration.py` 提供 `1 -> 7` 版本化迁移、`platform_migration` 审计记录、checksum 校验、事务级 PostgreSQL advisory lock、重复执行和显式数据丢失确认的回滚；`server/migrate.py` 提供 `upgrade`/`downgrade` CLI；`server/middleware/database.py` 启动阶段仅执行 `Migration.validate_startup()`，不再 `metadata.create_all()` 或写入默认配置。
  - 验证命令与结果：`PLATFORM_TEST_DATABASE_URL=... server/.venv/bin/pytest test/integration/test_platform_migration_postgres.py -q -s` 覆盖 revision `1..9`、重复升级、回滚到 `3` 和再次升级；`server/.venv/bin/pytest test/unit_test/test_platform_migration.py -q` 覆盖连续 revision 和启动守卫；`python -m compileall -q server`、`git diff --check` 通过。
  - 测试产物：`output/tests/m1-mig-01-migration.json`。
  - 遗留风险：当前迁移覆盖 PostgreSQL 和本地开发验证；生产发布仍需在 `M4-RELEASE-01` 中完成部署账号、迁移演练、备份和回滚流程。

## M2：官网 + M3 完整只读闭环

### 已处理

- [x] `M2-ACCESS-01` 建立 TrustedContext、权限版本和执行上下文生命周期校验。
  - 完成证据（2026-09-05，本地）：`server/core/platform.py` 的执行上下文加载/校验逻辑。
- [x] `M2-ACCESS-02` 覆盖上下文过期、撤销、角色/企业范围收窄和工具请求 ID 重放测试。
  - 完成证据（2026-09-05，本地）：`server/test/unit_test/test_platform_config.py`；相关安全测试通过。
- [x] `M2-M3-01` 实现受控的 M3 只读适配器、参数校验、字段白名单和证据化结果结构（本地 Mock/契约级）。
  - 完成证据（2026-09-05，本地 Mock）：`server/integrations/m3/adapter.py`、`server/test/unit_test/test_m3_adapter.py`。
- [x] `M2-DELIVERY-01` 实现入站去重、出站幂等、同会话 FIFO、租约领取/续租/过期恢复基础设施。
  - 完成证据（2026-09-05，本地）：`server/core/delivery.py`、`server/test/unit_test/test_delivery.py`。
- [x] `M2-DELIVERY-02` 增加 delivery 单测和隔离 schema 的 PostgreSQL 集成测试入口。
  - 完成证据（2026-09-05）：`server/test/integration/test_delivery_postgres.py`、`server/test/conftest.py`、`server/pyproject.toml`；PostgreSQL 集成测试 `3 passed`。
- [x] `M2-WORKER-01` 实现第一个真实 Worker handler/API 接线：读取入站任务、校验平台身份和企业范围、调用受控工具、持久化结果、创建出站回复任务。
  - 完成证据（2026-09-05，本地 PostgreSQL + M3 Mock/契约级）：`server/core/platform_worker.py`、`server/router/platform.py`、`server/core/delivery.py`、`server/test/integration/test_platform_worker_postgres.py`。
  - 验证命令：`PLATFORM_TEST_DATABASE_URL='postgresql+asyncpg://adp_chat_client_local@127.0.0.1:5432/adp_chat_client_local' server/.venv/bin/pytest server/test/integration/test_platform_worker_postgres.py server/test/integration/test_delivery_postgres.py -q -s`，结果 `5 passed`。
  - 覆盖范围：正常入站到出站链路、工具结果与 evidence 持久化、回复幂等、停用账号不可重试；租约过期恢复由 `test_delivery_postgres.py::test_postgres_reclaims_expired_lease` 覆盖。未完成真实 M3 或渠道联调。

- [x] `M2-WORKER-02` 将官网本地 API 接入标准化入站和回调去重。
  - 状态：`DONE`（2026-09-06，本地官网适配器）
  - 完成证据：新增 `server/integrations/channels/web.py` 的 `WebChannelAdapter`，把已认证平台会话转换为 `InboundMessageInput` 和 `platform.inbound.process` 任务；新增受 `platform_required` 和 `shipment.read` 保护的 `/api/v1/channels/web/inbound`，调用 `record_inbound_message()` 后返回 `inboundMessageId`、`taskId`、`created` 和状态。
  - 安全边界：`platformUserId`、`platformSessionId`、`enterpriseId`、发送者身份和账号范围均由服务端上下文生成；浏览器同名字段不参与授权。`messageId`/`X-Message-Id` 作为重试稳定的外部消息键，缺失时生成一次性 ID；`channelInstanceId=web-portal` 与 `externalMessageId` 共同复用 delivery 唯一约束。
  - 验证命令与结果：`server/.venv/bin/pytest server/test/unit_test/test_web_channel.py -q` 为 `4 passed`；`server/.venv/bin/python -m compileall -q server` 通过；`git diff --check` 通过。测试产物：`output/tests/m2-worker-02-web-channel.json`。
  - 遗留风险：当前完成的是官网本地协议适配器和标准入站入口，不代表微信服务号、微信客服或企微真实协议联调；真实渠道仍由 M3 TODO 和 `M0-CHANNEL-01` 依赖负责。现有 Portal 同步查询接口仍保留，官网新入站入口交由 Worker 异步处理，Portal 异步结果展示和 Agent/ADP 编排由 `M2-ORCH-01` 负责。

- [x] `M2-WEB-01` 完成官网会话、消息、执行轮次和证据的持久化与查询接口，并接入 Portal 页面。
  - 状态：`DONE`（2026-09-06）
  - 完成证据：新增 `PlatformMessage`、`PlatformExecutionRun`、`PlatformEvidence` 模型及 migration revision `6`（当前总 schema revision 为 `7`）；`server/router/platform.py` 持久化官网用户消息、执行轮次、M3 受控 evidence 和 assistant 结果，提供 `GET /api/v1/portal/sessions/<conversation_id>`；`client/packages/app/src/pages/Portal.vue`、`client/packages/app/src/platform/platformService.ts` 支持会话列表、历史详情点击、URL `conversationId` 刷新恢复。
  - 隔离边界：会话列表、详情、消息、run、evidence 均按 `AccountId` 和 `EnterpriseId` 查询；同企业不同账号访问彼此会话统一返回“会话不存在或无权访问”。
  - 验证命令与结果：使用 `.env` 动态构造 `PLATFORM_TEST_DATABASE_URL`，运行 `server/.venv/bin/pytest test/integration/test_portal_session_postgres.py::test_portal_persists_history_and_keeps_same_enterprise_users_isolated -q -s` 为 `1 passed`；覆盖两轮查询、4 条消息、2 个 execution run、最新 evidence 恢复和同企业跨账号拒绝；迁移 revision `6` 引入验收同步为 `1 passed`，当前总 schema revision 为 `7`。测试产物：`output/tests/m2-web-01-portal.json`。
  - 遗留问题：当前仅完成本地 PostgreSQL + M3 Mock/契约级官网闭环；真实 M3、ADP 编排和微信/企微渠道仍分别由 `M2-M3-02`、`M2-ORCH-01` 和 M3 TODO 负责。

- [x] `M2-RETRY-01` 分离业务执行重试与发送重试；外部发送结果未知时支持状态查询或上游消息 ID 去重。
  - 状态：`DONE`（2026-09-06，本地任务队列/发送器契约）
  - 完成证据：`server/core/delivery.py` 新增显式 `DeliveryRetryableError`；只有该错误进入有限次数重试，未分类异常终止任务，`DeliveryUncertainError` 进入 terminal `uncertain` 且不自动重试。`server/core/platform_worker.py` 为业务任务和回复任务设置独立 attempt 上限，持久化服务端生成的会话/轮次 ID，回复任务持久化稳定 `platform-reply:<inboundMessageId>` 幂等键并传给渠道发送器；`server/core/platform.py` 允许同一授权范围内恢复 `started` 工具调用，已完成调用仍拒绝重放。
  - 验证命令与结果：`server/.venv/bin/pytest server/test/unit_test/test_platform_config.py::test_load_execution_context_rejects_replayed_tool_request server/test/unit_test/test_delivery.py server/test/unit_test/test_platform_worker_retry.py -q` 为 `13 passed`；`PLATFORM_TEST_DATABASE_URL='postgresql+asyncpg://adp_chat_client_local@127.0.0.1:5432/adp_chat_client_local' server/.venv/bin/pytest server/test/integration/test_platform_worker_postgres.py::test_business_retry_recovers_started_tool_call server/test/integration/test_platform_worker_postgres.py::test_reply_retry_reuses_persisted_result_without_running_m3_again -q -s` 为 `2 passed`；编译检查和 `git diff --check` 通过。
  - 测试产物：`output/tests/m2-retry-01.json`，记录业务执行 M3 调用次数为 `1`、回复发送尝试 `2`、最终状态 `succeeded` 和未知结果不自动重试策略；业务重试用例同时确认同一 `PlatformToolCall` 记录被恢复。
  - 遗留风险：真实渠道的状态查询/上游幂等协议仍需在获得渠道协议样本后实现；当前本地发送器契约已提供稳定幂等键和明确 uncertain 状态，不能替代真实渠道联调。

- [x] `M2-ACCESS-03` 端到端验证用户停用、企业变更、角色收窄、密码重置后旧会话、旧上下文和待发送任务立即失效。
  - 状态：`DONE`（2026-09-06，本地 PostgreSQL 撤权闭环）
  - 完成证据：`server/core/platform.py` 新增账户回复任务撤销；密码重置、用户停用、角色/企业范围变更会将尚未终态的 `platform.reply` 标记为 `failed`，错误码为 `authorization_revoked`；`server/core/platform_worker.py` 在官网和外部渠道发送前重新校验账号、用户、会话、企业、membership 及 `shipment.read` 权限，拒绝时写入 `platform.reply.reject` 审计事件。
  - 验证命令与结果：`PLATFORM_TEST_DATABASE_URL=... server/.venv/bin/pytest server/test/integration/test_platform_worker_postgres.py -q` 为 `11 passed`；覆盖 session 撤销、用户停用、账号停用、membership 解绑、企业停用和角色收窄；另有队列尚未 claim 时的撤销用例。定向单测 `server/.venv/bin/pytest server/test/unit_test/test_platform_worker_retry.py server/test/unit_test/test_platform_config.py -q` 为 `30 passed`。
  - 安全证据：撤权后回复任务均为 `failed/authorization_revoked`，外部发送器调用次数为 `0`，M3 仅在撤权前执行一次，私有 evidence 不会再次发送；测试产物：`output/tests/m2-access-03-revocation.json`。
  - 遗留风险：真实 ADP/M3 和微信/企微渠道仍未联调；本项证明的是本地授权状态、任务队列和发送器契约在撤权后的即时失效。

- [x] `M2-UI-02` 收口 Portal 查询、会话和空状态的交互尺寸、焦点态与窄屏布局。
  - 状态：`DONE`（2026-09-06）
  - 范围：所有主要操作达到 44px 触控高度；移动端查询操作保留可读标签；无动作控件不伪装成按钮；加载、错误和空状态提供稳定的键盘焦点与操作反馈。
  - 验收：`client/packages/app/src/pages/Portal.vue` 在 320px、390px、768px 和 1280px 视口均无横向溢出；概览、查询和会话页主要操作达到至少 44px 触控高度；移动端查询按钮保留“查询”标签；“按最近更新”为普通状态文本；查询示例、空状态和会话页“发起查询”均可通过 Tab 聚焦并显示焦点环；构建与类型检查通过。
  - 浏览器证据：Playwright 本地 QA 用户在四视口完成概览、查询和会话页验收，历史基线控制台为 `0 errors / 2 warnings`；本轮前端告警收口后刷新复核为 `0 errors / 0 warnings`。会话页测得 `scrollWidth === innerWidth`，`发起查询`按钮为 `100x44px`，`按最近更新`节点为 `SPAN`，空状态“还没有查询会话”可见。截图：`output/playwright/m2-ui-02-overview-{320,390,768,1280}.png`、`output/playwright/m2-ui-02-lookup-{320,390,768,1280}.png`、`output/playwright/m2-ui-02-sessions-{320,390,768,1280}.png`。
  - 验证命令与结果：`npm run type-check`、`npm run build-only`、`git diff --check` 通过；Portal 概览、查询和会话页已完成真实浏览器四视口验收及 Tab 焦点检查。
  - 遗留风险：本地页面控制台告警已清零；真实第三方渠道和生产环境仍需独立联调与验收。

### 未处理 TODO

- [x] `M2-UI-03` 完成全局前端 UI/UX 审计并收口基础设计系统告警。
  - 状态：`DONE`（2026-09-06，本地 UI/UX 收尾）
  - 范围：按 Impeccable product register 检查字体、响应式布局、焦点态、控件尺寸、空状态和页面横向溢出；以 Admin/Portal 现有页面为本地验收范围。
  - 完成证据：基础字体栈已移除 `Inter` 首位依赖，统一使用系统无衬线栈；Admin/Portal 页面保留现有产品视觉语言并完成响应式、控件尺寸、焦点态和空状态检查。Impeccable layout detector 对 `Admin.vue`、`Portal.vue`、`PlatformShell.vue`、`main.css`、`base.css` 输出 `[]`；本轮补齐 TDesign `ConfigProvider` 运行时注册并清除 FileDir 无效 `emptyText` 默认值。
  - 验证命令与结果：`cd client/packages/app && npm run type-check`、`npm run build-only`、`git diff --check` 通过；Admin 企业/用户页在 `1280x900` 和 `390x844` 真实浏览器验收通过，`document.documentElement.scrollWidth === innerWidth`、`body.scrollWidth === innerWidth`，刷新后控制台 `0 errors / 0 warnings`。截图：`output/playwright/m2-ui-03-enterprises-1280.png`、`output/playwright/m2-ui-03-enterprises-390.png`。
  - 遗留问题：本地 UI/UX 告警已清零；真实第三方渠道、ADP 和生产交付仍按对应 ROADMAP 项阻塞或进行中。

- [ ] `M2-CHANNEL-FIX-01` 纠正渠道投递与企业范围的实现偏差（渠道接入审查产出）。
  - 状态：`DONE`（2026-09-08，本地实现与回归；真实渠道发送仍由 `M0-CHANNEL-01`、`M3-QA-01` 阻塞）
  - 背景：多渠道接入设计/实现审查发现四处与方案 §6.2、§6.3、§7.2、§13.1 不一致的实现，均已在本项修复。
  - 修复一（官网多企业静默选择）：`/api/v1/channels/web/inbound` 与 `/api/v1/portal/overview` 过去经 `get_enterprise_for_user()` 取按名称排序的第一个企业，多企业用户会被静默按错误企业作答，而微信路径同一情况是拒绝的。现新增 `core/platform.py::resolve_enterprise_scope()` 供两条渠道共用：显式 `enterpriseId` 必须命中当前有效 membership，缺失时只有单一有效企业才自动选择，多企业一律拒绝并要求明确范围。Portal overview 增加 `enterprises` 列表，Portal 页面在多企业时提供企业范围选择器并把选择随入站消息提交；浏览器仍不能提交身份字段。
  - 修复二（回复截止时间没有生产方）：方案 §6.3 要求 InboundMessage 携带回复截止时间，但 `ChannelCapabilities.reply_window_seconds` 无消费者、`replyWindowExpiresAt` 无生产者，微信发送器里的窗口校验是死代码。现 `InboundMessageInput` 增加 `reply_window_expires_at`，微信适配器按客服消息窗口从发信时刻推导并落库到 `platform_inbound_message.ReplyWindowExpiresAt`，回复任务载荷携带该截止时间，发送前统一判定并以 `reply_window_expired` 拒绝。
  - 修复三（回复前重新鉴权是条件性的）：`process_platform_reply_task()` 过去只在载荷含 `accountId` 时复核账号/会话/企业/membership/权限，注释说明是为兼容最小单测载荷，等于在生产授权路径里留了测试分支。现身份字段一律必填，校验抽出为 `_reply_authorization_error()`，`platformSessionId` 按渠道可空，单测载荷补齐为完整授权载荷。
  - 修复四（单一发送器无法按渠道路由）：`build_platform_delivery_handlers()` 只接受一个 `reply_sender_factory`，多渠道无法各用自己的发送协议。现支持按 `channel` 或 `channel:instance` 的映射，声明了其它 `channel` 的发送器不会收到本渠道回复，未匹配时仍以 `channel_sender_not_configured` 明确失败而不伪报成功。
  - 修复五（官网异步入站状态接口一直 500）：`WebChannelInboundStatusApi` 使用了未导入的 `PlatformInboundMessage`，`GET /api/v1/channels/web/inbound/<id>` 自 `M2-WORKER-02` 起每次都抛 `NameError`。该接口此前没有任何测试覆盖，Portal 的异步轮询在真实浏览器里必然失败。现补齐导入，并新增两个定向单测覆盖正常读取与「他人消息不可见」的归属校验。
  - 修复六（Portal 390px 横向溢出）：真实浏览器验收时发现「我的会话」面板在 390px 下把文档撑到 465px。`portal-columns` 的 grid 轨道改为 `minmax(0, ...)`，允许列收缩到 min-content 以下。属本轮验收顺带修复的既有响应式缺陷。
  - 验证命令与结果：`server/.venv/bin/pytest test/unit_test -q`（167 passed）；`PLATFORM_TEST_DATABASE_URL=... server/.venv/bin/pytest test/integration -q`（28 passed）；`make platform_api_check`、`npm run type-check`、`npm run build-only` 通过。
  - 真实浏览器验收（2026-09-08，本地 API + Vite + Worker，schema revision 12）：为一个 customer 用户绑定两个有效企业后，登录响应 `enterprise` 为 `null`、`enterprises` 返回两项；Portal 出现企业范围选择器，未选择时输入框与按钮禁用并提示「请先选择本次查询的企业范围」；选择「企业 B」后 `POST /api/v1/channels/web/inbound` 请求体携带该 `enterpriseId` 并返回 201；Worker 处理后 `platform_execution_run` 落在企业 B（旧实现会按名称排序静默选中企业 A），官网执行上下文仍保留 `PlatformSessionId`；状态接口由 500 变为 200。`1280x900` 与 `390x844` 均无横向溢出，刷新后控制台 `0 errors / 0 warnings`。
  - 测试产物：`output/tests/m2-channel-fix-01-enterprise-scope-browser.json`；截图 `output/playwright/m2-channel-fix-01-scope-required-1280.png`、`m2-channel-fix-01-enterprise-scope-1280.png`、`m2-channel-fix-01-enterprise-scope-390.png`。
  - 遗留风险：浏览器验收使用 `M3_USE_MOCK=true`，不代表真实 M3 联调；按渠道路由的发送器目前只有官网与微信服务号两种实现，微信客服/企微仍分别由 `M3-WECHAT-CS-01`、`M3-WECOM-01` 负责；真实渠道发送回执仍未验证。

- [ ] `M2-TEST-FIX-01` 修复测试基座缺陷：路由重复注册与顺序相关的收集失败。
  - 状态：`DONE`（2026-09-08，本地回归）
  - 背景：`server/.venv/bin/pytest test/unit_test` 整目录运行会在收集阶段中断（`Sanic app name "app_factory" already in use.`），此前只能按单文件运行，掩盖了跨模块相互影响。根因是 `util/module.py::autodiscover()` 用 `spec_from_file_location` 把每个 `router/**/*.py` 以合成模块名 `module` 重复执行，任何模块再按 `router.platform` 正常导入就会二次注册路由（`RouteExists`），同时使模块级 `__name__`（logger 名）不正确。
  - 修复：`autodiscover()` 改为按规范点分模块名 `import_module()`，由模块缓存保证同一文件只执行一次；新增 `server/test/app_bootstrap.py::ensure_app()` 作为测试进程内唯一应用入口，各测试模块和 `conftest` 的 `app` fixture 统一改用它。
  - 附带修复：`test_platform_worker_postgres.py` 中 `assert "138" not in request.visitor_id` 是随机失败断言（随机 UUID 十六进制会包含 `138`），改为断言 visitor_id 结构为 `platform:<uuid>:<uuid>`，等价且不再偶发失败。
  - 验证命令与结果：`server/.venv/bin/pytest test/unit_test -q` 由“收集中断”变为 `165 passed`（需本地库先 `python migrate.py upgrade` 到 revision 12）；`PLATFORM_TEST_DATABASE_URL=... server/.venv/bin/pytest test/integration -q` 为 `28 passed`。
  - 边界：与 `.env` 无关的纯本地测试基座修复；不改变生产路由集合，legacy 兼容 API 回归（`test_legacy_route_security_api.py` 等）在迁移后的库上全部通过。

- [ ] `M2-ORCH-01` 串入消息处理、Agent/ADP 执行、M3 查询、证据校验和回复发送。
  - 状态：`IN PROGRESS`（2026-09-06）
  - 验收：模型不能决定身份/权限；关键船名、航次、时间和状态均可映射到本轮证据。
  - 本轮完成（2026-09-06，本地 Worker/Portal 编排）：入站任务在服务端重新校验账号、会话、企业范围和 `shipment.read` 权限；创建并持久化 execution run、入站/assistant 消息、受控 evidence；通过独立 `AgentProvider` 边界执行 Agent 请求；创建 `platform.reply` 任务；官网回复通过 Portal 持久化结果视为已投递；非官网渠道未配置真实发送器时明确失败或标记发送结果不确定，不伪报成功。
  - 代码证据：`server/core/platform_worker.py`、`server/integrations/adp/provider.py`、`server/test/unit_test/test_agent_provider.py`、`server/test/integration/test_platform_worker_postgres.py`、`output/tests/m2-orch-01-worker.json`。
  - Provider 约束：`AgentRequest` 仅由已落库执行上下文提供 `agentId`、`conversationId`、`runId`、`channel`；`AgentProvider` 同时声明能力集合（当前受控实现为 `shipment.lookup`）；Worker 在创建 execution context/tool call 前校验能力和 `execute()` 契约；`AgentResponse` 只允许平台状态、摘要、trace 和白名单 evidence，Provider 原始字段不会进入业务模型或回复任务；旧 `adapter=` 入口保留为兼容包装器。
  - 运行接线：新增 `server/worker.py`、`Makefile run_worker` 和 `LOCAL_RUN.md` 启动说明。默认使用受控 M3 Provider；只有显式 `M3_USE_MOCK=true` 才使用 fixture，未配置真实 M3 时返回持久化 `upstream_error`，不会静默伪造结果。
  - 本轮新增 Provider 边界（2026-09-06，本地定向验证）：`server/integrations/adp/provider.py` 新增服务端映射的 `ADPAgentProvider`，解析 ADP SSE 文本增量、受控 trace/request ID、显式 evidence 白名单和 `error` 事件；未知事件忽略，供应商异常只落类型，不泄露 AppKey/Token。`AgentRequest.visitor_id` 固定为 `platform:<enterprise UUID>:<account UUID>`，不使用姓名、手机号或客户端 `agentId`。`server/worker.py` 仅从服务端 `ADP_AGENT_CONFIGS` 选择 Agent/Application，映射缺失、应用不存在或 Vendor 不支持 `chat` 时 fail closed。
  - 验证命令与结果：`server/.venv/bin/pytest server/test/unit_test/test_agent_provider.py -q`，`6 passed`；`server/.venv/bin/python -m py_compile server/config/tcadp_config.py server/integrations/adp/provider.py server/core/platform_worker.py server/worker.py server/test/unit_test/test_agent_provider.py`、`git diff --check` 通过。Worker PostgreSQL 集成验收仍覆盖 `13 passed`，并新增 VisitorId 格式断言；证据写入 `output/tests/m2-orch-01-adp-provider.json`。
  - 当前仍未满足完成条件：真实 ADP Agent 编排、真实 M3 数据和微信/企微发送协议尚未联调；本地撤权后的旧上下文和待发送任务失效已由 `M2-ACCESS-03` 完成，真实第三方联调仍待外部条件。

- [ ] `M2-M3-02` 使用真实 M3 数据验证订单、提单、箱号、船名、航次、预计/实际船期和未知状态处理。
  - 状态：`BLOCKED`
  - 依赖：`M0-EXT-01`、`M0-EXT-02`、`M0-M3-01`。

## M3：多渠道接入

### 已处理

- [x] `M3-BASE-01` 保留并识别旧 `client/packages/adp-chat-component` 的 ADP 渠道能力；明确其不计入统一渠道适配完成度。
  - 完成证据（2026-09-05）：现有组件目录和方案文档第 6 节边界说明；未作为统一渠道适配计数。

- [x] `M3-FRAMEWORK-01` 建立统一多渠道适配框架：渠道契约、能力声明、适配器注册、标准入站/出站结构化错误和观测边界。
  - 状态：`DONE`（2026-09-06，本地框架实现和契约回归）
  - 范围：以 Web 作为参考适配器；协议验签/解密留在具体微信/企微适配器，身份、企业范围、权限和 Agent 选择留在平台服务。
  - 完成证据：新增 `server/integrations/channels/base.py` 统一 `ChannelAdapter`、`ChannelSender`、能力元数据、入站/出站结构和结构化投递回执；`server/integrations/channels/registry.py` 提供显式注册、重复注册拒绝、显式替换和未知渠道失败关闭；`server/integrations/channels/web.py` 接入 Web 参考适配器；Web 入站路由通过注册表发现适配器。
  - 验证命令与结果：`server/.venv/bin/pytest server/test/unit_test/test_channel_framework.py server/test/unit_test/test_web_channel.py server/test/unit_test/test_delivery.py server/test/unit_test/test_platform_worker_retry.py -q`（`20 passed`）；Python 编译和 `git diff --check` 通过。
  - 遗留风险：本地契约和失败边界已完成；微信服务号、微信客服和企微的验签/解密、发送窗口及真实协议仍由 `M3-WECHAT-*`、`M3-WECOM-01`、`M3-VERIFY-01` 和 `M3-QA-01` 负责，不能以 Web 或 Mock 代替。

- [x] `M3-WEB-E2E-01` 使用 Web 渠道完成浏览器/API -> durable inbound -> Worker -> Agent/M3 provider -> durable reply -> Portal history 的端到端验证。
  - 状态：`DONE`（2026-09-06，本地 PostgreSQL E2E）
  - 验收结果：`server/test/integration/test_web_channel_e2e_postgres.py` 覆盖相同 `messageId` 重试只保留一条入站消息、只生成一轮执行和一条回复任务；Worker 完成受控 M3 Mock 查询，Portal conversation、入站/assistant message、evidence 和回复任务均可恢复。
  - 验证命令与结果：`PLATFORM_TEST_DATABASE_URL='postgresql+asyncpg://adp_chat_client_local@127.0.0.1:5432/adp_chat_client_local' server/.venv/bin/pytest server/test/integration/test_web_channel_e2e_postgres.py -q`（`1 passed`）；测试使用临时 PostgreSQL schema，结束后自动删除，不污染开发数据库。跨账号隔离和撤权后待发送任务失效沿用既有 Worker/Portal PostgreSQL 回归（`15 passed`）。
  - 边界：本地 M3 Mock/受控 Provider 只能证明框架和链路，不代表微信服务号、微信客服或企微真实协议已接通；真实渠道的回调验签/解密、回复窗口和发送失败联调仍待外部条件。

- [x] `M3-WECHAT-OA-01` 实现微信服务号适配器：回调验证、消息标准化、发送窗口和失败降级。
  - 状态：`DONE`（2026-09-07，本地明文与 AES 安全模式协议适配器完成）；依赖 `M0-CHANNEL-01` 的真实联调部分仍保留。
  - 完成证据：`server/integrations/channels/wechat_official_account.py` 支持 GET 明文回显和安全模式 `echostr` 解密、SHA-1 `signature/msg_signature` 常量时间比较、时间窗和进程内重放保护、AES-256-CBC/微信 32 字节填充、解密后 AppID 校验、XML 大小/DTD/实体拒绝、文本和事件标准化、缺失 `MsgId` 的稳定消息 ID、48 小时回复窗口边界和未配置发送传输时的 `uncertain` 回执；`server/router/platform.py` 支持 `encrypt_type=aes` 的 GET/POST，读取结构化 `token/appId/appSecret/encodingAesKey` 凭据，只有已确认渠道身份才入 durable queue。
  - 验证命令与结果：`server/.venv/bin/pytest server/test/unit_test/test_wechat_official_account.py -q`（`10 passed`）；Python 编译和 `git diff --check` 通过。测试覆盖明文回归、加密 GET、加密 POST、错误 AppID、错误签名、填充/长度边界。
  - 遗留风险：真实微信服务号账号、OpenID 样本和身份绑定、真实发送 API、回复窗口、重试/断线/进程重启联调仍未完成；本地实现不能替代 `M0-CHANNEL-01`、`M3-VERIFY-01` 和 `M3-QA-01` 的真实协议验收。

### 未处理 TODO

- [x] `M3-ADMIN-01` 将 Admin“渠道管理”完善为可操作的渠道接入中心。
  - 状态：`DONE`（2026-09-06，本地 Admin 渠道接入中心）
  - 范围：展示 Web、微信服务号、微信客服和企业微信机器人能力状态；接入微信服务号凭据新增/轮换/停用、回调地址和联调说明；接入渠道身份列表与管理员撤销。
  - 完成证据：`client/packages/app/src/components/AdminChannelManagement.vue`、`client/packages/app/src/pages/Admin.vue` 和 `client/packages/app/src/platform/platformService.ts` 完成真实管理 API 接线与交互；`server/router/platform.py`、`docs/api/openapi.yaml` 和生成类型补充内部 `connectionId` 契约；页面明确区分 Web 本地 E2E、服务号凭据配置和第三方真实在线状态。
  - 浏览器验收：Admin 登录后桌面和 `390 x 844` 移动视口均可加载渠道目录、实例和身份；移动端页面与配置弹窗的 `scrollWidth/bodyScrollWidth/innerWidth` 均为 `390/390/390`，无横向溢出，弹窗底部操作可触达，控制台无错误或警告。证据：`output/playwright/admin-channels-desktop.png`、`output/playwright/admin-channels-mobile.png`、`output/playwright/admin-channels-mobile-modal.png`。
  - 验证命令与结果：`python3 script/generate-platform-types.py`、`cd client/packages/app && npm run type-check`、`cd client/packages/app && npm run build-only`、`server/.venv/bin/python -m py_compile server/router/platform.py`、`make platform_api_check` 和 `git diff --check` 均通过。
  - 遗留边界：微信服务号真实账号/回调、AES/EncodingAESKey、真实客服消息发送和多实例持久化重放保护仍未完成；微信客服与企微适配器仍为待接入，不能把本地管理页或凭据保存视为真实渠道已上线。
  - 设计：`docs/plans/2026-09-06-admin-channel-management-design.md`。

- [x] `M3-PLATFORM-SCOPE-01` 将 ADP 应用和渠道实例纠正为平台级配置，移除配置阶段的企业绑定依赖。
  - 状态：`DONE`（2026-09-07）；修正此前 `M3-ADMIN-01` 中“先选择企业应用绑定再创建渠道”的错误范围。
  - 目标：一期只从服务器 `.env` 的 `TC_SECRET_APPID`、`TC_SECRET_ID`、`TC_SECRET_KEY`、`APP_CONFIGS` 读取唯一 ADP 应用；平台管理员创建渠道实例时只配置渠道、实例 ID 和渠道凭据，不选择企业或 ADP 连接。
  - 鉴权边界：第三方消息先由平台级渠道凭据验签和标准化，再解析渠道身份，并校验平台用户、企业访问范围和业务权限，最后由平台转发到唯一 ADP 应用；渠道配置本身不授予任何企业数据权限。
  - 完成证据：`server/model/platform.py`、`server/core/channel_credentials.py`、`server/core/migration.py`、`server/router/platform.py` 将渠道凭据归属改为平台级；revision 10 对重复 `Channel + ChannelInstanceId` 停止迁移并提示人工合并，重建 `ON DELETE SET NULL` 外键；Admin 导航与配置页展示平台唯一 ADP 应用，`docs/api/openapi.yaml` 和生成类型移除新建渠道的企业/连接必填字段并新增脱敏 ADP 状态接口；`server/test/unit_test/test_channel_credentials.py` 覆盖无企业/连接读取、全量密钥完整性、多应用拒绝和密钥不回显。
  - 验收：数据库迁移保留 `IntegrationConnection`、`EnterpriseExternalAccount` 和旧 binding 路由兼容性，但新渠道凭据不依赖企业/连接；Admin、服务端 API、OpenAPI 和生成类型一致；全局实例唯一、无绑定读取和 ADP 配置脱敏状态测试通过。验证结果：`server/.venv/bin/pytest server/test/unit_test/test_wechat_official_account.py server/test/unit_test/test_channel_credentials.py server/test/unit_test/test_platform_migration.py -q`（23 passed）、`npm run type-check`、`npm run build-only`、OpenAPI 校验、生成类型 `--check`、Python 编译和 `git diff --check` 均通过。

- [x] `M3-WECHAT-OA-02` 实现微信服务号客服消息出站发送：access_token 管理、发送分类与失败语义。
  - 状态：`DONE`（2026-09-08，本地实现与定向回归）；真实服务号发送回执仍由 `M0-CHANNEL-01`、`M3-QA-01` 阻塞。
  - 背景：`M3-WECHAT-OA-01` 只完成入站协议，发送器一律返回 `provider_transport_not_configured`，因此非官网渠道的回复任务必然以 `channel_sender_not_configured` 失败。这正是 `docs/plans/2026-09-08-channel-adapter-reference-research.md` §4 核实的「真实主动发送整条链路为空」缺口。
  - 完成证据：新增 `server/integrations/channels/wechat_transport.py`，用 `/cgi-bin/stable_token` 取 access_token，`expires_in-300s` 提前刷新、按 appId 加锁避免并发重复获取；`/cgi-bin/message/custom/send` 发送文本，超长截断并提示回官网查看。新增 `server/integrations/channels/sender_registry.py::ChannelSenderResolver`，按渠道实例惰性从加密凭据构造发送器并缓存；凭据缺失或只有回调凭据（无 AppSecret）时返回无传输的发送器，让回复标记 `uncertain` 而不是伪报成功；`server/worker.py` 默认接线该 resolver，`_resolve_channel_sender` 通过显式 `is_channel_sender_resolver` 标记识别并 await 它（不用鸭子类型，避免 mock 被误认）。
  - 失败语义（本项核心）：区分「未发出」「结果未知」「永久拒绝」。连接失败/DNS/token 获取失败为 `retryable`（未发出，重试不会重复）；请求已写出但无回执（读超时、响应截断、无法解析的 errcode）为 `uncertain`，既不自动重试也不报成功，避免用户已收到却重复发送；`45015` 超窗、`48001`/`50001` 无客服消息权限、`40003` 非法 openid 为永久拒绝；`-1`/`45009`/`45011`/`48004` 限频为 `retryable`；`40001`/`40014`/`42001`/`42007` token 失效只重试一次，两次拒绝都清除缓存 token；未识别 errcode 按永久处理以免队列空转。发送前校验回复窗口与收件人：收件人只从 `externalConversationId` 的 `<实例>:<openid>` 还原，跨实例会话键一律拒绝，浏览器与模型都无法影响收件人。
  - 与 `M3-REFACTOR-01` 计划的一处偏离（有意）：调研结论要求 token 缓存用「共享存储+锁，禁进程内 Map」。该要求针对会作废旧 token 的 `/cgi-bin/token`；本实现改用 `/cgi-bin/stable_token`，该端点对并发调用返回同一 token 且不作废旧 token，因此进程内缓存不会让多 Worker 互相顶掉，无需新增共享存储。此耦合已写进模块 docstring：若日后改回 `/cgi-bin/token`，必须先把缓存迁到共享存储。`WechatAccessTokenCache` 已按 appId 泛化，`M3-REFACTOR-01` 可直接搬进 `channels/_wechat/token.py` 供客服/企微复用。
  - 验证命令与结果：`server/.venv/bin/pytest test/unit_test/test_wechat_transport.py -q`（`27 passed`）覆盖凭据校验、内容截断、成功/永久/限频/token/未映射错误码分类、连接失败为 retryable、写出后超时为 uncertain、5xx 为 retryable、token 缓存复用与过期刷新、并发只取一次、无传输保持 uncertain、跨实例收件人拒绝、超窗拒绝；全量 `pytest test/unit_test -q`（`194 passed`）、`pytest test/integration -q`（`28 passed`）。
  - 遗留风险：所有发送路径均由本地伪造 HTTP 响应验证，未经真实微信 API 回执确认；客服消息要求认证服务号，部分账号还需把服务器出口 IP 加入白名单；`stable_token` 的真实配额与限频表现待联调观察。
  - 真实联调进展（2026-09-08→09，认证服务号 + 安全模式，生产 `adp.xdimspace.cn`）：这是首个接入的真实渠道账号，`M0-CHANNEL-01`/`M3-QA-01` 的「至少一个可用渠道账号」前置已满足（其余真实渠道仍缺）。真实微信端到端验证：服务器配置 URL 验证（明文 GET）通过；入站 AES 安全模式验签+解密+身份解析（绑定后 `processed`）；出站客服消息真实投递成功（`platform.reply` succeeded，`stable_token`+`custom/send` 真实调通）。修复两个真实环境暴露的缺陷：(a) errcode `40164` IP 不在白名单——需将服务器出口 IP 加入公众号 IP 白名单；(b) UTF-8 编码——aiohttp `json=` 默认 `ensure_ascii=True` 使中文投递为 `\uXXXX` 字面量，改为 `ensure_ascii=False`+UTF-8 bytes+`charset=utf-8` header，由真实投递验证。

- [x] `M2-ADP-ROUTE-01` Worker 默认路由到平台唯一 ADP 应用，业务网关不以 M3 配置为前置。
  - 状态：`DONE`（2026-09-08，本地实现 + 生产验证消息到达 ADP）
  - 背景：`worker.py::build_agent_provider` 原逻辑为 `ADP_AGENT_CONFIGS` 为空即回落本地 M3 provider、绕过 ADP。生产未配 `ADP_AGENT_CONFIGS`，每条消息去查 M3 配置、查不到即 `upstream_error`（客户收到「业务系统暂时不可用」）。与方案 §6.2「校验通过后才转发给一期全平台唯一的 ADP 应用，其运行配置由 `APP_CONFIGS` 提供」不符——M3 是否接入 ADP agent 属 agent 侧工具配置、不确定，不能作为消息到达 ADP 的前置。
  - 修复：优先级改为 ① `ADP_AGENT_CONFIGS` 显式映射（行为不变）；② `APP_CONFIGS` 恰好一项 → 平台唯一 ADP 应用（与 API `_adp_config_status()` 同口径）；③ 仅当 `M3_USE_MOCK`/`M3_BASE_URL` 刻意配置才用本地 M3 provider（开发）；④ 全空 → 无 vendor 的 ADP provider，消息诚实报 upstream error 并 ERROR 日志，不用本地替身冒充生产。多 `APP_CONFIGS` 无显式映射时 fail closed。
  - 验证：`test_worker_agent_routing.py`（8 passed，含「缺 M3 不阻断到达 ADP」回归主项）、全量 204 passed。生产：修复后真实微信消息成功到达 ADP 并返回回答（此前恒 upstream_error）。
  - 遗留风险：生产 `DescribeApp` 元信息接口仍报 `450006-用户未登录或者未注册`；`chat` 走通说明其授权有效，但二者共用 `TC_SECRET_*`，元信息接口授权需腾讯云侧确认。

- [ ] `M3-WECHAT-OA-03` 对齐 ADP 原生对话体感：ACK + 流式输出 + Markdown 适配 + 图文卡片。
  - 状态：`IN PROGRESS`（2026-09-09，本地实现与回归完成、已部署；真实微信流式/卡片体感待用户验收）
  - 背景：核实 `vendor/tcadp/tcadp.py::chat` 为真 SSE 流（`Stream: enable`+`Incremental: true`，逐行 `readline` 逐事件 `yield`，vendor 零攒批），流被 `ADPAgentProvider` 累积收敛成一次性全文。目标对齐 ADP 原生：先 ACK 再流式。
  - 完成证据：`ADPAgentProvider.execute` 新增可选 `sink`，边收 `text.delta` 边转发；`_execute_provider` 按签名探测，旧 `execute(request)` provider 不受影响。新增 `stream_sink.py::ChannelStreamSink`（句末/段落分块、每块独立幂等键 `platform-stream:<inbound>:<seq>`、失败即停不中断 run、上限 12 块下限 60 字防 `45009`）与 `text_format.py`（markdown→纯文本，emoji/换行保留；`split_at_boundary` 供切分）。回调 5 秒内返回被动 ACK「已收到，正在为你查询…」（加密模式同样加密）。`wechat_transport.send_news`+`send_result_card` 追发 `msgtype=news` 图文卡片（标题+摘要+回 Portal 链接，需 `PLATFORM_PUBLIC_BASE_URL`，未配置则跳过）。回复任务见 `streamedChunks>0` 不重发正文、只补卡片。
  - 有意的范围变更（安全）：按用户明确指示「鉴权通过后直接转发 ADP 流式给客户端」，流式文本不再经发送前证据白名单校验，`allowlisted_evidence()` 移到流结束后运行（Portal 侧仍保留完整校验记录与证据）。偏离方案「关键业务结论校验后返回」。前置权限校验（execution context + tool claim）仍在流开始前完成。若模型流出不实业务结论需重新评估。
  - 验证：`test_text_format.py`（17）、`test_stream_sink.py`（13，含幂等/断点续发/失败不中断/限流/向后兼容）、`test_wechat_transport.py`（31，含卡片与 UTF-8）；全量 237 passed、集成 28 passed。
  - 待验收（真实微信）：ACK 秒回、答案分条流入、结尾图文卡片、中文/emoji 正常、markdown 清理；worker 日志核对分块数/卡片投递/`45009`。分块节奏（`min_chars`/`max_chunks`）可调。

- [ ] `M3-WECHAT-CS-01` 实现微信客服适配器：通知接收、同步游标、消息去重和客服回复协议。
  - 状态：`TODO`；依赖 `M0-CHANNEL-01`；建议以 `M3-REFACTOR-01` 为前置。
  - 参考实现：openclaw-china `extensions/wecom-kf/src/webhook.ts` 的 cursor 拉取（先 ack、投递前存 `next_cursor`、首启 drain）；会话作用域抄 LangBot `get_launcher_id` 但做成真 ABC 方法，键用 `open_kfid|external_userid`；反例（勿抄）AstrBot/LangBot 客服 `while has_more` 只取 `[-1]` 丢批。详见 `docs/plans/2026-09-08-channel-adapter-reference-research.md` §5。
- [ ] `M3-WECOM-01` 实现企业微信智能机器人适配器，选择并实现长连接或 HTTPS 回调模式。
  - 状态：`TODO`；依赖 `M0-CHANNEL-01`；建议以 `M3-REFACTOR-01` 为前置。
  - 参考实现：AstrBot 内置腾讯官方 JSON 加解密 `wecom_ai_bot/WXBizJsonMsgCrypt.py`（wechatpy 不覆盖机器人 JSON 信封）；双模式抄 AstrBot「单适配器双模式」；反例（勿抄）LangBot `wecombot` 关掉 CorpID 校验。详见 `docs/plans/2026-09-08-channel-adapter-reference-research.md` §5。
- [ ] `M3-REFACTOR-01` 将渠道适配层提升为一等包并结构化：契约中性化、按渠道拆目录、统一 WeChat crypto、抽 `core/channel_ingress` 编排 seam。
  - 状态：`TODO`；作为 `M3-WECHAT-CS-01` 和 `M3-WECOM-01` 的结构前置。
  - 范围：`server/channels/`（从 `integrations/channels/` 提升）；`channels/contracts.py` 收敛 `InboundMessageInput/OutboundMessage/DeliveryReceipt/ChannelCapabilities` 使 core 依赖契约而非反向；`channels/_wechat/{crypto,crypto_json,token,text}.py` 供公众号/客服/企微复用；`ChannelAdapter.normalize` 收成带类型签名并新增 `get_launcher_id` 会话键钩子；把「验签→normalize→replay→身份→入队」从 2266 行的 `router/platform.py` 抽到 `core/channel_ingress.py`（鉴权仍留平台服务侧，不进渠道包）。
  - 验收：适配器仍不触碰 DB/models/identity/credentials/replay；渠道包依赖仅指向 `contracts`；每文件 <400 行、crypto 单份；现有 `M3-FRAMEWORK-01`/`M3-WECHAT-OA-01` 测试全绿且行为不变。
  - 依据：`docs/plans/2026-09-08-channel-adapter-reference-research.md` §6。
- [x] `M3-CRED-01` 实现渠道凭据加密存储、轮换、最小权限读取和脱敏展示。
  - 状态：`DONE`（2026-09-06，本地实现和专项回归）
  - 完成证据：新增 `platform_channel_credential` 表和 revision 8；`server/core/channel_credentials.py` 使用 Fernet 认证加密、当前密钥写入、旧密钥只读轮换、指纹校验和缺失/非法密钥 fail closed；`GET/POST /api/v1/admin/channel-credentials`、`POST .../<id>/rotate`、`POST .../<id>/disable` 均要求 `platform.manage`，响应只返回掩码和元数据；新平台路径只校验渠道实例唯一性，旧企业/连接字段和 binding 表仅保留兼容序列化与 legacy 路由；创建/轮换/停用写入不含凭据内容的审计事件。
  - 验证命令与结果：`server/.venv/bin/pytest server/test/unit_test/test_channel_credentials.py -q`，`7 passed`；`server/.venv/bin/python -m py_compile server/core/channel_credentials.py server/router/platform.py`、`git diff --check` 通过。
  - 测试产物：`output/tests/m3-cred-01-channel-credentials.json`。
  - 边界：本地完成加密存储和管理边界；真实微信/企微凭据、渠道验签协议和第三方联调仍由 `M3-VERIFY-01`、`M3-QA-01` 负责，不能以本地测试代替。
- [ ] `M3-VERIFY-01` 实现各渠道验签、解密、时间窗和重放保护。
  - 状态：`IN PROGRESS`（2026-09-08；微信服务号明文/AES 本地协议与跨实例重放保护已覆盖，其它渠道和真实样本仍待接入）；依赖各渠道真实协议样本。
  - 本轮补充：重放保护从进程内缓存改为数据库标记。`server/core/channel_replay.py` 以 `(Channel, ChannelInstanceId, ReplayKey)` 唯一约束拒绝已接受过的签名，适配器内的进程内缓存降级为快速路径；`platform_channel_replay_marker` 表由 revision 12 建立，过期行按批清理，拒绝行为由唯一约束而非清理进度决定。
  - 验证：`server/.venv/bin/pytest test/unit_test/test_channel_replay.py -q`（5 passed）覆盖首次记录、重放拒绝、并发写入竞争失败、非法窗口/标识 fail closed 和有界清理。
  - 遗留：仍未覆盖微信客服与企微的真实协议样本；`M1` 表格中记录的登录限流存储仍为进程内 `MemoryStorage`，与本项无关但同属多实例待办。
- [ ] `M3-IDENTITY-01` 实现渠道身份绑定、确认、解绑、过期和停用后的即时撤销。
  - 状态：`IN PROGRESS`（2026-09-08，平台用户级身份作用域纠偏 + 渠道执行授权纠偏）。
  - 历史实现（2026-09-06）：新增 `PlatformChannelIdentity` 表和 migration revision 9；已完成一次性 state、确认、解绑、账号停用撤销、内部确认 API 和审计脱敏，并通过当时的定向测试。
  - 已纠正偏差一（企业作用域）：历史模型把渠道身份固定关联企业。现新身份不写入企业，历史 `EnterpriseId` 由 revision 11 清空并改为 nullable `SET NULL`；账号停用仍撤销身份，企业停用或 membership 变化只影响执行授权。
  - 已纠正偏差二（渠道执行依赖浏览器登录态）：Worker 过去对每条入站消息都要求有效 `PlatformAuthSession`，缺少时还会回退取该账号“最新活跃 web 会话”，导致已绑定但未登录官网的微信用户消息一律失败，也让渠道消息借用了无关的浏览器会话。现改为：`platform_execution_context.PlatformSessionId` 可空（revision 12），浏览器消息继续绑定其登录会话并随之失效，渠道消息改由“已确认渠道身份 + 执行时 membership/权限版本”授权；账号级 `revoke_account_execution_contexts` 仍同时作废两者。`server/core/platform_worker.py` 删除会话回退，`server/core/platform.py` 的 `load_execution_context` 只在上下文本身带会话时校验会话。
  - 已纠正偏差三（绑定闭环缺入口）：绑定起点过去要求浏览器先提供 `externalIdentityId`，而客户看不到自己的 OpenID；微信回调对未绑定发送者直接返回 403，绑定口令没有任何拦截入口，方案 §7.2 的两条路径都无法走通。现 `externalIdentityId` 可省略，由可信适配器在确认时写入（`ExternalIdentityId` 改为 nullable）；微信回调在识别到 `pci_` 形态的一次性绑定码时交给身份流程消费，不落库为消息内容、不转发 ADP，并按结果回复被动文本。
  - 已纠正偏差四（活跃身份唯一性只在应用层）：revision 12 在 `Status='active'` 上建立 `(Channel, ChannelInstanceId, ExternalIdentityId)` 部分唯一索引，并在确认路径捕获唯一冲突 fail closed；`resolve_active_channel_identity` 对历史重复行返回空而不是抛错拖垮整条渠道；迁移遇到已存在的重复活跃绑定会停止并要求人工撤销。
  - 已纠正偏差五（未绑定发送者的 ack 语义）：微信对非 2xx 回调会重试并向用户显示“该公众号暂时无法提供服务”。现未绑定发送者收到 200 + 被动引导回复（提示登录官网绑定或联系销售/客服），加密模式下回复同样加密，回复内容拒绝 `]]>` 与控制字符以免伪造 XML 结构；拒绝事件写入脱敏审计。
  - 验证命令与结果：`server/.venv/bin/pytest test/unit_test -q`（165 passed，需先 `python migrate.py upgrade` 使本地库到 revision 12）；`PLATFORM_TEST_DATABASE_URL=... server/.venv/bin/pytest test/integration -q`（28 passed，隔离 schema）；`make platform_api_check` 通过（41 个公开操作、50 个 schema，生成类型已同步）；`cd client/packages/app && npm run type-check`、`npm run build-only` 通过。
  - 测试产物：`output/tests/m3-identity-01-platform-user-scope.json`、`m3-identity-01-platform-scope-migration.json`、`m3-identity-01-worker-single-membership.json`、`m3-identity-01-channel-sessionless-execution.json`。
  - 已验证（2026-09-08 真实浏览器）：企业范围选择器与官网异步查询链路已在 `1280x900`、`390x844` 完成验收，见 `M2-CHANNEL-FIX-01`。
  - 绑定页补齐并真实验收（2026-09-08→09）：此前 Portal「账号与绑定」为写死占位、客户侧绑定 UI 从未实现。补齐 `platformService` 的 `startChannelIdentityBinding/listMyChannelIdentities/revokeMyChannelIdentity` 与 Portal 真实 UI（获取绑定码/绑定码展示/已绑定列表/解绑）；`channelInstanceId` 改可选，新增 `core/channel_credentials.list_active_channel_instances`（只查实例 ID 不解密）由服务端解析、恰好一实例才自动选中、多实例 fail closed。真实微信已完成一次端到端绑定：`pci_` 码经公众号发送 → `channel.identity.confirm/success`、身份 `active`、`ExternalIdentityId` 由适配器写入、`EnterpriseId` 为 NULL、`StateHash` 已烧毁。
  - 遗留风险：本地测试只能证明平台状态机、权限边界和迁移行为；微信服务号、微信客服、企业微信的真实回调验签/解密、渠道发送协议、OAuth/身份样本和第三方联调仍由 `M0-CHANNEL-01`、`M3-VERIFY-01`、`M3-QA-01` 阻塞，不能以本地 API 或 Mock 代替。被动引导回复已按协议构造并可自解密验证，但未经真实服务号回执确认。
- [ ] `M3-QA-01` 完成重复消息、断线重连、进程重启、回复窗口、超时和发送失败的真实联调记录。
  - 状态：`BLOCKED`；依赖至少一个可用渠道账号和 `M2-WORKER-01`。
  - 参考实现：access token 管理抄 openclaw-china `token.ts`（`expires_in-300s`、退避、errcode 集），并补 TTL/共享锁/`40001`（多 worker 禁进程内 Map）；公众号 5s 竞速→客服消息兜底抄 AstrBot MsgId 区分重试/新问 + `asyncio.shield`，deadline 在解密后起算，勿抄 openclaw 正则抠 XML 与 LangBot `passive` 载体模式。详见 `docs/plans/2026-09-08-channel-adapter-reference-research.md` §5。

## M4：试运行与交付

### 已处理

- [x] `M4-API-01` 生成并维护 OpenAPI 文档及前端类型，减少手工维护接口结构。
  - 状态：`DONE`（2026-09-06，本地公共 API 契约链路）
  - 完成证据：`docs/api/openapi.yaml` 定义浏览器侧 `/api/v1` 公开接口并排除 `/api/internal/*`；`script/validate-platform-openapi.py` 校验 YAML、`$ref`、操作元数据和 Sanic 路由漂移；`script/generate-platform-types.py` 生成 `client/packages/app/src/platform/generated.ts`，`client/packages/app/src/platform/types.ts` 统一 re-export 生成类型；`docs/api/README.md` 和 `Makefile` 提供维护入口。
  - 验证命令与结果：`make platform_api_check` 通过（34 个公开操作、47 个 schema，生成文件无过期）；覆盖新增 `GET/POST /api/v1/admin/channel-credentials`、`POST .../{credential_id}/rotate`、`POST .../{credential_id}/disable`；`cd client/packages/app && npm run type-check` 通过；`npm run build-only` 通过，仅保留既有大 chunk warning；`git diff --check` 通过。
  - 遗留风险：该契约覆盖公共浏览器 API，不代表真实 ADP、M3、微信或企微协议已联调；内部 `/api/internal/*` 仍是服务间契约，需随真实 ADP 验证单独维护。

### 未处理 TODO

- [x] `M4-DEPLOY-01` 提供 Docker/Docker Compose 生产化部署、环境变量模板和健康检查。
  - 状态：`DONE`（2026-09-06，本地可复现部署基线）。
  - 完成证据：`docker-compose.yml` 编排 PostgreSQL、一次性迁移、API、Worker 和反向代理；`docker/.env.example` 提供不含凭据的环境变量模板；`docker/Dockerfile` 改为直接启动 Sanic，不再要求容器内存在可写 `.env`；`server/router/health.py` 提供不依赖上游的 `/healthz` 和校验数据库迁移 revision 的 `/readyz`，健康路由不创建请求 session、不触发 ADP 元信息刷新且不受应用限流影响；`docs/operations/release-and-rollback.md` 补充运行命令和公网边界。
  - 验证命令与结果：`docker compose --env-file docker/.env.example config` 通过；`server/.venv/bin/python -m py_compile server/router/health.py server/middleware/application.py server/middleware/database.py server/middleware/limit.py` 通过；`git diff --check` 通过。未宣称真实生产部署、备份恢复或 HTTPS 验收完成。
  - 服务器部署记录（2026-09-07）：提交 `de508a582220f5332e6c06944f6da597ee53e1b8` 已同步至 `/opt/tencent-adp-gateway`；Compose 项目 `tencent-adp-gateway` 的 PostgreSQL、迁移、API、Worker 和反向代理均已启动；`/healthz` 与 `/readyz` 均返回 200，schema revision 为 9。服务器 host Nginx 已增加 `adp.xdimspace.cn` 独立反向代理配置。HTTPS 证书申请因 DNS 当前解析到 `43.174.225.201`（本服务器为另一地址）未通过，待将 A 记录指向本服务器后重试；当前不能宣称公网 HTTPS 已验收。Sellclip PostgreSQL/Redis 容器已停止但未删除，数据卷保留。
  - 502 修复记录（2026-09-07）：Certbot 失败后 HTTPS 请求落入 Sellclip 默认虚拟主机；已补充 `adp.xdimspace.cn:443` 独立虚拟主机并反代至 `127.0.0.1:18080`。`curl -k --resolve adp.xdimspace.cn:443:127.0.0.1 https://adp.xdimspace.cn/healthz` 返回 200；公网请求现返回 ADP 响应。当前证书仍暂复用 Sellclip 证书，DNS 指向确认后必须申请 adp 专用证书。
  - 静态页面修复记录（2026-09-07）：首次部署镜像未包含 `server/static`，导致 `/static/app/index` 返回 `FileNotFound`；已将前端静态产物纳入服务器镜像并重建 API/Worker。当前 `/static/app/index` 和 `/healthz` 均返回 200。HTTPS 证书域名匹配仍待 DNS/ACME 验证条件满足。
- [x] `M4-DOC-01` 编写数据字典、运维手册和错误排查手册。
  - 状态：`DONE`（2026-09-06，本地交付文档）
  - 完成证据：`docs/operations/platform-data-dictionary.md` 描述平台核心表、关键字段、关联关系、敏感数据边界和迁移 revision `1..9`；`docs/operations/troubleshooting.md` 覆盖迁移阻断、登录/锁定/权限、M3 返回状态、Worker 租约/重试、撤权、未知发送结果和 ADP 元信息降级；`docs/operations/release-and-rollback.md` 提供发布前检查、备份、迁移、启动、应用回滚和数据库回滚边界。
  - 验证命令与结果：`git diff --check` 通过；文档中的模型和迁移版本已与 `server/model/platform.py`、`server/core/migration.py` 逐项核对；`make platform_api_check`、前端 `npm run type-check` 和 `npm run build-only` 仍保持通过。
  - 遗留风险：文档覆盖的是当前本地实现和受控部署流程；真实生产部署、备份恢复、RPO/RTO、外部 ADP/M3/微信/企微协议仍需对应权限、资料和演练，不能用本地文档或 Mock 结果替代。
- [ ] `M4-DR-01` 配置备份、异地/独立介质保存，并完成恢复演练，记录 RPO/RTO。
  - 状态：`IN PROGRESS`（2026-09-06）
  - 本轮处理（2026-09-06，本地可复现演练）：新增 `script/postgres-backup-drill.sh` 和 `docs/operations/backup-and-recovery-drill.md`。脚本在隔离 scratch schema 中生成 custom-format dump，复制到单独目录，删除后恢复并校验标记行、SHA-256 和恢复耗时；最近一次结果为 `1 -> 1` 行、SHA-256 一致、恢复耗时 `335ms`；证据写入 `output/tests/m4-dr-01/evidence.json`。
  - 尚未完成：当前副本仍在本机文件系统，不是异地/独立介质；`rpoObservedSeconds` 未伪造为 0，生产备份频率、真实恢复演练和 RPO/RTO 仍待部署权限、备份介质和生产样本。
- [x] `M4-PERF-01` 完成至少 20 个并发查询执行测试、容量记录和瓶颈结论。
  - 状态：`DONE`（2026-09-06，本地基线）
  - 完成证据：隔离 PostgreSQL schema 中创建 20 个独立企业、用户和入站任务，同时启动 20 个 `DeliveryWorker.run_once()`，20/20 成功并创建 20 个待发送回复任务；测试使用 M3 Mock，最后一次记录总耗时 `178.18ms`、吞吐 `112.25 qps`、平均耗时 `116.31ms`、p95 `170.09ms`。
  - 验证命令与结果：`PLATFORM_TEST_DATABASE_URL='postgresql+asyncpg://adp_chat_client_local@127.0.0.1:5432/adp_chat_client_local' server/.venv/bin/pytest server/test/integration/test_platform_worker_postgres.py::test_worker_handles_twenty_concurrent_queries_baseline -q -s`（`1 passed`）；结果保存于 `output/tests/m4-perf-01.json`。
  - 边界与瓶颈结论：该结果是本地 PostgreSQL 四连接池（`pool_size=4`、`max_overflow=0`）+ M3 Mock 的基线，不能外推生产容量或真实 M3 性能；生产仍需验证数据库连接池/锁竞争、真实 M3 延迟与限流、Worker 进程数和队列租约吞吐。
- [x] `M4-SEC-01` 完成日志、密钥、口令脱敏专项回归和权限回归测试。
  - 状态：`DONE`（2026-09-06，本地专项回归）。
  - 完成证据：新增 `server/util/security_logging.py`，统一处理嵌套凭据、Bearer/Authorization、口令、临时密钥、JSON 错误文本和签名 URL；腾讯云请求、ADP 转发、聊天参数、启动配置、异常、文件下载和客户签名日志均改为脱敏或摘要输出。新增 `server/test/unit_test/test_security_logging.py`，覆盖实际 `tc_request`/`TCADP.forward_request` 日志路径及普通业务字段保留。
  - 验证命令与结果（分进程执行，避免 Sanic app registry 冲突）：`server/.venv/bin/pytest test/unit_test/test_security_logging.py -q`（5 passed，1 个既有 datetime 弃用告警）；`server/.venv/bin/pytest test/unit_test/test_platform_auth_security.py -q`（7 passed）；`server/.venv/bin/pytest test/unit_test/test_platform_config.py -q`（27 passed）；`server/.venv/bin/pytest test/unit_test/test_platform_ops_status.py -q`（5 passed）。合计 `44 passed`。输出保存在 `output/tests/m4-sec-01-security-logging.txt`、`output/tests/m4-sec-01-auth-security.txt`、`output/tests/m4-sec-01-platform-config.txt` 和 `output/tests/m4-sec-01-ops-status.txt`；已扫描测试日志，未发现夹具中的敏感值。
  - 验证边界：本地日志脱敏、管理权限拒绝、配置发布/回滚和运维诊断脱敏已回归；真实生产日志管道、密钥管理服务、M3/ADP/微信/企微第三方联调仍需外部条件，不能以本地测试替代。
- [ ] `M4-RELEASE-01` 完成版本发布、回滚和数据库迁移演练。
  - 状态：`IN PROGRESS`（2026-09-06）
  - 本轮处理（2026-09-06）：补充 `docs/operations/release-and-rollback.md`，明确发布前备份、迁移、Web/Worker 启动顺序、健康检查、应用回滚与数据库回滚边界；新增 `script/release-drill.sh` 与 `make release_drill`，一次性收集 Compose 配置、迁移 CLI 和隔离数据库发布演练证据；同步 `LOCAL_RUN.md`、方案文档和数据字典到当前 revision 9。
  - 当前已具备：版本化迁移 CLI、重复升级保护、迁移审计、显式数据丢失确认和本地隔离 schema 的升级/回滚/再升级演练（revision `1..9`）；定向 PostgreSQL 集成演练于 2026-09-06 通过（`1 passed in 0.96s`），证据为 `output/tests/m1-mig-01-migration.json`；当前代码目标为 revision `9`，本地已应用渠道身份表，生产演练仍待发布环境。
  - 本轮新增证据：`PLATFORM_TEST_DATABASE_URL='postgresql+asyncpg://adp_chat_client_local@127.0.0.1:5432/adp_chat_client_local' make release_drill`；结果写入 `output/tests/m4-release-01/evidence.json`，明确记录本地隔离 schema、`developmentSchemaTouched=false` 和 `productionStatus=not_executed`。
  - 尚未完成：生产部署账号、真实备份介质、恢复演练和可审计的 RPO/RTO 记录；这些需要部署环境权限，不能用本地 PostgreSQL 测试替代。
- [x] `M4-ENABLE-01` 编写账号开通 SOP、验收用例和培训材料。
  - 状态：`DONE`（2026-09-06，本地交付材料）。
  - 完成证据：`docs/operations/account-onboarding-and-acceptance.md` 覆盖开通前资料核对、企业与 M3 映射、最小权限角色、一次性 6 位口令安全交付、首次登录改密、停用/重置/范围变更、14 项验收用例、客服/管理员/企业用户/运维培训要点和交付记录模板。
  - 验收边界：`git diff --check` 通过；文档已与 `server/core/platform.py` 的随机初始口令、哈希保存、失败锁定/限流和 `client/packages/app/src/pages/Admin.vue` 的企业/用户/范围操作对齐。真实 M3、ADP、微信/企微和生产交付仍需外部账号、权限、协议、数据和演练，不能以本地材料替代。
- [x] `M4-OPS-01` 提供运维机器人只读状态入口，包含脱敏错误和受控排障建议。
  - 状态：`DONE`（2026-09-06，本地只读诊断入口）。
  - 完成证据：`server/router/platform.py` 新增 `GET /api/v1/ops/status`，要求 `platform.diagnose`；聚合迁移 revision、投递/执行状态计数、最近失败固定分类、ADP 元信息健康计数，并生成固定 code/message 排障建议；数据库异常仅返回异常类型和 `ops_query_failed`，不返回载荷、正文、证据、凭据或 `LastError` 原文。`docs/operations/troubleshooting.md` 已补充调用和脱敏边界。
  - 验证命令与结果：`cd server && .venv/bin/pytest test/unit_test/test_platform_ops_status.py -q`（5 项聚焦测试）；`.venv/bin/python -m py_compile router/platform.py test/unit_test/test_platform_ops_status.py`；`git diff --check`。
  - 遗留风险：当前是后端只读入口，尚未接入生产运维机器人、告警系统和真实监控数据；真实 ADP/M3/微信/企微联调仍不在本项完成范围。

## 每个 TODO 的完成标准

一个 TODO 只有同时满足以下条件才可以从 `TODO`/`IN PROGRESS` 改为 `DONE`：

1. 实现或文档已经写入对应文件，并注明必要的接口/数据契约。
2. 相关测试、浏览器验收或第三方联调记录已执行；命令和结果可复现。
3. 安全、权限、错误处理和审计要求已经覆盖，或明确记录为后续 TODO。
4. 本文件在同一变更中更新：状态、日期、证据、遗留问题和依赖都同步。
5. 若依赖真实第三方条件，必须写成 `BLOCKED`，不能用 Mock 结果替代。

## 下一批建议

1. `M4-RELEASE-01`：获得生产部署权限后执行真实备份恢复和 RPO/RTO 演练，完成发布验收。
2. 在获得 M3/渠道资料后，分别解锁 `M0-EXT-*`、`M0-CHANNEL-01`，再推进真实 M3、ADP Agent 和微信/企微端到端联调。
3. 将运维状态入口接入生产机器人和告警系统时，补充对应联调记录；生产压测需在真实部署拓扑和 M3 权限就绪后重新执行。
