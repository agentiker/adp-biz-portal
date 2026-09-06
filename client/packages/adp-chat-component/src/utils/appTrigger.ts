/**
 * AppTrigger 相关工具函数
 *
 * 兼容层：提供与 cronTask.ts 工具函数相同签名的取值函数，
 * 使得现有 Vue 组件调用 getTaskName() / getPolicySummary() 等可平滑适配 AppTrigger 新结构。
 *
 * 设计目标：
 * 1. 优先按 AppTrigger 字段路径取值
 * 2. 当数据是旧 TimerTask 结构时也能兼容回退（双重兼容）
 */

import { pickField } from './cronTask';

// ============================================================
// 基础取值工具
// ============================================================

/**
 * 检查对象是否为 AppTrigger 结构（有 TriggerId + TriggerConfig）
 */
export function isAppTrigger(obj: any): boolean {
    if (!obj || typeof obj !== 'object') return false;
    return obj.TriggerId !== undefined && (obj.TriggerConfig !== undefined || obj.TriggerStatus !== undefined);
}

/**
 * 检查对象是否为 AppTriggerSummary 结构
 */
export function isAppTriggerSummary(obj: any): boolean {
    if (!obj || typeof obj !== 'object') return false;
    return obj.TriggerId !== undefined && obj.TriggerType !== undefined;
}

// ============================================================
// 字段取值（AppTrigger 优先 + 旧 TimerTask 回退）
// ============================================================

/** 获取触发器 ID */
export function getTriggerId(item: any): string {
    if (item?.TriggerId) return item.TriggerId;
    // 回退：旧 TimerTask
    return pickField<string>(item, 'timer_id', 'TimerId') || '';
}

/** 获取触发器名称 */
export function getTriggerName(item: any): string {
    if (item?.TriggerName) return item.TriggerName;
    // 回退：旧 TimerTask → Profile.TaskName
    const top = pickField<string>(item, 'task_name', 'TaskName');
    if (top) return top;
    const profile = pickField<any>(item, 'profile', 'Profile');
    if (profile) {
        return pickField<string>(profile, 'task_name', 'TaskName') || '';
    }
    return '';
}

/** 获取调度策略摘要 */
export function getTriggerPolicySummary(item: any): string {
    // 新版：TriggerStatus.ScheduledStatus.PolicySummary
    if (item?.TriggerStatus?.ScheduledStatus?.PolicySummary)
        return item.TriggerStatus.ScheduledStatus.PolicySummary;
    // 兼容旧版：ScheduledStatus.PolicySummary（平铺）
    if (item?.ScheduledStatus?.PolicySummary) return item.ScheduledStatus.PolicySummary;
    // 回退：旧版顶层 policy_summary
    const top = pickField<string>(item, 'policy_summary', 'PolicySummary');
    if (top) return top;
    const status = pickField<any>(item, 'status', 'Status');
    if (status) return pickField<string>(status, 'policy_summary', 'PolicySummary') || '';
    return '';
}

/** 获取触发器状态枚举值 */
export function getTriggerStatus(item: any): number {
    if (item?.Status !== undefined) {
        const s = Number(item.Status);
        if (s > 0) return s;
    }
    // 回退：旧 TimerTask → Status.Status
    const status = pickField<any>(item, 'status', 'Status');
    if (status) return Number(pickField<number>(status, 'status', 'Status') || 0);
    return 0;
}

/** 获取成功次数 */
export function getTriggerSuccessCount(item: any): number {
    if (item?.SuccessCount !== undefined) return Number(item.SuccessCount);
    const status = pickField<any>(item, 'status', 'Status');
    if (status) return Number(pickField<number>(status, 'success_count', 'SuccessCount') || 0);
    return 0;
}

/** 获取失败次数 */
export function getTriggerFailureCount(item: any): number {
    if (item?.FailedCount !== undefined) return Number(item.FailedCount);
    const status = pickField<any>(item, 'status', 'Status');
    if (status) {
        return Number(
            pickField<number>(status, 'failed_count', 'FailedCount') ??
            pickField<number>(status, 'failure_count', 'FailureCount') ?? 0
        );
    }
    return 0;
}

/** 获取未读运行记录条数 */
export function getTriggerUnreadCount(item: any): number {
    if (item?.UnreadRunLogCount !== undefined) return Number(item.UnreadRunLogCount);
    const status = pickField<any>(item, 'status', 'Status');
    if (status) return Number(pickField<number>(status, 'unread_count', 'UnreadCount') || 0);
    return 0;
}

/** 获取下一次触发时间 */
export function getTriggerNextFireTime(item: any): string {
    // 新版：TriggerStatus.ScheduledStatus.NextFireTime
    if (item?.TriggerStatus?.ScheduledStatus?.NextFireTime)
        return item.TriggerStatus.ScheduledStatus.NextFireTime;
    // 兼容旧版：ScheduledStatus.NextFireTime（平铺）
    if (item?.ScheduledStatus?.NextFireTime) return item.ScheduledStatus.NextFireTime;
    // 回退
    const status = pickField<any>(item, 'status', 'Status');
    if (status) return (pickField<string>(status, 'next_run_at', 'NextRunAt') || '') as string;
    return '';
}

/** 获取上一次触发时间 */
export function getTriggerLastFireTime(item: any): string {
    if (item?.TriggerStatus?.ScheduledStatus?.LastFireTime)
        return item.TriggerStatus.ScheduledStatus.LastFireTime;
    if (item?.ScheduledStatus?.LastFireTime) return item.ScheduledStatus.LastFireTime;
    const status = pickField<any>(item, 'status', 'Status');
    if (status) return (pickField<string>(status, 'last_run_at', 'LastRunAt') || '') as string;
    return '';
}

/** 获取最后一次执行的会话 ID */
export function getTriggerLastSessionId(item: any): string {
    if (item?.LastSessionId) return item.LastSessionId;
    const status = pickField<any>(item, 'status', 'Status');
    if (status) return (pickField<string>(status, 'last_session_id', 'LastSessionId') || '') as string;
    return '';
}

/** 获取提示词 / 执行指令内容 */
export function getTriggerPrompt(item: any): string {
    // 新版：ExecuteConfig.PromptConfig.ExecutePrompt
    if (item?.ExecuteConfig?.PromptConfig?.ExecutePrompt)
        return item.ExecuteConfig.PromptConfig.ExecutePrompt;
    // 兼容旧版：PromptConfig.ExecutePrompt（平铺）
    if (item?.PromptConfig?.ExecutePrompt) return item.PromptConfig.ExecutePrompt;
    // 回退：旧版 Profile.PromptContent
    const profile = pickField<any>(item, 'profile', 'Profile');
    if (profile) return (pickField<string>(profile, 'prompt_content', 'PromptContent') || '') as string;
    return '';
}

/** 获取调度配置 */
export function getTriggerScheduleConfig(item: any): any {
    // 新版：TriggerConfig.ScheduledConfig.Schedule
    if (item?.TriggerConfig?.ScheduledConfig?.Schedule)
        return item.TriggerConfig.ScheduledConfig.Schedule;
    // 兼容旧版：ScheduledConfig.Schedule（平铺）
    if (item?.ScheduledConfig?.Schedule) return item.ScheduledConfig.Schedule;
    // 回退：旧版 Config.Schedule
    const config = pickField<any>(item, 'config', 'Config');
    if (config) return pickField<any>(config, 'schedule', 'Schedule');
    return undefined;
}

/** 获取推送配置 */
export function getTriggerPushConfig(item: any): any {
    if (item?.PushConfig) return item.PushConfig;
    const config = pickField<any>(item, 'config', 'Config');
    if (config) return pickField<any>(config, 'push', 'Push');
    return undefined;
}

// ============================================================
// 运行日志取值
// ============================================================

/** 获取日志实例 ID */
export function getLogInstanceId(log: any): string {
    if (log?.InstanceId) return log.InstanceId;
    // 回退：旧版 LogId / FireInstanceId
    return pickField<string>(log, 'log_id', 'LogId') ||
        pickField<string>(log, 'fire_instance_id', 'FireInstanceId') || '';
}

/** 获取日志触发来源枚举值 */
export function getLogFireType(log: any): number {
    if (log?.FireType !== undefined) return Number(log.FireType);
    // 回退：旧版 TriggerType
    return Number(pickField<number>(log, 'trigger_type', 'TriggerType') || 0);
}

/** 获取日志关联会话 ID */
export function getLogConversationId(log: any): string {
    if (log?.ConversationId) return log.ConversationId;
    // 回退：旧版 SessionId
    return (pickField<string>(log, 'session_id', 'SessionId') || '') as string;
}

/** 获取日志运行 ID */
export function getLogRunId(log: any): string {
    return log?.RunId || '';
}

/** 获取日志工作流运行 ID */
export function getLogWorkflowRunId(log: any): string {
    return log?.WorkflowRunId || '';
}

/** 获取日志是否已读 */
export function getLogUnread(log: any): boolean {
    if (log?.Unread !== undefined) return Boolean(log.Unread);
    // 回退：旧版 IsRead 反向
    if (log?.IsRead !== undefined) return !log.IsRead;
    return false;
}

// ============================================================
// 状态文本映射
// ============================================================

import { AppTriggerStatus, AppTriggerFireType } from '../model/appTrigger';

/**
 * AppTriggerStatus 枚举 → 中文状态文本
 * @deprecated 建议使用 `getAppTriggerStatusText(status, language)` 支持国际化。
 *   本常量保留以兼容旧调用方（例如仅在中文场景下拼接展示的地方）。
 */
export const APP_TRIGGER_STATUS_TEXT: Record<number, string> = {
    [AppTriggerStatus.ENABLED]: '运行中',
    [AppTriggerStatus.PAUSED]: '已暂停',
    [AppTriggerStatus.DELETED]: '已删除',
};

/**
 * AppTriggerFireType 枚举 → 中文触发来源文本
 * @deprecated 建议使用 `getAppTriggerFireTypeText(type, language)` 支持国际化。
 */
export const APP_TRIGGER_FIRE_TYPE_TEXT: Record<number, string> = {
    [AppTriggerFireType.SCHEDULED]: '定时触发',
    [AppTriggerFireType.WEBHOOK]: 'Webhook',
    [AppTriggerFireType.MANUAL_RUN]: '手动执行',
    [AppTriggerFireType.TEST_RUN]: '测试执行',
};

/** AppTriggerStatus 枚举 → 英文状态文本 */
const APP_TRIGGER_STATUS_TEXT_EN: Record<number, string> = {
    [AppTriggerStatus.ENABLED]: 'Running',
    [AppTriggerStatus.PAUSED]: 'Paused',
    [AppTriggerStatus.DELETED]: 'Deleted',
};

/** AppTriggerFireType 枚举 → 英文触发来源文本 */
const APP_TRIGGER_FIRE_TYPE_TEXT_EN: Record<number, string> = {
    [AppTriggerFireType.SCHEDULED]: 'Scheduled',
    [AppTriggerFireType.WEBHOOK]: 'Webhook',
    [AppTriggerFireType.MANUAL_RUN]: 'Manual',
    [AppTriggerFireType.TEST_RUN]: 'Test',
};

function isEnglishLang(language?: string): boolean {
    return !!language && language.startsWith('en');
}

/**
 * 获取 AppTrigger 状态文本，按 language 返回中文/英文。
 */
export function getAppTriggerStatusText(status: number, language?: string): string {
    const map = isEnglishLang(language) ? APP_TRIGGER_STATUS_TEXT_EN : APP_TRIGGER_STATUS_TEXT;
    return map[status] || '';
}

/**
 * 获取 AppTrigger 触发来源文本，按 language 返回中文/英文。
 */
export function getAppTriggerFireTypeText(type: number, language?: string): string {
    const map = isEnglishLang(language) ? APP_TRIGGER_FIRE_TYPE_TEXT_EN : APP_TRIGGER_FIRE_TYPE_TEXT;
    return map[type] || '';
}
