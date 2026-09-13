/**
 * ADP Chat Component 入口
 *
 * 本组件库不再是对外可嵌入的 SDK，只服务平台管理端的 `/admin/adp-chat`
 * 调试页（`client/packages/app/src/pages/AdminAdpChat.vue`）。因此导出面
 * 收敛为该页面实际消费的部分：一个布局组件、axios 拦截器配置和三个类型。
 *
 * 全局挂载入口（原 `./main` 的 default 导出与 `./mounters`）随 UMD 产物一并
 * 下线；ADP 管理面能力（定时任务 / 渠道 / 插件 / 连接器 / 技能 / 知识库）
 * 已从组件库移除，不再从这里导出。
 */

// 导入 TDesign 基础样式
import 'tdesign-vue-next/es/style/index.css'
// 导入 TDesign Chat 样式
import '@tdesign-vue-next/chat/es/style/index.css'
// 导入全局样式（确保打包时包含）
import './style.css'
// 导入主题样式（TDesign 主题 CSS 变量）
import './styles/theme.css'

// 布局组件
export { default as ADPChat } from './components/layout/Index.vue'

// Service：调试页用它注入平台登录态失效的响应拦截
export {
    httpService,
    configureAxios,
    setRequestInterceptor,
    setResponseInterceptor,
    defaultApiDetailConfig,
} from './service'
export type { ApiConfig, ApiDetailConfig } from './service'

// 类型
export type { Application, AppPattern } from './model/application'
export type { ChatConversation, Record, Reference, QuoteInfo } from './model/chat-v2'
export { ScoreValue } from './model/chat-v2'
export type { ChatConfig, ChatMode, ThemeType } from './model/type'
