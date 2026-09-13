<!-- 消息发送组件：纯文本输入 + 发送 / 停止 -->
<script setup lang="ts">
import { ref, computed, nextTick } from 'vue'
import { MessagePlugin } from 'tdesign-vue-next'
import { MessageCode, getMessage } from '../../model/messages';
import type { ChatRelatedProps, SenderI18n } from '../../model/type';
import { chatRelatedPropsDefaults, defaultSenderI18n, defaultSenderI18nEn } from '../../model/type';
import CustomizedIcon from '../CustomizedIcon.vue';

export interface Props extends ChatRelatedProps {
    /** 是否正在流式输出（决定发送按钮是否切换为停止态） */
    isStreamLoad?: boolean;
    /** 国际化文本 */
    i18n?: SenderI18n;
}

const props = withDefaults(defineProps<Props>(), {
    ...chatRelatedPropsDefaults,
    isStreamLoad: false,
    i18n: () => ({}),
});

const emit = defineEmits<{
    (e: 'stop'): void;
    (e: 'send', value: string): void;
    (e: 'message', code: MessageCode, message: string): void;
}>();

const i18n = computed(() => {
    const defaults = props.language?.startsWith('en') ? defaultSenderI18nEn : defaultSenderI18n;
    return { ...defaults, ...props.i18n };
});

const inputText = ref('');
const inputFocus = ref(false);
/**
 * 输入法组合态。`event.isComposing` 在部分 Windows IME / Safari 的候选确认键上为 false，
 * `keyCode === 229` 覆盖 Chromium / Safari，三者叠加才能可靠避免中文输入时误发送。
 */
const isComposing = ref(false);
const textareaRef = ref<HTMLTextAreaElement | null>(null);

/** 自增高：先塌到 0 再按 scrollHeight 撑开，外层 .sender-editor-area 有 200px 上限与滚动 */
const autoResize = () => {
    const el = textareaRef.value;
    if (!el) return;
    el.style.height = '0px';
    el.style.height = `${Math.max(24, el.scrollHeight)}px`;
};

/** 剥离零宽字符与空白后是否仍有内容（防止粘贴 ​ 被当成有内容） */
const hasContent = computed(() => inputText.value.replace(/[​\s]/g, '') !== '');

const sendDisabled = computed(() => props.isStreamLoad);

const placeholder = computed(() =>
    props.isMobile ? (i18n.value.placeholderMobile || '') : (i18n.value.placeholder || ''));

const handleSend = () => {
    if (props.isStreamLoad) {
        const text = i18n.value.answering || getMessage(MessageCode.ANSWERING, props.language).message;
        MessagePlugin.warning(text);
        emit('message', MessageCode.ANSWERING, text);
        return;
    }
    if (!hasContent.value) return;
    emit('send', inputText.value);
    inputText.value = '';
    void nextTick(autoResize);
};

/** 在光标处插入换行（v-model 下 DOM 值下一 tick 才更新，故 selection 复位放在 nextTick） */
const insertNewlineAtCaret = () => {
    const el = textareaRef.value;
    if (!el) return;
    const start = el.selectionStart ?? inputText.value.length;
    const end = el.selectionEnd ?? start;
    inputText.value = `${inputText.value.slice(0, start)}\n${inputText.value.slice(end)}`;
    void nextTick(() => {
        el.selectionStart = el.selectionEnd = start + 1;
        autoResize();
    });
};

const handleKeydown = (event: KeyboardEvent) => {
    if (event.key !== 'Enter') return;
    if (isComposing.value || event.isComposing || event.keyCode === 229) return;
    if (event.metaKey || event.ctrlKey) {
        // 原 contenteditable 下 Ctrl+Enter 默认不换行故未拦截；textarea 默认会换行，
        // 不 preventDefault 会插入两个换行。
        event.preventDefault();
        insertNewlineAtCaret();
        return;
    }
    if (event.shiftKey) return;
    event.preventDefault();
    handleSend();
};

/**
 * 设置输入框内容（供外部调用）。
 * 语义由原先的「HTML 片段」改为纯文本——富文本编辑器已移除。
 */
const changeSenderVal = (value = '') => {
    inputText.value = value;
    void nextTick(() => {
        autoResize();
        if (value) textareaRef.value?.focus();
    });
};

defineExpose({ changeSenderVal });
</script>

<template>
    <div class="sender-wrapper">
        <!-- 快捷按钮插槽：消息列表为空时，外部注入 assist-quick-buttons（在输入框边框外侧上方） -->
        <slot name="quick-buttons" />

        <div class="sender-container" :class="{ 'is-focused': inputFocus }">
            <div class="sender-editor-area" @keydown="handleKeydown">
                <textarea
                    ref="textareaRef"
                    v-model="inputText"
                    class="sender-textarea"
                    rows="1"
                    :placeholder="placeholder"
                    @input="autoResize"
                    @focus="inputFocus = true"
                    @blur="inputFocus = false"
                    @compositionstart="isComposing = true"
                    @compositionend="isComposing = false"
                ></textarea>
            </div>

            <div class="sender-toolbar" :class="{ 'is-mobile': isMobile }">
                <div class="sender-toolbar__right">
                    <CustomizedIcon class="send-icon waiting" :class="{ disabled: sendDisabled }" v-if="!isStreamLoad && !hasContent" nativeIcon :showHoverBg="false" :name="theme === 'dark' ? 'send_dark' : 'send'" @click="handleSend" />
                    <CustomizedIcon class="send-icon success" :class="{ disabled: sendDisabled }" v-if="!isStreamLoad && hasContent" nativeIcon :showHoverBg="false" name="send_fill" @click="handleSend" />
                    <CustomizedIcon class="send-icon stop" v-if="isStreamLoad" nativeIcon :showHoverBg="false" :name="theme === 'dark' ? 'pause_dark' : 'pause'" @click="emit('stop')" />
                </div>
            </div>
        </div>
    </div>
</template>

<style scoped>
.sender-wrapper {
    display: flex;
    flex-direction: column;
    align-items: center;
    width: 100%;
}

/* ── 主容器 ── */
.sender-container {
    width: 100%;
    max-width: 800px;
    display: flex;
    flex-direction: column;
    border: 1px solid var(--td-component-border);
    border-radius: var(--td-radius-xl, 16px);
    background: var(--td-bg-color-container, #fff);
    /* 同时过渡 border-color / box-shadow / transform，曲线选用接近 Material 的 standard easing，进出更柔和 */
    transition:
        border-color 0.28s cubic-bezier(0.4, 0, 0.2, 1),
        box-shadow 0.28s cubic-bezier(0.4, 0, 0.2, 1),
        transform 0.28s cubic-bezier(0.4, 0, 0.2, 1);
    overflow: visible;
    will-change: box-shadow, border-color;
    margin: 5px;
}

.sender-container:hover {
    /* 边框略浅染品牌色，配合双层阴影营造自然抬起感（外层柔光 + 内层焦点环） */
    border-color: var(--td-brand-color, #0052d9);
    box-shadow:
        0 4px 16px -4px rgba(0, 82, 217, 0.18),
        0 0 0 3px rgba(0, 82, 217, 0.08);
}

/* 输入聚焦时给出更明显但仍克制的强调态 */
.sender-container:focus-within {
    border-color: var(--td-brand-color, #0052d9);
    box-shadow:
        0 6px 20px -6px rgba(0, 82, 217, 0.22),
        0 0 0 3px rgba(0, 82, 217, 0.04);
}

@media (prefers-reduced-motion: reduce) {
    .sender-container,
    .sender-container * {
        transition: none !important;
    }
}

/* ── 编辑器区域 ── */
.sender-editor-area {
    max-height: 200px;
    overflow-y: auto;
    overflow-x: hidden;
    scrollbar-width: thin;
    scrollbar-color: var(--td-scrollbar-color, rgba(0,0,0,.12)) transparent;
}

.sender-editor-area::-webkit-scrollbar {
    width: 5px;
}

.sender-editor-area::-webkit-scrollbar-thumb {
    background: var(--td-scrollbar-color, rgba(0,0,0,.12));
    border-radius: var(--td-radius-small);
}

.sender-editor-area::-webkit-scrollbar-track {
    background: transparent;
}

.sender-textarea {
    display: block;
    width: 100%;
    box-sizing: border-box;
    min-height: 24px;
    padding: 12px 14px 4px;
    border: 0;
    outline: 0;
    resize: none;
    background: transparent;
    color: var(--td-text-color-primary);
    font: inherit;
    line-height: 1.6;
    overflow: hidden;
}

.sender-textarea::placeholder {
    color: var(--td-text-color-placeholder);
}

/* ── 底部工具栏 ── */
.sender-toolbar {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: var(--td-size-1) 10px var(--td-size-4);
    cursor: default;
    gap: var(--td-size-2);
}

.sender-toolbar__right {
    display: flex;
    align-items: center;
    margin-left: auto;
    flex-shrink: 0;
}

/* ── 移动端布局 ── */
.sender-toolbar.is-mobile {
    flex-wrap: wrap;
}

/* ── 发送按钮 ── */
.send-icon {
    padding: 0 !important;
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    transition: opacity 0.15s ease, transform 0.12s ease;
}

.send-icon:active {
    transform: scale(0.94);
}

.send-icon.disabled {
    opacity: 0.25;
    cursor: not-allowed;
    pointer-events: none;
}

.send-icon.stop {
    color: var(--td-text-color-secondary);
}
</style>
