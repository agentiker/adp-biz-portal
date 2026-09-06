/**
 * 渠道设置弹窗相关类型定义与国际化
 *
 * C 端 claw 模式的 IM 渠道配置：
 *   - 当前支持：企微智能机器人（10014）、微信 ClawBot（10015）
 *   - 接口 scene 统一传 1（C_END）
 */

import {
    type ChannelItem,
    ClawChannelStatus,
    ChannelType,
} from '../service/channelApi';

import wecomIcon from '../assets/wecom_icon.png';
import wechatIcon from '../assets/wechat_icon.png';

// 重导出服务层类型，方便组件集中引入
export { ClawChannelStatus, ChannelType };
export type { ChannelItem };

// ============================================================
// 渠道显示配置
// ============================================================

/** 企微智能机器人（WebSocket） */
export const CHANNEL_WECOM_ROBOT_KEY = 'wecom_robot_ws' as const;
/** 微信 ClawBot */
export const CHANNEL_WECHAT_CLAWBOT_KEY = 'wechat_clawbot' as const;

/** C 端支持的渠道类型列表（与 webim 对齐） */
export const SUPPORTED_CHANNEL_TYPES = [
    ChannelType.WECOM_ROBOT_WS,   // 10014
    ChannelType.WECHAT_CLAWBOT,   // 10015
] as const;

/** 渠道类型 → 图标图片资源映射（与 webim 对齐，使用图片而非 iconfont） */
export const CHANNEL_ICON_MAP: Record<number, string> = {
    [ChannelType.WECOM_ROBOT_WS]: wecomIcon,
    [ChannelType.WECHAT_CLAWBOT]: wechatIcon,
};

/** 渠道类型 → 显示名称 key 映射 */
export const CHANNEL_NAME_KEYS: Record<number, string> = {
    [ChannelType.WECOM_ROBOT_WS]: 'channelNameWecomRobot',
    [ChannelType.WECHAT_CLAWBOT]: 'channelNameWechatClawBot',
};

// ============================================================
// 弹窗展示用的渠道行数据
// ============================================================

/** 弹窗列表中每一行的展示数据 */
export interface ChannelRow {
    /** 渠道类型枚举值 */
    channelType: number;
    /** 渠道 ID（后端分配的雪花 ID，未创建时为空） */
    channelId: number;
    /** 显示名称 */
    label: string;
    /** 图标名称 */
    icon: string;
    /** 配置状态 */
    connectStatus: ClawChannelStatus;
    /** 更新时间 */
    updateTime: number;
    /** 原始后端数据（用于详情/重新配置等场景透传） */
    raw: ChannelItem | null;
}

// ============================================================
// I18n 接口
// ============================================================

/** 渠道设置弹窗国际化文本 */
export interface ChannelSettingsI18n {
    /** 弹窗标题 */
    title?: string;
    /** 渠道类型列标题 */
    columnChannelType?: string;
    /** 配置状态列标题 */
    columnStatus?: string;
    /** 操作列标题 */
    columnAction?: string;
    /** 已配置 */
    statusConfigured?: string;
    /** 未配置 */
    statusUnconfigured?: string;
    /** 已失效 */
    statusInvalid?: string;
    /** 详情 */
    actionDetail?: string;
    /** 配置 */
    actionConfigure?: string;
    /** 重新配置 */
    actionReconfigure?: string;
    /** 重新配置确认文案 */
    reconfigureConfirmText?: string;
    /** 清除 */
    actionClear?: string;
    /** 清除确认文案 */
    clearConfirmText?: string;
    /** 确定清除 */
    confirmClear?: string;
    /** 取消 */
    cancel?: string;
    /** 渠道类型名称 */
    channelNameWecomRobot?: string;
    /** 渠道类型名称 - 微信 ClawBot */
    channelNameWechatClawBot?: string;
    /** 加载中 */
    loading?: string;
    /** 详情弹窗标题后缀（对齐 webim："{渠道名} 渠道配置"） */
    detailTitleSuffix?: string;
    /** 详情：Bot ID 字段标签 */
    detailBotIdLabel?: string;
    /** 详情：Secret 字段标签 */
    detailSecretLabel?: string;
    /** 详情：iLink 账号 ID 字段标签（微信 ClawBot） */
    detailIlinkIdLabel?: string;
    /** 详情：空值占位文案 */
    detailEmptyValue?: string;
    /** 详情：关闭按钮文案（知道了） */
    detailGotIt?: string;

    // ---- 企微机器人配置弹窗 ----
    /** 企微机器人配置：新建标题 */
    wecomBotDialogTitleCreate?: string;
    /** 企微机器人配置：重新配置标题 */
    wecomBotDialogTitleModify?: string;
    /** 企微机器人配置：获取凭证前缀文案 */
    wecomBotTipCredentialPrefix?: string;
    /** 企微机器人配置：可点击的链接文案（会渲染为 <a>） */
    wecomBotTipCredentialLink?: string;
    /** 企微机器人配置：链接后的描述文案 */
    wecomBotTipCredentialSuffix?: string;
    /** 企微机器人配置：重要提示（换行显示） */
    wecomBotTipImportant?: string;
    /** 企微机器人配置：输入框 placeholder */
    wecomBotInputPlaceholder?: string;
    /** 企微机器人配置：Bot ID 必填校验 */
    wecomBotBotIdRequired?: string;
    /** 企微机器人配置：Secret 必填校验 */
    wecomBotSecretRequired?: string;
    /** 企微机器人配置：确定按钮 */
    wecomBotConfirm?: string;
    /** 企微机器人配置：创建成功提示 */
    wecomBotCreateSuccess?: string;
    /** 企微机器人配置：修改成功提示 */
    wecomBotModifySuccess?: string;
    /** 企微机器人配置：默认失败提示 */
    wecomBotConfigFailed?: string;
    /** 企微机器人配置：SDK 未加载提示 */
    wecomBotSdkNotLoaded?: string;
    /** 企微机器人配置：SDK 加载失败提示 */
    wecomBotSdkLoadFailed?: string;
    /** 企微机器人配置：SDK 授权失败提示（引导手动填写） */
    wecomBotSdkAuthFailed?: string;

    // ---- 渠道设置弹窗：清除操作 ----
    /** 清除成功 toast */
    clearSuccess?: string;
    /** 清除失败 toast */
    clearFailed?: string;

    // ---- 微信 ClawBot 配置弹窗（10015） ----
    /** 微信 ClawBot：新建标题 */
    wechatClawBotDialogTitleCreate?: string;
    /** 微信 ClawBot：重新配置标题 */
    wechatClawBotDialogTitleModify?: string;
    /** 微信 ClawBot：渠道名称（创建时传后端 */
    wechatClawBotChannelName?: string;
    /** 微信 ClawBot：二维码等待扫码提示 */
    wechatClawBotQrcodeTipWait?: string;
    /** 微信 ClawBot：二维码已扫描提示 */
    wechatClawBotQrcodeTipScan?: string;
    /** 微信 ClawBot：二维码已确认提示 */
    wechatClawBotQrcodeTipConfirmed?: string;
    /** 微信 ClawBot：二维码已过期提示 */
    wechatClawBotQrcodeTipExpired?: string;
    /** 微信 ClawBot：正在生成二维码 */
    wechatClawBotGenerating?: string;
    /** 微信 ClawBot：二维码生成失败 */
    wechatClawBotQrcodeFailed?: string;
    /** 微信 ClawBot：创建渠道失败 */
    wechatClawBotCreateFailed?: string;
    /** 微信 ClawBot：关闭 */
    wechatClawBotClose?: string;
    /** 微信 ClawBot：重试 */
    wechatClawBotRetry?: string;
    /** 微信 ClawBot：完成 */
    wechatClawBotDone?: string;
    /** 微信 ClawBot：取消 */
    wechatClawBotCancel?: string;

    // ---- 渠道会话面板（CCP） ----
    /** CCP 面板标题兜底（无 channelLabel 时） */
    ccpPanelTitle?: string;
    /** CCP 未命名会话 */
    ccpUnnamed?: string;
    /** CCP 刚刚 */
    ccpJustNow?: string;
    /** CCP N 分钟前（占位 {n}） */
    ccpMinutesAgo?: string;
    /** CCP N 小时前（占位 {n}） */
    ccpHoursAgo?: string;
    /** CCP 刷新 tooltip */
    ccpRefresh?: string;
    /** CCP 关闭 tooltip */
    ccpClose?: string;
    /** CCP 加载中 */
    ccpLoading?: string;
    /** CCP 空态 */
    ccpEmpty?: string;
}

/** 渠道设置弹窗 i18n 中文默认值 */
export const defaultChannelSettingsI18n: Required<ChannelSettingsI18n> = {
    title: '渠道设置',
    columnChannelType: '渠道类型',
    columnStatus: '配置状态',
    columnAction: '操作',
    statusConfigured: '已配置',
    statusUnconfigured: '未配置',
    statusInvalid: '已失效',
    actionDetail: '详情',
    actionConfigure: '配置',
    actionReconfigure: '重新配置',
    reconfigureConfirmText: '重新配置，将覆盖当前绑定的账号和对话历史纪录',
    actionClear: '清除',
    clearConfirmText: '确认清除配置吗，原渠道将无法使用',
    confirmClear: '确定清除',
    cancel: '取消',
    channelNameWecomRobot: '企微智能机器人',
    channelNameWechatClawBot: '微信',
    loading: '加载中...',
    detailTitleSuffix: '渠道配置',
    detailBotIdLabel: 'Bot ID',
    detailSecretLabel: 'Secret',
    detailIlinkIdLabel: 'iLink 账号 ID',
    detailEmptyValue: '暂无',
    detailGotIt: '知道了',

    wecomBotDialogTitleCreate: '企微智能机器人渠道配置',
    wecomBotDialogTitleModify: '重新配置企微智能机器人',
    wecomBotTipCredentialPrefix: '获取凭证：',
    wecomBotTipCredentialLink: '点击链接',
    wecomBotTipCredentialSuffix: '用企微扫码快速获取。',
    wecomBotTipImportant: '重要提示：一个企微机器人只能绑定一个空间的智能工作台。',
    wecomBotInputPlaceholder: '请输入',
    wecomBotBotIdRequired: '请输入 Bot ID',
    wecomBotSecretRequired: '请输入 Bot Secret',
    wecomBotConfirm: '确定',
    wecomBotCreateSuccess: '渠道创建成功',
    wecomBotModifySuccess: '重新配置成功',
    wecomBotConfigFailed: '配置失败',
    wecomBotSdkNotLoaded: 'WecomAIBotSDK 未配置，请手动填写',
    wecomBotSdkLoadFailed: '扫码组件加载失败，请手动填写',
    wecomBotSdkAuthFailed: '获取失败，请手动填写',

    clearSuccess: '清除成功',
    clearFailed: '清除失败',

    wechatClawBotDialogTitleCreate: '微信渠道配置',
    wechatClawBotDialogTitleModify: '重新配置微信',
    wechatClawBotChannelName: '微信',
    wechatClawBotQrcodeTipWait: '微信扫码授权',
    wechatClawBotQrcodeTipScan: '扫码成功，请在微信中确认',
    wechatClawBotQrcodeTipConfirmed: '已成功绑定微信ClawBot',
    wechatClawBotQrcodeTipExpired: '二维码已过期，点击刷新',
    wechatClawBotGenerating: '正在生成二维码...',
    wechatClawBotQrcodeFailed: '未获取到二维码，请刷新重试',
    wechatClawBotCreateFailed: '创建渠道失败',
    wechatClawBotClose: '关闭',
    wechatClawBotRetry: '重试',
    wechatClawBotDone: '完成',
    wechatClawBotCancel: '取消',

    ccpPanelTitle: '渠道会话',
    ccpUnnamed: '未命名',
    ccpJustNow: '刚刚',
    ccpMinutesAgo: '{n}分钟前',
    ccpHoursAgo: '{n}小时前',
    ccpRefresh: '刷新',
    ccpClose: '关闭',
    ccpLoading: '加载中...',
    ccpEmpty: '暂无会话',
};

/** 渠道设置弹窗 i18n 英文默认值 */
export const defaultChannelSettingsI18nEn: Required<ChannelSettingsI18n> = {
    title: 'Channel Settings',
    columnChannelType: 'Channel Type',
    columnStatus: 'Status',
    columnAction: 'Action',
    statusConfigured: 'Configured',
    statusUnconfigured: 'Not Configured',
    statusInvalid: 'Invalid',
    actionDetail: 'Detail',
    actionConfigure: 'Configure',
    actionReconfigure: 'Reconfigure',
    reconfigureConfirmText: 'Reconfiguring will overwrite the currently bound account and conversation history',
    actionClear: 'Clear',
    clearConfirmText: 'Are you sure you want to clear the configuration? The original channel will become unavailable.',
    confirmClear: 'Confirm Clear',
    cancel: 'Cancel',
    channelNameWecomRobot: 'WeCom Bot',
    channelNameWechatClawBot: 'WeChat',
    loading: 'Loading...',
    detailTitleSuffix: 'Channel Config',
    detailBotIdLabel: 'Bot ID',
    detailSecretLabel: 'Secret',
    detailIlinkIdLabel: 'iLink Account ID',
    detailEmptyValue: 'None',
    detailGotIt: 'Got it',

    wecomBotDialogTitleCreate: 'WeCom Bot Channel Configuration',
    wecomBotDialogTitleModify: 'Reconfigure WeCom Bot',
    wecomBotTipCredentialPrefix: 'Get credentials: ',
    wecomBotTipCredentialLink: 'click here',
    wecomBotTipCredentialSuffix: ' and scan the QR code with WeCom.',
    wecomBotTipImportant: 'Note: a WeCom bot can be bound to only one space.',
    wecomBotInputPlaceholder: 'Please enter',
    wecomBotBotIdRequired: 'Please enter Bot ID',
    wecomBotSecretRequired: 'Please enter Bot Secret',
    wecomBotConfirm: 'Confirm',
    wecomBotCreateSuccess: 'Channel created',
    wecomBotModifySuccess: 'Reconfigured successfully',
    wecomBotConfigFailed: 'Configuration failed',
    wecomBotSdkNotLoaded: 'WecomAIBotSDK is not configured, please fill in manually',
    wecomBotSdkLoadFailed: 'Failed to load the QR-code component, please fill in manually',
    wecomBotSdkAuthFailed: 'Failed to retrieve, please fill in manually',

    clearSuccess: 'Cleared',
    clearFailed: 'Clear failed',

    wechatClawBotDialogTitleCreate: 'WeChat Channel Configuration',
    wechatClawBotDialogTitleModify: 'Reconfigure WeChat',
    wechatClawBotChannelName: 'WeChat',
    wechatClawBotQrcodeTipWait: 'Scan QR code with WeChat to authorize',
    wechatClawBotQrcodeTipScan: 'Scanned successfully, please confirm in WeChat',
    wechatClawBotQrcodeTipConfirmed: 'WeChat ClawBot bound successfully',
    wechatClawBotQrcodeTipExpired: 'QR code expired, click to refresh',
    wechatClawBotGenerating: 'Generating QR code...',
    wechatClawBotQrcodeFailed: 'Failed to get QR code, please refresh and try again',
    wechatClawBotCreateFailed: 'Failed to create channel',
    wechatClawBotClose: 'Close',
    wechatClawBotRetry: 'Retry',
    wechatClawBotDone: 'Done',
    wechatClawBotCancel: 'Cancel',

    ccpPanelTitle: 'Channel Conversations',
    ccpUnnamed: 'Untitled',
    ccpJustNow: 'Just now',
    ccpMinutesAgo: '{n}min ago',
    ccpHoursAgo: '{n}h ago',
    ccpRefresh: 'Refresh',
    ccpClose: 'Close',
    ccpLoading: 'Loading...',
    ccpEmpty: 'No conversations',
};
