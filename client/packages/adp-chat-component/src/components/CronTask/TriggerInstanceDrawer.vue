<template>
    <t-drawer
        v-model:visible="innerVisible"
        :header="i18n.instanceDetail"
        size="480px"
        :close-on-overlay-click="!loading"
        :footer="false"
        attach="body"
    >
        <div v-if="loading" class="instance-drawer__loading">
            <t-loading size="small" :text="i18n.loading" />
        </div>

        <template v-else-if="instance">
            <!-- 执行状态 -->
            <div class="instance-drawer__section">
                <div class="instance-drawer__label">{{ i18n.instanceStatus }}</div>
                <div class="instance-drawer__value">
                    <span class="instance-drawer__status-badge" :class="statusClass">
                        {{ statusText }}
                    </span>
                </div>
            </div>

            <!-- 触发来源 -->
            <div class="instance-drawer__section">
                <div class="instance-drawer__label">{{ i18n.instanceSource }}</div>
                <div class="instance-drawer__value">{{ sourceText }}</div>
            </div>

            <!-- 结果码 -->
            <div v-if="instance.ResultCode" class="instance-drawer__section">
                <div class="instance-drawer__label">{{ i18n.instanceResultCode }}</div>
                <div class="instance-drawer__value">
                    <t-tag v-if="isSuccess" theme="success" variant="light">{{ instance.ResultCode }}</t-tag>
                    <t-tag v-else theme="danger" variant="light">{{ instance.ResultCode }}</t-tag>
                </div>
            </div>

            <!-- 结果摘要 -->
            <div v-if="instance.ResultSummary" class="instance-drawer__section">
                <div class="instance-drawer__label">{{ i18n.instanceResultSummary }}</div>
                <div class="instance-drawer__value instance-drawer__summary">
                    {{ instance.ResultSummary }}
                </div>
            </div>

            <!-- 时间线 -->
            <div class="instance-drawer__section">
                <div class="instance-drawer__label">{{ i18n.instanceTimeLine }}</div>
                <div class="instance-drawer__timeline">
                    <div class="instance-drawer__timeline-item">
                        <span class="instance-drawer__timeline-dot instance-drawer__timeline-dot--start" />
                        <div>
                            <div class="instance-drawer__timeline-label">{{ i18n.instanceCreatedAt }}</div>
                            <div class="instance-drawer__timeline-value">{{ formatTime(instance.CreatedAt) }}</div>
                        </div>
                    </div>
                    <div v-if="instance.StartedAt" class="instance-drawer__timeline-item">
                        <span class="instance-drawer__timeline-dot instance-drawer__timeline-dot--running" />
                        <div>
                            <div class="instance-drawer__timeline-label">{{ i18n.instanceStartedAt }}</div>
                            <div class="instance-drawer__timeline-value">{{ formatTime(instance.StartedAt) }}</div>
                        </div>
                    </div>
                    <div v-if="instance.FinishedAt" class="instance-drawer__timeline-item">
                        <span class="instance-drawer__timeline-dot" :class="isSuccess ? 'instance-drawer__timeline-dot--success' : 'instance-drawer__timeline-dot--failed'" />
                        <div>
                            <div class="instance-drawer__timeline-label">{{ i18n.instanceFinishedAt }}</div>
                            <div class="instance-drawer__timeline-value">{{ formatTime(instance.FinishedAt) }}</div>
                        </div>
                    </div>
                </div>
            </div>

            <!-- 关联信息 -->
            <div class="instance-drawer__section">
                <div class="instance-drawer__label">ID</div>
                <div class="instance-drawer__info-list">
                    <div v-if="instance.ConversationId" class="instance-drawer__info-item">
                        <span class="instance-drawer__info-key">{{ i18n.instanceConversationId }}</span>
                        <span class="instance-drawer__info-val">
                            <t-button
                                size="small"
                                variant="text"
                                theme="primary"
                                @click="handleViewConversation"
                            >
                                {{ i18n.viewConversation }}
                            </t-button>
                        </span>
                    </div>
                    <div v-if="instance.RunId" class="instance-drawer__info-item">
                        <span class="instance-drawer__info-key">{{ i18n.instanceRunId }}</span>
                        <span class="instance-drawer__info-val instance-drawer__info-copy" @click="copyText(instance.RunId)">
                            {{ truncateId(instance.RunId) }}
                        </span>
                    </div>
                    <div v-if="instance.WorkflowRunId" class="instance-drawer__info-item">
                        <span class="instance-drawer__info-key">{{ i18n.instanceWorkflowRunId }}</span>
                        <span class="instance-drawer__info-val instance-drawer__info-copy" @click="copyText(instance.WorkflowRunId)">
                            {{ truncateId(instance.WorkflowRunId) }}
                        </span>
                    </div>
                </div>
            </div>
        </template>

        <div v-else-if="!loading" class="instance-drawer__empty">
            {{ i18n.noLogs }}
        </div>
    </t-drawer>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue';
import {
    Drawer as TDrawer,
    Loading as TLoading,
    Tag as TTag,
    Button as TButton,
    MessagePlugin,
} from 'tdesign-vue-next';
import { describeAppTriggerInstance } from '../../service/appTriggerApi';
import { AppTriggerScope } from '../../model/appTrigger';
import { TimerRunStatus } from '../../model/cronTask';
import { getAppTriggerI18nByLanguage } from '../../model/appTrigger';
import type { AppTriggerI18n, AppTriggerInstance } from '../../model/appTrigger';
import { formatDateTime } from '../../utils/cronTask';

interface Props {
    visible: boolean;
    instanceId: string;
    applicationId: string;
    /**
     * 触发器作用域（proto AppTriggerScope）。
     * USER(2) = C 端访客，默认，需配合 userId；APP(1) = B 端管理员。
     */
    scope?: number;
    /** C 端访客 ID，scope=USER 时必填 */
    userId?: string;
    language?: string;
    i18n?: Partial<AppTriggerI18n>;
}

const props = withDefaults(defineProps<Props>(), {
    visible: false,
    instanceId: '',
    applicationId: '',
    scope: AppTriggerScope.USER,
    userId: '',
    language: 'zh-CN',
    i18n: () => ({}),
});

const emit = defineEmits<{
    (e: 'update:visible', v: boolean): void;
    (e: 'switch-to-chat', conversationId: string): void;
}>();

const mergedI18n = computed<Required<AppTriggerI18n>>(() => ({
    ...getAppTriggerI18nByLanguage(props.language),
    ...props.i18n,
}));

const innerVisible = computed({
    get: () => props.visible,
    set: (v) => emit('update:visible', v),
});

const loading = ref(false);
const instance = ref<AppTriggerInstance | null>(null);

// ============================================================
// 加载
// ============================================================
watch(
    () => [props.visible, props.instanceId] as const,
    async ([vis, id]) => {
        if (!vis || !id) {
            instance.value = null;
            return;
        }
        loading.value = true;
        try {
            instance.value = await describeAppTriggerInstance(
                id,
                props.applicationId,
                props.scope,
                undefined,
                props.userId,
            );
        } catch (e) {
            console.error('[TriggerInstanceDrawer] load failed:', e);
            instance.value = null;
        } finally {
            loading.value = false;
        }
    },
    { immediate: true },
);

// ============================================================
// 展示
// ============================================================
const isSuccess = computed(() =>
    instance.value?.Status === TimerRunStatus.SUCCESS
);

const statusText = computed(() => {
    const s = instance.value?.Status;
    return mergedI18n.value.logStatus?.[s ?? 0] ?? '';
});

const statusClass = computed(() => {
    const s = instance.value?.Status;
    if (s === TimerRunStatus.SUCCESS) return 'instance-drawer__status-badge--success';
    if (s === TimerRunStatus.DEAD || s === TimerRunStatus.CANCELLED) return 'instance-drawer__status-badge--failed';
    return 'instance-drawer__status-badge--running';
});

const sourceText = computed(() => {
    const ft = instance.value?.Source;
    return mergedI18n.value.fireType?.[ft ?? 0] ?? '';
});

// ============================================================
// 工具
// ============================================================
function formatTime(val: string): string {
    return formatDateTime(val) || val || '—';
}

function truncateId(id: string): string {
    return id.length > 24 ? `${id.slice(0, 12)}...${id.slice(-8)}` : id;
}

async function copyText(text: string) {
    try {
        await navigator.clipboard.writeText(text);
        MessagePlugin.success(mergedI18n.value.instanceCopySuccess);
    } catch {
        // fallback
    }
}

function handleViewConversation() {
    if (instance.value?.ConversationId) {
        emit('switch-to-chat', instance.value.ConversationId);
        innerVisible.value = false;
    }
}
</script>

<style scoped>
.instance-drawer__loading,
.instance-drawer__empty {
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 200px;
    color: var(--td-text-color-placeholder);
    font-size: var(--td-font-size-body-medium);
}

.instance-drawer__section {
    margin-bottom: var(--td-size-7);
}

.instance-drawer__label {
    font-size: var(--td-font-size-body-small);
    color: var(--td-text-color-placeholder);
    margin-bottom: var(--td-size-2);
}

.instance-drawer__value {
    font-size: var(--td-font-size-body-medium);
    color: var(--td-text-color-primary);
}

.instance-drawer__summary {
    background: var(--td-bg-color-component);
    border-radius: var(--td-radius-default);
    padding: var(--td-size-4);
    max-height: 120px;
    overflow-y: auto;
    white-space: pre-wrap;
    word-break: break-word;
    line-height: var(--td-line-height-body-medium);
}

/* 状态徽标 */
.instance-drawer__status-badge {
    display: inline-flex;
    align-items: center;
    gap: var(--td-size-2);
    padding: 2px var(--td-size-4);
    border-radius: var(--td-radius-default);
    font-size: var(--td-font-size-body-small);
    font-weight: 500;
}

.instance-drawer__status-badge--success {
    color: var(--td-success-color);
    background: var(--td-success-color-light);
}

.instance-drawer__status-badge--failed {
    color: var(--td-error-color);
    background: var(--td-error-color-light);
}

.instance-drawer__status-badge--running {
    color: var(--td-brand-color);
    background: var(--td-brand-color-light);
}

/* 时间线 */
.instance-drawer__timeline {
    position: relative;
    padding-left: var(--td-size-7);
}

.instance-drawer__timeline-item {
    position: relative;
    padding-bottom: var(--td-size-6);
}

.instance-drawer__timeline-item:last-child {
    padding-bottom: 0;
}

.instance-drawer__timeline-dot {
    position: absolute;
    left: calc(-1 * var(--td-size-7) + var(--td-size-2));
    top: 4px;
    width: 8px;
    height: 8px;
    border-radius: var(--td-radius-circle);
}

.instance-drawer__timeline-dot--start {
    background: var(--td-brand-color);
}

.instance-drawer__timeline-dot--running {
    background: var(--td-warning-color);
}

.instance-drawer__timeline-dot--success {
    background: var(--td-success-color);
}

.instance-drawer__timeline-dot--failed {
    background: var(--td-error-color);
}

.instance-drawer__timeline-label {
    font-size: var(--td-font-size-body-small);
    color: var(--td-text-color-secondary);
}

.instance-drawer__timeline-value {
    font-size: var(--td-font-size-body-small);
    color: var(--td-text-color-primary);
    font-variant-numeric: tabular-nums;
}

/* 关联 ID 列表 */
.instance-drawer__info-list {
    display: flex;
    flex-direction: column;
    gap: var(--td-size-3);
}

.instance-drawer__info-item {
    display: flex;
    align-items: center;
    justify-content: space-between;
    font-size: var(--td-font-size-body-small);
}

.instance-drawer__info-key {
    color: var(--td-text-color-secondary);
    flex-shrink: 0;
}

.instance-drawer__info-val {
    color: var(--td-text-color-primary);
    font-family: monospace;
    max-width: 60%;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.instance-drawer__info-copy {
    cursor: pointer;
    transition: color 0.2s;
}

.instance-drawer__info-copy:hover {
    color: var(--td-brand-color);
}
</style>
