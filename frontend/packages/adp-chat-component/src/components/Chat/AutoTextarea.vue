<!--
  自适应高度文本域：内容变多时撑开、变少时缩回，并在超出字数限制时展示告警。
  用于反问澄清（ClassifyTag）中「其他」选项的补充输入。

  迁移说明：等价移植自 lke-component v2.0.5 的 AutoTextarea.vue（Vue 2 Options API），
  这里改写为 Vue 3 + TS，并把硬编码色值替换为 theme.css 的 --td-* 变量。
-->
<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue';

interface Props {
    /** 输入内容（配合 v-model 使用） */
    modelValue?: string;
    /** 占位提示 */
    placeholder?: string;
    /** 是否禁用 */
    disabled?: boolean;
    /** 最大字符数限制，超出触发告警（不做截断，与源组件行为一致） */
    maxLength?: number;
    /** 超出字数限制时展示的告警文案 */
    errorText?: string;
    /** 输入框最小高度（px） */
    minHeight?: number;
}

const props = withDefaults(defineProps<Props>(), {
    modelValue: '',
    placeholder: '',
    disabled: false,
    maxLength: 1000,
    errorText: '',
    minHeight: 30,
});

const emit = defineEmits<{
    (e: 'update:modelValue', value: string): void;
    /** 超出字数限制时抛出当前长度 */
    (e: 'over-limit', length: number): void;
}>();

const textareaRef = ref<HTMLTextAreaElement | null>(null);

/** 是否超出字数限制 */
const isOverLimit = computed(() => (props.modelValue || '').length > props.maxLength);

/** 是否展示告警：超出限制且未禁用 */
const showError = computed(() => isOverLimit.value && !props.disabled);

/**
 * 自适应高度：先把高度归零，强制 scrollHeight 仅按内容计算，
 * 再取 max(minHeight, scrollHeight) 作为最终高度。
 */
function autoResize(): void {
    const el = textareaRef.value;
    if (!el) return;
    el.style.height = '0px';
    el.style.height = `${Math.max(props.minHeight, el.scrollHeight)}px`;
}

function handleInput(event: Event): void {
    const el = event.target as HTMLTextAreaElement;
    const value = el.value || '';
    // 超出限制时向上告警，但不阻断输入（与源组件一致）
    if (value.length > props.maxLength) {
        emit('over-limit', value.length);
    }
    emit('update:modelValue', value);
    void nextTick(autoResize);
}

// 外部回显 modelValue 时重新计算高度
watch(
    () => props.modelValue,
    () => {
        void nextTick(autoResize);
    }
);

onMounted(autoResize);
</script>

<template>
    <div class="auto-textarea">
        <textarea
            ref="textareaRef"
            class="auto-textarea__field"
            :class="{ 'auto-textarea__field--error': showError }"
            :placeholder="placeholder"
            :disabled="disabled"
            :value="modelValue"
            @input="handleInput"
        ></textarea>
        <span v-if="showError" class="auto-textarea__error">{{ errorText }}</span>
    </div>
</template>

<style scoped>
.auto-textarea {
    width: 100%;
}

.auto-textarea__field {
    display: block;
    width: 100%;
    min-height: 30px;
    padding: 5px 12px;
    border: 1px solid var(--td-component-border);
    border-radius: var(--td-radius-default);
    font-size: 12px;
    font-family: inherit;
    line-height: 20px;
    color: var(--td-text-color-primary);
    background: var(--td-bg-color-container);
    resize: none;
    outline: none;
    overflow: hidden;
    transition: border-color 0.2s ease;
    box-sizing: border-box;
}

.auto-textarea__field:focus {
    border-color: var(--td-brand-color);
}

.auto-textarea__field:disabled {
    background: var(--td-bg-color-component-disabled);
    color: var(--td-text-color-disabled);
    cursor: not-allowed;
    border-color: var(--td-border-level-1-color);
}

.auto-textarea__field::placeholder {
    color: var(--td-text-color-placeholder);
}

.auto-textarea__field--error {
    border-color: var(--td-error-color);
}

.auto-textarea__error {
    display: block;
    font-size: 11px;
    color: var(--td-error-color);
    line-height: 16px;
    margin-top: 4px;
}
</style>
