/**
 * 企微 AI 机器人 SDK 类型声明
 *
 * 说明：
 *  - 源脚本为企微官方 UMD 包 wecom-aibot-sdk@0.1.1.min.js。
 *  - UMD 会在浏览器环境将 SDK 挂到 window.WecomAIBotSDK。
 *  - 使用方 `import 'wecom-aibot-sdk'` 后可通过 window.WecomAIBotSDK 访问。
 */

declare module 'wecom-aibot-sdk';

/** 扫码授权成功回调数据 */
export interface WecomAIBotSDKCreatedBot {
    /** Bot ID */
    botid?: string;
    /** Bot Secret */
    secret?: string;
}

/** SDK 打开授权窗口的入参 */
export interface WecomAIBotSDKOpenParams {
    /** 业务来源，透传给企微以便统计 */
    source: string;
    /** 扫码创建/授权成功回调 */
    onCreated?: (bot: WecomAIBotSDKCreatedBot | null | undefined) => void;
    /** 授权失败回调（用户主动关闭 / 网络失败 / 后台报错） */
    onError?: (err?: unknown) => void;
}

/** window.WecomAIBotSDK 接口约束 */
export interface WecomAIBotSDK {
    openBotInfoAuthWindow: (params: WecomAIBotSDKOpenParams) => void;
}

declare global {
    interface Window {
        WecomAIBotSDK?: WecomAIBotSDK;
    }
}
