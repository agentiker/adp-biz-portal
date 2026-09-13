# 微信服务号适配器实施计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在统一渠道框架中加入微信服务号明文回调适配器，支持本地可验证的回调验签、消息标准化、幂等入队和受限出站能力。

**Architecture:** 服务号回调由独立适配器解析和校验，凭据由平台加密凭据表读取；入站消息只写入 durable delivery 队列，由现有 Worker 处理身份、企业范围和 Agent/M3 调用。真实微信账号、加密协议和发送联调继续由 ROADMAP 的阻塞项管理，不以本地 Mock 代替。

**Tech Stack:** Python 3、Sanic、SQLAlchemy Async、标准库 `xml.etree.ElementTree`、pytest。

---

### Task 1: 建立协议 helper 和适配器

**Files:**
- Create: `backend/integrations/channels/wechat_official_account.py`
- Modify: `backend/integrations/channels/registry.py`
- Modify: `backend/integrations/channels/__init__.py`
- Test: `backend/test/unit_test/test_wechat_official_account.py`

覆盖 GET 签名、时间窗、进程内 nonce 重放保护、明文 XML 安全解析、文本消息标准化，以及未知发送结果返回 `uncertain`。

### Task 2: 接入公网回调路由

**Files:**
- Modify: `backend/router/platform.py`
- Test: `backend/test/unit_test/test_wechat_official_account.py`

增加服务号验证和 POST 回调路由。回调只读取已启用凭据、调用适配器、写入 `record_inbound_message`，不在请求内调用 Worker/ADP。

### Task 3: 更新 ROADMAP 与验证证据

**Files:**
- Modify: `ROADMAP.md`
- Create: `output/tests/m3-wechat-oa-01-official-account.json`

运行定向单测、编译和 `git diff --check`，记录本地框架完成情况与真实联调遗留风险。
