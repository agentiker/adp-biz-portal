<!-- Widget Action 标签组件：显示 "已进行操作" 提示 -->
<template>
  <div class="widget-action-tag">
    <span class="widget-action-text">{{ displayText }}</span>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { defaultChatItemI18n, defaultChatItemI18nEn } from '../../model/type';

interface Props {
  /** 显示文本；未传时按 language 走 ChatItemI18n.actionPerformed 默认值 */
  text?: string;
  /** 当前语言标识（如 'zh-CN'、'en-US'），仅用于内部默认文案 fallback */
  language?: string;
}

const props = withDefaults(defineProps<Props>(), {
  text: '',
  language: 'zh-CN',
});

/** 最终展示文本：外部 text 优先，否则按 language 选中/英默认值 */
const displayText = computed(() => {
  if (props.text) return props.text;
  const defaults = props.language?.startsWith('en') ? defaultChatItemI18nEn : defaultChatItemI18n;
  return defaults.actionPerformed;
});
</script>

<style scoped>
/* 标签胶囊样式 */
.widget-action-tag {
  display: inline-flex;
  flex-direction: row;
  align-items: center;
  gap: var(--td-size-2);
  padding: 0 12px;
  background: var(--td-bg-color-container-hover, #F7F8FA);
  border-radius: 20px;
  width: fit-content;
}

.widget-action-text {
  font-family: 'PingFang SC', sans-serif;
  font-weight: 400;
  font-size: var(--td-font-size-link-small);
  line-height: 2em;
  color: var(--td-text-color-placeholder, rgba(1, 11, 50, 0.41));
}
</style>
