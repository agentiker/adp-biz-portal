<template>
    <div class="cron-prompt-input">
        <div class="cron-prompt-input__label">
            {{ i18n.promptLabel }}
            <span class="cron-prompt-input__required">*</span>
        </div>

        <!-- 提示词输入框：字数计数由 TDesign 内置渲染到框内右下角（对齐 webim） -->
        <div class="cron-prompt-input__textarea-wrap">
            <t-textarea
                v-model="innerValue"
                :placeholder="i18n.promptPlaceholder"
                :maxlength="maxLength"
                :autosize="{ minRows: 4, maxRows: 10 }"
            />
        </div>
    </div>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { Textarea as TTextarea } from 'tdesign-vue-next';
import type { CronTaskI18n } from '../../../model/cronTask';
import { getCronTaskI18nByLanguage } from '../../../model/cronTask';
import type { ThemeProps } from '../../../model/type';
import { themePropsDefaults } from '../../../model/type';

/**
 * 定时任务提示词输入组件
 * 说明：当前 AppTrigger 协议 (AppTriggerPromptExecuteConfig) 只支持 execute_prompt，
 *      不支持 model_id 字段（透传会导致后端返回 UnknownParameter）。
 *      因此本组件不再包含模型选择器，仅提供提示词输入。
 */
interface Props extends ThemeProps {
    /** 提示词内容 v-model */
    modelValue: string;
    /** 最大字符数 */
    maxLength?: number;
    /** 语言 */
    language?: string;
    /** i18n 覆盖 */
    i18n?: Partial<CronTaskI18n>;
}

const props = withDefaults(defineProps<Props>(), {
    ...themePropsDefaults,
    modelValue: '',
    maxLength: 10000,
    language: 'zh-CN',
    i18n: () => ({}),
});

const emit = defineEmits<{
    (e: 'update:modelValue', val: string): void;
}>();

const i18n = computed<Required<CronTaskI18n>>(() => ({
    ...getCronTaskI18nByLanguage(props.language),
    ...props.i18n,
}));

const innerValue = computed({
    get: () => props.modelValue,
    set: (val) => emit('update:modelValue', val),
});

/** 表单校验 */
function validate(): { valid: boolean; message?: string } {
    if (!innerValue.value || !innerValue.value.trim()) {
        return { valid: false, message: i18n.value.promptPlaceholder };
    }
    return { valid: true };
}

/** 获取表单数据（仅提示词） */
function getFormData(): { ExecutePrompt: string } {
    return {
        ExecutePrompt: innerValue.value?.trim() || '',
    };
}

/**
 * 设置表单数据（编辑回填）
 * 兼容旧字段 prompt 和新字段 ExecutePrompt
 */
function setFormData(data: { ExecutePrompt?: string; prompt?: string }) {
    const val = data.ExecutePrompt ?? data.prompt ?? '';
    emit('update:modelValue', val);
}

/** 重置表单 */
function resetForm() {
    emit('update:modelValue', '');
}

defineExpose({ validate, getFormData, setFormData, resetForm });
</script>

<style scoped>
.cron-prompt-input {
    display: flex;
    flex-direction: column;
    gap: var(--td-size-4);
}

.cron-prompt-input__label {
    font-size: var(--td-font-size-body-medium);
    font-weight: 500;
    color: var(--td-text-color-primary);
    line-height: var(--td-line-height-body-medium);
}

.cron-prompt-input__required {
    color: var(--td-error-color);
    margin-left: var(--td-size-1);
}

/*
 * TDesign textarea 的 maxlength 计数：将它固定在框内右下角，避免部分主题下浮出框外
 * 依赖 :deep 穿透 scoped，命中内部 .t-textarea__limit
 */
.cron-prompt-input__textarea-wrap :deep(.t-textarea__inner) {
    padding-bottom: var(--td-size-6);
}

.cron-prompt-input__textarea-wrap :deep(.t-textarea__limit) {
    position: absolute;
    right: var(--td-size-3);
    bottom: var(--td-size-2);
    font-size: var(--td-font-size-body-small);
    color: var(--td-text-color-placeholder);
    background: transparent;
    pointer-events: none;
}

.cron-prompt-input__textarea-wrap :deep(.t-textarea) {
    position: relative;
}
</style>
