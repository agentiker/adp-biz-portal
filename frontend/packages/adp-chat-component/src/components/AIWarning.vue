<script setup lang="ts">
import { computed } from 'vue';
import { defaultChatItemI18n, defaultChatItemI18nEn } from '../model/type';

interface Props {
    /** 警告文本；未传时按 language 使用 ChatItemI18n.aiDisclaimer 默认值 */
    text?: string;
    /** 当前语言标识（如 'zh-CN'、'en-US'），用于选择内部默认文案 */
    language?: string;
}

const props = withDefaults(defineProps<Props>(), {
    text: '',
    language: 'zh-CN',
});

/** 最终展示的免责提示文本：外部 text 优先，否则按 language 走 ChatItemI18n 默认值 */
const displayText = computed(() => {
    if (props.text) return props.text;
    const defaults = props.language?.startsWith('en') ? defaultChatItemI18nEn : defaultChatItemI18n;
    return defaults.aiDisclaimer;
});
</script>

<template>
    <div class="chat-component ai-warning">
        {{ displayText }}
    </div>
</template>

<style scoped>
.ai-warning {
    text-align: center;
    color: var(--td-text-color-placeholder);
    font-size: 11px;
    opacity: 0.7;
    letter-spacing: 0.01em;
    padding: var(--td-size-1) 0;
}
</style>
