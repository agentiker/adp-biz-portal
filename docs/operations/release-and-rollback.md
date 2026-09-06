# 发布、迁移与回滚运行手册

本文对应 `M4-RELEASE-01`，用于统一业务接入平台的发布前检查、数据库迁移、Web/Worker 启停和故障回退。生产发布仍需由具备数据库备份、部署和监控权限的人员执行；本文不包含任何真实凭据。

## 发布不变量

- 数据库迁移由部署身份显式执行，Web 进程只校验迁移状态，不自动建表或升级 schema。
- 同一数据库同一时刻只允许一个迁移命令运行。迁移 runner 使用 PostgreSQL transaction advisory lock。
- 先备份、再迁移、后启动新版本 Web/Worker。迁移未完成时不得启动业务进程。
- 应用代码回滚和数据库回滚是两个独立决定。数据库降级会删除目标 revision 创建的表及数据，只能在确认数据恢复方案后执行。
- Worker 与 Web 必须使用同一版本代码和同一数据库，避免旧 Worker 读取新任务结构。

## 发布前检查

### Docker Compose 基线

仓库根目录的 `docker-compose.yml` 提供本地和单机试运行基线，包含 PostgreSQL、一次性迁移、API 和 Worker 四个服务。先构建当前版本镜像，再复制环境模板并只在目标机器填写凭据：

```bash
make pack
cp docker/.env.example .env
docker compose config
docker compose up -d
curl -fsS http://127.0.0.1:8000/healthz
curl -fsS http://127.0.0.1:8000/readyz
```

`/healthz` 只表示 API 进程存活，不访问 PostgreSQL 或第三方服务；`/readyz` 会检查 PostgreSQL 连通性、迁移历史和当前 revision。Compose 的 API/Worker 会等待 `migrate` 成功后再启动，`reverse-proxy` 等待 API 健康后对外提供 HTTP 入口，数据库数据保存在 `platform-postgres` 卷中。公网生产环境仍应在该入口配置受控 HTTPS（或放在云负载均衡之后），不能把数据库端口暴露到公网。

在发布机或受控运维终端执行以下检查，命令中的数据库连接由 `server/.env` 提供：

```bash
git rev-parse --verify HEAD
server/.venv/bin/python --version
server/.venv/bin/python server/migrate.py --help
server/.venv/bin/python -m compileall -q server
git diff --check
```

确认以下信息已记录在发布工单中：

- 发布版本、执行人、变更窗口和预计回退窗口；
- 数据库名称、schema、备份文件/对象存储位置和备份校验值；
- 当前数据库 revision、目标 revision（当前代码目标为 `9`）；
- Web、Worker、PostgreSQL 和上游 ADP/M3 的健康检查地址；
- 本次发布是否包含不可逆数据变更。

## 备份与迁移

1. 停止接收新流量，等待当前 Web 请求和 Worker 任务进入可观测状态。不要在未确认任务状态时强制删除 Worker。
2. 使用受控的 `pg_dump` 生成自定义格式备份，并将文件保存到独立介质。示例中的文件名和路径必须替换为发布工单指定的位置：

   ```bash
   pg_dump --format=custom --no-owner --file=/secure/backup/adp-chat-client-<release>-<timestamp>.dump "$DATABASE_URL"
   sha256sum /secure/backup/adp-chat-client-<release>-<timestamp>.dump
   ```

3. 使用部署数据库账号执行可重复的升级。`MIGRATION_ACTOR` 应使用工单中的服务身份，而不是个人密码：

   ```bash
   MIGRATION_ACTOR="release-<release>"
   server/.venv/bin/python server/migrate.py upgrade --applied-by "$MIGRATION_ACTOR"
   ```

   也可以使用仓库目标：

   ```bash
   MIGRATION_ACTOR="release-<release>" make migrate
   ```

4. 记录命令输出的 `database revision`，并检查 `platform_migration` 中每个 revision 均为 `applied`。迁移失败时保持旧版本进程，不要绕过启动检查。

## 启动顺序与冒烟检查

1. 启动一个 Web 实例，确认启动日志没有 `MigrationRequiredError`，健康检查返回成功。
2. 启动 Worker，确认只消费当前版本支持的任务类型；多实例发布时先完成一个实例的冒烟，再逐步放量。
3. 执行以下不包含业务敏感数据的冒烟流程：登录、读取企业/用户列表、创建一个测试会话、提交一条官网入站消息、确认 Worker 产生执行结果或明确的 `upstream_error`，最后确认撤权后的回复任务不会发送。
4. 检查以下监控指标/日志：HTTP 5xx、队列积压、任务 lease 超时、`authorization_revoked`、`upstream_error`、回复 `uncertain` 和数据库连接池错误。
5. 冒烟通过后恢复流量，并在发布工单记录开始放量时间、实例数量和观察窗口。

## 回滚决策

### 仅应用代码回滚

当新代码启动失败、健康检查失败，但数据库 revision 向后兼容时，优先停止新进程并恢复上一版本 Web/Worker。不要自动执行数据库降级。恢复后重新执行登录、队列和会话冒烟检查。

### 数据库降级

只有在以下条件全部满足时才允许降级：

- 旧版本代码无法兼容当前 schema；
- 已确认目标 revision 之后创建的表和数据允许丢失，或已从备份恢复到独立数据库验证；
- 变更负责人和数据库负责人在工单中明确批准；
- 已停止所有 Web/Worker，避免旧进程继续写入。

降级命令必须显式提供 `--allow-data-loss`，例如回退到 revision `3`：

```bash
server/.venv/bin/python server/migrate.py downgrade \
  --target 3 \
  --allow-data-loss \
  --applied-by "rollback-<release>"
```

降级后只能启动与目标 revision 兼容的旧版本。若需要恢复新版本，先确认备份/数据恢复策略，再执行：

```bash
server/.venv/bin/python server/migrate.py upgrade --applied-by "reupgrade-<release>"
```

### 从备份恢复

当数据完整性受到影响时，优先恢复到隔离数据库并验证，不要直接覆盖线上库。恢复操作使用平台既有数据库运维流程；至少完成表计数、迁移历史、账号登录和一条脱敏业务查询验证后，才决定切换连接配置。

## 演练记录模板

每次正式演练都应复制以下字段到发布工单：

```text
演练日期：
发布版本：
数据库备份位置：
备份 sha256：
升级前 revision：
升级后 revision：
应用回滚开始/结束：
数据库降级开始/结束（如执行）：
恢复验证结果：
RPO：
RTO：
异常与后续 TODO：
```

## 当前仓库验证边界

本地发布检查可以用一个命令重复执行；它只使用集成测试创建的隔离 schema，不会升级或回滚开发库：

```bash
PLATFORM_TEST_DATABASE_URL='postgresql+asyncpg://adp_chat_client_local@127.0.0.1:5432/adp_chat_client_local' \
  make release_drill
```

命令会验证 Compose 配置、迁移 CLI 帮助和 `1..9 -> 3 -> 9` 的隔离迁移流程，并将日志和汇总写入 `output/tests/m4-release-01/`。证据中的 `productionStatus` 固定为 `not_executed`，不能当作生产发布、应用回滚或 RPO/RTO 记录。

截至 2026-09-06，仓库已在隔离 PostgreSQL schema 中验证 revision `1..9` 可重复升级、审计、降级到 `3` 并再次升级到 `9`，并通过启动版本校验。定向命令为：

```bash
PLATFORM_TEST_DATABASE_URL='postgresql+asyncpg://adp_chat_client_local@127.0.0.1:5432/adp_chat_client_local' \
  server/.venv/bin/pytest server/test/integration/test_platform_migration_postgres.py -q -s
```

结果为 `1 passed in 0.96s`；证据见 `output/tests/m1-mig-01-migration.json`、`server/test/integration/test_platform_migration_postgres.py` 和渠道身份定向回归。本结果证明的是迁移代码和本地流程可运行，不代表生产备份恢复、部署权限、RPO/RTO 或真实 ADP/M3 联调已经完成。
