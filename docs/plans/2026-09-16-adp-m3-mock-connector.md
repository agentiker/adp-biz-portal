# ADP 连接器与 M3 Mock 联调

对应 ROADMAP：`M2-ORCH-MOCK-01`、`M2-ORCH-01`、`M4-ADP-CFG-01`、`M4-ADP-KEY-01`。初始采用 HTTP 连接器；现补充远程 MCP，二者复用平台工具执行链。以下为本地已实现契约，ADP 云端导入及隐藏参数映射仍待真实验证。

## 运行配置

业务 Worker 和企微 Bot 只从数据库选择 ADP 应用：企业显式绑定 → 启用的平台默认应用。显式绑定已停用或不可用时拒绝执行；缺少可用应用时也拒绝执行，不回退到 `.env` 或本地 M3 Agent。

1. 数据库迁移至 revision 19，在 API、Worker、企微网关使用相同的 `PLATFORM_CHANNEL_CREDENTIAL_KEY`。此密钥用于解密数据库中的应用及渠道凭据，必须持久保存。
2. 管理后台「ADP 应用配置」录入 ApplicationId、AppKey、TC SecretAppId、SecretId、SecretKey，按实际云环境设置 Vendor/ServiceVendor，启用并设为默认；如有多个应用，在企业配置中明确绑定。
3. 在隔离联调环境设置 `M3_USE_MOCK=true`；在管理后台「开放接口」通过「新建 API Key」填写名称创建 Key，再点击复制配置到连接器。创建专用测试企业，CustomerCode 分别为 `MOCK-ENT-A`、`MOCK-ENT-B`，创建/绑定测试用户。不修改已有客户企业编码。
4. API、Worker/网关必须连接同一平台数据库。工具 HTTPS 域名必须可从 ADP 云端访问。
5. `APP_CONFIGS=[]` 可保持为空；该配置只供旧管理员调试入口使用。数据库、服务鉴权、加密、渠道等基础设施配置仍在环境变量中。本次未修改远程服务器 `.env`。

## 导入和参数映射

导入 [adp-tools.openapi.yaml](../api/adp-tools.openapi.yaml)，把占位服务器 `https://portal.example.com` 替换为联调环境域名。三个操作分别为：

| operationId | POST 路径 | 返回内容 |
|---|---|---|
| shipmentLookup | `/api/internal/adp/tools/shipment/lookup` | 订单、提单、箱号、船期、节点七个字段 |
| shipmentSchedule | `/api/internal/adp/tools/shipment/schedule` | 船名/航次、预计抵港 |
| shipmentMilestones | `/api/internal/adp/tools/shipment/milestones` | 当前节点、实际抵港 |

Provider 通过 ADP `CustomVariables` 注入以下变量。必须使用连接器固定映射/隐藏参数，不能让模型生成或覆盖身份字段；若云端模式无法做到，真实验收继续阻塞，不能改为信任模型传入的用户或企业 ID。

| 请求位置 | 来源 |
|---|---|
| Header `X-ADP-Service-Token` | 在连接器的安全凭据配置中保存，使用 Admin 创建的 API Key；不再接受环境变量服务 Token |
| Header `X-Platform-Context-Token` | 隐藏变量 `platform_context_token`，每轮生成，禁止写入提示词、聊天正文和普通日志 |
| Header `X-ADP-Request-Id` | `platform_tool_request_id` + 操作后缀，例如 `:lookup:1`；每次新调用唯一，重放会拒绝 |
| Body `query` | 用户要查询的完整订单号、提单号或箱号，1–128 字符 |
| Body `conversationId` | 隐藏变量 `platform_conversation_id`（可选一致性校验） |
| Body `runId` | 隐藏变量 `platform_run_id`（可选一致性校验） |
| Body `agentId` | 隐藏变量 `platform_agent_id`（可选一致性校验） |

`platform_application_id` 为当前数据库应用的 ApplicationId，供 ADP 编排使用，不接受为工具请求字段。工具请求不接受 `customerCode` 或其它额外字段；企业范围只由令牌对应的服务端上下文和当前有效权限决定。不要从管理调试页直接执行这些业务工具：该入口没有业务执行令牌。

建议 Agent 对一个编号调用 lookup；需要分步编排时，对同一编号调用 schedule、milestones。一次执行涉及不同查询编号时，平台返回澄清，避免把不同记录拼成一份结果。

## 固定 Mock 验收样例

| 当前企业 | 查询 | 预期 |
|---|---|---|
| MOCK-ENT-A | MOCK-ORDER-A001 / MOCK-BL-A001 / MOCK-CONT-A001 | 返回模拟船 ALPHA / A001，ETA 为 2026-10-01T08:00:00+08:00，当前节点「模拟：已离港」 |
| MOCK-ENT-A | MOCK-BL-B001 | not_found，不披露 B 企业记录 |
| MOCK-ENT-A | 不存在的编号 | not_found，与不可访问记录的对外语义相同 |
| MOCK-ENT-B | MOCK-BL-B001 | 返回模拟船 BETA / B001，ETA、当前节点、ATA 为「暂无数据」 |
| 任意 | 空 query、伪造 customerCode、错 runId | 参数错误或权限拒绝 |
| 任意 | 无令牌、失效令牌、重复请求 ID | 拒绝执行 |

Mock 使用固定数据，不会按输入临时生成订单；回复和来源均带模拟标识。schedule/milestones 当前是同一 lookup 契约的字段投影；正式 M3 独立 API 路径、鉴权与字段映射仍待上游文档，不代表真实 M3 已接入。

## 回复与执行生命周期

ADP 负责识别查询和选择工具。平台只使用本轮数据库中已完成的工具回执生成最终业务回复，忽略模型生成的船期、状态和证据。无回执、上游失败、不同编号或字段冲突时不输出未经核实的结果。未知字段显示「暂无数据」。

业务查询等待工具回执完成后发送确定性正文，企微可先显示「思考中」占位。这一策略收紧此前直接转发 ADP 文本流的业务路径；旧管理调试入口仍用于原生聊天调试。微信 `M3-WECHAT-OA-03` 既有渠道体验按用户确认已验收，但本轮业务编排改动仍需发布后回归。

上下文令牌只保存哈希。回调与结束使用数据库行锁协调；回合结束撤销令牌，Worker 重试也会废止旧令牌。客户端不能选择应用、企业或权限。

## 本地验证与真实验收

本地测试通过模拟 ADP SSE 调用真实 HTTP handler，使用独立 PostgreSQL 测试库、随机 schema，覆盖三种工具、企业隔离、重放、无回执、冲突、令牌撤销、持久化回复和企微最终帧。模拟的 ADP 不证明腾讯云实际参数映射可用。

```bash
PLATFORM_TEST_DATABASE_URL='postgresql+asyncpg://user:password@localhost/adp_biz_portal_orch_test' \
backend/.venv/bin/python -m pytest \
  backend/test/integration/test_adp_connector_postgres.py \
  backend/test/integration/test_wecom_bot_stream_postgres.py -q
```

真实验收需要：发布本轮代码、录入可用数据库 ADP 应用、在 ADP 导入连接器并配置隐藏参数、安全保存服务凭据，从 Portal/真实渠道发起上述查询，核对工具审计、最终回复及越权拒绝。完成前 `M2-ORCH-01` 和 `M4-ADP-CFG-01` 的真实联调保持 BLOCKED。正式 M3 验收另依赖 `M0-EXT-*` 与 `M2-M3-02`。

## 连接器 API Key 管理（2026-09-16）

管理接口要求服务端 `platform.manage` 权限。创建时生成 256 位随机密钥，创建和按需查看接口返回明文并设置 `Cache-Control: no-store`；数据库 `platform_adp_api_key` 保存 SHA-256 鉴权摘要、Fernet 加密副本与密钥版本、显示前缀、名称、创建/撤销时间。列表不返回密钥或摘要；创建、查看和撤销写入不含密钥的审计事件。

Key 为平台连接器级凭据，仅授权三个 shipment 工具；每次工具调用仍须验证执行上下文及当前企业权限。Key 不授权旧入站身份/上下文签发接口，这些内部适配器接口保留 `ADP_TOOL_SERVICE_TOKEN`。工具鉴权每次查询数据库，撤销提交后的新鉴权立即失败；已通过鉴权的在途请求不会被中断。

轮换：创建新 Key → 更新 ADP 连接器安全凭据 → 验证调用 → 撤销旧 Key。独立「开放接口」页面列出名称、默认隐藏的 Key、创建时间和状态，支持小眼睛查看及一键复制；查看时重新校验服务端权限并记录审计。刷新后重新隐藏。历史仅保存摘要的 Key 继续有效，但无法还原，需新建替换才能查看。加密副本复用平台凭据密钥，必须保留对应版本的密钥。此次仅本地实现和测试，生产需先备份并迁移至 19、创建 Key、更新 ADP 连接器，云端验收仍由 `M2-ORCH-01` 跟踪。

补充：API Key 列固定宽度，完整值在单元格内横向滚动。支持软删除（DeletedAt，revision 19），删除同时撤销，列表过滤已删除项，已删除 Key 不可查看或鉴权。删除要求 platform.manage，并记录 adp_api_key.delete 审计；数据库保留历史记录，不提供恢复入口。


## 远程 MCP（M4-MCP-01）

地址：`https://<平台域名>/mcp`，传输为无状态 Streamable HTTP，POST 返回 JSON，不分配 MCP Session ID。GET 返回 405（不提供服务端主动 SSE 推送）；不提供旧版 HTTP+SSE `/sse` 入口。支持协议版本 `2025-11-25`、`2025-06-18`、`2025-03-26`，initialize 协商版本，后续请求建议携带 `MCP-Protocol-Version`。实现 initialize、ping、tools/list、tools/call，通知返回 202，不支持批量 JSON-RPC。鉴权为预配置 API Key，不提供 OAuth 授权发现流程。

每个 POST 必须包含：
- `Authorization: Bearer <后台创建的 API Key>`（兼容 `X-ADP-Service-Token`）。
- `Content-Type: application/json`。
- `Accept: application/json, text/event-stream`。

工具调用另需可信客户端动态 Header `X-Platform-Context-Token` 和唯一 `X-ADP-Request-Id`，映射来源与 HTTP 连接器相同。不能把令牌放到模型参数。工具仅接受 query，不接受企业 ID、CustomerCode 或执行上下文作为参数。初始化和工具发现不需要业务上下文，但必须有有效 API Key。API Key 撤销/删除后包括发现接口在内均拒绝访问。

```json
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"adp-client","version":"1.0"}}}
```

初始化后发送 notifications/initialized 通知，再执行 tools/list。三个工具名为 shipment_lookup、shipment_schedule、shipment_milestones：

```json
{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"shipment_lookup","arguments":{"query":"MOCK-BL-A001"}}}
```

响应包含文本 content 和 structuredContent；权限/上下文/重放校验失败返回 isError，不暴露内部异常。查询不到数据仍是正常业务结果。工具调用共用 HTTP 执行链，继续记录回执、审计及生成确定性业务回复。无新增数据库迁移（依赖现有 revision 19）。Origin 存在时只接受请求同源；无浏览器 Origin 的服务端客户端正常接入。

隔离 PostgreSQL 验证见 test_mcp_postgres.py、test_mcp_protocol_postgres.py，并回归 test_adp_connector_postgres.py。ADP 云端能否配置 Bearer 凭据、传递动态上下文及唯一请求 ID 尚待真实验证；仅支持静态 Header 的客户端可以发现工具，但不能直接执行企业业务查询。M2-ORCH-01 保持 BLOCKED。

## 服务器联调状态（2026-09-16）

已按用户授权在 `https://adp.xdimspace.cn/mcp` 所在服务器开启固定 M3 Mock，API、Worker、企微网关均通过 Compose override 持久设置 `M3_USE_MOCK=true`，重建并检查生效；`.env` 未修改。该开关作用于这三个进程的 M3 适配器，固定数据仅包含 MOCK-ENT-A / MOCK-ENT-B。

公网 MCP 初始化、三个工具发现和已删除 Key 拒绝通过；运行镜像内固定数据及跨企业过滤四例通过。服务器已新增专用测试企业 MOCK-ENT-A/B，分别绑定 MCP 测试用户 A/B（登录占位手机号 19900000001/19900000002），仅有 shipment.read 权限并使用平台默认 ADP 应用；公网登录、管理权限拒绝和本企业/跨企业查询通过。初始口令保存在操作员本机仓库外受限文件。下一步从 Portal/渠道发起查询；ADP 调试台单独发送文字没有平台业务上下文，不能代替该验收。真实 ADP 动态 Header 映射及工具回执尚未验收，M2-ORCH-01 保持 BLOCKED。部署配置、恢复方式和验证记录见 ROADMAP 的 M4-MCP-MOCK-01。

## ADP API 参数与 MCP Header 映射（2026-09-17）

腾讯云 ADP 已确认支持将 API 参数变量映射到 MCP 请求 Header。采用以下稳定契约：

| API 参数 | 类型 | 必填 | MCP Header | 用途 |
|---|---|---:|---|---|
| `platform_context_token` | string | 是 | `X-Platform-Context-Token` | 短期、不透明上下文令牌，绑定用户、企业、权限版本、应用、渠道和会话 |
| `platform_tool_request_id` | string | 是 | `X-ADP-Request-Id` | 每次工具调用唯一，用于防重放和审计关联 |
| `corp_id` | string | 是 | `X-Corp-Id` | 当前企业 ID，便于路由、审计和一致性校验 |
| `corp_user_id` | string | 是 | `X-Corp-User-Id` | 当前企业员工 ID，便于员工身份映射和审计 |

ADP API 请求中的变量：

```json
{"custom_variables":{"platform_context_token":"ctx_...","platform_tool_request_id":"toolreq_...","corp_id":"corp_...","corp_user_id":"user_..."}}
```

MCP 连接器映射：

```text
X-API-Key: <连接器安全凭据中的 API Key>
X-Platform-Context-Token: {{API.platform_context_token}}
X-ADP-Request-Id: {{API.platform_tool_request_id}}
X-Corp-Id: {{API.corp_id}}
X-Corp-User-Id: {{API.corp_user_id}}
```

API Key 是 ADP 应用级服务身份，不代表具体企业。`corp_id` 和 `corp_user_id` 是 API 层的显式上下文字段，不能由模型填写，也不能单独作为权限依据；服务端必须将它们与 `platform_context_token` 解出的企业和员工身份逐一比对，不一致即拒绝请求。MCP 工具只暴露业务参数 `query`，不暴露企业编码或上下文令牌为模型参数。服务端继续校验 API Key、上下文有效期、权限版本、工具权限和请求 ID 重放状态。

验收应覆盖：企业 A/B 上下文隔离、缺少 Header、过期/撤销令牌、重复请求 ID，以及查询参数尝试跨企业读取。

## ADP 动态 Header 能力偏差（历史记录）

用户真实联调确认腾讯云 ADP 无法填充动态 Header；该结论已由 2026-09-17 的平台能力确认修正，当前以 API 参数映射契约为准。

补充确认：用户明确 MCP 工具参数只能由模型填写，不能固定映射 CustomVariables。请求体兼容方案因此不具备落地前提；不向模型暴露上下文凭据。推荐候选方案为 ADP 仅输出受限查询意图（操作、编号），平台将该意图绑定到当前已认证的执行轮次，校验操作白名单及权限，执行 M3 并保存工具回执，最终依据回执回复；模型输出不携带可信身份。该方案尚未实现，且属于平台侧编排，不能宣称 ADP→远程 MCP 闭环完成。保留 ADP 主动调用目标时，需要另行验证 HTTP 工作流是否支持可信动态变量映射。
