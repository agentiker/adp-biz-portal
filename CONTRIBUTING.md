# 贡献指南

感谢你为企业 AI 业务接入平台贡献代码、文档或问题反馈。

## 开始之前

- 阅读 [README](README.md)、[开发说明](docs/development.md) 和 [公开路线图](docs/roadmap.md)。
- 涉及架构边界的改动先补充 `docs/architecture/` 或 `docs/plans/` 中的设计说明。
- 不提交真实凭据、客户数据、渠道 Token、服务器地址或内部运维记录。

## 提交改动

1. 为修复或功能建立分支，并说明用户可见的行为变化。
2. 保持 API、前端生成类型、迁移和文档同步。
3. 为权限、企业隔离、重放保护等安全边界补充有意义的测试。
4. 在提交前运行：

```bash
make platform_api_check
PYTHONPATH=backend backend/.venv/bin/python -m pytest backend/test/unit_test -q
cd frontend/packages/app && npm run type-check && npm run build-only
cd ../../.. && git diff --check
```

集成测试必须使用显式的隔离 PostgreSQL URL。Pull request 请写清变更、验证命令和已知限制。

## 报告问题

请提供最小复现步骤、脱敏日志、版本和运行环境。安全漏洞请按 [SECURITY.md](SECURITY.md) 私下报告，不要公开发布可利用细节。
