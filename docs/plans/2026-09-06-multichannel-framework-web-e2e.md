# 多渠道框架与 Web 端到端验证实施计划

日期：2026-09-06

## 目标

先建立可复用的 `ChannelAdapter`/`ChannelSender` 边界和注册表，再用 Web 渠道证明入站、持久任务、Worker 编排、受控 Agent/M3 Provider、回复投递和 Portal 会话恢复可以闭环。

## 设计决策

- 适配器只处理协议字段验证、标准化和渠道能力声明；不接受客户端声明的企业、用户、权限或 Agent。
- 入站统一转换为 `InboundMessageInput`，沿用 PostgreSQL durable queue 的去重、租约、FIFO、重试和失败状态。
- 出站统一使用带稳定幂等键的 `OutboundMessage`，真实渠道 sender 可在未来按协议实现状态查询或 uncertain 语义。
- 适配器通过进程内注册表发现。当前模块化单体足够，暂不引入消息 broker 或独立微服务。
- 验签、解密、重放窗口和回复窗口是微信/企微协议专属能力，保留在后续适配器，不用 Web Mock 冒充真实联调。

## 安全与失败边界

平台服务在入站持久化和 Worker 执行前后重新加载账号、企业、membership、权限和会话；适配器输出的身份字段不是授权依据。结构化错误分为 rejected、retryable、uncertain、unsupported，避免把未知发送结果误报成功或无限重试。

## 实施与验收

1. 新增基础契约、能力元数据和注册表，Web 适配器实现该契约并保留现有兼容入口。
2. 增加入站状态查询接口，供 Portal 轮询 Worker 产生的服务端会话 ID 和回复状态。
3. Portal 查询优先走 Web 入站异步链路，完成后恢复同一会话详情；保留同步工具接口作为兼容路径。
4. 增加单元契约测试和 PostgreSQL 集成 E2E：重复消息、结果/证据恢复、回复投递、跨账号隔离和撤权拒发。
5. 运行定向测试、OpenAPI/前端类型检查、前端构建并更新公开路线图。真实微信/企微协议仍保持 TODO/BLOCKED。
