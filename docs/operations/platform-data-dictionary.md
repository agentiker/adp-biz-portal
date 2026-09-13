# 统一业务平台数据字典

本文以 `backend/model/platform.py` 和当前迁移定义为准，描述平台新增表、关键字段、关联关系和敏感数据边界。字段名保留代码中的 PascalCase 写法；实际数据库列名与模型一致。旧聊天表仍由原项目维护，不在本字典中重新定义。

## 数据边界

| 数据类别 | 主要表 | 用途 | 浏览器可见性 |
| --- | --- | --- | --- |
| 身份与授权 | `platform_user`、`platform_membership`、`platform_credential`、`platform_auth_session` | 登录、角色、企业范围、会话撤销 | 仅返回脱敏用户、角色和范围；不返回哈希、盐或 Token 原文 |
| 企业与上游绑定 | `platform_enterprise`、`integration_connection`、`enterprise_external_account` | 企业、M3 客户编码和旧 ADP Workspace 选择器 | 管理员按权限读取映射元数据；新平台渠道不依赖这些旧兼容绑定 |
| 渠道入口与身份 | `platform_channel_credential`、`platform_channel_identity` | 平台级渠道凭据和外部身份到平台用户的映射 | 管理员按权限读取掩码元数据；渠道凭据只保存认证密文，渠道身份只返回脱敏信息，浏览器和日志不接触明文 state 或凭据；企业范围不固化在渠道记录中 |
| 官网会话与证据 | `platform_conversation`、`platform_message`、`platform_execution_run`、`platform_evidence` | 归属隔离、历史恢复和可验证业务结果 | 只允许所属账号读取；同企业其他账号也不能读取 |
| 入站与投递 | `platform_inbound_message`、`platform_delivery_task` | 渠道去重、Worker 租约、重试和发送结果 | 仅运维/管理权限可查看脱敏状态，原始载荷不得进入普通日志 |
| 工具执行 | `platform_tool_definition`、`platform_execution_context`、`platform_tool_call` | 受控工具、短期上下文和请求幂等 | 不返回上下文 Token、TokenHash 或完整上游载荷 |
| 审计与配置 | `platform_audit_event`、`platform_config_version`、`platform_migration`、`platform_schema_version` | 操作追踪、配置发布和迁移状态 | 管理员只读查看脱敏结果；配置发布需要 `platform.manage` |

## 表与关键字段

### 身份、企业和绑定

| 表 | 主键/唯一约束 | 关键字段 | 关联与规则 |
| --- | --- | --- | --- |
| `platform_enterprise` | `Id`；`CustomerCode` 唯一 | `Name`、`CustomerCode`、`Status`、`ExtraInfo` | `Status` 为 `active`/`suspended`；停用后企业范围校验失败；客户编码是 M3 业务范围键，不是员工字段 |
| `platform_user` | `Id`；`AccountId`、`PhoneNormalized` 唯一 | `Name`、`PhoneMasked`、`Role`、`Status` | `AccountId` 指向旧账号；手机号只保留规范化索引和脱敏展示；角色为 `customer`/`staff`/`admin`/`ops` |
| `platform_membership` | `Id`；`(UserId, EnterpriseId)` 唯一 | `MembershipRole`、`Active` | 用户可有多个企业范围；停用 membership 后旧上下文和待发送任务必须失效 |
| `platform_credential` | `Id`；`AccountId` 唯一 | `PasswordHash`、`PasswordSalt`、`FailedAttempts`、`LockedUntil`、`MustReset` | 只保存 PBKDF2 哈希和随机盐；禁止写入明文口令、Token 或完整手机号 |
| `platform_auth_session` | `Id`；`TokenId` 唯一 | `AccountId`、`ExpiresAt`、`RevokedAt`、`LastSeenAt` | 浏览器 Token 只作为不可逆会话索引使用；密码重置、停用和权限收窄会撤销相关会话 |
| `integration_connection` | `Id`；`ApplicationId` 唯一 | `ApplicationId`、`UpstreamAppId`、`Vendor`、`Status` | 服务端维护旧应用到上游连接的映射；客户端提交的 ApplicationId 只能作为选择器 |
| `enterprise_external_account` | `Id`；`(EnterpriseId, ConnectionId)`、`(ConnectionId, WorkspaceId)` 唯一 | `ExternalAccountId`、`WorkspaceId`、`Status` | 把企业和上游 Workspace 绑定；绑定停用后旧兼容路由立即拒绝；真实 Workspace 归属仍需第三方验证 |
| `platform_channel_credential` | `Id`；`(Channel, ChannelInstanceId)` 全局唯一 | nullable 兼容字段 `EnterpriseId`/`ConnectionId`；`Ciphertext`、`KeyVersion`、`Version`、`Fingerprint`、`Status`、`RotatedAt`、`ExpiresAt` | 新凭据的企业与连接字段固定为空；`Ciphertext` 为 Fernet 认证密文，`KeyVersion` 用于受控密钥轮换，`Fingerprint` 仅为摘要；管理员 API 只返回固定掩码和元数据，Worker 才能在服务端解密 |
| `platform_channel_identity` | `Id`；外部身份按渠道实例和状态索引；`StateHash` 用于一次性绑定确认；`(Channel, ChannelInstanceId, ExternalIdentityId)` 在 `Status='active'` 上部分唯一 | `UserId`、`AccountId`、nullable 兼容字段 `EnterpriseId`、`Channel`、`ChannelInstanceId`、nullable `ExternalIdentityId`、`Status`、`StateHash`、`StateExpiresAt`、`ConfirmedAt`、`RevokedAt` | 新身份的 `EnterpriseId` 固定为空；绑定 state 只保存 SHA-256 摘要并一次性消费；确认时重新校验渠道、实例、用户和账号。`ExternalIdentityId` 在等待原渠道发送者确认期间为空，由可信适配器在确认时写入；部分唯一索引保证同一外部身份同时只归属一个平台用户，并发确认由数据库拒绝。解绑、密码重置或账号停用会撤销身份；企业、membership 或角色变化只使旧执行上下文/待发送结果失效，Worker 在下一次消息执行时按最新范围鉴权 |
| `platform_channel_replay_marker` | `(Channel, ChannelInstanceId, ReplayKey)` 唯一；`ExpiresAt` 索引 | `Channel`、`ChannelInstanceId`、`ReplayKey`、`ExpiresAt` | 已验签通过的渠道回调签名摘要，跨 API 实例和进程重启拒绝重放；只保存摘要不保存回调内容；过期行按批清理，唯一约束而非清理进度决定拒绝行为。与 `platform_inbound_message` 的消息级去重相互独立：渠道正常重试不会复用签名 |

### 会话、消息与证据

| 表 | 关键字段 | 规则 |
| --- | --- | --- |
| `platform_conversation` | `AccountId`、`EnterpriseId`、`Channel`、`Title`、`LastActiveAt` | 平台生成 `Id`；官网、微信和企微会话按渠道独立；读取必须同时匹配账号和企业 |
| `platform_message` | `ConversationId`、`AccountId`、`EnterpriseId`、`ExecutionRunId`、`Direction`、`Body`、`Payload`、`TraceId` | `Payload` 是内部结构化数据；日志和管理界面只显示脱敏摘要；删除会话时级联删除消息 |
| `platform_execution_run` | `RunId` 唯一、`Query`、`Status`、`Summary`、`TraceId`、`StartedAt`、`CompletedAt` | 一次可追踪业务执行；状态和 summary 不等于真实 M3 证据，关键断言必须关联 evidence |
| `platform_evidence` | `ExecutionRunId`、`ConversationId`、`AccountId`、`EnterpriseId`、`Label`、`Value`、`Source`、`CapturedAt`、`Known` | 同一 run 的 `Label` 唯一；只保存字段白名单和来源；`Known=false` 不得被渲染为确定事实 |

### 入站、任务和工具执行

| 表 | 关键字段 | 规则 |
| --- | --- | --- |
| `platform_inbound_message` | `ChannelInstanceId`、`ExternalMessageId`、`ExternalConversationId`、`SenderIdentityId`、`Text`、`Status`、`TraceId`、nullable `ReplyWindowExpiresAt` | `(ChannelInstanceId, ExternalMessageId)` 唯一，用于渠道回调去重；发送者身份必须由适配器验证后生成；`ReplyWindowExpiresAt` 由适配器按渠道协议窗口从发信时刻推导，发送前据此拒绝超窗回复，官网渠道为空 |
| `platform_delivery_task` | `TaskType`、`DeduplicationKey`、`ConversationKey`、`Payload`、`Status`、`Attempts`、`MaxAttempts`、`LeaseOwner`、`LeaseUntil`、`LastError`、`Result` | `DeduplicationKey` 唯一；租约过期可恢复；业务执行和回复发送分别使用任务类型与重试边界 |
| `platform_tool_definition` | `Name` 唯一、`Version`、`Permission`、`Enabled`、`ReadOnly` | 只登记平台批准的工具；后台不能通过 URL、SQL 或脚本创建任意工具 |
| `platform_execution_context` | `TokenHash` 唯一、`UserId`、`AccountId`、`EnterpriseId`、nullable `PlatformSessionId`、`ConversationId`、`AgentId`、`Channel`、`RunId`、`PermissionVersion`、`ExpiresAt`、`RevokedAt` | 原始 context token 只在签发时返回；数据库只存 SHA-256 摘要；每次工具调用重新检查当前权限。浏览器发起的上下文绑定登录会话并随其失效；渠道发起的上下文没有会话（`PlatformSessionId` 为空），改由已确认的渠道身份加执行时 membership/权限版本授权，账号级撤销同时作废两者 |
| `platform_tool_call` | `(ExecutionContextId, RequestId)` 唯一、`ToolName`、`QueryHash`、`TraceId`、`Status`、`Outcome`、`Evidence` | 防止同一请求重放；已完成调用不可重复执行；允许安全恢复处于 `started` 的调用 |

### 审计、配置和迁移

| 表 | 关键字段 | 规则 |
| --- | --- | --- |
| `platform_audit_event` | `ActorAccountId`、`Action`、`TargetType`、`TargetId`、`TraceId`、`Outcome`、`Metadata`、`CreatedAt` | 记录管理操作、授权拒绝、上游降级和投递结果；`Metadata` 只放脱敏键值 |
| `platform_config_version` | `Version` 唯一、`Status`、`Payload`、`ValidationErrors`、三类操作者 ID、发布/回滚时间 | 状态为 `draft`/`published`/`rolled_back`；发布和回滚必须保留审计；配置不保存真实密钥 |
| `platform_migration` | `Version` 主键、`Name`、`Checksum`、`Status`、`AppliedBy`、`AppliedAt`、`RolledBackAt` | 迁移 CLI 写入；Web/Worker 只校验，不自动建表或升级 |
| `platform_schema_version` | `Version` 主键、`AppliedAt` | 兼容 revision 5 之前的安装；当前发布目标以 `Migration.CURRENT_PLATFORM_SCHEMA_VERSION` 为准 |

## 关系摘要

```text
account
  ├─ platform_user ──< platform_membership >── platform_enterprise
  ├─ platform_credential
  └─ platform_auth_session

platform_enterprise ──< enterprise_external_account >── integration_connection
platform_channel_credential       平台级渠道实例（无企业归属）
platform_user ──< platform_channel_identity（无固定企业授权，活跃身份唯一）
platform_conversation ──< platform_message
                      └─< platform_execution_run ──< platform_evidence
platform_inbound_message ──> platform_delivery_task
platform_execution_context ──< platform_tool_call
```

所有带 `AccountId` 和 `EnterpriseId` 的业务记录都必须在服务端做归属过滤。不能用浏览器提交的企业、Workspace、ApplicationId、ConversationId 或模型生成的身份字段替代数据库关联和当前授权校验。

## 迁移版本

| Revision | 名称 | 引入内容 |
| ---: | --- | --- |
| 1 | `legacy_chat_schema` | 原聊天、账号和 Agent 表 |
| 2 | `platform_identity_schema` | 企业、用户、membership、凭据、登录会话、平台会话 |
| 3 | `platform_delivery_and_config_schema` | 入站消息、投递任务、配置版本、schema 兼容标记 |
| 4 | `platform_execution_and_audit_schema` | 工具定义、执行上下文、工具调用、审计 |
| 5 | `explicit_migration_lifecycle` | 显式迁移生命周期表 |
| 6 | `portal_conversation_history_schema` | execution run、消息、证据 |
| 7 | `legacy_application_binding_schema` | 旧应用连接和企业 Workspace 绑定 |
| 8 | `platform_channel_credential_schema` | 加密渠道凭据、密钥版本、轮换和停用状态（初始版本仍包含企业/连接归属） |
| 9 | `platform_channel_identity_binding_schema` | 渠道身份绑定、一次性确认 state、过期和撤销状态 |
| 10 | `platform_channel_scope_schema` | 渠道凭据改为平台级全局实例，清空历史企业/连接归属并使用 nullable `SET NULL` 兼容字段 |
| 11 | `platform_channel_identity_scope_schema` | 渠道身份改为平台用户级，清空历史企业归属并将兼容字段改为 nullable `SET NULL` |
| 12 | `platform_channel_execution_scope_schema` | 执行上下文 `PlatformSessionId` 与渠道身份 `ExternalIdentityId` 改为 nullable，新增 `platform_inbound_message.ReplyWindowExpiresAt` 与 `platform_channel_replay_marker` 表，并在活跃渠道身份上建立部分唯一索引；存在重复活跃绑定时迁移停止并要求人工撤销 |

迁移详情以 `backend/core/migration.py` 为准；生产升级必须使用 `backend/migrate.py`，不能通过应用启动阶段隐式修改 schema。
