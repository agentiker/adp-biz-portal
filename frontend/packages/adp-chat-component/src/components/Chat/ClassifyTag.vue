<!--
  反问澄清交互卡（questionnaire）。

  展示后端下发的澄清问题，支持单选/多选作答、「其他」自由输入，
  用户可提交或跳过。已提交后卡片进入只读态。

  迁移说明：等价移植自 lke-component v2.0.5 的 ClassifyTag.vue（Vue 2 Options API），
  改写为 Vue 3 + TS，硬编码色值替换为 theme.css 的 --td-* 变量，
  i18n 改为「外部 i18n prop + 内部中英默认值 fallback」模式。

  以下行为与源组件严格保持一致，不可「优化」：
    1. 「其他」选项由本组件自动追加，后端不下发；
    2. 选中「其他」时必须填写内容且不超字数上限，否则不允许提交；
    3. 提交结果中「其他」的文案被替换为用户输入的文本；
    4. 框选复制文案时不触发选项切换（_hasTextSelection 拦截）；
    5. defaultAnswers 一旦有值即置为已提交态（用于历史消息回显）；
    6. 提交结果同时提供单选与多选字段，兼容不同消费方。
-->
<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue';
import type {
    NormalizedQuestionnaireQuestion,
    QuestionnaireDefaultAnswer,
    QuestionnaireSubmitItem,
} from '../../model/chat-v2';
import type { ChatI18n } from '../../model/type';
import { defaultChatI18n, defaultChatI18nEn } from '../../model/type';
import { OTHER_INPUT_MAX_LENGTH } from '../../utils/questionnaire';
import { QuestionnaireQuestionType } from '../../model/chat-v2';
import AutoTextarea from './AutoTextarea.vue';

interface Props {
    /** 卡片标题，为空时回落到 i18n 的 clarifyTitle */
    title?: string;
    /** 归一化后的问题列表（由 utils/questionnaire.normalizeQuestionnaire 产出） */
    questions?: NormalizedQuestionnaireQuestion[];
    /** 是否禁用交互（已提交、分享只读等场景） */
    disabled?: boolean;
    /** 历史回显：已选择的答案，传入后自动置为已提交态 */
    defaultAnswers?: QuestionnaireDefaultAnswer[];
    /** 当前语言标识 */
    language?: string;
    /** 国际化文本 */
    i18n?: ChatI18n;
}

const props = withDefaults(defineProps<Props>(), {
    title: '',
    questions: () => [],
    disabled: false,
    defaultAnswers: () => [],
    language: 'zh-CN',
    i18n: () => ({}),
});

const emit = defineEmits<{
    (e: 'submit', result: QuestionnaireSubmitItem[]): void;
    (e: 'skip'): void;
}>();

const mergedI18n = computed(() => {
    const defaults = props.language?.startsWith('en') ? defaultChatI18nEn : defaultChatI18n;
    return { ...defaults, ...props.i18n };
});

/** 是否折叠 */
const collapsed = ref(false);
/** 是否已提交（提交后卡片只读） */
const submitted = ref(false);
/** 单选存 optionIndex，多选存 optionIndex[] */
const selectedAnswers = reactive<Record<number, number | number[]>>({});
/** 「其他」选项的补充输入内容 */
const otherInputs = reactive<Record<number, string>>({});

/** 卡片标题，缺省回落到 i18n */
const displayTitle = computed(() => props.title || mergedI18n.value.clarifyTitle);

/**
 * 归一化问题列表，并在每题末尾追加「其他」选项。
 * 「其他」由前端自造，后端不下发。
 */
interface DisplayOption {
    label: string;
    description: string;
    isOther: boolean;
}
interface DisplayQuestion {
    id: number;
    text: string;
    isMulti: boolean;
    options: DisplayOption[];
}

const displayQuestions = computed<DisplayQuestion[]>(() =>
    (props.questions || []).map((q, idx) => {
        const options: DisplayOption[] = (q.options || []).map((opt) => ({
            label: opt.label,
            description: opt.description,
            isOther: false,
        }));
        // 追加「其他」选项
        options.push({
            label: mergedI18n.value.clarifyOther,
            description: '',
            isOther: true,
        });
        return {
            id: q.id ?? idx,
            text: q.text,
            isMulti: q.type === QuestionnaireQuestionType.Multiple,
            options,
        };
    })
);

/** 每题「其他」选项的下标（即最后一项） */
const otherOptionIndexMap = computed<Record<number, number>>(() => {
    const map: Record<number, number> = {};
    displayQuestions.value.forEach((q) => {
        map[q.id] = q.options.length - 1;
    });
    return map;
});

/** 判断某题是否选中了「其他」 */
function isOtherSelected(questionId: number): boolean {
    const otherIdx = otherOptionIndexMap.value[questionId];
    const answer = selectedAnswers[questionId];
    if (Array.isArray(answer)) return answer.includes(otherIdx as number);
    return answer === otherIdx;
}

/**
 * 是否全部问题均已有效作答（决定提交按钮可用性）。
 * 选中「其他」时要求补充内容非空且不超字数上限。
 */
const allAnswered = computed(() => {
    const questions = displayQuestions.value;
    if (!questions.length) return false;
    return questions.every((q) => {
        const answer = selectedAnswers[q.id];
        const otherIdx = otherOptionIndexMap.value[q.id];
        const otherText = otherInputs[q.id] || '';
        const otherValid = otherText.trim().length > 0 && otherText.length <= OTHER_INPUT_MAX_LENGTH;

        if (q.isMulti) {
            if (!Array.isArray(answer) || !answer.length) return false;
            if (answer.includes(otherIdx as number) && !otherValid) return false;
            return true;
        }
        if (answer === undefined) return false;
        if (answer === otherIdx && !otherValid) return false;
        return true;
    });
});

/**
 * 判断当前是否存在有效的文本选区。
 * 选项文案可被框选复制，拖拽结束的 mouseup 仍会触发 label 的 click，
 * 若不拦截会导致用户复制文案时误选/误取消选项。
 */
function hasTextSelection(): boolean {
    if (typeof window === 'undefined' || typeof window.getSelection !== 'function') {
        return false;
    }
    const selection = window.getSelection();
    if (!selection || selection.isCollapsed) return false;
    return selection.toString().trim() !== '';
}

function toggleCollapse(): void {
    collapsed.value = !collapsed.value;
}

/** 单选：选中某项 */
function selectOption(questionId: number, optionIdx: number): void {
    if (submitted.value || props.disabled) return;
    if (hasTextSelection()) return;
    selectedAnswers[questionId] = optionIdx;
}

/** 多选：判断某项是否已勾选 */
function isChecked(questionId: number, optionIdx: number): boolean {
    const answer = selectedAnswers[questionId];
    return Array.isArray(answer) && answer.includes(optionIdx);
}

/** 多选：切换某项勾选状态 */
function toggleCheckbox(questionId: number, optionIdx: number): void {
    if (submitted.value || props.disabled) return;
    if (hasTextSelection()) return;
    const current = selectedAnswers[questionId];
    const next = Array.isArray(current) ? [...current] : [];
    const pos = next.indexOf(optionIdx);
    if (pos !== -1) {
        next.splice(pos, 1);
    } else {
        next.push(optionIdx);
    }
    selectedAnswers[questionId] = next;
}

/** 单选按钮是否选中 */
function isRadioChecked(questionId: number, optionIdx: number): boolean {
    return selectedAnswers[questionId] === optionIdx;
}

function handleOtherInput(questionId: number, value: string): void {
    otherInputs[questionId] = value;
}

function getOtherInput(questionId: number): string {
    return otherInputs[questionId] || '';
}

/**
 * 根据 defaultAnswers 初始化已选答案并置为已提交态（历史消息回显）。
 * 兼容多选题被传入旧的单选格式（selectedIndex）的情况。
 */
function applyDefaultAnswers(answers: QuestionnaireDefaultAnswer[]): void {
    answers.forEach((answer) => {
        if (answer.questionId === undefined) return;
        if (answer.selectedIndices && Array.isArray(answer.selectedIndices)) {
            selectedAnswers[answer.questionId] = [...answer.selectedIndices];
            return;
        }
        if (answer.selectedIndex === undefined) return;
        const question = displayQuestions.value.find((q) => q.id === answer.questionId);
        // 多选题但传入单选格式时转为数组
        selectedAnswers[answer.questionId] = question?.isMulti
            ? [answer.selectedIndex]
            : answer.selectedIndex;
    });
    submitted.value = true;
}

watch(
    () => props.defaultAnswers,
    (value) => {
        if (value && value.length) {
            applyDefaultAnswers(value);
        }
    },
    { immediate: true }
);

/**
 * 提交：构造单题结果。
 * 选中「其他」时以用户输入的文本替代其 label；
 * 单选与多选字段同时提供，以兼容不同消费方。
 */
function handleSubmit(): void {
    if (!allAnswered.value || submitted.value) return;
    submitted.value = true;

    const result: QuestionnaireSubmitItem[] = displayQuestions.value.map((q) => {
        const answer = selectedAnswers[q.id];
        const otherIdx = otherOptionIndexMap.value[q.id] as number;
        const otherText = otherInputs[q.id] || '';

        if (q.isMulti) {
            const indices = Array.isArray(answer) ? answer : [];
            const selectedOptions = indices.map((i) =>
                i === otherIdx ? otherText : q.options[i]?.label ?? ''
            );
            return {
                questionId: String(q.id),
                questionText: q.text,
                isMulti: true,
                selectedOption: selectedOptions[0] ?? '',
                selectedOptions,
                selectedIndex: indices[0] ?? -1,
                selectedIndices: indices,
                isOther: indices.includes(otherIdx),
            };
        }

        const index = typeof answer === 'number' ? answer : -1;
        const isOther = index === otherIdx;
        const label = isOther ? otherText : q.options[index]?.label ?? '';
        return {
            questionId: String(q.id),
            questionText: q.text,
            isMulti: false,
            selectedOption: label,
            selectedOptions: [label],
            selectedIndex: index,
            selectedIndices: [index],
            isOther,
        };
    });

    emit('submit', result);
}

function handleSkip(): void {
    if (submitted.value || props.disabled) return;
    emit('skip');
}
</script>

<template>
    <div class="classify-tag" :class="{ 'classify-tag--collapsed': collapsed }">
        <!-- 标题栏：整行可点击折叠 -->
        <div class="classify-tag__header" @click="toggleCollapse">
            <svg
                class="classify-tag__icon"
                width="16"
                height="16"
                viewBox="0 0 16 16"
                fill="none"
                xmlns="http://www.w3.org/2000/svg"
            >
                <path
                    fill-rule="evenodd"
                    clip-rule="evenodd"
                    d="M14.6673 8.0026C14.6673 4.32071 11.6825 1.33594 8.00065 1.33594C4.31875 1.33594 1.33398 4.32071 1.33398 8.0026C1.33398 11.6845 4.31875 14.6693 8.00065 14.6693C9.30211 14.6693 10.5165 14.2963 11.5427 13.6515L14.0003 14.0026L13.6493 11.5451C14.2943 10.5188 14.6673 9.30427 14.6673 8.0026ZM9.53271 4.90821C9.17249 4.59038 8.69733 4.42965 8.09538 4.42965C7.40443 4.42965 6.87353 4.62549 6.49142 5.00899L6.49031 5.01011C6.10731 5.38555 5.91113 5.89787 5.91113 6.55934V6.58788H6.92834V6.55934C6.92834 6.186 7.00316 5.88407 7.16637 5.66942C7.35011 5.41021 7.64478 5.29692 8.03181 5.29692C8.34206 5.29692 8.6007 5.37861 8.78036 5.55472L8.78283 5.55714C8.95394 5.7338 9.03537 5.97228 9.03537 6.26554C9.03537 6.4892 8.94804 6.6972 8.78703 6.89889L8.78139 6.90595L8.62913 7.07178L8.35539 7.31521L8.23731 7.42503L8.0271 7.63165C7.80455 7.86045 7.6682 8.03969 7.60292 8.17753L7.60164 8.18025L7.56817 8.2469C7.47946 8.44276 7.42756 8.73331 7.41978 9.22348H8.4573C8.49181 8.50677 8.80055 8.14573 8.96934 8.00587L9.28505 7.73273L9.58341 7.46308L9.67835 7.37044L9.73842 7.30517C9.96924 7.01379 10.0889 6.64468 10.0889 6.20321C10.0889 5.65678 9.90079 5.22396 9.53412 4.90944L9.53271 4.90821ZM7.94792 11.3333C8.31611 11.3333 8.61458 11.0349 8.61458 10.6667C8.61458 10.2985 8.31611 10 7.94792 10C7.57973 10 7.28125 10.2985 7.28125 10.6667C7.28125 11.0349 7.57973 11.3333 7.94792 11.3333Z"
                    fill="currentColor"
                />
            </svg>
            <span class="classify-tag__title">{{ displayTitle }}</span>
            <svg
                class="classify-tag__arrow"
                :class="{ 'classify-tag__arrow--up': !collapsed }"
                width="16"
                height="16"
                viewBox="0 0 16 16"
                fill="none"
                xmlns="http://www.w3.org/2000/svg"
            >
                <path
                    d="M4 6L8 10L12 6"
                    stroke="currentColor"
                    stroke-width="1.5"
                    stroke-linecap="round"
                    stroke-linejoin="round"
                />
            </svg>
        </div>

        <!-- 问题与选项 -->
        <div v-show="!collapsed" class="classify-tag__content">
            <div
                v-for="(question, qIdx) in displayQuestions"
                :key="question.id"
                class="classify-tag__question-group"
            >
                <div class="classify-tag__question-text">
                    {{ qIdx + 1 }}、{{ question.text }}
                    <span v-if="question.isMulti" class="classify-tag__multi-hint">
                        {{ mergedI18n.clarifyMultiHint }}
                    </span>
                </div>
                <div class="classify-tag__options">
                    <div
                        v-for="(option, oIdx) in question.options"
                        :key="oIdx"
                        class="classify-tag__option-wrapper"
                    >
                        <!-- 单选 -->
                        <label
                            v-if="!question.isMulti"
                            class="classify-tag__radio"
                            :class="{
                                'classify-tag__radio--checked': isRadioChecked(question.id, oIdx),
                            }"
                            @click="selectOption(question.id, oIdx)"
                        >
                            <span class="classify-tag__radio-circle">
                                <span
                                    v-if="isRadioChecked(question.id, oIdx)"
                                    class="classify-tag__radio-dot"
                                ></span>
                            </span>
                            <span class="classify-tag__radio-content">
                                <span class="classify-tag__radio-label">{{ option.label }}</span>
                                <span v-if="option.description" class="classify-tag__radio-desc">
                                    {{ option.description }}
                                </span>
                            </span>
                        </label>

                        <!-- 多选 -->
                        <label
                            v-else
                            class="classify-tag__checkbox"
                            :class="{
                                'classify-tag__checkbox--checked': isChecked(question.id, oIdx),
                            }"
                            @click="toggleCheckbox(question.id, oIdx)"
                        >
                            <span class="classify-tag__checkbox-box">
                                <svg
                                    v-if="isChecked(question.id, oIdx)"
                                    class="classify-tag__checkbox-tick"
                                    width="10"
                                    height="8"
                                    viewBox="0 0 10 8"
                                    fill="none"
                                    xmlns="http://www.w3.org/2000/svg"
                                >
                                    <path
                                        d="M1 4L3.5 6.5L9 1"
                                        stroke="currentColor"
                                        stroke-width="1.5"
                                        stroke-linecap="round"
                                        stroke-linejoin="round"
                                    />
                                </svg>
                            </span>
                            <span class="classify-tag__radio-content">
                                <span class="classify-tag__radio-label">{{ option.label }}</span>
                                <span v-if="option.description" class="classify-tag__radio-desc">
                                    {{ option.description }}
                                </span>
                            </span>
                        </label>

                        <!-- 「其他」选项的补充输入框 -->
                        <div v-if="option.isOther" class="classify-tag__other-input-wrapper">
                            <AutoTextarea
                                :model-value="getOtherInput(question.id)"
                                :placeholder="mergedI18n.clarifyOtherPlaceholder"
                                :disabled="!isOtherSelected(question.id) || submitted || disabled"
                                :max-length="OTHER_INPUT_MAX_LENGTH"
                                :error-text="mergedI18n.clarifyOverLimit"
                                @update:model-value="(val: string) => handleOtherInput(question.id, val)"
                            />
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- 操作区 -->
        <div v-show="!collapsed" class="classify-tag__footer">
            <div class="classify-tag__footer-divider"></div>
            <div class="classify-tag__footer-actions">
                <div class="classify-tag__footer-buttons">
                    <button
                        type="button"
                        class="classify-tag__btn classify-tag__btn--primary"
                        :disabled="!allAnswered || submitted || disabled"
                        @click="handleSubmit"
                    >
                        {{ submitted ? mergedI18n.clarifySubmitted : mergedI18n.clarifySubmit }}
                    </button>
                    <button
                        v-if="!submitted"
                        type="button"
                        class="classify-tag__btn classify-tag__btn--secondary"
                        :disabled="disabled"
                        @click="handleSkip"
                    >
                        {{ mergedI18n.clarifySkip }}
                    </button>
                </div>
            </div>
        </div>
    </div>
</template>

<style scoped>
.classify-tag {
    margin: 8px 0;
    border: 1px solid var(--td-border-level-1-color);
    border-radius: var(--td-radius-medium);
    background: var(--td-bg-color-container);
    overflow: hidden;
}

/* 标题栏 */
.classify-tag__header {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 12px;
    background: var(--td-bg-color-secondarycontainer);
    cursor: pointer;
    user-select: none;
}

.classify-tag__icon {
    flex-shrink: 0;
    width: 16px;
    height: 16px;
    color: var(--td-brand-color);
}

.classify-tag__title {
    flex: 1;
    font-size: 12px;
    line-height: 16px;
    color: var(--td-text-color-secondary);
}

.classify-tag__arrow {
    flex-shrink: 0;
    width: 16px;
    height: 16px;
    color: var(--td-text-color-placeholder);
    transition: transform 0.2s ease;
}

.classify-tag__arrow--up {
    transform: rotate(180deg);
}

/* 问题区 */
.classify-tag__content {
    display: flex;
    flex-direction: column;
    gap: 16px;
    padding: 12px;
    border-top: 1px solid var(--td-border-level-1-color);
}

.classify-tag__question-group {
    display: flex;
    flex-direction: column;
    gap: 8px;
}

.classify-tag__question-text {
    font-size: 12px;
    line-height: 24px;
    color: var(--td-text-color-primary);
}

.classify-tag__multi-hint {
    margin-left: 4px;
    font-size: 11px;
    color: var(--td-brand-color);
}

.classify-tag__options {
    display: flex;
    flex-direction: column;
    gap: 12px;
}

.classify-tag__option-wrapper {
    display: flex;
    flex-direction: column;
    gap: 8px;
}

/* 单选 */
.classify-tag__radio,
.classify-tag__checkbox {
    display: flex;
    align-items: flex-start;
    gap: 8px;
    min-height: 20px;
    cursor: pointer;
}

.classify-tag__radio-circle {
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    width: 16px;
    height: 16px;
    margin-top: 2px;
    border: 1px solid var(--td-component-border);
    border-radius: 50%;
    background: var(--td-bg-color-container);
    transition: border-color 0.2s ease;
    /* 控件本身不参与文本选中 */
    user-select: none;
}

.classify-tag__radio:hover .classify-tag__radio-circle,
.classify-tag__radio--checked .classify-tag__radio-circle {
    border-color: var(--td-brand-color);
}

.classify-tag__radio-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--td-brand-color);
}

/* 多选 */
.classify-tag__checkbox-box {
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    width: 16px;
    height: 16px;
    margin-top: 2px;
    border: 1px solid var(--td-component-border);
    border-radius: 3px;
    background: var(--td-bg-color-container);
    color: var(--td-text-color-anti);
    transition: all 0.2s ease;
    user-select: none;
}

.classify-tag__checkbox:hover .classify-tag__checkbox-box {
    border-color: var(--td-brand-color);
}

.classify-tag__checkbox--checked .classify-tag__checkbox-box {
    border-color: var(--td-brand-color);
    background: var(--td-brand-color);
}

.classify-tag__checkbox-tick {
    display: block;
}

/* 选项文案：允许框选复制 */
.classify-tag__radio-content {
    display: flex;
    flex-direction: column;
    gap: 2px;
    flex: 1;
    min-width: 0;
    user-select: text;
    -webkit-user-select: text;
    cursor: text;
}

.classify-tag__radio-label {
    font-size: 12px;
    line-height: 20px;
    color: var(--td-text-color-primary);
    user-select: text;
    -webkit-user-select: text;
}

.classify-tag__radio-desc {
    font-size: 11px;
    line-height: 16px;
    color: var(--td-text-color-placeholder);
    user-select: text;
    -webkit-user-select: text;
}

/* 「其他」输入框缩进对齐选项文案 */
.classify-tag__other-input-wrapper {
    padding-left: 24px;
}

/* 操作区 */
.classify-tag__footer {
    position: relative;
    padding: 16px;
}

.classify-tag__footer-divider {
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    height: 1px;
    background: var(--td-border-level-1-color);
}

.classify-tag__footer-actions {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
}

.classify-tag__footer-buttons {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-shrink: 0;
    margin-left: auto;
}

.classify-tag__btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 6px 16px;
    border: 1px solid transparent;
    border-radius: 3px;
    font-size: 13px;
    line-height: 20px;
    font-family: inherit;
    cursor: pointer;
    outline: none;
    transition: all 0.2s ease;
}

.classify-tag__btn--primary {
    background: var(--td-bg-color-component-disabled);
    border-color: var(--td-border-level-1-color);
    color: var(--td-text-color-disabled);
}

.classify-tag__btn--primary:not(:disabled) {
    background: var(--td-brand-color);
    border-color: var(--td-brand-color);
    color: var(--td-text-color-anti);
}

.classify-tag__btn--primary:not(:disabled):hover {
    background: var(--td-brand-color-hover);
    border-color: var(--td-brand-color-hover);
}

.classify-tag__btn--primary:disabled {
    cursor: not-allowed;
}

.classify-tag__btn--secondary {
    background: var(--td-bg-color-container);
    border-color: var(--td-component-border);
    color: var(--td-text-color-primary);
}

.classify-tag__btn--secondary:not(:disabled):hover {
    background: var(--td-bg-color-container-hover);
}

.classify-tag__btn--secondary:disabled {
    cursor: not-allowed;
    color: var(--td-text-color-disabled);
}
</style>
