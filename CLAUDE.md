本仓库的公开进度以 [docs/roadmap.md](docs/roadmap.md) 为准，架构背景见 [docs/architecture/](docs/architecture/)。

执行工作时：

- 先从公开路线图选择一个明确的 TODO 编号；没有编号就先补充。
- 开始时标记 `IN PROGRESS`，完成实现、测试或验收后标记 `DONE`，同步记录证据和限制。
- 缺少真实 M3、ADP、CRM 或渠道资料、账号、权限和数据时标记 `BLOCKED`，不可把 Mock 或本地测试当成真实联调结果。
- 后端测试使用 `backend/.venv/bin/pytest`；集成测试必须显式指定测试数据库并使用隔离 schema。
- 不提交真实凭据或客户数据，不用前端隐藏按钮、提示词或客户端字段作为服务端授权。
