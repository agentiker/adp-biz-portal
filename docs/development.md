# 开发指南

## 环境要求

- Python 3.12
- Node.js 22
- PostgreSQL 14 或更高版本
- [uv](https://docs.astral.sh/uv/)
- Docker（可选，用于 Compose 验证）

## 初始化

```bash
cd backend
uv sync --frozen
cp .env.example .env
cd ../frontend
npm ci --no-audit --no-fund
cd ..
```

在 `backend/.env` 中填写本机 PostgreSQL 连接和随机的平台密钥。不要把真实凭据、客户数据或渠道 Token 写入仓库。

## 迁移与运行

当前代码要求数据库 schema revision `21`。应用启动不会自动建表或升级 schema：

```bash
backend/.venv/bin/python backend/migrate.py upgrade --applied-by local-development
bash script/local-preview.sh
make run_worker
```

服务默认只监听 `http://127.0.0.1:8000`。本地管理员可以使用脚本创建，脚本支持通过环境变量覆盖账号信息：

```bash
backend/.venv/bin/python script/bootstrap-local-admin.py
```

详细的本地数据库、MCP 和渠道步骤见 [LOCAL_RUN.md](../LOCAL_RUN.md)。

## 验证

```bash
backend/.venv/bin/python -m pytest backend/test/unit_test -q
PLATFORM_TEST_DATABASE_URL='<isolated-postgres-url>' \
  backend/.venv/bin/python -m pytest backend/test/integration -q
cd frontend/packages/app
npm run type-check
npm run build-only
cd ../../..
make platform_api_check
git diff --check
```

集成测试必须使用隔离数据库和 schema，不能连接开发数据库。真实第三方联调需要单独的测试租户和凭据，不能用 Mock 结果代替。

## 代码结构和提交

新功能先确定所属模块和公开契约，权限判断放在服务端；新增 Provider 或 Connector 时同时补充能力声明、失败边界和脱敏日志。提交信息使用简短的命令式描述，Pull Request 说明行为变化、验证命令和剩余风险。
