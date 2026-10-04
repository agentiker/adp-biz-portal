# MCP 与 ADP 接入

本项目把企业身份、成员关系、权限和业务查询统一收口在平台服务端，再通过 MCP 或 HTTP 工具向 AI 应用提供受控能力。模型只填写业务查询参数，企业和员工身份由可信执行上下文确定。

## MCP 端点

部署后端点为 `https://<host>/mcp`，使用无状态 Streamable HTTP。请求需要：

```http
Authorization: Bearer <platform-api-key>
Content-Type: application/json
Accept: application/json, text/event-stream
```

API Key 在管理后台“开放接口”页面创建、查看和撤销。它是平台连接器级服务身份，不代表某个企业；撤销后立即失效。生产环境应通过 HTTPS 和密钥管理系统保存它。

支持 `initialize`、`ping`、`tools/list` 和 `tools/call`。工具名称为 `shipment_lookup`、`shipment_schedule` 和 `shipment_milestones`，工具参数只有业务查询值 `query`：

```json
{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"shipment_lookup","arguments":{"query":"ORDER-001"}}}
```

查询结果同时提供 `content` 和 `structuredContent`。未找到或无权访问的记录统一返回 `not_found`，避免泄露跨企业记录存在性。

## 执行上下文

工具调用还需要由平台或可信适配器传入动态 Header：

| Header | 作用 |
| --- | --- |
| `X-Platform-Context-Token` | 短期执行上下文，绑定用户、企业、权限版本、应用、渠道和会话 |
| `X-ADP-Request-Id` | 每次工具调用唯一，用于防重放和审计关联 |
| `X-Corp-Id` | 当前企业 ID，用于一致性校验和审计 |
| `X-Corp-User-Id` | 当前企业员工 ID，用于一致性校验和审计 |

服务端会将这些 Header 与令牌解出的身份逐一比对，并检查令牌有效期、权限版本、工具权限和请求 ID。企业 ID、员工 ID、CustomerCode 和令牌都不应暴露为模型参数，也不能依赖提示词或客户端字段授权。

腾讯云 ADP 可把 API 请求中的 `custom_variables` 映射为 MCP Header。推荐参数契约如下：

```json
{
  "custom_variables": {
    "platform_context_token": "ctx_...",
    "platform_tool_request_id": "toolreq_...",
    "corp_id": "corp_...",
    "corp_user_id": "user_..."
  }
}
```

映射关系为 `platform_context_token` → `X-Platform-Context-Token`、`platform_tool_request_id` → `X-ADP-Request-Id`、`corp_id` → `X-Corp-Id`、`corp_user_id` → `X-Corp-User-Id`。若 ADP 或其他客户端不能可信地传递动态 Header，只能使用平台侧已认证的执行轮次编排工具调用，不能让模型自行生成身份字段。

## HTTP 工具与 Mock

HTTP 连接器的 OpenAPI 定义在 [`docs/api/adp-tools.openapi.yaml`](../api/adp-tools.openapi.yaml)。固定 Mock 仅在显式设置 `M3_USE_MOCK=true` 时启用，用于本地和隔离环境验证企业范围、重放保护和确定性回执。Mock 不证明真实 M3 或 ADP 已联调；切换真实 M3 前应配置正式上游地址、凭据、字段归属、分页和错误码。

推荐验证顺序：先调用 `initialize` 和 `tools/list`，再使用隔离测试企业执行一条查询，检查审计和结构化回执，最后验证缺少 Header、过期令牌、重复请求 ID 和跨企业查询均被拒绝。
