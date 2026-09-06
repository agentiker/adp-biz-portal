<!--
  企微智能机器人渠道配置弹窗
  @description
    对应 proto ChannelType = 10014（WECOM_ROBOT_WS）
    新建：调用 CreateChannel（scene=1, channel_type=10014, WecomRobot.Websocket）
    重新配置：调用 ModifyChannel（channel_id 已存在时）
    交互对齐 webim 的 wecom-bot-config-dialog

  扫码绑定说明：
    "点击链接" 走懒加载的 window.WecomAIBotSDK.openBotInfoAuthWindow，
    SDK 通过 workspace 包 `wecom-aibot-sdk` 动态 import 加载（UMD 副作用会挂到 window），
    扫码通过 onCreated 回调返回 { botid, secret } 自动回填表单。
    若 SDK 加载失败或未暴露 openBotInfoAuthWindow，均降级到手动填写。
-->
<script setup lang="ts">
import { ref, computed, watch } from 'vue';
import {
    Dialog as TDialog,
    Form as TForm,
    FormItem as TFormItem,
    Input as TInput,
    Button as TButton,
    MessagePlugin,
} from 'tdesign-vue-next';
import type { FormInstanceFunctions, FormRules } from 'tdesign-vue-next';
import type { ThemeProps } from '../../model/type';
import { themePropsDefaults } from '../../model/type';
import {
    type ChannelItem,
    type ChannelSettingsI18n,
    ChannelType,
    defaultChannelSettingsI18n,
    defaultChannelSettingsI18nEn,
} from '../../model/channel';
import { createChannel, modifyChannel, buildChannelUserId } from '../../service/channelApi';

// ============================================================
// SDK 类型（window.WecomAIBotSDK，由本地包 wecom-aibot-sdk 副作用挂载）
// ============================================================

/** 扫码授权成功回调数据 */
interface WecomAIBotSDKCreatedBot {
    /** Bot ID */
    botid?: string;
    /** Bot Secret */
    secret?: string;
}

/** SDK 打开授权窗口的入参 */
interface WecomAIBotSDKOpenParams {
    /** 业务来源，透传给企微以便统计 */
    source: string;
    /** 扫码创建/授权成功回调 */
    onCreated?: (bot: WecomAIBotSDKCreatedBot | null | undefined) => void;
    /** 授权失败回调（用户主动关闭 / 网络失败 / 后台报错） */
    onError?: (err?: unknown) => void;
}

/** window.WecomAIBotSDK 接口约束 */
interface WecomAIBotSDK {
    openBotInfoAuthWindow: (params: WecomAIBotSDKOpenParams) => void;
}

/** 声明全局挂载点，避免每处使用都 as any */
declare global {
    interface Window {
        WecomAIBotSDK?: WecomAIBotSDK;
    }
}

// ============================================================
// Props / Emits
// ============================================================

interface Props extends ThemeProps {
    modelValue: boolean;
    /** 应用 ID */
    applicationId: string;
    /** C 端归属用户 ID */
    userId?: string;
    /** C 端 claw agent 运行态 ID */
    agentId?: string;
    /**
     * 编辑中的渠道数据
     * - 首次配置：null（创建新渠道）
     * - 重新配置：{ channelId, spec }（修改已有渠道）
     */
    editingChannel: ChannelItem | null;
    i18n?: Partial<ChannelSettingsI18n>;
    language?: string;
}

const props = withDefaults(defineProps<Props>(), {
    ...themePropsDefaults,
    modelValue: false,
    applicationId: '',
    userId: '',
    agentId: '',
    editingChannel: null,
    i18n: () => ({}),
    language: 'zh-CN',
});

const emit = defineEmits<{
    (e: 'update:modelValue', val: boolean): void;
    (e: 'submitted'): void;
    (e: 'close'): void;
}>();

// ============================================================
// I18n
// ============================================================

const mergedI18n = computed<Required<ChannelSettingsI18n>>(() => {
    const defaults = props.language?.startsWith('en')
        ? defaultChannelSettingsI18nEn
        : defaultChannelSettingsI18n;
    return { ...defaults, ...props.i18n };
});

// ============================================================
// v-model
// ============================================================

const visible = computed({
    get: () => props.modelValue,
    set: (v) => emit('update:modelValue', v),
});

// ============================================================
// 表单
// ============================================================

const formRef = ref<FormInstanceFunctions | null>(null);

const formData = ref({
    botId: '',
    botSecret: '',
});

const submitting = ref(false);
/** SDK 是否正在加载中，避免多次点击重复注入 */
const sdkLoading = ref(false);

/** 是否为重新配置模式 */
const isModify = computed(() => {
    return props.editingChannel !== null && props.editingChannel.channelId > 0;
});

/** 对话框标题 */
const dialogTitle = computed(() => {
    return isModify.value
        ? mergedI18n.value.wecomBotDialogTitleModify
        : mergedI18n.value.wecomBotDialogTitleCreate;
});

// 弹窗打开时初始化表单
watch(() => props.modelValue, (val) => {
    if (val) {
        formData.value = { botId: '', botSecret: '' };
        if (props.editingChannel) {
            // 尝试从已有渠道数据中回填
            const spec = props.editingChannel.spec || {};
            const wecomRobot = (spec as any).WecomRobot || (spec as any).wecom_robot || {};
            const ws = wecomRobot.Websocket || wecomRobot.websocket || {};
            formData.value.botId = (ws.BotId || ws.bot_id || '') as string;
            formData.value.botSecret = (ws.BotSecret || ws.bot_secret || '') as string;
        }
    }
});

// ============================================================
// SDK 懒加载 + 扫码
// ============================================================

/** SDK 加载 Promise 缓存，避免多次点击并发 import */
let sdkLoadPromise: Promise<void> | null = null;

/**
 * 按需加载本地 workspace 包 `wecom-aibot-sdk`。
 * - 该包是官方 UMD 脚本，副作用会挂 window.WecomAIBotSDK。
 * - 若 window.WecomAIBotSDK 已存在，直接 resolve。
 * - 若同一 Promise 正在进行中，复用之。
 */
function loadWecomAIBotSDK(): Promise<void> {
    if (typeof window === 'undefined') {
        return Promise.reject(new Error('window is undefined'));
    }
    if (window.WecomAIBotSDK) {
        return Promise.resolve();
    }
    if (sdkLoadPromise) {
        return sdkLoadPromise;
    }
    sdkLoadPromise = import('wecom-aibot-sdk')
        .then(() => {
            if (!window.WecomAIBotSDK) {
                throw new Error('wecom-aibot-sdk loaded but window.WecomAIBotSDK is missing');
            }
        })
        .catch((err) => {
            sdkLoadPromise = null;
            throw err;
        });
    return sdkLoadPromise;
}

/**
 * "点击链接"入口：先按需加载 SDK，再调用 openBotInfoAuthWindow 弹企微扫码窗口。
 * SDK 回调返回 botid/secret 时自动回填表单，回调失败或 SDK 未暴露入口一律降级到手动填写。
 */
const handleOpenWecomLink = async () => {
    const i18n = mergedI18n.value;
    if (sdkLoading.value) return;
    sdkLoading.value = true;
    try {
        await loadWecomAIBotSDK();
        const sdk = window.WecomAIBotSDK;
        if (!sdk || typeof sdk.openBotInfoAuthWindow !== 'function') {
            MessagePlugin.warning(i18n.wecomBotSdkNotLoaded);
            return;
        }
        sdk.openBotInfoAuthWindow({
            source: 'tcadp',
            onCreated: (bot) => {
                if (bot?.botid) {
                    formData.value.botId = bot.botid;
                }
                if (bot?.secret) {
                    formData.value.botSecret = bot.secret;
                }
            },
            onError: () => {
                MessagePlugin.error(i18n.wecomBotSdkAuthFailed);
            },
        });
    } catch (e) {
        console.error('[WecomBotConfigDialog] SDK 加载失败:', e);
        MessagePlugin.error(i18n.wecomBotSdkLoadFailed);
    } finally {
        sdkLoading.value = false;
    }
};

// ============================================================
// 提交
// ============================================================

const handleSubmit = async () => {
    const valid = await formRef.value?.validate();
    if (valid !== true && valid !== undefined) return;

    submitting.value = true;
    try {
        const channelConfig = {
            WecomRobot: {
                Websocket: {
                    BotId: formData.value.botId,
                    BotSecret: formData.value.botSecret,
                    BindType: 2, // 填写表单绑定（对齐 webim）
                },
            },
        };

        if (isModify.value) {
            // 重新配置：调用 ModifyChannel
            // UpdateMask 必须指定到具体字段路径（proto FieldMask 语义）：
            // C 端企微机器人 WebSocket 仅修改 BotId / BotSecret，对齐 proto 注释示例
            //   spec.wecom_robot.websocket.bot_id / spec.wecom_robot.websocket.bot_secret
            // 若只传顶层 spec.wecom_robot 会整体覆盖（含未变更字段），故精确到嵌套字段。
            await modifyChannel(
                {
                    applicationId: props.applicationId,
                    channelId: props.editingChannel!.channelId,
                    channelType: ChannelType.WECOM_ROBOT_WS,
                    channelName: mergedI18n.value.channelNameWecomRobot,
                    channelConfig,
                    userAgent: {
                        userId: buildChannelUserId(props.userId || ''),
                        agentId: props.agentId || '',
                    },
                    updateMask: [
                        'spec.wecom_robot.websocket.bot_id',
                        'spec.wecom_robot.websocket.bot_secret',
                    ],
                },
            );
            MessagePlugin.success(mergedI18n.value.wecomBotModifySuccess);
        } else {
            // 首次配置：调用 CreateChannel
            // 【方案1】UserAgent.UserId 绑「派生的稳定渠道用户 id」（custom-<账号id>），而不是登录账号 id：
            // 登录账号 id = 后端默认注入的 {{ACCOUNT_ID}}，会让渠道会话与账号会话混在一起、无法隔离；
            // custom-<账号id> 稳定唯一、该用户所有渠道共用同一个，且与账号自身会话隔离。
            await createChannel(
                {
                    applicationId: props.applicationId,
                    channelType: ChannelType.WECOM_ROBOT_WS,
                    channelName: mergedI18n.value.channelNameWecomRobot,
                    channelConfig,
                    userAgent: {
                        userId: buildChannelUserId(props.userId || ''),
                        agentId: props.agentId || '',
                    },
                },
            );
            MessagePlugin.success(mergedI18n.value.wecomBotCreateSuccess);
        }

        emit('submitted');
        visible.value = false;
    } catch (err: any) {
        MessagePlugin.error(err?.message || mergedI18n.value.wecomBotConfigFailed);
    } finally {
        submitting.value = false;
    }
};

const handleClose = () => {
    emit('close');
};

// 表单校验规则（提交时根据 i18n 动态生成，保证多语言切换后 message 也跟随变化）
const rules = computed<FormRules>(() => ({
    botId: [{ required: true, message: mergedI18n.value.wecomBotBotIdRequired, trigger: 'blur' }],
    botSecret: [{ required: true, message: mergedI18n.value.wecomBotSecretRequired, trigger: 'blur' }],
}));
</script>

<template>
    <Teleport to="body">
        <t-dialog
            v-model:visible="visible"
            :header="dialogTitle"
            :footer="false"
            :close-on-overlay-click="false"
            width="520px"
            class="wecom-bot-config-dialog"
            @close="handleClose"
        >
            <div class="wbc-body">
                <!-- 提示信息（对齐 webim step-tip） -->
                <div class="wbc-tip">
                    <span class="wbc-tip__dot" />
                    <div class="wbc-tip__text">
                        <span>{{ mergedI18n.wecomBotTipCredentialPrefix }}</span>
                        <a
                            class="wbc-tip__link"
                            :class="{ 'wbc-tip__link--loading': sdkLoading }"
                            href="javascript:void(0)"
                            @click="handleOpenWecomLink"
                        >{{ mergedI18n.wecomBotTipCredentialLink }}</a>
                        <span>{{ mergedI18n.wecomBotTipCredentialSuffix }}</span>
                        <br />
                        <span>{{ mergedI18n.wecomBotTipImportant }}</span>
                    </div>
                </div>

                <t-form
                    ref="formRef"
                    :data="formData"
                    :rules="rules"
                    label-align="left"
                    label-width="70px"
                    class="wbc-form"
                >
                    <t-form-item label="Bot ID" name="botId" :required-mark="true">
                        <t-input
                            v-model="formData.botId"
                            :placeholder="mergedI18n.wecomBotInputPlaceholder"
                            clearable
                        />
                    </t-form-item>
                    <t-form-item label="Secret" name="botSecret" :required-mark="true">
                        <t-input
                            v-model="formData.botSecret"
                            :placeholder="mergedI18n.wecomBotInputPlaceholder"
                            type="password"
                            clearable
                        />
                    </t-form-item>
                </t-form>

                <div class="wbc-footer">
                    <t-button theme="primary" size="large" :loading="submitting" @click="handleSubmit">
                        {{ mergedI18n.wecomBotConfirm }}
                    </t-button>
                    <t-button size="large" @click="visible = false">{{ mergedI18n.cancel }}</t-button>
                </div>
            </div>
        </t-dialog>
    </Teleport>
</template>

<style scoped>
/* ---- 弹窗主体对齐 webim ---- */
.wecom-bot-config-dialog :deep(.t-dialog__body) {
    padding: 0 var(--td-size-8) 0;
}

.wbc-body {
    width: 100%;
}

/* ---- 提示（对齐 webim step-tip） ---- */
.wbc-tip {
    display: flex;
    align-items: flex-start;
    gap: var(--td-size-3);
    padding: 10px 12px;
    margin-bottom: var(--td-size-7);
    background: #ECF9FF;
    border-radius: 3px;
}

.wbc-tip__dot {
    width: 14px;
    height: 14px;
    flex-shrink: 0;
    margin-top: var(--td-size-1);
    background: #1492FF;
    border-radius: var(--td-radius-circle);
}

.wbc-tip__text {
    font-size: var(--td-font-size-body-small);
    color: rgba(1, 11, 50, 0.61);
    line-height: var(--td-line-height-body-small);
}

.wbc-tip__link {
    color: #1492FF;
    text-decoration: none;
    cursor: pointer;
}

.wbc-tip__link:hover {
    text-decoration: underline;
}

.wbc-tip__link--loading {
    opacity: 0.6;
    cursor: wait;
    pointer-events: none;
}

/* ---- 表单（对齐 webim credential-form） ---- */
.wbc-form {
    margin-bottom: var(--td-size-4);
}

.wbc-form :deep(.t-form__item) {
    margin-bottom: var(--td-size-7);
}

.wbc-form :deep(.t-form__label) {
    font-size: 13px;
    color: rgba(0, 1, 10, 0.93);
}

/* ---- Footer（对齐 webim：居中、大按钮） ---- */
.wbc-footer {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: var(--td-size-5);
    padding: 16px 0 0;
}
</style>
