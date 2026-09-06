/**
 * 应用触发器（AppTrigger）相关类型定义
 * 对应后端 proto: trpc.adp.time_scheduler (AppTrigger 系列)
 *
 * 从旧 TimerTask 接口体系迁移而来，统一使用新 AppTrigger 接口。
 * 仅包含 ACC 实际使用的 Scheduled + Prompt 分支，Webhook + Workflow 预留类型已裁切。
 */

// ============================================================
// 枚举（来自 proto）
// ============================================================

/** 触发器类型 */
export const AppTriggerType = {
    UNSPECIFIED: 0,
    /** 定时触发 — ACC 仅使用此类型 */
    SCHEDULED: 1,
    /** Webhook 触发 — 预留 */
    WEBHOOK: 2,
} as const;
export type AppTriggerTypeValue = typeof AppTriggerType[keyof typeof AppTriggerType];

/** 执行类型 */
export const AppTriggerExecuteType = {
    UNSPECIFIED: 0,
    /** 指令执行 — ACC 仅使用此类型 */
    PROMPT: 1,
    /** 工作流执行 — 预留 */
    WORKFLOW: 2,
} as const;
export type AppTriggerExecuteTypeValue = typeof AppTriggerExecuteType[keyof typeof AppTriggerExecuteType];

/** 触发器状态 */
export const AppTriggerStatus = {
    UNSPECIFIED: 0,
    /** 启用（对应旧 ACTIVE） */
    ENABLED: 1,
    /** 暂停 */
    PAUSED: 2,
    /** 已删除（对应旧 COMPLETED） */
    DELETED: 3,
} as const;
export type AppTriggerStatusValue = typeof AppTriggerStatus[keyof typeof AppTriggerStatus];

/** 触发器触发来源（运行日志用） */
export const AppTriggerFireType = {
    UNSPECIFIED: 0,
    /** 定时触发 */
    SCHEDULED: 1,
    /** Webhook 触发 */
    WEBHOOK: 2,
    /** 手动立即执行 */
    MANUAL_RUN: 3,
    /** 测试执行 */
    TEST_RUN: 4,
} as const;
export type AppTriggerFireTypeValue = typeof AppTriggerFireType[keyof typeof AppTriggerFireType];

/** 作用域 */
export const AppTriggerScope = {
    UNSPECIFIED: 0,
    /** B 端管理员 — ACC 固定使用此值 */
    APP: 1,
    /** C 端访客 */
    USER: 2,
} as const;
export type AppTriggerScopeValue = typeof AppTriggerScope[keyof typeof AppTriggerScope];

/** 实例来源 */
export const AppTriggerInstanceSource = {
    UNSPECIFIED: 0,
    /** 来源于应用触发器 */
    APP_TRIGGER: 1,
} as const;
export type AppTriggerInstanceSourceValue = typeof AppTriggerInstanceSource[keyof typeof AppTriggerInstanceSource];

// ============================================================
// 运行时状态枚举（复用 proto 原有 TimerRunStatus / TimerRunPushStatus）
// 与 cronTask.ts 中共用一份类型，不在 appTrigger.ts 中重复定义，
// 使用时直接从 cronTask 导入：
//   import { TimerRunStatus, TimerRunPushStatus } from './cronTask';
// ============================================================

// ============================================================
// 调度 & 推送配置（复用旧结构体，仅多一层包装）
// ============================================================

// TimerScheduleConfig / TimerPushConfig / 相关子类型均从 cronTask.ts 导入
// 此处仅定义 AppTrigger 专属的包装层

import type {
    TimerScheduleConfig,
    TimerPushConfig,
} from './cronTask';

/** 定时触发器配置包装 */
export interface AppTriggerScheduleConfig {
    /** 调度配置，直接复用 TimerScheduleConfig */
    Schedule: TimerScheduleConfig;
}

/** 定时触发器运行态信息（oneof trigger_status → scheduled_status） */
export interface AppTriggerScheduleStatus {
    /** ISO8601，下一次计划触发时间 */
    NextFireTime: string;
    /** ISO8601，上一次实际触发时间 */
    LastFireTime: string;
    /** 调度策略人话摘要 */
    PolicySummary: string;
}

// ============================================================
// 执行配置（仅 Prompt 分支）
// ============================================================

/** 指令执行配置 */
export interface AppTriggerPromptExecuteConfig {
    /** 指令模板 */
    ExecutePrompt: string;
    /** API 参数绑定（本次不实现，留空） */
    ParamBindingsApi?: AppTriggerParamBindingConfig;
    /**
     * 模型 ID（按 webim 惯例透传扩展字段）
     * proto AppTriggerPromptExecuteConfig 未显式定义，
     * 后端识别则消费、不识别则忽略。
     */
    ModelId?: string;
}

/** 参数绑定配置（预留） */
export interface AppTriggerParamBindingConfig {
    ParamList?: AppTriggerParamBinding[];
}

/** 单个参数绑定（预留） */
export interface AppTriggerParamBinding {
    ParamName: string;
    ParamType: number;
    ParamValue?: string;
    VariableName?: string;
}

// ============================================================
// oneof 包装类型（proto 更新后 oneof 不再平铺在顶层）
// ============================================================

/** 触发器配置包装（oneof trigger_config 载体） */
export interface TriggerConfigMessage {
    // ACC 仅使用 scheduled_config 分支
    ScheduledConfig?: AppTriggerScheduleConfig;
}

/** 执行配置包装（oneof execute_config 载体） */
export interface ExecuteConfigMessage {
    // ACC 仅使用 prompt_config 分支
    PromptConfig?: AppTriggerPromptExecuteConfig;
}

/** 触发器运行状态包装（oneof trigger_status 载体） */
export interface TriggerStatusMessage {
    // ACC 仅使用 scheduled_status 分支
    ScheduledStatus?: AppTriggerScheduleStatus;
}

// ============================================================
// 核心数据结构
// ============================================================

/** 应用触发器完整视图（DescribeAppTrigger 返回） */
export interface AppTrigger {
    TriggerId: string;
    AppId: number;
    TriggerName: string;
    TriggerType: AppTriggerTypeValue;
    ExecuteType: AppTriggerExecuteTypeValue;
    PushConfig?: TimerPushConfig;
    Status: AppTriggerStatusValue;
    SuccessCount: number;
    FailedCount: number;
    // oneof 包装在 TriggerConfig message 中
    TriggerConfig?: TriggerConfigMessage;
    // oneof 包装在 ExecuteConfig message 中
    ExecuteConfig?: ExecuteConfigMessage;
    // oneof 包装在 TriggerStatus message 中
    TriggerStatus?: TriggerStatusMessage;
    Scope: AppTriggerScopeValue;
    UserId?: string;
}

/** 触发器列表轻量视图（DescribeAppTriggerSummaryList 返回） */
export interface AppTriggerSummary {
    TriggerId: string;
    AppId: number;
    TriggerName: string;
    TriggerType: AppTriggerTypeValue;
    ExecuteType: AppTriggerExecuteTypeValue;
    Status: AppTriggerStatusValue;
    /** 未读运行记录条数（扁平化到顶层） */
    UnreadRunLogCount: number;
    SuccessCount: number;
    FailedCount: number;
    /** 最近一次执行 SessionID，跳转用（扁平化到顶层） */
    LastSessionId: string;
    // oneof 包装在 TriggerStatus message 中
    TriggerStatus?: TriggerStatusMessage;
    Scope: AppTriggerScopeValue;
    UserId?: string;
}

/** 触发器运行日志（DescribeAppTriggerRunLogList 返回） */
export interface AppTriggerRunLog {
    InstanceId: string;
    TriggerId: string;
    FireType: AppTriggerFireTypeValue;
    ScheduledFireTime: string;
    StartTime: string;
    EndTime: string;
    DurationMs: number;
    /** 执行状态，值为 TimerRunStatus 枚举值 */
    Status: number;
    ResultCode: string;
    ResultSummary: string;
    /** ⚠️ 对应旧字段 SessionId，跳转会话时使用此字段 */
    ConversationId: string;
    /** 应用运行 ID（新增字段） */
    RunId: string;
    /** 工作流运行 ID（新增字段，仅 Workflow 执行时有值） */
    WorkflowRunId: string;
    Unread: boolean;
    /** 推送状态，值为 TimerRunPushStatus 枚举值 */
    PushStatus: number;
    Scope: AppTriggerScopeValue;
    UserId?: string;
}

/** 触发器执行实例详情（DescribeAppTriggerInstance 返回） */
export interface AppTriggerInstance {
    InstanceId: string;
    TriggerId: string;
    AppId: number;
    Source: AppTriggerInstanceSourceValue;
    /** 执行状态，值为 TimerRunStatus 枚举值 */
    Status: number;
    ResultCode: string;
    ResultSummary: string;
    ConversationId: string;
    RunId: string;
    WorkflowRunId: string;
    TraceId: string;
    RequestId: string;
    CreatedAt: string;
    StartedAt: string;
    FinishedAt: string;
    Scope: AppTriggerScopeValue;
    UserId?: string;
}

// ============================================================
// 国际化
// ============================================================

/** 应用触发器相关国际化文本 */
export interface AppTriggerI18n {
    /* 面板 */
    panelTitle?: string;
    panelHelp?: string;
    createButton?: string;
    noTriggers?: string;
    noTriggersHint?: string;

    /* 卡片 */
    statusEnabled?: string;
    statusPaused?: string;
    pauseAction?: string;
    resumeAction?: string;
    editAction?: string;
    deleteAction?: string;
    runNowAction?: string;

    /* 创建 / 编辑弹窗 */
    createTitle?: string;
    editTitle?: string;
    triggerName?: string;
    triggerNamePlaceholder?: string;
    triggerNameRequired?: string;
    promptLabel?: string;
    promptPlaceholder?: string;
    promptRequired?: string;
    frequencyLabel?: string;
    pushChannelLabel?: string;
    submitCreate?: string;
    submitEdit?: string;
    cancel?: string;

    /* 详情 */
    backToList?: string;
    promptArea?: string;
    scheduleInfo?: string;
    nextFireTime?: string;
    lastFireTime?: string;
    noFireYet?: string;

    /* 运行日志 */
    runLogTitle?: string;
    markAllRead?: string;
    noLogs?: string;
    logStatus?: Record<number, string>;
    fireType?: Record<number, string>;
    viewConversation?: string;

    /* 删除 */
    deleteConfirmTitle?: string;
    deleteConfirmContent?: string;
    deleteSuccess?: string;

    /* 操作反馈 */
    pauseSuccess?: string;
    resumeSuccess?: string;
    runNowSuccess?: string;

    /* 实例详情 */
    instanceDetail?: string;
    instanceSource?: string;
    instanceStatus?: string;
    instanceResultCode?: string;
    instanceResultSummary?: string;
    instanceTimeLine?: string;
    instanceCreatedAt?: string;
    instanceStartedAt?: string;
    instanceFinishedAt?: string;
    instanceConversationId?: string;
    instanceRunId?: string;
    instanceWorkflowRunId?: string;
    instanceTraceId?: string;
    instanceRequestId?: string;
    instanceCopySuccess?: string;

    /* 加载状态 */
    loading?: string;
    loadFailed?: string;
}

/** AppTrigger i18n 中文默认值 */
export const defaultAppTriggerI18n: Required<AppTriggerI18n> = {
    panelTitle: '应用触发器',
    panelHelp: '定时自动执行预设提示词或工作流，并将结果推送到指定渠道',
    createButton: '手动创建',
    noTriggers: '暂无触发器',
    noTriggersHint: '点击上方按钮创建第一个定时触发器',

    statusEnabled: '运行中',
    statusPaused: '已暂停',
    pauseAction: '暂停',
    resumeAction: '恢复',
    editAction: '编辑',
    deleteAction: '删除',
    runNowAction: '立即执行',

    createTitle: '创建定时触发器',
    editTitle: '编辑定时触发器',
    triggerName: '触发器名称',
    triggerNamePlaceholder: '请输入触发器名称',
    triggerNameRequired: '请输入触发器名称',
    promptLabel: '执行指令',
    promptPlaceholder: '请输入定时执行的提示词',
    promptRequired: '请输入执行指令',
    frequencyLabel: '执行频率',
    pushChannelLabel: '推送渠道',
    submitCreate: '创建',
    submitEdit: '保存',
    cancel: '取消',

    backToList: '返回列表',
    promptArea: '执行指令',
    scheduleInfo: '调度信息',
    nextFireTime: '下次触发时间',
    lastFireTime: '上次触发时间',
    noFireYet: '尚未触发',

    runLogTitle: '运行日志',
    markAllRead: '全部已读',
    noLogs: '暂无运行日志',
    logStatus: {
        0: '未知',
        1: '等待执行',
        2: '执行中',
        3: '等待重试',
        4: '执行成功',
        5: '执行失败',
        6: '已取消',
    },
    fireType: {
        1: '定时触发',
        2: 'Webhook',
        3: '手动执行',
        4: '测试执行',
    },
    viewConversation: '查看对话',

    deleteConfirmTitle: '确认删除',
    deleteConfirmContent: '删除后，该触发器的所有配置和运行记录将被清除，已生成的消息不受影响，确定要删除吗？',
    deleteSuccess: '删除成功',

    pauseSuccess: '已暂停',
    resumeSuccess: '已恢复',
    runNowSuccess: '已触发执行',

    instanceDetail: '执行实例详情',
    instanceSource: '触发来源',
    instanceStatus: '执行状态',
    instanceResultCode: '结果码',
    instanceResultSummary: '结果摘要',
    instanceTimeLine: '执行时间线',
    instanceCreatedAt: '创建时间',
    instanceStartedAt: '开始时间',
    instanceFinishedAt: '结束时间',
    instanceConversationId: '对话 ID',
    instanceRunId: '运行 ID',
    instanceWorkflowRunId: '工作流运行 ID',
    instanceTraceId: '追踪 ID',
    instanceRequestId: '请求 ID',
    instanceCopySuccess: '已复制',

    loading: '加载中',
    loadFailed: '加载失败',
};

/** AppTrigger i18n 英文默认值 */
export const defaultAppTriggerI18nEn: Required<AppTriggerI18n> = {
    panelTitle: 'App Triggers',
    panelHelp: 'Automatically execute preset prompts or workflows on schedule and push results to designated channels',
    createButton: 'Create Manually',
    noTriggers: 'No triggers yet',
    noTriggersHint: 'Click the button above to create your first scheduled trigger',

    statusEnabled: 'Running',
    statusPaused: 'Paused',
    pauseAction: 'Pause',
    resumeAction: 'Resume',
    editAction: 'Edit',
    deleteAction: 'Delete',
    runNowAction: 'Run Now',

    createTitle: 'Create Scheduled Trigger',
    editTitle: 'Edit Scheduled Trigger',
    triggerName: 'Trigger Name',
    triggerNamePlaceholder: 'Enter trigger name',
    triggerNameRequired: 'Trigger name is required',
    promptLabel: 'Execute Prompt',
    promptPlaceholder: 'Enter the prompt to execute on schedule',
    promptRequired: 'Execute prompt is required',
    frequencyLabel: 'Frequency',
    pushChannelLabel: 'Push Channel',
    submitCreate: 'Create',
    submitEdit: 'Save',
    cancel: 'Cancel',

    backToList: 'Back to List',
    promptArea: 'Execute Prompt',
    scheduleInfo: 'Schedule Information',
    nextFireTime: 'Next Fire Time',
    lastFireTime: 'Last Fire Time',
    noFireYet: 'Not fired yet',

    runLogTitle: 'Run Logs',
    markAllRead: 'Mark All Read',
    noLogs: 'No run logs yet',
    logStatus: {
        0: 'Unknown',
        1: 'Pending',
        2: 'Running',
        3: 'Retry Waiting',
        4: 'Success',
        5: 'Failed',
        6: 'Cancelled',
    },
    fireType: {
        1: 'Scheduled',
        2: 'Webhook',
        3: 'Manual Run',
        4: 'Test Run',
    },
    viewConversation: 'View Conversation',

    deleteConfirmTitle: 'Confirm Delete',
    deleteConfirmContent: 'After deletion, all configurations and run records for this trigger will be cleared. Existing messages will not be affected. Are you sure?',
    deleteSuccess: 'Deleted successfully',

    pauseSuccess: 'Paused',
    resumeSuccess: 'Resumed',
    runNowSuccess: 'Triggered',

    instanceDetail: 'Instance Details',
    instanceSource: 'Source',
    instanceStatus: 'Status',
    instanceResultCode: 'Result Code',
    instanceResultSummary: 'Result Summary',
    instanceTimeLine: 'Timeline',
    instanceCreatedAt: 'Created At',
    instanceStartedAt: 'Started At',
    instanceFinishedAt: 'Finished At',
    instanceConversationId: 'Conversation ID',
    instanceRunId: 'Run ID',
    instanceWorkflowRunId: 'Workflow Run ID',
    instanceTraceId: 'Trace ID',
    instanceRequestId: 'Request ID',
    instanceCopySuccess: 'Copied',

    loading: 'Loading',
    loadFailed: 'Load failed',
};

/** 按语言选取 AppTrigger 默认 i18n */
export const getAppTriggerI18nByLanguage = (language: string): Required<AppTriggerI18n> => {
    return language && language.startsWith('en') ? defaultAppTriggerI18nEn : defaultAppTriggerI18n;
};
