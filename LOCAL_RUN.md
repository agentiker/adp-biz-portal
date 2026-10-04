# 本地运行

本文介绍如何在本机启动 API、Worker 和前端开发环境。所有凭据和数据库只用于隔离开发环境。

## 依赖

- Python 3.12 与 uv
- Node.js 22 与 npm
- PostgreSQL 14+

## 安装与迁移

```bash
cd backend
uv sync --frozen
cp .env.example .env
# 编辑 .env，填写本地 PostgreSQL、SECRET_KEY 和加密密钥
backend/.venv/bin/python migrate.py upgrade --applied-by local
cd ../frontend
npm ci --no-audit --no-fund
cd ..
```

也可以直接使用根目录 Docker Compose：

```bash
cp docker/.env.example .env
docker compose up -d
curl http://127.0.0.1:8000/healthz
curl http://127.0.0.1:8000/readyz
```

## 启动服务

```bash
bash script/local-preview.sh
make run_worker
```

前端和 API 的本地地址以终端输出为准，默认 API 为 `http://127.0.0.1:8000`。首次创建管理员：

```bash
backend/.venv/bin/python script/bootstrap-local-admin.py \
  --phone 10000000000 --password '<local-only-password>'
```

也可以通过 `LOCAL_ADMIN_PHONE`、`LOCAL_ADMIN_PASSWORD` 和 `LOCAL_ADMIN_NAME` 传入本地值。请勿复用生产口令或把本地口令写入仓库。

## Mock 与测试

M3 固定 Mock 只在显式设置 `M3_USE_MOCK=true` 的隔离环境使用；Mock 结果不代表真实 M3 或 ADP 联调。

```bash
make platform_api_check
PYTHONPATH=backend backend/.venv/bin/python -m pytest backend/test/unit_test -q
cd frontend/packages/app
npm run type-check
npm run build-only
```

集成测试必须提供隔离 PostgreSQL URL 和 schema：

```bash
PLATFORM_TEST_DATABASE_URL='postgresql+asyncpg://user:password@127.0.0.1:5432/adp_biz_portal_test' \
  PYTHONPATH=backend backend/.venv/bin/python -m pytest backend/test/integration -q
```

## 日志和停止

本地日志可能包含业务调试信息，分享前应脱敏。停止 Compose 服务：

```bash
docker compose down
```

迁移降级会删除目标版本创建的数据，只能在隔离数据库中执行并明确提供 `--allow-data-loss`。
