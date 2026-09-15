# ADP 业务统一网关

面向货代业务的统一接入平台。项目基于腾讯云 ADP Chat Client 二次开发，提供管理后台、客户 Portal、企业与权限模型、异步 Worker、审计，以及微信服务号、微信客服和企业微信机器人渠道适配。

## 架构与边界

```text
官网 / 微信 / 企业微信 -> 渠道适配 -> 身份与权限 -> Worker
                                      |              |
                                  企业范围       ADP Agent
                                                     |
                                                   M3 查询
```

平台负责身份、企业范围、权限、会话、投递、重试和审计；ADP 负责智能体对话；M3 是订单、提单、箱号、船期等业务数据的权威来源。权限由服务端校验，密钥不会发送到浏览器。

## 当前状态

详细进度见 [`ROADMAP.md`](ROADMAP.md)。本地已覆盖管理后台、Portal、任务队列、幂等与撤权失效、ADP/M3 受控 Provider、Web/微信协议基础、PostgreSQL 迁移、Docker Compose、OpenAPI 和运维文档。真实 M3 数据、ADP Agent、部分渠道账号与协议、生产备份恢复和正式压测仍需专项验收；Mock 不代表真实联调。

## 目录

- `backend/`：Python 3.12 + Sanic 后端；`router` 为 HTTP 入口，`core` 为平台业务，`model` 为数据模型，`integrations` 为 ADP/M3/渠道适配器，`worker.py` 为异步任务进程。
- `frontend/packages/app/`：Vue 3 + TypeScript 主应用，包含登录、Portal、Admin 和共享结果页。
- `frontend/packages/adp-chat-component/`：ADP 对话组件。
- `docs/`：方案、OpenAPI 和运维文档。
- `docker-compose.yml`：PostgreSQL、迁移、API、Worker、企微 WebSocket 网关和 Nginx。

## 本地运行

要求 Python 3.12、Node.js 22、PostgreSQL 14+ 和 uv。创建 `backend/.env`，配置数据库、`SECRET_KEY` 和 `PLATFORM_CHANNEL_CREDENTIAL_KEY`；ADP 应用及其凭据在管理后台录入。请勿提交真实凭据或客户数据。

```bash
cd backend && uv sync --frozen
cd ../frontend && npm ci --no-audit --no-fund
cd ..
backend/.venv/bin/python backend/migrate.py upgrade --applied-by local-migration
bash script/local-preview.sh
make run_worker
```

预览地址：<http://127.0.0.1:8000>。创建本地管理员：

```bash
backend/.venv/bin/python script/bootstrap-local-admin.py
```

默认开发账号为 `13900000000` / `123456`，仅用于本机。

## Docker 部署

准备项目根目录 `.env` 后执行：

```bash
docker compose config
make pack
make deploy
docker compose ps
curl http://127.0.0.1:8000/healthz
curl http://127.0.0.1:8000/readyz
```

生产环境应使用 HTTPS、受限数据库账号、备份和可回滚迁移流程，见 [`docs/operations/release-and-rollback.md`](docs/operations/release-and-rollback.md)。

## ADP 配置

业务 Worker 和企微 Bot 使用数据库「ADP 应用配置」：优先选择企业绑定的启用应用，未绑定时使用启用的平台默认应用。显式绑定失效或没有可用应用时拒绝执行，不回退到服务器 `.env`。客户端的 `agentId`、`ApplicationId` 和 `WorkspaceId` 不参与授权。

在管理后台录入应用 ID、AppKey 和每个应用自己的腾讯云签名凭据，再设为默认或绑定企业。`APP_CONFIGS` 仅供旧管理员调试入口使用，可以保持 `[]`；数据库、加密密钥和工具服务 Token 等基础设施仍由环境变量配置。

已提供订单/提单/箱号、船期、节点三个 HTTP 工具连接器。固定 Mock 和 ADP 参数映射见 [联调说明](docs/plans/2026-09-16-adp-m3-mock-connector.md)，导入文件为 [adp-tools.openapi.yaml](docs/api/adp-tools.openapi.yaml)。Mock 只在显式设置 `M3_USE_MOCK=true` 时启用，不能代替真实 ADP/M3 验收。

## 测试与检查

```bash
backend/.venv/bin/python -m pytest backend/test/unit_test -q
PLATFORM_TEST_DATABASE_URL='postgresql+asyncpg://user:password@127.0.0.1:5432/test_db' backend/.venv/bin/python -m pytest backend/test/integration -q
cd frontend/packages/app && npm run type-check && npm run build-only
cd ../../.. && make platform_api_check
git diff --check
```

集成测试必须使用隔离的 PostgreSQL URL，不能误写开发数据库。

## 相关文档

- [总体方案](docs/plans/2026-09-04-unified-business-platform-design.md)
- [ROADMAP](ROADMAP.md)
- [OpenAPI 维护说明](docs/api/README.md)
- [数据字典](docs/operations/platform-data-dictionary.md)
- [排障手册](docs/operations/troubleshooting.md)
- [本地运行说明](LOCAL_RUN.md)

## 安全与许可证

`backend/.env` 和部署环境变量属于机密配置。日志、测试夹具和截图不得包含真实凭据、订单或渠道 Token。项目采用 Apache License 2.0，详见 [`LICENSE`](LICENSE)。
