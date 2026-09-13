# adp-chat-component

腾讯 ADP 对话 UI 组件库（基于 TDesign Chat + SSE 流式 + Widget 渲染），由腾讯开源
[ADP Chat Client](https://github.com/TencentCloudADP/adp-chat-client) 派生而来。

在本仓库（ADP 业务统一网关）中，它已不再是对外可嵌入的 SDK，仅作为上游对话岛，
服务平台管理端的 ADP 调试页 `frontend/packages/app/src/pages/admin/AdminAdpChat.vue`。
导出面收敛为该页实际消费的部分：布局组件 `ADPChat`、axios 拦截器配置与少量类型
（见 `src/index.ts`）。

- 构建：`npm run build`（产出 ESM 库到 `dist/`，由 `frontend` 根构建脚本拷入 `backend/static/adp-chat-component`）。
- 组件 Props / Events / Slots / Methods 文档见 [`COMPONENTS.md`](./COMPONENTS.md)。
