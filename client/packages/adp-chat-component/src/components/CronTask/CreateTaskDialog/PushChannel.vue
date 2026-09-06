<template>
    <div class="cron-push-channel">
        <div class="cron-push-channel__label">
            {{ i18n.pushLabel }}
            <span class="cron-push-channel__required">*</span>
        </div>

        <t-radio-group v-model="channel" class="cron-push-channel__radio-group" @change="onChannelChange">
            <t-radio :value="TimerPushChannel.NONE">{{ i18n.pushNone }}</t-radio>
            <t-radio
                :value="TimerPushChannel.WECOM_BOT"
                :disabled="isChannelDisabled(TimerPushChannel.WECOM_BOT)"
            >{{ i18n.pushWecomBot }}</t-radio>
            <t-radio
                :value="TimerPushChannel.WECHAT"
                :disabled="isChannelDisabled(TimerPushChannel.WECHAT)"
            >{{ i18n.pushWechat }}</t-radio>
            <span v-if="channelListLoading && !channelListLoaded" class="cron-push-channel__loading">
                <t-loading size="small" />
            </span>
        </t-radio-group>

        <!-- 选中具体渠道后展示"选择会话"下拉 -->
        <div v-if="channel !== TimerPushChannel.NONE" class="cron-push-channel__extra">
            <t-select
                v-model="targetId"
                :options="targetOptions"
                :loading="conversationLoading"
                :disabled="isChannelDisabled(channel)"
                :placeholder="conversationLoading ? i18n.conversationLoading : i18n.conversationPlaceholder"
                :empty="i18n.conversationEmpty"
                filterable
                clearable
                class="cron-push-channel__target-select"
            />
        </div>
    </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue';
import {
    RadioGroup as TRadioGroup,
    Radio as TRadio,
    Select as TSelect,
    Loading as TLoading,
} from 'tdesign-vue-next';
import type { CronTaskI18n, TimerPushChannelValue } from '../../../model/cronTask';
import {
    getCronTaskI18nByLanguage,
    TimerPushChannel,
} from '../../../model/cronTask';
import {
    describeChannelList,
    ChannelType,
    ClawChannelStatus,
    type ChannelItem,
} from '../../../service/channelApi';
import { describeConversationList, type CapiConversationItem } from '../../../service/api';

/**
 * 定时任务推送渠道选择器
 *
 * 对齐 smart-webim `push-channel.vue`：
 *   - Radio 三选一：不推送 / 企微智能机器人 / 微信
 *   - 未在已配置渠道列表中的选项自动禁用（对齐 webim availableChannels 逻辑）
 *   - 选中具体渠道后展示"选择会话"下拉
 *
 * 数据链路（tcadp 走 CAPI，无 webim 的企业助手 API）：
 *   1. describeChannelList({ applicationId }) → 找到 channelType 对应的渠道
 *   2. 从 channel 中取 channelId + spec.UserAgent.{UserId, AgentId}
 *   3. describeConversationList({ AppId, UserId, AgentId, ChannelId, Type:5 })
 *      → 完整参数对齐右侧「渠道对话记录」面板（ChannelConversationPanel），
 *        缺少 ChannelId 时企微渠道会话会返空
 *
 * 协议映射（proto TimerPushChannel ↔ ChannelType）：
 *   - WECOM_BOT (3)  ↔ WECOM_ROBOT_WS (10014)
 *   - WECHAT   (2)  ↔ WECHAT_CLAWBOT  (10015)
 *
 * ⚠️ 关于 PushTargetType：
 *   proto 中 push_target_type 由 push_channel 语义唯一决定
 *   （WECHAT→USER=1, WECOM_BOT→CHAT=2, WECOM_WEBHOOK→UNSPECIFIED=0）。
 *   映射逻辑集中在 CreateTaskDialog `_resolvePushTargetType`，
 *   本组件仅负责收集 channel + targetId，不参与 targetType 计算。
 */
interface Props {
    /** 应用 ID：拉取渠道列表和会话列表都需要 */
    applicationId: string;
    language?: string;
    i18n?: Partial<CronTaskI18n>;
}

const props = withDefaults(defineProps<Props>(), {
    applicationId: '',
    language: 'zh-CN',
    i18n: () => ({}),
});

const emit = defineEmits<{
    (e: 'change'): void;
}>();

const i18n = computed<Required<CronTaskI18n>>(() => ({
    ...getCronTaskI18nByLanguage(props.language),
    ...props.i18n,
}));

// ============================================================
// 状态
// ============================================================
const channel = ref<TimerPushChannelValue>(TimerPushChannel.NONE);
const targetId = ref<string>('');
/** 编辑回填期间抑制 change 冒泡，避免触发父级滚动到底 */
const isFilling = ref(false);

/** 已加载的渠道列表（挂载时立即拉一次，用于禁用判断 & 拉会话） */
const channelList = ref<ChannelItem[]>([]);
const channelListLoaded = ref(false);
const channelListLoading = ref(false);

/**
 * 按渠道类型缓存会话列表
 * key = TimerPushChannelValue（2/3），value = { list, loading, loaded }
 */
interface ConvEntry {
    list: CapiConversationItem[];
    loading: boolean;
    loaded: boolean;
}
const conversationsByChannel = ref<Record<number, ConvEntry>>({});

// ============================================================
// 派生
// ============================================================
const currentEntry = computed<ConvEntry | null>(() => conversationsByChannel.value[channel.value] || null);
const conversationLoading = computed(() => !!(currentEntry.value && currentEntry.value.loading));
const targetOptions = computed(() => {
    const list = currentEntry.value ? currentEntry.value.list : [];
    // 按 UpdateTime 倒序
    return [...list]
        .sort((a, b) => Number(b.UpdateTime || 0) - Number(a.UpdateTime || 0))
        .map((item) => ({
            label: item.Title || item.ConversationId || i18n.value.conversationPlaceholder,
            value: item.ConversationId,
        }));
});

// ============================================================
// 辅助：proto TimerPushChannel → 渠道 ChannelType
// ============================================================
function _pushChannelToChannelType(pc: TimerPushChannelValue): number {
    if (pc === TimerPushChannel.WECOM_BOT) return ChannelType.WECOM_ROBOT_WS;
    if (pc === TimerPushChannel.WECHAT) return ChannelType.WECHAT_CLAWBOT;
    return 0;
}

/** 从已加载渠道列表中找可用（连接成功）的渠道 */
function _findChannel(pc: TimerPushChannelValue): ChannelItem | null {
    const chType = _pushChannelToChannelType(pc);
    if (!chType) return null;
    // 优先取已成功连接的渠道；找不到再退回类型匹配的第一条
    const matched = channelList.value.filter((c) => c.channelType === chType);
    if (matched.length === 0) return null;
    const active = matched.find((c) => c.connectStatus === ClawChannelStatus.SUCCESS);
    return active || matched[0] || null;
}

/** 未绑定（渠道列表中无该类型 或 该类型未成功连接）→ 禁用 */
function isChannelDisabled(pc: TimerPushChannelValue): boolean {
    // 列表未加载完之前保持禁用，避免用户点了却拉不到会话
    if (!channelListLoaded.value) return true;
    const chType = _pushChannelToChannelType(pc);
    if (!chType) return true;
    return !channelList.value.some(
        (c) => c.channelType === chType && c.connectStatus === ClawChannelStatus.SUCCESS,
    );
}

// ============================================================
// 拉取
// ============================================================

/** 拉一次渠道列表（幂等，多次调用只请求一次） */
async function ensureChannelList(): Promise<void> {
    if (channelListLoaded.value || channelListLoading.value) return;
    if (!props.applicationId) return;
    channelListLoading.value = true;
    try {
        const { channelList: list } = await describeChannelList({
            applicationId: props.applicationId,
            pageNumber: 1,
            pageSize: 100,
        });
        channelList.value = list || [];
        channelListLoaded.value = true;
    } catch (e) {
        console.error('[PushChannel] describeChannelList failed:', e);
        channelList.value = [];
        // 不置 loaded=true，允许下次重试
    } finally {
        channelListLoading.value = false;
    }
}

/**
 * 按需拉指定 TimerPushChannel 下的会话列表（带缓存）
 * 参数完全对齐右侧渠道对话面板（ChannelConversationPanel）：
 *   AppId + UserId + AgentId + ChannelId + Type=5
 * 缺 ChannelId 会导致企微渠道会话拉不到
 */
async function ensureConversations(pc: TimerPushChannelValue, force = false): Promise<void> {
    if (!pc || pc === TimerPushChannel.NONE) return;
    const cached = conversationsByChannel.value[pc];
    if (!force && cached && (cached.loaded || cached.loading)) return;

    // 标记 loading
    conversationsByChannel.value = {
        ...conversationsByChannel.value,
        [pc]: {
            list: cached ? cached.list : [],
            loading: true,
            loaded: false,
        },
    };

    // 先确保渠道列表已加载
    await ensureChannelList();

    const matched = _findChannel(pc);
    if (!matched) {
        // 该渠道未配置，直接置空
        conversationsByChannel.value = {
            ...conversationsByChannel.value,
            [pc]: { list: [], loading: false, loaded: true },
        };
        return;
    }

    const userId = matched.spec?.UserAgent?.UserId || '';
    const agentId = matched.spec?.UserAgent?.AgentId || '';
    const channelIdStr = matched.channelId ? String(matched.channelId) : '';

    try {
        const { conversations } = await describeConversationList(
            {
                Type: 5,
                AppId: props.applicationId,
                UserId: userId || undefined,
                AgentId: agentId || undefined,
                // ChannelId 是企微渠道会话过滤的关键字段（对齐 ChannelConversationPanel）
                ChannelId: channelIdStr || undefined,
                Offset: 0,
                Limit: 50,
            },
            props.applicationId,
        );
        conversationsByChannel.value = {
            ...conversationsByChannel.value,
            [pc]: { list: conversations || [], loading: false, loaded: true },
        };
    } catch (e) {
        console.error('[PushChannel] describeConversationList failed:', { pc, error: e });
        conversationsByChannel.value = {
            ...conversationsByChannel.value,
            [pc]: { list: [], loading: false, loaded: true },
        };
    }
}

// ============================================================
// 交互
// ============================================================

function onChannelChange() {
    // 编辑回填期间不清空、不冒泡
    if (!isFilling.value) {
        targetId.value = '';
        emit('change');
    }
    if (channel.value !== TimerPushChannel.NONE) {
        ensureConversations(channel.value);
    }
}

/**
 * 应用 ID 变化时清空所有缓存
 * （不同应用有不同的渠道 / 用户 / 会话，防止串态）
 */
watch(
    () => props.applicationId,
    (id) => {
        channelList.value = [];
        channelListLoaded.value = false;
        channelListLoading.value = false;
        conversationsByChannel.value = {};
        if (id) ensureChannelList();
    },
    { immediate: true },
);

// ============================================================
// 对外方法
// ============================================================

function validate(): { valid: boolean; message?: string } {
    if (channel.value !== TimerPushChannel.NONE) {
        if (!targetId.value || !String(targetId.value).trim()) {
            return { valid: false, message: i18n.value.conversationRequired };
        }
    }
    return { valid: true };
}

/**
 * 获取表单数据（对齐 proto TimerPushConfig 字段）
 * - channel: push_channel
 * - targetId: push_target_id（会话 ID）
 *
 * ⚠️ 本组件不输出 targetType：proto 中 push_target_type 由 channel 语义唯一决定，
 *    统一在 CreateTaskDialog `_resolvePushTargetType` 中按 channel 映射后提交，
 *    避免本组件与调用方各自维护一份映射造成漂移。
 */
function getFormData(): {
    channel: TimerPushChannelValue;
    targetId: string;
} {
    const isReal = channel.value !== TimerPushChannel.NONE;
    return {
        channel: channel.value,
        targetId: isReal ? String(targetId.value || '').trim() : '',
    };
}

/**
 * 编辑回填：兼容新老字段
 *   - 新协议：PushChannel / PushTargetId / PushTargetType
 *   - 旧 snake_case：push_channel / push_target_id / push_target_type
 *   - 旧结构（本前端曾用）：Channel + WecomBot.WebhookUrl（无会话概念，只还原 channel）
 */
function setFormData(config: any) {
    isFilling.value = true;
    try {
        if (!config || typeof config !== 'object') {
            channel.value = TimerPushChannel.NONE;
            targetId.value = '';
            return;
        }
        const ch =
            config.PushChannel ??
            config.push_channel ??
            config.Channel ??
            config.channel;
        if (typeof ch === 'number') {
            channel.value = ch as TimerPushChannelValue;
        } else {
            channel.value = TimerPushChannel.NONE;
        }

        const tid =
            config.PushTargetId ??
            config.push_target_id ??
            '';
        targetId.value = String(tid || '');

        // 选中具体渠道时拉一次会话列表，保证下拉能展示 label
        if (channel.value !== TimerPushChannel.NONE) {
            ensureConversations(channel.value);
        }
    } finally {
        // 等 v-model 联动事件触发完毕再解锁
        setTimeout(() => {
            isFilling.value = false;
        }, 0);
    }
}

function resetForm() {
    isFilling.value = true;
    channel.value = TimerPushChannel.NONE;
    targetId.value = '';
    setTimeout(() => {
        isFilling.value = false;
    }, 0);
}

defineExpose({ validate, getFormData, setFormData, resetForm });
</script>

<style scoped>
.cron-push-channel {
    display: flex;
    flex-direction: column;
    gap: var(--td-size-4);
}

.cron-push-channel__label {
    font-size: var(--td-font-size-body-medium);
    font-weight: 500;
    color: var(--td-text-color-primary);
    line-height: var(--td-line-height-body-medium);
}

.cron-push-channel__required {
    color: var(--td-error-color);
    margin-left: var(--td-size-1);
}

.cron-push-channel__radio-group {
    display: flex;
    align-items: center;
    gap: var(--td-size-6);
    flex-wrap: wrap;
}

.cron-push-channel__loading {
    display: inline-flex;
    align-items: center;
}

.cron-push-channel__extra {
    margin-top: var(--td-size-2);
    padding: var(--td-size-4);
    background: var(--td-bg-color-container-hover);
    border-radius: var(--td-radius-medium);
}

.cron-push-channel__target-select {
    width: 100%;
}
</style>
