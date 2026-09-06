/**
 * 应用触发器（AppTrigger）API 服务
 *
 * 所有请求通过 /adp 代理转发：
 *   POST { ApplicationId, Payload }
 *
 * 接口对应 proto: trpc.adp.time_scheduler (AppTrigger 系列)
 * 与旧 cronTaskApi.ts 接口一一对应，采用新 AppTrigger 数据结构。
 *
 * ⚠️ Scope / UserId 约定（对齐 proto trpc.adp.time_scheduler）：
 *   - proto 每个接口都携带 `AppTriggerScope scope` + `string user_id`。
 *   - scope=APP(1)：B 端管理员语义，user_id 可省略；后端按 app_id 维度分片 / 鉴权。
 *   - scope=USER(2)：C 端访客语义，user_id 必填；后端按 owner_user_id 分片 / 鉴权。
 * 前端约定：
 *   - api 层不做业务判断，Scope 与 UserId 全部由调用方决定。
 *   - Scope 默认 USER（当前业务以 C 端访客视角为主），UserId 默认不带（`undefined` 不塞进 Payload）。
 *   - USER 场景需同时传非空 `userId`；APP 场景显式传 `scope=AppTriggerScope.APP`，userId 可省略。
 */
import { httpService } from './httpService';
import { defaultApiDetailConfig } from './api';
import { AppTriggerScope } from '../model/appTrigger';
import type {
    AppTrigger,
    AppTriggerSummary,
    AppTriggerRunLog,
    AppTriggerInstance,
} from '../model/appTrigger';
import type { TimerScheduleConfig, TimerPushConfig } from '../model/cronTask';

// ============================================================
// API 路径定义
// ============================================================

/** AppTrigger 相关 API 路径 */
export interface AppTriggerApiPaths {
    createAppTriggerApi?: string;
    modifyAppTriggerApi?: string;
    describeAppTriggerApi?: string;
    describeAppTriggerSummaryListApi?: string;
    pauseAppTriggerApi?: string;
    resumeAppTriggerApi?: string;
    deleteAppTriggerApi?: string;
    runAppTriggerNowApi?: string;
    describeAppTriggerRunLogListApi?: string;
    markAppTriggerRunLogReadApi?: string;
    describeAppTriggerInstanceApi?: string;
}

export const defaultAppTriggerApiPaths: Required<AppTriggerApiPaths> = {
    createAppTriggerApi: '/adp/CreateAppTrigger',
    modifyAppTriggerApi: '/adp/ModifyAppTrigger',
    describeAppTriggerApi: '/adp/DescribeAppTrigger',
    describeAppTriggerSummaryListApi: '/adp/DescribeAppTriggerSummaryList',
    pauseAppTriggerApi: '/adp/PauseAppTrigger',
    resumeAppTriggerApi: '/adp/ResumeAppTrigger',
    deleteAppTriggerApi: '/adp/DeleteAppTrigger',
    runAppTriggerNowApi: '/adp/RunAppTriggerNow',
    describeAppTriggerRunLogListApi: '/adp/DescribeAppTriggerRunLogList',
    markAppTriggerRunLogReadApi: '/adp/MarkAppTriggerRunLogRead',
    describeAppTriggerInstanceApi: '/adp/DescribeAppTriggerInstance',
};

// 合并到全局默认配置，供 useApiConfig 消费
Object.assign(defaultApiDetailConfig, defaultAppTriggerApiPaths);

// 让 ApiDetailConfig 类型层面也感知这些字段
declare module './api' {
    interface ApiDetailConfig extends AppTriggerApiPaths {}
}

// ============================================================
// 内部工具
// ============================================================

/**
 * 检查 /adp 代理返回的 Response 中是否有 Error
 * 有 Error 时抛出异常，否则返回 Response 对象
 */
function _checkResponse(data: any, action: string): any {
    const response = data?.Response ?? data ?? {};
    const err = response.Error;
    if (err && (err.Code || err.Message)) {
        throw new Error(`[${action}] ${err.Code || ''}: ${err.Message || ''}`);
    }
    return response;
}

/**
 * 将 (scope, userId) 归一化后并入 Payload：
 * - Scope 恒定写入（proto 允许 0=UNSPECIFIED，由后端按 APP 语义兜底）。
 * - UserId 仅在非空字符串时写入，避免 APP 场景带上冗余空串。
 */
function _mergeAuth<T extends Record<string, any>>(
    payload: T,
    scope: number,
    userId?: string,
): T & { Scope: number; UserId?: string } {
    const merged: T & { Scope: number; UserId?: string } = {
        ...payload,
        Scope: scope,
    };
    if (userId) merged.UserId = userId;
    return merged;
}

// ============================================================
// 请求 & 响应类型
// ============================================================

/** CreateAppTrigger 请求 Payload */
export interface CreateAppTriggerPayload {
    TriggerName: string;
    TriggerType: number;
    ExecuteType: number;
    PushConfig?: TimerPushConfig;
    TriggerConfig: { ScheduledConfig: { Schedule: TimerScheduleConfig } };
    ExecuteConfig: { PromptConfig: { ExecutePrompt: string; ParamBindingsApi?: any } };
    Scope: number;
    /** C 端访客 ID，scope=USER 时必填 */
    UserId?: string;
}

/** ModifyAppTrigger 请求 Payload */
export interface ModifyAppTriggerPayload {
    TriggerId: string;
    UpdateMask: { Paths: string[] };
    Trigger: Partial<AppTrigger>;
    Scope: number;
    /** C 端访客 ID，scope=USER 时必填 */
    UserId?: string;
}

/**
 * 列表通用过滤条件（对齐 proto trpc.adp.common.v2.Filter，PascalCase）。
 * 多个 Filter 之间为 AND 关系；同一 Filter 的 ValueList 多值为 OR 关系。
 */
export interface AppTriggerFilter {
    /** 过滤字段名，如 'Status' / 'HasRunHistory' */
    Name: string;
    /** 过滤值数组，如 ['1'] / ['true'] */
    ValueList: string[];
}

/** AppTriggerSummaryList 请求 Payload */
export interface DescribeAppTriggerSummaryListPayload {
    Query?: string;
    PageNumber: number;
    PageSize: number;
    Scope: number;
    /** C 端访客 ID，scope=USER 时按 owner_user_id 过滤 */
    UserId?: string;
    /**
     * 过滤条件列表（对齐 proto filter_list，支持 Status 等维度）。
     * 侧边栏「定时任务」分组用法（对齐 smart-webim）：
     *   Status=运行中(ENABLED=1) + HasRunHistory=有执行记录(true)。
     */
    FilterList?: AppTriggerFilter[];
}

/** AppTriggerRunLogList 请求 Payload */
export interface DescribeAppTriggerRunLogListPayload {
    TriggerId: string;
    PageNumber: number;
    PageSize: number;
    Scope: number;
    /** C 端访客 ID，scope=USER 时按 owner_user_id 过滤 */
    UserId?: string;
}

/** MarkAppTriggerRunLogRead 请求 Payload */
export interface MarkAppTriggerRunLogReadPayload {
    TriggerId: string;
    InstanceIdList: string[];
    Scope: number;
    /** C 端访客 ID，scope=USER 时必填 */
    UserId?: string;
}

// ============================================================
// 1. CreateAppTrigger — 创建触发器
// ============================================================

/**
 * 创建定时触发器
 *
 * ⚠️ Payload 内已含 Scope；UserId 若在 Payload 里已给出则直接使用，
 *   未给出时也可通过第 4 个位置参数 `userId` 显式补上（USER 场景常用）。
 * @returns 新建触发器 ID
 */
export async function createAppTrigger(
    payload: CreateAppTriggerPayload,
    applicationId: string,
    apiPath?: string,
    userId?: string,
): Promise<string> {
    const path = apiPath || defaultApiDetailConfig.createAppTriggerApi!;
    // 允许调用方在 payload 里已经带 UserId；此处仅在非空时兜底填入
    const finalPayload: CreateAppTriggerPayload = payload.UserId
        ? payload
        : (userId ? { ...payload, UserId: userId } : payload);
    const data = await httpService.post(path, {
        ApplicationId: applicationId,
        Payload: finalPayload,
    });
    const response = _checkResponse(data, 'CreateAppTrigger');
    return response.TriggerId;
}

// ============================================================
// 2. ModifyAppTrigger — 修改触发器
// ============================================================

/**
 * 修改触发器（⚠️ 返回空对象，无 next_fire_time）
 *
 * Scope / UserId 语义与 CreateAppTrigger 一致，见 payload.Scope / payload.UserId 或第 4 参数。
 */
export async function modifyAppTrigger(
    payload: ModifyAppTriggerPayload,
    applicationId: string,
    apiPath?: string,
    userId?: string,
): Promise<void> {
    const path = apiPath || defaultApiDetailConfig.modifyAppTriggerApi!;
    const finalPayload: ModifyAppTriggerPayload = payload.UserId
        ? payload
        : (userId ? { ...payload, UserId: userId } : payload);
    const data = await httpService.post(path, {
        ApplicationId: applicationId,
        Payload: finalPayload,
    });
    _checkResponse(data, 'ModifyAppTrigger');
}

// ============================================================
// 3. DescribeAppTrigger — 触发器详情
// ============================================================

/**
 * 获取触发器详情
 */
export async function describeAppTrigger(
    triggerId: string,
    applicationId: string,
    scope: number = AppTriggerScope.USER,
    apiPath?: string,
    userId?: string,
): Promise<AppTrigger> {
    const path = apiPath || defaultApiDetailConfig.describeAppTriggerApi!;
    const data = await httpService.post(path, {
        ApplicationId: applicationId,
        Payload: _mergeAuth({ TriggerId: triggerId }, scope, userId),
    });
    const response = _checkResponse(data, 'DescribeAppTrigger');
    return response.Trigger;
}

// ============================================================
// 4. DescribeAppTriggerSummaryList — 触发器列表
// ============================================================

/**
 * 获取触发器摘要列表（分页）
 *
 * ⚠️ USER 场景务必在 payload 里显式带上 UserId，或通过第 4 参数 userId 传入；
 *   否则后端会按 APP 维度返回全部触发器，语义不符预期。
 */
export async function describeAppTriggerSummaryList(
    payload: DescribeAppTriggerSummaryListPayload,
    applicationId: string,
    apiPath?: string,
    userId?: string,
): Promise<{ TotalCount: number; TriggerList: AppTriggerSummary[] }> {
    const path = apiPath || defaultApiDetailConfig.describeAppTriggerSummaryListApi!;
    const finalPayload: DescribeAppTriggerSummaryListPayload = payload.UserId
        ? payload
        : (userId ? { ...payload, UserId: userId } : payload);
    const data = await httpService.post(path, {
        ApplicationId: applicationId,
        Payload: finalPayload,
    });
    return _checkResponse(data, 'DescribeAppTriggerSummaryList');
}

// ============================================================
// 5. PauseAppTrigger — 暂停
// ============================================================

/**
 * 暂停触发器
 */
export async function pauseAppTrigger(
    triggerId: string,
    applicationId: string,
    scope: number = AppTriggerScope.USER,
    apiPath?: string,
    userId?: string,
): Promise<void> {
    const path = apiPath || defaultApiDetailConfig.pauseAppTriggerApi!;
    const data = await httpService.post(path, {
        ApplicationId: applicationId,
        Payload: _mergeAuth({ TriggerId: triggerId }, scope, userId),
    });
    _checkResponse(data, 'PauseAppTrigger');
}

// ============================================================
// 6. ResumeAppTrigger — 恢复
// ============================================================

/**
 * 恢复触发器（⚠️ 返回空对象，无 next_fire_time）
 */
export async function resumeAppTrigger(
    triggerId: string,
    applicationId: string,
    scope: number = AppTriggerScope.USER,
    apiPath?: string,
    userId?: string,
): Promise<void> {
    const path = apiPath || defaultApiDetailConfig.resumeAppTriggerApi!;
    const data = await httpService.post(path, {
        ApplicationId: applicationId,
        Payload: _mergeAuth({ TriggerId: triggerId }, scope, userId),
    });
    _checkResponse(data, 'ResumeAppTrigger');
}

// ============================================================
// 7. DeleteAppTrigger — 删除
// ============================================================

/**
 * 删除触发器
 */
export async function deleteAppTrigger(
    triggerId: string,
    applicationId: string,
    scope: number = AppTriggerScope.USER,
    apiPath?: string,
    userId?: string,
): Promise<void> {
    const path = apiPath || defaultApiDetailConfig.deleteAppTriggerApi!;
    const data = await httpService.post(path, {
        ApplicationId: applicationId,
        Payload: _mergeAuth({ TriggerId: triggerId }, scope, userId),
    });
    _checkResponse(data, 'DeleteAppTrigger');
}

// ============================================================
// 8. RunAppTriggerNow — 立即执行
// ============================================================

/**
 * 立即执行一次触发器
 * @returns 执行实例 ID
 */
export async function runAppTriggerNow(
    triggerId: string,
    applicationId: string,
    scope: number = AppTriggerScope.USER,
    apiPath?: string,
    userId?: string,
): Promise<string> {
    const path = apiPath || defaultApiDetailConfig.runAppTriggerNowApi!;
    const data = await httpService.post(path, {
        ApplicationId: applicationId,
        Payload: _mergeAuth({ TriggerId: triggerId }, scope, userId),
    });
    const response = _checkResponse(data, 'RunAppTriggerNow');
    return response.InstanceId;
}

// ============================================================
// 9. DescribeAppTriggerRunLogList — 运行日志列表
// ============================================================

/**
 * 获取触发器运行日志列表（分页）
 */
export async function describeAppTriggerRunLogList(
    payload: DescribeAppTriggerRunLogListPayload,
    applicationId: string,
    apiPath?: string,
    userId?: string,
): Promise<{ TotalCount: number; RunLogList: AppTriggerRunLog[] }> {
    const path = apiPath || defaultApiDetailConfig.describeAppTriggerRunLogListApi!;
    const finalPayload: DescribeAppTriggerRunLogListPayload = payload.UserId
        ? payload
        : (userId ? { ...payload, UserId: userId } : payload);
    const data = await httpService.post(path, {
        ApplicationId: applicationId,
        Payload: finalPayload,
    });
    return _checkResponse(data, 'DescribeAppTriggerRunLogList');
}

// ============================================================
// 10. MarkAppTriggerRunLogRead — 标记已读
// ============================================================

/**
 * 标记运行日志已读
 * @param instanceIdList 空数组表示全部标记已读
 * @returns 实际标记条数
 */
export async function markAppTriggerRunLogRead(
    payload: MarkAppTriggerRunLogReadPayload,
    applicationId: string,
    apiPath?: string,
    userId?: string,
): Promise<number> {
    const path = apiPath || defaultApiDetailConfig.markAppTriggerRunLogReadApi!;
    const finalPayload: MarkAppTriggerRunLogReadPayload = payload.UserId
        ? payload
        : (userId ? { ...payload, UserId: userId } : payload);
    const data = await httpService.post(path, {
        ApplicationId: applicationId,
        Payload: finalPayload,
    });
    const response = _checkResponse(data, 'MarkAppTriggerRunLogRead');
    return response.MarkedCount;
}

// ============================================================
// 11. DescribeAppTriggerInstance — 实例详情
// ============================================================

/**
 * 按 instance_id 查询执行实例详情
 */
export async function describeAppTriggerInstance(
    instanceId: string,
    applicationId: string,
    scope: number = AppTriggerScope.USER,
    apiPath?: string,
    userId?: string,
): Promise<AppTriggerInstance> {
    const path = apiPath || defaultApiDetailConfig.describeAppTriggerInstanceApi!;
    const data = await httpService.post(path, {
        ApplicationId: applicationId,
        Payload: _mergeAuth({ InstanceId: instanceId }, scope, userId),
    });
    const response = _checkResponse(data, 'DescribeAppTriggerInstance');
    return response.Instance;
}
