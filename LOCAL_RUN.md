# 本地运行说明

官方项目已浅克隆到本目录。使用本机 Python 3.12、Node.js 22 和 PostgreSQL，未启动 Docker。

## 启动

首次启动或代码升级后，先用部署账号执行版本化数据库迁移。应用进程不会在启动时建表，也不会自动升级 schema：

```bash
server/.venv/bin/python server/migrate.py upgrade --applied-by local-migration
```

迁移命令可重复执行；当前代码要求 schema revision `12`。需要回滚时必须明确确认会删除目标 revision 创建的表和数据：

```bash
server/.venv/bin/python server/migrate.py downgrade --target 3 --allow-data-loss --applied-by local-rollback
```

回滚后重新执行 `upgrade`，再启动应用。若忘记迁移，服务会在启动阶段拒绝运行并提示上述命令。

在项目目录运行：

```bash
bash script/local-preview.sh
```

服务只监听 http://127.0.0.1:8000，不对局域网公开。按 Ctrl+C 停止。

启动统一业务接入平台 Worker（需要先完成数据库迁移）：

```bash
make run_worker
```

Worker 从 PostgreSQL 消费 `platform.inbound.process` 和 `platform.reply` 任务。仅处理一条任务后退出可运行：

```bash
cd server
./.venv/bin/python worker.py --once
```

Worker 默认使用受控的 M3 Provider。只有显式设置 `M3_USE_MOCK=true` 才会使用本地 fixture；未配置 `M3_BASE_URL` 且未启用 Mock 时，任务会持久化为 `upstream_error`，不会伪造业务结果。

在另一个终端打开并登录本地预览账号：

```bash
server/.venv/bin/python script/open-local-preview.py
```

采用官方签名登录流程，链接有效期 60 秒。预览账号为 local-preview，未开放匿名注册。

创建或刷新可登录平台管理端的本地 admin 账号：

```bash
server/.venv/bin/python script/bootstrap-local-admin.py
```

账号引导脚本只负责账号数据，不负责建表；必须先完成上面的迁移步骤。

默认凭据为手机号 `13900000000`、口令 `123456`。脚本只接受回环地址上的 PostgreSQL，重复执行会刷新该账号的 admin 角色、口令和登录状态，不会创建重复账号。可通过 `LOCAL_ADMIN_NAME`、`LOCAL_ADMIN_PHONE`、`LOCAL_ADMIN_PASSWORD` 环境变量覆盖默认值。

## 配置真实 ADP 应用

编辑 server/.env（已被 Git 忽略，文件权限为 600）：

- 公有云：填写 TC_SECRET_ID、TC_SECRET_KEY，以及 APP_CONFIGS 中的 ApplicationId 和 AppKey。
- 独立站：设置 ServiceVendor=ChinaTencentADP，并填写 ADP_SECRET_ID / ADP_SECRET_KEY。
- 启用统一业务 Worker 的真实 ADP Agent 时，额外设置 `ADP_AGENT_CONFIGS`，例如：
  `ADP_AGENT_CONFIGS='[{"agentId":"shipment-agent","applicationId":"server-configured-app-id"}]'`。
  `applicationId` 必须同时存在于服务端 `APP_CONFIGS`，并且对应 Vendor 必须支持 `chat`；多个映射时必须设置 `ADP_DEFAULT_AGENT_ID`。
  这些映射由服务端配置维护，客户端请求中的 `agentId` 不参与授权，也不能切换应用。
- TC_SECRET_APPID、COS、语音等按实际需要配置；本次不主动开通任何付费服务。
- 初始 APP_CONFIGS=[]，可以启动界面，但没有可用智能体，不能进行真实聊天。
- 不要将密钥提交 Git、贴到聊天里或放入截图。

未配置 `ADP_AGENT_CONFIGS` 时，Worker 使用受控 M3 Provider；这只用于本地 M3 契约/Mock 验证。
配置映射但应用、Vendor 或 Agent 选择不合法时，Worker fail closed 并持久化 `upstream_error`，不会回退到模拟结果。

保存配置后重启后端，再运行登录脚本。正常启动时项目会访问 ADP 获取应用信息；错误配置可能导致启动失败。

## 数据与日志

- 独立数据库和专用非超级用户：adp_chat_client_local。
- 数据库凭据只在 server/.env 中；没有修改既有业务数据库。
- 日志：server/logs/server.log。分享日志前注意脱敏。
- 数据库由本机现有 PostgreSQL 服务提供，本项目不会自动停止该共享服务。

## 构建与依赖

```bash
cd server
uv sync --frozen
cd ../client
npm ci --no-audit --no-fund
npm run build
```

官方初始 Python 锁文件缺少源码需要的 pydash、COS SDK 等已声明依赖，已通过 uv sync 更新 server/uv.lock。
页面未加入模拟模型、模拟回答或模拟 M3 数据。
