<script setup lang="ts">
import { ADPChat, type ApiConfig, type Application, type ChatConversation } from 'adp-chat-component';
import { onMounted, computed, ref, watch } from 'vue'
import { useUiStore } from '@/stores/ui'
import { logout } from '@/service/login';
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n';
import { languageMap } from '@/i18n';
import { getBaseURL } from '@/utils/url';
import Logo from '@/assets/img/favicon.png';

const router = useRouter()
const uiStore = useUiStore()
const route = useRoute()
const { t } = useI18n();

// 当前选中的应用和会话（用于 URL 同步）
const currentApplicationId = ref<string>('');
const currentConversationId = ref<string>('');
// 当前会话是否为渠道（访客）会话：由 URL 中是否包含 /channel/ 段判定。
// 渠道会话不落地本地 chat_conversation 表（权威源在 CAPI DescribeConversationList），
// 通过该 flag 传给 ADPChat，让其直接走「渠道恢复」流程，避免走普通 /chat/messages 导致 404。
const currentConversationChannel = ref<boolean>(false);
// 当前会话是否来自定时任务（AppTrigger 触发）：由 URL 中是否包含 /timertask/ 段判定。
// 定时任务会话与渠道会话同源（不在本地 chat_conversation 表，权威源在 CAPI），
// 通过该 flag + triggerId 传给 ADPChat，让其：
//   1) 走 DescribeConversationMessageList 拉首屏历史
//   2) 自动进入 sidebar 模式，右侧展开定时任务执行记录面板
//   3) 若携带 triggerId，定位到该触发器的详情视图
const currentConversationCronTask = ref<boolean>(false);
const currentConversationCronTaskTriggerId = ref<string>('');
// 当前定时任务会话对应的执行记录 InstanceId（URL 携带的 logId query）。
// 用于刷新后自动在右侧 sidebar 高亮当前那条运行记录，避免"没有选中当前项"。
const currentConversationCronTaskLogId = ref<string>('');

// API 配置 - 使用组件自动加载数据

const apiConfig: ApiConfig = {
    baseURL: getBaseURL(),
    timeout: 1000 * 60,
    apiDetailConfig: {
        applicationListApi: '/application/list',
        conversationListApi: '/chat/conversations',
        conversationDetailApi: '/chat/messages',
        sendMessageApi: '/chat/message',
        rateApi: '/feedback/rate',
        shareApi: '/share/create',
        userInfoApi: '/account/info',
        uploadApi: '/file/upload',
        asrUrlApi: '/helper/asr/url',
        systemConfigApi: '/system/config',
    }
};

// 语言选项
const languageOptions = computed(() => {
    return Object.entries(languageMap).map(([key, value]) => ({
        key,
        value
    }));
});

// 侧边栏国际化
const sideI18n = computed(() => ({
    more: t('common.more'),
    collapse: t('common.collapse'),
    today: t('common.today'),
    recent: t('common.recent'),
    switchTheme: t('sider.switchTheme'),
    selectLanguage: t('sider.selectLanguage'),
    logout: t('account.logout'),
}));

// 聊天国际化
const chatI18n = computed(() => ({
    uploading: t('common.uploading'),
    loading: t('common.loading'),
    thinking: t('common.thinking'),
    checkAll: t('operation.checkAll'),
    shareFor: t('operation.shareFor'),
    copyUrl: t('operation.copyUrl'),
    cancelShare: t('operation.cancelShare'),
    sendError: t('conversation.sendError'),
    networkError: t('conversation.networkError'),
    loginExpired: t('conversation.loginExpired'),
    createConversation: t('conversation.createConversation'),
    copySuccess: t('common.copySuccess'),
    copyFailed: t('common.copyFailed'),
    shareFailed: t('common.shareFailed'),
    rateFailed: t('common.rateFailed'),
    loadMoreFailed: t('common.loadMoreFailed'),
    getAppListFailed: t('common.getAppListFailed'),
    getConversationListFailed: t('common.getConversationListFailed'),
    getConversationDetailFailed: t('common.getConversationDetailFailed'),
}));

// ChatItem 国际化
const chatItemI18n = computed(() => ({
    thinking: t('conversation.thinking'),
    deepThinkingFinished: t('conversation.deepThinkingFinished'),
    deepThinkingExpand: t('conversation.deepThinkingExpand'),
    copy: t('operation.copy'),
    replay: t('operation.replay'),
    share: t('operation.share'),
    good: t('operation.good'),
    bad: t('operation.bad'),
    thxForGood: t('operation.thxForGood'),
    thxForBad: t('operation.thxForBad'),
    references: t('sender.references'),
}));

// Sender 国际化
const senderI18n = computed(() => ({
    placeholder: t('conversation.input.placeholder'),
    placeholderMobile: t('conversation.input.placeholderMobile'),
    uploadImg: t('sender.uploadImg'),
    startRecord: t('sender.startRecord'),
    stopRecord: t('sender.stopRecord'),
    answering: t('sender.answering'),
    notSupport: t('sender.notSupport'),
    uploadError: t('sender.uploadError'),
    recordTooLong: t('sender.recordTooLong'),
    asrServiceFailed: t('sender.asrServiceFailed'),
    recordFailed: t('sender.recordFailed'),
    chromeSecurityError: t('sender.chromeSecurityError'),
    browserNotSupport: t('sender.browserNotSupport'),
    audioContextNotSupport: t('sender.audioContextNotSupport'),
    webAudioApiNotSupport: t('sender.webAudioApiNotSupport'),
    mediaStreamSourceNotSupport: t('sender.mediaStreamSourceNotSupport'),
}));

/**
 * 页面挂载时执行的生命周期钩子
 * 1. 获取用户信息
 * 2. 初始化应用列表
 * 3. 更新聊天列表
 */
onMounted(async () => {
    console.log('[onMounted]');

    // url参数 -> store
    updateFromUrl();
});

/**
 * 页面url路径、参数处理
 * 1. url参数处理应该在pages层面，不能在组件里读写url参数（组件需要通过store，或者组件参数间接使用url参数）
 * 2. url参数和store应该保持一致，优先级：url参数 > store
 */

// URL 参数处理：
//   普通会话：/:applicationId?/:conversationId?
//   渠道会话：/:applicationId/channel/:conversationId  （route.name === 'home-channel'）
//   定时任务：/:applicationId/timertask/:conversationId?triggerId=xxx&logId=yyy （route.name === 'home-timertask'）
const updateFromUrl = () => {
    console.log('updateFromUrl', route.name, route.params, route.query);
    currentApplicationId.value = (route.params.applicationId as string) || '';
    currentConversationId.value = (route.params.conversationId as string) || '';
    currentConversationChannel.value = route.name === 'home-channel';
    currentConversationCronTask.value = route.name === 'home-timertask';
    currentConversationCronTaskTriggerId.value = currentConversationCronTask.value
        ? ((route.query.triggerId as string) || '')
        : '';
    currentConversationCronTaskLogId.value = currentConversationCronTask.value
        ? ((route.query.logId as string) || '')
        : '';
};

// 监听路由参数变化
watch(() => route.params.applicationId, () => updateFromUrl());
watch(() => route.params.conversationId, () => updateFromUrl());
// 路由名变化（普通 <-> 渠道 <-> 定时任务）也要重新同步 flag
watch(() => route.name, () => updateFromUrl());
watch(() => route.query.triggerId, () => updateFromUrl());
watch(() => route.query.logId, () => updateFromUrl());

/**
 * 更新 URL
 * - fromChannel=true：使用 home-channel 路由（/:appId/channel/:convId）
 * - fromCronTask=true：使用 home-timertask 路由（/:appId/timertask/:convId?triggerId=xxx&logId=yyy）
 * - 否则使用 home 路由
 */
const updateUrl = (fromChannel = false, fromCronTask = false, triggerId = '', logId = '') => {
    // 会话 id 必须依附在某个 applicationId 之下，避免出现无 app 的孤儿会话 URL
    const params: Record<string, string> = {};
    if (currentApplicationId.value) {
        params.applicationId = currentApplicationId.value;
        if (currentConversationId.value) {
            params.conversationId = currentConversationId.value;
        }
    }
    // 判定路由名（互斥；必须有 conversationId 才启用变体路由，否则回退到 home）
    let routeName: 'home' | 'home-channel' | 'home-timertask' = 'home';
    if (params.conversationId) {
        if (fromCronTask) routeName = 'home-timertask';
        else if (fromChannel) routeName = 'home-channel';
    }
    const query: Record<string, string> = {};
    if (routeName === 'home-timertask') {
        if (triggerId) query.triggerId = triggerId;
        // logId 单独判断：允许仅有 triggerId 而无 logId 的情况（sidebar 会拉列表，无高亮）；
        // 但当 logId 存在时必须写入，保证刷新后能高亮当前那条运行记录。
        if (logId) query.logId = logId;
    }
    router.push({ name: routeName, params, query });
};

// 事件处理函数
const handleSelectApplication = (app: Application) => {
    currentApplicationId.value = app.ApplicationId || '';
    currentConversationId.value = '';
    currentConversationChannel.value = false;
    currentConversationCronTask.value = false;
    currentConversationCronTaskTriggerId.value = '';
    currentConversationCronTaskLogId.value = '';
    updateUrl();
};

/**
 * 选中会话（普通 / 渠道）
 * Index.vue 内部 emit 时会带 fromChannel 标识：渠道会话使用 home-channel 路由，
 * 这样刷新后能通过 URL 直接判定为渠道会话，走渠道恢复流程。
 */
const handleSelectConversation = (conversation: ChatConversation, fromChannel = false) => {
    currentConversationId.value = conversation.Id;
    currentApplicationId.value = conversation.ApplicationId;
    currentConversationChannel.value = !!fromChannel;
    // 切换到普通/渠道会话时清空定时任务 flag，避免残留导致 URL 错乱
    currentConversationCronTask.value = false;
    currentConversationCronTaskTriggerId.value = '';
    currentConversationCronTaskLogId.value = '';
    updateUrl(fromChannel);
};

const handleCreateConversation = () => {
    currentConversationId.value = '';
    currentConversationChannel.value = false;
    currentConversationCronTask.value = false;
    currentConversationCronTaskTriggerId.value = '';
    currentConversationCronTaskLogId.value = '';
    updateUrl();
};

/**
 * 定时任务执行记录 → 切到对话窗口：
 * ADPChat 会 emit `cronTaskSwitchToChat`，携带 { task, triggerId, sessionId, logId, userId }。
 * 这里负责同步 URL 到 /:appId/timertask/:convId?triggerId=xxx&logId=yyy，保证刷新可恢复，
 * 并让右侧执行记录 sidebar 高亮当前项。
 */
const handleCronTaskSwitchToChat = (payload: {
    task: unknown;
    triggerId?: string;
    sessionId?: string;
    logId?: string;
    userId?: string;
}) => {
    if (!payload.sessionId) return;
    currentConversationId.value = payload.sessionId;
    currentConversationChannel.value = false;
    currentConversationCronTask.value = true;
    currentConversationCronTaskTriggerId.value = payload.triggerId || '';
    currentConversationCronTaskLogId.value = payload.logId || '';
    updateUrl(
        false,
        true,
        currentConversationCronTaskTriggerId.value,
        currentConversationCronTaskLogId.value,
    );
};

/**
 * 再次点击"定时任务"入口：Index.vue 已将面板重置为初始 list 视图，
 * 这里负责清空 URL 中的 timertask 变体（/timertask/xxx?triggerId=yyy&logId=zzz）,
 * 保留会话 id（若原本处于定时任务会话下，切回普通会话 URL；否则维持现状）。
 */
const handleCronTaskResetUrl = () => {
    if (
        !currentConversationCronTask.value
        && !currentConversationCronTaskTriggerId.value
        && !currentConversationCronTaskLogId.value
    ) {
        return;
    }
    currentConversationCronTask.value = false;
    currentConversationCronTaskTriggerId.value = '';
    currentConversationCronTaskLogId.value = '';
    // 同时清空 conversationId：定时任务会话不再属于当前上下文，回到"选中应用"的初始状态
    currentConversationId.value = '';
    currentConversationChannel.value = false;
    updateUrl();
};

const handleToggleTheme = () => {
    const newTheme = uiStore.theme === 'light' ? 'dark' : 'light';
    uiStore.setTheme(newTheme);
};

const handleChangeLanguage = (key: string) => {
    uiStore.setLanguage(key as 'en' | 'zh');
};

const handleLogout = () => {
    logout(() => router.replace({ name: 'login' }));
};

// 数据加载完成回调
const handleDataLoaded = (type: 'applications' | 'conversations' | 'chatList' | 'user', data: any) => {
    // 初始化时从 URL 同步状态
    if (type === 'applications' && data.length > 0) {
        // 如果 URL 没有指定应用，默认选中第一个
        if (!currentApplicationId.value && !currentConversationId.value) {
            currentApplicationId.value = data[0].ApplicationId;
        }
        // 关键：这里的 updateUrl 必须带上当前的 channel / cronTask flag + triggerId + logId，
        // 否则 URL 会被回退成通用 home 路由（/appId/convId），刷新 timertask/channel 页面时
        // /timertask/ 或 /channel/ 段以及 ?triggerId=xxx&logId=yyy query 会被丢掉，
        // 进而使 Index.vue 里"定时任务会话恢复"watch 判定 flag=false 而不拉执行记录，
        // 或者 sidebar 因缺 logId 而无法高亮"当前项"。
        updateUrl(
            currentConversationChannel.value,
            currentConversationCronTask.value,
            currentConversationCronTaskTriggerId.value,
            currentConversationCronTaskLogId.value,
        );
    }
};

// 会话变化回调（由 Chat 组件内部 watch(chatId) 触发，用于新建会话后同步 URL）
// 注意：不要重置 currentConversationChannel / currentConversationCronTask —— 
// 点击渠道 / 定时任务会话时对应 handler 已经把 flag 设为 true 并 push 到对应变体路由；
// 随后 Chat 组件 chatId prop 变化会再次触发本回调，若这里不带对应 flag 调用 updateUrl，
// 会立刻把 URL 覆盖回普通路径，导致刷新掉会话 404。
const handleConversationChange = (conversationId: string) => {
    // 相同 id 无需重复 push（大部分场景就是同一次点击带来的回声，跳过避免覆盖）
    if (conversationId === currentConversationId.value) return;
    currentConversationId.value = conversationId;
    // 由外部（selectConversation / createConversation / cronTaskSwitchToChat）的显式回调负责调整 flag，
    // 这里保持现状，用当前 flag 更新 URL。
    updateUrl(
        currentConversationChannel.value,
        currentConversationCronTask.value,
        currentConversationCronTaskTriggerId.value,
        currentConversationCronTaskLogId.value,
    );
};
</script>

<template>
    <ADPChat
        :apiConfig="apiConfig"
        :autoLoad="true"
        :theme="uiStore.theme || 'light'"
        :language="uiStore.language || 'zh'"
        :languageOptions="languageOptions"
        :isSidePanelOverlay="uiStore.isMobile"
        :showCloseButton="false"
        :showOverlayButton="false"
        :logoUrl="Logo"
        :currentApplicationId="currentApplicationId"
        :currentConversationId="currentConversationId"
        :currentConversationChannel="currentConversationChannel"
        :currentConversationCronTask="currentConversationCronTask"
        :currentConversationCronTaskTriggerId="currentConversationCronTaskTriggerId"
        :currentConversationCronTaskLogId="currentConversationCronTaskLogId"
        :aiWarningText="t('common.aiWarning')"
        :createConversationText="t('conversation.createConversation')"
        :sideI18n="sideI18n"
        :chatI18n="chatI18n"
        :chatItemI18n="chatItemI18n"
        :senderI18n="senderI18n"
        @selectApplication="handleSelectApplication"
        @selectConversation="handleSelectConversation"
        @createConversation="handleCreateConversation"
        @cronTaskSwitchToChat="handleCronTaskSwitchToChat"
        @cronTaskResetUrl="handleCronTaskResetUrl"
        @toggleTheme="handleToggleTheme"
        @changeLanguage="handleChangeLanguage"
        @logout="handleLogout"
        @dataLoaded="handleDataLoaded"
        @conversationChange="handleConversationChange"
    />
</template>

<style scoped>
</style>
