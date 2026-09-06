<template>
    <div class="cron-task-panel">
        <!-- 标题栏 -->
        <div class="panel-header">
            <div class="header-left">
                <!-- 收起菜单 + 新建对话：对齐主区 header（定时任务面板遮住了主区 header，故在此补齐同款入口） -->
                <SidebarToggle :theme="theme" @toggle="emit('toggle-sidebar')" />
                <CreateConversation
                    :tooltip-text="createConversationText || undefined"
                    :theme="theme"
                    @create="emit('create-conversation')"
                />
                <span class="panel-title">{{ i18n.panelTitle }}</span>
                <t-tooltip :content="i18n.panelTip" placement="bottom">
                    <span class="help-icon">
                        <CustomizedIcon
                            remote
                            name="basic_help_line"
                            size="xs"
                            :show-hover-bg="false"
                            :theme="theme"
                        />
                    </span>
                </t-tooltip>
            </div>
        </div>

        <!-- 操作条：新建按钮（直接打开手动新建弹框） -->
        <div class="panel-action-bar">
            <div class="create-menu-trigger">
                <t-button
                    theme="primary"
                    class="create-menu-trigger__button"
                    @click="onManualCreate"
                >
                    <template #icon>
                        <CustomizedIcon
                            remote
                            name="basic_new_line"
                            size="xxs"
                            :show-hover-bg="false"
                            :theme="theme"
                        />
                    </template>
                    <span class="create-menu-trigger__text">{{ i18n.createTask }}</span>
                </t-button>
            </div>
        </div>

        <!-- 卡片列表 -->
        <div ref="panelBody" class="panel-body" @scroll="onScroll">
            <!-- 首屏加载 -->
            <div v-if="loading && list.length === 0" class="empty-state">
                <t-loading size="small" :text="i18n.loading" />
            </div>

            <!-- 空状态 -->
            <div v-else-if="list.length === 0" class="empty-state">
                <CustomizedIcon
                    remote
                    nativeIcon
                    name="default_wait"
                    class="empty-icon"
                    size="160"
                    :show-hover-bg="false"
                    :theme="theme"
                />
                <p class="empty-text">
                    {{ i18n.empty }}
                    <span class="empty-text--highlight" @click="onManualCreate">
                        {{ i18n.createTask }}
                    </span>
                    {{ i18n.emptySuffix }}
                </p>
            </div>

            <!-- 任务卡片列表 -->
            <div v-else class="task-card-list">
                <CronTaskCard
                    v-for="item in list"
                    :key="getEntityId(item)"
                    :task="item"
                    :action-loading="operatingTaskId === getEntityId(item)"
                    :theme="theme"
                    :language="language"
                    :i18n="i18n"
                    @click="onCardClick"
                    @pause="onPause"
                    @resume="onResume"
                    @edit="onEdit"
                    @delete="onDelete"
                    @run="onRunNow"
                />
            </div>

            <!-- 加载更多 -->
            <div v-if="loadingMore" class="load-more">
                <t-loading size="small" />
            </div>
        </div>

        <!-- 创建/编辑对话框 -->
        <CreateTaskDialog
            v-model:visible="createDialogVisible"
            :editing-task="editingTask"
            :application-id="applicationId"
            :space-id="spaceId"
            :scope="scope"
            :user-id="userId"
            :theme="theme"
            :language="language"
            :i18n="i18n"
            @success="onCreateSuccess"
            @close="onDialogClose"
        />

        <!-- 删除确认 -->
        <DeleteTaskDialog
            v-model:visible="deleteDialogVisible"
            :task="deletingTask"
            :application-id="applicationId"
            :space-id="spaceId"
            :scope="scope"
            :user-id="userId"
            :theme="theme"
            :language="language"
            :i18n="i18n"
            @success="onDeleteSuccess"
        />
    </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue';
import {
    Button as TButton,
    Tooltip as TTooltip,
    Loading as TLoading,
    MessagePlugin,
} from 'tdesign-vue-next';
import CustomizedIcon from '../CustomizedIcon.vue';
import SidebarToggle from '../SidebarToggle.vue';
import CreateConversation from '../CreateConversation.vue';
import CronTaskCard from './CronTaskCard.vue';
import CreateTaskDialog from './CreateTaskDialog/CreateTaskDialog.vue';
import DeleteTaskDialog from './DeleteTaskDialog.vue';
import type { ThemeProps } from '../../model/type';
import { themePropsDefaults } from '../../model/type';
import type {
    CronTaskI18n,
    TimerTaskSummary,
    TimerTask,
} from '../../model/cronTask';
import { getCronTaskI18nByLanguage } from '../../model/cronTask';
import {
    describeAppTriggerSummaryList,
    pauseAppTrigger,
    resumeAppTrigger,
    runAppTriggerNow,
} from '../../service/appTriggerApi';
import { AppTriggerScope } from '../../model/appTrigger';
import { getTimerId } from '../../utils/cronTask';
import { getTriggerId } from '../../utils/appTrigger';

export interface FolderOption { label: string; value: string }
export interface ModelOption { label: string; value: string }

export interface Props extends ThemeProps {
    /** 应用 ID（/adp 代理必需） */
    applicationId: string;
    /** @deprecated AppTrigger 不再依赖 spaceId，保留以兼容旧调用方 */
    spaceId?: string;
    /**
     * 触发器作用域（proto AppTriggerScope）。
     * USER(2) = C 端访客，默认，需配合 userId；APP(1) = B 端管理员。
     */
    scope?: number;
    /** C 端访客 ID，scope=USER 时必填；APP 场景留空即可 */
    userId?: string;
    /** 语言 */
    language?: string;
    /** i18n 覆盖 */
    i18n?: Partial<CronTaskI18n>;
    /** 每页大小 */
    pageSize?: number;
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
    createConversationText: '',
});

const emit = defineEmits<{
    (e: 'select-task', task: TimerTaskSummary | TimerTask): void;
    (e: 'run-and-view', task: TimerTaskSummary | TimerTask): void;
    (e: 'optimize-prompt', content: string): void;
    (e: 'refresh'): void;
    /** 收起/展开侧边栏（对齐主区 header 的收起按钮） */
    (e: 'toggle-sidebar'): void;
    /** 新建对话（对齐主区 header 的新建对话按钮） */
    (e: 'create-conversation'): void;
}>();

const i18n = computed<Required<CronTaskI18n>>(() => ({
    ...getCronTaskI18nByLanguage(props.language),
    ...props.i18n,
}));

// ─── 状态 ──────────────────────────────────────────────
const panelBody = ref<HTMLDivElement | null>(null);

const list = ref<Array<TimerTaskSummary | Record<string, any>>>([]);
const page = ref(1);
const hasMore = ref(true);
const loading = ref(false);
const loadingMore = ref(false);
const operatingTaskId = ref<string | null>(null);

const createDialogVisible = ref(false);
const editingTask = ref<TimerTaskSummary | TimerTask | null>(null);

const deleteDialogVisible = ref(false);
const deletingTask = ref<TimerTaskSummary | TimerTask | null>(null);

// ─── API 调用 ──────────────────────────────────────────
/**
 * 获取实体的唯一标识（兼容 AppTrigger:TriggerId + TimerTask:TimerId）
 */
function getEntityId(item: any): string {
    return getTriggerId(item) || getTimerId(item);
}

/**
 * 判断当前上下文（applicationId / scope / userId）是否与请求发起时一致
 * 用于丢弃"应用切换过程中飞行中的旧请求"，防止跨应用错拼列表
 */
function isSameContext(appId: string | undefined, scope: number | undefined, userId: string | undefined): boolean {
    return appId === props.applicationId && scope === props.scope && userId === props.userId;
}

async function fetchList() {
    if (loading.value) return;
    if (!props.applicationId) return;   // applicationId 尚未就绪，等待 watch 触发
    // 请求发起瞬间快照当前上下文
    const ctxAppId = props.applicationId;
    const ctxScope = props.scope;
    const ctxUserId = props.userId;
    loading.value = true;
    try {
        const res = await describeAppTriggerSummaryList(
            {
                PageNumber: 1,
                PageSize: props.pageSize,
                Scope: ctxScope,
                ...(ctxUserId ? { UserId: ctxUserId } : {}),
            },
            ctxAppId,
        );
        // 响应返回时若上下文已切换，丢弃本次结果
        if (!isSameContext(ctxAppId, ctxScope, ctxUserId)) return;
        // 兼容 trigger_list / TriggerList
        const items = (res as any)?.trigger_list || res?.TriggerList || [];
        list.value = items;
        page.value = 1;
        hasMore.value = items.length >= props.pageSize;
    } catch (e) {
        if (!isSameContext(ctxAppId, ctxScope, ctxUserId)) return;
        console.error('[CronTaskPanel] fetchList failed:', e);
        MessagePlugin.error(i18n.value.loadFailed);
    } finally {
        if (isSameContext(ctxAppId, ctxScope, ctxUserId)) {
            loading.value = false;
        }
    }
}

async function fetchMore() {
    if (loadingMore.value || !hasMore.value) return;
    if (!props.applicationId) return;
    const ctxAppId = props.applicationId;
    const ctxScope = props.scope;
    const ctxUserId = props.userId;
    loadingMore.value = true;
    try {
        const next = page.value + 1;
        const res = await describeAppTriggerSummaryList(
            {
                PageNumber: next,
                PageSize: props.pageSize,
                Scope: ctxScope,
                ...(ctxUserId ? { UserId: ctxUserId } : {}),
            },
            ctxAppId,
        );
        // 上下文已切换（例如用户切了应用），本次追加丢弃
        if (!isSameContext(ctxAppId, ctxScope, ctxUserId)) return;
        const items = (res as any)?.trigger_list || res?.TriggerList || [];
        const existing = new Set(list.value.map((t) => getEntityId(t)));
        items.forEach((t: any) => {
            if (!existing.has(getEntityId(t))) list.value.push(t);
        });
        page.value = next;
        hasMore.value = items.length >= props.pageSize;
    } catch (e) {
        if (!isSameContext(ctxAppId, ctxScope, ctxUserId)) return;
        console.error('[CronTaskPanel] fetchMore failed:', e);
    } finally {
        if (isSameContext(ctxAppId, ctxScope, ctxUserId)) {
            loadingMore.value = false;
        }
    }
}

/**
 * 操作成功后按当前已加载条数重新拉取
 */
async function refreshAfterAction() {
    if (!props.applicationId) return;
    const ctxAppId = props.applicationId;
    const ctxScope = props.scope;
    const ctxUserId = props.userId;
    const total = list.value.length;
    const pages = Math.max(1, Math.ceil(total / props.pageSize));
    try {
        const requests = [];
        for (let p = 1; p <= pages; p++) {
            requests.push(
                describeAppTriggerSummaryList(
                    {
                        PageNumber: p,
                        PageSize: props.pageSize,
                        Scope: ctxScope,
                        ...(ctxUserId ? { UserId: ctxUserId } : {}),
                    },
                    ctxAppId,
                ),
            );
        }
        const responses = await Promise.all(requests);
        // 上下文已切换，丢弃本次刷新结果（新上下文的 watch 已经/即将触发 fetchList）
        if (!isSameContext(ctxAppId, ctxScope, ctxUserId)) return;
        const seen = new Set<string>();
        const newList: any[] = [];
        responses.forEach((res) => {
            const items = (res as any)?.trigger_list || res?.TriggerList || [];
            items.forEach((t: any) => {
                const id = getEntityId(t);
                if (id && !seen.has(id)) {
                    seen.add(id);
                    newList.push(t);
                }
            });
        });
        list.value = newList;
        page.value = pages;
        const lastItems = ((responses[responses.length - 1] as any)?.trigger_list ||
            responses[responses.length - 1]?.TriggerList ||
            []) as any[];
        hasMore.value = lastItems.length >= props.pageSize;
    } catch (e) {
        if (!isSameContext(ctxAppId, ctxScope, ctxUserId)) return;
        console.error('[CronTaskPanel] refreshAfterAction failed:', e);
    }
    if (isSameContext(ctxAppId, ctxScope, ctxUserId)) {
        emit('refresh');
    }
}

// ─── 滚动 ──────────────────────────────────────────────
const SCROLL_THRESHOLD = 100;
function onScroll() {
    const el = panelBody.value;
    if (!el) return;
    const { scrollTop, scrollHeight, clientHeight } = el;
    if (scrollHeight - scrollTop - clientHeight < SCROLL_THRESHOLD) {
        fetchMore();
    }
}

// ─── 交互 ──────────────────────────────────────────────
function onManualCreate() {
    editingTask.value = null;
    createDialogVisible.value = true;
}

function onCardClick(task: any) {
    emit('select-task', task);
}

function onDialogClose() {
    createDialogVisible.value = false;
    editingTask.value = null;
}

function onCreateSuccess() {
    refreshAfterAction();
}

function onDeleteSuccess() {
    refreshAfterAction();
}

async function onPause(task: any) {
    const id = getEntityId(task);
    operatingTaskId.value = id;
    try {
        await pauseAppTrigger(id, props.applicationId, props.scope, undefined, props.userId);
        MessagePlugin.success(i18n.value.pauseSuccess);
        await refreshAfterAction();
    } catch (e) {
        console.error('[CronTaskPanel] pause failed:', e);
        MessagePlugin.error(i18n.value.pauseFailed);
    } finally {
        operatingTaskId.value = null;
    }
}

async function onResume(task: any) {
    const id = getEntityId(task);
    operatingTaskId.value = id;
    try {
        // ⚠️ ResumeAppTriggerRsp 无 next_fire_time 返回，详情页需补偿刷新
        await resumeAppTrigger(id, props.applicationId, props.scope, undefined, props.userId);
        MessagePlugin.success(i18n.value.resumeSuccess);
        await refreshAfterAction();
    } catch (e) {
        console.error('[CronTaskPanel] resume failed:', e);
        MessagePlugin.error(i18n.value.resumeFailed);
    } finally {
        operatingTaskId.value = null;
    }
}

function onEdit(task: any) {
    editingTask.value = task;
    createDialogVisible.value = true;
}

function onDelete(task: any) {
    deletingTask.value = task;
    deleteDialogVisible.value = true;
}

async function onRunNow(task: any) {
    const id = getEntityId(task);
    operatingTaskId.value = id;
    try {
        // 新版返回 instanceId，旧版返回 { LogId, SessionId }
        await runAppTriggerNow(id, props.applicationId, props.scope, undefined, props.userId);
        MessagePlugin.success(i18n.value.runNowSuccess);
        emit('run-and-view', task);
        await refreshAfterAction();
    } catch (e) {
        console.error('[CronTaskPanel] runNow failed:', e);
        MessagePlugin.error(i18n.value.runNowFailed);
    } finally {
        operatingTaskId.value = null;
    }
}

// ─── 生命周期 ──────────────────────────────────────────
// 监听上下文三要素（applicationId / scope / userId）：
// - 首次从空 → 有值：拉取列表
// - 切换应用 / 切换 scope / 切换 userId：重置分页并重新拉取
// - 飞行中的旧请求由各 fetch 函数内部的 isSameContext 校验丢弃
watch(
    () => [props.applicationId, props.scope, props.userId] as const,
    (newVal, oldVal) => {
        const [appId] = newVal;
        if (!appId) return;
        // 首次触发（oldVal 为 undefined）视为初始化，直接拉取
        // 后续触发：任一维度变化都重置分页并重拉
        if (oldVal) {
            const [oldAppId, oldScope, oldUserId] = oldVal;
            const contextChanged =
                appId !== oldAppId || props.scope !== oldScope || props.userId !== oldUserId;
            if (contextChanged) {
                list.value = [];
                page.value = 1;
                hasMore.value = true;
            }
        }
        fetchList();
    },
    { immediate: true },
);

defineExpose({
    fetchList,
    refreshAfterAction,
});
</script>

<style scoped>
.cron-task-panel {
    display: flex;
    flex-direction: column;
    height: 100%;
    background: var(--td-bg-color-container);
}

/* 标题栏 */
.panel-header {
    display: flex;
    align-items: center;
    height: 56px;
    padding: 0 var(--td-size-8);
    flex-shrink: 0;
}

.header-left {
    display: flex;
    align-items: center;
    gap: var(--td-size-4);
}

.panel-title {
    font-size: var(--td-font-size-title-large);
    font-weight: 600;
    line-height: var(--td-line-height-title-large);
    color: var(--td-text-color-primary);
}

.help-icon {
    display: inline-flex;
    color: var(--td-text-color-placeholder);
    cursor: pointer;
}

/* 操作条 */
.panel-action-bar {
    display: flex;
    align-items: flex-start;
    height: 44px;
    padding: 0 var(--td-size-8);
    flex-shrink: 0;
}

.create-menu-trigger {
    display: inline-flex;
    padding-bottom: var(--td-size-2);
}

/* 主按钮：图标与文字之间 4px 间距，图标强制白色（对齐 webim） */
.create-menu-trigger__button :deep(.t-button__text) {
    display: inline-flex;
    align-items: center;
    gap: var(--td-size-1);
}

.create-menu-trigger__button :deep(.t-icon),
.create-menu-trigger__button :deep(svg) {
    color: var(--td-text-color-anti);
    fill: currentColor;
}

.create-menu-trigger__text {
    line-height: 1;
}

/* 内容区 */
.panel-body {
    flex: 1;
    overflow-y: auto;
    padding: 0 var(--td-size-8);
    /* 滚动条：对齐 tcadp 统一样式（SideLayout/chat-overrides） */
    scrollbar-color: var(--td-scrollbar-color) transparent;
    scrollbar-width: thin;
}

.panel-body::-webkit-scrollbar {
    width: 6px;
    background: transparent;
}

.panel-body::-webkit-scrollbar-thumb {
    border: 1.5px solid transparent;
    background-clip: content-box;
    background-color: var(--td-scrollbar-color);
    border-radius: var(--td-radius-round);
}

.panel-body::-webkit-scrollbar-thumb:hover {
    background-color: var(--td-scrollbar-hover-color);
}

/* 空状态 */
.empty-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 100%;
}

.empty-icon {
    /* 宽高由 CustomizedIcon size="160" 内联控制，这里只保留间距 */
    margin-bottom: var(--td-size-8);
}

.empty-text {
    font-size: var(--td-font-size-body-small);
    line-height: var(--td-line-height-body-small);
    color: var(--td-text-color-placeholder);
    text-align: center;
    margin: 0;
}

.empty-text--highlight {
    color: var(--td-brand-color);
    cursor: pointer;
    margin: 0 var(--td-size-1);
}

/* 卡片网格：宽度自适应，卡片最小宽度 300px；
   面板越宽自动排更多列，窄屏自动降为 2/1 列。 */
.task-card-list {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
    gap: var(--td-size-6);
}

/* 加载更多 */
.load-more {
    display: flex;
    justify-content: center;
    padding: var(--td-size-6) 0;
}
</style>
