# 发布、迁移与回滚

本文描述通用的单机或容器化发布基线，不包含具体服务器、域名、账号或凭据。正式发布应由有数据库备份和部署权限的人员执行。

## 不变量

- 迁移由部署身份显式执行，Web 进程只校验版本，不自动建表。
- 迁移前备份，迁移成功后再启动同版本 API 和 Worker。
- API、Worker 和迁移使用同一代码版本、数据库和加密密钥。
- 应用回滚与数据库回滚是两个独立决定；数据库降级可能删除数据。
- 环境文件、密钥和持久化卷不通过代码同步工具删除或覆盖。

## 发布检查

```bash
make pack
cp docker/.env.example .env
docker compose config
docker compose up -d
curl -fsS http://127.0.0.1:8000/healthz
curl -fsS http://127.0.0.1:8000/readyz
```

记录发布版本、执行人、数据库备份位置、升级前后 revision 和回退窗口。生产环境应在反向代理或负载均衡器后启用 HTTPS，不要暴露数据库端口。

## 备份与迁移

使用受控数据库账号，将备份保存到独立介质并校验：

```bash
pg_dump --format=custom --no-owner \
  --file=/secure/backup/adp-biz-portal-<release>-<timestamp>.dump \
  "$DATABASE_URL"
sha256sum /secure/backup/adp-biz-portal-<release>-<timestamp>.dump
```

再执行：

```bash
MIGRATION_ACTOR="release-<release>" make migrate
docker compose up -d
```

检查 `/readyz` 的 schema revision、API/Worker 日志和队列状态。迁移失败时保持旧版本进程，不要绕过启动检查。

## 回滚

应用启动失败但 schema 向后兼容时，只回滚 API 和 Worker 镜像，不自动降级数据库。只有在确认新版本表和数据可以丢失、所有业务进程已停止并完成审批后，才执行：

```bash
backend/.venv/bin/python backend/migrate.py downgrade \
  --target <revision> --allow-data-loss --applied-by "rollback-<release>"
```

数据异常时先恢复到隔离数据库，验证迁移历史、账号登录和一条脱敏查询，再决定是否切换连接配置。

## 运维安全

不要在工单、日志、截图或 issue 中保存 API Key、AppKey、Token、客户订单和原始渠道载荷。MCP Key 应在管理后台轮换和撤销。固定 Mock 只属于隔离环境，不能写入生产或作为真实第三方验收证据。
