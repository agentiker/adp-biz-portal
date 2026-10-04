# 开源整理实施记录

日期：2026-10-04
对应路线图：`OSS-PUBLISH-01`
公开定位：企业 AI 业务接入平台

## 结果

- 新增 `docs/roadmap.md`、`docs/architecture/`、`docs/integrations/` 和 `docs/development.md` 公开入口。
- 重写根目录 README，并新增贡献、行为准则和安全策略。
- 将统一业务平台和扩展设计归档到 `docs/architecture/`。
- 用占位主机、环境变量和通用 Nginx 示例替换环境特有的运行说明。
- 删除根目录内部路线图、域名专用 Nginx 配置和内部部署技能文件。
- 保留历史方案，但移除其中的服务器地址、部署路径、测试账号、手机号和生产联调记录。
- 更新文档链接、协作规范和本地管理员示例，使其匹配当前 `backend/`、`frontend/` 目录。

## 验证

- `make platform_api_check`：OpenAPI 56 operations、62 schemas，有效。
- `PYTHONPATH=backend backend/.venv/bin/python -m compileall -q backend`：通过。
- `pytest test_extensibility_registry.py test_agent_provider.py test_legacy_binding.py -q`：16 passed。
- 前端 `npm run type-check`：通过。
- 前端 `npm run build-only`：通过。
- `git diff --check`：通过。
- Markdown 相对链接检查：0 个缺失链接。
- 敏感信息扫描：未发现生产域名、部署路径、服务器账号或凭据。
- 全量后端单元测试在未配置隔离 PostgreSQL 时无法完成；测试环境应按 README 提供隔离数据库 URL。

## 公开边界

本次整理只改变文档组织、开源入口和示例边界，不宣称真实 CRM、M3、ADP 或渠道联调完成。相关工作仍以外部文档、测试租户和权限为前提。
