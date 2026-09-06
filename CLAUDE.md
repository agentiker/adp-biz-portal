# Claude 工作规范

本仓库的统一业务接入平台进度以根目录 `ROADMAP.md` 为准，方案背景和验收原则见 `docs/plans/2026-09-04-unified-business-platform-design.md`。

执行相关工作时：

- 先从 `ROADMAP.md` 选择一个明确的 TODO 编号；没有编号就先补充 TODO。
- 开始时标记 `IN PROGRESS`，完成实现、测试或验收后立即标记 `DONE`，同时写入日期、证据和剩余风险。
- 缺少真实 M3/ADP/微信资料、账号、权限或数据时标记 `BLOCKED`，不可把 Mock 或本地测试当成真实联调结果。
- 每次完成 TODO 必须在同一变更中更新 `ROADMAP.md`；新增依赖、回归或范围变化也必须同步记录。
- 后端测试使用 `server/.venv/bin/pytest`；集成测试必须显式指定测试数据库并使用隔离 schema。
- 不提交真实凭据或客户数据，不用前端隐藏按钮、提示词或客户端字段作为服务端授权。
