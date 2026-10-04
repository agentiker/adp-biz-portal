# 企业 AI 业务接入平台

<p align="center">
  <img src="docs/assets/readme-hero.svg" alt="企业 AI 业务接入平台：连接渠道、AI Provider、MCP 工具与企业业务系统" width="100%" />
</p>

<p align="center">
  <strong>Enterprise AI Business Integration Platform</strong><br />
  面向企业业务系统的 AI 接入层，让 AI 安全连接身份、权限与业务事实。
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-8b5cf6?style=flat-square" alt="Apache-2.0 License" /></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.12-3776ab?style=flat-square&logo=python&logoColor=white" alt="Python 3.12" /></a>
  <a href="https://vuejs.org/"><img src="https://img.shields.io/badge/vue-3.x-42b883?style=flat-square&logo=vuedotjs&logoColor=white" alt="Vue 3" /></a>
  <a href="https://www.typescriptlang.org/"><img src="https://img.shields.io/badge/typescript-5.x-3178c6?style=flat-square&logo=typescript&logoColor=white" alt="TypeScript" /></a>
  <a href="https://www.postgresql.org/"><img src="https://img.shields.io/badge/postgresql-14%2B-4169e1?style=flat-square&logo=postgresql&logoColor=white" alt="PostgreSQL 14 or later" /></a>
  <a href="https://www.docker.com/"><img src="https://img.shields.io/badge/docker-compose-2496ed?style=flat-square&logo=docker&logoColor=white" alt="Docker Compose" /></a>
  <a href="https://modelcontextprotocol.io/"><img src="https://img.shields.io/badge/MCP-enabled-6d5dfc?style=flat-square" alt="MCP enabled" /></a>
</p>

面向企业业务系统的 AI 接入层：统一管理企业、成员、权限和会话，把 AI 应用安全连接到 CRM、订单、物流等业务数据。平台同时提供管理后台、Portal、异步任务、审计、MCP/HTTP 工具和多渠道适配能力。

## 平台能力

<table>
  <tr>
    <td width="33%" valign="top"><strong>🌐 多渠道接入</strong><br />Web、微信服务号、微信客服和企业微信适配器共享统一的身份与会话边界。</td>
    <td width="33%" valign="top"><strong>🛡️ 企业级权限</strong><br />服务端验证用户、企业成员关系、角色、数据范围和执行上下文。</td>
    <td width="33%" valign="top"><strong>⚡ MCP 与业务工具</strong><br />通过 MCP 和 HTTP 工具把 ADP、CRM、订单与 M3 连接到可审计的业务事实。</td>
  </tr>
</table>

## 核心能力

- 企业与成员身份、角色和数据范围；
- ADP Provider 配置与可扩展的 CRM/AI 服务连接器边界；
- MCP 与 OpenAPI 工具调用，服务端执行上下文和防重放校验；
- Web、微信服务号、微信客服和企业微信适配器框架；
- PostgreSQL 持久化、异步 Worker、幂等投递和审计；
- Vue 管理后台、客户 Portal、Docker Compose 本地运行基线。

## 架构

```mermaid
flowchart LR
  C[Web / 微信 / 企业微信] --> A[渠道适配器]
  A --> I[身份与企业范围]
  I --> W[Worker / 执行上下文]
  W --> L[ADP Provider]
  W --> T[MCP / HTTP 工具]
  T --> B[CRM / 订单 / M3]
  I --> D[(PostgreSQL)]
  W --> D
```

平台负责身份、权限、上下文、任务和审计；上游业务系统负责业务数据；AI Provider 负责对话编排。工具调用的企业范围由服务端验证，不能由模型参数或提示词决定。

## 目录

```text
backend/                         Python API、领域模型、集成和 Worker
frontend/packages/app/           Vue 3 管理后台与 Portal
frontend/packages/adp-chat-component/  对话组件
docs/architecture/               架构与扩展边界
docs/integrations/               MCP、ADP 和外部系统接入说明
docs/api/                        OpenAPI 契约
docs/operations/                 通用运行与排障手册
docs/plans/                      历史方案和实施记录
docs/roadmap.md                  公开路线图
docker-compose.yml               本地单机运行基线
```

## 快速开始

要求 Python 3.12、Node.js 22、PostgreSQL 14+ 和 uv。复制环境模板并只填写本地配置：

```bash
cp docker/.env.example .env
cd backend && uv sync --frozen
cd ../frontend && npm ci --no-audit --no-fund
cd ..
docker compose config
docker compose up -d
curl http://127.0.0.1:8000/healthz
curl http://127.0.0.1:8000/readyz
```

也可以按 [LOCAL_RUN.md](LOCAL_RUN.md) 使用本地 Python 进程启动 API 和 Worker。首次使用时通过 `script/bootstrap-local-admin.py` 创建本地管理员。所有密码、密钥和业务数据都应使用隔离的开发值，不能提交到 Git。

## ADP、MCP 与业务工具

在管理后台配置 ADP Provider、加密凭据和企业绑定。MCP 接入地址为 `https://<host>/mcp`；API Key 在“开放接口”页面创建并配置到客户端。工具只接受业务查询参数，可信客户端还需传递平台执行上下文 Header。完整协议、Header 映射、错误边界和 Mock 说明见 [MCP 与 ADP 接入](docs/integrations/mcp-and-adp.md)。

HTTP 工具 OpenAPI 定义见 [docs/api/adp-tools.openapi.yaml](docs/api/adp-tools.openapi.yaml)。固定 M3 Mock 只用于隔离环境和自动化验证，设置 `M3_USE_MOCK=true` 才启用；它不代表真实 M3、ADP 或渠道已经完成联调。

## 测试

```bash
make platform_api_check
PYTHONPATH=backend backend/.venv/bin/python -m pytest backend/test/unit_test -q
cd frontend/packages/app && npm run type-check && npm run build-only
cd ../../.. && git diff --check
```

集成测试必须显式提供隔离 PostgreSQL URL，例如：

```bash
PLATFORM_TEST_DATABASE_URL='postgresql+asyncpg://user:password@127.0.0.1:5432/adp_biz_portal_test' \
  PYTHONPATH=backend backend/.venv/bin/python -m pytest backend/test/integration -q
```

## 当前边界

本仓库提供可运行的平台骨架、Mock 和本地验证链路。正式 CRM、M3、云厂商 ADP、微信/企微账号、生产备份恢复、压测和监控接入需要各自的第三方文档、租户、权限与验收，不能以本地 Mock 或单元测试替代。公开进度见 [docs/roadmap.md](docs/roadmap.md)。

## 参与和安全

欢迎提交 Issue、文档和代码，参见 [CONTRIBUTING.md](CONTRIBUTING.md) 与 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)。安全问题请按 [SECURITY.md](SECURITY.md) 私下报告。项目使用 Apache License 2.0，见 [LICENSE](LICENSE)。
