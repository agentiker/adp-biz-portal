# 多渠道适配参考调研与借鉴方案

- 日期：2026-09-08
- 关联：[docs/roadmap.md](../roadmap.md) M3；[统一业务接入平台方案](../architecture/unified-business-platform.md)；[Admin 渠道管理设计](2026-09-06-admin-channel-management-design.md)
- 基线提交：本仓库 `53a6d5e`（`backend/integrations/channels/` + `core/channel_replay.py` + `core/channel_identity.py`）

## 1. 目的与范围

评估三个开源项目，确定我们统一业务接入平台「多渠道接入适配」层可借鉴的具体特性；同时评估我们现有渠道适配结构是否合理、是否需要重构成一等包。**只聚焦多渠道适配**（协议验签/解密、消息标准化、入站/出站、凭据、身份、幂等、重放），不评估其 LLM/插件生态等无关部分。

参考项目（克隆于 `ref-repos/`，已在 `.gitignore`）：

| 项目 | 版本 | 形态 | 许可证 |
|---|---|---|---|
| openclaw-china | `2026.3.9-1`（单 squash 提交 `4d6fd54`） | TS 插件集，给宿主 OpenClaw 加中国 IM 渠道 | MIT |
| AstrBot | v4.28.0 @ `a412146401426c0cd` | Python 聊天机器人框架 | 见其仓库 |
| LangBot | v4.10.10 @ `267232c`（基类在 sibling SDK `langbot-plugin==0.5.7`） | Python 聊天机器人框架 | Apache-2.0 |

## 2. 决策（ADR 式）：不迁宿主，库级借鉴

**结论：保持我们平台为宿主，把参考项目当参考实现 + 可 vendored 的窄层借鉴；不基于 LangBot 做「迁宿主」式二次开发。**

理由：

- **重心不同**：LangBot/AstrBot 的核心价值是「IM 连接 + LLM pipeline + bot 托管」——正是我们不要的部分（我们的 Agent 是 ADP，不是它们的 LLM 管线）。我们的核心是「B2B 企业业务网关 + 强隔离 + ADP/M3 业务执行」。
- **迁宿主要覆盖它们的绝大多数核心**：LLM pipeline、内存队列、明文凭据、其多租户模型、登录/角色、web/API/DB 模型——要么闲置要么与我们已交付且已上线的 M1/M2/M4 冲突。
- **会继承技术债**：非持久队列、明文凭据、弱 token、回放保护缺失，以及调研查到的真 bug（客服 `sync_msg` 丢批、`bot_account_id` 被入站流量改写误路由、缺 `await`）。
- **接口不稳定**：LangBot 基类在独立 SDK（我们不控），且正重写为 EBA（event-based agents），依赖它等于绑移动靶。
- 许可证不是障碍：LangBot 为 Apache-2.0，可商业闭源二次开发，仅需保留 NOTICE。选择库级借鉴纯粹出于工程/产品适配度。

## 3. 我们已具备/已领先（不再借鉴，避免重复造轮子）

以 `53a6d5e` 为准，下列能力已实现且相对三家领先：

| 能力 | 现状（公开路线图项目） | 相对三家 |
|---|---|---|
| 适配器 ABC + 注册表 + 能力声明 | `M3-FRAMEWORK-01` DONE：`integrations/channels/base.py` `ChannelAdapter`/`ChannelSender`/`ChannelCapabilities`；`registry.py`（显式注册/拒重复/失败关闭） | 强于 AstrBot（2 布尔能力）、LangBot（`hasattr` 探测） |
| 公众号明文+安全模式验签/解密 | `M3-WECHAT-OA-01` DONE：SHA-1 常量时间比较、AES-256-CBC/32 字节填充、解密后 AppID 校验、XML 大小/DTD/实体拒绝 | 强于 AstrBot（无条件解密，明文抛错） |
| **跨进程重放保护** | `M3-VERIFY-01`：`core/channel_replay.py` `(Channel,ChannelInstanceId,ReplayKey)` DB 唯一约束，跨实例 | **三家全缺** |
| 凭据加密/轮换/脱敏 | `M3-CRED-01` DONE：Fernet 加密、旧密钥只读轮换、掩码、审计 | 强于三家（均明文落库） |
| 两方渠道身份绑定 + 未绑定 ack 语义 | `M3-IDENTITY-01`：一次性 `pci_` 码被身份流消费不落库、未绑定发送者 200+被动引导、活跃身份部分唯一索引、回复拒绝 `]]>`/控制字符 | 三家全无身份绑定概念 |
| Admin 渠道管理 UI | `M3-ADMIN-01` DONE：能力状态、凭据增/轮换/停用、回调地址、身份撤销 | 有 UI；仅声明式配置清单可选增强 |
| durable 幂等 `(ChannelInstanceId, ExternalMessageId)` | 已有 | 强于三家进程内 dict |

## 4. 三方横向对比（多渠道适配维度）

| 维度 | openclaw-china | AstrBot | LangBot |
|---|---|---|---|
| 中文渠道覆盖 | 公众号/客服/企微机器人/企微自建/钉钉/QQ | 公众号/企微应用+客服/企微机器人/飞书/QQ | 公众号/企微/企微客服/企微机器人/飞书/QQ官方 |
| 适配器抽象 | 宿主 `ChannelPlugin`（~15 字段，偏单租户桌面） | `Platform`+`AstrMessageEvent`；能力=2 布尔 | SDK `AbstractMessagePlatformAdapter`；能力=可选方法默认值 |
| 统一 webhook 入口 | 无（每 account 一路由） | `/webhook/{uuid}`（线性扫描） | `/bots/{uuid}` + fail-closed（最佳） |
| 适配器拥有响应体 | 部分 | `webhook_response_from_result` | router 原样返回（最佳） |
| 公众号 5s 问题 | 竞速+**客服消息主动兜底**（最完整） | 竞速+MsgId 区分重试/新问（思路最好） | `drop` 轮询 4.8s；**无客服消息能力** |
| 客服 sync_msg | **cursor 正确**（先 ack/存 cursor/首启 drain） | 只取 `[-1]` 丢批（bug） | 只取 `[-1]` 且不用 cursor（bug） |
| access token | 主动刷新+退避+errcode 集（最佳） | 各适配器自理 | 最差（无 TTL/无锁/漏 40001） |
| 凭据隔离/多租户 | 单进程 JSON 明文 | 无多租户，全局明文单文件 | 真多租户 + placement 栅栏（仍明文落库） |
| 持久队列 | 无 | 内存 asyncio.Queue | 内存 QueryPool |
| 渠道身份绑定 | 无（甩给宿主未实现） | 无 | 无 |
| 明文/兼容模式入站 | `plain/safe/compat` 自动探测 | 无条件解密 | 公众号 GET 不解密（对） |
| 回放保护 | 无 | 无 | 无 |

选型口径：**渠道协议细节**看 openclaw-china；**平台层结构**看 LangBot；AstrBot 取「MsgId 区分重试/新问」「媒体自解析 + 组件日志脱敏」两点。三家的持久化/幂等/凭据隔离/身份绑定都弱于我们，属护城河，不回退。

## 5. 借鉴清单（归口到 公开路线图未完成 TODO）

真实缺口核实：代码里**无 access token 处理**（无 `cgi-bin/token`、无客服消息/custom send），公众号无发送传输时返 `uncertain`。故「真实主动发送」整条链路为空，是借鉴主要落点。

### → `M3-WECHAT-CS-01` 微信客服适配器（TODO，最高价值）
- 抄 openclaw `wecom-kf` 的 **cursor 拉取**（`ref-repos/openclaw-china/extensions/wecom-kf/src/webhook.ts`）：验签→**先返 `200 success` 再干活**→`sync_msg` 持久化 cursor（键 `${accountId}:${openKfId}`）→**投递前先存 `next_cursor`**→首启 `primeWecomKfCursor` drain 历史。
- 反例（勿抄）：AstrBot `wecom_adapter.py` 与 LangBot 客服都是 `while has_more` 只取 `msg_list[-1]`，丢批。
- 会话作用域：抄 LangBot `get_launcher_id` 思路，但**做成我们 `ChannelAdapter` 的真 ABC 方法**（现 base 无会话键钩子），键用 `open_kfid|external_userid`。
- cursor 存我方 DB，复用现有 durable 语义。

### → `M3-WECOM-01` 企业微信智能机器人（TODO）
- 抄 AstrBot 内置腾讯官方 **JSON 加解密** `ref-repos/AstrBot/.../wecom_ai_bot/WXBizJsonMsgCrypt.py`（`VerifyURL/EncryptMsg/DecryptMsg`）——wechatpy 覆盖不了机器人的 JSON 信封（硬约束）。
- 双模式：抄 AstrBot「单适配器双模式、`__init__`/`run()` 分支只建所需 client」；回调模式可参考 LangBot `wecombot` 的 stream 协议（首帧 `{msgtype:'stream',finish:false}`）。
- 反例（勿抄）：LangBot `wecombot` **关掉 CorpID 校验**（`WXBizMsgCrypt(token,aeskey,'')`）；我方保留 receiveid/CorpID 校验。

### → `M3-QA-01` / `M0-CHANNEL-01` 真实发送链路（BLOCKED，可先备实现）
- **access token 管理**：抄 openclaw `token.ts`（`expires_in-300s` 过期、主动刷新+退避、`INVALID_ACCESS_TOKEN_ERRCODES={40001,40014,42001,42007}` 命中才重试）；**补 LangBot 缺的**：honor TTL、多 worker 用**共享存储+锁**（禁进程内 Map）、必须处理 `40001`。
- **公众号 5s 竞速→客服消息兜底**（已绑定用户 Agent 慢于 5s）：竞速做在**队列侧投递模式决策**，deadline **在解密之后起算**（LangBot 在解密前起算是坑）；赢→被动 XML，输→ack `success`+Worker 走 48h 客服消息。用 AstrBot 的 **MsgId 区分「重试 vs 用户新问」** + `asyncio.shield` 防重试取消真调用。勿抄 openclaw 正则抠 XML、LangBot `passive` 载体模式。
- **按字节切分文本**（`WECHAT_TEXT_BYTE_LIMIT=2048`，openclaw `text.ts`）——中文真 bug 源。
- **outbound preflight 补 `reason`**：现有 `reply_window_expires_at`+`uncertain`（`core/delivery.py`），补齐 openclaw `checkCapability` 的 `{canSend, reason, windowExpiresAt}`；在凭据对象上暴露派生标志 `configured`/`canSendActive`，入口用可操作运维提示拒绝。

### → 增强项（可选，归 `M3-VERIFY-01` / `M3-ADMIN-01` 后续）
- LangBot 声明式配置清单 + **`__system.outbound_ips`（微信可信 IP 白名单）/ `type: webhook-url`（回调 URL 复制）**。
- 公众号明文/安全/**兼容模式自动探测**（openclaw `parsePostBody` 优先 body 内 `TimeStamp/Nonce/MsgSignature`）。
- normalize 带 `hasUserIntent`（openclaw）：`unsubscribe/view` 只记录不唤醒 Agent。
- 组件/日志 base64 截断脱敏（AstrBot `__repr_args__`）。

### 共享 crypto 与回放
- 三家都各自复制多份 crypto。我方**统一一份共享 WeChat crypto 模块**，用尾部 id 参数化（公众号 `appId`、企微 `corpId`）；Apache-2.0/MIT 允许直接 vendored `WXBizMsgCrypt3.py`/`WXBizJsonMsgCrypt.py`，保留 NOTICE。
- 回放保护三家全缺，我方已有 DB 级；新增渠道沿用 `core/channel_replay.py`。

### 优先级
1. **P0** `M3-WECHAT-CS-01` 客服 cursor + `get_launcher_id` ABC 钩子（纯本地可做，不阻塞）。
2. **P0** access token 管理模块（openclaw + 补锁/TTL/40001；真实发送前置）。
3. **P1** 公众号 5s→客服消息兜底（AstrBot MsgId+shield）+ 按字节切分（待 `M0-CHANNEL-01`）。
4. **P1** `M3-WECOM-01` JSON crypt（AstrBot vendored）+ 双模式。
5. **P2** 配置清单 `__system.*`、兼容模式自动探测、`hasUserIntent`、日志脱敏。

## 6. 现有结构评估与目标包结构（→ `M3-REFACTOR-01`）

### 6.1 评估结论：分层合理，但两处结构债
合理（有据）：
- 依赖方向干净——`integrations/channels/` 仅依赖 `core.delivery`（入站 DTO）/`core.error`/`core.platform`；**适配器不碰 DB session/models/identity/credentials/replay**。
- 边界与设计意图一致——「协议留适配器，身份/范围/权限/Agent 留平台服务」在代码中成立，强于三家（它们把 runtime/全局态塞进适配器）。

结构债（有据）：
- `backend/router/platform.py` = **2266 行**，远超 800 上限，是 god-orchestrator（HTTP+鉴权+注册+回调路由+编排）。
- crypto 内联在 451 行的 `wechat_official_account.py`（约 61 行 crypto），企微一来会复制第二份并顶 800 上限——重演三家坏味道。

### 6.2 是否单独成包
- **可分发独立包（类 LangBot SDK）：现在不要。** 单消费者、709 行/4 文件，独立版本化开销不划算；LangBot 正被自己的 SDK 拆分拖累（EBA 重写），引以为戒。
- **仓库内一等包 + 按渠道重构：要，且在客服/企微落地前做。** 该层将从 709 行增至数千行。目标结构：

```
backend/channels/
  contracts.py        # 中性契约：InboundMessageInput/OutboundMessage/DeliveryReceipt/ChannelCapabilities
  registry.py
  _wechat/
    crypto.py         # 统一 AES-256-CBC/PKCS7(32)/IV，尾部 id 参数化(appId/corpId)
    crypto_json.py    # 企微机器人 JSON 信封（wechatpy 不覆盖，vendored AstrBot）
    token.py          # access_token 缓存（TTL+锁+errcode 集）
    text.py           # 按字节切分 2048
  wechat_oa/  { adapter, inbound, outbound }.py   # 每文件 <400 行
  wechat_kf/  { adapter, inbound, outbound, cursor }.py
  wecom_bot/  { adapter, inbound, outbound }.py
  web.py
```

### 6.3 关键一步：契约中性化
现耦合方向为 channels → `core.delivery`。应反转：把 `InboundMessageInput/OutboundMessage/DeliveryReceipt/ChannelCapabilities` 收进 `channels/contracts.py`（或中性 `backend/contracts/`），令 **core 依赖契约**。改动便宜（挪 dataclass），但把「未来是否真拆包」变为零重构随时可做。

### 6.4 契约做实
`ChannelAdapter.normalize(self, **kwargs: Any) -> Any` 与 registry 存 `Any` 是弱鸭子契约。渠道一多，应收成带类型签名 + 明确返回 envelope 类型（呼应 LangBot EBA 从 `hasattr` 转 manifest 声明的教训）。

### 6.5 router 减肥（独立于成包）
把「验签→normalize→replay→身份→入队」编排从 `router/platform.py` 抽到 **`core/channel_ingress.py`**（留平台服务侧，**鉴权绝不进渠道包**），router 只留 HTTP + 调用 seam。

## 7. 落地建议顺序
1. `M3-REFACTOR-01`：一等包 + `contracts.py` 中性化 + 统一 `_wechat/crypto.py` + `core/channel_ingress` seam（作为客服/企微前置）。
2. `M3-WECHAT-CS-01`：客服 cursor + `get_launcher_id` ABC。
3. access token 模块 + `M3-WECOM-01`。
4. 真实联调相关（`M0-CHANNEL-01`/`M3-QA-01`）解阻塞后接 5s 兜底与真实发送。
