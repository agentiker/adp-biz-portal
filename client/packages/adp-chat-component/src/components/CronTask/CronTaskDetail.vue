<template>
    <div class="cron-task-detail">
        <!-- 头部 -->
        <div class="cron-task-detail__header">
            <span class="cron-task-detail__back" @click="handleBack">
                <CustomizedIcon
                    remote
                    name="arrow_left_small_line"
                    size="xs"
                    :show-hover-bg="false"
                    :theme="theme"
                />
            </span>
            <span class="cron-task-detail__title" :title="taskDisplayName">
                {{ taskDisplayName }}
            </span>
        </div>

        <!-- 主体 -->
        <div class="cron-task-detail__body">
            <template v-if="currentTask">
                <!-- 提示词 -->
                <div class="cron-task-detail__section">
                    <div class="cron-task-detail__section-title">{{ i18n.prompt }}</div>
                    <div class="cron-task-detail__section-content">
                        <div class="cron-task-detail__desc">{{ taskPrompt || '—' }}</div>
                    </div>
                </div>

                <!-- 调度信息 + 操作 -->
                <div class="cron-task-detail__schedule">
                    <div class="cron-task-detail__schedule-left">
                        <span
                            class="cron-task-detail__status"
                            :class="`cron-task-detail__status--${statusClass}`"
                        >
                            <span class="cron-task-detail__status-dot" />
                            {{ statusText }}
                        </span>
                        <span class="cron-task-detail__schedule-text">
                            {{ scheduleDescription }}
                        </span>
                    </div>
                    <div class="cron-task-detail__actions">
                        <t-button
                            v-if="taskStatus === TimerTaskStatus.ACTIVE"
                            size="small"
                            variant="outline"
                            :disabled="actionLoading"
                            @click="handlePause"
                        >
                            <template #icon>
                                <CustomizedIcon remote name="basic_pause_line" size="xxs" :theme="theme" />
                            </template>
                            {{ i18n.pause }}
                        </t-button>
                        <t-button
                            v-else-if="taskStatus === TimerTaskStatus.PAUSED"
                            size="small"
                            variant="outline"
                            :disabled="actionLoading"
                            @click="handleResume"
                        >
                            <template #icon>
                                <CustomizedIcon remote name="basic_play_round_line" size="xxs" :theme="theme" />
                            </template>
                            {{ i18n.resume }}
                        </t-button>
                        <t-button size="small" variant="outline" :disabled="actionLoading" @click="handleEdit">
                            <template #icon>
                                <CustomizedIcon remote name="basic_edit_line" size="xxs" :theme="theme" />
                            </template>
                            {{ i18n.edit }}
                        </t-button>
                        <t-button
                            size="small"
                            variant="outline"
                            :disabled="actionLoading"
                            @click="handleDelete"
                        >
                            <template #icon>
                                <CustomizedIcon remote name="basic_delete_line" size="xxs" :theme="theme" />
                            </template>
                            {{ i18n.del }}
                        </t-button>
                        <t-button
                            size="small"
                            variant="outline"
                            :loading="actionLoading"
                            @click="handleRunNow"
                        >
                            <template #icon>
                                <CustomizedIcon remote name="basic_play_line" size="xxs" :theme="theme" />
                            </template>
                            {{ i18n.runNow }}
                        </t-button>
                    </div>
                </div>

                <!-- 运行日志 -->
                <div class="cron-task-detail__section cron-task-detail__section--logs">
                    <div class="cron-task-detail__section-header">
                        <div class="cron-task-detail__section-title">{{ i18n.runLog }}</div>
                        <t-button
                            v-if="hasUnread"
                            size="small"
                            variant="text"
                            :loading="markingAllRead"
                            @click="handleMarkAllRead"
                        >
                            {{ i18n.markAllRead }}
                        </t-button>
                    </div>
                    <div ref="logListRef" class="cron-task-detail__log-list" @scroll="handleLogScroll">
                        <div
                            v-for="log in executionLogs"
                            :key="log.LogId || log.InstanceId || `${log.TriggerId || log.TimerId}-${log.TriggerTime || log.ScheduledFireTime || ''}`"
                            class="cron-task-detail__log-item"
                            @click="handleLogClick(log)"
                        >
                            <div class="cron-task-detail__log-header">
                                <span class="cron-task-detail__log-time">{{ log._timeLabel }}</span>
                                <span
                                    class="cron-task-detail__log-status"
                                    :class="`cron-task-detail__log-status--${log._statusClass}`"
                                >
                                    {{ log._statusText }}
                                </span>
                                <span v-if="!log.IsRead" class="cron-task-detail__log-dot" />
                            </div>
                            <div class="cron-task-detail__log-content">
                                {{ log._content }}
                            </div>
                        </div>

                        <div v-if="logsLoadingMore" class="cron-task-detail__log-tip">
                            {{ i18n.loading }}
                        </div>
                        <div
                            v-else-if="!hasMoreLogs && executionLogs.length"
                            class="cron-task-detail__log-tip"
                        >
                            {{ i18n.noMore }}
                        </div>
                        <div v-if="!executionLogs.length && !logsLoading" class="cron-task-detail__log-empty">
                            {{ i18n.noRunLog }}
                        </div>
                    </div>
                </div>
            </template>

            <div v-else class="cron-task-detail__placeholder">
                <span>{{ i18n.noRunLog }}</span>
            </div>
        </div>

        <!-- 编辑对话框 -->
        <CreateTaskDialog
            v-model:visible="editDialogVisible"
            :editing-task="editingTask"
            :application-id="applicationId"
            :space-id="spaceId"
            :scope="scope"
            :user-id="userId"
            :language="language"
            :i18n="props.i18n"
            @success="handleEditSuccess"
            @close="editDialogVisible = false"
        />

        <!-- 删除对话框 -->
        <DeleteTaskDialog
            v-model:visible="deleteDialogVisible"
            :task="currentTask"
            :application-id="applicationId"
            :space-id="spaceId"
            :scope="scope"
            :user-id="userId"
            :language="language"
            :i18n="props.i18n"
            :theme="theme"
            @success="handleDeleteSuccess"
        />

    </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onBeforeUnmount } from 'vue';
import { Button as TButton, MessagePlugin } from 'tdesign-vue-next';
import CustomizedIcon from '../CustomizedIcon.vue';
import CreateTaskDialog from './CreateTaskDialog/CreateTaskDialog.vue';
import DeleteTaskDialog from './DeleteTaskDialog.vue';
import type { ThemeProps } from '../../model/type';
import { themePropsDefaults } from '../../model/type';
import type {
    CronTaskI18n,
    TimerTask,
    TimerTaskSummary,
} from '../../model/cronTask';
import {
    TimerTaskStatus,
    TimerRunStatus,
    getCronTaskI18nByLanguage,
} from '../../model/cronTask';
import { AppTriggerStatus, AppTriggerScope } from '../../model/appTrigger';
import {
    describeAppTrigger,
    describeAppTriggerRunLogList,
    pauseAppTrigger,
    resumeAppTrigger,
    runAppTriggerNow,
    markAppTriggerRunLogRead,
} from '../../service/appTriggerApi';
import {
    getTimerId,
    getPromptContent,
    getPolicySummary,
    getTaskStatus,
    getTaskName,
    formatRelativeTime,
} from '../../utils/cronTask';
import {
    getTriggerId,
    getTriggerName,
    getTriggerPolicySummary,
    getTriggerStatus,
    getTriggerPrompt,
    isAppTrigger,
} from '../../utils/appTrigger';

interface Props extends ThemeProps {
    /** 任务（可以只是 Summary） */
    task: TimerTaskSummary | TimerTask | null;
    /** 应用 ID */
    applicationId: string;
    /** @deprecated AppTrigger 不再依赖 spaceId，保留以兼容旧调用方 */
    spaceId?: string;
    /**
     * 触发器作用域（proto AppTriggerScope）。
     * USER(2) = C 端访客，默认，需配合 userId；APP(1) = B 端管理员。
     */
    scope?: number;
    /** C 端访客 ID，scope=USER 时必填 */
    userId?: string;
    /** 语言 */
    language?: string;
    /** i18n 覆盖 */
    i18n?: Partial<CronTaskI18n>;
    /** 轮询间隔（ms），默认 10s */
    pollInterval?: number;
}

const props = withDefaults(defineProps<Props>(), {
    ...themePropsDefaults,
    task: null,
    spaceId: '',
    scope: AppTriggerScope.USER,
    userId: '',
    language: 'zh-CN',
    i18n: () => ({}),
    pollInterval: 10 * 1000,
});

const emit = defineEmits<{
    (e: 'back'): void;
    (e: 'switch-to-chat', payload: { task: any; triggerId?: string; sessionId?: string; logId?: string; userId?: string }): void;
    (e: 'action-done', action: 'pause' | 'resume' | 'edit' | 'delete' | 'run', task: any): void;
}>();

const i18n = computed<Required<CronTaskI18n>>(() => ({
    ...getCronTaskI18nByLanguage(props.language),
    ...props.i18n,
}));

// ============================================================
// 状态
// ============================================================
const taskDetail = ref<any>(null);
const runLogs = ref<any[]>([]);
const logsLoading = ref(false);
const logsLoadingMore = ref(false);
const hasMoreLogs = ref(true);
const currentPage = ref(1);
const pageSize = ref(20);
const pollTimer = ref<ReturnType<typeof setInterval> | null>(null);

const editDialogVisible = ref(false);
const editingTask = ref<TimerTaskSummary | TimerTask | null>(null);
const deleteDialogVisible = ref(false);
const actionLoading = ref(false);
const markingAllRead = ref(false);

const logListRef = ref<HTMLDivElement | null>(null);

/** 获取实体的唯一标识（兼容 AppTrigger:TriggerId + TimerTask:TimerId） */
function getEntityId(item: any): string {
    return getTriggerId(item) || getTimerId(item);
}

// 统一数据源
const currentTask = computed(() => taskDetail.value || props.task);
const _isAppTrigger = computed(() => isAppTrigger(currentTask.value));
const taskStatus = computed(() => {
    if (!currentTask.value) return 0;
    return _isAppTrigger.value
        ? getTriggerStatus(currentTask.value)
        : getTaskStatus(currentTask.value);
});
const statusClass = computed(() => {
    const s = taskStatus.value;
    if (s === TimerTaskStatus.ACTIVE || s === AppTriggerStatus.ENABLED) return 'active';
    if (s === TimerTaskStatus.PAUSED || s === AppTriggerStatus.PAUSED) return 'paused';
    return 'stopped';
});
const statusText = computed(() => {
    const s = taskStatus.value;
    if (s === TimerTaskStatus.ACTIVE || s === AppTriggerStatus.ENABLED) return i18n.value.running;
    if (s === TimerTaskStatus.PAUSED || s === AppTriggerStatus.PAUSED) return i18n.value.paused;
    if (s === TimerTaskStatus.COMPLETED || s === AppTriggerStatus.DELETED) return i18n.value.completed;
    return '';
});
const taskPrompt = computed(() => {
    if (!currentTask.value) return '';
    return _isAppTrigger.value
        ? getTriggerPrompt(currentTask.value)
        : getPromptContent(currentTask.value);
});
const scheduleDescription = computed(() => {
    if (!currentTask.value) return '';
    return _isAppTrigger.value
        ? getTriggerPolicySummary(currentTask.value) || '—'
        : getPolicySummary(currentTask.value) || '—';
});

/**
 * 详情页头部标题：显示当前任务/触发器名称。
 * 兼容 AppTrigger（TriggerName）与旧 TimerTask（Profile.TaskName）两种数据源；
 * 若名称为空，回退到 i18n.panelTitle（"定时任务"）而不是执行记录标题，
 * 避免与右侧执行记录 sidebar 的"定时任务执行记录"文案混淆。
 */
const taskDisplayName = computed(() => {
    const task = currentTask.value;
    if (!task) return i18n.value.panelTitle;
    const name = _isAppTrigger.value ? getTriggerName(task) : getTaskName(task);
    return name || i18n.value.panelTitle;
});

// ============================================================
// 日志渲染（兼容 TimerRunLog + AppTriggerRunLog）
// ============================================================
function getLogStatusValue(log: any): number {
    return Number(log.status ?? log.Status ?? log.run_status ?? log.RunStatus ?? 0);
}

function getLogTriggerTime(log: any): string | number | undefined {
    return log.scheduled_fire_time ?? log.ScheduledFireTime ??
        log.start_time ?? log.StartTime ??
        log.trigger_time ?? log.TriggerTime;
}

function getLogConversationId(log: any): string {
    return log.conversation_id ?? log.ConversationId ??
        log.session_id ?? log.SessionId ?? '';
}

function getLogInstanceId(log: any): string {
    return log.instance_id ?? log.InstanceId ??
        log.fire_instance_id ?? log.FireInstanceId ??
        log.log_id ?? log.LogId ?? '';
}

function getLogContent(log: any): string {
    return (
        log.result_summary ?? log.ResultSummary ??
        log.result_message ?? log.ResultMessage ??
        log.error_message ?? log.ErrorMessage ?? ''
    );
}

function getLogUnread(log: any): boolean {
    if (log.unread !== undefined) return Boolean(log.unread);
    if (log.Unread !== undefined) return Boolean(log.Unread);
    const read = log.is_read ?? log.IsRead;
    return read === false;
}

const executionLogs = computed(() =>
    runLogs.value.map((log: any) => {
        const status = getLogStatusValue(log);
        return {
            ...log,
            LogId: getLogInstanceId(log),
            ConversationId: getLogConversationId(log),
            _timeLabel: formatRelativeTime(getLogTriggerTime(log), {
                today: i18n.value.today,
                daysAgo: i18n.value.daysAgo,
            }),
            _statusClass: getLogStatusClass(status),
            _statusText: getLogStatusText(status),
            _content: getLogContent(log),
            IsRead: !getLogUnread(log),
        };
    }),
);

const hasUnread = computed(() => executionLogs.value.some((l: any) => !l.IsRead));

function getLogStatusClass(status: number): string {
    // 严格对齐 proto TimerRunStatus：0 UNSPECIFIED / 1 PENDING / 2 RUNNING /
    // 3 RETRY_WAIT / 4 SUCCESS / 5 DEAD(失败) / 6 CANCELLED
    const map: Record<number, string> = {
        [TimerRunStatus.PENDING]: 'pending',
        [TimerRunStatus.RUNNING]: 'running',
        [TimerRunStatus.RETRY_WAIT]: 'pending',
        [TimerRunStatus.SUCCESS]: 'success',
        [TimerRunStatus.DEAD]: 'failed',
        [TimerRunStatus.CANCELLED]: 'pending',
    };
    return map[status] || 'pending';
}

function getLogStatusText(status: number): string {
    const t = i18n.value;
    const map: Record<number, string> = {
        [TimerRunStatus.PENDING]: t.runStatusPending,
        [TimerRunStatus.RUNNING]: t.runStatusRunning,
        [TimerRunStatus.RETRY_WAIT]: t.runStatusRetryWait,
        [TimerRunStatus.SUCCESS]: t.runStatusSuccess,
        [TimerRunStatus.DEAD]: t.runStatusFailed,
        [TimerRunStatus.CANCELLED]: t.runStatusCancelled,
    };
    return map[status] || '';
}

// ============================================================
// 数据加载
// ============================================================
async function fetchTaskDetail(id: string) {
    try {
        // 优先调 AppTrigger 接口
        const detail = await describeAppTrigger(id, props.applicationId, props.scope, undefined, props.userId);
        taskDetail.value = detail || null;
    } catch (e) {
        console.error('[CronTaskDetail] fetchTaskDetail failed:', e);
        taskDetail.value = null;
    }
}

async function fetchRunLogs(id: string) {
    logsLoading.value = true;
    currentPage.value = 1;
    hasMoreLogs.value = true;
    try {
        const res: any = await describeAppTriggerRunLogList(
            {
                TriggerId: id,
                PageNumber: 1,
                PageSize: pageSize.value,
                Scope: props.scope,
                ...(props.userId ? { UserId: props.userId } : {}),
            },
            props.applicationId,
        );
        const list = res?.run_log_list || res?.RunLogList || [];
        runLogs.value = list;
        if (list.length < pageSize.value) hasMoreLogs.value = false;
        _startPolling();
    } catch (e) {
        console.error('[CronTaskDetail] fetchRunLogs failed:', e);
        runLogs.value = [];
    } finally {
        logsLoading.value = false;
    }
}

async function loadMoreLogs() {
    const id = currentTask.value ? getEntityId(currentTask.value) : '';
    if (!id || logsLoadingMore.value || !hasMoreLogs.value) return;
    logsLoadingMore.value = true;
    const nextPage = currentPage.value + 1;
    try {
        const res: any = await describeAppTriggerRunLogList(
            {
                TriggerId: id,
                PageNumber: nextPage,
                PageSize: pageSize.value,
                Scope: props.scope,
                ...(props.userId ? { UserId: props.userId } : {}),
            },
            props.applicationId,
        );
        const list = res?.run_log_list || res?.RunLogList || [];
        if (list.length < pageSize.value) hasMoreLogs.value = false;
        runLogs.value = [...runLogs.value, ...list];
        currentPage.value = nextPage;
    } catch (e) {
        console.error('[CronTaskDetail] loadMoreLogs failed:', e);
    } finally {
        logsLoadingMore.value = false;
    }
}

function handleLogScroll() {
    const el = logListRef.value;
    if (!el) return;
    if (el.scrollHeight - el.scrollTop - el.clientHeight < 50) {
        loadMoreLogs();
    }
}

function _startPolling() {
    _stopPolling();
    pollTimer.value = setInterval(() => {
        _pollRefreshLogs();
    }, props.pollInterval);
}

function _stopPolling() {
    if (pollTimer.value) {
        clearInterval(pollTimer.value);
        pollTimer.value = null;
    }
}

async function _pollRefreshLogs() {
    const id = currentTask.value ? getEntityId(currentTask.value) : '';
    if (!id) return;
    const totalSize = currentPage.value * pageSize.value;
    try {
        const res: any = await describeAppTriggerRunLogList(
            {
                TriggerId: id,
                PageNumber: 1,
                PageSize: totalSize,
                Scope: props.scope,
                ...(props.userId ? { UserId: props.userId } : {}),
            },
            props.applicationId,
        );
        const list = res?.run_log_list || res?.RunLogList || [];
        runLogs.value = list;
        if (list.length < totalSize) hasMoreLogs.value = false;
    } catch (e) {
        console.error('[CronTaskDetail] poll failed:', e);
    }
}

// ============================================================
// 操作
// ============================================================
function handleBack() {
    _stopPolling();
    emit('back');
}

function handleLogClick(log: any) {
    const conversationId = getLogConversationId(log);
    const instanceId = getLogInstanceId(log);
    // 点击日志时自动标记单条为已读
    const isLogUnread = getLogUnread(log);
    if (instanceId && isLogUnread) {
        markSingleLogRead(instanceId);
    }
    // 直接切到对应会话进行对话（webim 风格，携带 userId 供 DescribeConversationMessageList 拉取历史）
    if (conversationId) {
        const userId = log.user_id ?? log.UserId ?? '';
        const triggerId = currentTask.value ? getEntityId(currentTask.value) : '';
        emit('switch-to-chat', {
            task: currentTask.value,
            triggerId,
            sessionId: conversationId,
            logId: instanceId,
            userId,
        });
    }
}

/**
 * 标记单条日志为已读（静默，不弹 toast）
 */
async function markSingleLogRead(instanceId: string) {
    const triggerId = currentTask.value ? getEntityId(currentTask.value) : '';
    if (!triggerId) return;
    try {
        await markAppTriggerRunLogRead(
            {
                TriggerId: triggerId,
                InstanceIdList: [instanceId],
                Scope: props.scope,
                ...(props.userId ? { UserId: props.userId } : {}),
            },
            props.applicationId,
        );
        // 本地更新该条日志的已读状态
        const log = runLogs.value.find((l: any) => getLogInstanceId(l) === instanceId);
        if (log) {
            log.unread = false;
            log.Unread = false;
        }
    } catch (e) {
        console.error('[CronTaskDetail] markSingleLogRead failed:', e);
    }
}

/**
 * 一键全部已读
 */
async function handleMarkAllRead() {
    const triggerId = currentTask.value ? getEntityId(currentTask.value) : '';
    if (!triggerId || markingAllRead.value) return;
    markingAllRead.value = true;
    try {
        // InstanceIdList 为空数组表示标记全部已读
        const count = await markAppTriggerRunLogRead(
            {
                TriggerId: triggerId,
                InstanceIdList: [],
                Scope: props.scope,
                ...(props.userId ? { UserId: props.userId } : {}),
            },
            props.applicationId,
        );
        MessagePlugin.success(`${i18n.value.markAllRead}（${count}）`);
        // 本地批量更新所有日志为已读
        runLogs.value.forEach((l: any) => {
            l.unread = false;
            l.Unread = false;
        });
    } catch (e) {
        console.error('[CronTaskDetail] handleMarkAllRead failed:', e);
    } finally {
        markingAllRead.value = false;
    }
}

async function handlePause() {
    const id = currentTask.value ? getEntityId(currentTask.value) : '';
    if (!id) return;
    actionLoading.value = true;
    try {
        await pauseAppTrigger(id, props.applicationId, props.scope, undefined, props.userId);
        MessagePlugin.success(i18n.value.pauseSuccess);
        await fetchTaskDetail(id);
        emit('action-done', 'pause', currentTask.value);
    } catch (e) {
        console.error('[CronTaskDetail] pause failed:', e);
        MessagePlugin.error(i18n.value.pauseFailed);
    } finally {
        actionLoading.value = false;
    }
}

async function handleResume() {
    const id = currentTask.value ? getEntityId(currentTask.value) : '';
    if (!id) return;
    actionLoading.value = true;
    try {
        // ⚠️ ResumeAppTriggerRsp 无 next_fire_time，需额外刷新详情
        await resumeAppTrigger(id, props.applicationId, props.scope, undefined, props.userId);
        MessagePlugin.success(i18n.value.resumeSuccess);
        await fetchTaskDetail(id);
        emit('action-done', 'resume', currentTask.value);
    } catch (e) {
        console.error('[CronTaskDetail] resume failed:', e);
        MessagePlugin.error(i18n.value.resumeFailed);
    } finally {
        actionLoading.value = false;
    }
}

function handleEdit() {
    editingTask.value = currentTask.value;
    editDialogVisible.value = true;
}

function handleEditSuccess() {
    editDialogVisible.value = false;
    editingTask.value = null;
    const id = currentTask.value ? getEntityId(currentTask.value) : '';
    if (id) fetchTaskDetail(id);
    emit('action-done', 'edit', currentTask.value);
}

function handleDelete() {
    deleteDialogVisible.value = true;
}

function handleDeleteSuccess() {
    _stopPolling();
    emit('action-done', 'delete', currentTask.value);
    handleBack();
}

async function handleRunNow() {
    const id = currentTask.value ? getEntityId(currentTask.value) : '';
    if (!id) return;
    actionLoading.value = true;
    try {
        await runAppTriggerNow(id, props.applicationId, props.scope, undefined, props.userId);
        MessagePlugin.success(i18n.value.runNowSuccess);
        await _pollRefreshLogs();
        _startPolling();
        emit('action-done', 'run', currentTask.value);
    } catch (e) {
        console.error('[CronTaskDetail] run failed:', e);
        MessagePlugin.error(i18n.value.runNowFailed);
    } finally {
        actionLoading.value = false;
    }
}

// ============================================================
// 生命周期
// ============================================================
watch(
    () => props.task,
    (val) => {
        if (val) {
            const id = getEntityId(val);
            if (id) {
                fetchTaskDetail(id);
                fetchRunLogs(id);
            }
        } else {
            _stopPolling();
        }
    },
    { immediate: true },
);

onBeforeUnmount(() => {
    _stopPolling();
});
</script>

<style scoped>
.cron-task-detail {
    display: flex;
    flex-direction: column;
    height: 100%;
    background: var(--td-bg-color-container);
}

.cron-task-detail__header {
    display: flex;
    align-items: center;
    padding: var(--td-size-6) var(--td-size-7);
    border-bottom: 1px solid var(--td-component-border);
    flex-shrink: 0;
}

.cron-task-detail__back {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 28px;
    height: 28px;
    border-radius: var(--td-radius-small);
    cursor: pointer;
    margin-right: var(--td-size-4);
    transition: background-color 0.2s ease;
}

.cron-task-detail__back:hover {
    background: var(--td-bg-color-container-hover);
}

.cron-task-detail__title {
    font-size: var(--td-font-size-body-large);
    font-weight: 600;
    line-height: var(--td-line-height-body-large);
    color: var(--td-text-color-primary);
    max-width: 70%;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

.cron-task-detail__body {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    padding: var(--td-size-7) var(--td-size-8);
}

.cron-task-detail__section {
    flex-shrink: 0;
    margin-bottom: var(--td-size-8);
}

.cron-task-detail__section-title {
    font-size: var(--td-font-size-title-small);
    font-weight: 600;
    color: var(--td-text-color-primary);
    margin-bottom: var(--td-size-5);
}

/* 提示词内容容器
   对齐 webim：使用比 hover 更浅的中性底色（webim 为 rgba(36,56,97,.03)），
   而非 container-hover 的 #f5f5f7 —— 后者在浅色主题下偏深，用户反馈"背景色太深"。 */
.cron-task-detail__section-content {
    font-size: var(--td-font-size-body-medium);
    color: var(--td-text-color-secondary);
    line-height: var(--td-line-height-body-large);
    background: var(--td-bg-color-page);
    border-radius: var(--td-radius-medium);
    padding: var(--td-size-5) var(--td-size-6);
    max-height: 156px;
    overflow-y: auto;
}

.cron-task-detail__desc {
    white-space: pre-wrap;
    word-break: break-word;
}

.cron-task-detail__schedule {
    flex-shrink: 0;
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: var(--td-size-8);
    font-size: var(--td-font-size-body-small);
    flex-wrap: wrap;
    gap: var(--td-size-5);
}

.cron-task-detail__schedule-left {
    display: flex;
    align-items: center;
    gap: var(--td-size-4);
}

.cron-task-detail__actions {
    display: flex;
    align-items: center;
    gap: var(--td-size-2);
    flex-shrink: 0;
}

.cron-task-detail__status {
    display: flex;
    align-items: center;
    color: var(--td-text-color-placeholder);
}

.cron-task-detail__status-dot {
    width: 8px;
    height: 8px;
    border-radius: var(--td-radius-circle);
    margin-right: var(--td-size-2);
    background: var(--td-text-color-disabled);
    flex-shrink: 0;
}

.cron-task-detail__status--active .cron-task-detail__status-dot {
    background: var(--td-success-color);
}

.cron-task-detail__status--paused .cron-task-detail__status-dot {
    background: var(--td-warning-color);
}

.cron-task-detail__status--stopped .cron-task-detail__status-dot {
    background: var(--td-text-color-disabled);
}

.cron-task-detail__schedule-text {
    color: var(--td-text-color-placeholder);
}

.cron-task-detail__section--logs {
    display: flex;
    flex-direction: column;
    min-height: 0;
    flex: 1;
    margin-bottom: 0;
}

.cron-task-detail__section-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: var(--td-size-5);
}

.cron-task-detail__section-header .cron-task-detail__section-title {
    margin-bottom: 0;
}

.cron-task-detail__log-list {
    position: relative;
    border-radius: var(--td-radius-default);
    overflow-y: auto;
    flex: 1;
    min-height: 0;
}

.cron-task-detail__log-item {
    position: relative;
    padding: var(--td-size-6) var(--td-size-4);
    border-bottom: 1px solid var(--td-component-border);
    cursor: pointer;
    transition: background-color 0.2s ease;
}

.cron-task-detail__log-item:last-child {
    border-bottom: 0;
}

.cron-task-detail__log-item:hover {
    background: var(--td-bg-color-container-hover);
}

.cron-task-detail__log-header {
    display: flex;
    align-items: center;
    margin-bottom: var(--td-size-2);
}

.cron-task-detail__log-time {
    font-size: var(--td-font-size-body-small);
    font-weight: 500;
    color: var(--td-text-color-secondary);
    margin-right: var(--td-size-4);
}

.cron-task-detail__log-status {
    font-size: var(--td-font-size-body-small);
    color: var(--td-text-color-placeholder);
}

.cron-task-detail__log-status--success {
    color: var(--td-success-color);
}

.cron-task-detail__log-status--failed {
    color: var(--td-error-color);
}

.cron-task-detail__log-status--running {
    color: var(--td-brand-color);
}

.cron-task-detail__log-content {
    font-size: var(--td-font-size-body-small);
    color: var(--td-text-color-placeholder);
    line-height: var(--td-line-height-body-small);
    word-break: break-word;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

.cron-task-detail__log-dot {
    width: 8px;
    height: 8px;
    border-radius: var(--td-radius-circle);
    background: var(--td-error-color);
    margin-left: auto;
    flex-shrink: 0;
}

.cron-task-detail__log-empty,
.cron-task-detail__log-tip {
    padding: var(--td-size-5) 0;
    text-align: center;
    font-size: var(--td-font-size-body-small);
    color: var(--td-text-color-placeholder);
}

.cron-task-detail__placeholder {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 100%;
    color: var(--td-text-color-placeholder);
    font-size: var(--td-font-size-body-medium);
}
</style>
