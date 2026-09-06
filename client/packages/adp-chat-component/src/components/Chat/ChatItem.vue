<!-- 聊天消息项组件，支持 Markdown、深度思考、操作按钮等 -->
<script setup lang="tsx">
import { ref, computed, watch } from 'vue';
import type { Content, Message, QuoteInfo, Record as RecordV2, Reference as ReferenceV2, FileInfo } from '../../model/chat-v2';
import type {
    Questionnaire,
    QuestionnaireAnswer,
    QuestionnaireSubmitItem,
} from '../../model/chat-v2';
import { ScoreValue } from '../../model/chat-v2';
import type { CommonLayoutProps, ChatItemI18n, ChatI18n, ChatMode } from '../../model/type';
import { commonLayoutPropsDefaults, defaultChatItemI18n, defaultChatI18n, defaultChatI18nEn } from '../../model/type';
import {  ChatItem as TChatItem } from '@tdesign-vue-next/chat';
import { Tooltip, Loading as TLoading, Link as TLink, Dialog as TDialog } from 'tdesign-vue-next';
import OptionCard from '../Common/OptionCard.vue';
import MdContent from '../Common/MdContent.vue';
import MessageFileCard from '../Common/MessageFileCard.vue';
import AssistantFileCard from '../Common/AssistantFileCard.vue';
import WidgetActionTag from '../Common/WidgetActionTag.vue';
import CustomizedIcon from '../CustomizedIcon.vue';
import CollapsibleMessageGroup from './CollapsibleMessageGroup.vue';
import type { CollapseKind } from './CollapsibleMessageGroup.vue';
import ClassifyTag from './ClassifyTag.vue';
import ClassifySummary from './ClassifySummary.vue';
import { widgetContentToMarkdown } from '../../utils/mergeRecord-v2';
import {
    pickQuestionnaireContent,
    normalizeQuestionnaire,
    buildDefaultAnswers,
    buildSubmitAnswers,
    buildQuestionnairePayload,
    countAnswered,
    buildSummaryItems,
} from '../../utils/questionnaire';
import type { NormalizedSkill } from '../../model/skills';

interface Props extends CommonLayoutProps {
    /** 当前聊天记录项 */
    item: RecordV2;
    /** 当前项的索引 */
    index: number;
    /** 是否为最后一条消息 */
    isLastMsg?: boolean;
    /** 是否正在加载 */
    loading: boolean;
    /** 是否为流式加载 */
    isStreamLoad: boolean;
    /** 是否显示操作按钮 */
    showActions?: boolean;
    /** 国际化文本 */
    i18n?: ChatItemI18n;
    /** Chat 折叠组等的国际化文本（透传给 CollapsibleMessageGroup） */
    chatI18n?: ChatI18n;
    /** 当前语言标识（如 'zh-CN'、'en-US'），用于 widget 国际化 */
    language?: string;
    /** 聊天模式：claw-简化模式, standard-标准模式 */
    mode?: ChatMode;
    /** 已注册 skills 列表（用于把 user 消息中的 @skill:name 还原为蓝色 chip） */
    mentionSkills?: NormalizedSkill[];
    /** 已注册 knowledgeBase 列表 */
    mentionKnowledge?: NormalizedSkill[];
    /** 已注册 tools 列表 */
    mentionTools?: NormalizedSkill[];
    /** 已注册 connectors 列表 */
    mentionConnectors?: NormalizedSkill[];
    /**
     * 是否为只读环境（如分享落地页）。
     * 为 true 时反问澄清卡片禁止访客操作。
     */
    readonly?: boolean;
    /**
     * 当前 Record 之后是否已存在新一轮用户输入。
     * 由父级根据完整会话列表计算并下传，用于判定反问澄清是否「已过期」：
     * 用户没有提交/跳过澄清就继续对话时，澄清卡应折叠为「已澄清 0 个问题」且不可再提交。
     */
    hasSubsequentUserRecord?: boolean;
    /**
     * 历史回显：当前 assistant Record 之后紧邻的一条用户消息是纯文本「跳过」。
     *
     * 用户主动点击「跳过」时，前端上行的是纯文本消息（对齐 webim `assist-side.onQuestionnaireSkip`），
     * 页面刷新后仅凭 hasSubsequentUserRecord 只能得到「过期」语义。此标记让 ChatItem 直接
     * 把它当作「已提交（=跳过）」处理，与 webim `_isQuestionnaireSkippedInHistory` 行为对齐。
     */
    historyQuestionnaireSkipped?: boolean;
}

const props = withDefaults(defineProps<Props>(), {
    isLastMsg: false,
    showActions: true,
    language: 'zh-CN',
    mode: 'standard',
    ...commonLayoutPropsDefaults,
    i18n: () => ({}),
    chatI18n: () => ({}),
    mentionSkills: () => [],
    mentionKnowledge: () => [],
    mentionTools: () => [],
    mentionConnectors: () => [],
    readonly: false,
    hasSubsequentUserRecord: false,
    historyQuestionnaireSkipped: false,
});

// 合并默认值和传入值
const i18n = computed(() => ({
    ...defaultChatItemI18n,
    ...props.i18n
}));

const emit = defineEmits<{
    (e: 'resend', relatedRecordId: string | undefined, recordId: string | undefined): void;
    (e: 'share', recordIds: string[]): void;
    (e: 'rate', record: RecordV2, score: typeof ScoreValue[keyof typeof ScoreValue]): void;
    (e: 'copy', rowtext: string | undefined, content: string | undefined, type: string): void;
    (e: 'sendMessage', message: string): void;
    /** widget 事件（用于与 SSE/对话流交互） */
    (e: 'widgetEvent', event: CustomEvent, widgetRunId: string, widgetId: string, recordId: string): void;
    /** 反问澄清提交：payload 为可直接上行的 Questionnaire 内容体 */
    (e: 'questionnaireSubmit', questionnaire: Questionnaire, recordId: string): void;
    /** 反问澄清跳过：questionnaire 为原始内容体，宿主可据此上行「已跳过」或直接丢弃 */
    (e: 'questionnaireSkip', questionnaire: Questionnaire, recordId: string): void;
}>();

// 响应式变量
type ChatRecord = RecordV2 & { Score?: typeof ScoreValue[keyof typeof ScoreValue] };
type QuoteInfoLike = QuoteInfo;
type ReferenceLike = ReferenceV2;

const record = ref(props.item as ChatRecord);
const expandStatus = ref(false);
const referenceDialogVisible = ref(false);
const activeReference = ref<ReferenceLike | null>(null);

// 监听 props.item 变化，同步到 record
// 这是必要的，因为 placeholder 消息的 RecordId 会在 SSE 返回后被更新
watch(
    () => props.item,
    (newItem) => {
        record.value = newItem as ChatRecord;
    },
    { deep: true }
);

const isFromSelf = computed(() => {
    return record.value.Role === 'user';
});

const messages = computed(() => record.value.Messages ?? []);

const primaryMessage = computed(() => {
    const list = messages.value;
    if (list.length === 0) return undefined;
    if (isFromSelf.value) {
        return list.find((msg) => msg.Type === 'question') ?? list[0];
    }
    return list.find((msg) => msg.Type === 'reply');
});

const extractMessageText = (message?: Message) => {
    if (!message?.Contents?.length) return '';
    return message.Contents
        .map((content) => {
            const parts: string[] = [];
            
            // 先处理文本内容（如果有）
            if (content.Text) {
                parts.push(content.Text);
            }
            
            // 处理 widget 类型内容，转换为 Markdown 代码块
            if (content.Type === 'widget' && content.Widget) {
                const widgetMarkdown = widgetContentToMarkdown(content);
                if (widgetMarkdown) {
                    parts.push(widgetMarkdown);
                }
            }
            
            return parts.join('');
        })
        .filter((text) => text.length > 0)
        .join('\n');
};

const displayText = computed(() => {
    const text = extractMessageText(primaryMessage.value);
    if (text) return text;
    // 错误态兜底（对齐 webim）：后端可能只下发 Status=failed + StatusDesc="回复失败"
    // 而 contents 为空。webim 的 SseV2ProtocolHandler 会把 StatusDesc 写成消息文本
    // （findedMsg.text = message.StatusDesc）展示给用户；这里同样以 StatusDesc 作为
    // 错误文案 fallback，优先消息级、其次 Record 级。两者皆空时返回空串 → 整条隐藏。
    if (isError.value && !isFromSelf.value) {
        return primaryMessage.value?.StatusDesc?.trim() || record.value.StatusDesc?.trim() || '';
    }
    return '';
});

const reasoningMessages = computed(() => {
    return messages.value.filter((msg) => msg.Type === 'thought');
});

/**
 * 根据消息类型和工具名称返回折叠分类
 * 支持 tool_call、task_execution、thought 类型
 */
function getCollapseKindForMsg(msg: Message): CollapseKind | '' {
    if (msg.Type === 'thought') return 'thought';
    if (msg.Type !== 'tool_call' && msg.Type !== 'task_execution') return '';
    const toolName = msg.ExtraInfo?.ToolName || '';
    if (['websearch', 'web_search'].includes(toolName)) return 'search';
    if (['read', 'grep', 'glob'].includes(toolName)) return 'read';
    if (['write', 'edit'].includes(toolName)) return 'write';
    return 'tools';
}

/**
 * 渲染项类型
 */
interface RenderItem {
    kind: 'collapse' | 'reply';
    collapseKind?: CollapseKind;
    messages?: Message[];
    message?: Message;
}

/**
 * 将 Record.Messages 拆分为渲染项列表：
 * - 连续的 tool_call/thought 归入同一个折叠组
 * - reply 独立渲染
 * 无论 mode 是 claw 还是 standard，只要有 tool_call 就启用分组渲染
 */
const renderItems = computed<RenderItem[]>(() => {
    if (isFromSelf.value) return [];

    const list = messages.value;
    if (list.length === 0) return [];

    const hasToolCall = list.some(m => m.Type === 'tool_call' || m.Type === 'task_execution');
    if (!hasToolCall) return [];

    const items: RenderItem[] = [];
    let collapseBuffer: Message[] = [];

    const flushCollapse = () => {
        if (collapseBuffer.length > 0) {
            items.push({
                kind: 'collapse',
                collapseKind: 'mixed',
                messages: [...collapseBuffer],
            });
            collapseBuffer = [];
        }
    };

    for (const msg of list) {
        const collapseKind = getCollapseKindForMsg(msg);

        if (collapseKind === '') {
            // reply / question / recommendation / notice — 不可折叠
            if (msg.Type === 'reply') {
                flushCollapse();
                items.push({ kind: 'reply', message: msg });
            }
            // 其他类型暂不处理
        } else if (collapseKind === 'thought' && !hasToolCall) {
            // 没有 tool_call 时，thought 不进入折叠组（由原有 reasoning 逻辑处理）
            continue;
        } else {
            // 可折叠消息：tool_call 或 thought（有 tool_call 时）
            collapseBuffer.push(msg);
        }
    }

    // 最后一组折叠消息
    flushCollapse();

    return items;
});

/**
 * 是否使用分组渲染模式（有 tool_call/task_execution 消息时启用，不限制 mode）
 * 确保历史对话和 SSE 对话保持一致的渲染规则
 */
const useClawRender = computed(() => {
    if (isFromSelf.value) return false;
    return messages.value.some(m => m.Type === 'tool_call' || m.Type === 'task_execution');
});

/**
 * 判断最后一个折叠组是否处于流式状态
 */
const isLastCollapseStreaming = computed(() => {
    if (!useClawRender.value) return false;
    if (!props.isLastMsg || !props.isStreamLoad) return false;
    const items = renderItems.value;
    if (items.length === 0) return false;
    return items[items.length - 1]!.kind === 'collapse';
});

/**
 * 判断是否任务终止（最后是折叠组，无后续 reply，且 Record 已完成）
 */
const isTerminated = computed(() => {
    if (!useClawRender.value) return false;
    if (record.value.Status === 'processing') return false;
    const items = renderItems.value;
    if (items.length === 0) return false;
    const lastItem = items[items.length - 1]!;
    if (lastItem.kind !== 'collapse') return false;
    // 有错误状态时视为终止
    return record.value.Status === 'error' || record.value.Status === 'failed';
});

/** 当前 Record 是否为错误状态 */
const isError = computed(() => {
    return record.value.Status === 'error' || record.value.Status === 'failed';
});

const reasoningContents = computed(() => {
    // claw 模式下，thought 已在折叠组中渲染，不再显示独立的 reasoning 面板
    if (useClawRender.value) return [];
    return reasoningMessages.value
        .map((msg) => extractMessageText(msg))
        .filter((text) => text.length > 0);
});

const collectFromMessageContents = <T,>(message: Message | undefined, picker: (content: Content) => T[] | undefined): T[] => {
    const values: T[] = [];
    for (const content of message?.Contents ?? []) {
        const picked = picker(content);
        if (picked?.length) {
            values.push(...picked);
        }
    }
    return values;
};

const optionCards = computed(() => {
    return collectFromMessageContents(primaryMessage.value, (content) => content.OptionCards ?? []);
});

const fileAttachments = computed<FileInfo[]>(() => {
    const files: FileInfo[] = [];
    const seen = new Set<string>();
    const msgs = isFromSelf.value ? [primaryMessage.value] : [primaryMessage.value];
    for (const msg of msgs) {
        if (!msg?.Contents?.length) continue;
        for (const content of msg.Contents) {
            if (content.Type === 'file' && content.File) {
                const key = content.File.FileUrl || content.File.FileName || '';
                if (key && seen.has(key)) continue;
                if (key) seen.add(key);
                files.push(content.File);
            }
        }
    }
    return files;
});

/** 图片 MIME 类型前缀 */
const IMAGE_TYPE_RE = /^image\//i
/** 通过文件名判断图片 */
const IMAGE_EXT_RE = /\.(jpg|jpeg|png|bmp|webp|gif)$/i

const imageAttachments = computed<FileInfo[]>(() => {
    return fileAttachments.value.filter(f =>
        IMAGE_TYPE_RE.test(f.FileType || '') || IMAGE_EXT_RE.test(f.FileName || '')
    );
});

const docAttachments = computed<FileInfo[]>(() => {
    return fileAttachments.value.filter(f =>
        !IMAGE_TYPE_RE.test(f.FileType || '') && !IMAGE_EXT_RE.test(f.FileName || '')
    );
});

/** 点击图片附件，新窗口打开预览 */
const openImagePreview = (file: FileInfo) => {
    const url = file.FileUrl || file.Url;
    if (url) window.open(url, '_blank');
};

const quoteInfos = computed<QuoteInfoLike[]>(() => {
    const source = useClawRender.value ? lastReplyMessage.value : primaryMessage.value;
    return collectFromMessageContents(source, (content) => content.QuoteInfos ?? []);
});

const references = computed<ReferenceLike[]>(() => {
    const source = useClawRender.value ? lastReplyMessage.value : primaryMessage.value;
    return collectFromMessageContents(source, (content) => content.References ?? []);
});

/**
 * claw 模式下的最后一条 reply 消息（用于提取 references 等）
 */
const lastReplyMessage = computed(() => {
    if (!useClawRender.value) return primaryMessage.value;
    const replies = messages.value.filter(m => m.Type === 'reply');
    return replies.length > 0 ? replies[replies.length - 1] : undefined;
});

const isFinal = computed(() => {
    return record.value.Status !== 'processing';
});

/**
 * assistant 消息是否有可展示内容。
 * 判定维度：正文文本 / 工具调用分组 / 图片·文件附件 / 深度思考 / 引用 / 选项卡 / 反问澄清。
 * 用户消息不受此限制（恒为 true）。
 *
 * 注意：**不要**因为 `isError` 就无脑返回 true。错误态只是给气泡换个红边框/红字色的
 * 视觉皮肤（.chat-item--error），需要内部真实有可展示内容（如错误文案 / renderItems）
 * 才有意义；否则会渲染成一个只有 1px `#ffd8d4` 红边框、内部空空的盒子——即用户看到的
 * "一条莫名其妙的橙色线条"。
 *
 * 反问澄清（questionnaire）计入可展示内容（对齐 webim messageHasVisibleOutput）：
 * AI 反问那轮可能没有正文文本，questionnaire 卡片（ClassifyTag/ClassifySummary）是
 * 唯一内容——分享落地页等场景若漏掉此维度，整条气泡会被 shouldRenderItem 隐藏。
 */
const hasAssistantContent = computed(() => {
    if (isFromSelf.value) return true;
    if (useClawRender.value) return renderItems.value.length > 0;
    return !!displayText.value
        || reasoningContents.value.length > 0
        || imageAttachments.value.length > 0
        || docAttachments.value.length > 0
        || optionCards.value.length > 0
        || references.value.length > 0
        || !!questionnaireData.value;
});

/**
 * 是否渲染整条消息气泡（含操作按钮）。
 * - 用户消息：默认始终渲染；但「反问澄清答案回放」（仅含 questionnaire 的 user record）整条隐藏；
 * - assistant 流式生成中的最后一条：渲染（可能正在产出，需展示 loading / 逐步内容）；
 * - 其余 assistant：仅在「有可展示内容」时渲染，避免出现空的 md-content-container 与孤立操作按钮。
 */
const shouldRenderItem = computed(() => {
    if (isQuestionnaireAnswerRecord.value) return false;
    if (isFromSelf.value) return true;
    if (props.isStreamLoad && props.isLastMsg) return true;
    return hasAssistantContent.value;
});

/**
 * 回复时间（从 ExtraInfo.StartTime 提取）
 * - 今天：显示 hh:mm:ss
 * - 今年过去日期：显示 M月D日
 * - 过去年份：显示 YYYY年M月D日
 */
const replyTime = computed(() => {
    const startTime = record.value.ExtraInfo?.StartTime;
    if (!startTime) return '';
    const ts = Number(startTime);
    if (!ts) return '';
    const date = new Date(ts);
    const now = new Date();
    const isToday = date.getFullYear() === now.getFullYear() &&
        date.getMonth() === now.getMonth() &&
        date.getDate() === now.getDate();
    const isThisYear = date.getFullYear() === now.getFullYear();

    if (isToday) {
        const hours = String(date.getHours()).padStart(2, '0');
        const minutes = String(date.getMinutes()).padStart(2, '0');
        const seconds = String(date.getSeconds()).padStart(2, '0');
        return `${hours}:${minutes}:${seconds}`;
    } else if (isThisYear) {
        return `${date.getMonth() + 1}月${date.getDate()}日`;
    } else {
        return `${date.getFullYear()}年${date.getMonth() + 1}月${date.getDate()}日`;
    }
});

/**
 * 判断用户消息是否是 widget action 类型
 * widget action 类型的消息应该显示为 "已进行操作" 样式，而不是原始 JSON 内容
 */
const isWidgetAction = computed(() => {
    if (!isFromSelf.value) return false;
    const message = primaryMessage.value;
    if (!message?.Contents?.length) return false;
    // 检查是否有 widget_action 类型的 content
    return message.Contents.some(content => content.Type === 'widget_action');
});

/**
 * 用户消息是否为「反问澄清答案回放」——应整条隐藏。
 *
 * 后端会把「用户提交澄清答案」的上行消息回放为 role:user 的历史消息，contents 里
 * 只有 questionnaire 类型（text 为空）。若按普通用户消息渲染会得到一个空气泡（甚至
 * 撑出 toolbar），澄清结果已由前一条 assistant reply 上的「已澄清 N 个问题」摘要
 * 展示，无需重复渲染 → 对齐 webim `assist-chat.vue._isQuestionnaireOnlyUserMsg`：
 * 整条跳过。
 *
 * 严格条件（避免误伤）：
 *   1. contents 必须非空
 *   2. 至少 1 个 questionnaire 类型 content
 *   3. 其余 content 必须是空 text（无 text/markdown 文本），不能含 file/widget/widget_action 等
 */
const isQuestionnaireAnswerRecord = computed(() => {
    if (!isFromSelf.value) return false;
    const contents = primaryMessage.value?.Contents;
    if (!contents?.length) return false;
    let hasQuestionnaire = false;
    for (const content of contents) {
        const type = content.Type;
        if (type === 'questionnaire') {
            hasQuestionnaire = true;
            continue;
        }
        if (type === 'text') {
            // 允许空 text 与 questionnaire 共存（占位内容）
            if (!content.Text) continue;
            return false;
        }
        // 其他任何非空 content（file/widget/widget_action/option_cards 等）→ 不视为纯回放
        return false;
    }
    return hasQuestionnaire;
});

const recordScore = computed(() => record.value.Score);

const canRate = computed(() => {
    return record.value.ExtraInfo?.CanRating !== false;
});

/**
 * 复制内容到剪贴板
 */
async function copyContent(event: any, content: string | undefined, type: string): Promise<void> {
    let rowtext: string | undefined;
    const container = event?.target as HTMLElement;
    const markdownElements = container?.closest('.t-chat__content')?.querySelectorAll('.markdown-body');
    rowtext = markdownElements && markdownElements.length > 0 
        ? markdownElements[markdownElements.length - 1]?.textContent || undefined 
        : undefined;
    emit('copy', rowtext, content, type);
}

/**
 * 判断是否已评分
 * 注意：服务端可能返回 null/undefined/0，这些都视为"未评分"
 */
const isRated = () => {
    const score = recordScore.value;
    return score !== undefined && score !== null && score !== ScoreValue.Unknown;
};

/**
 * 对消息进行评分（点赞/踩）
 */
const rate = async (target: RecordV2, score: typeof ScoreValue[keyof typeof ScoreValue]) => {
    if (!canRate.value || isRated()) return;
    emit('rate', target, score);
};

/**
 * 分享消息
 */
const share = async (target: RecordV2) => {
    let shareList = [target.RecordId]
    if (target.RelatedRecordId) {
        shareList.push(target.RelatedRecordId)
    }
    emit('share', shareList);
};

/**
 * 渲染推理模块的头部自定义内容
 */
const renderHeader = () => {
    const endText = expandStatus.value ? i18n.value.deepThinkingFinished : i18n.value.deepThinkingExpand;
    return (
        <div class="collapsed-thinking-text">
            <CustomizedIcon 
                remote 
                name="arrow_up_small_line" 
                showHoverBg={false} 
                size="xs" 
                theme={props.theme}
                class={['thinking-arrow-icon', { 'thinking-arrow--expanded': expandStatus.value }]}
            />
            <span>{endText}</span>
        </div>
    );
};

/**
 * 渲染推理内容
 */
const renderReasoningContent = (contents: string[]) => {
    if (contents.length === 0) return <div></div>;
    return (
        <div>
            {contents.map((content, index) => (
            <MdContent 
                content={content} 
                role="system" 
                theme={props.theme} 
                mode={props.mode}
                language={props.language}
                key={index} 
            />
            ))}
        </div>
    );
};

const renderReasoning = () => {
    if (reasoningContents.value.length === 0) {
        return false;
    }
    return {
        collapsed: props.isLastMsg && !props.isStreamLoad,
        expandIcon: () => null,
        expandIconPlacement: 'right' as const,
        onExpandChange: (e: boolean) => {
            expandStatus.value = e;
        },
        collapsePanelProps: {
            expandIcon: false,
            header: renderHeader(),
            content: renderReasoningContent(reasoningContents.value),
        },
    };
};

const getReferenceUrl = (reference: ReferenceLike) => {
    return reference.Url || reference.DocRefer?.Url || reference.WebSearchRefer?.Url;
};

const handleSendMessage = (message: string) => {
    emit('sendMessage', message);
};

/**
 * 处理 widget 事件
 * @param event - widget 事件
 * @param widgetRunId - widget run id
 * @param widgetId - widget id
 */
const handleWidgetEvent = (event: CustomEvent, widgetRunId: string, widgetId: string) => {
    // 向上传递事件，附带当前消息的 recordId
    emit('widgetEvent', event, widgetRunId, widgetId, record.value.RecordId || '');
};

/* ───────────────────────── 反问澄清（questionnaire） ─────────────────────────
 * 四种状态：
 *   待澄清   —— 未提交且未过期，渲染可交互的 ClassifyTag
 *   已澄清   —— 用户已提交/跳过，渲染 ClassifySummary 摘要
 *   已过期   —— 未提交但后续已有新一轮用户输入，渲染摘要且标题为「已澄清 0 个问题」并默认折叠
 *   只读     —— 分享落地页等场景，ClassifyTag 禁用交互
 * 行为与 smart-webim 保持一致。
 */

/** 澄清相关的 i18n（复用 ChatI18n 的中英默认值 + 外部覆盖） */
const clarifyI18n = computed(() => {
    const defaults = props.language?.startsWith('en') ? defaultChatI18nEn : defaultChatI18n;
    return { ...defaults, ...props.chatI18n };
});

/** 本地提交状态：提交/跳过后立即切换视图，不等待服务端回写 */
const questionnaireSubmitted = ref(false);
/**
 * 提交瞬间的本地答案缓存。
 * 必须有：服务端把 answers 回写到 Contents 之前，摘要若直接读 Contents 会误显示为「跳过」。
 */
const localQuestionnaireAnswers = ref<QuestionnaireAnswer[] | null>(null);

/** 从 assistant 的 reply 消息中提取原始澄清内容体 */
const rawQuestionnaire = computed<Questionnaire | null>(() => {
    if (isFromSelf.value) return null;
    for (const message of messages.value) {
        const found = pickQuestionnaireContent(message.Contents);
        if (found) return found;
    }
    return null;
});

/** 归一化后的澄清数据 */
const questionnaireData = computed(() =>
    normalizeQuestionnaire(rawQuestionnaire.value, clarifyI18n.value.clarifyTitle)
);

/** 历史消息中是否已存在答案（刷新后回显用） */
const hasHistoryAnswers = computed(() => (questionnaireData.value?.answers.length ?? 0) > 0);

/** 是否已提交（本地提交 或 历史已有答案 或 历史紧邻「跳过」文本回显） */
const isQuestionnaireSubmitted = computed(
    () => questionnaireSubmitted.value || hasHistoryAnswers.value || props.historyQuestionnaireSkipped
);

/**
 * 是否「已过期」：未提交，但该轮之后已经出现新一轮用户输入。
 * 已显式提交/跳过的不算过期。
 */
const isQuestionnaireExpired = computed(() => {
    if (!questionnaireData.value) return false;
    if (isQuestionnaireSubmitted.value) return false;
    return props.hasSubsequentUserRecord;
});

/** 是否渲染摘要卡（已提交或已过期） */
const showQuestionnaireSummary = computed(
    () => Boolean(questionnaireData.value) && (isQuestionnaireSubmitted.value || isQuestionnaireExpired.value)
);

/** 是否渲染可交互卡（未提交且未过期） */
const showQuestionnaireTag = computed(
    () => Boolean(questionnaireData.value) && !isQuestionnaireSubmitted.value && !isQuestionnaireExpired.value
);

/** 已澄清个数（过期视为 0；跳过时为 0，不兜底为题目总数） */
const questionnaireAnsweredCount = computed(() =>
    countAnswered(questionnaireData.value, {
        localAnswers: localQuestionnaireAnswers.value,
        isExpired: isQuestionnaireExpired.value,
        isSubmitted: isQuestionnaireSubmitted.value,
    })
);

/** 摘要卡标题，如「已澄清 2 个问题」 */
const questionnaireSummaryTitle = computed(() =>
    clarifyI18n.value.clarifySummaryTitle.replace('{count}', String(questionnaireAnsweredCount.value))
);

/** 摘要卡内容 */
const questionnaireSummaryItems = computed(() =>
    buildSummaryItems(
        questionnaireData.value,
        clarifyI18n.value.clarifySkip,
        localQuestionnaireAnswers.value
    )
);

/** 历史回显：把服务端 answers 映射为 ClassifyTag 的 defaultAnswers */
const questionnaireDefaultAnswers = computed(() =>
    buildDefaultAnswers(questionnaireData.value, isQuestionnaireSubmitted.value)
);

/** 提交：先写本地缓存与已提交态，再上抛可直接发送的 Questionnaire */
const handleQuestionnaireSubmit = (result: QuestionnaireSubmitItem[]) => {
    // 幂等：避免重复提交导致发送两次 Query
    if (isQuestionnaireSubmitted.value) return;
    const raw = rawQuestionnaire.value;
    if (!raw) return;

    const answers = buildSubmitAnswers(result);
    // 顺序重要：先缓存答案，再切换状态，保证摘要首帧即为正确内容
    localQuestionnaireAnswers.value = answers;
    questionnaireSubmitted.value = true;

    emit('questionnaireSubmit', buildQuestionnairePayload(raw, answers), record.value.RecordId || '');
};

/** 跳过：同样置为已提交态，摘要展示为「已澄清 0 个问题」 */
const handleQuestionnaireSkip = () => {
    if (isQuestionnaireSubmitted.value) return;
    const raw = rawQuestionnaire.value;
    if (!raw) return;
    localQuestionnaireAnswers.value = [];
    questionnaireSubmitted.value = true;
    emit('questionnaireSkip', raw, record.value.RecordId || '');
};

// 切换到另一条 Record（组件复用）时重置澄清本地状态，避免状态串台
watch(
    () => record.value.RecordId,
    () => {
        questionnaireSubmitted.value = false;
        localQuestionnaireAnswers.value = null;
    }
);

const openReferenceDialog = (reference: ReferenceLike) => {
    activeReference.value = reference;
    referenceDialogVisible.value = true;
};

const isSliceReference = (reference: ReferenceLike) => {
    return reference.Type === 2 && Boolean(reference.PageContent || reference.OrgData);
};

const getReferenceId = (reference: ReferenceLike) => {
    return reference.Id || reference.DocRefer?.ReferenceId || reference.ReferBizId || reference.DocRefer?.ReferBizId;
};

const getReferenceTitle = (reference: ReferenceLike) => {
    return reference.DocRefer?.DocName || reference.DocName || reference.Name || '未命名来源';
};

const getReferenceContent = (reference: ReferenceLike) => {
    return reference.PageContent || reference.OrgData || '';
};

const getReferenceMeta = (reference: ReferenceLike) => {
    const meta: string[] = [];
    if (reference.PageInfos && reference.PageInfos.length > 0) {
        meta.push(`P${reference.PageInfos.join(', ')}`);
    }
    if (reference.SheetInfos && reference.SheetInfos.length > 0) {
        meta.push(reference.SheetInfos.join(', '));
    }
    return meta.join(' · ');
};

const getReferencePreview = (reference: ReferenceLike) => {
    return getReferenceContent(reference).replace(/\s+/g, ' ').trim();
};

const referenceDialogTitle = computed(() => {
    if (!activeReference.value) {
        return i18n.value.referenceSlice;
    }
    return getReferenceTitle(activeReference.value);
});
</script>

<template>
    <!-- Widget action 回放：无可展示文本，显示「已进行操作」占位。
         反问澄清答案回放（questionnaire-only user record）走 shouldRenderItem=false 整条隐藏，
         对齐 webim `_isQuestionnaireOnlyUserMsg`，避免出现空气泡与"已进行操作"误显。 -->
    <div v-if="isFromSelf && isWidgetAction" class="widget-action-row">
        <WidgetActionTag :text="i18n.actionPerformed" />
    </div>
    <!-- 聊天项组件 -->
    <TChatItem v-else-if="shouldRenderItem" animation="skeleton" :role="isFromSelf ? 'user' : 'assistant'" :text-loading="false"
        :reasoning="renderReasoning()" >
        <!-- 内容插槽 -->
        <template #content>
            <div v-if="isLastMsg && isStreamLoad && !displayText && reasoningContents.length === 0 && !useClawRender" class="loading-container">
                <TLoading  size="small">
                    <template #text>
                        <span class="thinking-text">
                            {{ `${i18n.thinking}...` }}
                        </span>
                    </template>
                    <template #indicator>
                        <CustomizedIcon class="thinking-icon" name="thinking" :theme="theme" nativeIcon :showHoverBg="false"/>
                    </template>
                </TLoading>
            </div>
            <div v-else :class="{ 'chat-item--error': isError && !isFromSelf }">
                <!-- 普通用户消息 -->
                <div v-if="isFromSelf" class="user-message">
                    <!-- 图片附件：独立于文字气泡展示（claw 模式下已在文本中渲染） -->
                    <div v-if="imageAttachments.length > 0 && mode !== 'claw'" class="image-attachments">
                        <img
                            v-for="(file, idx) in imageAttachments"
                            :key="'img-' + idx"
                            :src="file.FileUrl || file.Url"
                            :alt="file.FileName"
                            class="msg-inline-image"
                            @click="openImagePreview(file)"
                        />
                    </div>
                    <!-- 文件附件：card 形式展示（claw 模式下已在文本中渲染） -->
                    <div v-if="docAttachments.length > 0 && mode !== 'claw'" class="file-attachments">
                        <MessageFileCard
                            v-for="(file, idx) in docAttachments"
                            :key="'doc-' + idx"
                            :file="file"
                            :theme="theme"
                        />
                    </div>
                    <MdContent 
                        :content="displayText" 
                        role="user" 
                        :theme="theme" 
                        :mode="mode"
                        :quoteInfos="quoteInfos"
                        :language="language"
                        :recordId="item.RecordId"
                        :enableScale="isMobile"
                        :mentionSkills="mentionSkills"
                        :mentionKnowledge="mentionKnowledge"
                        :mentionTools="mentionTools"
                        :mentionConnectors="mentionConnectors"
                        @widgetEvent="handleWidgetEvent"
                    />
                    <span>
                    <CustomizedIcon remote :size="isMobile ? 'm' : 's'" v-if="showActions && !isMobile" class="control-icon copy-icon" name="basic_copy_line" :theme="theme"
                        @click="(e: any) => copyContent(e, displayText, 'user')" />
                    <CustomizedIcon remote :size="isMobile ? 'm' : 's'" v-if="showActions && !isMobile" class="control-icon share-icon" name="basic_forward_line" :theme="theme"
                        @click="share(item)" />
                    </span>
                </div>
                <!-- claw 模式分组渲染：tool_call 折叠 + reply 独立展示 -->
                <div v-else-if="useClawRender" class="claw-render">
                    <template v-for="(renderItem, rIdx) in renderItems" :key="'ri-' + rIdx">
                        <CollapsibleMessageGroup
                            v-if="renderItem.kind === 'collapse'"
                            :kind="renderItem.collapseKind || 'mixed'"
                            :messages="renderItem.messages || []"
                            :isStreaming="isLastCollapseStreaming && rIdx === renderItems.length - 1"
                            :isTerminated="isTerminated && rIdx === renderItems.length - 1"
                            :theme="theme"
                            :language="language"
                            :i18n="chatI18n"
                        />
                        <MdContent
                            v-else-if="renderItem.kind === 'reply'"
                            :content="extractMessageText(renderItem.message)"
                            role="assistant"
                            :theme="theme"
                            :mode="mode"
                            :language="language"
                            :recordId="item.RecordId"
                            :disable="!isLastMsg"
                            :enableScale="isMobile"
                            @widgetEvent="handleWidgetEvent"
                        />
                    </template>
                </div>
                <MdContent 
                    v-else-if="displayText" 
                    :content="displayText" 
                    role="assistant" 
                    :theme="theme" 
                    :mode="mode"
                    :quoteInfos="quoteInfos"
                    :language="language"
                    :recordId="item.RecordId"
                    :disable="!isLastMsg"
                    :enableScale="isMobile"
                    @widgetEvent="handleWidgetEvent"
                />
                <!-- assistant 图片附件 -->
                <div v-if="!isFromSelf && imageAttachments.length > 0 && mode === 'claw'" class="image-attachments">
                    <img
                        v-for="(file, idx) in imageAttachments"
                        :key="'assistant-img-' + idx"
                        :src="file.FileUrl || file.Url"
                        :alt="file.FileName"
                        class="msg-inline-image"
                        @click="openImagePreview(file)"
                    />
                </div>
                <!-- assistant 文件附件卡片：仅 claw 模式展示，standard 模式下文件链接已在 markdown 中渲染 -->
                <AssistantFileCard
                    v-if="!isFromSelf && docAttachments.length > 0 && mode === 'claw'"
                    :files="docAttachments"
                    :theme="theme"
                />
                <!-- 反问澄清：待澄清渲染可交互卡，已澄清/已过期渲染摘要卡。
                     放在 useClawRender / displayText 两条渲染路径之后，
                     使有无 tool_call 的对话都能正常展示。 -->
                <ClassifyTag
                    v-if="showQuestionnaireTag"
                    :title="questionnaireData?.title"
                    :questions="questionnaireData?.questions || []"
                    :defaultAnswers="questionnaireDefaultAnswers"
                    :disabled="readonly"
                    :language="language"
                    :i18n="chatI18n"
                    @submit="handleQuestionnaireSubmit"
                    @skip="handleQuestionnaireSkip"
                />
                <ClassifySummary
                    v-else-if="showQuestionnaireSummary"
                    :title="questionnaireSummaryTitle"
                    :items="questionnaireSummaryItems"
                    :defaultCollapsed="questionnaireAnsweredCount <= 0"
                />
                <OptionCard v-if="optionCards && optionCards.length" :cards="optionCards" :sendMessage="handleSendMessage" />
                <div class="references-container"
                    v-if="references && references.length > 0 && isFinal">
                    <span class="title">{{ i18n.references }}: </span>
                    <ol class="reference-list">
                        <li
                            v-for="(reference, idx) in references"
                            :key="`${getReferenceId(reference) || getReferenceUrl(reference) || getReferenceTitle(reference) || idx}-${idx}`"
                            class="reference-list__item"
                        >
                            <button
                                v-if="isSliceReference(reference)"
                                type="button"
                                class="reference-slice__trigger"
                                @click="openReferenceDialog(reference)"
                            >
                                <div class="reference-slice__header">
                                    <span class="reference-slice__name">{{ getReferenceTitle(reference) }}</span>
                                </div>
                                <div v-if="getReferenceMeta(reference)" class="reference-slice__meta">
                                    {{ getReferenceMeta(reference) }}
                                </div>
                                <div class="reference-slice__preview">
                                    {{ getReferencePreview(reference) }}
                                </div>
                            </button>
                            <TLink
                                v-else-if="getReferenceUrl(reference)"
                                class="reference-link"
                                theme="primary"
                                :href="getReferenceUrl(reference)"
                                target="_blank"
                                rel="noopener noreferrer"
                            >
                                {{ getReferenceTitle(reference) }}
                            </TLink>
                            <span v-else class="reference-link">
                                {{ getReferenceTitle(reference) }}
                            </span>
                            <div v-if="getReferenceMeta(reference)" class="reference-link__meta">
                                {{ getReferenceMeta(reference) }}
                            </div>
                        </li>
                    </ol>
                </div>
            </div>
        </template>
        <!-- 操作按钮插槽 -->
        <template #actions v-if="showActions" >
            <div v-show="!isStreamLoad || !isLastMsg" class="actions-container" :class="{ isMobile: isMobile }">
                <Tooltip :content="i18n.copy" destroyOnClose showArrow theme="default">
                    <CustomizedIcon remote :size="isMobile ? 'm' : 's'" class="control-icon copy-icon icon" name="basic_copy_line" :theme="theme"
                        @click="(e: any) => copyContent(e, displayText, 'assistant')" />
                </Tooltip>
                <Tooltip :content="i18n.replay" destroyOnClose showArrow theme="default">
                    <CustomizedIcon remote :size="isMobile ? 'm' : 's'" class="control-icon icon" name="basic_refresh_line" :theme="theme"
                        @click="emit('resend', item.RelatedRecordId, item.RecordId)" />
                </Tooltip>
                <Tooltip :content="i18n.share" destroyOnClose showArrow theme="default">
                    <CustomizedIcon remote :size="isMobile ? 'm' : 's'" class="control-icon share-icon icon" name="basic_forward_line" :theme="theme" @click="share(item)" />
                </Tooltip>
                <Tooltip :content="i18n.good" destroyOnClose showArrow theme="default">
                    <CustomizedIcon remote
                        :size="isMobile ? 'm' : 's'"
                        :class="{ disabled: !canRate || (isRated() && recordScore !== ScoreValue.Like), 'not-allowed': isRated() || !canRate }"
                        class="control-icon icon"
                        :name="recordScore === ScoreValue.Like ? 'basic_thumbsup_fill' : 'basic_thumbsup_line'"
                        :theme="theme" @click="rate(item, ScoreValue.Like)" />
                </Tooltip>
                <Tooltip :content="i18n.bad" destroyOnClose showArrow theme="default">
                    <CustomizedIcon remote
                        :size="isMobile ? 'm' : 's'"
                        :class="{ disabled: !canRate || (isRated() && recordScore !== ScoreValue.Dislike), 'not-allowed': isRated() || !canRate }"
                        class="control-icon icon"
                        :name="recordScore === ScoreValue.Dislike ? 'basic_thumbsdown_fill' : 'basic_thumbsdown_line'"
                        :theme="theme" @click="rate(item, ScoreValue.Dislike)" />
                </Tooltip>
                <Tooltip :content="i18n.aiDisclaimer" destroyOnClose showArrow theme="default">
                    <CustomizedIcon remote :size="isMobile ? 'm' : 's'" class="control-icon icon" name="basic_tips_line" :theme="theme" />
                </Tooltip>
                <span v-if="replyTime" class="actions-divider"></span>
                <span v-if="replyTime" class="actions-time">{{ replyTime }}</span>
            </div>
        </template>
    </TChatItem>
    <TDialog
        v-model:visible="referenceDialogVisible"
        :header="referenceDialogTitle"
        :footer="false"
        :width="isMobile ? '92%' : '80%'"
        top="5vh"
        destroy-on-close
    >
        <div v-if="activeReference" class="reference-dialog">
            <div v-if="getReferenceMeta(activeReference)" class="reference-dialog__meta">
                {{ getReferenceMeta(activeReference) }}
            </div>
            <div v-if="getReferenceUrl(activeReference)" class="reference-dialog__link">
                <TLink theme="primary" :href="getReferenceUrl(activeReference)" target="_blank" rel="noopener noreferrer">
                    {{ i18n.openSource }}
                </TLink>
            </div>
            <div class="reference-dialog__content">
                <MdContent
                    :content="getReferenceContent(activeReference)"
                    role="assistant"
                    :theme="theme"
                    :mode="mode"
                    :language="language"
                />
            </div>
        </div>
    </TDialog>
</template>

<style scoped>
/* ── 错误消息 ── */
.chat-item--error {
    border: 1px solid var(--td-error-color-2, #ffd8d4);
    padding: 0 var(--td-size-5);
    background-color: var(--td-error-color-1, #fff0ed);
    border-radius: var(--td-radius-medium);
}

.chat-item--error :deep(.md-content-container) {
    background-color: transparent;
    font-size: 13px;
    color: var(--td-error-color-6, #da4449);
}

/* ── Widget action 独立行 ── */
.widget-action-row {
    width: 100%;
    display: flex;
    align-items: center;
    justify-content: center;
    margin-bottom: var(--td-comp-margin-l);
}

/* ── Claw 模式分组渲染 ── */
.claw-render {
    display: flex;
    flex-direction: column;
    gap: var(--td-size-3);
    width: 100%;
}

/* ── 用户消息 ── */
.user-message {
    display: flex;
    flex-direction: column;
    align-items: flex-end;
}

.user-message .copy-icon,
.user-message .share-icon {
    opacity: 0;
    transition: opacity 0.15s ease;
    cursor: pointer;
}

.user-message:hover .copy-icon,
.user-message:hover .share-icon {
    opacity: 1;
}

/* ── 操作按钮 ── */
.control-icon {
    padding: 3px;
    margin-right: 4px;
    border-radius: var(--td-radius-default);
    transition: background-color 0.15s ease, opacity 0.15s ease;
}

.control-icon:hover {
    background-color: var(--td-bg-color-container-hover);
}

.copy-icon {
    padding-left: 0;
}

.icon.disabled {
    opacity: 0.2;
    cursor: not-allowed;
    pointer-events: none;
}

.icon.not-allowed {
    cursor: not-allowed;
}

/* ── 操作按钮容器 ── */
.actions-container {
    display: flex;
    align-items: center;
    list-style: none;
    padding: var(--td-size-2) 0;
    overflow: hidden;
    position: relative;
    gap: 0;
}

.actions-divider {
    width: 1px;
    height: 14px;
    background: var(--td-component-stroke);
    margin: 0 var(--td-size-3);
    flex-shrink: 0;
}

.actions-time {
    font-size: 11px;
    color: var(--td-text-color-placeholder);
    line-height: var(--td-line-height-body-small);
    margin-left: var(--td-size-2);
    white-space: nowrap;
    opacity: 0.65;
}

/* ── 深度思考折叠 ── */
.collapsed-thinking-text {
    color: var(--td-text-color-placeholder);
    display: flex;
    align-items: center;
    gap: var(--td-size-2);
    width: 100%;
    padding: 3px var(--td-size-4);
    border-radius: var(--td-radius-default);
    cursor: pointer;
    font-family: 'SF Mono', 'Monaco', 'Menlo', 'Consolas', monospace;
    font-size: var(--td-font-size-body-small);
    font-weight: 400;
    line-height: 18px;
    transition: background 0.15s ease;
}

.collapsed-thinking-text:hover {
    background: var(--td-bg-color-container-hover);
}

:deep(.t-collapse-panel__header) {
    padding: 0 !important;
}

:deep(.t-collapse-panel__icon) {
    display: none;
}

.thinking-arrow-icon {
    transform: rotate(180deg);
    transition: transform 0.2s ease;
    flex-shrink: 0;
}

.thinking-arrow--expanded {
    transform: rotate(90deg);
}

/* ── 加载状态 ── */
.loading-container {
    padding: 0;
}

.thinking-text {
    color: var(--td-text-color-secondary);
    font-size: var(--td-font-size-body-medium);
    margin-left: var(--td-size-2);
}

.thinking-icon {
    animation: rotate 2s linear infinite;
    width: var(--td-comp-size-xs);
    height: var(--td-comp-size-xs);
    padding: 0;
}

/* ── 引用来源 ── */
.references-container {
    margin: var(--td-size-4) var(--td-size-6) var(--td-size-6) var(--td-size-6);
    padding: 12px 14px;
    background: var(--td-bg-color-container-hover);
    border-radius: var(--td-radius-medium);
}

.references-container .title {
    color: var(--td-text-color-placeholder);
    display: inline-block;
    margin-bottom: var(--td-size-3);
    font-size: var(--td-font-size-body-small);
    font-weight: 500;
}

.reference-list {
    margin: 0;
    padding-left: 16px;
}

.reference-list__item + .reference-list__item {
    margin-top: var(--td-size-3);
}

.reference-slice__trigger {
    width: 100%;
    display: block;
    text-align: left;
    padding: var(--td-size-4) var(--td-size-5);
    border: 1px solid var(--td-component-stroke);
    border-radius: var(--td-radius-medium);
    background: var(--td-bg-color-container);
    cursor: pointer;
    transition: border-color 0.15s ease, box-shadow 0.15s ease;
}

.reference-slice__trigger:hover {
    border-color: var(--td-brand-color-3);
    box-shadow: 0 1px 4px rgba(0, 0, 0, 0.04);
}

.reference-slice__header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--td-size-4);
}

.reference-slice__name {
    color: var(--td-text-color-primary);
    font-weight: 600;
    font-size: 13px;
}

.reference-slice__meta,
.reference-link__meta {
    color: var(--td-text-color-placeholder);
    font-size: 11px;
    margin-top: var(--td-size-1);
}

.reference-slice__preview {
    color: var(--td-text-color-secondary);
    font-size: var(--td-font-size-body-small);
    margin-top: var(--td-size-2);
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
    word-break: break-word;
    line-height: 1.5;
}

.reference-link {
    word-break: break-word;
}

/* ── 引用详情弹窗 ── */
.reference-dialog {
    max-height: min(70vh, 720px);
    overflow: auto;
    scrollbar-width: thin;
    scrollbar-color: var(--td-scrollbar-color, rgba(0,0,0,.12)) transparent;
}

.reference-dialog::-webkit-scrollbar {
    width: 5px;
}

.reference-dialog::-webkit-scrollbar-thumb {
    background: var(--td-scrollbar-color, rgba(0,0,0,.12));
    border-radius: var(--td-radius-small);
}

.reference-dialog::-webkit-scrollbar-track {
    background: transparent;
}

.reference-dialog__meta {
    color: var(--td-text-color-placeholder);
    font-size: var(--td-font-size-body-small);
    margin-bottom: var(--td-comp-margin-xs);
}

.reference-dialog__link {
    margin-bottom: var(--td-comp-margin-s);
}

.reference-dialog__content {
    color: var(--td-text-color-primary);
    word-break: break-word;
    line-height: 1.7;
}

/* ── 布局覆盖 ── */
:deep(.t-chat__actions-margin) {
    width: 100%;
    padding: 0;
    margin-left: 0;
}

/* ── 移动端 ── */
.isMobile .share-icon {
    position: absolute;
    right: 0;
    margin-right: 0;
}

.isMobile .control-icon {
    border: 1px solid var(--td-component-stroke);
    border-radius: var(--td-radius-medium);
    padding: calc(var(--td-pop-padding-m) - 1px);
}

.chat-item__container.loading {
    padding-bottom: var(--td-comp-paddingTB-xxl);
}

/* ── 附件 ── */
.file-attachments {
    display: flex;
    flex-wrap: wrap;
    gap: var(--td-size-4);
    margin: 8px 0;
}

.image-attachments {
    display: flex;
    flex-wrap: wrap;
    gap: var(--td-size-4);
    margin: 8px 0;
}

.msg-inline-image {
    max-width: 200px;
    max-height: 200px;
    border-radius: 10px;
    object-fit: contain;
    cursor: pointer;
    display: block;
    transition: opacity 0.15s ease, transform 0.15s ease;
}

.msg-inline-image:hover {
    opacity: 0.88;
    transform: scale(1.02);
}

@media (prefers-reduced-motion: reduce) {
    .thinking-icon {
        animation: none;
    }
    .msg-inline-image {
        transition: none;
    }
}
</style>
