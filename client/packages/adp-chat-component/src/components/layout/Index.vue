<!-- ADP 聊天布局主组件，支持 API 模式和 Props 模式 -->
<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch, nextTick, toRefs, provide } from 'vue';
import { Layout as TLayout, Content as TContent, MessagePlugin, DialogPlugin, Tooltip, Icon as TIcon } from 'tdesign-vue-next';

// TLayout, TContent 已导入，模板中使用对应组件
import MainLayout from './MainLayout.vue';
import SideLayout from './SideLayout.vue';
import FilePreviewLayout from './FilePreviewLayout.vue';
import LogoArea from '../LogoArea.vue';
import CustomizedIcon from '../CustomizedIcon.vue';
import CronTask from '../CronTask/CronTask.vue';
import CronTaskExecutionSidebar from '../CronTask/CronTaskExecutionSidebar.vue';
import ChannelConversationPanel from '../Channel/ChannelConversationPanel.vue';
import type { Application, AppPattern } from '../../model/application';
import type { ChatConversation, Record, Reference, SseEvent, Content, ErrorEvent, Questionnaire } from '../../model/chat-v2';
import type { CronTaskI18n, TimerTask, TimerTaskSummary } from '../../model/cronTask';
import { getCronTaskI18nByLanguage } from '../../model/cronTask';
import { AppTriggerScope, AppTriggerStatus } from '../../model/appTrigger';
import type { AppTriggerSummary } from '../../model/appTrigger';
import type { FileProps } from '../../model/file';
import { ScoreValue } from '../../model/chat-v2';
import type { ApiConfig } from '../../service/api';
import {
    fetchApplicationList,
    // fetchConversationList 已移入 SideLayout 内部使用（方案 B：SideLayout 按 appId 主动拉取）
    deleteConversation,
    fetchConversationDetail,
    fetchConversationDetailV2,
    fetchReferenceDetails,
    createConversation,
    ConversationType,
    sendMessage,
    rateMessage,
    createShare,
    fetchUserInfo,
    uploadFile,
    parseFile,
    fetchSystemConfig,
    describeConversationList,
} from '../../service/api';
import type { SystemConfig } from '../../service/api';
import { describeChannel, describeChannelList, ClawChannelStatus, buildChannelUserId, type ChannelItem } from '../../service/channelApi';
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
    SideI18n, 
    ChatI18n, 
    ChatItemI18n, 
    SenderI18n,
    FilePreviewI18n,
    ThemeProps,
    OverlayProps,
    ChatMode
} from '../../model/type';
import { 
    defaultLanguageOptions,
    themePropsDefaults,
    overlayPropsDefaults,
    defaultFilePreviewI18n,
    defaultFilePreviewI18nEn,
    defaultChatI18n,
    defaultChatI18nEn,
    defaultChatItemI18n,
    defaultChatItemI18nEn,
    defaultSenderI18n,
    defaultSenderI18nEn,
    defaultSideI18n,
    defaultSideI18nEn
} from '../../model/type';
import { useAgentStore } from '../../composables/useAgentStore';
import { describeAppTriggerSummaryList, describeAppTriggerRunLogList } from '../../service/appTriggerApi';
import { getTriggerId, getTriggerName, getTriggerLastFireTime, getTriggerStatus, getTriggerSuccessCount, getTriggerFailureCount } from '../../utils/appTrigger';
import { formatRelativeTime } from '../../utils/cronTask';
import type { SideGroupItem } from './SideGroupList.vue';


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
    /**
     * 当前选中的会话是否为渠道（访客）会话。
     * 由外层根据 URL 语义传入（如 `/:appId/channel/:convId` → true）。
     *
     * 用途：渠道会话不落地本地 chat_conversation 表，权威源在 CAPI DescribeConversationList。
     *   - 刷新场景：置 true 时组件会直接触发「渠道恢复」流程（DescribeChannelList + DescribeConversationList
     *     反查所属渠道并建立选中态 + 主动拉首屏），跳过普通 /chat/messages（避免 404）
     *   - 置 false / 未传：按普通会话流程（本地 /chat/conversations 命中 + InfiniteLoading /chat/messages）
     */
    currentConversationChannel?: boolean;
    /** 当前会话是否来自定时任务执行记录（cron task 产生的 channel 型会话）。
     *    同 currentConversationChannel 机制：URL 携带会话 ID + 此标记时，绕过本地列表匹配，
     *    直接注册为渠道会话 + DescribeConversationMessageList 拉首屏历史。
     *    配合父组件的 URL 格式如 /:appId/timertask/:convId 使用，刷新页面后能正确还原。
     */
    currentConversationCronTask?: boolean;
    /**
     * 当前定时任务会话对应的触发器 ID（URL 携带的 triggerId，如 query 参数）。
     * 刷新页面后用于自动定位到该触发器的详情面板（右侧 sidebar）。
     * 通常来源：父应用 URL `/:appId/timertask/:convId?triggerId=xxx` 中解析。
     */
    currentConversationCronTaskTriggerId?: string;
    /**
     * 当前定时任务会话对应的执行记录 InstanceId（URL 携带的 logId，如 query 参数）。
     * 刷新页面后用于在右侧 sidebar 高亮当前那条运行记录，保证"选中态"能跨刷新保留。
     * 通常来源：父应用 URL `/:appId/timertask/:convId?triggerId=xxx&logId=yyy` 中解析。
     */
    currentConversationCronTaskLogId?: string;
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
    /** 侧边栏国际化文本 */
    sideI18n?: SideI18n;
    /** 聊天国际化文本 */
    chatI18n?: ChatI18n;
    /** ChatItem 国际化文本 */
    chatItemI18n?: ChatItemI18n;
    /** Sender 国际化文本 */
    senderI18n?: SenderI18n;
    /** 文件预览面板国际化文本 */
    filePreviewI18n?: FilePreviewI18n;
    /** API 配置 - 如果传入则使用 HTTP 请求获取数据 */
    apiConfig?: ApiConfig;
    /** 是否自动加载数据（仅在使用 apiConfig 时生效） */
    autoLoad?: boolean;
    /** 是否启用 Skills 功能 */
    enableSkills?: boolean;
    /** Skills 空间 ID */
    skillsSpaceId?: string;
    /** Skills 应用 ID（/adp/ 转发需要） */
    skillsApplicationId?: string;
    /** 定时任务国际化文本 */
    cronTaskI18n?: Partial<CronTaskI18n>;
    /** @deprecated AppTrigger 不再需要模型/文件夹选项，保留以兼容 */
    cronTaskModelOptions?: Array<{ label: string; value: string }>;
    /** @deprecated AppTrigger 不再需要模型/文件夹选项，保留以兼容 */
    cronTaskFolderOptions?: Array<{ label: string; value: string }>;
    /** 定时任务：列表分页大小 */
    cronTaskPageSize?: number;
    /** 定时任务：详情页运行日志轮询间隔（ms） */
    cronTaskPollInterval?: number;
    /** 是否在侧边栏显示"定时任务"入口 */
    enableCronTask?: boolean;
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
    enableSkills: true,
    skillsSpaceId: '',
    skillsApplicationId: '',
    cronTaskI18n: () => ({}),
    cronTaskModelOptions: () => [],
    cronTaskFolderOptions: () => [],
    cronTaskPageSize: 20,
    cronTaskPollInterval: 10 * 1000,
    enableCronTask: true,
});

const {
    getAgentIdByAppId,
    fetchAndSetAgentId,
    watchApplicationId,
    agentIdMap,
    setApplicationModes,
} = useAgentStore();

const emit = defineEmits<{
    (e: 'selectApplication', app: Application): void;
    /**
     * 选中会话（普通 / 渠道）
     * 第二参 fromChannel：true 表示是渠道（访客）会话，外层应据此使用不同的 URL 变体
     * （例如 /:appId/channel/:convId），保证刷新后仍能还原为渠道会话选中态。
     */
    (e: 'selectConversation', conversation: ChatConversation, fromChannel: boolean): void;
    /** 删除会话（用户在侧栏确认删除后触发；API 模式下删除已完成再 emit，非 API 模式仅透传） */
    (e: 'deleteConversation', conversation: ChatConversation): void;
    (e: 'createConversation'): void;
    (e: 'toggleTheme'): void;
    (e: 'changeLanguage', key: string): void;
    (e: 'logout'): void;
    (e: 'userClick'): void;
    (e: 'close'): void;
    (e: 'overlay', isOverlay: boolean): void;
    (e: 'send', query: string, fileList: FileProps[], conversationId: string, applicationId: string): void;
    (e: 'stop'): void;
    (e: 'loadMore', conversationId: string, lastRecordId: string): void;
    (e: 'rate', conversationId: string, recordId: string, score: typeof ScoreValue[keyof typeof ScoreValue]): void;
    (e: 'share', conversationId: string, applicationId: string, recordIds: string[]): void;
    (e: 'copy', rowtext: string | undefined, content: string | undefined, type: string): void;
    (e: 'uploadFile', files: File[]): void;
    (e: 'uploadStatus', status: 'uploading' | 'done'): void;
    (e: 'startRecord'): void;
    (e: 'stopRecord'): void;
    (e: 'message', code: MessageCode, message: string): void;
    (e: 'conversationChange', conversationId: string): void;
    (e: 'dataLoaded', type: 'applications' | 'conversations' | 'chatList' | 'user' | 'systemConfig', data: any): void;
    /** Widget 事件（用于与 SSE/对话流交互） */
    (e: 'widgetEvent', event: CustomEvent, widgetRunId: string, widgetId: string, recordId: string): void;
    /** 反问澄清提交：questionnaire 为可直接上行的内容体（API 模式内部消化后再对外通知） */
    (e: 'questionnaireSubmit', questionnaire: Questionnaire, recordId: string): void;
    /** 反问澄清跳过：questionnaire 为原始内容体 */
    (e: 'questionnaireSkip', questionnaire: Questionnaire, recordId: string): void;
    /** 定时任务面板可见性变化 */
    (e: 'cronTaskVisibleChange', visible: boolean): void;
    /** 定时任务：再次点击入口重置为初始 list 视图，请求外层清空 timertask 相关 URL 段（保留会话 id） */
    (e: 'cronTaskResetUrl'): void;
    /** 定时任务：立即执行并查看 */
    (e: 'cronTaskRunAndView', task: TimerTask | TimerTaskSummary): void;
    /** 渠道：展开/收起渠道会话列表 */
    (e: 'toggleChannelList'): void;
    /** 定时任务：切换到聊天窗口（携带任务 & 会话 / 日志 Id / 触发器 Id） */
    (e: 'cronTaskSwitchToChat', payload: { task: TimerTask | TimerTaskSummary; triggerId?: string; sessionId?: string; logId?: string; userId?: string }): void;
    /** 定时任务：某个操作完成（新增/编辑/删除/暂停/恢复/立即执行等） */
    (e: 'cronTaskActionDone', action: string, task: TimerTask | TimerTaskSummary): void;
    /** 定时任务：优化 Prompt */
    (e: 'cronTaskOptimizePrompt', content: string): void;
}>();

// 解构 props 保持响应式
const { theme } = toRefs(props);

const sidebarVisible = ref(!props.isSidePanelOverlay);
const mainLayoutRef = ref<InstanceType<typeof MainLayout> | null>(null);
const sideLayoutRef = ref<InstanceType<typeof SideLayout> | null>(null);
const filePreviewLayoutRef = ref<InstanceType<typeof FilePreviewLayout> | null>(null);

// 文件预览面板显示状态
const filePreviewVisible = ref(false);

// 定时任务面板显示状态（覆盖会话窗口）
const cronTaskVisible = ref(false);
// 定时任务侧边栏模式：正在查看定时任务会话时，右侧面板与聊天并存
const cronTaskSidebarActiveConvId = ref('');
const cronTaskSidebarMode = computed(() =>
    cronTaskVisible.value && !!cronTaskSidebarActiveConvId.value
);
/** sidebar 模式下当前定位的任务（用于渲染执行历史 sidebar） */
const cronTaskSidebarTask = ref<TimerTask | TimerTaskSummary | null>(null);
/** sidebar 模式下当前激活的执行记录 InstanceId（列表高亮） */
const cronTaskSidebarActiveLogId = ref('');
/** CronTask 组件引用（暴露 showTaskDetail / refreshList） */
const cronTaskRef = ref<InstanceType<typeof CronTask> | null>(null);
/** 渠道会话列表抽屉可见性 */
const channelDrawerVisible = ref(false);

/**
 * 侧边栏「定时任务」分组：原始触发器摘要列表。
 * 数据源 DescribeAppTriggerSummaryList，与 CronTaskPanel 同源，仅取首页用于侧栏概览。
 */
const cronTaskListRaw = ref<AppTriggerSummary[]>([]);
/** 侧边栏「定时任务」分组：当前选中项 id（用于列表高亮） */
const currentCronTaskId = ref('');

/**
 * 打开定时任务面板
 * 同时关闭文件预览面板，避免同时叠加
 */
const openCronTask = () => {
    if (cronTaskVisible.value) return;
    // 打开定时任务面板时，清除远程终端（渠道）选中态与历史对话列表选中态，避免多个选中态并存
    clearChannelSelection();
    clearConversationSelection();
    // 从入口（顶栏 / 快捷按钮）打开 → 进入列表态，清除侧栏定时任务项高亮
    currentCronTaskId.value = '';
    cronTaskSidebarActiveConvId.value = '';   // 从入口打开 → 全屏模式
    cronTaskSidebarTask.value = null;
    cronTaskSidebarActiveLogId.value = '';
    cronTaskVisible.value = true;
    filePreviewVisible.value = false;
    emit('cronTaskVisibleChange', true);
};

/**
 * 关闭定时任务面板
 */
const closeCronTask = () => {
    if (!cronTaskVisible.value) return;
    cronTaskVisible.value = false;
    cronTaskSidebarActiveConvId.value = '';
    cronTaskSidebarTask.value = null;
    cronTaskSidebarActiveLogId.value = '';
    // 注意：不清空 currentCronTaskId。关闭执行记录 sidebar 后用户仍停留在该定时任务的对话页，
    // 左侧定时任务列表应保持高亮选中态；此处若清空会导致高亮丢失。
    // 侧栏项高亮的清除交由「从入口打开列表(openCronTask)」「再次点击入口重置(handleSideActionClick)」等场景处理。
    emit('cronTaskVisibleChange', false);
};

/**
 * 恢复右侧执行记录 sidebar 关联的任务 stub。
 * 当处于定时任务会话、但 cronTaskSidebarTask 为空时（closeCronTask 关闭后被清空，
 * 或刷新时父层解析的 triggerId 晚于会话恢复 watch 就绪），用当前会话 URL 携带的 triggerId
 * 构造最小 stub 交给 <CronTaskExecutionSidebar>，使其 triggerId 有值 → fetchLogs 正常拉取
 * 执行记录列表，避免"重新打开/刷新后没有新拿 list"。
 * getEntityId 依次读 TriggerId → TimerId，二者都塞上兼容 AppTrigger 与旧 TimerTask。
 */
const restoreCronTaskSidebarTask = () => {
    if (cronTaskSidebarTask.value) return;
    const triggerId = props.currentConversationCronTaskTriggerId;
    if (!triggerId) return;
    cronTaskSidebarTask.value = {
        TriggerId: triggerId,
        TimerId: triggerId,
    } as any;
    cronTaskSidebarActiveLogId.value = props.currentConversationCronTaskLogId || '';
};

/**
 * Header 定时任务图标点击：
 * - 当前正在浏览定时任务会话（currentConversationCronTask 或 sidebar 已激活）：仅切换右侧 sidebar 显隐
 * - 否则走全屏 openCronTask
 */
const handleCronTaskHeaderIconClick = () => {
    const inCronTaskConversation = props.currentConversationCronTask
        || !!cronTaskSidebarActiveConvId.value;
    if (inCronTaskConversation) {
        // 切换右侧 sidebar 显隐（保持当前会话 & sidebar 关联 convId 不动）
        if (cronTaskVisible.value) {
            cronTaskVisible.value = false;
            emit('cronTaskVisibleChange', false);
        } else {
            // 若 sidebar convId 丢失（例如页面初次进入），用当前会话 id 兜底
            if (!cronTaskSidebarActiveConvId.value) {
                cronTaskSidebarActiveConvId.value = props.currentConversationId || currentConversationStateKey.value;
            }
            // 关闭后重新打开时 cronTaskSidebarTask 已被 closeCronTask 清空，此处需按当前会话恢复，
            // 否则 <CronTaskExecutionSidebar> triggerId 为空，fetchLogs 短路 → 执行记录列表空白。
            restoreCronTaskSidebarTask();
            cronTaskVisible.value = true;
            filePreviewVisible.value = false;
            emit('cronTaskVisibleChange', true);
        }
        return;
    }
    openCronTask();
};

/**
 * 切换文件预览面板显示
 * 打开时重置为纯文档列表状态，不保留上次预览态
 */
const toggleFilePreview = () => {
    if (filePreviewVisible.value) {
        filePreviewVisible.value = false;
    } else {
        filePreviewVisible.value = true;
        nextTick(() => {
            filePreviewLayoutRef.value?.resetToList();
        });
    }
};

/**
 * 打开文件预览面板
 */
const openFilePreview = () => {
    filePreviewVisible.value = true;
};

/**
 * 关闭文件预览面板
 */
const closeFilePreview = () => {
    filePreviewVisible.value = false;
};

/**
 * 打开文件预览并定位到指定路径（不展示文档列表列）
 */
const viewFile = (filePath: string) => {
    if (!filePath) return;
    openFilePreview();
    nextTick(() => {
        filePreviewLayoutRef.value?.setPreviewPath(filePath, { showDir: false });
    });
};

provide('viewFile', viewFile);

// 上传状态
const isUploading = ref(false);

// 合并 i18n 配置（根据 language 选择对应语言的默认值）
const mergedChatItemI18n = computed(() => {
    const defaults = props.language?.startsWith('en') ? defaultChatItemI18nEn : defaultChatItemI18n;
    return { ...defaults, ...props.chatItemI18n };
});

// 合并文件预览 i18n 配置（根据 language 选择对应语言的默认值）
const mergedFilePreviewI18n = computed(() => {
    const defaults = props.language?.startsWith('en') ? defaultFilePreviewI18nEn : defaultFilePreviewI18n;
    return { ...defaults, ...props.filePreviewI18n };
});

// 合并侧边栏 i18n（顶栏"定时任务"按钮 tooltip 复用 sideI18n.cronTask）
const mergedSideI18n = computed(() => {
    const defaults = props.language?.startsWith('en') ? defaultSideI18nEn : defaultSideI18n;
    return { ...defaults, ...props.sideI18n };
});

/**
 * 合并定时任务 i18n（侧边栏「定时任务」分组、执行记录 sidebar 等复用）。
 * 供本文件内部构造 cronTaskItems、格式化时间等使用，
 * 组件自身仍会各自内部合并（组件同时接收 language + i18n）。
 */
const mergedCronTaskI18n = computed(() => ({
    ...getCronTaskI18nByLanguage(props.language),
    ...props.cronTaskI18n,
}));

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

/** 当前用户 ID（来自 /account/info 返回的 Id） */
const currentUserId = computed(() => internalUser.value?.id || '');
/** 当前应用的 agent ID（来自 useAgentStore 缓存，由 watchApplicationId 自动拉取） */
const currentAgentId = computed(() => agentIdMap.value[currentApplicationId.value] || '');
const currentApplicationName = computed(() => actualCurrentApplication.value?.Name || '');
// Skills 的 ApplicationId 优先用显式配置，否则回退到当前应用 ID
const skillsAppId = computed(() => props.skillsApplicationId || currentApplicationId.value);
// Skills 空间 ID：优先从当前应用接口返回的 SpaceId 获取，否则回退到显式 props
const resolvedSpaceId = computed(() => actualCurrentApplication.value?.SpaceId || props.skillsSpaceId || 'default_space');
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

/**
 * 是否为 claw 模式：严格基于当前应用的 Pattern === 'ClawAgent'（即 clawcloud / AppMode=4），
 * 不受 props.mode 手动配置干扰。
 * 定时任务、远程终端等能力仅在 claw 模式下开放，其他模式一律隐藏入口且不请求相关接口。
 */
const isClawMode = computed(
    () => (actualCurrentApplication.value?.Pattern as AppPattern | null | undefined) === 'ClawAgent',
);

/**
 * 定时任务统一开关：外部 enableCronTask 且当前为 claw 模式时才启用。
 * 控制侧栏入口、分组列表、header 按钮、全屏面板、执行记录 sidebar 的显隐。
 */
const cronTaskEnabled = computed(() => props.enableCronTask && isClawMode.value);

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
 * 会话列表加载入口（方案 B：由 SideLayout 内部按 currentApplicationId 主动拉取）
 *
 * 变更说明：
 * - 后端请求由 SideLayout.fetchList() 发起，本函数改为委托到 sideLayoutRef.reload()
 * - internalConversations 保留作为"业务判断镜像"（isConversationChatting、getConversationDisplayName、
 *   SSE 事件里判断占位是否存在等仍读它），通过 handleSideConversationsChange 由 SideLayout 事件反向同步
 * - 若 SideLayout 尚未挂载（首次加载最早期），本函数是 no-op，不会阻塞其它并行初始化流程
 */
const loadConversations = async () => {
    if (!useApiMode.value) return;
    if (!sideLayoutRef.value) return;
    await sideLayoutRef.value.reload();
};

/**
 * SideLayout 内部会话列表变化时的镜像同步：
 * SideLayout 是权威源，Index 只做镜像，供 chattingConversationIds / SSE 占位查询 等业务判断使用。
 */
const handleSideConversationsChange = (list: ChatConversation[]) => {
    internalConversations.value = list;
};

/**
 * SideLayout 拉取后端成功后触发（区别于乐观 UI 变更）
 * 保留 dataLoaded 事件语义，供外部业务感知
 */
const handleSideConversationsLoaded = (list: ChatConversation[]) => {
    emit('dataLoaded', 'conversations', list);
};

/**
 * SideLayout 拉取后端失败时的错误提示（保持与原 loadConversations 的错误行为一致）
 */
const handleSideFetchError = (_error: unknown) => {
    const text = mergedChatI18n.value.getConversationListFailed;
    MessagePlugin.error(text);
    emit('message', MessageCode.GET_CONVERSATION_LIST_FAILED, text);
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
const handleInternalSend = async (query: string, fileList: FileProps[], conversationId: string, applicationId: string) => {
    if (isUploading.value) return;
    if (!useApiMode.value) {
        emit('send', query, fileList, conversationId, applicationId);
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
            // 方案 B：SideLayout 是权威源；本地镜像通过 SideLayout 的 @conversationsChange 事件同步，
            // 无需再手动写 internalConversations（写了也会被 change 事件覆盖，语义不冲突，但避免出现"镜像先于源"的窗口）
            sideLayoutRef.value?.addOptimistic(optimisticConversation);
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

    // 构建用户消息展示内容（图片和文档都作为 file Content 展示）
    const userContents: Content[] = [{ Type: 'text', Text: query }];
    for (const file of fileList) {
        if (file.status === 'done' && file.url) {
            const extName = file.name?.split('.').pop() || '';
            userContents.push({
                Type: 'file',
                File: { DocId: file.docId || '0', FileName: file.name || '', FileUrl: file.url, FileSize: String(file.size || 0), FileType: extName },
            });
        }
    }

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
    // 将所有已上传成功的文件（图片和文档）以 file content 格式加入
    for (const file of fileList) {
        if (file.status === 'done' && file.url) {
            const extName = file.name?.split('.').pop() || '';
            contents.push({
                Type: 'file',
                File: {
                    DocId: file.docId || '0',
                    FileName: file.name || '',
                    FileUrl: file.url,
                    FileSize: String(file.size || 0),
                    FileType: extName,
                },
            });
        }
    }
    await fetchSSE(
        () => {
            return sendMessage(
                {
                    Contents: contents,
                    ConversationId: conversationId || undefined,
                    ApplicationId: applicationId,
                    FileInfos: fileList,
                    // 渠道会话 / 定时任务会话：告知后端本次会话属于 vendor 权威源，不在本地 chat_conversation 表落地
                    // （对齐 webim：这类会话的权威数据源在 vendor 侧 CAPI，不应污染 /chat/conversations 侧栏列表）
                    IsChannel: shouldSkipLocalConversationPersist.value,
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
                        // 若 loadConversations() 已经先返回，pending 项在 SideLayout 端已被覆盖（fetchList 里以后端为准），
                        // 此时 replaceConversation 找不到对应 Id，方法内部 no-op
                        if (internalConversations.value.some(c => c.Id === previousKey)) {
                            sideLayoutRef.value?.replaceConversation(previousKey, event.Payload);
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
                        sideLayoutRef.value?.removeConversation(streamConversationKey);
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

    // 渠道（访客）会话：历史消息由 loadChannelHistory 主动加载（对齐 adp-b2c selectConversation → loadConversationHistory，
    // 仅拉取一屏 50 条、不做滚动分页），因此 Chat 组件被动的 InfiniteLoading 不再重复拉取，直接结束即可，
    // 避免与主动加载产生重复消息 / vue-infinite-loading 空内容重复触发。
    // 之所以不能走下方标准 /chat/messages：该接口按登录账号在本地库查会话，渠道访客会话不在本地库、
    // 且 UserId 会被强制成账号 ID，无法拉到渠道历史。
    if (channelConversationUserId.value[conversationId]) {
        mainLayoutRef.value?.notifyComplete();
        return;
    }

    // 【URL 刷新场景】URL 语义明示该 conv 是渠道会话（props.currentConversationChannel=true）：
    //   Chat 组件 InfiniteLoading 挂载即触发 loadMore，此时渠道恢复流程可能还没跑完
    //   （channelConversationUserId 映射未建立）→ 如果直接走下方 /chat/messages 会 404。
    //   处理：先等待正在进行的 restore（若还没启动则主动触发），
    //     - 命中 → channelConversationUserId 建立 → 走渠道分支 notifyComplete
    //     - 未命中/失败 → 该 conv 本身不存在或不属于任何渠道，也不应走 /chat/messages，直接 notifyComplete 结束
    //   核心：URL 已标记渠道，绝不回退到普通 /chat/messages 分支。
    if (
        useApiMode.value
        && props.currentConversationChannel
        && props.currentConversationId === conversationId
    ) {
        let pendingRestore = channelRestorePending.get(conversationId);
        if (!pendingRestore) {
            const appId = props.currentApplicationId
                || internalCurrentApplication.value?.ApplicationId
                || '';
            if (appId) {
                pendingRestore = restoreChannelConversationById(conversationId, appId);
            }
        }
        if (pendingRestore) {
            try {
                await pendingRestore;
            } catch (err) {
                console.warn('[handleInternalLoadMore] 等待渠道恢复出错:', err);
            }
        }
    // 无论 restore 结果如何，URL 标记为渠道的 conv 都不应触发 /chat/messages
        mainLayoutRef.value?.notifyComplete();
        return;
    }

    // 【URL 刷新场景】定时任务会话（props.currentConversationCronTask=true）：同渠道逻辑
    if (
        useApiMode.value
        && props.currentConversationCronTask
        && props.currentConversationId === conversationId
    ) {
        // 确保已注册为渠道会话，后续首屏历史由 restore 或 handleCronTaskSwitchToChat 的缓存补充
        if (!channelConversationUserId.value[conversationId]) {
            channelConversationUserId.value[conversationId] = 'anonymous';
        }
        mainLayoutRef.value?.notifyComplete();
        return;
    }

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

/**
 * 将 DescribeConversationMessageList 返回的消息分组为前端 V2 Record 列表。
 * 兼容两种上游返回：
 *   1) 已分组的 Record 格式（后端 describe_conversation_message_list 方法返回，含 Messages 数组）→ 直接用；
 *   2) 扁平 ConversationMessage 列表（后端未加载专属方法、走 forward_request 直连 CAPI 时返回）→ 按 RecordId 分组。
 * 逻辑对齐后端 tcadp.py 的 _convert_messages_to_records，确保任一后端状态下都能正确渲染。
 */
const groupChannelMessagesToRecords = (messages: any[], conversationId: string): Record[] => {
    if (!messages || messages.length === 0) return [];
    const first = messages[0];
    // 已是分组的 Record 格式
    if (first && Array.isArray(first.Messages)) return messages as Record[];
    // 扁平格式：按 RecordId 分组，保留 Score（RateMsgRecord 后 DescribeConversationMessageList 返回更新后的评分）
    const groups = new Map<string, any>();
    const groupScores = new Map<string, number>();
    for (const msg of messages) {
        const recordId = msg?.RecordId || '';
        if (!recordId) continue;
        if (!groups.has(recordId)) {
            groups.set(recordId, {
                Role: msg.Role || 'assistant',
                RecordId: recordId,
                ConversationId: msg.ConversationId || conversationId,
                Status: msg.Status || 'completed',
                StatusDesc: msg.StatusDesc || '',
                Messages: [],
                ExtraInfo: msg.ExtraInfo,
            });
        }
        // 保留 Score
        const score = msg?.Score;
        if (score !== undefined && score !== null && score !== 0) {
            groupScores.set(recordId, score);
        }
        groups.get(recordId).Messages.push({
            Type: msg.Type || 'reply',
            MessageId: msg.MessageId || '',
            Name: msg.Name || '',
            Title: msg.Title || '',
            Icon: msg.Icon || '',
            Status: msg.Status || 'completed',
            StatusDesc: msg.StatusDesc || '',
            Contents: msg.Contents || [],
            ExtraInfo: msg.ExtraInfo,
            RecordId: recordId,
        });
    }
    // 将评分写入分组后的 Record
    for (const [recordId, score] of groupScores) {
        groups.get(recordId).Score = score;
    }
    return Array.from(groups.values()) as Record[];
};

/**
 * 主动加载渠道会话首屏历史（对齐 adp-b2c selectConversation → loadConversationHistory）。
 * 渠道（访客）会话选中后立即调用，直接通过 CAPI DescribeConversationMessageList 拉取历史并填充，
 * 不依赖 Chat 组件被动的 InfiniteLoading，确保"选中即出历史"。
 * 首屏结果覆盖写入 runtime state。对齐 adp-b2c：渠道历史仅拉取一屏（50 条），不做滚动分页。
 */
const loadChannelHistory = async (conversationId: string, userId: string, applicationId: string) => {
    if (!conversationId || !userId) return;
    const appId = applicationId || currentApplicationId.value || internalCurrentApplication.value?.ApplicationId || '';
    try {
        const resp = await fetchConversationDetailV2(
            {
                ConversationId: conversationId,
                Limit: 50,
                // Type=5（CONVERSATION_TYPE_CHANNEL）：与 DescribeConversationList 一致，
                // 渠道会话列表接口用 Type=5 才能拉到列表；对应的历史消息也必须用 Type=5，
                // 否则 CAPI 会因 Type 不一致找不到该 Channel 下的消息（400/空返回）。
                Type: 5,
                // 携带渠道 UserId（对齐 adp-b2c loadConversationHistory 的 UserId 参数）
                UserId: userId,
                // 1=向前（从最新往更早取）
                RecordQueryDirection: 1,
                IsChannel: true,
            },
            appId,
            mergedApiDetailConfig.value.describeConversationMessageListApi,
        );
        const data = resp?.Response || ({} as NonNullable<typeof resp>['Response']);
        // 兼容后端返回已分组 Records（专属方法）或扁平 Messages（forward 直连）
        const records: Record[] = (data.Records && data.Records.length)
            ? data.Records
            : groupChannelMessagesToRecords((data.Messages as any[]) || [], conversationId);
        // 标记为渠道历史消息（供 Chat 组件 channelDividerIndex 计算：
        // 仅当用户后续发送"非历史"新消息时，才在其前显示渠道分割线，对齐 webim _is_history 语义）
        records.forEach((r) => { (r as any)._isChannelHistory = true; });
        console.debug('[loadChannelHistory] loaded', {
            conversationId,
            userId,
            count: records.length,
            raw: data,
        });
        if (records.length > 0) {
            await hydrateReferences(records, { applicationId: appId });
        }
        // 首屏：覆盖写入（而非 prepend），确保切换会话后展示的是本会话历史
        setConversationRecords(conversationId, records, appId);
        nextTick(() => {
            mainLayoutRef.value?.getChatRef()?.backToBottom();
        });
    } catch (error) {
        console.error('[loadChannelHistory] failed:', error);
    }
};

// 内部评分处理（API 模式）
const handleInternalRate = async (conversationId: string, recordId: string, score: typeof ScoreValue[keyof typeof ScoreValue]) => {
    if (!useApiMode.value) {
        emit('rate', conversationId, recordId, score);
        return;
    }

    try {
        // 渠道/定时任务会话不在本地 ChatConversation 表中，
        // 后端 get_application_id 会失败，需附带 ApplicationId 供后端 fallback
        const isVendorConversation = !!channelConversationUserId.value[conversationId]
            || (props.currentConversationCronTask && props.currentConversationId === conversationId);
        const payload: { [key: string]: unknown } = { ConversationId: conversationId, RecordId: recordId, Score: score };
        if (isVendorConversation) {
            payload.ApplicationId = currentApplicationId.value || '';
        }
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

const handleToggleSidebar = () => {
    sidebarVisible.value = !sidebarVisible.value;
};

const handleSelectApplication = (app: Application) => {
    if (useApiMode.value) {
        internalCurrentApplication.value = app;
        internalCurrentConversation.value = undefined;
        currentConversationStateKey.value = '';
        // 清空 Sender 中的已选文件和输入内容
        const senderRef = mainLayoutRef.value?.getChatRef()?.getSenderRef();
        if (senderRef) {
            senderRef.changeSenderVal('', []);
        }
    }
    // 切换应用时关闭文件预览面板 & 定时任务面板
    closeFilePreview();
    closeCronTask();
    // 移动端选择应用后收起侧边栏
    if (isMobile.value || props.isSidePanelOverlay) {
        sidebarVisible.value = false;
    }
    emit('selectApplication', app);
};

const handleSelectConversation = async (conversation: ChatConversation, fromChannel = false) => {
    const isSameConversation =
        conversation.Id === internalCurrentConversation.value?.Id &&
        currentConversationStateKey.value === conversation.Id;

    if (isSameConversation) {
        if (isMobile.value) {
            sidebarVisible.value = false;
        }
        return;
    }

    if (useApiMode.value) {
        internalCurrentConversation.value = conversation;
        currentConversationStateKey.value = conversation.Id;
        setConversationApplicationId(conversation.Id, conversation.ApplicationId);
        // 点击历史对话列表（非渠道入口）选中会话时，无条件清空渠道选中态：
        // 取消渠道高亮、恢复输入框可用。渠道会话选中走 handleChannelConversationSelect（fromChannel=true），不清。
        if (!fromChannel) {
            clearChannelSelection();
        }
    }
    // 切换会话时关闭文件预览面板；仅非渠道/定时任务场景才关闭 CronTask
    closeFilePreview();
    if (!fromChannel) {
        closeCronTask();
    }
    // 移动端选择对话后收起侧边栏
    if (isMobile.value) {
        sidebarVisible.value = false;
    }
    emit('selectConversation', conversation, fromChannel);
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
    // 创建新会话时关闭文件预览面板 & 定时任务面板
    closeFilePreview();
    closeCronTask();
    emit('createConversation');
};

/**
 * 定时任务面板 → 切回聊天（webim 风格：运行记录侧边栏 + 对话区并存）
 * 内部完成「选中会话 + 拉取 DescribeConversationMessageList 历史 + 渲染」全链路
 */
const handleCronTaskSwitchToChat = async (payload: { task: TimerTask | TimerTaskSummary; triggerId?: string; sessionId?: string; logId?: string; userId?: string }) => {
    const conversationId = payload.sessionId || '';
    if (!conversationId) return;

    const appId = currentApplicationId.value || internalCurrentApplication.value?.ApplicationId || '';
    const userId = payload.userId || 'anonymous';

    // 1. 注册为渠道会话，后续 handleInternalLoadMore 会走 CAPI 历史加载
    channelConversationUserId.value[conversationId] = userId;
    channelRestoreAttempted.add(conversationId);

    // 2. 构造 stub 并选中
    const stub: ChatConversation = {
        Id: conversationId,
        ApplicationId: appId,
    } as ChatConversation;
    internalCurrentConversation.value = stub;
    currentConversationStateKey.value = conversationId;
    setConversationApplicationId(conversationId, appId);
    clearChannelSelection();

    // 2.5 提前进入侧边栏模式并同步 URL（放在 async 拉历史之前）
    //   ⚠️ Bug 修复：以前这里 emit('selectConversation', stub, true) 会让父层先 push 到
    //   home-channel 路由（URL 闪现 /channel/），随后才由末尾的 cronTaskSwitchToChat 改成
    //   /timertask/，造成「channel → timertask」URL 抖动。
    //   现在移除 selectConversation，直接、且提前 emit cronTaskSwitchToChat 一步到位 push 到
    //   timertask 路由；父层同样会同步 currentConversationId，从而触发内部按 conversationId
    //   重新拉取记录，等价于原「清空旧 chatList、强制走内部源」的效果。
    //   提前 emit 也保证下方 async 期间 Chat 组件 watch(chatId) 回声出的 conversationChange
    //   使用到正确的定时任务上下文 flag（cronTask=true），不会被覆写回普通路由。
    cronTaskSidebarActiveConvId.value = conversationId;
    cronTaskSidebarTask.value = payload.task || cronTaskSidebarTask.value;
    cronTaskSidebarActiveLogId.value = payload.logId || '';
    if (!cronTaskVisible.value) {
        cronTaskVisible.value = true;
    }
    emit('cronTaskSwitchToChat', payload);

    // 3. 主动拉首屏历史
    try {
        const resp = await fetchConversationDetailV2(
            {
                ConversationId: conversationId,
                Limit: 50,
                Type: 5,
                UserId: userId,
                RecordQueryDirection: 1,
                IsChannel: true,
            },
            appId,
            mergedApiDetailConfig.value.describeConversationMessageListApi,
        );
        const data = resp?.Response || ({} as NonNullable<typeof resp>['Response']);
        const records: Record[] = (data.Records && data.Records.length)
            ? data.Records
            : groupChannelMessagesToRecords((data.Messages as any[]) || [], conversationId);
        records.forEach((r) => { (r as any)._isChannelHistory = true; });
        if (records.length > 0) {
            await hydrateReferences(records, { applicationId: appId });
        }
        setConversationRecords(conversationId, records, appId);
        nextTick(() => {
            mainLayoutRef.value?.getChatRef()?.backToBottom();
        });
    } catch (e) {
        console.error('[CronTaskSwitchToChat] load history failed:', e);
        MessagePlugin.warning(mergedChatI18n.value.loadMoreFailed);
    }
};

/**
 * SideActions 快捷入口点击：
 * - key === 'cron-task'：打开定时任务面板（等同于顶栏 header-action 的 openCronTask）
 * - key === 'channel-list'：展开/收起渠道会话列表（对齐 webim channel-drawer）
 */
/**
 * 渠道会话列表面板中选中一条会话：
 * 对齐 adp-b2c selectConversation / webim handleAutoSelectSession，
 * 复用 handleSelectConversation 切换当前会话，随后主动调用 loadChannelHistory
 * 通过 CAPI DescribeConversationMessageList（带渠道 UserId + Type=1）拉取该会话历史消息。
 */
const handleChannelConversationSelect = async (conversationId: string) => {
    if (!conversationId) return;
    // 停止当前流（切换会话前打断旧的 SSE，对齐 adp-b2c）
    const prevState = conversationRuntimeStates.value[currentConversationStateKey.value];
    if (prevState) {
        prevState.abortController?.abort();
        prevState.isChatting = false;
    }
    // 找到目标会话（列表 + Panel 内部拉取共享一份 API，最坏情况兜底 stub）
    const matched = internalConversations.value.find(c => c.Id === conversationId)
        || { Id: conversationId, AccountId: '', ApplicationId: currentApplicationId.value, Title: '', LastActiveAt: 0, CreatedAt: 0 } as ChatConversation;
    const channelUserId = remoteTerminalActiveUserId.value;
    // 记录该会话属于当前渠道，历史消息走 CAPI（带渠道 UserId + Type=1）
    if (channelUserId) {
        channelConversationUserId.value[conversationId] = channelUserId;
    }
    await handleSelectConversation(matched, true);
    // 主动加载该会话首屏历史（对齐 adp-b2c selectConversation → loadConversationHistory）
    if (channelUserId) {
        await loadChannelHistory(conversationId, channelUserId, matched.ApplicationId || currentApplicationId.value);
    }
};

const handleSideAction = (key: string) => {
    if (key === 'new-task') {
        // 新建对话（"新建任务"入口）：清空渠道 / 定时任务选中态，回到"选中应用后的全新对话"状态
        clearChannelSelection();
        handleCreateConversation();
    }
    if (key === 'cron-task') {
        // 再次点击"定时任务"入口：
        // - 若面板未打开：正常打开
        // - 若已打开（可能停留在 detail 或 sidebar 模式）：重置为初始 list 视图，
        //   清空 sidebar 关联状态，并请求外层清空 timertask 相关 URL 段
        if (cronTaskVisible.value) {
            cronTaskRef.value?.resetToList?.();
            currentCronTaskId.value = '';
            cronTaskSidebarActiveConvId.value = '';
            cronTaskSidebarTask.value = null;
            cronTaskSidebarActiveLogId.value = '';
            emit('cronTaskResetUrl');
        } else {
            openCronTask();
        }
    }
    if (key === 'channel-list') {
        channelDrawerVisible.value = !channelDrawerVisible.value;
        emit('toggleChannelList');
    }
};

/** 当前选中的远程终端 ID（渠道选中后 SideActions 显示"展开列表"入口） */
const remoteTerminalActiveId = ref('');
/** 当前选中渠道的显示名称 */
const remoteTerminalActiveLabel = ref('');
/** 当前选中渠道的 CAPI ChannelId（proto v2 已定义，SDK 未开放；保留供后续启用） */
const remoteTerminalActiveChannelId = ref('');
/**
 * 当前选中渠道绑定的 UserId（来自 channel.spec.UserAgent.UserId）
 * 这是渠道会话过滤的核心字段：ADP 每个渠道对应一个专属 UserAgent，
 * 传 UserId 到 DescribeConversationList 即可精准拉取该渠道下的会话（对齐 adp-b2c）
 */
const remoteTerminalActiveUserId = ref('');
/** 当前选中渠道绑定的 AgentId（来自 channel.spec.UserAgent.AgentId） */
const remoteTerminalActiveAgentId = ref('');

/**
 * 定时任务（AppTrigger）作用域：固定为 USER(2)。
 * 业务约定：所有 AppTrigger 均以"C 端访客维度"落库，Scope 恒为 2、user_id 必带。
 */
const cronTaskScope = computed(() => AppTriggerScope.USER);

/**
 * 定时任务（AppTrigger）owner_user_id 取值：
 * 对齐 channel 场景 UserAgent.UserId 的派生规则（见 buildChannelUserId）——
 *   `chatclient_<currentUserId>`。
 * 特性：
 *   - 稳定唯一：同一登录账号任何时候派生结果都一致；
 *   - 账号级归属：该账号名下所有 AppTrigger 与 channel 会话共用同一个 owner，
 *     与 channel 侧数据天然打通；
 *   - 与账号自身应用会话隔离：`chatclient_` 前缀避免和账号原始 id 冲突。
 * 说明：这里不再使用 `remoteTerminalActiveUserId`（渠道选中态、会变动），
 *   而是直接从 currentUserId 派生，保证 Scope=USER 下 user_id 永不为空且稳定。
 */
const cronTaskUserId = computed(() => buildChannelUserId(currentUserId.value || ''));

/**
 * 侧边栏「定时任务」分组列表项：映射原始触发器摘要 → SideGroupItem。
 * 参考 smart-webim conversation-list 的 cronTaskFieldMap：
 *   id = 触发器 id，label = 触发器名称，extraText = 上次触发时间（相对格式）。
 * 显示逻辑对齐 webim：无数据时由 SideGroupList 的 hideWhenEmpty 自动隐藏整组。
 */
const cronTaskItems = computed<SideGroupItem[]>(() =>
    cronTaskListRaw.value.map((item) => ({
        id: getTriggerId(item),
        label: getTriggerName(item) || mergedCronTaskI18n.value.unnamedTask,
        extraText: formatRelativeTime(getTriggerLastFireTime(item), {
            today: mergedCronTaskI18n.value.today,
            daysAgo: mergedCronTaskI18n.value.daysAgo,
        }),
    })),
);

/**
 * 判断某个触发器是否「有执行记录」（对齐 webim HasRunHistory 过滤语义）。
 * 优先看成功/失败计数，其次回退看上次触发时间是否存在。
 * 作为前端兜底：即便后端未消费 HasRunHistory 过滤，也能保证侧栏只展示已执行过的任务。
 */
const cronTaskHasRunHistory = (item: AppTriggerSummary): boolean => {
    if (getTriggerSuccessCount(item) + getTriggerFailureCount(item) > 0) return true;
    return !!getTriggerLastFireTime(item);
};

/**
 * 拉取侧边栏「定时任务」分组数据（首屏，PageNumber=1）。
 * 与 CronTaskPanel 共用 DescribeAppTriggerSummaryList，Scope/UserId 复用 cronTaskScope/cronTaskUserId。
 *
 * 筛选规则对齐 smart-webim（store.fetchCronTaskList）：侧边栏只展示
 *   运行中(Status=ENABLED=1) 且 有执行记录(HasRunHistory=true) 的定时任务。
 * FilterList 项使用 proto trpc.adp.common.v2.Filter 的 PascalCase 形态 { Name, ValueList }。
 * 注：全屏管理面板 CronTaskPanel 不套用此筛选，仍展示全部任务。
 */
const fetchCronTaskSummaryList = async () => {
    // 非 claw 模式（或外部禁用）不请求定时任务接口
    if (!cronTaskEnabled.value) return;
    const appId = currentApplicationId.value;
    if (!appId) return;
    try {
        const res = await describeAppTriggerSummaryList(
            {
                PageNumber: 1,
                PageSize: props.cronTaskPageSize,
                Scope: cronTaskScope.value,
                FilterList: [
                    { Name: 'Status', ValueList: [String(AppTriggerStatus.ENABLED)] },
                    { Name: 'HasRunHistory', ValueList: ['true'] },
                ],
                ...(cronTaskUserId.value ? { UserId: cronTaskUserId.value } : {}),
            },
            appId,
        );
        const list: AppTriggerSummary[] = (res as any)?.trigger_list || res?.TriggerList || [];
        // 前端兜底：过滤出「运行中且有执行记录」，防止后端未消费上述 FilterList 时展示不符
        cronTaskListRaw.value = list.filter(
            (item) => getTriggerStatus(item) === AppTriggerStatus.ENABLED && cronTaskHasRunHistory(item),
        );
    } catch (e) {
        console.error('[Index] fetchCronTaskSummaryList failed:', e);
    }
};

/**
 * 侧边栏定时任务执行记录字段归一化（兼容 snake_case / PascalCase），
 * 与 CronTaskExecutionSidebar 中的取值逻辑保持一致。
 */
const getCronLogConversationId = (log: any): string =>
    log?.conversation_id ?? log?.ConversationId ?? log?.session_id ?? log?.SessionId ?? '';
const getCronLogInstanceId = (log: any): string =>
    log?.instance_id ?? log?.InstanceId ?? log?.fire_instance_id ?? log?.FireInstanceId ?? log?.log_id ?? log?.LogId ?? '';
const getCronLogUserId = (log: any): string => log?.user_id ?? log?.UserId ?? '';

/**
 * 选中侧边栏某个定时任务：打开该任务「执行记录」并自动进入最新一条执行记录对应的会话。
 * 对齐 smart-webim selectCronTask → handleSelectCronTask（drawer.fetchAndAutoSelect）：
 *   1. 进入 sidebar 模式（右侧执行记录列表 + 左侧对话并存）；
 *   2. 拉取该任务执行记录列表，自动选中最新一条，用其 session_id 切换会话并加载历史。
 * 注：查看任务「详情」改由列表项 hover 三点菜单「查看详情」触发（handleViewCronTaskDetail）。
 */
const handleSelectCronTask = async (item: SideGroupItem) => {
    const raw = cronTaskListRaw.value.find((t) => getTriggerId(t) === item.id);
    if (!raw) return;
    const appId = currentApplicationId.value;
    if (!appId) return;
    const triggerId = getTriggerId(raw);
    // 高亮当前选中项
    currentCronTaskId.value = item.id;
    // 记录当前面板任务（供右侧执行记录 sidebar 渲染），但此处「先不」打开 cronTaskVisible。
    // 原因：若在拿到会话前就置 cronTaskVisible=true，而 cronTaskSidebarActiveConvId 仍为空，
    // cronTaskSidebarMode=false，会先渲染出全屏 <CronTask> 列表/详情页，产生「闪现」（问题2）。
    // 改为等拉到最新执行记录后，由 handleCronTaskSwitchToChat 一次性设置 convId + visible，
    // 使 cronTaskSidebarMode 直接为 true，直接进入聊天并列右侧执行记录，无中间态闪现。
    cronTaskSidebarTask.value = raw as unknown as TimerTaskSummary;
    const wasVisible = cronTaskVisible.value;
    // 拉取执行记录列表，自动选中最新一条并打开其会话
    try {
        const res: any = await describeAppTriggerRunLogList(
            {
                TriggerId: triggerId,
                PageNumber: 1,
                PageSize: props.cronTaskPageSize,
                Scope: cronTaskScope.value,
                ...(cronTaskUserId.value ? { UserId: cronTaskUserId.value } : {}),
            },
            appId,
        );
        const list = (res as any)?.run_log_list || res?.RunLogList || [];
        const latest = list[0];
        const sessionId = latest ? getCronLogConversationId(latest) : '';
        if (latest && sessionId) {
            filePreviewVisible.value = false;
            cronTaskSidebarActiveLogId.value = getCronLogInstanceId(latest);
            await handleCronTaskSwitchToChat({
                task: raw as unknown as TimerTaskSummary,
                triggerId,
                sessionId,
                logId: getCronLogInstanceId(latest),
                userId: getCronLogUserId(latest),
            });
            // handleCronTaskSwitchToChat 内部会置 cronTaskVisible=true 但不发事件，
            // 这里在从「不可见 → 可见」时补发一次，保持外层 URL / 状态同步。
            if (!wasVisible) emit('cronTaskVisibleChange', true);
        } else {
            // 无执行记录：退回打开该任务详情面板，保证点击有反馈
            openCronTask();
            currentCronTaskId.value = item.id;
            nextTick(() => {
                cronTaskRef.value?.showTaskDetail?.(raw as unknown as TimerTaskSummary);
            });
        }
    } catch (e) {
        console.error('[Index] handleSelectCronTask fetch run log failed:', e);
    }
};

/**
 * 侧边栏定时任务列表项「查看详情」：打开定时任务面板并直接进入该任务详情视图。
 * 对齐 smart-webim view-cron-task-detail → handleViewCronTaskDetail。
 */
const handleViewCronTaskDetail = (item: SideGroupItem) => {
    const raw = cronTaskListRaw.value.find((t) => getTriggerId(t) === item.id);
    // ⚠️ 不能复用 openCronTask：当前若已处于定时任务会话（sidebar 模式，cronTaskVisible 已为 true），
    //   openCronTask 开头 `if (cronTaskVisible.value) return` 会直接早退，sidebar 状态残留，
    //   cronTaskSidebarMode 仍为 true → 全屏 <CronTask>（v-show="cronTaskVisible && !cronTaskSidebarMode"）
    //   持续被隐藏，导致「查看详情」无效、详情页不展示。
    // 这里显式清空 sidebar 关联状态，强制回到全屏详情模式，再 showTaskDetail。
    clearChannelSelection();
    clearConversationSelection();
    cronTaskSidebarActiveConvId.value = '';
    cronTaskSidebarTask.value = null;
    cronTaskSidebarActiveLogId.value = '';
    filePreviewVisible.value = false;
    if (!cronTaskVisible.value) {
        cronTaskVisible.value = true;
        emit('cronTaskVisibleChange', true);
    }
    // 保留 / 重设当前选中项高亮
    currentCronTaskId.value = item.id;
    if (raw) {
        nextTick(() => {
            cronTaskRef.value?.showTaskDetail?.(raw as unknown as TimerTaskSummary);
        });
    }
};

/**
 * 侧边栏定时任务列表项「更多操作」菜单选择分发。
 */
const handleCronTaskMenuSelect = (payload: { value: string; item: SideGroupItem }) => {
    if (payload.value === 'detail') {
        handleViewCronTaskDetail(payload.item);
    }
};

// 应用切换 / userId 就绪后拉取侧边栏定时任务列表
watch(
    [currentApplicationId, cronTaskUserId],
    ([appId]) => {
        if (appId) fetchCronTaskSummaryList();
    },
    { immediate: true },
);

/**
 * 清空渠道选中态：取消远程终端高亮、隐藏"展开列表"入口、关闭渠道会话面板、
 * 恢复输入框可用（channelInputDisabled 依赖 remoteTerminalActiveId）。
 * 用于「新建对话」以及选中普通会话时，确保回到无渠道上下文的干净状态。
 * 注意：不清空 channelConversationUserId 映射——历史加载仍需按会话 Id 判断是否走 CAPI。
 */
const clearChannelSelection = () => {
    remoteTerminalActiveId.value = '';
    remoteTerminalActiveLabel.value = '';
    remoteTerminalActiveChannelId.value = '';
    remoteTerminalActiveUserId.value = '';
    remoteTerminalActiveAgentId.value = '';
    channelDrawerVisible.value = false;
};

/**
 * 重置为「新建对话」态：清除历史对话列表选中态，并通知外层（清除 URL、取消列表高亮、显示欢迎页）。
 * 用于点击远程终端（渠道）/ 定时任务时，让对话区回到与「新建对话」完全一致的欢迎页状态。
 * 注意：列表高亮取 props.currentConversationId，仅清内部 state 不够，必须 emit('createConversation') 让外层同步。
 */
const clearConversationSelection = () => {
    if (useApiMode.value) {
        internalCurrentConversation.value = undefined;
        currentConversationStateKey.value = '';
    }
    emit('createConversation');
};
/** 渠道模式下无对话时禁用输入（对齐 webim：渠道下只能继续已有对话，不可新建） */
const channelInputDisabled = computed(() => !!remoteTerminalActiveId.value && !currentConversationStateKey.value);

/**
 * 当前是否处于"渠道会话继续对话"状态（对齐 webim）
 * 语义：渠道选中 + 已选中一条渠道会话（ConversationId 来自 CAPI 拉取到的 vendor 侧渠道会话）。
 * 用途：透传给 /chat/message 的 IsChannel 字段 → 后端不把该会话落地到本地 chat_conversation 表，
 *      避免 /chat/conversations 侧栏出现由渠道会话延伸出的"新对话"脏数据。
 */
const isChannelConversation = computed(
    () => !!remoteTerminalActiveId.value && !!currentConversationStateKey.value,
);

/**
 * 当前是否处于"定时任务会话继续对话"状态。
 * 语义：定时任务会话（TimerTask session）本质与渠道会话同源——vendor 侧才是权威数据源，
 * 不应在本地 chat_conversation 表落地，否则会污染 /chat/conversations 侧栏列表
 * （用户在定时任务侧边栏继续对话 → 侧栏冒出一条"新对话"）。
 * 判定条件（任一即可）：
 *   1) 外部 URL 语义标记：props.currentConversationCronTask=true（URL 刷新场景）
 *   2) 用户从执行记录进入侧边栏继续对话：cronTaskSidebarActiveConvId 已绑定当前会话
 * 用途：透传给 /chat/message 的 IsChannel 字段 → 后端跳过本地落地（对齐渠道会话行为）。
 */
const isCronTaskConversation = computed(() => {
    const convId = currentConversationStateKey.value;
    if (!convId) return false;
    if (props.currentConversationCronTask && props.currentConversationId === convId) return true;
    if (cronTaskSidebarActiveConvId.value && cronTaskSidebarActiveConvId.value === convId) return true;
    return false;
});

/**
 * 合并渠道会话 / 定时任务会话判断：任一命中即视为"vendor 侧权威会话"，
 * 通过 IsChannel=true 让后端跳过本地 chat_conversation 表落地。
 */
const shouldSkipLocalConversationPersist = computed(
    () => isChannelConversation.value || isCronTaskConversation.value,
);

/** 渠道对话提示文本（对齐 webim ChannelDivider） */
const channelDividerText = computed(() => {
    if (!remoteTerminalActiveId.value || !currentConversationStateKey.value) return '';
    const name = remoteTerminalActiveLabel.value || '渠道';
    return `以上来自${name}渠道，继续对话可共享上下文，但回复可能不会显示在${name}`;
});

/**
 * 渠道选中：
 * 1) 从渠道 raw.spec.UserAgent 中提取 UserId / AgentId（对齐 adp-b2c DescribeConversationList 过滤方式）
 * 2) 通过 CAPI DescribeConversationList 按 UserId 精准过滤拉取会话列表
 * 3) 自动选中最近一条会话（对齐 webim fetchAndAutoSelect），走 handleSelectConversation
 *    → 触发 chatId 变化 → Chat 组件内部 InfiniteLoading 自动加载历史消息
 * 4) 展开面板供用户切换其他会话
 * 5) 若列表为空则保持输入禁用（对齐 webim：渠道下不可新建）
 */
const handleSelectRemoteTerminal = async (item: { id: string; label?: string; raw?: { [key: string]: any } }) => {
    remoteTerminalActiveId.value = item.id;
    remoteTerminalActiveLabel.value = item.label || '';
    // 点击渠道时，先清除历史对话列表的选中态（若该渠道下有会话，会在随后自动选中时覆盖）
    clearConversationSelection();

    // 提取 CAPI ChannelId（暂作语义标记，SDK 未开放不透传）
    const rawChannelId = item.raw?.channelId ?? item.raw?.ChannelId ?? item.id;
    remoteTerminalActiveChannelId.value = rawChannelId !== undefined && rawChannelId !== null ? String(rawChannelId) : '';

    // 从 channel.spec.UserAgent 中提取过滤字段（RemoteTerminalList 已把 ChannelItem 全字段透传到 raw）
    // raw 里的 spec 是 ChannelSpecRaw 原始 CAPI 数据；小写 spec 是 normalizeChannelItem 后的引用。
    // 【方案1】渠道会话按 UserAgent.UserId 过滤——该值在创建时绑成 custom-<账号id>（见 buildChannelUserId）：
    // 稳定唯一、该用户所有渠道共用、与账号自身应用会话隔离。这里直接读取渠道绑定的值即可。
    let spec = (item.raw?.spec || {}) as { [key: string]: any };
    let userAgent = (spec.UserAgent || {}) as { [key: string]: any };
    remoteTerminalActiveUserId.value = String(userAgent.UserId || '');
    remoteTerminalActiveAgentId.value = String(userAgent.AgentId || '');

    // DescribeChannelList 的 spec 可能是摘要、缺 UserAgent；此时拉取渠道完整详情补齐。
    if (!remoteTerminalActiveUserId.value && item.id && currentApplicationId.value) {
        try {
            const detail = await describeChannel({ applicationId: currentApplicationId.value, channelId: Number(item.id) });
            spec = (detail?.spec || {}) as { [key: string]: any };
            userAgent = (spec.UserAgent || {}) as { [key: string]: any };
            remoteTerminalActiveUserId.value = String(userAgent.UserId || '');
            remoteTerminalActiveAgentId.value = String(userAgent.AgentId || remoteTerminalActiveAgentId.value || '');
        } catch (e) {
            console.warn('[handleSelectRemoteTerminal] describeChannel 补齐 UserAgent 失败:', e);
        }
    }
    // 调试日志：确认用于过滤的渠道 UserId（应为 custom-<账号id>）
    console.debug('[handleSelectRemoteTerminal] channel filter:', {
        channelId: remoteTerminalActiveChannelId.value,
        使用的filterUserId: remoteTerminalActiveUserId.value,
        agentId: remoteTerminalActiveAgentId.value,
        rawSpec: spec,
    });

    if (!useApiMode.value) return;

    const applicationId = currentApplicationId.value;
    if (!applicationId) return;

    // 切换渠道时关闭定时任务面板（互斥）
    closeCronTask();
    // 停止当前流（切换渠道 = 切换会话，先打断旧的 SSE）
    const prevState = conversationRuntimeStates.value[currentConversationStateKey.value];
    if (prevState) {
        prevState.abortController?.abort();
        prevState.isChatting = false;
    }

    // 无 ChannelId 时无法按渠道过滤会话（后台确认 DescribeConversationList 按 channel_id 查询），
    // 保持输入禁用即可
    if (!remoteTerminalActiveChannelId.value) {
        console.warn('[handleSelectRemoteTerminal] 渠道无 ChannelId，无法按渠道过滤会话');
        channelDrawerVisible.value = true;
        return;
    }

    try {
        // 后台确认：DescribeConversationList 在原有传参基础上「新增 ChannelId」按渠道过滤
        //（CAPI v2 / X-TC-Version 2026-05-20）。
        const { conversations: capiList } = await describeConversationList(
            {
                AppId: applicationId,
                UserId: remoteTerminalActiveUserId.value || undefined,
                AgentId: remoteTerminalActiveAgentId.value || undefined,
                ChannelId: remoteTerminalActiveChannelId.value,
                Offset: 0,
                Limit: 50,
            },
            applicationId,
            mergedApiDetailConfig.value.describeConversationListApi,
        );
        console.debug('[handleSelectRemoteTerminal] describeConversationList 结果:', {
            channelId: remoteTerminalActiveChannelId.value,
            filterUserId: remoteTerminalActiveUserId.value,
            count: capiList.length,
            list: capiList,
        });

        if (capiList.length > 0) {
            // 自动选中最近一条：按 UpdateTime / CreateTime 排序
            const sorted = [...capiList].sort((a, b) => {
                const ta = Number(a.UpdateTime || a.CreateTime || 0);
                const tb = Number(b.UpdateTime || b.CreateTime || 0);
                return tb - ta;
            });
            const first = sorted[0];
            if (first && first.ConversationId) {
                // 构造 ChatConversation stub：handleSelectConversation 只需 Id + ApplicationId 即可
                const stub: ChatConversation = {
                    Id: first.ConversationId,
                    AccountId: '',
                    ApplicationId: applicationId,
                    Title: (first.Title as string) || '',
                    LastActiveAt: Number(first.UpdateTime || first.CreateTime || 0),
                    CreatedAt: Number(first.CreateTime || 0),
                } as ChatConversation;
                // 登记该会话属于当前渠道，历史消息走 CAPI（带渠道 UserId + Type=1）
                channelConversationUserId.value[first.ConversationId] = remoteTerminalActiveUserId.value;
                // fromChannel=true：保留渠道选中态（remoteTerminalActive* / channelDrawer），
                // 否则默认走 clearChannelSelection() 会把 channelId / userId / drawer 全清掉，
                // 导致 ChannelConversationPanel 的 watch 触发面板清空 + 列表跳走。
                await handleSelectConversation(stub, true);
                // 主动加载首屏历史（对齐 adp-b2c selectConversation → loadConversationHistory）
                await loadChannelHistory(first.ConversationId, remoteTerminalActiveUserId.value, applicationId);
            }
        }
        // 空列表 → 不新建，保持输入禁用，对齐 webim：渠道下只能继续已有对话

        // 对齐 webim fetchAndAutoSelect：选中渠道后自动展开会话列表面板
        channelDrawerVisible.value = true;
    } catch (err) {
        console.error('[handleSelectRemoteTerminal] failed:', err);
    }
};

/**
 * 从 CAPI ChannelItem 中提取该渠道用于会话过滤的三元组（ChannelId / UserId / AgentId）。
 * spec 摘要可能缺 UserAgent，此时通过 describeChannel 拉详情补齐（对齐 handleSelectRemoteTerminal 的兜底逻辑）。
 */
const resolveChannelFilter = async (
    ch: ChannelItem,
    applicationId: string,
): Promise<{ channelId: string; userId: string; agentId: string; label: string } | null> => {
    if (!ch?.channelId) return null;
    let spec: { [key: string]: any } = (ch.spec || {}) as any;
    let userAgent: { [key: string]: any } = (spec.UserAgent || {}) as any;
    let userId = String(userAgent.UserId || '');
    let agentId = String(userAgent.AgentId || '');
    if (!userId && applicationId) {
        try {
            const detail = await describeChannel({ applicationId, channelId: Number(ch.channelId) });
            spec = (detail?.spec || {}) as any;
            userAgent = (spec.UserAgent || {}) as any;
            userId = String(userAgent.UserId || '');
            agentId = String(userAgent.AgentId || agentId);
        } catch (e) {
            console.warn('[resolveChannelFilter] describeChannel 补齐失败:', ch.channelId, e);
        }
    }
    return {
        channelId: String(ch.channelId),
        userId,
        agentId,
        label: ch.channelName || '',
    };
};

/**
 * 【URL 刷新恢复】按 ConversationId 反查所属渠道并恢复渠道会话选中态。
 *
 * 触发时机：URL 中带 conversationId，但该 Id 不在 /chat/conversations（本地库）里，
 *           说明它可能是渠道会话（渠道会话不落地本地表，权威源在 CAPI）。
 *
 * 流程（对齐 handleSelectRemoteTerminal → describeConversationList → handleSelectConversation → loadChannelHistory）：
 *   1) DescribeChannelList 拉出应用下所有 SUCCESS 状态的渠道
 *   2) 遍历渠道，用其 UserAgent(UserId/AgentId) + ChannelId 调 DescribeConversationList
 *   3) 命中目标 conversationId 的即为所属渠道 → 建立渠道选中态
 *      （remoteTerminalActive* + channelConversationUserId 映射）
 *   4) handleSelectConversation(stub, fromChannel=true) 切换到该会话
 *   5) loadChannelHistory 主动拉首屏（渠道历史必须走 CAPI，不能走 /chat/messages）
 *
 * 未命中：不动，保持"欢迎页"状态（避免误标记非渠道会话）。
 */
const restoreChannelConversationById = (
    conversationId: string,
    applicationId: string,
): Promise<boolean> => {
    if (!useApiMode.value || !conversationId || !applicationId) return Promise.resolve(false);
    // 已建立映射 → 无需重复恢复（点渠道时已登记）
    if (channelConversationUserId.value[conversationId]) return Promise.resolve(true);
    // 已有正在进行的 restore → 复用同一 Promise，避免并发重复扫描
    const inflight = channelRestorePending.get(conversationId);
    if (inflight) return inflight;

    const task = (async (): Promise<boolean> => {
        let channelList: ChannelItem[] = [];
        try {
            const res = await describeChannelList({ applicationId, pageSize: 100, agentId: currentAgentId.value || undefined });
            channelList = (res.channelList || []).filter(
                (ch) => ch.connectStatus === ClawChannelStatus.SUCCESS,
            );
        } catch (err) {
            console.warn('[restoreChannelConversationById] describeChannelList 失败:', err);
            return false;
        }
        if (channelList.length === 0) return false;

        for (const ch of channelList) {
            const filter = await resolveChannelFilter(ch, applicationId);
            if (!filter || !filter.channelId) continue;
            try {
                const { conversations: capiList } = await describeConversationList(
                    {
                        AppId: applicationId,
                        UserId: filter.userId || undefined,
                        AgentId: filter.agentId || undefined,
                        ChannelId: filter.channelId,
                        Offset: 0,
                        Limit: 50,
                    },
                    applicationId,
                    mergedApiDetailConfig.value.describeConversationListApi,
                );
                const matched = capiList.find((c: any) => c.ConversationId === conversationId);
                if (!matched) continue;

                // 命中：建立渠道选中态（对齐 handleSelectRemoteTerminal 内部命中分支）
                remoteTerminalActiveId.value = filter.channelId;
                remoteTerminalActiveLabel.value = filter.label;
                remoteTerminalActiveChannelId.value = filter.channelId;
                remoteTerminalActiveUserId.value = filter.userId;
                remoteTerminalActiveAgentId.value = filter.agentId;

                const stub: ChatConversation = {
                    Id: conversationId,
                    AccountId: '',
                    ApplicationId: applicationId,
                    Title: (matched.Title as string) || '',
                    LastActiveAt: Number((matched as any).UpdateTime || (matched as any).CreateTime || 0),
                    CreatedAt: Number((matched as any).CreateTime || 0),
                } as ChatConversation;
                // 关键：先登记 channelConversationUserId，再切换会话。这样 handleInternalLoadMore
                // 后续如果被触发（例如切换过程中的 chatId 变化），会立即走「渠道分支」直接 notifyComplete，
                // 不会误发 /chat/messages。
                channelConversationUserId.value[conversationId] = filter.userId;

                // fromChannel=true：保留渠道选中态，不清空 remoteTerminalActive*
                await handleSelectConversation(stub, true);
                await loadChannelHistory(conversationId, filter.userId, applicationId);
                console.debug('[restoreChannelConversationById] restored', {
                    conversationId,
                    channelId: filter.channelId,
                    userId: filter.userId,
                });
                return true;
            } catch (err) {
                console.warn(
                    '[restoreChannelConversationById] describeConversationList 失败，尝试下一个渠道:',
                    filter.channelId,
                    err,
                );
            }
        }
        return false;
    })();

    channelRestorePending.set(conversationId, task);
    // 任务结束后清理缓存（无论成功/失败），避免长期驻留
    task.finally(() => {
        channelRestorePending.delete(conversationId);
    });
    return task;
};


/**
 * 侧栏删除会话
 * 流程：
 *   1) 保护：进行中会话不允许删（HistoryList 里已过滤，这里再兜底一次）
 *   2) 弹二次确认（避免误操作）
 *   3) 乐观 UI：先从侧栏移除 → 请求后端 → 失败则回滚 + 提示
 *   4) 如果删的是当前会话，清空 chat 主区（视觉上退回到空态）
 *   5) 对 pending 占位（未真正落库的乐观项）：跳过后端调用，本地移除即可
 *   6) 清理 conversationRuntimeStates 中对应 key，避免残留状态影响 chattingConversationIds 计算
 * 非 API 模式：仅向外 emit，由父组件自处理
 */
const handleDeleteConversation = (conversation: ChatConversation) => {
    if (!conversation?.Id) return;

    if (!useApiMode.value) {
        emit('deleteConversation', conversation);
        return;
    }

    // 兜底：进行中会话禁止删除
    if (isConversationChatting(conversation.Id)) {
        MessagePlugin.warning('会话正在进行中，请先停止后再删除');
        return;
    }

    const isPendingPlaceholder = conversation.Id.startsWith('pending-conversation:');
    const title = (conversation.Title || '').slice(0, 40) || '该会话';

    const confirmDialog = DialogPlugin.confirm({
        header: '删除会话',
        body: `确认删除"${title}"？删除后不可恢复。`,
        confirmBtn: { content: '删除', theme: 'danger' },
        cancelBtn: '取消',
        onConfirm: async () => {
            confirmDialog.hide();

            // 乐观 UI：立即从侧栏移除
            // 通过 SideLayout 的 snapshot 拿到当前权威源快照用于失败回滚
            const prevList = sideLayoutRef.value?.snapshot?.() ?? internalConversations.value.slice();
            sideLayoutRef.value?.removeConversation(conversation.Id);

            // 如果删的是当前会话，清空主区状态
            const wasCurrent =
                internalCurrentConversation.value?.Id === conversation.Id ||
                currentConversationStateKey.value === conversation.Id;
            if (wasCurrent) {
                internalCurrentConversation.value = undefined;
                currentConversationStateKey.value = '';
                closeFilePreview();
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
                sideLayoutRef.value?.rollback(prevList);
                if (wasCurrent) {
                    internalCurrentConversation.value = conversation;
                    currentConversationStateKey.value = conversation.Id;
                }
                MessagePlugin.error('删除失败，请稍后重试');
                console.error('删除会话失败:', err);
            }
        },
    });
};

const handleClose = () => {
    emit('close');
};

const handleOverlay = () => {
    emit('overlay', !props.isOverlay);
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
                // 渠道会话 / 定时任务会话：透传 IsChannel，行为对齐 handleInternalSend
                IsChannel: shouldSkipLocalConversationPersist.value,
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
    await handleInternalSend(skipText, [], conversationId, applicationId);
    emit('questionnaireSkip', questionnaire, recordId);
};

// 内部文件上传处理（API 模式）
const handleInternalUploadFile = async (files: File[]) => {
    if (!useApiMode.value) {
        emit('uploadFile', files);
        return;
    }

    if (isUploading.value) return;

    isUploading.value = true;
    emit('uploadStatus', 'uploading');

    const senderRef = mainLayoutRef.value?.getChatRef()?.getSenderRef();

    for (const file of files) {
        const uid = `${Date.now()}-${Math.random().toString(36).slice(2)}-${file.name}`;
        const category = file.type.startsWith('image/') ? 'image' : 'document';

        // 立即添加文件到列表，状态为 uploading，显示 loading
        if (senderRef) {
            senderRef.addFile({
                uid,
                name: file.name,
                url: '',
                size: file.size,
                type: file.type,
                category,
                status: 'uploading',
            });
        }

        try {
            const response = await uploadFile(file, currentApplicationId.value, mergedApiDetailConfig.value.uploadApi, chatMode.value);
            if (senderRef && response) {
                const fileUrl = response.Url || response.url;
                senderRef.updateFile(uid, {
                    url: fileUrl,
                    status: 'done',
                });

                // standard 模式下，非图片文件需要调用实时文档解析获取 doc_id
                if (chatMode.value === 'standard' && category === 'document' && mergedApiDetailConfig.value.fileParseApi) {
                    const extName = file.name.split('.').pop() || '';
                    try {
                        const parseResult = await parseFile({
                            ApplicationId: currentApplicationId.value,
                            FileName: file.name,
                            FileType: extName,
                            FileUrl: fileUrl,
                            CosUrl: response.CosUrl || response.cos_url || '',
                            CosBucket: response.CosBucket || response.cos_bucket || '',
                            ETag: response.ETag || response.e_tag || '',
                            CosHash: response.CosHash || response.cos_hash || '',
                            Size: String(file.size || 0),
                        }, mergedApiDetailConfig.value.fileParseApi);

                        if (parseResult && parseResult.doc_id && parseResult.doc_id !== '0') {
                            senderRef.updateFile(uid, { docId: parseResult.doc_id });
                        }
                    } catch (parseError) {
                        console.warn('文档解析失败，将使用 FileUrl 模式:', parseError);
                    }
                }
            }
        } catch (error) {
            if (senderRef) {
                senderRef.removeFile(uid);
            }
            const uploadErrorText = mergedSenderI18n.value.uploadError;
            MessagePlugin.error(uploadErrorText);
            emit('message', MessageCode.FILE_UPLOAD_FAILED, uploadErrorText);
        }
    }

    isUploading.value = false;
    emit('uploadStatus', 'done');
    emit('uploadFile', files);
};

// 记录上一次的 ID 值，用于判断变化
let prevConvId: string | undefined = undefined;
/**
 * 已尝试过「渠道会话恢复」的 conversationId 集合。
 * 防止 watch 反复触发同一个 convId 的 DescribeChannelList/DescribeConversationList 全表扫描。
 * 场景：一次 restore 成功后，channelConversationUserId 会被填充，restoreChannelConversationById
 * 自己也会跳过；但失败时若不做防抖，watch 后续依赖（apps / conversations）任何变化都会重放。
 */
const channelRestoreAttempted = new Set<string>();

// 监听外部传入的 currentApplicationId 和 currentConversationId 变化
watch(
    [
        () => props.currentApplicationId,
        () => props.currentConversationId,
        () => props.currentConversationChannel,
        () => props.currentConversationCronTask,
        () => actualApplications.value,
        () => actualConversations.value
    ],
    async ([appId, convId, isChannel, isCronTask, apps, conversations]) => {
        // 处理应用 ID 变化
        if (appId && apps.length > 0) {
            const foundApp = apps.find(app => app.ApplicationId === appId);
            if (foundApp && foundApp.ApplicationId !== internalCurrentApplication.value?.ApplicationId) {
                internalCurrentApplication.value = foundApp;
            }
        }

        // 处理会话 ID 变化（普通会话：本地 /chat/conversations 列表命中即可切换）
        // 渠道会话跳过本地匹配（不在本地列表里），交由下面的 restoreChannelConversationById 处理
        if (!isChannel && convId && conversations.length > 0) {
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
        } else if (!convId && prevConvId) {
            // ID 从有值变为空时，清空当前会话
            internalCurrentConversation.value = undefined;
            currentConversationStateKey.value = '';
        }

        // 【URL 刷新场景】渠道会话恢复：
        //   URL 语义已明确该 conv 是渠道会话（外层通过 currentConversationChannel prop 传入 true，
        //   来源于 `/:appId/channel/:convId` 路由）→ 直接触发渠道恢复流程：
        //     1) DescribeChannelList 拉出应用下所有 SUCCESS 状态渠道
        //     2) 逐个 DescribeConversationList 找到属于哪个渠道
        //     3) 建立 remoteTerminalActive* + channelConversationUserId 映射
        //     4) handleSelectConversation(stub, fromChannel=true) 切换到该会话
        //     5) loadChannelHistory 主动拉首屏历史
        //   条件：
        //     - useApiMode（API 模式才有渠道概念）
        //     - convId + appId 都有
        //     - 内部尚未选中该 conv（防重复）
        //     - 该 convId 未曾尝试过恢复（防抖，避免 watch 频繁重放）
        if (
            useApiMode.value
            && isChannel
            && convId
            && appId
            && currentConversationStateKey.value !== convId
            && !channelRestoreAttempted.has(convId)
        ) {
            channelRestoreAttempted.add(convId);
            void restoreChannelConversationById(convId, appId);
        }

        // 【URL 刷新场景】定时任务会话恢复（同 channel 机制，简化：无需反查渠道列表）
        // ⚠️ 时序守卫：必须等应用列表加载完且能匹配到当前 appId 再执行恢复。
        //   原因：CronTask / CronTaskExecutionSidebar 的 :application-id 绑的是内部
        //   computed currentApplicationId（= actualCurrentApplication?.ApplicationId），
        //   而 actualCurrentApplication 依赖 internalCurrentApplication，后者是本 watch
        //   在 `if (appId && apps.length > 0)` 分支里赋值的。
        //   若此处不等 apps.length > 0 就直接触发 `cronTaskRef.showTaskDetail(...)`，
        //   CronTaskDetail watch(props.task, immediate:true) 会立刻用空 applicationId
        //   调 DescribeAppTrigger / DescribeAppTriggerRunLogList，后端 500 报
        //   "application_id not found"。
        //   本 watch 深依赖 actualApplications，apps 加载后会再次 fire，届时守卫通过再恢复。
        //   注意：channelRestoreAttempted.add 也必须放在守卫之后，避免首次空 apps 就把
        //   convId 标脏，导致后续 apps 就绪时被 has(convId) 挡住无法进入。
        if (
            useApiMode.value
            && isCronTask
            && convId
            && appId
            && apps.length > 0
            && apps.some(app => app.ApplicationId === appId)
            && currentConversationStateKey.value !== convId
            && !channelRestoreAttempted.has(convId)
        ) {
            channelRestoreAttempted.add(convId);
            channelConversationUserId.value[convId] = channelConversationUserId.value[convId] || 'anonymous';
            const stub: ChatConversation = {
                Id: convId,
                ApplicationId: appId,
            } as ChatConversation;
            internalCurrentConversation.value = stub;
            currentConversationStateKey.value = convId;
            setConversationApplicationId(convId, appId);
            clearChannelSelection();
            // 主动拉首屏历史
            void (async () => {
                try {
                    const resp = await fetchConversationDetailV2(
                        {
                            ConversationId: convId,
                            Limit: 50,
                            Type: 5,
                            UserId: channelConversationUserId.value[convId],
                            RecordQueryDirection: 1,
                            IsChannel: true,
                        },
                        appId,
                        mergedApiDetailConfig.value.describeConversationMessageListApi,
                    );
                    const data = resp?.Response || ({} as NonNullable<typeof resp>['Response']);
                    const records: Record[] = (data.Records && data.Records.length)
                        ? data.Records
                        : groupChannelMessagesToRecords((data.Messages as any[]) || [], convId);
                    records.forEach((r) => { (r as any)._isChannelHistory = true; });
                    if (records.length > 0) {
                        await hydrateReferences(records, { applicationId: appId });
                    }
                    setConversationRecords(convId, records, appId);
                    nextTick(() => {
                        mainLayoutRef.value?.getChatRef()?.backToBottom();
                    });
                } catch (e) {
                    console.error('[CronTaskWatch] restore failed:', e);
                }
            })();

            // URL 刷新场景：自动进入右侧 sidebar 模式（对齐企微机器人体验）
            // 若 URL 携带了 triggerId，把 stub task 交给 <CronTaskExecutionSidebar>
            // 触发其 watch → fetchLogs 拉取 DescribeAppTriggerRunLogList
            if (props.enableCronTask) {
                cronTaskSidebarActiveConvId.value = convId;
                if (!cronTaskVisible.value) {
                    cronTaskVisible.value = true;
                    filePreviewVisible.value = false;
                    emit('cronTaskVisibleChange', true);
                }
                const triggerId = props.currentConversationCronTaskTriggerId;
                if (triggerId) {
                    // ⚠️ 修复：sidebar 模式下真正渲染执行记录的是 <CronTaskExecutionSidebar>，
                    //   它读取的是 `cronTaskSidebarTask` 而不是 <CronTask>。以前只调
                    //   `cronTaskRef.showTaskDetail(...)`，实际是给被 v-show 隐藏的 <CronTask>
                    //   下的 <CronTaskDetail> 发请求，用户可见的 sidebar 里 props.task
                    //   一直是 null → triggerId 为空 → fetchLogs 短路返回 [] → 显示"暂无运行日志"。
                    //   这里必须把 stub 塞给 sidebar 的 :task 绑定源。
                    //   getEntityId 依次读 TriggerId → timer_id/TimerId，两者都塞上保证兼容
                    //   AppTrigger + 旧 TimerTask。
                    cronTaskSidebarTask.value = {
                        TriggerId: triggerId,
                        TimerId: triggerId,
                    } as any;
                    // ⚠️ 选中态修复（Bug2）：刷新后 currentCronTaskId 为空，导致侧栏定时任务
                    //   下拉/分组列表 activeId === item.id 恒 false、高亮丢失。这里用 URL 的
                    //   triggerId（= cronTaskItems 各项 id 来源）回填，恢复选中态。
                    //   即便此刻 cronTaskItems 尚未加载完，待 fetchCronTaskSummaryList 拉到后
                    //   active 匹配即生效。
                    currentCronTaskId.value = triggerId;
                    // ⚠️ 高亮当前项修复：URL 携带 logId 时同步给 sidebar，避免刷新后"没有选中当前项"。
                    // sidebar 通过 :active-log-id 判定 .active 高亮，若为空则整个列表无选中态。
                    // 空字符串等同"无高亮"，兼容仅有 triggerId 无 logId 的旧 URL。
                    cronTaskSidebarActiveLogId.value = props.currentConversationCronTaskLogId || '';
                }
            }
        }

        // 更新上一次的值
        prevConvId = convId;
    },
    { immediate: true }
);

// 【URL logId 变化 → sidebar 高亮同步】
// 场景：定时任务会话已恢复完毕（上面的恢复 watch 因 currentConversationStateKey 守卫不再重入），
// 但用户切换到另一条 log（例如点击其它执行记录，导致 URL 中 logId query 变化）时，
// 本文件里 handleCronTaskSwitchToChat 会主动更新 cronTaskSidebarActiveLogId；
// 反过来，若外部（URL 前进/后退、或父层主动改写 query）先驱动了 props.currentConversationCronTaskLogId，
// 需要在这里把它同步到 sidebar，否则 sidebar 高亮会滞后于 URL。
// 兼容"仅有 triggerId 无 logId"（旧格式）：空字符串等同无高亮，不影响功能。
watch(
    () => props.currentConversationCronTaskLogId,
    (logId) => {
        if (!props.enableCronTask) return;
        if (!props.currentConversationCronTask) return;
        // 只在 sidebar 已启用（即已进入定时任务会话）时同步，避免误清普通场景下的高亮态
        if (!cronTaskSidebarTask.value) return;
        cronTaskSidebarActiveLogId.value = logId || '';
    },
);

// 【刷新 / 父层异步解析场景：triggerId 补齐 → sidebar 拉取执行记录】
// 页面刷新时父层从 URL 解析 currentConversationCronTaskTriggerId 可能晚于会话恢复 watch 执行，
// 导致会话恢复分支里 triggerId 为空、cronTaskSidebarTask 未设，执行记录列表拉不到。
// 这里在 triggerId 到位后补设 stub，触发 <CronTaskExecutionSidebar> 重新 fetchLogs 拿 list。
watch(
    () => props.currentConversationCronTaskTriggerId,
    (triggerId) => {
        if (!props.enableCronTask || !triggerId) return;
        // 仅在确实处于定时任务会话（或 sidebar 已激活）时补设，避免污染普通会话
        if (!props.currentConversationCronTask && !cronTaskSidebarActiveConvId.value) return;
        // 选中态修复（Bug2）：triggerId 到位后回填 currentCronTaskId，恢复侧栏下拉/分组列表高亮
        currentCronTaskId.value = triggerId;
        if (!cronTaskSidebarTask.value) restoreCronTaskSidebarTask();
    },
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
        await Promise.all([
            loadApplications(),
            loadConversations(),
        ]);
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
    notifyLoaded: () => mainLayoutRef.value?.notifyLoaded(),
    notifyComplete: () => mainLayoutRef.value?.notifyComplete(),
    openFilePreview,
    closeFilePreview,
    getFilePreviewRef: () => filePreviewLayoutRef.value,
    openCronTask,
    closeCronTask,
    isCronTaskVisible: () => cronTaskVisible.value,
});
</script>

<template>
    <TLayout class="page-container">
        <TContent class="content">
            <!-- 移动端毛玻璃遮罩 -->
            <div 
                v-if="isSidePanelOverlay && sidebarVisible" 
                class="mobile-overlay" 
                @click="handleToggleSidebar"
            ></div>
            <SideLayout 
                ref="sideLayoutRef"
                :isMobile="isMobile"
                :visible="sidebarVisible"
                :applications="actualApplications"
                :currentApplicationId="currentApplicationId"
                :currentApplication="actualCurrentApplication"
                :conversations="actualConversations"
                :useInternalFetch="useApiMode"
                :conversationListApi="mergedApiDetailConfig.conversationListApi"
                :currentConversationId="currentConversationId"
                :chattingConversationIds="chattingConversationIds"
                :userAvatarUrl="actualUser?.avatarUrl"
                :userAvatarName="actualUser?.avatarName"
                :userName="actualUser?.name"
                :theme="theme"
                :languageOptions="languageOptions"
                :isSidePanelOverlay="isSidePanelOverlay"
                :maxAppLen="maxAppLen"
                :i18n="props.sideI18n"
                :showCronTaskAction="cronTaskEnabled"
                :cronTaskItems="cronTaskItems"
                :currentCronTaskId="currentCronTaskId"
                :showCronTaskList="cronTaskEnabled"
                :showRemoteTerminalList="isClawMode"
                :currentRemoteTerminalId="remoteTerminalActiveId"
                :sideActionActiveKey="cronTaskVisible ? 'cron-task' : ''"
                :channelSettingUserId="currentUserId"
                :channelSettingAgentId="currentAgentId"
                :chatMode="chatMode"
                :language="language"
                @toggleSidebar="handleToggleSidebar"
                @selectApplication="handleSelectApplication"
                @selectConversation="handleSelectConversation"
                @deleteConversation="handleDeleteConversation"
                @toggleTheme="emit('toggleTheme')"
                @changeLanguage="(key) => emit('changeLanguage', key)"
                @logout="emit('logout')"
                @userClick="emit('userClick')"
                @conversationsChange="handleSideConversationsChange"
                @conversationsLoaded="handleSideConversationsLoaded"
                @fetchError="handleSideFetchError"
                @sideAction="handleSideAction"
                @selectCronTask="handleSelectCronTask"
                @cronTaskMenuSelect="handleCronTaskMenuSelect"
                @selectRemoteTerminal="handleSelectRemoteTerminal"
            >
                <template #sider-logo v-if="(logoUrl || logoTitle) || $slots['sider-logo']">
                    <slot name="sider-logo">
                        <LogoArea v-if="logoUrl || logoTitle" :logoUrl="logoUrl" :title="logoTitle" />
                    </slot>
                </template>
            </SideLayout>
            <div class="main-area" :class="{ 'main-area--sidebar': cronTaskSidebarMode }">
            <MainLayout
                v-show="!cronTaskVisible || cronTaskSidebarMode"
                class="main-area__chat"
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
                :showSidebarToggle="!sidebarVisible"
                :aiWarningText="aiWarningText"
                :i18n="props.chatI18n"
                :chatItemI18n="props.chatItemI18n"
                :senderI18n="props.senderI18n"
                :useInternalRecord="useApiMode"
                :asrUrlApi="mergedApiDetailConfig.asrUrlApi"
                :enableVoiceInput="enableVoiceInput"
                :isUploading="isUploading"
                :channelInputDisabled="channelInputDisabled"
                :channelDividerText="channelDividerText"
                :isOverlay="props.isOverlay"
                :enableSkills="props.enableSkills"
                :skillsSpaceId="resolvedSpaceId"
                :skillsApplicationId="skillsAppId"
                :suggestionApi="mergedApiDetailConfig.suggestionListApi"
                @toggleSidebar="handleToggleSidebar"
                @createConversation="handleCreateConversation"
                @close="handleClose"
                @send="handleInternalSend"
                @stop="handleInternalStop"
                @loadMore="handleInternalLoadMore"
                @rate="handleInternalRate"
                @share="handleInternalShare"
                @copy="handleInternalCopy"
                @uploadFile="handleInternalUploadFile"
                @uploadStatus="(status: 'uploading' | 'done') => emit('uploadStatus', status)"
                @startRecord="emit('startRecord')"
                @stopRecord="emit('stopRecord')"
                @message="(code: MessageCode, message: string) => emit('message', code, message)"
                @conversationChange="(conversationId: string) => emit('conversationChange', conversationId)"
                @widgetEvent="handleInternalWidgetEvent"
                @questionnaireSubmit="handleInternalQuestionnaireSubmit"
                @questionnaireSkip="handleInternalQuestionnaireSkip"
            >
                <template #header-actions>
                    <!-- 渠道模式：展开列表 + 收起（隐藏定时任务按钮，互斥） -->
                    <Tooltip v-if="remoteTerminalActiveId && !channelDrawerVisible" :content="'展开列表'" destroyOnClose showArrow theme="default">
                        <span class="header-action-btn" @click="channelDrawerVisible = true; closeCronTask()">
                            <CustomizedIcon remote name="basic_time_line" :theme="theme" />
                        </span>
                    </Tooltip>
                    <!-- 非渠道模式：定时任务（仅 claw 模式显示） -->
                    <Tooltip v-if="!remoteTerminalActiveId && cronTaskEnabled" :content="mergedSideI18n.cronTask" destroyOnClose showArrow theme="default">
                        <span
                            class="header-action-btn"
                            :class="{ 'header-action-btn--active': cronTaskVisible }"
                            @click="handleCronTaskHeaderIconClick"
                        >
                            <CustomizedIcon remote name="basic_time_line" :theme="theme" />
                        </span>
                    </Tooltip>
                    <Tooltip v-if="!isMobile && chatMode !== 'standard'" :content="mergedFilePreviewI18n.openFileList" destroyOnClose showArrow theme="default">
                        <span class="open-file-list-btn" @click="toggleFilePreview">
                            <CustomizedIcon name="open_file_list" :theme="theme" />
                        </span>
                    </Tooltip>
                </template>
                <template #header-overlay-content v-if="showOverlayButton || $slots['header-overlay-content']">
                    <slot name="header-overlay-content">
                        <CustomizedIcon class="header-overlay-icon" v-if="showOverlayButton" name="overlay" :theme="theme" @click="handleOverlay"/>
                    </slot>
            </template>
                <template #header-close-content v-if="showCloseButton || $slots['header-close-content']">
                    <slot name="header-close-content">
                        <CustomizedIcon class="header-overlay-icon" v-if="showCloseButton" name="logout_close" :theme="theme" @click="handleClose"/>
                    </slot>
                </template>
            </MainLayout>
            <CronTask
                v-if="cronTaskEnabled"
                v-show="cronTaskVisible && !cronTaskSidebarMode"
                ref="cronTaskRef"
                class="cron-task-overlay"
                :application-id="currentApplicationId"
                :space-id="resolvedSpaceId"
                :scope="cronTaskScope"
                :user-id="cronTaskUserId"
                :theme="theme"
                :language="props.language"
                :i18n="cronTaskI18n"
                :page-size="cronTaskPageSize"
                :poll-interval="cronTaskPollInterval"
                :create-conversation-text="mergedChatI18n.createConversation"
                @run-and-view="(task: TimerTask | TimerTaskSummary) => emit('cronTaskRunAndView', task)"
                @optimize-prompt="(content: string) => emit('cronTaskOptimizePrompt', content)"
                @refresh="() => fetchCronTaskSummaryList()"
                @switch-to-chat="handleCronTaskSwitchToChat"
                @toggle-sidebar="handleToggleSidebar"
                @create-conversation="handleCreateConversation"
                @action-done="(action: string, task: TimerTask | TimerTaskSummary) => { emit('cronTaskActionDone', action, task); fetchCronTaskSummaryList(); }"
            />
            <!-- 定时任务执行历史 sidebar：仅在 sidebar 模式下渲染，样式对齐 ChannelConversationPanel -->
            <CronTaskExecutionSidebar
                v-if="cronTaskEnabled && cronTaskSidebarMode"
                :visible="cronTaskSidebarMode"
                :task="cronTaskSidebarTask"
                :application-id="currentApplicationId"
                :scope="cronTaskScope"
                :user-id="cronTaskUserId"
                :language="props.language"
                :i18n="cronTaskI18n"
                :active-log-id="cronTaskSidebarActiveLogId"
                :page-size="cronTaskPageSize"
                :poll-interval="cronTaskPollInterval"
                :is-mobile="isMobile"
                :theme="theme"
                @select-log="handleCronTaskSwitchToChat"
                @close="closeCronTask"
            />
            </div>
            <!-- 渠道会话列表面板：作为 .content 的 flex 子项，从右侧推开（对齐 FilePreviewLayout 的位置） -->
            <ChannelConversationPanel
                :visible="channelDrawerVisible"
                :application-id="currentApplicationId"
                :user-id="remoteTerminalActiveUserId"
                :agent-id="remoteTerminalActiveAgentId"
                :channel-id="remoteTerminalActiveChannelId"
                :channel-label="remoteTerminalActiveLabel"
                :describe-conversation-list-api="mergedApiDetailConfig.describeConversationListApi"
                :active-conversation-id="currentConversationId"
                :is-mobile="isMobile"
                :theme="theme"
                :language="props.language"
                @select="handleChannelConversationSelect"
                @close="channelDrawerVisible = false"
            />
            <FilePreviewLayout
                ref="filePreviewLayoutRef"
                :visible="filePreviewVisible"
                :conversationId="currentConversationId"
                :applicationId="currentApplicationId"
                :i18n="mergedFilePreviewI18n"
                @close="closeFilePreview"
            />
        </TContent>
    </TLayout>
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
