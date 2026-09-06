# 统一业务平台排障手册

本文用于本地开发和受控部署排障。排障优先使用 trace、任务 ID、migration revision 和脱敏状态定位；不要复制客户订单、口令、Session Token、AppKey、M3 Token 或渠道原始载荷到工单和聊天。

## 先确认范围

1. 记录发生时间、发布版本、环境、账号角色、企业 ID 的脱敏标识、`traceId`、`conversation_id` 或任务 ID。
2. 判断是 Web 请求、Worker 任务、M3 上游、ADP 元信息、渠道发送还是数据库迁移问题。
3. 查看对应的 `platform_audit_event`、`platform_delivery_task`、`platform_execution_run`，不要先重试未知结果的外部发送。
4. 确认当前数据库 revision；Web 和 Worker 必须使用同一版本代码和同一数据库。

## 常用只读检查

在加载了正确 `server/.env` 的受控终端执行：

```bash
server/.venv/bin/python server/migrate.py --help
cd server && .venv/bin/python worker.py --help
server/.venv/bin/python -m compileall -q server
git diff --check
```

数据库检查应使用只读账号或隔离诊断连接，并只取计数、状态和时间：

```sql
select "Status", count(*) from platform_delivery_task group by "Status";
select "Status", count(*) from platform_execution_run group by "Status";
select "Action", "Outcome", count(*) from platform_audit_event group by "Action", "Outcome";
select "Version", "Status", "AppliedAt", "RolledBackAt"
from platform_migration
order by "Version";
```

不要在生产环境执行 `select *` 导出 `Payload`、`Body`、`Evidence`、`Metadata` 或凭据字段。

### 运维状态接口

具有 `platform.diagnose` 权限的运维账号可以调用只读接口：

```bash
curl -sS -H "Authorization: Bearer <platform-session-token>" \
  https://<host>/api/v1/ops/status
```

`GET /api/v1/ops/status` 只返回当前迁移版本、投递任务和执行状态计数、最近失败的固定错误分类、ADP 元信息健康计数和受控排障建议。接口不返回业务载荷、消息正文、证据、完整异常、口令、Token、Secret、AppKey 或 `LastError` 原文；建议中的 `code` 和 `message` 是固定值，不能作为自动执行命令。

普通客户、客服和平台管理员没有 `platform.diagnose` 权限，直接调用会返回拒绝。数据库聚合失败时接口只返回异常类型和 `ops_query_failed` 建议，详细原因仅写入服务端按权限保护的日志。

## 故障分流

### Web 无法启动或提示 migration required

**现象**：Web/Worker 启动失败，日志包含 `MigrationRequiredError` 或数据库 revision 不匹配。

**处理**：

1. 停止继续放量，确认没有旧 Worker 正在写任务。
2. 用发布工单中的数据库连接执行 `server/.venv/bin/python server/migrate.py upgrade --applied-by "<release-id>"`。
3. 检查 `platform_migration` 的版本、checksum 和状态；不要让 Web 进程执行 `metadata.create_all()` 或手工建表。
4. 若数据库由更新版本迁移，先回滚应用代码到兼容版本；数据库降级需要备份、审批和显式 `--allow-data-loss`，流程见 `release-and-rollback.md`。

### 登录失败、账号被锁定或管理员操作被拒绝

**现象**：登录返回未授权/限流，或后台返回 403。

**处理**：

1. 确认手机号经过规范化，账号、`PlatformUser.Status`、旧 `Account.Status` 和 `PlatformCredential.LockedUntil` 是否有效。
2. 检查角色是否具备所需权限：客户查询需要 `shipment.read`，后台管理需要 `platform.manage`，运维诊断需要 `platform.diagnose`。
3. 确认企业为 `active`，membership 的 `Active=true`，对应 binding 未停用。
4. 口令重置或停用后不要复用旧 Token；重新登录并记录新的 trace。
5. 不要通过前端隐藏按钮、修改请求中的企业 ID 或伪造 `ApplicationId` 绕过授权。

### 查询返回 `needs_clarification`、`not_found` 或 `upstream_error`

**现象**：Portal 显示需要澄清、未找到可访问记录或上游不可用。

**处理**：

1. `needs_clarification`：让用户补充业务标识，不要让模型猜测箱号、提单号或船期。
2. `not_found`：按统一对外语义处理；内部再检查企业客户编码、字段归属和是否被过滤，不能向客户泄露“记录存在但无权限”。
3. `upstream_error`：检查 `M3_BASE_URL`、超时、上游 HTTP 状态、`traceId` 和 Worker 的 `LastError`；未配置真实 M3 且未显式 `M3_USE_MOCK=true` 时，返回该状态是预期行为。
4. 只把 `platform_evidence` 中 `Known=true` 且来源明确的字段作为确定业务事实；预计/实际时间不可混用。

### 任务积压、重复执行或租约超时

**现象**：`platform_delivery_task` 长时间处于 `queued`/`processing`，或同一消息反复出现。

**处理**：

1. 查看 `TaskType`、`DeduplicationKey`、`Attempts`、`MaxAttempts`、`LeaseOwner`、`LeaseUntil` 和 `LastError`。
2. 确认 Worker 使用稳定的 `--worker-id`，并与 Web 使用同一数据库和 schema。
3. `LeaseUntil` 过期的任务可由 Worker 重新领取；不要手工复制任务行或修改 deduplication key。
4. `DeliveryRetryableError` 才允许有限重试；不可分类异常会终止任务，外部发送结果未知会进入 `uncertain`，不能盲目重发。
5. 检查同一 `ConversationKey` 是否因 FIFO 规则等待前一任务；无关会话不应被同一 key 阻塞。

### 回复被拒绝为 `authorization_revoked`

**现象**：执行结果已经存在，但 `platform.reply` 变成 `failed`，审计显示 `authorization_revoked`。

**处理**：这是预期安全行为，不要强行补发。确认是否发生了密码重置、账号/企业停用、membership 解绑、角色收窄、会话撤销或 binding 停用。重新授权后由用户发起新查询；旧 evidence 不得发送到新范围。

### 回复状态为 `uncertain`

**现象**：渠道发送器超时或断线，平台无法确认上游是否已收到消息。

**处理**：

1. 先使用渠道提供的上游消息 ID、状态查询或管理后台确认；不要直接重新发送私有业务结果。
2. 记录任务 ID、稳定幂等键 `platform-reply:<inboundMessageId>`、trace 和渠道实例。
3. 若渠道没有状态查询或幂等协议，把该条标为人工处理，不把 `uncertain` 改成 `succeeded`。

### ADP 应用名称或元信息异常

**现象**：应用列表名称显示 `Unknown` 或元信息刷新失败，但聊天路由仍可用。

**处理**：

1. 查看 `adp.metadata.refresh` 审计事件和脱敏错误原因。
2. 确认该应用的上次成功元信息是否仍在缓存；`metadata_status=degraded` 不等于聊天能力已失效。
3. 只在获得正式 ADP 文档、权限和回调样本后调整协议；不要把管理 API 的失败扩散成聊天不可用。

## 不要做的操作

- 不要把 `M3_USE_MOCK=true` 的结果写进生产环境，也不要用本地 Mock 证明真实 M3 已联调。
- 不要在数据库中直接修改账号状态、权限、任务结果或迁移状态来“修复”问题；应通过管理 API、迁移 CLI 或经审批的运维脚本。
- 不要重试未知外部发送、重复执行已完成工具调用或复制旧 execution context。
- 不要在日志、截图、工单、测试夹具中保存真实口令、Token、AppKey、M3 凭据、客户订单和渠道原始回调。

## 升级条件

以下任一情况应停止自动处理并升级给平台负责人和对应上游负责人：

- 同一 deduplication key 出现多个成功执行；
- 企业范围校验与 M3 返回归属不一致；
- `uncertain` 消息无法通过上游状态查询确认；
- 数据库 checksum 不一致、迁移状态回退或出现未知 revision；
- 真实 ADP/M3/微信/企微协议与当前适配器契约不一致。
