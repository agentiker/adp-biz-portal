<template>
    <div class="cron-task-card" @click="onCardClick">
        <!-- 顶部：标题 + 状态 -->
        <div class="card-header">
            <span class="card-title" :title="taskName">{{ taskName }}</span>
            <span class="card-status" :class="`card-status--${statusClass}`">
                <span class="status-dot" />
                {{ statusText }}
            </span>
        </div>

        <!-- 中间：策略摘要 + 成功/失败次数 -->
        <div class="card-tags">
            <t-tooltip :content="scheduleText" placement="top">
                <span class="card-tags__time">
                    <CustomizedIcon
                        remote
                        name="basic_time_line"
                        size="xxs"
                        :show-hover-bg="false"
                        :theme="theme"
                    />
                    <span class="card-tags__time-text">{{ scheduleText }}</span>
                </span>
            </t-tooltip>
            <span v-if="successCount > 0" class="card-tags__count card-tags__count--success">
                <CustomizedIcon
                    remote
                    name="basic_finish_line"
                    size="xxs"
                    :show-hover-bg="false"
                    :theme="theme"
                />
                {{ successCount }}
            </span>
            <span v-if="failureCount > 0" class="card-tags__count card-tags__count--fail">
                <CustomizedIcon
                    remote
                    name="basic_close_line"
                    size="xxs"
                    :show-hover-bg="false"
                    :theme="theme"
                />
                {{ failureCount }}
            </span>
        </div>

        <!-- 底部：操作按钮
             对齐 webim：pause/resume/edit/delete 使用 v-button size=small（默认带边框），
             不再是 text 无边框按钮。截图中每个按钮都有一层浅灰边框。 -->
        <div class="card-actions">
            <t-tooltip v-if="taskStatus === TimerTaskStatus.ACTIVE" :content="i18n.pause" placement="top">
                <t-button
                    size="small"
                    variant="outline"
                    shape="square"
                    :disabled="actionLoading"
                    @click.stop="emit('pause', task)"
                >
                    <CustomizedIcon
                        remote
                        name="basic_pause_line"
                        size="xs"
                        :show-hover-bg="false"
                        :theme="theme"
                    />
                </t-button>
            </t-tooltip>
            <t-tooltip v-else-if="taskStatus === TimerTaskStatus.PAUSED" :content="i18n.resume" placement="top">
                <t-button
                    size="small"
                    variant="outline"
                    shape="square"
                    :disabled="actionLoading"
                    @click.stop="emit('resume', task)"
                >
                    <CustomizedIcon
                        remote
                        name="basic_play_round_line"
                        size="xs"
                        :show-hover-bg="false"
                        :theme="theme"
                    />
                </t-button>
            </t-tooltip>
            <t-tooltip :content="i18n.edit" placement="top">
                <t-button
                    size="small"
                    variant="outline"
                    shape="square"
                    :disabled="actionLoading"
                    @click.stop="emit('edit', task)"
                >
                    <CustomizedIcon
                        remote
                        name="basic_edit_line"
                        size="xs"
                        :show-hover-bg="false"
                        :theme="theme"
                    />
                </t-button>
            </t-tooltip>
            <t-tooltip :content="i18n.del" placement="top">
                <t-button
                    size="small"
                    variant="outline"
                    shape="square"
                    :disabled="actionLoading"
                    @click.stop="emit('delete', task)"
                >
                    <CustomizedIcon
                        remote
                        name="basic_delete_line"
                        size="xs"
                        :show-hover-bg="false"
                        :theme="theme"
                    />
                </t-button>
            </t-tooltip>
            <t-button
                size="small"
                variant="outline"
                :disabled="actionLoading"
                :loading="actionLoading"
                @click.stop="emit('run', task)"
            >
                <template #icon>
                    <CustomizedIcon
                        remote
                        name="basic_play_line"
                        size="xxs"
                        :show-hover-bg="false"
                        :theme="theme"
                    />
                </template>
                {{ i18n.runNow }}
            </t-button>
        </div>
    </div>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import {
    Button as TButton,
    Tooltip as TTooltip,
} from 'tdesign-vue-next';
import CustomizedIcon from '../CustomizedIcon.vue';
import type { ThemeProps } from '../../model/type';
import { themePropsDefaults } from '../../model/type';
import type { CronTaskI18n, TimerTaskSummary, TimerTask } from '../../model/cronTask';
import { TimerTaskStatus, getCronTaskI18nByLanguage } from '../../model/cronTask';
import { AppTriggerStatus } from '../../model/appTrigger';
import {
    getTaskName,
    getPolicySummary,
    getTaskStatus,
    getSuccessCount,
    getFailureCount,
} from '../../utils/cronTask';
import {
    getTriggerName,
    getTriggerPolicySummary,
    getTriggerStatus,
    getTriggerSuccessCount,
    getTriggerFailureCount,
    isAppTriggerSummary,
} from '../../utils/appTrigger';

interface Props extends ThemeProps {
    /** 任务数据（AppTriggerSummary / TimerTaskSummary / 完整 Trigger / 完整 Task） */
    task: TimerTaskSummary | TimerTask | Record<string, any>;
    /** 是否处于操作 loading 态 */
    actionLoading?: boolean;
    /** i18n 覆盖 */
    i18n?: Partial<CronTaskI18n>;
    /** 语言 */
    language?: string;
}

const props = withDefaults(defineProps<Props>(), {
    ...themePropsDefaults,
    actionLoading: false,
    i18n: () => ({}),
    language: 'zh-CN',
});

const emit = defineEmits<{
    (e: 'click', task: Props['task']): void;
    (e: 'pause', task: Props['task']): void;
    (e: 'resume', task: Props['task']): void;
    (e: 'edit', task: Props['task']): void;
    (e: 'delete', task: Props['task']): void;
    (e: 'run', task: Props['task']): void;
}>();

const i18n = computed<Required<CronTaskI18n>>(() => ({
    ...getCronTaskI18nByLanguage(props.language),
    ...props.i18n,
}));

/** 是否为新 AppTrigger 数据结构 */
const isAppTrigger = computed(() => isAppTriggerSummary(props.task));

const taskName = computed(() =>
    isAppTrigger.value ? getTriggerName(props.task) : getTaskName(props.task)
);
const taskStatus = computed(() =>
    isAppTrigger.value ? getTriggerStatus(props.task) : getTaskStatus(props.task)
);
const successCount = computed(() =>
    isAppTrigger.value ? getTriggerSuccessCount(props.task) : getSuccessCount(props.task)
);
const failureCount = computed(() =>
    isAppTrigger.value ? getTriggerFailureCount(props.task) : getFailureCount(props.task)
);

const scheduleText = computed(() => {
    if (isAppTrigger.value) return getTriggerPolicySummary(props.task) || '-';
    return getPolicySummary(props.task) || '-';
});

/** 状态 CSS class（兼容新旧枚举值：ACTIVE=1/ENABLED=1, PAUSED=2） */
const statusClass = computed(() => {
    const s = taskStatus.value;
    if (s === TimerTaskStatus.ACTIVE || s === AppTriggerStatus.ENABLED) return 'active';
    if (s === TimerTaskStatus.PAUSED || s === AppTriggerStatus.PAUSED) return 'paused';
    return 'stopped';
});

/** 状态展示文本 */
const statusText = computed(() => {
    const s = taskStatus.value;
    if (s === TimerTaskStatus.ACTIVE || s === AppTriggerStatus.ENABLED) return i18n.value.running;
    if (s === TimerTaskStatus.PAUSED || s === AppTriggerStatus.PAUSED) return i18n.value.paused;
    if (s === TimerTaskStatus.COMPLETED || s === AppTriggerStatus.DELETED) return i18n.value.completed;
    return '';
});

function onCardClick() {
    emit('click', props.task);
}
</script>

<style scoped>
.cron-task-card {
    display: flex;
    flex-direction: column;
    height: 120px;
    padding: var(--td-size-6);
    background: var(--td-bg-color-container);
    border: 1px solid var(--td-border-level-2-color);
    border-radius: var(--td-radius-default);
    cursor: pointer;
    transition: box-shadow 0.2s ease, border-color 0.2s ease;
    box-sizing: border-box;
}

.cron-task-card:hover {
    /* 对齐 webim：hover 时用中性色略深边框 + 淡阴影，不使用品牌色高亮，避免过强视觉干扰 */
    border-color: var(--td-border-level-3-color, rgba(17, 32, 70, 0.2));
    box-shadow: var(--td-shadow-1);
}

/* 顶部 */
.card-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    height: 24px;
}

.card-title {
    flex: 1;
    min-width: 0;
    font-size: var(--td-font-size-body-large);
    font-weight: 500;
    line-height: var(--td-line-height-body-large);
    color: var(--td-text-color-primary);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

.card-status {
    flex-shrink: 0;
    display: flex;
    align-items: center;
    margin-left: var(--td-size-5);
    font-size: var(--td-font-size-body-small);
    line-height: var(--td-line-height-body-small);
    color: var(--td-text-color-secondary);
}

.card-status .status-dot {
    width: 8px;
    height: 8px;
    margin-right: var(--td-size-2);
    border-radius: var(--td-radius-circle);
    background: var(--td-text-color-disabled);
}

.card-status--active .status-dot {
    background: var(--td-success-color);
}

.card-status--paused .status-dot {
    background: var(--td-warning-color);
}

.card-status--stopped .status-dot {
    background: var(--td-text-color-disabled);
}

/* 标签行
   对齐 webim：时间 tag 只占内容宽度（不撑满剩余空间），后接成功/失败计数 tag。 */
.card-tags {
    display: flex;
    align-items: center;
    flex-wrap: nowrap;
    gap: var(--td-size-3);
    margin-top: var(--td-size-2);
    overflow: hidden;
}

/* 时间 tag：内容宽 + 灰底 + 圆角，不撑满剩余空间（对齐设计图 pill 外观）。
   过长时省略号截断。 */
.card-tags__time {
    flex: 0 1 auto;
    min-width: 0;
    max-width: 100%;
    display: inline-flex;
    align-items: center;
    gap: var(--td-size-2);
    padding: var(--td-size-1) var(--td-size-4);
    background: var(--td-bg-color-container-hover);
    color: var(--td-text-color-secondary);
    border-radius: var(--td-radius-small);
    font-size: var(--td-font-size-body-small);
    line-height: 18px;
    overflow: hidden;
}

.card-tags__time-text {
    flex: 0 1 auto;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.card-tags__count {
    flex-shrink: 0;
    display: inline-flex;
    align-items: center;
    gap: var(--td-size-1);
    padding: var(--td-size-1) var(--td-size-4);
    border-radius: var(--td-radius-small);
    font-size: var(--td-font-size-body-small);
    line-height: 18px;
}

/* 让时间 tag（或 t-tooltip 包裹它的 wrapper span）占据剩余空间的左端，
   把后续的计数标签推到卡片右侧。
   注意：不能用 .card-tags__count:first-of-type，因为 t-tooltip 会在
   .card-tags 里插入一个 <span> wrapper，导致按标签名匹配 :first-of-type
   实际命中的是 wrapper 而非 count 元素。这里改用相邻兄弟选择器，
   凡是紧跟在时间 tag（或其 wrapper）后面的第一个 count，都吸到右侧。 */
.card-tags > :first-child {
    margin-right: auto;
}

.card-tags__count--success {
    color: var(--td-success-color);
    background: var(--td-success-color-light);
}

.card-tags__count--fail {
    color: var(--td-error-color);
    background: var(--td-error-color-light);
}

/* 底部操作
   对齐 webim：按钮之间较小间距（8px），末尾"立即执行"稍作分隔。 */
.card-actions {
    display: flex;
    align-items: center;
    justify-content: flex-end;
    gap: var(--td-size-4);
    margin-top: auto;
}
</style>
