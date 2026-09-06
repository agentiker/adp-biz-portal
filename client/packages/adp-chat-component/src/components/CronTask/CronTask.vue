<template>
    <div class="cron-task-container">
        <CronTaskPanel
            v-if="currentView === 'list'"
            ref="panelRef"
            :application-id="applicationId"
            :space-id="spaceId"
            :scope="scope"
            :user-id="userId"
            :theme="theme"
            :language="language"
            :i18n="props.i18n"
            :page-size="pageSize"
            :create-conversation-text="createConversationText"
            @select-task="handleSelectTask"
            @run-and-view="onRunAndView"
            @optimize-prompt="onOptimizePrompt"
            @refresh="onRefresh"
            @toggle-sidebar="emit('toggle-sidebar')"
            @create-conversation="emit('create-conversation')"
        />
        <CronTaskDetail
            v-else-if="currentView === 'detail'"
            :task="currentTask"
            :application-id="applicationId"
            :space-id="spaceId"
            :scope="scope"
            :user-id="userId"
            :theme="theme"
            :language="language"
            :i18n="props.i18n"
            :poll-interval="pollInterval"
            @back="handleBackToList"
            @switch-to-chat="onSwitchToChat"
            @action-done="onActionDone"
        />
    </div>
</template>

<script setup lang="ts">
import { ref } from 'vue';
import CronTaskPanel from './CronTaskPanel.vue';
import CronTaskDetail from './CronTaskDetail.vue';
import type { ThemeProps } from '../../model/type';
import { themePropsDefaults } from '../../model/type';
import type {
    CronTaskI18n,
    TimerTask,
    TimerTaskSummary,
} from '../../model/cronTask';
import { AppTriggerScope } from '../../model/appTrigger';

export interface Option { label: string; value: string }

export interface Props extends ThemeProps {
    /** 应用 ID（/adp 代理必需） */
    applicationId: string;
    /** @deprecated AppTrigger 不再依赖 spaceId，保留以兼容旧调用方 */
    spaceId?: string;
    /**
     * 触发器作用域，proto AppTriggerScope。
     * - USER(2)：C 端访客，默认；需同时传 userId。
     * - APP(1)：B 端管理员，user_id 可省略。
     */
    scope?: number;
    /** C 端访客 ID；scope=USER 时必填 */
    userId?: string;
    /** 语言 */
    language?: string;
    /** i18n 覆盖 */
    i18n?: Partial<CronTaskI18n>;
    /** 分页大小 */
    pageSize?: number;
    /** 详情页运行日志轮询间隔（ms） */
    pollInterval?: number;
    /** 新建对话按钮的 tooltip 文案（对齐主区 header 的"新建对话"） */
    createConversationText?: string;
}

const props = withDefaults(defineProps<Props>(), {
    ...themePropsDefaults,
    spaceId: '',
    scope: AppTriggerScope.USER,
    userId: '',
    language: 'zh-CN',
    i18n: () => ({}),
    pageSize: 20,
    pollInterval: 10 * 1000,
    createConversationText: '',
});

const emit = defineEmits<{
    (e: 'run-and-view', task: any): void;
    (e: 'optimize-prompt', content: string): void;
    (e: 'refresh'): void;
    (e: 'switch-to-chat', payload: { task: any; triggerId?: string; sessionId?: string; logId?: string; userId?: string }): void;
    (e: 'action-done', action: string, task: any): void;
    (e: 'view-change', view: 'list' | 'detail'): void;
    /** 收起/展开侧边栏（对齐主区 header 的收起按钮） */
    (e: 'toggle-sidebar'): void;
    /** 新建对话（对齐主区 header 的新建对话按钮） */
    (e: 'create-conversation'): void;
}>();

// ============================================================
// 视图切换
// ============================================================
type ViewType = 'list' | 'detail';
const currentView = ref<ViewType>('list');
const currentTask = ref<TimerTaskSummary | TimerTask | null>(null);
const panelRef = ref<InstanceType<typeof CronTaskPanel> | null>(null);

function handleSelectTask(task: TimerTaskSummary | TimerTask) {
    currentTask.value = task;
    currentView.value = 'detail';
    emit('view-change', 'detail');
}

function handleBackToList() {
    currentView.value = 'list';
    currentTask.value = null;
    emit('view-change', 'list');
    // 返回列表时刷新一次，感知详情页可能的变更（暂停/编辑/删除/立即执行）
    panelRef.value?.refreshAfterAction?.();
}

/** 供外部调用：直接进入指定任务详情 */
function showTaskDetail(task: TimerTaskSummary | TimerTask) {
    currentTask.value = task;
    currentView.value = 'detail';
    emit('view-change', 'detail');
}

/** 供外部调用：手动刷新列表 */
function refreshList() {
    return panelRef.value?.fetchList?.();
}

/**
 * 供外部调用：无论当前处于 detail / list，都重置为初始 list 视图
 * 用于"再次点击定时任务入口"时回到初始态。
 */
function resetToList() {
    if (currentView.value !== 'list') {
        currentView.value = 'list';
        emit('view-change', 'list');
    }
    currentTask.value = null;
    // 刷新列表，感知可能的外部变更
    panelRef.value?.refreshAfterAction?.();
}

// ============================================================
// 事件透传
// ============================================================
function onRunAndView(task: any) {
    emit('run-and-view', task);
}
function onOptimizePrompt(content: string) {
    emit('optimize-prompt', content);
}
function onRefresh() {
    emit('refresh');
}
function onSwitchToChat(payload: { task: any; triggerId?: string; sessionId?: string; logId?: string; userId?: string }) {
    emit('switch-to-chat', payload);
}
function onActionDone(action: string, task: any) {
    emit('action-done', action, task);
}

defineExpose({ showTaskDetail, refreshList, resetToList });
</script>

<style scoped>
.cron-task-container {
    width: 100%;
    height: 100%;
    display: flex;
    flex-direction: column;
}
</style>
