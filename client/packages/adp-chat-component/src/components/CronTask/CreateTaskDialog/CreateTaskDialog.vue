<template>
    <t-dialog
        v-model:visible="innerVisible"
        :header="dialogTitle"
        :close-on-overlay-click="true"
        :close-on-esc-keydown="!confirmLoading && !detailLoading"
        :footer="false"
        width="640px"
        class="cron-create-task-dialog"
        @close="handleClose"
    >
        <div class="cron-create-task-dialog__body">
            <!-- 任务名称 -->
            <div class="cron-create-task-dialog__form-item">
                <div class="cron-create-task-dialog__label">
                    {{ i18n.taskNameLabel }}
                    <span class="cron-create-task-dialog__required">*</span>
                </div>
                <t-input
                    v-model="taskName"
                    :placeholder="i18n.taskNamePlaceholder"
                    :maxlength="50"
                />
            </div>

            <!-- 提示词 -->
            <div class="cron-create-task-dialog__form-item">
                <PromptInput
                    ref="promptInputRef"
                    v-model="promptValue"
                    :max-length="10000"
                    :language="language"
                    :i18n="i18n"
                />
            </div>

            <!-- 执行频率 -->
            <div class="cron-create-task-dialog__form-item">
                <FrequencySelector
                    ref="frequencySelectorRef"
                    :language="language"
                    :i18n="i18n"
                />
            </div>

            <!-- 推送渠道 -->
            <div class="cron-create-task-dialog__form-item">
                <PushChannel
                    ref="pushChannelRef"
                    :application-id="applicationId"
                    :language="language"
                    :i18n="i18n"
                    @change="scrollBodyToBottom"
                />
            </div>

            <!-- 编辑模式：详情加载遮罩 -->
            <div v-if="detailLoading" class="cron-create-task-dialog__loading-mask">
                <t-loading size="small" />
            </div>
        </div>

        <div class="cron-create-task-dialog__footer">
            <t-button theme="default" :disabled="confirmLoading" @click="handleClose">
                {{ i18n.cancel }}
            </t-button>
            <t-button
                theme="primary"
                :loading="confirmLoading"
                :disabled="detailLoading"
                @click="handleConfirm"
            >
                {{ i18n.confirm }}
            </t-button>
        </div>
    </t-dialog>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick } from 'vue';
import {
    Dialog as TDialog,
    Input as TInput,
    Button as TButton,
    Loading as TLoading,
    MessagePlugin,
} from 'tdesign-vue-next';
import PromptInput from './PromptInput.vue';
import FrequencySelector from './FrequencySelector.vue';
import PushChannel from './PushChannel.vue';
import type {
    CronTaskI18n,
    TimerTask,
    TimerTaskSummary,
    TimerPushChannelValue,
    TimerScheduleConfig,
} from '../../../model/cronTask';
import {
    TimerScheduleType,
    TimerPushChannel,
    TimerPushTargetType,
    getCronTaskI18nByLanguage,
} from '../../../model/cronTask';
import { AppTriggerScope } from '../../../model/appTrigger';
import {
    createAppTrigger,
    modifyAppTrigger,
    describeAppTrigger,
} from '../../../service/appTriggerApi';
import type { CreateAppTriggerPayload, ModifyAppTriggerPayload } from '../../../service/appTriggerApi';
import { getTimerId } from '../../../utils/cronTask';
import { getTriggerId } from '../../../utils/appTrigger';

interface Props {
    visible: boolean;
    editingTask?: TimerTaskSummary | TimerTask | null;
    applicationId: string;
    /** @deprecated AppTrigger 不再需要 spaceId */
    spaceId?: string;
    /**
     * 触发器作用域（proto AppTriggerScope）。
     * USER(2) = C 端访客，默认，需配合 userId；APP(1) = B 端管理员。
     */
    scope?: number;
    /** C 端访客 ID，scope=USER 时必填 */
    userId?: string;
    language?: string;
    i18n?: Partial<CronTaskI18n>;
}

const props = withDefaults(defineProps<Props>(), {
    visible: false,
    editingTask: null,
    spaceId: '',
    scope: AppTriggerScope.USER,
    userId: '',
    language: 'zh-CN',
    i18n: () => ({}),
});

const emit = defineEmits<{
    (e: 'update:visible', v: boolean): void;
    (e: 'success', payload: { isEdit: boolean }): void;
    (e: 'close'): void;
}>();

const i18n = computed<Required<CronTaskI18n>>(() => ({
    ...getCronTaskI18nByLanguage(props.language),
    ...props.i18n,
}));

const isEdit = computed(() => !!props.editingTask);
const dialogTitle = computed(() => (isEdit.value ? i18n.value.dialogTitleEdit : i18n.value.dialogTitleCreate));

// ============================================================
// 状态
// ============================================================
const innerVisible = computed({
    get: () => props.visible,
    set: (v) => emit('update:visible', v),
});

const taskName = ref('');
const promptValue = ref('');
const confirmLoading = ref(false);
const detailLoading = ref(false);

const promptInputRef = ref<InstanceType<typeof PromptInput> | null>(null);
const frequencySelectorRef = ref<InstanceType<typeof FrequencySelector> | null>(null);
const pushChannelRef = ref<InstanceType<typeof PushChannel> | null>(null);

// ============================================================
// 交互
// ============================================================
function scrollBodyToBottom() {
    nextTick(() => {
        const body = document.querySelector('.cron-create-task-dialog__body');
        if (body) body.scrollTo({ top: (body as HTMLElement).scrollHeight, behavior: 'smooth' });
    });
}

// 等待子组件 ref 就绪（dialog 打开瞬间子树尚在挂载）
function _waitChildrenReady(maxTries = 20): Promise<boolean> {
    return new Promise((resolve) => {
        let tries = 0;
        const check = () => {
            const ready = promptInputRef.value && frequencySelectorRef.value && pushChannelRef.value;
            if (ready || tries >= maxTries) {
                resolve(!!ready);
                return;
            }
            tries += 1;
            nextTick(() => setTimeout(check, 16));
        };
        check();
    });
}

// ============================================================
// 组装 & 提交
// ============================================================

/**
 * 从 cron 表达式解析出 HH:mm 字符串。
 * ⚠️ proto `DailySchedule.time_of_day` / `WeeklyTime.time_of_day` 是字符串（校验正则
 * `^([0-1][0-9]|2[0-3]):[0-5][0-9]$`），不是 `{Hour, Minute}` 对象。
 * 之前误传对象会被后端 validate 拒（"invalid TimeOfDay" 类错误）。
 */
function _cronToTimeOfDay(cron: string): string {
    const parts = (cron || '').trim().split(/\s+/);
    const minute = Number(parts[0]) || 0;
    const hour = Number(parts[1]) || 0;
    const h = Math.min(23, Math.max(0, hour));
    const m = Math.min(59, Math.max(0, minute));
    return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`;
}

/**
 * 拼 ISO8601 时间字符串（proto `IntervalSchedule.start_at` / `OnceSchedule.fire_time`）。
 * date + time 为本地时区（Asia/Shanghai 默认）时的墙钟时间，这里追加本地时区偏移，
 * 得到形如 `2026-07-23T09:00:00+08:00` 的严格 ISO8601 字符串，避免歧义。
 */
function _toIso8601(date: string, time: string): string {
    if (!date || !time) return '';
    const offsetMin = -new Date().getTimezoneOffset();
    const sign = offsetMin >= 0 ? '+' : '-';
    const abs = Math.abs(offsetMin);
    const oh = String(Math.floor(abs / 60)).padStart(2, '0');
    const om = String(abs % 60).padStart(2, '0');
    return `${date}T${time}:00${sign}${oh}:${om}`;
}

function _buildSchedule(freq: ReturnType<NonNullable<typeof frequencySelectorRef.value>['getFormData']>) {
    const schedule: Record<string, any> = {
        Timezone: freq.timezone || 'Asia/Shanghai',
    };
    switch (freq.type) {
        case 'daily':
            schedule.ScheduleType = TimerScheduleType.DAILY;
            // proto DailySchedule.time_of_day 是 HH:mm 字符串
            schedule.Daily = { TimeOfDay: _cronToTimeOfDay(freq.cron || '') };
            break;
        case 'weekly':
            schedule.ScheduleType = TimerScheduleType.WEEKLY;
            schedule.Weekly = {
                Times: (freq.weekDays || []).map((day) => ({
                    // proto 1..7 表示周一..周日
                    Weekday: day === 0 ? 7 : day,
                    // proto WeeklyTime.time_of_day 是 HH:mm 字符串
                    TimeOfDay: _cronToTimeOfDay(freq.cron || ''),
                })),
            };
            break;
        case 'interval':
            schedule.ScheduleType = TimerScheduleType.INTERVAL;
            schedule.Interval = {
                Value: freq.intervalValue || 1,
                // 1 = INTERVAL_UNIT_HOUR
                Unit: 1,
                // proto 要求 ISO8601 且 min_len=1，带上时区偏移
                StartAt: _toIso8601(freq.startDate || '', freq.startTime || ''),
            };
            break;
        case 'once':
            schedule.ScheduleType = TimerScheduleType.ONCE;
            schedule.Once = {
                FireTime: _toIso8601(freq.date || '', freq.time || ''),
            };
            break;
        case 'cron':
            schedule.ScheduleType = TimerScheduleType.CRON;
            schedule.Cron = { Expression: freq.cron || '' };
            break;
        default:
            schedule.ScheduleType = TimerScheduleType.DAILY;
            schedule.Daily = { TimeOfDay: '09:00' };
    }
    return schedule as TimerScheduleConfig;
}

/**
 * 根据 push_channel 语义映射 push_target_type。
 *
 * proto 定义（time_scheduler.proto）:
 *   - TIMER_PUSH_CHANNEL_WECHAT       → target 为公众号 openid → USER(1)
 *   - TIMER_PUSH_CHANNEL_WECOM_BOT    → target 为企微 chat_id  → CHAT(2)
 *   - TIMER_PUSH_CHANNEL_WECOM_WEBHOOK→ 走 webhook_url，无目标 → UNSPECIFIED(0)
 *   - TIMER_PUSH_CHANNEL_NONE / UNSPECIFIED → UNSPECIFIED(0)
 *
 * 该映射由 proto 语义唯一决定，任何 channel 新增/调整都应同步这里。
 */
function _resolvePushTargetType(channel: TimerPushChannelValue): number {
    switch (channel) {
        case TimerPushChannel.WECHAT:
            return TimerPushTargetType.USER;
        case TimerPushChannel.WECOM_BOT:
            return TimerPushTargetType.CHAT;
        // WECOM_WEBHOOK / NONE / UNSPECIFIED
        default:
            return TimerPushTargetType.UNSPECIFIED;
    }
}

/**
 * 构造 push_config（对齐 proto TimerPushConfig）
 * - PushChannel:    1 NONE / 2 WECHAT / 3 WECOM_BOT / 4 WECOM_WEBHOOK
 * - PushTargetType: 由 channel 语义映射（见 _resolvePushTargetType）
 * - PushTargetId:   选中的会话 ID（openid / chat_id）
 */
function _buildPushConfig(pushData: {
    channel: TimerPushChannelValue;
    targetId: string;
}) {
    const channel = pushData.channel || TimerPushChannel.NONE;
    const config: Record<string, any> = {
        PushChannel: channel,
        PushTargetType: _resolvePushTargetType(channel),
    };
    if (channel !== TimerPushChannel.NONE) {
        config.PushTargetId = pushData.targetId || '';
    }
    return config;
}

async function handleConfirm() {
    if (confirmLoading.value) return;

    if (!taskName.value || !taskName.value.trim()) {
        MessagePlugin.warning(i18n.value.taskNamePlaceholder);
        return;
    }
    if (taskName.value.trim().length > 50) {
        MessagePlugin.warning(i18n.value.taskNamePlaceholder);
        return;
    }

    if (!promptInputRef.value) return;
    const promptResult = promptInputRef.value.validate();
    if (!promptResult.valid) {
        MessagePlugin.warning(promptResult.message || i18n.value.promptPlaceholder);
        return;
    }

    if (!frequencySelectorRef.value) return;
    const freqResult = frequencySelectorRef.value.validate();
    if (!freqResult.valid) {
        MessagePlugin.warning(freqResult.message || i18n.value.frequencyLabel);
        return;
    }

    if (!pushChannelRef.value) return;
    const pushResult = pushChannelRef.value.validate();
    if (!pushResult.valid) {
        MessagePlugin.warning(pushResult.message || i18n.value.pushLabel);
        return;
    }

    const promptData = promptInputRef.value.getFormData();
    const freqData = frequencySelectorRef.value.getFormData();
    const pushData = pushChannelRef.value.getFormData();

    confirmLoading.value = true;
    try {
        if (isEdit.value) {
            // —— 编辑：调 ModifyAppTrigger ——
            const triggerId = getTriggerId(props.editingTask || {}) || getTimerId(props.editingTask || {});
            if (!triggerId) throw new Error('missing trigger id');

            const updateMask: ModifyAppTriggerPayload = {
                TriggerId: triggerId,
                Scope: props.scope,
                ...(props.userId ? { UserId: props.userId } : {}),
                Trigger: {
                    TriggerName: taskName.value.trim(),
                    TriggerConfig: { ScheduledConfig: { Schedule: _buildSchedule(freqData) } },
                    ExecuteConfig: {
                        PromptConfig: {
                            ExecutePrompt: promptData.ExecutePrompt,
                        },
                    },
                    PushConfig: _buildPushConfig(pushData),
                },
                UpdateMask: {
                    Paths: [
                        'trigger_name',
                        'trigger_config.scheduled_config.schedule',
                        'execute_config.prompt_config.execute_prompt',
                        'push_config',
                    ],
                },
            };
            await modifyAppTrigger(updateMask, props.applicationId);
            // ⚠️ ModifyAppTriggerRsp 无 next_fire_time，调用方需补偿刷新
            MessagePlugin.success(i18n.value.updateSuccess);
        } else {
            // —— 创建：调 CreateAppTrigger ——
            const triggerType = 1; // SCHEDULED
            const executeType = 1; // PROMPT
            const payload: CreateAppTriggerPayload = {
                TriggerName: taskName.value.trim(),
                TriggerType: triggerType,
                ExecuteType: executeType,
                PushConfig: _buildPushConfig(pushData),
                TriggerConfig: { ScheduledConfig: { Schedule: _buildSchedule(freqData) } },
                ExecuteConfig: {
                    PromptConfig: {
                        ExecutePrompt: promptData.ExecutePrompt,
                    },
                },
                Scope: props.scope,
                ...(props.userId ? { UserId: props.userId } : {}),
            };
            await createAppTrigger(payload, props.applicationId);
            MessagePlugin.success(i18n.value.createSuccess);
        }
        emit('success', { isEdit: isEdit.value });
        handleClose();
    } catch (e) {
        console.error('[CreateTaskDialog] submit failed:', e);
        MessagePlugin.error(isEdit.value ? i18n.value.updateFailed : i18n.value.createFailed);
    } finally {
        confirmLoading.value = false;
    }
}

function handleClose() {
    innerVisible.value = false;
    emit('close');
}

// ============================================================
// 表单重置 / 回填
// ============================================================

async function resetForm() {
    taskName.value = '';
    promptValue.value = '';
    await _waitChildrenReady();
    promptInputRef.value?.resetForm();
    frequencySelectorRef.value?.resetForm();
    pushChannelRef.value?.resetForm();
}

async function fillFormWithTask(task: TimerTaskSummary | TimerTask) {
    const triggerId = getTriggerId(task) || getTimerId(task);
    if (!triggerId) return;

    await resetForm();
    detailLoading.value = true;
    try {
        // 优先调新 AppTrigger 接口
        let detail: any = null;
        try {
            detail = await describeAppTrigger(triggerId, props.applicationId, props.scope, undefined, props.userId);
        } catch {
            // 回退：旧 TimerTask 接口（存量数据兼容）
            const { describeTimerTask } = await import('../../../service/cronTaskApi');
            detail = await describeTimerTask(
                { SpaceId: props.spaceId, TimerId: triggerId },
                props.applicationId,
            );
        }

        // 从 AppTrigger 或 TimerTask 结构中提取字段
        const triggerName =
            detail?.TriggerName ??
            detail?.profile?.TaskName ?? detail?.Profile?.task_name ?? '';
        const promptText =
            detail?.ExecuteConfig?.PromptConfig?.ExecutePrompt ??
            detail?.execute_config?.prompt_config?.execute_prompt ??
            detail?.PromptConfig?.ExecutePrompt ??
            detail?.prompt_config?.execute_prompt ??
            detail?.profile?.PromptContent ?? detail?.Profile?.prompt_content ??
            detail?.profile?.prompt ?? detail?.Profile?.Prompt ?? '';
        const schedule =
            detail?.TriggerConfig?.ScheduledConfig?.Schedule ??
            detail?.trigger_config?.scheduled_config?.schedule ??
            detail?.ScheduledConfig?.Schedule ??
            detail?.scheduled_config?.schedule ??
            detail?.config?.Schedule ?? detail?.Config?.schedule ??
            detail?.config?.schedule ?? null;
        const pushConfig =
            detail?.PushConfig ?? detail?.push_config ??
            detail?.config?.Push ?? detail?.Config?.push ??
            detail?.config?.push_config ?? detail?.Config?.push_config ?? null;

        taskName.value = triggerName;
        promptValue.value = promptText;

        await _waitChildrenReady();
        promptInputRef.value?.setFormData({ ExecutePrompt: promptText });
        if (schedule) frequencySelectorRef.value?.setFormData(schedule);
        if (pushConfig) pushChannelRef.value?.setFormData(pushConfig);
    } catch (e) {
        console.error('[CreateTaskDialog] fillFormWithTask failed:', e);
        MessagePlugin.error(i18n.value.loadFailed);
    } finally {
        detailLoading.value = false;
    }
}

// visible 变化时初始化表单
watch(
    () => props.visible,
    (val) => {
        if (!val) return;
        if (isEdit.value && props.editingTask) {
            fillFormWithTask(props.editingTask);
        } else {
            resetForm();
        }
    },
);

defineExpose({ resetForm, fillFormWithTask });
</script>

<style scoped>
.cron-create-task-dialog__body {
    padding: 0 var(--td-size-2) var(--td-size-2);
    max-height: min(450px, calc(100vh - 240px));
    overflow-y: auto;
    position: relative;
}

/* 自定义滚动条：对齐系统其他面板（CronTaskPanel .panel-body / chat-overrides） */
.cron-create-task-dialog__body::-webkit-scrollbar {
    width: 6px;
}

.cron-create-task-dialog__body::-webkit-scrollbar-track {
    background: transparent;
}

.cron-create-task-dialog__body::-webkit-scrollbar-thumb {
    border-radius: var(--td-radius-default);
    background: transparent;
}

.cron-create-task-dialog__body:hover::-webkit-scrollbar-thumb {
    background: var(--td-scrollbar-color);
}

.cron-create-task-dialog__body:hover::-webkit-scrollbar-thumb:hover {
    background: var(--td-scrollbar-hover-color);
}

.cron-create-task-dialog__form-item {
    margin-bottom: var(--td-size-7);
}

.cron-create-task-dialog__form-item:last-child {
    margin-bottom: 0;
}

.cron-create-task-dialog__label {
    font-size: var(--td-font-size-body-medium);
    font-weight: 500;
    color: var(--td-text-color-primary);
    line-height: var(--td-line-height-body-medium);
    margin-bottom: var(--td-size-4);
}

.cron-create-task-dialog__required {
    color: var(--td-error-color);
    margin-left: var(--td-size-1);
}

.cron-create-task-dialog__loading-mask {
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    background: var(--td-mask-disabled);
    z-index: 10;
}

.cron-create-task-dialog__footer {
    display: flex;
    justify-content: flex-end;
    gap: var(--td-size-4);
    padding-top: var(--td-size-5);
    border-top: 1px solid var(--td-component-border);
    margin-top: var(--td-size-5);
}
</style>
