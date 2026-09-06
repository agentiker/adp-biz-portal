/**
 * 定时任务（CronTask）相关类型定义
 * 对应后端 proto: trpc.adp.time_scheduler
 */

// ============================================================
// 枚举
// ============================================================

/** 任务状态 */
export const TimerTaskStatus = {
    UNSPECIFIED: 0,
    /** 运行中 */
    ACTIVE: 1,
    /** 已暂停 */
    PAUSED: 2,
    /** 已完成 */
    COMPLETED: 3,
} as const;
export type TimerTaskStatusValue = typeof TimerTaskStatus[keyof typeof TimerTaskStatus];

/**
 * 单次运行状态。
 * 严格对齐 proto `TimerRunStatus`（time_scheduler.proto）：
 *   0 UNSPECIFIED / 1 PENDING / 2 RUNNING / 3 RETRY_WAIT
 *   / 4 SUCCESS / 5 DEAD(失败终态) / 6 CANCELLED
 *
 * 注意：AppTriggerRunLog.status / AppTriggerInstance.status 均使用该枚举，
 *   前后端必须一致。历史上前端错把 3=SUCCESS/4=FAILED/5=CANCELED/6=TIMEOUT，
 *   会导致 DescribeAppTriggerRunLogList 返回状态与 UI 显示不一致，务必勿改回。
 */
export const TimerRunStatus = {
    UNSPECIFIED: 0,
    /** 等待执行 */
    PENDING: 1,
    /** 运行中 */
    RUNNING: 2,
    /** 等待重试 */
    RETRY_WAIT: 3,
    /** 成功 */
    SUCCESS: 4,
    /** 已死亡（失败终态） */
    DEAD: 5,
    /** DEAD 的别名，语义"失败"，便于调用方读起来更直白。 */
    FAILED: 5,
    /** 已取消 */
    CANCELLED: 6,
    /** CANCELLED 的旧拼写别名，勿新增使用。 */
    CANCELED: 6,
} as const;
export type TimerRunStatusValue = typeof TimerRunStatus[keyof typeof TimerRunStatus];

/** 调度类型 */
export const TimerScheduleType = {
    UNSPECIFIED: 0,
    /** 仅手动 */
    MANUAL_ONLY: 1,
    /** 每天 */
    DAILY: 2,
    /** 每周 */
    WEEKLY: 3,
    /** 间隔 */
    INTERVAL: 4,
    /** 一次性 */
    ONCE: 5,
    /** Cron 表达式 */
    CRON: 6,
} as const;
export type TimerScheduleTypeValue = typeof TimerScheduleType[keyof typeof TimerScheduleType];

/**
 * 推送渠道
 * 对齐 proto TimerPushChannel（time_scheduler.proto）：
 *   1 = 不推送 / 2 = 微信公众号 / 3 = 企业微信 AI 机器人 / 4 = 企业微信 webhook 机器人
 */
export const TimerPushChannel = {
    UNSPECIFIED: 0,
    NONE: 1,
    WECHAT: 2,
    WECOM_BOT: 3,
    WECOM_WEBHOOK: 4,
} as const;
export type TimerPushChannelValue = typeof TimerPushChannel[keyof typeof TimerPushChannel];

/**
 * 推送目标类型
 * 对齐 proto TimerPushTargetType：
 *   1 = USER（微信公众号 openid）/ 2 = CHAT（企微机器人 chat_id）
 */
export const TimerPushTargetType = {
    UNSPECIFIED: 0,
    USER: 1,
    CHAT: 2,
} as const;
export type TimerPushTargetTypeValue = typeof TimerPushTargetType[keyof typeof TimerPushTargetType];

/** 创建来源 */
export const TimerCreateSource = {
    UNSPECIFIED: 0,
    /** 手动创建 */
    MANUAL: 1,
    /** NLP 自然语言创建 */
    NLP: 2,
} as const;
export type TimerCreateSourceValue = typeof TimerCreateSource[keyof typeof TimerCreateSource];

// ============================================================
// 数据结构
// ============================================================

/** 时间点，例如 {Hour:9, Minute:30} */
export interface TimerTimeOfDay {
    Hour: number;
    Minute: number;
}

/** 间隔配置 */
export interface TimerInterval {
    /** 间隔秒数 */
    Seconds: number;
}

/** 调度配置 */
export interface TimerScheduleConfig {
    /** 调度类型 */
    ScheduleType: TimerScheduleTypeValue;
    /** 时区（IANA，如 Asia/Shanghai） */
    Timezone?: string;
    /** DAILY: 每天触发时间点 */
    Daily?: TimerTimeOfDay;
    /** WEEKLY: 星期几（0-6，0=Sunday） */
    Weekdays?: number[];
    /** WEEKLY: 触发时间点 */
    Weekly?: TimerTimeOfDay;
    /** INTERVAL: 间隔配置 */
    Interval?: TimerInterval;
    /** ONCE: RFC3339 时间字符串，或直接使用 Unix 秒（后端约定 ExecuteAt） */
    ExecuteAt?: string | number;
    /** CRON: 表达式（5 段：分 时 日 月 周） */
    CronExpression?: string;
}

/** 微信推送配置 */
export interface TimerPushWechatConfig {
    OpenId?: string;
    TemplateId?: string;
}

/** 企微机器人推送配置 */
export interface TimerPushWecomBotConfig {
    WebhookUrl?: string;
}

/**
 * 推送配置
 * 对齐 proto TimerPushConfig（time_scheduler.proto:468）：
 *   push_channel + push_target_type + push_target_id + push_webhook_url
 * 保留旧的 Channel / Wechat / WecomBot 字段以兼容存量数据回填。
 */
export interface TimerPushConfig {
    /** 推送渠道枚举 */
    PushChannel?: TimerPushChannelValue;
    /** 推送目标类型：1=USER / 2=CHAT */
    PushTargetType?: TimerPushTargetTypeValue;
    /** openid（公众号）或 chat_id（企微机器人） */
    PushTargetId?: string;
    /** 企业微信 webhook 推送地址（TIMER_PUSH_CHANNEL_WECOM_WEBHOOK 使用） */
    PushWebhookUrl?: string;
    /** @deprecated 兼容旧字段：等价于 PushChannel */
    Channel?: TimerPushChannelValue;
    /** @deprecated 兼容旧字段 */
    Wechat?: TimerPushWechatConfig;
    /** @deprecated 兼容旧字段 */
    WecomBot?: TimerPushWecomBotConfig;
}

/** 任务档案 */
export interface TimerProfile {
    TaskName: string;
    Description?: string;
    PromptContent: string;
    /** 使用的模型 */
    ModelName?: string;
    /** 关联的会话/文件夹 ID */
    ConversationId?: string;
    /** 创建来源 */
    CreateSource?: TimerCreateSourceValue;
}

/** 任务运行配置 */
export interface TimerConfig {
    Schedule: TimerScheduleConfig;
    Push?: TimerPushConfig;
    /** 单次执行超时（秒） */
    TimeoutSeconds?: number;
    /** 最大重试次数 */
    MaxRetries?: number;
}

/** 任务状态信息 */
export interface TimerStatus {
    /** 任务状态 */
    Status: TimerTaskStatusValue;
    /** 下次触发时间（Unix 秒 或 RFC3339） */
    NextRunAt?: string | number;
    /** 上次触发时间 */
    LastRunAt?: string | number;
    /** 最近一次运行结果 */
    LastRunStatus?: TimerRunStatusValue;
    /** 累计成功次数 */
    SuccessCount?: number;
    /** 累计失败次数 */
    FailureCount?: number;
    /** 累计总次数 */
    TotalCount?: number;
    /** 未读日志数 */
    UnreadCount?: number;
    /** 策略摘要（后端生成的可读文本） */
    PolicySummary?: string;
}

/** 完整任务详情 */
export interface TimerTask {
    TimerId: string;
    SpaceId?: string;
    ApplicationId?: string;
    OwnerId?: string;
    Profile: TimerProfile;
    Config: TimerConfig;
    Status: TimerStatus;
    CreateTime?: string | number;
    UpdateTime?: string | number;
}

/** 任务摘要（列表项） */
export interface TimerTaskSummary {
    TimerId: string;
    Profile: TimerProfile;
    Config?: TimerConfig;
    Status: TimerStatus;
    CreateTime?: string | number;
    UpdateTime?: string | number;
}

/** 单条运行日志 */
export interface TimerRunLog {
    LogId: string;
    TimerId: string;
    RunStatus: TimerRunStatusValue;
    /** 触发时间 */
    TriggerTime?: string | number;
    /** 完成时间 */
    FinishTime?: string | number;
    /** 关联的会话 ID（点击跳转） */
    SessionId?: string;
    /** 结果消息 */
    ResultMessage?: string;
    /** 错误信息 */
    ErrorMessage?: string;
    /** 是否已读 */
    IsRead?: boolean;
}

// ============================================================
// I18n
// ============================================================

/** CronTask 相关国际化文本 */
export interface CronTaskI18n {
    /* 面板 */
    panelTitle?: string;
    /** 面板标题旁问号 tooltip 内容（对齐 webim："设置定时任务，系统将按计划自动执行"） */
    panelTip?: string;
    empty?: string;
    /** 空态提示末尾（用于"点击 {createTask} {emptySuffix}"分段），如"开始" */
    emptySuffix?: string;
    createTask?: string;
    createByNlp?: string;
    createManual?: string;
    loadMore?: string;
    loading?: string;
    loadFailed?: string;

    /* 卡片 */
    running?: string;
    paused?: string;
    completed?: string;
    successCount?: string;
    failureCount?: string;
    nextRun?: string;
    lastRun?: string;
    edit?: string;
    del?: string;
    pause?: string;
    resume?: string;
    runNow?: string;
    detail?: string;

    /* 详情 */
    backToList?: string;
    prompt?: string;
    schedule?: string;
    runLog?: string;
    noRunLog?: string;
    viewSession?: string;
    unread?: string;
    /** 执行记录标题 */
    executionRecordTitle?: string;
    /** 全部标记已读 */
    markAllRead?: string;
    /** 没有更多了 */
    noMore?: string;

    /* 创建/编辑对话框 */
    dialogTitleCreate?: string;
    dialogTitleEdit?: string;
    taskNameLabel?: string;
    taskNamePlaceholder?: string;
    promptLabel?: string;
    promptPlaceholder?: string;
    frequencyLabel?: string;
    freqDaily?: string;
    freqWeekly?: string;
    freqInterval?: string;
    freqOnce?: string;
    freqCron?: string;
    timeLabel?: string;
    weekdaysLabel?: string;
    intervalLabel?: string;
    intervalSeconds?: string;
    onceExecuteAtLabel?: string;
    cronExpressionLabel?: string;
    cronPlaceholder?: string;
    cronInvalid?: string;
    timezoneLabel?: string;
    pushLabel?: string;
    pushNone?: string;
    pushWechat?: string;
    pushWecomBot?: string;
    webhookUrlLabel?: string;
    webhookUrlPlaceholder?: string;
    modelLabel?: string;
    /** 模型选择器占位文案 */
    modelSelectPlaceholder?: string;
    conversationLabel?: string;
    conversationPlaceholder?: string;
    /** 校验：选择推送渠道但未选择会话时的提示 */
    conversationRequired?: string;
    /** 会话列表加载中 */
    conversationLoading?: string;
    /** 会话列表为空 */
    conversationEmpty?: string;
    save?: string;
    cancel?: string;
    confirm?: string;

    /* 删除对话框 */
    deleteDialogTitle?: string;
    deleteDialogContent?: string;

    /* 消息提示 */
    createSuccess?: string;
    createFailed?: string;
    updateSuccess?: string;
    updateFailed?: string;
    deleteSuccess?: string;
    deleteFailed?: string;
    pauseSuccess?: string;
    pauseFailed?: string;
    resumeSuccess?: string;
    resumeFailed?: string;
    runNowSuccess?: string;
    runNowFailed?: string;

    /* 星期 */
    weekdayNames?: string[];
    /* 相对时间 */
    today?: string;
    daysAgo?: string;

    /* 单次执行状态（TimerRunStatus 映射） */
    /** PENDING（等待执行） */
    runStatusPending?: string;
    /** RUNNING（执行中） */
    runStatusRunning?: string;
    /** RETRY_WAIT（等待重试） */
    runStatusRetryWait?: string;
    /** SUCCESS（执行成功） */
    runStatusSuccess?: string;
    /** DEAD / FAILED（执行失败） */
    runStatusFailed?: string;
    /** CANCELLED（已取消） */
    runStatusCancelled?: string;

    /* 通用操作 */
    /** 刷新按钮 tooltip */
    refresh?: string;
    /** 关闭按钮 tooltip */
    close?: string;
    /** 未命名任务兜底 */
    unnamedTask?: string;
}

/** CronTask i18n 中文默认值 */
export const defaultCronTaskI18n: Required<CronTaskI18n> = {
    panelTitle: '定时任务',
    panelTip: '设置定时任务，系统将按计划自动执行',
    empty: '没有进行中的任务，点击',
    emptySuffix: '开始',
    createTask: '新建',
    createByNlp: '智能生成',
    createManual: '手动创建',
    loadMore: '加载更多',
    loading: '加载中',
    loadFailed: '加载失败',

    running: '运行中',
    paused: '已暂停',
    completed: '已完成',
    successCount: '成功',
    failureCount: '失败',
    nextRun: '下次执行',
    lastRun: '上次执行',
    edit: '编辑',
    del: '删除',
    pause: '暂停',
    resume: '恢复',
    runNow: '立即执行',
    detail: '详情',

    backToList: '返回列表',
    prompt: '提示词',
    schedule: '调度设置',
    runLog: '执行记录',
    noRunLog: '暂无执行记录',
    viewSession: '查看会话',
    unread: '未读',
    executionRecordTitle: '执行记录',
    markAllRead: '全部标记已读',
    noMore: '没有更多了',

    dialogTitleCreate: '新建定时任务',
    dialogTitleEdit: '编辑定时任务',
    taskNameLabel: '任务名称',
    taskNamePlaceholder: '请输入任务名称',
    promptLabel: '提示词',
    promptPlaceholder: '请输入提示词',
    frequencyLabel: '执行频率',
    freqDaily: '每天',
    freqWeekly: '每周',
    freqInterval: '间隔',
    freqOnce: '一次性',
    freqCron: 'Cron 表达式',
    timeLabel: '执行时间',
    weekdaysLabel: '星期',
    intervalLabel: '间隔',
    intervalSeconds: '秒',
    onceExecuteAtLabel: '执行时间',
    cronExpressionLabel: 'Cron 表达式',
    cronPlaceholder: '例如: 0 9 * * 1（每周一 9 点）',
    cronInvalid: 'Cron 表达式无效，应为 5 段（分 时 日 月 周）',
    timezoneLabel: '时区',
    pushLabel: '通知渠道',
    pushNone: '不通知',
    pushWechat: '微信',
    pushWecomBot: '企微机器人',
    webhookUrlLabel: 'Webhook 地址',
    webhookUrlPlaceholder: '请输入企微机器人 Webhook URL',
    modelLabel: '模型',
    modelSelectPlaceholder: '选择模型',
    conversationLabel: '选择会话',
    conversationPlaceholder: '请选择会话',
    conversationRequired: '请选择推送会话',
    conversationLoading: '加载中',
    conversationEmpty: '暂无可选会话',
    save: '保存',
    cancel: '取消',
    confirm: '确认',

    deleteDialogTitle: '删除定时任务',
    deleteDialogContent: '删除后不可恢复，确定删除该定时任务吗？',

    createSuccess: '创建成功',
    createFailed: '创建失败',
    updateSuccess: '更新成功',
    updateFailed: '更新失败',
    deleteSuccess: '删除成功',
    deleteFailed: '删除失败',
    pauseSuccess: '已暂停',
    pauseFailed: '暂停失败',
    resumeSuccess: '已恢复',
    resumeFailed: '恢复失败',
    runNowSuccess: '已触发执行',
    runNowFailed: '触发执行失败',

    weekdayNames: ['日', '一', '二', '三', '四', '五', '六'],
    today: '今天',
    daysAgo: '天前',

    runStatusPending: '等待执行',
    runStatusRunning: '执行中',
    runStatusRetryWait: '等待重试',
    runStatusSuccess: '执行成功',
    runStatusFailed: '执行失败',
    runStatusCancelled: '已取消',

    refresh: '刷新',
    close: '关闭',
    unnamedTask: '未命名任务',
};

/** CronTask i18n 英文默认值 */
export const defaultCronTaskI18nEn: Required<CronTaskI18n> = {
    panelTitle: 'Scheduled Tasks',
    panelTip: 'Set up scheduled tasks to run automatically on schedule.',
    empty: 'No active tasks. Click',
    emptySuffix: 'to start',
    createTask: 'New',
    createByNlp: 'Create with AI',
    createManual: 'Manual',
    loadMore: 'Load more',
    loading: 'Loading',
    loadFailed: 'Load failed',

    running: 'Running',
    paused: 'Paused',
    completed: 'Completed',
    successCount: 'Success',
    failureCount: 'Failed',
    nextRun: 'Next run',
    lastRun: 'Last run',
    edit: 'Edit',
    del: 'Delete',
    pause: 'Pause',
    resume: 'Resume',
    runNow: 'Run now',
    detail: 'Detail',

    backToList: 'Back',
    prompt: 'Prompt',
    schedule: 'Schedule',
    runLog: 'Run Logs',
    noRunLog: 'No run logs yet',
    viewSession: 'View session',
    unread: 'Unread',
    executionRecordTitle: 'Execution Records',
    markAllRead: 'Mark all as read',
    noMore: 'No more',

    dialogTitleCreate: 'New Scheduled Task',
    dialogTitleEdit: 'Edit Scheduled Task',
    taskNameLabel: 'Task Name',
    taskNamePlaceholder: 'Enter task name',
    promptLabel: 'Prompt',
    promptPlaceholder: 'Enter prompt',
    frequencyLabel: 'Frequency',
    freqDaily: 'Daily',
    freqWeekly: 'Weekly',
    freqInterval: 'Interval',
    freqOnce: 'Once',
    freqCron: 'Cron',
    timeLabel: 'Time',
    weekdaysLabel: 'Weekdays',
    intervalLabel: 'Interval',
    intervalSeconds: 'seconds',
    onceExecuteAtLabel: 'Execute at',
    cronExpressionLabel: 'Cron Expression',
    cronPlaceholder: 'e.g. 0 9 * * 1 (Every Monday 9:00)',
    cronInvalid: 'Invalid cron expression. Expect 5 fields (min hour day month weekday).',
    timezoneLabel: 'Timezone',
    pushLabel: 'Notification',
    pushNone: 'None',
    pushWechat: 'WeChat',
    pushWecomBot: 'WeCom Bot',
    webhookUrlLabel: 'Webhook URL',
    webhookUrlPlaceholder: 'Enter WeCom bot webhook URL',
    modelLabel: 'Model',
    modelSelectPlaceholder: 'Select model',
    conversationLabel: 'Conversation',
    conversationPlaceholder: 'Select conversation',
    conversationRequired: 'Please select a conversation to push to',
    conversationLoading: 'Loading',
    conversationEmpty: 'No conversations available',
    save: 'Save',
    cancel: 'Cancel',
    confirm: 'Confirm',

    deleteDialogTitle: 'Delete Scheduled Task',
    deleteDialogContent: 'This action cannot be undone. Delete this task?',

    createSuccess: 'Created',
    createFailed: 'Create failed',
    updateSuccess: 'Updated',
    updateFailed: 'Update failed',
    deleteSuccess: 'Deleted',
    deleteFailed: 'Delete failed',
    pauseSuccess: 'Paused',
    pauseFailed: 'Pause failed',
    resumeSuccess: 'Resumed',
    resumeFailed: 'Resume failed',
    runNowSuccess: 'Triggered',
    runNowFailed: 'Trigger failed',

    weekdayNames: ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'],
    today: 'Today',
    daysAgo: 'd ago',

    runStatusPending: 'Pending',
    runStatusRunning: 'Running',
    runStatusRetryWait: 'Retry Waiting',
    runStatusSuccess: 'Success',
    runStatusFailed: 'Failed',
    runStatusCancelled: 'Cancelled',

    refresh: 'Refresh',
    close: 'Close',
    unnamedTask: 'Untitled task',
};

/** 按语言选取默认 i18n */
export const getCronTaskI18nByLanguage = (language: string): Required<CronTaskI18n> => {
    return language && language.startsWith('en') ? defaultCronTaskI18nEn : defaultCronTaskI18n;
};
