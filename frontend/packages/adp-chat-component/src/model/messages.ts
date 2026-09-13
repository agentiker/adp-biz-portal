/**
 * 消息常量定义
 * 统一管理所有提示消息的 code 和 message 映射
 * 内部维护中/英双套默认文案，通过 language 参数或 getMessage 的 language 入参切换
 */

/** 消息码常量对象 */
export const MessageCode = {
    // 成功类
    COPY_SUCCESS: 'COPY_SUCCESS',
    // 错误类
    COPY_FAILED: 'COPY_FAILED',
    SHARE_FAILED: 'SHARE_FAILED',
    FILE_UPLOAD_FAILED: 'FILE_UPLOAD_FAILED',
    FILE_FORMAT_NOT_SUPPORT: 'FILE_FORMAT_NOT_SUPPORT',
    GET_APP_LIST_FAILED: 'GET_APP_LIST_FAILED',
    GET_CONVERSATION_LIST_FAILED: 'GET_CONVERSATION_LIST_FAILED',
    GET_CONVERSATION_DETAIL_FAILED: 'GET_CONVERSATION_DETAIL_FAILED',
    SEND_MESSAGE_FAILED: 'SEND_MESSAGE_FAILED',
    NETWORK_ERROR: 'NETWORK_ERROR',
    LOAD_MORE_FAILED: 'LOAD_MORE_FAILED',
    RATE_FAILED: 'RATE_FAILED',
    ASR_SERVICE_FAILED: 'ASR_SERVICE_FAILED',
    RECORD_FAILED: 'RECORD_FAILED',
    CHROME_SECURITY_ERROR: 'CHROME_SECURITY_ERROR',
    BROWSER_NOT_SUPPORT: 'BROWSER_NOT_SUPPORT',
    AUDIO_CONTEXT_NOT_SUPPORT: 'AUDIO_CONTEXT_NOT_SUPPORT',
    WEB_AUDIO_API_NOT_SUPPORT: 'WEB_AUDIO_API_NOT_SUPPORT',
    MEDIA_STREAM_SOURCE_NOT_SUPPORT: 'MEDIA_STREAM_SOURCE_NOT_SUPPORT',
    MIC_PERMISSION_DENIED: 'MIC_PERMISSION_DENIED',
    MIC_NOT_FOUND: 'MIC_NOT_FOUND',
    MIC_OCCUPIED: 'MIC_OCCUPIED',

    // 警告类
    ANSWERING: 'ANSWERING',
    RECORD_TOO_LONG: 'RECORD_TOO_LONG',
} as const;

/** 消息码类型 */
export type MessageCode = typeof MessageCode[keyof typeof MessageCode];

/** 消息类型 */
export type MessageType = 'success' | 'warning' | 'error' | 'info';

/** 消息配置项 */
export interface MessageConfig {
    /** 消息码 */
    code: MessageCode;
    /** 消息文本（按当前 language 派生） */
    message: string;
    /** 消息类型（success/warning/error/info） */
    type: MessageType;
}

/** 单条消息的 type 与 中/英 文案定义 */
interface MessageEntry {
    type: MessageType;
    zh: string;
    en: string;
}

/** 消息映射表（内部维护中/英双套文案） */
const MESSAGE_MAP: Record<MessageCode, MessageEntry> = {
    // 成功类
    [MessageCode.COPY_SUCCESS]: {
        type: 'success',
        zh: '复制成功',
        en: 'Copied',
    },
    // 错误类
    [MessageCode.COPY_FAILED]: {
        type: 'error',
        zh: '复制失败',
        en: 'Copy failed',
    },
    [MessageCode.SHARE_FAILED]: {
        type: 'error',
        zh: '分享失败',
        en: 'Share failed',
    },
    [MessageCode.FILE_UPLOAD_FAILED]: {
        type: 'error',
        zh: '文件上传失败',
        en: 'File upload failed',
    },
    [MessageCode.FILE_FORMAT_NOT_SUPPORT]: {
        type: 'error',
        zh: '不支持的文件格式',
        en: 'Unsupported file format',
    },
    [MessageCode.GET_APP_LIST_FAILED]: {
        type: 'error',
        zh: '获取应用列表失败',
        en: 'Failed to load application list',
    },
    [MessageCode.GET_CONVERSATION_LIST_FAILED]: {
        type: 'error',
        zh: '获取会话列表失败',
        en: 'Failed to load conversation list',
    },
    [MessageCode.GET_CONVERSATION_DETAIL_FAILED]: {
        type: 'error',
        zh: '获取会话详情失败',
        en: 'Failed to load conversation detail',
    },
    [MessageCode.SEND_MESSAGE_FAILED]: {
        type: 'error',
        zh: '发送消息失败',
        en: 'Failed to send message',
    },
    [MessageCode.NETWORK_ERROR]: {
        type: 'error',
        zh: '网络错误',
        en: 'Network error',
    },
    [MessageCode.LOAD_MORE_FAILED]: {
        type: 'error',
        zh: '加载更多失败',
        en: 'Failed to load more',
    },
    [MessageCode.RATE_FAILED]: {
        type: 'error',
        zh: '评分失败',
        en: 'Rating failed',
    },
    [MessageCode.ASR_SERVICE_FAILED]: {
        type: 'error',
        zh: '获取语音识别服务失败',
        en: 'Failed to acquire ASR service',
    },
    [MessageCode.RECORD_FAILED]: {
        type: 'error',
        zh: '录音失败',
        en: 'Recording failed',
    },
    [MessageCode.CHROME_SECURITY_ERROR]: {
        type: 'error',
        zh: 'Chrome下获取录音功能需要在localhost、127.0.0.1或https下才能获取权限',
        en: 'Chrome requires localhost, 127.0.0.1 or HTTPS to grant microphone permission',
    },
    [MessageCode.BROWSER_NOT_SUPPORT]: {
        type: 'error',
        zh: '无法获取浏览器录音功能，请升级浏览器或使用Chrome',
        en: 'Browser recording is not available. Please upgrade your browser or use Chrome',
    },
    [MessageCode.AUDIO_CONTEXT_NOT_SUPPORT]: {
        type: 'error',
        zh: '浏览器不支持AudioContext',
        en: 'Browser does not support AudioContext',
    },
    [MessageCode.WEB_AUDIO_API_NOT_SUPPORT]: {
        type: 'error',
        zh: '浏览器不支持webAudioApi相关接口',
        en: 'Browser does not support Web Audio API',
    },
    [MessageCode.MEDIA_STREAM_SOURCE_NOT_SUPPORT]: {
        type: 'error',
        zh: '不支持MediaStreamSource',
        en: 'MediaStreamSource is not supported',
    },
    [MessageCode.MIC_PERMISSION_DENIED]: {
        type: 'error',
        zh: '麦克风权限被拒绝，请点击地址栏锁定图标将麦克风设为允许后重试；若页面嵌在 iframe 中，还需宿主页面声明 allow="microphone"',
        en: 'Microphone permission denied. Click the lock icon in the address bar and set Microphone to Allow, then retry. If embedded in an iframe, the host page must declare allow="microphone"',
    },
    [MessageCode.MIC_NOT_FOUND]: {
        type: 'error',
        zh: '未检测到可用的麦克风设备',
        en: 'No microphone device detected',
    },
    [MessageCode.MIC_OCCUPIED]: {
        type: 'error',
        zh: '麦克风被其他应用占用，请关闭占用程序后重试',
        en: 'Microphone is occupied by another application. Close it and retry',
    },

    // 警告类
    [MessageCode.ANSWERING]: {
        type: 'warning',
        zh: '正在回答中...',
        en: 'Answering...',
    },
    [MessageCode.RECORD_TOO_LONG]: {
        type: 'warning',
        zh: '录音时间过长',
        en: 'Recording is too long',
    },
};

/**
 * 判断 language 是否为英文（前缀 en）
 * @param language 语言标识（如 'zh-CN'、'en-US'）
 */
function isEnglish(language?: string): boolean {
    return !!language && language.startsWith('en');
}

/**
 * 根据消息码获取消息配置
 * @param code 消息码
 * @param language 当前语言标识（如 'zh-CN'、'en-US'），未传时按中文
 * @returns 消息配置
 */
export function getMessage(code: MessageCode, language?: string): MessageConfig {
    const entry = MESSAGE_MAP[code];
    return {
        code,
        type: entry.type,
        message: isEnglish(language) ? entry.en : entry.zh,
    };
}

/**
 * 根据消息码获取消息文本
 * @param code 消息码
 * @param language 当前语言标识（如 'zh-CN'、'en-US'），未传时按中文
 * @returns 消息文本
 */
export function getMessageText(code: MessageCode, language?: string): string {
    const entry = MESSAGE_MAP[code];
    if (!entry) return '';
    return isEnglish(language) ? entry.en : entry.zh;
}
