# 备份与恢复演练

本文对应 `M4-DR-01`。备份和恢复是发布流程的一部分，但当前仓库只能在本地 PostgreSQL 上提供可复现的流程演练；本地目录不等于异地或独立介质，也不能替代生产 RPO/RTO 验收。

## 本地隔离演练

演练脚本只创建并删除一个带唯一名称的 scratch schema，不改动 `public` schema。它会写入一个标记行，生成 PostgreSQL custom-format dump，把 dump 复制到单独目录，删除 scratch schema，再从复制文件恢复并校验标记行和 SHA-256。

```bash
DATABASE_URL='postgresql://adp_chat_client_local@127.0.0.1:5432/adp_chat_client_local' \
  ./script/postgres-backup-drill.sh \
  --artifact-dir output/tests/m4-dr-01 \
  --media-dir output/tests/m4-dr-01-independent-media
```

也接受应用测试使用的 SQLAlchemy URL：

```bash
export PLATFORM_TEST_DATABASE_URL='postgresql+asyncpg://adp_chat_client_local@127.0.0.1:5432/adp_chat_client_local'
./script/postgres-backup-drill.sh \
  --database-url "$PLATFORM_TEST_DATABASE_URL"
```

脚本接受应用使用的 `postgresql+asyncpg://` URL，并会在调用 PostgreSQL 命令行工具前转换为 `postgresql://`。

成功后，`evidence.json` 会记录备份文件、独立目录副本、两份 SHA-256、恢复耗时、恢复前后行数和生产遗留项。脚本不会把恢复耗时写成生产 RTO，也不会把本地目录写成异地存储。

## 生产执行要求

生产发布时必须使用受控的 `pg_dump` 或托管 PostgreSQL 的等价快照能力，并满足以下条件：

1. 备份写入独立的加密对象存储或其他异地介质，至少保留校验值、创建时间、数据库 revision 和执行身份。
2. 按业务确认的备份频率计算 RPO；当前 POC 文档只给出每日快照的最坏 24 小时上限，不是生产承诺。
3. 将备份恢复到隔离数据库，完成迁移历史、表计数、管理员登录和一条脱敏业务查询验证，再决定是否切换连接配置。
4. 记录从恢复开始到业务冒烟通过的 RTO；没有实际恢复开始/结束时间，不得填写 RTO 数字。
5. 在发布工单中记录备份位置、SHA-256、升级前后 revision、恢复验证、RPO、RTO 和后续问题。

发布与数据库回滚命令见 [`release-and-rollback.md`](release-and-rollback.md)。
