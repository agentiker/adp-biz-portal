<!--
  对话列表组件
  @description 用于展示和管理用户的聊天会话列表，支持切换会话
-->
<script setup lang="tsx">
import { computed } from 'vue';
import { Loading as TLoading, Icon as TIcon } from 'tdesign-vue-next';
import type { ChatConversation } from '../model/chat-v2';
import type { SideI18n } from '../model/type';
import { defaultSideI18n, defaultSideI18nEn } from '../model/type';

interface Props {
    /** 会话列表 */
    conversations: ChatConversation[];
    /** 当前选中的会话ID */
    currentConversationId?: string;
    /**
     * 正在进行中（流式请求未完成）的会话 Id 集合
     * 命中的项会在列表里显示转圈加载态（替代时间显示）
     * 由父组件基于 conversationRuntimeStates.isChatting 计算后传入
     */
    chattingConversationIds?: string[];
    /** 侧边栏国际化文本（复用 SideI18n 中的 taskListTitle / inProgress / deleteConversation / daysAgo） */
    i18n?: SideI18n;
    /** 当前语言标识（如 'zh-CN'、'en-US'），用于选择内部默认 i18n */
    language?: string;
}

const props = withDefaults(defineProps<Props>(), {
    conversations: () => [],
    currentConversationId: '',
    chattingConversationIds: () => [],
    i18n: () => ({}),
    language: 'zh-CN',
});

/** 合并 i18n：外部覆盖 > 按 language 选中/英默认值 */
const mergedI18n = computed<Required<SideI18n>>(() => ({
    ...(props.language?.startsWith('en') ? defaultSideI18nEn : defaultSideI18n),
    ...props.i18n,
}));

/**
 * 用 Set 加速命中判断，避免每项 O(n) 扫描
 */
const chattingIdSet = computed(() => new Set(props.chattingConversationIds));

const emit = defineEmits<{
    (e: 'select', conversation: ChatConversation): void;
    /**
     * 请求删除会话（由父组件负责弹确认框 + 调后端 + 更新列表）
     * 组件本身不做删除动作，保持单一职责
     */
    (e: 'delete', conversation: ChatConversation): void;
}>();

/**
 * 按最后活跃时间倒序排列的会话列表
 */
const sortedConversations = computed(() => {
    return [...props.conversations].sort(
        (a, b) => b.LastActiveAt - a.LastActiveAt
    );
});

/**
 * 格式化更新时间
 * 规则：当天 HH:mm、1~6 天内 x天前、7 天及以上 M/D
 * @param time 秒级或毫秒级时间戳
 */
const formatUpdateTime = (time: number): string => {
    if (!time) return '';
    const ts = time < 1e12 ? time * 1000 : time;
    const target = new Date(ts);
    if (isNaN(target.getTime())) return '';

    const now = new Date();
    const todayStart = new Date(
        now.getFullYear(), now.getMonth(), now.getDate()
    ).getTime();
    const targetDayStart = new Date(
        target.getFullYear(), target.getMonth(), target.getDate()
    ).getTime();

    if (targetDayStart === todayStart) {
        const hh = String(target.getHours()).padStart(2, '0');
        const mm = String(target.getMinutes()).padStart(2, '0');
        return `${hh}:${mm}`;
    }

    const diffDays = Math.floor(
        (todayStart - targetDayStart) / (24 * 60 * 60 * 1000)
    );
    if (diffDays >= 1 && diffDays <= 6) {
        // daysAgo 支持 {days} 占位符（"{days}天前" / "{days}d ago"）
        return mergedI18n.value.daysAgo.replace('{days}', String(diffDays));
    }
    return `${target.getMonth() + 1}/${target.getDate()}`;
};

/**
 * 点击会话项的处理函数
 */
const handleClick = (detail: ChatConversation) => {
    emit('select', detail);
};

/**
 * 点击删除按钮：阻止冒泡以免触发会话选中，向父组件抛出 delete 事件
 * 正在进行中（chatting）的会话不允许删除，避免与 SSE 竞态
 */
const handleDeleteClick = (event: Event, detail: ChatConversation) => {
    event.stopPropagation();
    if (chattingIdSet.value.has(detail.Id)) {
        return;
    }
    emit('delete', detail);
};
</script>

<template>
    <!-- 会话列表容器 -->
    <div class="history-list">
        <div class="history-header">
            <span class="history-header__title">{{ mergedI18n.taskListTitle }}</span>
        </div>
        <!-- 会话项列表 -->
        <div
            v-for="item in sortedConversations"
            :key="item.Id"
            class="history-item"
            :class="{ active: currentConversationId === item.Id }"
            @click="handleClick(item)"
        >
            <div class="history-title" :title="item.Title">{{ item.Title }}</div>
            <!--
              右侧状态区展示优先级（互斥，避免拥挤）：
              1. 进行中 → 转圈
              2. hover / active 且非进行中 → 删除按钮
              3. 否则 → 最近更新时间（hover / active 时才可见）
            -->
            <span v-if="chattingIdSet.has(item.Id)" class="history-loading" :aria-label="mergedI18n.inProgress">
                <TLoading size="14px" />
            </span>
            <template v-else>
                <span
                    class="history-delete"
                    :aria-label="mergedI18n.deleteConversation"
                    role="button"
                    tabindex="0"
                    @click="handleDeleteClick($event, item)"
                    @keydown.enter.stop.prevent="handleDeleteClick($event, item)"
                >
                    <TIcon name="delete" size="14px" />
                </span>
                <span v-if="item.LastActiveAt" class="history-time">
                    {{ formatUpdateTime(item.LastActiveAt) }}
                </span>
            </template>
        </div>
    </div>
</template>

<style scoped>
.history-list {
    width: 100%;
    padding: 0 var(--td-size-2);
}

.history-header {
    font-size: 11px;
    font-weight: 500;
    letter-spacing: 0.02em;
    text-transform: uppercase;
    height: var(--td-comp-size-s);
    line-height: var(--td-comp-size-s);
    color: var(--td-text-color-placeholder);
    padding-left: var(--td-comp-paddingLR-s);
    display: flex;
    align-items: center;
    margin-bottom: var(--td-comp-margin-xs);
}

.history-header__title {
    color: var(--td-text-color-placeholder);
    font-size: 11px;
    font-weight: 500;
    letter-spacing: 0.03em;
}

.history-item {
    min-height: 36px;
    line-height: var(--td-line-height-body-small);
    cursor: pointer;
    padding: var(--td-size-4) 10px;
    border-radius: var(--td-radius-medium);
    transition: background 0.15s ease, color 0.15s ease;
    color: var(--td-text-color-primary);
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: var(--td-font-size-body-medium);
    margin-bottom: var(--td-size-1);
}

.history-item.active {
    background: var(--td-bg-color-container-active);
    font-weight: 500;
}

.history-item:hover:not(.active) {
    background: var(--td-bg-color-container-hover);
}

.history-title {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.history-time {
    flex-shrink: 0;
    margin-left: var(--td-size-4);
    font-size: 11px;
    color: var(--td-text-color-placeholder);
}

/* 默认展示时间；hover/active 时让位给删除按钮，避免右侧同时显示两个元素造成拥挤 */
.history-item:hover .history-time,
.history-item.active .history-time {
    display: none;
}

/* 进行中的转圈：始终可见，颜色与主色一致，位置与 history-time 对齐 */
.history-loading {
    flex-shrink: 0;
    margin-left: var(--td-size-4);
    display: inline-flex;
    align-items: center;
    color: var(--td-brand-color);
}

/* 删除按钮：默认隐藏，hover/active 时展示 */
.history-delete {
    flex-shrink: 0;
    margin-left: var(--td-size-4);
    display: none;
    align-items: center;
    justify-content: center;
    width: 20px;
    height: 20px;
    border-radius: var(--td-radius-small);
    color: var(--td-text-color-placeholder);
    cursor: pointer;
    transition: background 0.15s ease, color 0.15s ease;
}

.history-item:hover .history-delete,
.history-item.active .history-delete {
    display: inline-flex;
}

.history-delete:hover {
    background: var(--td-bg-color-container-active);
    color: var(--td-error-color);
}

.history-delete:focus-visible {
    outline: 2px solid var(--td-brand-color);
    outline-offset: 1px;
}
</style>
