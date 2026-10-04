# README 视觉识别设计

日期：2026-10-04  
任务：`OSS-README-02`  
状态：已确认，进入实现

## 目标

让第一次访问仓库的开发者在几秒内理解项目定位、技术边界和主要能力，同时保持 README 在 GitHub、Gitee 和离线 Markdown 渲染器中的可读性。视觉资源必须放在仓库内，不依赖外部图片服务，不出现生产地址、客户数据或凭据。

## 方案

采用深色科技感的静态首页。README 顶部使用本地 SVG 主视觉，深蓝至黑色渐变作为底色，蓝紫渐变作为强调色，以节点连线表达渠道、AI Provider、MCP 和企业业务系统之间的受控连接。SVG 提供替代文本，并控制尺寸，避免使用自动播放 GIF 或 JavaScript 轮播。

横幅下方使用真实技术徽章和三张静态能力卡片，分别说明多渠道接入、企业身份与数据范围、MCP/HTTP 工具调用。现有 Mermaid 架构图、快速开始、接入说明和边界声明继续保留。徽章只反映仓库已使用的技术；当前没有 GitHub Actions，因此不添加 CI 状态徽章。

## 资源与文档结构

```text
docs/assets/readme-hero.svg       README 主视觉，仓库内可复用
README.md                         首页结构、徽章、能力导航和文档入口
docs/roadmap.md                   任务状态和完成证据
```

GitHub Repository Topics 和 Issue Labels 属于仓库设置，交付时提供建议清单，不在 README 中伪装为已生效配置。

## 验收标准

1. SVG 可在 GitHub README 中加载，拥有有意义的替代文本，且不引用外部资源。
2. README 顶部包含主视觉、项目定位和真实技术徽章；能力导航不依赖脚本。
3. 既有快速开始、架构、MCP/ADP 接入、测试和安全边界链接继续有效。
4. Markdown 链接检查、SVG 路径检查和 `git diff --check` 通过。
