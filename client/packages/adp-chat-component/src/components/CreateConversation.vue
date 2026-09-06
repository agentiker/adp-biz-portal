<script setup lang="ts">
import { computed } from 'vue';
import CustomizedIcon from './CustomizedIcon.vue';
import type { ThemeProps } from '../model/type';
import { themePropsDefaults, defaultChatI18n, defaultChatI18nEn } from '../model/type';
import { Tooltip as TTooltip, Button as TButton } from 'tdesign-vue-next';

interface Props extends ThemeProps {
    /** 提示文本；未传时按 language 走 ChatI18n.createConversation 默认值 */
    tooltipText?: string;
    /** 当前语言标识（如 'zh-CN'、'en-US'），仅用于内部默认文案 fallback */
    language?: string;
}

const props = withDefaults(defineProps<Props>(), {
    ...themePropsDefaults,
    tooltipText: '',
    language: 'zh-CN',
});

/** 内部 fallback 文案：外部未传 tooltipText 时按 language 选中/英文 */
const displayTooltip = computed(() => {
    if (props.tooltipText) return props.tooltipText;
    const defaults = props.language?.startsWith('en') ? defaultChatI18nEn : defaultChatI18n;
    return defaults.createConversation;
});

const emit = defineEmits<{
    (e: 'create'): void;
}>();

const createConversation = () => {
    emit('create');
};
</script>

<template>
    <t-tooltip :content="displayTooltip">
        <t-button shape="square" variant="text" @click="createConversation">
            <CustomizedIcon remote name="basic_newchat_line" :theme="theme"/>
        </t-button>
    </t-tooltip>
</template>

<style scoped></style>
