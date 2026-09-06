<!--
  定时任务执行历史 · 右侧 sidebar
  @description
    - 仅展示某个定时任务的执行历史（不含描述/操作按钮，简化版）
    - 与 MainLayout（对话主区）并列，宽度对齐 ChannelConversationPanel
    - 标题：任务名称（对齐 webim cron-task-detail 的 detail-title）
    - 点击列表项 → emit `select-log`，携带 conversationId / instanceId / userId
    - 支持轮询、加载更多、单条已读、全部已读
  @参考
    - ChannelConversationPanel.vue：header / body / list 视觉风格
    - CronTaskDetail.vue：日志字段兼容 + 已读逻辑 + 轮询
    - smart-webim cron-task-detail.vue：标题使用任务名 + 未读红点
-->
<script setup lang="ts">
import { ref, computed, watch, onBeforeUnmount } from 'vue';
import { Icon as TIcon, MessagePlugin } from 'tdesign-vue-next';
import CustomizedIcon from '../CustomizedIcon.vue';
import type { ThemeProps } from '../../model/type';
import { themePropsDefaults } from '../../model/type';
import type {
    CronTaskI18n,
    TimerTask,
    TimerTaskSummary,
} from '../../model/cronTask';
import {
    TimerRunStatus,
    getCronTaskI18nByLanguage,
} from '../../model/cronTask';
import { AppTriggerScope } from '../../model/appTrigger';
import {
    describeAppTriggerRunLogList,
    markAppTriggerRunLogRead,
} from '../../service/appTriggerApi';
import { getTimerId, formatRelativeTime } from '../../utils/cronTask';
import { getTriggerId } from '../../utils/appTrigger';

interface Props extends ThemeProps {
    /** 面板可见性（v-if 由父层控制，这里 prop 仅用于内部 watch 拉起 fetch） */
    visible: boolean;
    /** 当前任务（Summary / 详情皆可） */
    task: TimerTaskSummary | TimerTask | null;
    /** 应用 ID */
    applicationId: string;
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
    /** 当前激活的执行记录 InstanceId（用于高亮） */
    activeLogId?: string;
    /** 分页大小 */
    pageSize?: number;
    /** 轮询间隔（ms），0 表示不轮询 */
    pollInterval?: number;
    /** 是否为移动端：移动端改为右侧抽屉 + 背景模糊遮罩，点击遮罩关闭；PC 端保持右推面板 */
    isMobile?: boolean;
}

const props = withDefaults(defineProps<Props>(), {
    ...themePropsDefaults,
    visible: false,
    task: null,
    applicationId: '',
    scope: AppTriggerScope.USER,
    userId: '',
    language: 'zh-CN',
    i18n: () => ({}),
    activeLogId: '',
    pageSize: 20,
    pollInterval: 10 * 1000,
    isMobile: false,
});

const emit = defineEmits<{
    /** 选中一条执行记录（携带 conversationId 供主区加载对话） */
    (e: 'select-log', payload: {
        task: TimerTaskSummary | TimerTask;
        triggerId: string;
        sessionId: string;
        logId: string;
        userId: string;
    }): void;
    /** 关闭 sidebar */
    (e: 'close'): void;
}>();

const mergedI18n = computed(() => ({
    ...getCronTaskI18nByLanguage(props.language),
    ...props.i18n,
}));

// ============================================================
// 状态
// ============================================================
const runLogs = ref<any[]>([]);
const loading = ref(false);
const refreshing = ref(false);
const loadingMore = ref(false);
const hasMore = ref(true);
const currentPage = ref(1);
const markingAllRead = ref(false);
const listRef = ref<HTMLDivElement | null>(null);

let pollTimer: ReturnType<typeof setInterval> | null = null;
/** 竞态保护 */
let lastFetchId = 0;

// ============================================================
// 计算属性
// ============================================================
function getEntityId(t: any): string {
    return getTriggerId(t) || getTimerId(t);
}

const triggerId = computed(() => (props.task ? getEntityId(props.task) : ''));
/** 标题：固定"定时任务执行记录"文案（对齐 webim 需求） */
const headerTitle = computed(() => mergedI18n.value.executionRecordTitle);

// ============================================================
// 日志字段归一化（兼容 snake_case / PascalCase）
// ============================================================
function getLogStatusValue(log: any): number {
    return Number(log.status ?? log.Status ?? log.run_status ?? log.RunStatus ?? 0);
}
function getLogTriggerTime(log: any): string | number | undefined {
    return (
        log.scheduled_fire_time ?? log.ScheduledFireTime ??
        log.start_time ?? log.StartTime ??
        log.trigger_time ?? log.TriggerTime
    );
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
function getLogUserId(log: any): string {
    return log.user_id ?? log.UserId ?? '';
}

function getLogStatusClass(status: number): string {
    // 严格对齐 proto TimerRunStatus：0 UNSPECIFIED / 1 PENDING / 2 RUNNING /
    // 3 RETRY_WAIT / 4 SUCCESS / 5 DEAD(失败) / 6 CANCELLED
    const map: Record<number, string> = {
        [TimerRunStatus.PENDING]: 'pending',
        [TimerRunStatus.RUNNING]: 'running',
        [TimerRunStatus.RETRY_WAIT]: 'running',
        [TimerRunStatus.SUCCESS]: 'success',
        [TimerRunStatus.DEAD]: 'failed',
        [TimerRunStatus.CANCELLED]: 'pending',
    };
    return map[status] || 'pending';
}
function getLogStatusText(status: number): string {
    const i18n = mergedI18n.value;
    const map: Record<number, string> = {
        [TimerRunStatus.PENDING]: i18n.runStatusPending,
        [TimerRunStatus.RUNNING]: i18n.runStatusRunning,
        [TimerRunStatus.RETRY_WAIT]: i18n.runStatusRetryWait,
        [TimerRunStatus.SUCCESS]: i18n.runStatusSuccess,
        [TimerRunStatus.DEAD]: i18n.runStatusFailed,
        [TimerRunStatus.CANCELLED]: i18n.runStatusCancelled,
    };
    return map[status] || '';
}

interface ExecutionLog {
    raw: any;
    logId: string;
    conversationId: string;
    userId: string;
    timeLabel: string;
    statusClass: string;
    statusText: string;
    content: string;
    isUnread: boolean;
}

const executionLogs = computed<ExecutionLog[]>(() =>
    runLogs.value.map((log) => {
        const status = getLogStatusValue(log);
        return {
            raw: log,
            logId: getLogInstanceId(log),
            conversationId: getLogConversationId(log),
            userId: getLogUserId(log),
            timeLabel: formatRelativeTime(getLogTriggerTime(log), {
                today: mergedI18n.value.today,
                daysAgo: mergedI18n.value.daysAgo,
            }),
            statusClass: getLogStatusClass(status),
            statusText: getLogStatusText(status),
            content: getLogContent(log),
            isUnread: getLogUnread(log),
        };
    }),
);

/** 是否存在未读记录（用于控制"全部已读"按钮展示） */
const hasUnread = computed(() => executionLogs.value.some((l) => l.isUnread));

// ============================================================
// 数据加载
// ============================================================
async function fetchLogs(silent = false): Promise<void> {
    const id = triggerId.value;
    if (!id || !props.applicationId) {
        runLogs.value = [];
        return;
    }
    const fetchId = ++lastFetchId;
    if (!silent) loading.value = true;
    currentPage.value = 1;
    hasMore.value = true;
    try {
        const res: any = await describeAppTriggerRunLogList(
            {
                TriggerId: id,
                PageNumber: 1,
                PageSize: props.pageSize,
                Scope: props.scope,
                ...(props.userId ? { UserId: props.userId } : {}),
            },
            props.applicationId,
        );
        if (fetchId !== lastFetchId) return;
        const list = res?.run_log_list || res?.RunLogList || [];
        runLogs.value = list;
        if (list.length < props.pageSize) hasMore.value = false;
        startPolling();
    } catch (e) {
        if (fetchId !== lastFetchId) return;
        console.error('[CronTaskExecutionSidebar] fetchLogs failed:', e);
        runLogs.value = [];
    } finally {
        if (fetchId === lastFetchId && !silent) loading.value = false;
    }
}

async function loadMore(): Promise<void> {
    const id = triggerId.value;
    if (!id || loadingMore.value || !hasMore.value) return;
    loadingMore.value = true;
    const nextPage = currentPage.value + 1;
    try {
        const res: any = await describeAppTriggerRunLogList(
            {
                TriggerId: id,
                PageNumber: nextPage,
                PageSize: props.pageSize,
                Scope: props.scope,
                ...(props.userId ? { UserId: props.userId } : {}),
            },
            props.applicationId,
        );
        const list = res?.run_log_list || res?.RunLogList || [];
        if (list.length < props.pageSize) hasMore.value = false;
        runLogs.value = [...runLogs.value, ...list];
        currentPage.value = nextPage;
    } catch (e) {
        console.error('[CronTaskExecutionSidebar] loadMore failed:', e);
    } finally {
        loadingMore.value = false;
    }
}

async function handleRefresh(): Promise<void> {
    if (refreshing.value) return;
    refreshing.value = true;
    try {
        await fetchLogs(true);
    } finally {
        refreshing.value = false;
    }
}

async function silentPollRefresh(): Promise<void> {
    const id = triggerId.value;
    if (!id) return;
    const totalSize = currentPage.value * props.pageSize;
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
        if (list.length < totalSize) hasMore.value = false;
    } catch (e) {
        // 静默失败
    }
}

function startPolling() {
    stopPolling();
    if (!props.pollInterval || props.pollInterval <= 0) return;
    pollTimer = setInterval(() => {
        silentPollRefresh();
    }, props.pollInterval);
}
function stopPolling() {
    if (pollTimer) {
        clearInterval(pollTimer);
        pollTimer = null;
    }
}

function handleScroll(): void {
    const el = listRef.value;
    if (!el) return;
    if (el.scrollHeight - el.scrollTop - el.clientHeight < 50) {
        loadMore();
    }
}

// ============================================================
// 交互
// ============================================================
function handleSelect(log: ExecutionLog): void {
    if (!log.conversationId || !props.task) return;
    // 单条静默标已读
    if (log.isUnread && log.logId) {
        markSingleLogRead(log.logId);
    }
    emit('select-log', {
        task: props.task,
        triggerId: triggerId.value,
        sessionId: log.conversationId,
        logId: log.logId,
        userId: log.userId,
    });
}

async function markSingleLogRead(instanceId: string): Promise<void> {
    const id = triggerId.value;
    if (!id) return;
    try {
        await markAppTriggerRunLogRead(
            {
                TriggerId: id,
                InstanceIdList: [instanceId],
                Scope: props.scope,
                ...(props.userId ? { UserId: props.userId } : {}),
            },
            props.applicationId,
        );
        const raw = runLogs.value.find((l: any) => getLogInstanceId(l) === instanceId);
        if (raw) {
            raw.unread = false;
            raw.Unread = false;
            raw.is_read = true;
            raw.IsRead = true;
        }
    } catch (e) {
        console.error('[CronTaskExecutionSidebar] markSingleLogRead failed:', e);
    }
}

async function handleMarkAllRead(): Promise<void> {
    const id = triggerId.value;
    if (!id || markingAllRead.value) return;
    markingAllRead.value = true;
    try {
        const count = await markAppTriggerRunLogRead(
            {
                TriggerId: id,
                InstanceIdList: [],
                Scope: props.scope,
                ...(props.userId ? { UserId: props.userId } : {}),
            },
            props.applicationId,
        );
        MessagePlugin.success(`${mergedI18n.value.markAllRead}（${count}）`);
        runLogs.value.forEach((l: any) => {
            l.unread = false;
            l.Unread = false;
            l.is_read = true;
            l.IsRead = true;
        });
    } catch (e) {
        console.error('[CronTaskExecutionSidebar] handleMarkAllRead failed:', e);
    } finally {
        markingAllRead.value = false;
    }
}

// ============================================================
// 生命周期
// ============================================================
watch(
    [() => props.visible, () => triggerId.value, () => props.applicationId],
    ([vis, tid, appId]) => {
        if (vis && tid && appId) {
            fetchLogs();
        } else {
            stopPolling();
        }
    },
    { immediate: true },
);

onBeforeUnmount(() => {
    stopPolling();
});
</script>

<template>
    <template v-if="visible">
        <!-- 移动端毛玻璃遮罩：点击关闭抽屉（对齐 sider 移动端 .mobile-overlay） -->
        <div v-if="isMobile" class="ces-backdrop" @click="emit('close')"></div>
    <div class="cron-exec-sidebar" :class="{ 'cron-exec-sidebar--mobile': isMobile }">
        <!-- Header：固定"定时任务执行记录"标题 + 未读时展示"全部已读" + 刷新 + 关闭 -->
        <div class="ces-header">
            <span class="ces-header__title" :title="headerTitle">{{ headerTitle }}</span>
            <div class="ces-header__actions">
                <span
                    v-if="hasUnread"
                    class="ces-header__action ces-header__action--text"
                    :title="mergedI18n.markAllRead"
                    @click="handleMarkAllRead"
                >
                    <TIcon v-if="markingAllRead" name="loading" class="icon-spinning" />
                    <span v-else>{{ mergedI18n.markAllRead }}</span>
                </span>
                <span class="ces-header__action" :title="mergedI18n.refresh" @click="handleRefresh">
                    <CustomizedIcon
                        remote
                        size="xs"
                        :showHoverBg="false"
                        :class="{ 'icon-spinning': refreshing }"
                        name="basic_refresh_line"
                        :theme="theme"
                    />
                </span>
                <span class="ces-header__action" :title="mergedI18n.close" @click="emit('close')">
                    <CustomizedIcon
                        remote
                        size="xs"
                        :showHoverBg="false"
                        name="basic_close_line"
                        :theme="theme"
                    />
                </span>
            </div>
        </div>

        <!-- Body：loading / empty / list -->
        <div class="ces-body">
            <div v-if="loading" class="ces-loading">
                <TIcon name="loading" class="icon-spinning" />
                <span>{{ mergedI18n.loading }}</span>
            </div>
            <div v-else-if="executionLogs.length === 0" class="ces-empty">
                <CustomizedIcon
                    remote
                    nativeIcon
                    name="default_wait"
                    class="ces-empty__icon"
                    :showHoverBg="false"
                    :theme="theme"
                />
                <p class="ces-empty__text">{{ mergedI18n.noRunLog }}</p>
            </div>
            <div v-else ref="listRef" class="ces-list" @scroll="handleScroll">
                <!-- 列表项对齐 webim task-list-panel：
                     - 左侧：content（title，两行文案）+ status（desc）
                     - 右侧：time（相对时间，如"1天前"）
                     - 未读小红点 absolute 定位于右上角
                     - 无 border-bottom；靠 hover / active 背景色区分 -->
                <div
                    v-for="log in executionLogs"
                    :key="log.logId || `${log.timeLabel}-${log.statusText}`"
                    class="ces-item"
                    :class="{ active: activeLogId && activeLogId === log.logId }"
                    @click="handleSelect(log)"
                >
                    <span v-if="log.isUnread" class="ces-item__dot" />
                    <div class="ces-item__content">
                        <div v-if="log.content" class="ces-item__title">{{ log.content }}</div>
                        <div
                            class="ces-item__status"
                            :class="`ces-item__status--${log.statusClass}`"
                        >{{ log.statusText }}</div>
                    </div>
                    <span class="ces-item__time">{{ log.timeLabel }}</span>
                </div>
                <div v-if="loadingMore" class="ces-tip">{{ mergedI18n.loading }}</div>
                <div v-else-if="!hasMore && executionLogs.length" class="ces-tip">
                    {{ mergedI18n.noMore }}
                </div>
            </div>
        </div>
    </div>
    </template>
</template>

<style scoped>
/* ---------------- 容器：对齐 webim cron-task-detail 竖向面板 + ChannelConversationPanel 宽度 ---------------- */
.cron-exec-sidebar {
    width: 320px;
    min-width: 320px;
    height: 100%;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    border-left: 1px solid var(--td-component-border);
    background: var(--td-bg-color-container);
    flex-shrink: 0;
}

/* ---------------- 移动端：右侧抽屉 + 背景模糊遮罩（对齐 sider 移动端行为） ---------------- */
.ces-backdrop {
    position: absolute;
    inset: 0;
    background: var(--td-mask-disabled);
    backdrop-filter: blur(4px);
    -webkit-backdrop-filter: blur(4px);
    z-index: 99;
    animation: ces-backdrop-fade-in 0.2s ease;
}

.cron-exec-sidebar--mobile {
    position: absolute;
    top: 0;
    right: 0;
    bottom: 0;
    height: 100%;
    width: 85%;
    min-width: 0;
    max-width: 320px;
    z-index: 100;
    box-shadow: var(--td-shadow-3, -2px 0 12px rgba(0, 0, 0, 0.12));
    animation: ces-drawer-slide-in 0.25s cubic-bezier(0.4, 0, 0.2, 1);
}

@keyframes ces-backdrop-fade-in {
    from { opacity: 0; }
    to { opacity: 1; }
}

@keyframes ces-drawer-slide-in {
    from { transform: translateX(100%); }
    to { transform: translateX(0); }
}

/* ---------------- Header：对齐 webim .detail-header 16px 20px + 底部分隔线 ---------------- */
.ces-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: var(--td-size-6) var(--td-size-7);
    flex-shrink: 0;
    gap: var(--td-size-4);
}

.ces-header__title {
    flex: 1;
    min-width: 0;
    font-size: var(--td-font-size-body-large);
    font-weight: 600;
    line-height: var(--td-line-height-body-large);
    color: var(--td-text-color-primary);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.ces-header__actions {
    display: flex;
    align-items: center;
    gap: var(--td-size-2);
    flex-shrink: 0;
}

.ces-header__action {
    cursor: pointer;
    color: var(--td-text-color-secondary);
    line-height: 1;
    display: flex;
    padding: var(--td-size-2);
    align-items: center;
    justify-content: center;
    border-radius: var(--td-radius-small);
    transition: background-color 0.2s ease, color 0.2s ease;
}

.ces-header__action:hover {
    background-color: var(--td-bg-color-container-hover);
    color: var(--td-text-color-primary);
}

.ces-header__action--text {
    font-size: var(--td-font-size-body-small);
    padding: 0 var(--td-size-4);
    line-height: var(--td-line-height-body-small);
}

.icon-spinning {
    animation: spin 1s linear infinite;
}

@keyframes spin {
    from { transform: rotate(0deg); }
    to { transform: rotate(360deg); }
}

/* ---------------- Body ---------------- */
.ces-body {
    flex: 1;
    min-height: 0;
    overflow: hidden;
    display: flex;
    flex-direction: column;
}

.ces-loading {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: var(--td-size-4);
    padding: var(--td-size-12) 0;
    color: var(--td-text-color-placeholder);
    font-size: var(--td-font-size-body-small);
}

.ces-empty {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 100%;
    gap: var(--td-size-8);
}

.ces-empty :deep(.customeized-icon.ces-empty__icon) {
    width: 120px;
    height: 120px;
    padding: 0;
}

.ces-empty__text {
    margin: 0;
    font-size: var(--td-font-size-body-small);
    line-height: var(--td-line-height-body-small);
    color: var(--td-text-color-placeholder);
}

/* ---------------- 列表：对齐 webim task-list-panel（无分割线，item 圆角 hover） ---------------- */
.ces-list {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    padding: 0 var(--td-size-5);
    display: flex;
    flex-direction: column;
    /* 滚动条：对齐 tcadp 统一样式（SideLayout/chat-overrides） */
    scrollbar-color: var(--td-scrollbar-color) transparent;
    scrollbar-width: thin;
}

.ces-list::-webkit-scrollbar {
    width: 6px;
    background: transparent;
}

.ces-list::-webkit-scrollbar-thumb {
    border: 1.5px solid transparent;
    background-clip: content-box;
    background-color: var(--td-scrollbar-color);
    border-radius: var(--td-radius-round);
}

.ces-list::-webkit-scrollbar-thumb:hover {
    background-color: var(--td-scrollbar-hover-color);
}

/* ---------------- 列表项：对齐 webim .task-list-panel__item
     - 左内容（title/desc）+ 右时间（右对齐独立列）
     - 无 border-bottom；圆角 3px；hover / active 背景色区分
     - 未读小红点 absolute 定位于右上角 ---------------- */
.ces-item {
    position: relative;
    display: flex;
    align-items: center;
    padding: var(--td-size-5);
    border-radius: var(--td-radius-small);
    cursor: pointer;
    transition: background-color 0.2s ease;
    color: var(--td-text-color-primary);
}

.ces-item:hover:not(.active) {
    background: var(--td-bg-color-container-hover);
}

.ces-item.active {
    background: var(--td-bg-color-container-active);
}

.ces-item__content {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: var(--td-size-2);
}

.ces-item__title {
    font-size: var(--td-font-size-body-small);
    font-weight: 500;
    line-height: var(--td-line-height-body-small);
    color: var(--td-text-color-primary);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

.ces-item__status {
    font-size: 12px;
    line-height: 16px;
    color: var(--td-text-color-placeholder);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

.ces-item__status--success {
    color: var(--td-success-color);
}
.ces-item__status--failed {
    color: var(--td-error-color);
}
.ces-item__status--running {
    color: var(--td-brand-color);
}

.ces-item__time {
    flex-shrink: 0;
    margin-left: var(--td-size-4);
    font-size: 12px;
    line-height: 16px;
    color: var(--td-text-color-placeholder);
}

.ces-item__dot {
    position: absolute;
    top: var(--td-size-3);
    right: var(--td-size-3);
    width: 8px;
    height: 8px;
    border-radius: var(--td-radius-circle);
    background: var(--td-error-color);
    flex-shrink: 0;
}

.ces-tip {
    padding: var(--td-size-5) 0;
    text-align: center;
    font-size: var(--td-font-size-body-small);
    color: var(--td-text-color-placeholder);
}
</style>
