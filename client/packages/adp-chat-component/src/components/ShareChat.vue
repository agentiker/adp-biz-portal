<template>
  <div class="chat-component share-chat">
    <!-- 聊天组件，用于展示分享的聊天记录 -->
    <TChat ref="chatRef" :reverse="false" style="height: 100%" :clear-history="false">
      <!-- 遍历聊天记录列表，渲染每条消息 -->
      <ChatItem 
        v-for="(item, index) in chatList" 
        :key="item.RecordId" 
        :isLastMsg="index === (chatList.length - 1)" 
        :item="item"
        :index="index" 
        :loading="loading" 
        :isStreamLoad="isStreamLoad" 
        :showActions="false"
        :theme="theme"
        :language="language"
        :chat-i18n="mergedChatI18n"
        :readonly="true"
        :hasSubsequentUserRecord="hasSubsequentUserRecord(index)"
        :historyQuestionnaireSkipped="isHistoryQuestionnaireSkipped(index)"
      />
    </TChat>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref, watch, toRef, computed } from 'vue';
import { Chat as TChat } from '@tdesign-vue-next/chat';
import ChatItem from './Chat/ChatItem.vue';
import { fetchConversationDetail, fetchReferenceDetails } from '../service/api';
import type { ApiConfig } from '../service/api';
import { useApiConfig } from '../composables';
import type { Record, Reference } from '../model/chat-v2';
import type { ThemeType, ChatI18n } from '../model/type';
import { defaultChatI18n, defaultChatI18nEn } from '../model/type';
import { hydrateType2References } from '../utils/reference';
import {
    hasSubsequentUserRecord as hasSubsequentUserRecordInList,
    isHistoryQuestionnaireSkipped as isHistoryQuestionnaireSkippedInList,
} from '../utils/questionnaire';

/**
 * ShareChat 组件 Props
 */
interface Props {
  /** 分享ID */
  shareId: string
  /** 主题 */
  theme?: ThemeType
  /** 当前语言标识（用于 ChatItem 的 i18n 与「跳过」文本判定） */
  language?: string
  /** 澄清相关 i18n 文案覆盖（默认走中英内置值） */
  chatI18n?: ChatI18n
  /** API 配置 - 如果传入则使用 HTTP 请求获取数据 */
  apiConfig?: ApiConfig
  /** 加载完成回调 */
  onLoadComplete?: (records: Record[]) => void
  /** 加载失败回调 */
  onLoadError?: (error: Error) => void
}

const props = withDefaults(defineProps<Props>(), {
  theme: 'light',
  language: 'zh-CN',
  chatI18n: () => ({}),
  apiConfig: () => ({}),
})

const emit = defineEmits<{
  (e: 'loadComplete', records: Record[]): void
  (e: 'loadError', error: Error): void
}>()

// 使用 composable 统一管理 API 配置
const { mergedApiDetailConfig } = useApiConfig({
  apiConfig: toRef(props, 'apiConfig'),
});

/**
 * 聊天消息列表
 */
const chatList = ref<Record[]>([]);

/**
 * 聊天加载状态
 */
const loading = ref(false);

/**
 * 是否流式加载中（分享页面固定为 false）
 */
const isStreamLoad = ref(false);
const referenceDetailCache = new Map<string, Reference>();
const referenceDetailPendingKeys = new Set<string>();

/** 澄清 i18n：按语言选默认值，再合并外部覆盖（与 ChatItem 内部 clarifyI18n 一致） */
const mergedChatI18n = computed<ChatI18n>(() => {
    const defaults = props.language?.startsWith('en') ? defaultChatI18nEn : defaultChatI18n;
    return { ...defaults, ...props.chatI18n };
});

/**
 * 反问澄清「已过期」判定：当前 assistant Record 之后是否已存在用户消息。
 * 分享的快照对话里，未提交就继续的问卷要折叠为「已澄清 0 个问题」摘要态。
 */
const hasSubsequentUserRecord = (index: number): boolean => {
    return hasSubsequentUserRecordInList(chatList.value, index);
};

/**
 * 历史「跳过」识别：当前 assistant Record 之后紧邻的第一条用户消息是否为
 * 纯文本「跳过」（i18n 文案），让问卷展示为已提交摘要而非过期态。
 */
const isHistoryQuestionnaireSkipped = (index: number): boolean => {
    return isHistoryQuestionnaireSkippedInList(
        chatList.value,
        index,
        mergedChatI18n.value.clarifySkip || '跳过'
    );
};

const hydrateReferences = async (records: Record[], shareId: string) => {
  if (records.length === 0) {
    return
  }

  try {
    await hydrateType2References(records, {
      shareId,
      cache: referenceDetailCache,
      pending: referenceDetailPendingKeys,
      fetcher: (params) => fetchReferenceDetails(params, mergedApiDetailConfig.value.referenceDetailApi),
    })
  } catch (error) {
    console.error('补充分享引用切片失败:', error)
  }
}

/**
 * 加载聊天会话详情
 */
const loadConversationDetail = async (shareId: string) => {
  if (!shareId) return
  
  loading.value = true;
  try {
    const response = await fetchConversationDetail(
      { ShareId: shareId },
      mergedApiDetailConfig.value.conversationDetailApi
    );
    loading.value = false;
    chatList.value = response?.Response?.Records || [];
    await hydrateReferences(chatList.value, shareId)
    
    // 触发回调
    props.onLoadComplete?.(chatList.value)
    emit('loadComplete', chatList.value)
  } catch (error) {
    loading.value = false;
    const err = error instanceof Error ? error : new Error('加载分享内容失败')
    props.onLoadError?.(err)
    emit('loadError', err)
  }
};

// 监听 shareId 变化
watch(() => props.shareId, (newId) => {
  if (newId) {
    loadConversationDetail(newId)
  }
}, { immediate: false })

onMounted(() => {
  if (props.shareId) {
    loadConversationDetail(props.shareId)
  }
});

// 暴露方法供外部调用
defineExpose({
  reload: () => loadConversationDetail(props.shareId),
  chatList,
  loading,
})
</script>

<style scoped>
@import '../styles/chat-overrides.css';
.share-chat {
  background-color: var(--td-bg-color-container);
  height: 100%;
  overflow: auto;
}
.share-chat :deep(.t-chat){
  width: 100%;
}
.share-chat :deep(.t-chat__list) {
  padding: var(--td-comp-size-xxs) 10%;
}
</style>
