# 公开路线图

本路线图面向开源用户，只记录可公开讨论的能力方向。真实第三方接入需要对应厂商的正式文档、测试租户、凭据和脱敏样本；本地 Mock、契约测试和示例数据不能替代真实验收。

更新时间：2026-10-04

## 当前状态

### 开源项目呈现

- `OSS-README-02`（2026-10-04，DONE）：为企业 AI 业务接入平台加入深色科技感 README 主视觉、真实技术徽章和静态能力导航；新增 `docs/assets/readme-hero.svg` 与设计记录 `docs/plans/2026-10-04-readme-visual-identity-design.md`，更新 `README.md`；GitHub 仓库描述、Topics 和 Issue Labels 已同步。验证：`xmllint --noout docs/assets/readme-hero.svg`、`git diff --check`、README 本地链接与资源检查通过。

### 已具备

- 平台用户、企业、成员关系、角色、权限和审计模型。
- Web Portal、管理后台、异步 Worker、持久化投递任务和幂等边界。
- ADP Provider 注册表、数据库应用配置和加密凭据存储。
- M3 只读工具适配器、固定 Mock、企业范围过滤和结构化证据结果。
- Streamable HTTP MCP，支持工具发现、工具调用、API Key 和执行上下文校验。
- 渠道适配器基础设施，以及 Web、微信和企业微信的协议层实现。
- Docker Compose、本地迁移 CLI、OpenAPI 文档和健康检查。

### 进行中

- 完善多渠道真实身份绑定、重放保护和发送协议的公开示例。
- 增加可替换的 CRM Connector 示例和同步游标策略。
- 补充发布、备份恢复、观测和压测的可复现开发环境。
- 改善管理后台的配置向导、错误提示和移动端体验。

### 需要外部条件

- 真实 M3 API、字段归属规则、限流和测试数据。
- ADP 厂商的测试应用、工具调用权限和回调样本。
- 微信/企业微信等渠道的测试账号、协议权限和发送样本。
- 阿里云、火山引擎 ADP 的正式 API 和签名文档。

## 近期计划

1. 发布一套脱敏的 CRM Connector 参考实现，并完成同步失败恢复演练。
2. 为 Provider 能力声明、健康检查和错误转换补充公共扩展指南。
3. 增加示例渠道适配器和端到端测试夹具，覆盖重复消息、撤权和未知发送结果。
4. 建立可选的观测插件接口，支持日志、指标和追踪系统按部署环境接入。

## 不在当前范围

- 将所有厂商的协议强行统一为同一套内部字段。
- 在平台中保存或分发客户业务数据、生产凭据或渠道 Token。
- 用模型提示词、前端隐藏按钮或客户端字段实现企业数据权限。

## 参与路线图

欢迎通过 Issue 讨论需求，通过 Pull Request 提交实现。涉及外部服务的提案请同时提供公开文档链接、脱敏请求/响应样本和失败边界；无法公开的凭据和客户数据请不要提交到仓库。

## 迁移记录

- `OSS-PUBLISH-01`（2026-10-04，DONE）：将内部根目录路线图的公开部分迁移到本文，架构、接入、开发和运维说明分别归档到 `docs/architecture/`、`docs/integrations/`、`docs/development.md` 和 `docs/operations/`；根目录 `ROADMAP.md` 已移除。验证：`make platform_api_check`、`backend/.venv/bin/python -m compileall -q backend`、前端 `npm run type-check`、`npm run build-only`、`git diff --check` 和公开文档链接检查通过；完整后端单元测试因未提供本地 PostgreSQL（默认连接为 None:5433）未能全量通过，数据库相关用例需按 README 使用隔离 URL 执行。敏感信息扫描未发现生产域名、部署路径、服务器账号或凭据。
