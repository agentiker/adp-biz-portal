# 本地运行说明

官方项目已浅克隆到本目录。使用本机 Python 3.12、Node.js 22 和 PostgreSQL，未启动 Docker。

## 启动

首次启动或代码升级后，先用部署账号执行版本化数据库迁移。应用进程不会在启动时建表，也不会自动升级 schema：

```bash
backend/.venv/bin/python backend/migrate.py upgrade --applied-by local-migration
```

迁移命令可重复执行；当前代码要求 schema revision `16`。需要回滚时必须明确确认会删除目标 revision 创建的表和数据：

```bash
backend/.venv/bin/python backend/migrate.py downgrade --target 3 --allow-data-loss --applied-by local-rollback
```

回滚后重新执行 `upgrade`，再启动应用。若忘记迁移，服务会在启动阶段拒绝运行并提示上述命令。

在项目目录运行：

```bash
bash script/local-preview.sh
```

服务只监听 http://127.0.0.1:8000，不对局域网公开。按 Ctrl+C 停止。

启动统一业务接入平台 Worker（需要先完成数据库迁移）：

```bash
make run_worker
```

Worker 从 PostgreSQL 消费 `platform.inbound.process` 和 `platform.reply` 任务。仅处理一条任务后退出可运行：

```bash
cd backend
./.venv/bin/python worker.py --once
```

Worker 按企业从数据库解析 ADP 应用。工具数据只有显式设置 `M3_USE_MOCK=true` 才使用固定 Mock；这不会替代 ADP 应用。未配置可用应用时拒绝执行。

在另一个终端打开并登录本地预览账号：

```bash
backend/.venv/bin/python script/open-local-preview.py
```

采用官方签名登录流程，链接有效期 60 秒。预览账号为 local-preview，未开放匿名注册。

创建或刷新可登录平台管理端的本地 admin 账号：

```bash
backend/.venv/bin/python script/bootstrap-local-admin.py
```

账号引导脚本只负责账号数据，不负责建表；必须先完成上面的迁移步骤。

默认凭据为手机号 `13900000000`、口令 `123456`。脚本只接受回环地址上的 PostgreSQL，重复执行会刷新该账号的 admin 角色、口令和登录状态，不会创建重复账号。可通过 `LOCAL_ADMIN_NAME`、`LOCAL_ADMIN_PHONE`、`LOCAL_ADMIN_PASSWORD` 环境变量覆盖默认值。

## 配置真实 ADP 应用

在管理后台「ADP 应用配置」录入应用 ID、AppKey、SecretAppId、SecretId 和 SecretKey，选择实际 Vendor/ServiceVendor 并启用，设为平台默认或在企业中明确绑定。业务运行不再读取 `.env` 默认应用；显式绑定停用时不会切换到其它应用。

`backend/.env` 保留数据库、平台密钥、`PLATFORM_CHANNEL_CREDENTIAL_KEY`、旧内部适配器使用的 `ADP_TOOL_SERVICE_TOKEN` 等基础设施配置（不用于 shipment 连接器工具；连接器 Key 在 Admin「开放接口」创建、查看和复制，需迁移 revision 18）。`APP_CONFIGS=[]` 可为空，仅旧管理员调试入口使用。不要把真实密钥提交 Git 或贴到日志、截图中。

固定 M3 Mock、测试企业和连接器设置见 [ADP/M3 联调说明](docs/plans/2026-09-16-adp-m3-mock-connector.md)。正常业务查询需要可用的数据库 ADP 应用以及云端连接器回调；没有工具回执时返回失败提示。

## 数据与日志

- 独立数据库和专用非超级用户：adp_chat_client_local。
- 数据库凭据只在 backend/.env 中；没有修改既有业务数据库。
- 日志：backend/logs/server.log。分享日志前注意脱敏。
- 数据库由本机现有 PostgreSQL 服务提供，本项目不会自动停止该共享服务。

## 构建与依赖

```bash
cd backend
uv sync --frozen
cd ../frontend
npm ci --no-audit --no-fund
npm run build
```

官方初始 Python 锁文件缺少源码需要的 pydash、COS SDK 等已声明依赖，已通过 uv sync 更新 backend/uv.lock。
M3 固定 Mock 仅供显式启用的联调环境使用；真实联调进度以 ROADMAP 为准。
