<!-- ADP 聊天布局主组件，支持 API 模式和 Props 模式 -->
<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch, nextTick, toRefs, provide } from 'vue';
import { MessagePlugin } from 'tdesign-vue-next';

import MainLayout from './MainLayout.vue';
import type { Application, AppPattern } from '../../model/application';
import type { ChatConversation, Record, Reference, SseEvent, Content, ErrorEvent, Questionnaire } from '../../model/chat-v2';
import { ScoreValue } from '../../model/chat-v2';
import type { ApiConfig } from '../../service/api';
import {
    fetchApplicationList,
    fetchConversationList,
    deleteConversation,
    fetchConversationDetail,
    fetchReferenceDetails,
    createConversation,
    ConversationType,
    sendMessage,
    rateMessage,
    createShare,
    fetchUserInfo,
    fetchSystemConfig,
} from '../../service/api';
import type { SystemConfig } from '../../service/api';
import { MessageCode } from '../../model/messages';
import { fetchSSE } from '../../model/sseRequest-reasoning';
import { applySseEventToRecord } from '../../utils/mergeRecord-v2';
import { hydrateType2References } from '../../utils/reference';
import { copyToClipboard } from '../../utils/clipboard';
import { useApiConfig } from '../../composables';
import { computeIsMobile } from '../../utils/device';
import {
    handleWidgetEvent as routeWidgetEvent,
    disableWidgetsByRecordId,
} from '../../widget';
import type { WidgetActionRequest } from '../../widget';
import type {
    LanguageOption,
    UserInfo,
    ChatI18n,
    ChatItemI18n,
    SenderI18n,
    ThemeProps,
    OverlayProps,
    ChatMode
} from '../../model/type';
import {
    defaultLanguageOptions,
    themePropsDefaults,
    overlayPropsDefaults,
    defaultChatI18n,
    defaultChatI18nEn,
    defaultChatItemI18n,
    defaultChatItemI18nEn,
    defaultSenderI18n,
    defaultSenderI18nEn
} from '../../model/type';
import { useAgentStore } from '../../composables/useAgentStore';


export interface Props extends ThemeProps, OverlayProps {
    /** 当前语言标识，用于自动选择内部默认 i18n（如 'zh-CN'、'en-US'） */
    language?: string;
    /** 聊天模式：claw-简化模式（无文件预览/无解析进度），standard-标准模式 */
    mode?: ChatMode;
    /** 是否为浮层模式 */
    isOverlay?: boolean;
    /** 宽度（仅在 isOverlay 为 true 时用于计算 isMobile） */
    width?: string | number;
    /** 高度（仅在 isOverlay 为 true 时用于计算 isMobile） */
    height?: string | number;
    /** 容器选择器（仅在非 isOverlay 模式用于计算 isMobile） */
    container?: string;
    /** 侧边栏是否使用overlay模式 */
    isSidePanelOverlay?: boolean;
    /** 应用列表 */
    applications?: Application[];
    /** 当前选中的应用 */
    currentApplication?: Application;
    /** 当前选中的应用 ID（优先级高于 currentApplication） */
    currentApplicationId?: string;
    /** 会话列表 */
    conversations?: ChatConversation[];
    /** 当前选中的会话 */
    currentConversation?: ChatConversation;
    /** 当前选中的会话 ID（优先级高于 currentConversation） */
    currentConversationId?: string;
    /** 聊天消息列表 */
    chatList?: Record[];
    /** 是否正在聊天中 */
    isChatting?: boolean;
    /** 用户信息 */
    user?: UserInfo;
    /** 语言选项列表 */
    languageOptions?: LanguageOption[];
    /** Logo URL */
    logoUrl?: string;
    /** Logo 标题 */
    logoTitle?: string;
    /** 最大应用显示数量 */
    maxAppLen?: number;
    /** 是否显示关闭按钮 */
    showCloseButton?: boolean;
    /** AI警告文本 */
    aiWarningText?: string;
    /** 聊天国际化文本 */
    chatI18n?: ChatI18n;
    /** ChatItem 国际化文本 */
    chatItemI18n?: ChatItemI18n;
    /** Sender 国际化文本 */
    senderI18n?: SenderI18n;
    /** API 配置 - 如果传入则使用 HTTP 请求获取数据 */
    apiConfig?: ApiConfig;
    /** 是否自动加载数据（仅在使用 apiConfig 时生效） */
    autoLoad?: boolean;
}

const props = withDefaults(defineProps<Props>(), {
    ...themePropsDefaults,
    ...overlayPropsDefaults,
    language: 'zh-CN',
    mode: 'standard',
    isOverlay: false,
    width: 0,
    height: 0,
    container: 'body',
    isSidePanelOverlay: true,
    applications: () => [],
    currentApplicationId: '',
    conversations: () => [],
    currentConversationId: '',
    chatList: () => [],
    isChatting: false,
    user: () => ({}),
    languageOptions: () => defaultLanguageOptions,
    logoUrl: '',
    logoTitle: '',
    maxAppLen: 4,
    showCloseButton: true,
    aiWarningText: '内容由AI生成，仅供参考',
    apiConfig: () => ({}),
    autoLoad: true,
});

const {
    getAgentIdByAppId,
    fetchAndSetAgentId,
    watchApplicationId,
    setApplicationModes,
} = useAgentStore();

const emit = defineEmits<{
    (e: 'selectApplication', app: Application): void;
    /** 选中会话 */
    (e: 'selectConversation', conversation: ChatConversation): void;
    /** 删除会话（用户在侧栏确认删除后触发；API 模式下删除已完成再 emit，非 API 模式仅透传） */
    (e: 'deleteConversation', conversation: ChatConversation): void;
    (e: 'createConversation'): void;
    (e: 'toggleTheme'): void;
    (e: 'changeLanguage', key: string): void;
    (e: 'logout'): void;
    (e: 'userClick'): void;
    (e: 'close'): void;
    (e: 'overlay', isOverlay: boolean): void;
    (e: 'send', query: string, conversationId: string, applicationId: string): void;
    (e: 'stop'): void;
    (e: 'loadMore', conversationId: string, lastRecordId: string): void;
    (e: 'rate', conversationId: string, recordId: string, score: typeof ScoreValue[keyof typeof ScoreValue]): void;
    (e: 'share', conversationId: string, applicationId: string, recordIds: string[]): void;
    (e: 'copy', rowtext: string | undefined, content: string | undefined, type: string): void;
    (e: 'message', code: MessageCode, message: string): void;
    (e: 'conversationChange', conversationId: string): void;
    /** 会话列表状态变化（列表本身 / 进行中集合 / 加载中 / 失败） */
    (e: 'conversationsChange', payload: {
        list: ChatConversation[];
        chattingIds: string[];
        loading: boolean;
        error: unknown;
    }): void;
    (e: 'dataLoaded', type: 'applications' | 'conversations' | 'chatList' | 'user' | 'systemConfig', data: any): void;
    /** Widget 事件（用于与 SSE/对话流交互） */
    (e: 'widgetEvent', event: CustomEvent, widgetRunId: string, widgetId: string, recordId: string): void;
    /** 反问澄清提交：questionnaire 为可直接上行的内容体（API 模式内部消化后再对外通知） */
    (e: 'questionnaireSubmit', questionnaire: Questionnaire, recordId: string): void;
    /** 反问澄清跳过：questionnaire 为原始内容体 */
    (e: 'questionnaireSkip', questionnaire: Questionnaire, recordId: string): void;
}>();

// 解构 props 保持响应式
const { theme } = toRefs(props);

const mainLayoutRef = ref<InstanceType<typeof MainLayout> | null>(null);

// 合并 i18n 配置（根据 language 选择对应语言的默认值）
const mergedChatItemI18n = computed(() => {
    const defaults = props.language?.startsWith('en') ? defaultChatItemI18nEn : defaultChatItemI18n;
    return { ...defaults, ...props.chatItemI18n };
});

// 计算是否为移动端模式（内部计算，不再依赖外部传入）
const isMobile = computed(() => {
    return computeIsMobile({
        isOverlay: props.isOverlay,
        width: props.width,
        height: props.height,
        container: props.container,
    });
});

provide('isMobile', isMobile);

// 内部数据状态（当使用 API 时）
const internalApplications = ref<Application[]>([]);
const internalConversations = ref<ChatConversation[]>([]);
const internalUser = ref<{ id?: string; avatarUrl?: string; avatarName?: string; name?: string }>({});
const internalCurrentApplication = ref<Application | undefined>(undefined);
const internalCurrentConversation = ref<ChatConversation | undefined>(undefined);

// 用于确保 applications 列表加载完成后再判断模式
let resolveApplicationsReady: () => void;
const applicationsReadyPromise = new Promise<void>((resolve) => {
    resolveApplicationsReady = resolve;
});


const internalSystemConfig = ref<SystemConfig>({ EnableVoiceInput: true });
const referenceDetailCache = new Map<string, Reference>();
const referenceDetailPendingKeys = new Set<string>();

interface ConversationRuntimeState {
    records: Record[];
    isChatting: boolean;
    abortController: AbortController | null;
    applicationId?: string;
}

type ConversationRuntimeStateMap = {
    [key: string]: ConversationRuntimeState;
};

const conversationRuntimeStates = ref<ConversationRuntimeStateMap>({});
const currentConversationStateKey = ref('');
/**
 * 渠道会话 → 渠道 UserId 映射
 * 渠道会话的历史消息必须走 CAPI DescribeConversationMessageList 且携带该渠道的 UserId + Type=5
 * （与 DescribeConversationList 保持一致，Type=5 = CONVERSATION_TYPE_CHANNEL）。
 * 普通会话不在此表中，仍走标准 /chat/messages。
 * key = ConversationId，value = 该渠道绑定的 UserAgent.UserId
 */
const channelConversationUserId = ref<{ [conversationId: string]: string }>({});

/**
 * 【URL 刷新恢复】当前正在进行中的渠道会话恢复 Promise 缓存。
 * key = conversationId，value = restoreChannelConversationById 的 Promise（resolve 为 true 表示命中并已建立映射）。
 *
 * 用途：Chat 组件的 InfiniteLoading 在挂载时会 emit('loadMore')，此时 URL 触发的 restore 可能尚未完成，
 * `channelConversationUserId` 里还没有 convId → handleInternalLoadMore 会错误地走 `/chat/messages`（404）。
 * 通过此 Map，handleInternalLoadMore 可以先 await 正在进行的 restore，命中即跳过 /chat/messages。
 */
const channelRestorePending = new Map<string, Promise<boolean>>();

let pendingConversationSeq = 0;

const createPendingConversationKey = () => `pending-conversation:${Date.now()}:${pendingConversationSeq++}`;

const getConversationRuntimeState = (key: string) => {
    if (!key) {
        return undefined;
    }
    return conversationRuntimeStates.value[key];
};

const ensureConversationRuntimeState = (key: string) => {
    if (!key) {
        return undefined;
    }
    let state = conversationRuntimeStates.value[key];
    if (!state) {
        state = {
            records: [],
            isChatting: false,
            abortController: null,
        };
        conversationRuntimeStates.value[key] = state;
    }
    return state;
};

const getConversationRecords = (key: string) => {
    return getConversationRuntimeState(key)?.records ?? [];
};

const isConversationChatting = (key: string) => {
    return getConversationRuntimeState(key)?.isChatting ?? false;
};

const setConversationRecords = (key: string, records: Record[], applicationId?: string) => {
    const state = ensureConversationRuntimeState(key);
    if (!state) {
        return [];
    }
    state.records = records;
    if (applicationId) {
        state.applicationId = applicationId;
    }
    return state.records;
};

const setConversationApplicationId = (key: string, applicationId?: string) => {
    if (!key || !applicationId) {
        return;
    }
    const state = ensureConversationRuntimeState(key);
    if (!state) {
        return;
    }
    state.applicationId = applicationId;
};

const moveConversationRuntimeState = (fromKey: string, toKey: string, applicationId?: string) => {
    if (!fromKey) {
        setConversationApplicationId(toKey, applicationId);
        return toKey;
    }
    if (!toKey || fromKey === toKey) {
        setConversationApplicationId(fromKey, applicationId);
        return fromKey;
    }

    const fromState = getConversationRuntimeState(fromKey);
    if (!fromState) {
        setConversationApplicationId(toKey, applicationId);
        return toKey;
    }

    conversationRuntimeStates.value[toKey] = fromState;
    if (applicationId) {
        fromState.applicationId = applicationId;
    }
    delete conversationRuntimeStates.value[fromKey];
    return toKey;
};

const stopConversationStream = (key: string) => {
    const state = getConversationRuntimeState(key);
    if (!state) {
        return;
    }
    if (state.abortController) {
        state.abortController.abort();
        state.abortController = null;
    }
    state.isChatting = false;
};

// 判断是否使用 API 模式（始终启用）
const useApiMode = computed(() => true);

// 是否启用语音输入
const enableVoiceInput = computed(() => internalSystemConfig.value.EnableVoiceInput);

// 合并默认值和传入值的 chatI18n（根据 language 选择对应语言的默认值）
const mergedChatI18n = computed(() => {
    const defaults = props.language?.startsWith('en') ? defaultChatI18nEn : defaultChatI18n;
    return { ...defaults, ...props.chatI18n };
});

// 合并默认值和传入值的 senderI18n（根据 language 选择对应语言的默认值）
const mergedSenderI18n = computed(() => {
    const defaults = props.language?.startsWith('en') ? defaultSenderI18nEn : defaultSenderI18n;
    return { ...defaults, ...props.senderI18n };
});

// 使用 composable 统一管理 API 配置
const { mergedApiDetailConfig } = useApiConfig({
    apiConfig: computed((): ApiConfig | undefined => props.apiConfig),
});

const isStreamAbortError = (msg: unknown) => {
    return !!(
        msg &&
        typeof msg === 'object' &&
        (
            ('name' in msg && msg.name === 'AbortError') ||
            ('code' in msg && msg.code === 'ERR_CANCELED')
        )
    );
};

/**
 * 将错误信息写入指定会话的 placeholder-agent Record，使其在消息列表中以气泡形式展示。
 * 如果写入成功返回 true，否则返回 false（外层可兜底 toast）。
 */
const writeErrorToRecords = (conversationKey: string, errorMessage: string, errorEvent?: ErrorEvent): boolean => {
    const targetState = getConversationRuntimeState(conversationKey);
    if (!targetState) return false;

    const placeholderIdx = targetState.records.findIndex(
        (r) => r.RecordId === 'placeholder-agent' || (r.Role === 'assistant' && r.Status === 'processing')
    );
    if (placeholderIdx === -1) return false;

    const record = targetState.records[placeholderIdx]!;
    record.Status = 'error';
    record.StatusDesc = errorMessage;
    record.RecordId = errorEvent?.RecordId || record.RecordId;
    record.Messages = [
        {
            Type: 'reply',
            MessageId: `error-${Date.now()}`,
            Name: 'error',
            Title: '',
            Status: 'error',
            StatusDesc: '',
            Contents: [{ Type: 'text', Text: errorMessage }],
        },
    ];

    // 滚动到底部以展示错误消息
    if (currentConversationStateKey.value === conversationKey) {
        nextTick(() => {
            mainLayoutRef.value?.getChatRef()?.backToBottom();
        });
    }
    return true;
};

const handleStreamFailure = (msg: unknown, errorEvent?: ErrorEvent, conversationKey?: string) => {
    if (isStreamAbortError(msg)) {
        return;
    }
    if (msg && typeof msg === 'object' && 'response' in msg && msg.response && typeof msg.response === 'object') {
        const response = msg.response as { status?: number };
        if (response.status === 401) {
            const loginExpiredText = mergedChatI18n.value.loginExpired;
            MessagePlugin.error(loginExpiredText);
            emit('message', MessageCode.SEND_MESSAGE_FAILED, loginExpiredText);
            return;
        }
    }
    if (msg && typeof msg === 'object' && 'code' in msg && msg.code === 'ERR_NETWORK') {
        const networkErrorText = mergedChatI18n.value.networkError;
        MessagePlugin.error(networkErrorText);
        emit('message', MessageCode.NETWORK_ERROR, networkErrorText);
        return;
    }
    if (typeof msg === 'string' && conversationKey) {
        // SSE error 事件：将错误渲染到消息气泡中（支持 Markdown 链接）
        if (writeErrorToRecords(conversationKey, msg, errorEvent)) {
            emit('message', MessageCode.SEND_MESSAGE_FAILED, msg);
            return;
        }
    }
    if (typeof msg === 'string') {
        // 兜底：写入失败则 toast
        MessagePlugin.error(msg);
        emit('message', MessageCode.SEND_MESSAGE_FAILED, msg);
        return;
    }
    const sendErrorText = mergedChatI18n.value.sendError;
    MessagePlugin.error(sendErrorText);
    emit('message', MessageCode.SEND_MESSAGE_FAILED, sendErrorText);
};

const hydrateReferences = async (
    records: Record[],
    options: { applicationId?: string; shareId?: string } = {}
) => {
    if (records.length === 0) {
        return;
    }

    try {
        await hydrateType2References(records, {
            ...options,
            cache: referenceDetailCache,
            pending: referenceDetailPendingKeys,
            fetcher: (params) => fetchReferenceDetails(params, mergedApiDetailConfig.value.referenceDetailApi),
        });
    } catch (error) {
        console.error('补充引用切片失败:', error);
    }
};

// 实际使用的数据（优先使用 props，否则使用内部数据）
const actualApplications = computed(() => 
    props.applications.length > 0 ? props.applications : internalApplications.value
);
const actualConversations = computed(() => 
    props.conversations.length > 0 ? props.conversations : internalConversations.value
);
const actualChatList = computed(() => {
    // 渠道 / 定时任务会话：消息来源是内部 DescribeConversationMessageList 拉取，
    // 不在本地库也不通过 /chat/messages，必须用内部 records，不能回退到 props.chatList
    if (currentConversationStateKey.value && channelConversationUserId.value[currentConversationStateKey.value]) {
        return getConversationRecords(currentConversationStateKey.value);
    }
    return props.chatList.length > 0 ? props.chatList : getConversationRecords(currentConversationStateKey.value);
});
const actualUser = computed(() => 
    (props.user && Object.keys(props.user).length > 0) ? props.user : internalUser.value
);
const actualCurrentApplication = computed(() => 
    props.currentApplication || internalCurrentApplication.value
);
const actualCurrentConversation = computed(() => 
    props.currentConversation || internalCurrentConversation.value
);
const actualIsChatting = computed(() => 
    useApiMode.value ? isConversationChatting(currentConversationStateKey.value) : props.isChatting
);

/**
 * 所有正在进行中的会话 Id 集合
 * 用途：透传给 HistoryList 让侧栏对应项显示转圈
 * 数据源：conversationRuntimeStates 中 isChatting=true 的 key
 * 注意：key 既包含真实 conversationId，也包含 pending-conversation:* 占位 key（乐观 UI 场景），
 *      两种 key 都会出现在 internalConversations 里，所以直接命中即可
 */
const chattingConversationIds = computed(() =>
    Object.entries(conversationRuntimeStates.value)
        .filter(([, state]) => state?.isChatting)
        .map(([key]) => key)
);

// 计算属性
const currentApplicationId = computed(() => actualCurrentApplication.value?.ApplicationId || '');

/**
 * 应用列表变化时把每个应用的 Pattern 登记到 useAgentStore，
 * 让 store 内的 fetchAndSetAgentId / fetchAgentDetail / getAgentIdByAppId 等
 * 能够按 applicationId 精确判定：仅 mode === 'claw'（即 Pattern === 'ClawAgent'）的应用才走 Agent 扩展流程。
 * 入参保留 { ApplicationId, Pattern } 原字段，store 内部会通过 patternToMode() 归一化为 ChatMode 存储。
 */
watch(
    actualApplications,
    (list) => {
        if (Array.isArray(list) && list.length > 0) {
            setApplicationModes(list);
        }
    },
    { immediate: true, deep: false },
);

/**
 * 在最外层监听 currentApplicationId 变化，仅在 claw 模式（Pattern='ClawAgent' 或 props.mode='claw'）时触发 Agent 拉取。
 * 非 claw（standard 模式）以及 pattern 尚未就绪的场景一律跳过。
 * 使用 chatMode 而非直接判断 Pattern，可同时兼容"外部强制 claw 模式"与"按 Pattern 自动推导"两种场景。
 */
watchApplicationId(() => {
    const app = actualCurrentApplication.value;
    if (!app?.ApplicationId) return '';
    return chatMode.value === 'claw' ? app.ApplicationId : '';
});
const currentApplicationAvatar = computed(() => actualCurrentApplication.value?.Avatar || '');

const currentApplicationName = computed(() => actualCurrentApplication.value?.Name || '');
const currentApplicationGreeting = computed(() => actualCurrentApplication.value?.Greeting || '');
const currentApplicationOpeningQuestions = computed(() => actualCurrentApplication.value?.OpeningQuestions || []);
const currentConversationId = computed(() => props.currentConversationId || actualCurrentConversation.value?.Id || '');

/**
 * 聊天模式：优先使用 props.mode 手动配置，否则从当前应用的 Pattern 自动推导
 * Pattern='ClawAgent' → mode='claw'，其他值或 null → mode='standard'
 */
const chatMode = computed<ChatMode>(() => {
    if (props.mode !== 'standard') {
        return props.mode;
    }
    const pattern = actualCurrentApplication.value?.Pattern as AppPattern | null | undefined;
    if (pattern === 'ClawAgent') {
        return 'claw';
    }
    return 'standard';
});

// API 数据加载方法
const loadApplications = async () => {
    if (!useApiMode.value) {
        resolveApplicationsReady();
        return;
    }
    try {
        const data = await fetchApplicationList(mergedApiDetailConfig.value.applicationListApi);
        internalApplications.value = data;
        // 默认选中第一个应用
        if (data.length > 0 && !internalCurrentApplication.value) {
            internalCurrentApplication.value = data[0];
        }
        emit('dataLoaded', 'applications', data);
    } catch (error) {
        const text = mergedChatI18n.value.getAppListFailed;
        MessagePlugin.error(text);
        emit('message', MessageCode.GET_APP_LIST_FAILED, text);
    } finally {
        resolveApplicationsReady();
    }
};

/**
 * 会话列表加载入口。
 *
 * 列表的权威源就是本组件的 `internalConversations`，不再经由 SideLayout 中转。
 * 这一点是硬约束而非风格选择：SSE `success` 事件里要靠「当前列表中是否存在占位项」
 * 决定是否把 `pending-conversation:*` 替换成真实会话（见下方 handleInternalSend），
 * 那个判断必须与写入发生在同一个同步 tick。若把数组挪到父组件、再靠 prop 回传，
 * 判断读到的是上一拍的旧值 → 替换被跳过 → 列表里永久留下一条 pending 幽灵行。
 */
const isFetchingConversations = ref(false);
const conversationsError = ref<unknown>(null);
/** 并发保护：每发起一次请求 +1，返回时 token 不匹配即丢弃，避免旧响应覆盖新列表 */
let conversationFetchToken = 0;

const loadConversations = async () => {
    const applicationId = currentApplicationId.value;
    if (!applicationId) {
        internalConversations.value = [];
        return;
    }
    const currentToken = ++conversationFetchToken;
    isFetchingConversations.value = true;
    try {
        const data = await fetchConversationList(
            mergedApiDetailConfig.value.conversationListApi,
            { ApplicationId: applicationId },
        );
        if (currentToken !== conversationFetchToken) return;
        const list = Array.isArray(data) ? data : [];
        // 拉取结果不能覆盖仍在流式中的会话行。判据用 isConversationChatting 而不是
        // `pending-conversation:` 前缀：占位被替换成真实 Id 之后前缀判据就失效了，
        // 此时若后端尚未落库该会话，这一行会在流式过程中从列表里消失。
        const backendIds = new Set(list.map(item => item.Id));
        const streaming = internalConversations.value.filter(
            item => !backendIds.has(item.Id) && isConversationChatting(item.Id),
        );
        internalConversations.value = streaming.length > 0 ? [...streaming, ...list] : list;
        conversationsError.value = null;
        emit('dataLoaded', 'conversations', list);
    } catch (error) {
        if (currentToken !== conversationFetchToken) return;
        conversationsError.value = error;
        const text = mergedChatI18n.value.getConversationListFailed;
        MessagePlugin.error(text);
        emit('message', MessageCode.GET_CONVERSATION_LIST_FAILED, text);
    } finally {
        if (currentToken === conversationFetchToken) {
            isFetchingConversations.value = false;
        }
    }
};

/** 乐观插入一条占位会话；Id 已存在时是 no-op（保持调用点的幂等语义） */
const addOptimisticConversation = (conversation: ChatConversation) => {
    if (internalConversations.value.some(item => item.Id === conversation.Id)) return;
    internalConversations.value = [conversation, ...internalConversations.value];
};

/** 用真实会话替换占位项；未命中时是 no-op */
const replaceConversationInList = (targetId: string, conversation: ChatConversation) => {
    const index = internalConversations.value.findIndex(item => item.Id === targetId);
    if (index < 0) return;
    const next = internalConversations.value.slice();
    next.splice(index, 1, conversation);
    internalConversations.value = next;
};

const removeConversationFromList = (targetId: string) => {
    internalConversations.value = internalConversations.value.filter(item => item.Id !== targetId);
};

/** 删除失败时按快照整体回滚（保留原顺序） */
const rollbackConversations = (snapshot: ChatConversation[]) => {
    internalConversations.value = snapshot.slice();
};

const loadConversationDetail = async (conversationId: string) => {
    if (!useApiMode.value || !conversationId) return;
    // 确保 applications 列表已加载完成
    await applicationsReadyPromise;
    try {
        const response = await fetchConversationDetail(
            { ConversationId: conversationId },
            mergedApiDetailConfig.value.conversationDetailApi
        );
        const records: Record[] = response?.Response?.Records || [];
        const applicationId = response?.Response?.ApplicationId || '';

        setConversationRecords(conversationId, records, applicationId);
        await hydrateReferences(records, { applicationId });
        emit('dataLoaded', 'chatList', records);
    } catch (error) {
        const text = mergedChatI18n.value.getConversationDetailFailed;
        MessagePlugin.error(text);
        emit('message', MessageCode.GET_CONVERSATION_DETAIL_FAILED, text);
    }
};

const loadUserInfo = async () => {
    if (!useApiMode.value) return;
    try {
        const data = await fetchUserInfo(mergedApiDetailConfig.value.userInfoApi);
        internalUser.value = {
            id: data.Id || '',
            avatarUrl: data.Avatar,
            avatarName: data.Name?.charAt(0) || '',
            name: data.Name,
        };
        emit('dataLoaded', 'user', internalUser.value);
    } catch (error) {
        // 用户信息获取失败不影响主流程
        console.error('获取用户信息失败:', error);
    }
};

const loadSystemConfig = async () => {
    if (!useApiMode.value) return;
    try {
        const data = await fetchSystemConfig(mergedApiDetailConfig.value.systemConfigApi);
        internalSystemConfig.value = data;
        emit('dataLoaded', 'systemConfig', internalSystemConfig.value);
    } catch (error) {
        // 系统配置获取失败不影响主流程，默认不启用语音输入
        console.error('获取系统配置失败:', error);
    }
};

// 内部发送消息处理（API 模式）
const handleInternalSend = async (query: string, conversationId: string, applicationId: string) => {
    if (!useApiMode.value) {
        emit('send', query, conversationId, applicationId);
        return;
    }

    // 乐观 UI 需要在函数最开始就记录"进入时是不是新会话"
    // 因为后面走 agentId 分支会同步调 createConversation，把 conversationId 从空变成真实 Id，
    // 那样后续判断就分不清了。
    const isNewConversationSend = !conversationId;

    const agentId = await getAgentIdByAppId(applicationId);

    // 如果存在 agentId 且没有 conversationId，则先调用 CreateConversation 获取
    if (agentId && !conversationId) {
        try {
            conversationId = await createConversation(
                {
                    Type: ConversationType.CONVERSATION_TYPE_VISITOR,
                    AppId: applicationId,
                    AgentId: agentId,
                },
                applicationId
            );
        } catch (error) {
            console.error('CreateConversation 失败:', error);
            return;
        }

        // 成功创建后立即同步内部状态 + 通知外部，确保：
        // 1) currentConversationStateKey 绑定到新 conversationId（与点击侧栏会话的行为一致）
        // 2) ApplicationId 关联到该 conversation
        // 3) 向外 emit('conversationChange')，让父组件同步 currentConversationId（更新 URL / 路由等）
        if (conversationId) {
            currentConversationStateKey.value = conversationId;
            setConversationApplicationId(conversationId, applicationId);
            emit('conversationChange', conversationId);
        }
    }

    let streamConversationKey = conversationId || currentConversationStateKey.value || createPendingConversationKey();
    currentConversationStateKey.value = streamConversationKey;
    const streamState = ensureConversationRuntimeState(streamConversationKey);
    if (!streamState) {
        return;
    }
    streamState.isChatting = true;
    streamState.applicationId =
        applicationId ||
        streamState.applicationId ||
        internalCurrentConversation.value?.ApplicationId ||
        internalCurrentApplication.value?.ApplicationId;
    // 重置用户滚动状态
    mainLayoutRef.value?.getChatRef()?.setHasUserScrolled(false);

    // 乐观 UI：新会话首条消息发送时，先在侧栏插入占位会话
    // 覆盖两种"新会话"路径：
    //   1) 走 CreateConversation 提前拿到真实 Id（agentId 分支）：streamConversationKey 是真实 Id
    //   2) 未走 CreateConversation，靠 SSE 首事件回吐 Id：streamConversationKey 是 pending-conversation:*
    // 两者都需要占位，因为无论哪种，此刻侧栏都还没这条会话（loadConversations 尚未刷新）
    // - Id 用 streamConversationKey，保证 HistoryList 的 active 高亮命中
    // - Title 用用户首条消息前 40 字符（后端也会基于首条 query 生成摘要）
    // - LastActiveAt 用当前时间，保证在 sortedConversations 中排最上
    // - 路径 1：SSE 结束后无 IsNewConversation 事件，占位靠 loadConversations 时把 pending 过滤后由真实项覆盖
    //          → 因此路径 1 的占位替换依赖 SSE finish/success 中的 loadConversations 调用（见后端事件处理）
    // - 路径 2：SSE 首事件（IsNewConversation=true）就地替换 pending 项
    if (isNewConversationSend) {
        const optimisticTitle = (query || '').replace(/\s+/g, ' ').trim().slice(0, 40) || 'New chat';
        const nowSec = Math.floor(Date.now() / 1000);
        const optimisticConversation: ChatConversation = {
            Id: streamConversationKey,
            AccountId: '',
            Title: optimisticTitle,
            LastActiveAt: nowSec,
            CreatedAt: nowSec,
            ApplicationId: applicationId || internalCurrentApplication.value?.ApplicationId || '',
        };
        // 幂等：避免同一 key 被重复插入
        if (!internalConversations.value.some(c => c.Id === streamConversationKey)) {
            // internalConversations 是权威源，插入后同一 tick 即可被后续判断读到，
            // 无需再手动写 internalConversations（写了也会被 change 事件覆盖，语义不冲突，但避免出现"镜像先于源"的窗口）
            addOptimisticConversation(optimisticConversation);
        }
    }

    const timestamp = Date.now();
    const baseExtraInfo = (isFromSelf: boolean) => ({
        RequestId: '',
        TraceId: '',
        Elapsed: 0,
        StartTime: timestamp,
        IsFromSelf: isFromSelf,
    });

    // 构建用户消息展示内容
    const userContents: Content[] = [{ Type: 'text', Text: query }];

    // 创建用户消息占位
    const userRecord: Record = {
        Role: 'user',
        RecordId: 'placeholder-user',
        ConversationId: conversationId || streamConversationKey,
        Status: 'success',
        StatusDesc: '',
        Messages: [
            {
                Type: 'question',
                MessageId: `placeholder-user-${timestamp}`,
                Name: 'question',
                Title: '',
                Status: 'success',
                StatusDesc: '',
                Contents: userContents,
            },
        ],
        ExtraInfo: baseExtraInfo(true),
    };
    streamState.records.push(userRecord);

    // 创建助手消息占位
    const assistantRecord: Record = {
        Role: 'assistant',
        RecordId: 'placeholder-agent',
        ConversationId: conversationId || streamConversationKey,
        Status: 'processing',
        StatusDesc: '',
        Messages: [],
        ExtraInfo: baseExtraInfo(false),
    };
    streamState.records.push(assistantRecord);

    // 发送消息后滚动到底部
    nextTick(() => {
        mainLayoutRef.value?.getChatRef()?.backToBottom();
    });

    streamState.abortController = new AbortController();

    const contents: Content[] = [{ Type: 'text', Text: query }];
    await fetchSSE(
        () => {
            return sendMessage(
                {
                    Contents: contents,
                    ConversationId: conversationId || undefined,
                    ApplicationId: applicationId,
                },
                { signal: streamState.abortController?.signal },
                mergedApiDetailConfig.value.sendMessageApi
            );
        },
        {
            success(event: SseEvent) {
                if (event.Type === 'conversation') {
                    // 创建新的对话，重新调用 chatlist 接口更新列表
                    loadConversations();
                    if (event.Payload.IsNewConversation) {
                        const previousKey = streamConversationKey;
                        streamConversationKey = moveConversationRuntimeState(
                            previousKey,
                            event.Payload.Id,
                            event.Payload.ApplicationId || streamState.applicationId
                        );
                        if (currentConversationStateKey.value === previousKey) {
                            currentConversationStateKey.value = streamConversationKey;
                            internalCurrentConversation.value = event.Payload;
                        }
                        // 乐观 UI：把占位项（pending key）就地替换为真实会话
                        // 若 loadConversations() 已经先返回，pending 项可能已被后端列表覆盖，
                        // 此时 replaceConversation 找不到对应 Id，方法内部 no-op
                        if (internalConversations.value.some(c => c.Id === previousKey)) {
                            replaceConversationInList(previousKey, event.Payload);
                        }
                    }
                    return;
                }

                const targetState = ensureConversationRuntimeState(streamConversationKey);
                if (!targetState) {
                    return;
                }
                const resolvedApplicationId =
                    targetState.applicationId ||
                    applicationId ||
                    internalCurrentApplication.value?.ApplicationId;

                const replacePlaceholder = (placeholderId: string, next: Record): Record | undefined => {
                    const placeholderIdx = targetState.records.findIndex(item => item.RecordId === placeholderId);
                    if (placeholderIdx !== -1) {
                        targetState.records.splice(placeholderIdx, 1, next);
                        return next;
                    }
                    return undefined;
                };

                const updateRecord = (next: Record, placeholderId: string): Record => {
                    const idx = targetState.records.findIndex(item => item.RecordId === next.RecordId);
                    if (idx !== -1) {
                        if (targetState.records[idx] !== undefined) {
                            Object.assign(targetState.records[idx], next);
                            return targetState.records[idx] as Record;
                        }
                        return next;
                    }
                    const replaced = replacePlaceholder(placeholderId, next);
                    if (replaced) {
                        return replaced;
                    }
                    targetState.records.push(next);
                    return next;
                };

                if (event.Type === 'request_ack') {
                    // 用户消息：替换占位
                    const placeholderUser = targetState.records.find(item => item.RecordId === 'placeholder-user');
                    const nextUser = applySseEventToRecord(event, placeholderUser);
                    if (nextUser) {
                        const appliedUser = updateRecord(nextUser, 'placeholder-user');
                        void hydrateReferences([appliedUser], { applicationId: resolvedApplicationId });
                    }
                } else {
                    // 助手消息：只用占位 + lastRecord
                    const lastIndex = targetState.records.length - 1;
                    const lastRecord = targetState.records[lastIndex];
                    const baseAssistant =
                        lastRecord && (lastRecord.RecordId === 'placeholder-agent' || lastRecord.Role === 'assistant')
                            ? lastRecord
                            : undefined;
                    const nextAssistant = applySseEventToRecord(event, baseAssistant);
                    if (nextAssistant) {
                        const appliedAssistant = updateRecord(nextAssistant, 'placeholder-agent');
                        void hydrateReferences([appliedAssistant], { applicationId: resolvedApplicationId });
                    }
                }

                // 每次收到数据后滚动到底部
                if (currentConversationStateKey.value === streamConversationKey) {
                    nextTick(() => {
                        mainLayoutRef.value?.getChatRef()?.backToBottom();
                    });
                }
            },
            complete(isOk) {
                const targetState = getConversationRuntimeState(streamConversationKey);
                if (targetState) {
                    targetState.isChatting = false;
                    targetState.abortController = null;
                }
                if (!isOk) {
                    return;
                }
                // 乐观 UI：路径 1（agentId 分支已提前拿到真实 conversationId）不会触发 SSE 的 conversation 事件，
                // 需要在 SSE 完成后主动刷一次列表，让后端返回的真实会话（含正式 Title / LastActiveAt）覆盖占位项。
                // 路径 2 已在 success 事件里就地替换过，这里的 loadConversations 只是"顺带兜底"，代价可以接受。
                if (isNewConversationSend) {
                    loadConversations();
                }
                // 完成后滚动到底部并延迟重置用户滚动状态
                if (currentConversationStateKey.value === streamConversationKey) {
                    nextTick(() => {
                        mainLayoutRef.value?.getChatRef()?.backToBottom();
                        setTimeout(() => {
                            mainLayoutRef.value?.getChatRef()?.setHasUserScrolled(false);
                        }, 500);
                    });
                }
            },
            fail(msg, errorEvent) {
                // 乐观 UI 回滚：SSE 失败时，若本次是新会话发送、且占位仍在，清掉避免侧栏残留死条目
                // 覆盖两种占位：pending-conversation:* 前缀（路径 2）和真实 Id 占位（路径 1，agentId 分支）
                if (isNewConversationSend) {
                    if (internalConversations.value.some(c => c.Id === streamConversationKey)) {
                        removeConversationFromList(streamConversationKey);
                    }
                }
                handleStreamFailure(msg, errorEvent, streamConversationKey);
            }
        }
    );
};

// 内部停止处理（API 模式）
const handleInternalStop = () => {
    stopConversationStream(currentConversationStateKey.value);
    emit('stop');
};

// 内部加载更多处理（API 模式）
const handleInternalLoadMore = async (conversationId: string, lastRecordId: string) => {
    if (!useApiMode.value) {
        emit('loadMore', conversationId, lastRecordId);
        return;
    }

    // 确保 applications 列表已加载完成
    await applicationsReadyPromise;

    try {
        const response = await fetchConversationDetail(
            { ConversationId: conversationId, LastRecordId: lastRecordId },
            mergedApiDetailConfig.value.conversationDetailApi
        );
        const newRecords: Record[] = response?.Response?.Records || [];
        const applicationId = response?.Response?.ApplicationId || internalCurrentApplication.value?.ApplicationId || '';

        if (newRecords.length > 0) {
            await hydrateReferences(newRecords, { applicationId });
            const targetState = ensureConversationRuntimeState(conversationId);
            if (targetState) {
                targetState.records = [...newRecords, ...targetState.records];
                if (applicationId) {
                    targetState.applicationId = applicationId;
                }
            }
            mainLayoutRef.value?.notifyLoaded();
        } else {
            mainLayoutRef.value?.notifyComplete();
        }
        nextTick(() => {
            if (!lastRecordId) {
                mainLayoutRef.value?.getChatRef()?.backToBottom();
            }
        })
    } catch (error) {
        mainLayoutRef.value?.notifyComplete();
        const text = mergedChatI18n.value.loadMoreFailed;
        MessagePlugin.error(text);
        emit('message', MessageCode.LOAD_MORE_FAILED, text);
    }
};


// 内部评分处理（API 模式）
const handleInternalRate = async (conversationId: string, recordId: string, score: typeof ScoreValue[keyof typeof ScoreValue]) => {
    if (!useApiMode.value) {
        emit('rate', conversationId, recordId, score);
        return;
    }

    try {
        const payload: { [key: string]: unknown } = { ConversationId: conversationId, RecordId: recordId, Score: score };
        await rateMessage(payload, mergedApiDetailConfig.value.rateApi);
        // 更新本地状态
        const record = getConversationRecords(conversationId).find(r => r.RecordId === recordId);
        if (record) {
            record.Score = score;
        }
        // 显示感谢反馈信息（使用 i18n 文案）
        const message = score === ScoreValue.Like ? mergedChatItemI18n.value.thxForGood : score === ScoreValue.Dislike ? mergedChatItemI18n.value.thxForBad : '';
        if (message) {
            MessagePlugin.info(message);
        }
    } catch (error) {
        const text = mergedChatI18n.value.rateFailed;
        MessagePlugin.error(text);
        emit('message', MessageCode.RATE_FAILED, text);
    }
};

// 内部分享处理（API 模式）
const handleInternalShare = async (conversationId: string, applicationId: string, recordIds: string[]) => {
    if (!useApiMode.value) {
        emit('share', conversationId, applicationId, recordIds);
        return;
    }

    try {
        const response = await createShare(
            { ConversationId: conversationId, ApplicationId: applicationId, RecordIds: recordIds },
            mergedApiDetailConfig.value.shareApi
        );
        const shareUrl = `${window.location.origin}${window.location.pathname}#/share?ShareId=${response.ShareId}`;
        await copyToClipboard(shareUrl, {
            isMobile: isMobile.value,
            onSuccess: () => {
                MessagePlugin.success(mergedChatI18n.value.copySuccess);
            },
            onError: () => {
                const text = mergedChatI18n.value.copyFailed;
                MessagePlugin.error(text);
                emit('message', MessageCode.COPY_FAILED, text);
            },
        });
    } catch (error) {
        const text = mergedChatI18n.value.shareFailed;
        MessagePlugin.error(text);
        emit('message', MessageCode.SHARE_FAILED, text);
    }
};

const handleSelectApplication = (app: Application) => {
    if (useApiMode.value) {
        internalCurrentApplication.value = app;
        internalCurrentConversation.value = undefined;
        currentConversationStateKey.value = '';
        // 清空 Sender 输入内容
        const senderRef = mainLayoutRef.value?.getChatRef()?.getSenderRef();
        if (senderRef) {
            senderRef.changeSenderVal('');
        }
    }
    emit('selectApplication', app);
};

const handleSelectConversation = async (conversation: ChatConversation) => {
    const isSameConversation =
        conversation.Id === internalCurrentConversation.value?.Id &&
        currentConversationStateKey.value === conversation.Id;

    if (isSameConversation) return;

    if (useApiMode.value) {
        internalCurrentConversation.value = conversation;
        currentConversationStateKey.value = conversation.Id;
        setConversationApplicationId(conversation.Id, conversation.ApplicationId);
    }
    emit('selectConversation', conversation);
};

const handleCreateConversation = () => {
    if (useApiMode.value) {
        internalCurrentConversation.value = undefined;
        currentConversationStateKey.value = '';
    }
    // 新建会话时强制刷新当前应用的 agentId：跳过内存缓存与本地 DB，
    // 重新 CopyAgentFromApp 生成新的 agentId 并覆盖写回（仅 claw 应用生效，内部已做门槛判断）。
    const appId = currentApplicationId.value;
    if (appId) {
        fetchAndSetAgentId({ applicationId: appId, force: true });
    }
    emit('createConversation');
};

/**
 * 删除会话（由页面调用，二次确认交给调用方）。
 *
 * 这里只负责「删除」本身：
 *   1) 保护：进行中的会话不允许删
 *   2) 乐观 UI：先从列表移除 → 请求后端 → 失败回滚 + 提示
 *   3) 删的是当前会话时清空主区（视觉上退回空态）
 *   4) pending 占位从未落库，跳过后端调用，仅清本地状态
 *   5) 清理 conversationRuntimeStates 对应 key，避免残留影响 chattingConversationIds
 *
 * 确认弹窗不放在这里：调用方是后台页面，用它自己的弹窗视觉语言，
 * 组件库再弹一个 TDesign 对话框会造成两套观感。
 */
const requestDeleteConversation = async (conversation: ChatConversation) => {
    if (!conversation?.Id) return;

    // 兜底：进行中会话禁止删除
    if (isConversationChatting(conversation.Id)) {
        MessagePlugin.warning('会话正在进行中，请先停止后再删除');
        return;
    }

    const isPendingPlaceholder = conversation.Id.startsWith('pending-conversation:');

    // 先留快照，删除请求失败时整体回滚
    const prevList = internalConversations.value.slice();
    removeConversationFromList(conversation.Id);

    // 如果删的是当前会话，清空主区状态
    const wasCurrent =
        internalCurrentConversation.value?.Id === conversation.Id ||
        currentConversationStateKey.value === conversation.Id;
    if (wasCurrent) {
        internalCurrentConversation.value = undefined;
        currentConversationStateKey.value = '';
    }

    // pending 占位：从未落库，仅清本地 runtime state
    if (isPendingPlaceholder) {
        delete conversationRuntimeStates.value[conversation.Id];
        return;
    }

    try {
        await deleteConversation(
            conversation.Id,
            mergedApiDetailConfig.value.conversationDeleteApi,
        );
        // 后端成功：清理对应 runtime state（历史 records / applicationId 等）
        delete conversationRuntimeStates.value[conversation.Id];
        emit('deleteConversation', conversation);
    } catch (err: any) {
        // 404：会话已经被其他端/其他 tab 删除，视为成功，UI 不回滚
        // 避免"我看到的还在，但后端说不存在"这种拧巴的状态
        const status = err?.response?.status ?? err?.status;
        if (status === 404) {
            delete conversationRuntimeStates.value[conversation.Id];
            emit('deleteConversation', conversation);
            return;
        }
        // 其它错误：回滚，把这条塞回原位置
        rollbackConversations(prevList);
        if (wasCurrent) {
            internalCurrentConversation.value = conversation;
            currentConversationStateKey.value = conversation.Id;
        }
        MessagePlugin.error('删除失败，请稍后重试');
        console.error('删除会话失败:', err);
        throw err;
    }
};

// 内部复制处理
const handleInternalCopy = async (rowtext: string | undefined, content: string | undefined, type: string) => {
    await copyToClipboard(content, {
        rawText: rowtext,
        isMobile: isMobile.value,
        onSuccess: () => {
            MessagePlugin.success(mergedChatI18n.value.copySuccess);
        },
        onError: () => {
            const text = mergedChatI18n.value.copyFailed;
            MessagePlugin.error(text);
            emit('message', MessageCode.COPY_FAILED, text);
        },
    });
    emit('copy', rowtext, content, type);
};

/**
 * 通用「用户在既有消息上追加内容」的 SSE 骨架。
 *
 * 与 handleInternalSend 的差异：不预插入 placeholder-user，用户消息以后端 request_ack 事件里的
 * Record 为准（通过占位插入到 assistant 占位前）。适用于 widget_action、questionnaire 这类
 * 「已有 assistant record 上的二次交互」。
 *
 * @param contents 上行的 Contents 数组
 * @param conversationId 当前会话 id；为空表示新会话，将走占位 key
 * @param applicationId 应用 id；用于新会话首事件识别
 */
const runContentSSE = async (
    contents: Content[],
    conversationId: string,
    applicationId: string,
) => {
    let streamConversationKey = conversationId || currentConversationStateKey.value || createPendingConversationKey();
    currentConversationStateKey.value = streamConversationKey;
    const streamState = ensureConversationRuntimeState(streamConversationKey);
    if (!streamState) return;

    streamState.isChatting = true;
    streamState.applicationId = applicationId || streamState.applicationId;
    mainLayoutRef.value?.getChatRef()?.setHasUserScrolled(false);

    const timestamp = Date.now();
    const baseExtraInfo = (isFromSelf: boolean) => ({
        RequestId: '',
        TraceId: '',
        Elapsed: 0,
        StartTime: timestamp,
        IsFromSelf: isFromSelf,
    });

    // 创建助手消息占位
    const assistantRecord: Record = {
        Role: 'assistant',
        RecordId: 'placeholder-agent',
        ConversationId: conversationId || streamConversationKey,
        Status: 'processing',
        StatusDesc: '',
        Messages: [],
        ExtraInfo: baseExtraInfo(false),
    };
    streamState.records.push(assistantRecord);

    nextTick(() => {
        mainLayoutRef.value?.getChatRef()?.backToBottom();
    });

    streamState.abortController = new AbortController();

    await fetchSSE(
        () => sendMessage(
            {
                Contents: contents,
                ConversationId: conversationId || undefined,
                ApplicationId: applicationId,
            },
            { signal: streamState.abortController?.signal },
            mergedApiDetailConfig.value.sendMessageApi
        ),
        {
            success(sseEvent: SseEvent) {
                if (sseEvent.Type === 'conversation') {
                    loadConversations();
                    if (sseEvent.Payload.IsNewConversation) {
                        const previousKey = streamConversationKey;
                        streamConversationKey = moveConversationRuntimeState(
                            previousKey,
                            sseEvent.Payload.Id,
                            sseEvent.Payload.ApplicationId || streamState.applicationId
                        );
                        if (currentConversationStateKey.value === previousKey) {
                            currentConversationStateKey.value = streamConversationKey;
                            internalCurrentConversation.value = sseEvent.Payload;
                        }
                    }
                    return;
                }

                const targetState = ensureConversationRuntimeState(streamConversationKey);
                if (!targetState) return;

                const resolvedApplicationId =
                    targetState.applicationId ||
                    applicationId ||
                    internalCurrentApplication.value?.ApplicationId;

                const replacePlaceholder = (placeholderId: string, next: Record): Record | undefined => {
                    const placeholderIdx = targetState.records.findIndex(item => item.RecordId === placeholderId);
                    if (placeholderIdx !== -1) {
                        targetState.records.splice(placeholderIdx, 1, next);
                        return next;
                    }
                    return undefined;
                };

                const updateRecord = (next: Record, placeholderId: string): Record => {
                    const idx = targetState.records.findIndex(item => item.RecordId === next.RecordId);
                    if (idx !== -1) {
                        if (targetState.records[idx] !== undefined) {
                            Object.assign(targetState.records[idx], next);
                            return targetState.records[idx] as Record;
                        }
                        return next;
                    }
                    const replaced = replacePlaceholder(placeholderId, next);
                    if (replaced) return replaced;
                    targetState.records.push(next);
                    return next;
                };

                // request_ack 包含用户消息记录：插入到 assistant 占位前
                if (sseEvent.Type === 'request_ack') {
                    const nextUser = applySseEventToRecord(sseEvent, undefined);
                    if (nextUser) {
                        const placeholderIdx = targetState.records.findIndex(item => item.RecordId === 'placeholder-agent');
                        if (placeholderIdx !== -1) {
                            targetState.records.splice(placeholderIdx, 0, nextUser);
                        } else {
                            const lastIdx = targetState.records.length - 1;
                            targetState.records.splice(lastIdx, 0, nextUser);
                        }
                    }
                    return;
                } else {
                    const lastIndex = targetState.records.length - 1;
                    const lastRecord = targetState.records[lastIndex];
                    const baseAssistant =
                        lastRecord && (lastRecord.RecordId === 'placeholder-agent' || lastRecord.Role === 'assistant')
                            ? lastRecord
                            : undefined;
                    const nextAssistant = applySseEventToRecord(sseEvent, baseAssistant);
                    if (nextAssistant) {
                        const appliedAssistant = updateRecord(nextAssistant, 'placeholder-agent');
                        void hydrateReferences([appliedAssistant], { applicationId: resolvedApplicationId });
                    }
                }
            },
            complete(isOk) {
                const targetState = conversationRuntimeStates.value[streamConversationKey];
                if (targetState) {
                    targetState.isChatting = false;
                    targetState.abortController = null;
                }
                if (!isOk) {
                    return;
                }
                if (currentConversationStateKey.value === streamConversationKey) {
                    nextTick(() => {
                        mainLayoutRef.value?.getChatRef()?.backToBottom();
                    });
                }
            },
            fail(msg, errorEvent) {
                handleStreamFailure(msg, errorEvent, streamConversationKey);
            }
        }
    );
};

/**
 * 发送 widget_action SSE 请求
 */
const sendWidgetActionSSE = async (conversationId: string, applicationId: string, widgetAction: WidgetActionRequest) => {
    const contents: Content[] = [{ Type: 'widget_action', WidgetAction: widgetAction }];
    await runContentSSE(contents, conversationId, applicationId);
};

/**
 * 发送反问澄清 SSE 请求
 * @param questionnaire 已由 ClassifyTag 构造好的、带 Answers 的完整 questionnaire 内容体
 */
const sendQuestionnaireSSE = async (conversationId: string, applicationId: string, questionnaire: Questionnaire) => {
    const contents: Content[] = [{ Type: 'questionnaire', Questionnaire: questionnaire }];
    await runContentSSE(contents, conversationId, applicationId);
};

// 内部 Widget 事件处理（API 模式）
const handleInternalWidgetEvent = async (event: CustomEvent, widgetRunId: string, widgetId: string, recordId: string) => {
    // 使用集中式事件处理器进行路由分发
    const result = routeWidgetEvent(event, widgetRunId, widgetId);
    
    // sys.go_to_url / sys.download 等本地处理完成的事件
    if (result.handled) {
        emit('widgetEvent', event, widgetRunId, widgetId, recordId);
        return;
    }
    
    // sys.chat / sys.clarify - 需要发送 SSE 请求
    if (result.widgetActionRequest) {
        // 检查是否正在进行请求
        const currentKey = currentConversationStateKey.value;
        if (currentKey && isConversationChatting(currentKey)) {
            console.warn('[layout/Index] widget action: 正在进行请求，跳过此次提交');
            if (recordId) {
                disableWidgetsByRecordId(recordId);
            }
            return;
        }
        
        // 先禁用该消息下的所有 widgets（防止重复提交）
        if (recordId) {
            disableWidgetsByRecordId(recordId);
        }
        
        if (!useApiMode.value) {
            emit('widgetEvent', event, widgetRunId, widgetId, recordId);
            return;
        }
        
        const conversationId = internalCurrentConversation.value?.Id || currentConversationStateKey.value;
        const applicationId = internalCurrentApplication.value?.ApplicationId || '';
        
        if (!conversationId) {
            console.warn('[layout/Index] widget action: 没有当前会话');
            emit('widgetEvent', event, widgetRunId, widgetId, recordId);
            return;
        }
        
        // 发送 widget_action SSE 请求
        await sendWidgetActionSSE(conversationId, applicationId, result.widgetActionRequest);
        
        emit('widgetEvent', event, widgetRunId, widgetId, recordId);
        return;
    }
    
    // 其他事件类型，只向外传递
    emit('widgetEvent', event, widgetRunId, widgetId, recordId);
};

/**
 * 内部反问澄清提交处理（API 模式）
 *
 * 把 ClassifyTag 组装好的、带 Answers 的 questionnaire 内容体作为一条 Content 走 SSE
 * （对齐 webim ChatProtocolHandler.sendQuestionnaireAnswer）。
 *
 * @param questionnaire ClassifyTag 组装好的、带 Answers 的完整内容体
 * @param recordId      触发澄清的原始助手消息 recordId，仅用于回传给外层
 */
const handleInternalQuestionnaireSubmit = async (questionnaire: Questionnaire, recordId: string) => {
    // 会话进行中 → 幂等丢弃（ClassifyTag 内部已置为已提交态，此处不用回滚 UI）
    const currentKey = currentConversationStateKey.value;
    if (currentKey && isConversationChatting(currentKey)) {
        console.warn('[layout/Index] questionnaire submit: 会话正在进行中，跳过此次提交');
        return;
    }

    if (!useApiMode.value) {
        // 非 API 模式：交给外部宿主自行处理上行
        emit('questionnaireSubmit', questionnaire, recordId);
        return;
    }

    const conversationId = internalCurrentConversation.value?.Id || currentConversationStateKey.value;
    const applicationId = internalCurrentApplication.value?.ApplicationId || '';

    if (!conversationId) {
        console.warn('[layout/Index] questionnaire submit: 没有当前会话');
        emit('questionnaireSubmit', questionnaire, recordId);
        return;
    }

    await sendQuestionnaireSSE(conversationId, applicationId, questionnaire);
    emit('questionnaireSubmit', questionnaire, recordId);
};

/**
 * 内部反问澄清跳过处理（API 模式）
 *
 * 对齐 webim 主流做法（client-v2 / assist-side / workflow-v2 / manage-skills / frequent-app）：
 * 跳过澄清 = 发送一条普通文本消息（i18n `clarifySkip`，默认「跳过」/「Skip」）。
 *
 * 注意：不要把 `{Answers: []}` 或 `{Skipped: true}` 的 questionnaire 作为 Content 上行——
 * 后端在这条通用消息通道上要求必须有可展示的用户消息内容，否则会返回
 * "missing user message content in messages"。仅 SkillsCompareColumn 场景使用
 * `{Skipped: true}` 单独的 sendQuestionnaireSkip 通道，与此处协议不同。
 *
 * @param questionnaire 原始 questionnaire 内容体（仅用于回传外层，函数本身不消费）
 * @param recordId      触发澄清的助手消息 recordId（仅用于回传外层）
 */
const handleInternalQuestionnaireSkip = async (questionnaire: Questionnaire, recordId: string) => {
    const currentKey = currentConversationStateKey.value;
    if (currentKey && isConversationChatting(currentKey)) {
        console.warn('[layout/Index] questionnaire skip: 会话正在进行中，跳过此次提交');
        return;
    }

    if (!useApiMode.value) {
        emit('questionnaireSkip', questionnaire, recordId);
        return;
    }

    const conversationId = internalCurrentConversation.value?.Id || currentConversationStateKey.value || '';
    const applicationId = internalCurrentApplication.value?.ApplicationId || '';

    // 跳过文案取 i18n（默认「跳过」/「Skip」），对齐 webim `$t('跳过')` 行为
    const skipText = mergedChatI18n.value.clarifySkip || '跳过';

    // 走标准的 handleInternalSend：与用户手动发送"跳过"完全一致，
    // 用户消息以正常文本气泡展示，避免任何"空 Content 上行"引发的后端校验失败。
    await handleInternalSend(skipText, conversationId, applicationId);
    emit('questionnaireSkip', questionnaire, recordId);
};

// 记录上一次的 ID 值，用于判断变化
let prevConvId: string | undefined = undefined;

/**
 * 当前应用变化 → 重拉会话列表。
 * 先清空再拉，避免切换瞬间闪一下上一个应用的会话。
 */
watch(currentApplicationId, (newId, oldId) => {
    if (newId === oldId) return;
    internalConversations.value = [];
    void loadConversations();
}, { immediate: true });

/**
 * 把会话列表状态整体抛给调用方渲染。
 * 一个事件覆盖「列表变了 / 进行中变了 / 加载中 / 失败」四种转移，
 * 调用方只做纯渲染，不必自己发请求或推导状态。
 */
watch(
    [internalConversations, chattingConversationIds, isFetchingConversations, conversationsError],
    ([list, chattingIds, loading, error]) => {
        emit('conversationsChange', {
            list,
            chattingIds,
            loading,
            error,
        });
    },
    { immediate: true },
);

// 监听外部传入的 currentApplicationId 和 currentConversationId 变化
watch(
    [
        () => props.currentApplicationId,
        () => props.currentConversationId,
        () => actualApplications.value,
        () => actualConversations.value
    ],
    async ([appId, convId, apps, conversations]) => {
        // 处理应用 ID 变化
        if (appId && apps.length > 0) {
            const foundApp = apps.find(app => app.ApplicationId === appId);
            if (foundApp && foundApp.ApplicationId !== internalCurrentApplication.value?.ApplicationId) {
                internalCurrentApplication.value = foundApp;
            }
        }

        // 处理会话 ID 变化（本地 /chat/conversations 列表命中即可切换）
        if (convId && conversations.length > 0) {
            const foundConv = conversations.find(conv => conv.Id === convId);
            if (foundConv && (
                foundConv.Id !== internalCurrentConversation.value?.Id ||
                currentConversationStateKey.value !== foundConv.Id
            )) {
                internalCurrentConversation.value = foundConv;
                currentConversationStateKey.value = foundConv.Id;
                setConversationApplicationId(foundConv.Id, foundConv.ApplicationId);
                // 如果会话有关联的应用，且未指定 appId，则自动切换应用
                if (!appId && foundConv.ApplicationId && apps.length > 0) {
                    const convApp = apps.find(app => app.ApplicationId === foundConv.ApplicationId);
                    if (convApp) {
                        internalCurrentApplication.value = convApp;
                    }
                }
            }
        } else if (convId && currentConversationStateKey.value !== convId) {
            // 列表还没回来（深链直接进入）或该会话不在当前列表里：
            // 仍要把 stateKey 切过去。actualChatList 读的是 stateKey 而不是
            // currentConversationId，不切就会出现"消息拉回来了但一条都不显示"。
            currentConversationStateKey.value = convId;
        } else if (!convId && prevConvId) {
            // ID 从有值变为空时，清空当前会话
            internalCurrentConversation.value = undefined;
            currentConversationStateKey.value = '';
        }

        prevConvId = convId;
    },
    { immediate: true },
);

// 监听外部传入的 currentApplication 对象变化，同步内部状态
watch(() => props.currentApplication, (newApp) => {
    if (newApp) {
        internalCurrentApplication.value = newApp;
    }
}, { immediate: true });

// 监听外部传入的 currentConversation 对象变化，同步内部状态
watch([() => props.currentConversation, () => actualApplications.value], async ([newConversation, apps]) => {
    if (newConversation && (
        newConversation.Id !== internalCurrentConversation.value?.Id ||
        currentConversationStateKey.value !== newConversation.Id
    )) {
        internalCurrentConversation.value = newConversation;
        currentConversationStateKey.value = newConversation.Id;
        setConversationApplicationId(newConversation.Id, newConversation.ApplicationId);
        // 同时更新对应的应用
        if (newConversation.ApplicationId && apps.length > 0) {
            const foundApp = apps.find(app => app.ApplicationId === newConversation.ApplicationId);
            if (foundApp) {
                internalCurrentApplication.value = foundApp;
            }
        }
    }
}, { immediate: true });

// 组件挂载时自动加载数据
onMounted(async () => {
    if (useApiMode.value && props.autoLoad) {
        // axios 配置已由 useApiConfig composable 自动处理
        // 先加载用户信息和系统配置，因为如果配置了AUTO_CREATE_ACCOUNT，会在加载用户信息时创建账户
        await Promise.all([
            loadUserInfo(),
            loadSystemConfig(),
        ]);
        // 会话列表不在这里拉：它由 watch(currentApplicationId) 驱动，
        // 而 currentApplicationId 要等 loadApplications 选出默认应用之后才有值。
        await loadApplications();
    }
});

onUnmounted(() => {
    Object.values(conversationRuntimeStates.value).forEach((state) => {
        state.abortController?.abort();
        state.abortController = null;
        state.isChatting = false;
    });
});

// 暴露方法供外部调用
defineExpose({
    loadApplications,
    loadConversations,
    loadConversationDetail,
    loadUserInfo,
    loadSystemConfig,
    startNewConversation: handleCreateConversation,
    deleteConversation: requestDeleteConversation,
    notifyLoaded: () => mainLayoutRef.value?.notifyLoaded(),
    notifyComplete: () => mainLayoutRef.value?.notifyComplete(),
});
</script>

<template>
    <MainLayout
        class="adp-chat-root"
        ref="mainLayoutRef"
        :currentApplicationAvatar="currentApplicationAvatar"
        :currentApplicationName="currentApplicationName"
        :currentApplicationGreeting="currentApplicationGreeting"
        :currentApplicationOpeningQuestions="currentApplicationOpeningQuestions"
        :currentApplicationId="currentApplicationId"
        :chatId="currentConversationId"
        :chatList="actualChatList"
        :isChatting="actualIsChatting"
        :isMobile="isMobile"
        :theme="theme"
        :language="props.language"
        :mode="chatMode"
        :aiWarningText="aiWarningText"
        :i18n="props.chatI18n"
        :chatItemI18n="props.chatItemI18n"
        :senderI18n="props.senderI18n"
        :isOverlay="props.isOverlay"
        :suggestionApi="mergedApiDetailConfig.suggestionListApi"
        @send="handleInternalSend"
        @stop="handleInternalStop"
        @loadMore="handleInternalLoadMore"
        @rate="handleInternalRate"
        @share="handleInternalShare"
        @copy="handleInternalCopy"
        @message="(code: MessageCode, message: string) => emit('message', code, message)"
        @conversationChange="(conversationId: string) => emit('conversationChange', conversationId)"
        @widgetEvent="handleInternalWidgetEvent"
        @questionnaireSubmit="handleInternalQuestionnaireSubmit"
        @questionnaireSkip="handleInternalQuestionnaireSkip"
    />
</template>

<style scoped>
.page-container {
    height: 100%;
    width: 100%;
}
.content {
    display: flex;
    height: 100%;
    width:100%;
    position: relative;
}
/* 移动端毛玻璃遮罩 */
.mobile-overlay {
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    background: var(--td-mask-disabled);
    backdrop-filter: blur(4px);
    -webkit-backdrop-filter: blur(4px);
    z-index: 99;
}
.header-overlay-icon{
    margin-left: var(--td-size-4);
}

.open-file-list-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    width: var(--td-comp-size-m);
    height: var(--td-comp-size-m);
    border-radius: var(--td-radius-medium);
    cursor: pointer;
    color: var(--td-text-color-secondary);
    transition: all 0.2s;
}

.open-file-list-btn:hover {
    color: var(--td-brand-color);
    background: var(--td-bg-color-container-hover);
}

/* 顶栏通用图标按钮（定时任务等） */
.header-action-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    width: var(--td-comp-size-m);
    height: var(--td-comp-size-m);
    border-radius: var(--td-radius-medium);
    cursor: pointer;
    color: var(--td-text-color-secondary);
    transition: all 0.2s;
    margin-right: var(--td-size-2);
}

.header-action-btn:hover {
    color: var(--td-brand-color);
    background: var(--td-bg-color-container-hover);
}

.header-action-btn--active {
    color: var(--td-brand-color);
    background: var(--td-bg-color-container-active);
}

/* 主区容器：让 MainLayout 与 CronTask 覆盖层共享同一区域
 * 默认 column（overlay 模式下 CronTask 绝对定位覆盖 MainLayout）
 * sidebar 模式切成 row：MainLayout 与 CronTask 横向并列 */
.main-area {
    flex: 1;
    min-width: 0;
    height: 100%;
    display: flex;
    flex-direction: column;
    position: relative;
    overflow: hidden;
}
.main-area--sidebar {
    flex-direction: row;
}
/* sidebar 模式下聊天区占满剩余空间 */
.main-area--sidebar .main-area__chat {
    flex: 1;
    min-width: 0;
    height: 100%;
}
/* 定时任务覆盖层：填充主区，覆盖会话窗口（从左侧入口/新窗口打开） */
.cron-task-overlay {
    position: absolute;
    inset: 0;
    background: var(--td-bg-color-container);
    z-index: 2;
    display: flex;
    flex-direction: column;
    overflow: hidden;
}
</style>
