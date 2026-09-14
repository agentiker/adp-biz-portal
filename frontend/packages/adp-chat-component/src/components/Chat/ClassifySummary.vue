<!--
  已澄清摘要折叠卡：澄清提交（或跳过 / 过期）后替代交互卡展示问答结果。

  迁移说明：等价移植自 smart-webim 的 ClassifySummary.vue（Vue 2 Options API），
  改写为 Vue 3 + TS，硬编码色值替换为 theme.css 的 --td-* 变量。

  注意：defaultCollapsed 由父级根据「已澄清个数」决定——
  已澄清 0 个（跳过或过期未提交）时默认折叠，否则默认展开。
-->
<script setup lang="ts">
import { ref } from 'vue';
import type { QuestionnaireSummaryItem } from '../../model/chat-v2';

interface Props {
    /** 标题文案，如「已澄清 3 个问题」 */
    title?: string;
    /** 问答摘要列表 */
    items?: QuestionnaireSummaryItem[];
    /** 是否默认折叠 */
    defaultCollapsed?: boolean;
}

const props = withDefaults(defineProps<Props>(), {
    title: '',
    items: () => [],
    defaultCollapsed: false,
});

const collapsed = ref(props.defaultCollapsed);

function toggleCollapse(): void {
    collapsed.value = !collapsed.value;
}
</script>

<template>
    <div class="classify-summary">
        <div class="classify-summary__header" @click="toggleCollapse">
            <svg
                class="classify-summary__icon"
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
            <span class="classify-summary__title">{{ title }}</span>
            <svg
                class="classify-summary__arrow"
                :class="{ 'classify-summary__arrow--collapsed': collapsed }"
                width="16"
                height="16"
                viewBox="0 0 16 16"
                fill="none"
                xmlns="http://www.w3.org/2000/svg"
            >
                <path
                    fill-rule="evenodd"
                    clip-rule="evenodd"
                    d="M7.9921 5.06676C8.16673 5.0636 8.34237 5.12865 8.47563 5.26191L12.997 9.78325C13.2573 10.0436 13.2573 10.4657 12.997 10.7261C12.7366 10.9864 12.3145 10.9864 12.0542 10.7261L8.00016 6.67206L3.94593 10.7263C3.68558 10.9866 3.26347 10.9866 3.00312 10.7263C2.74277 10.4659 2.74277 10.0438 3.00312 9.78348L7.52459 5.26201C7.65377 5.13283 7.82278 5.06774 7.9921 5.06676Z"
                    fill="currentColor"
                />
            </svg>
        </div>
        <div v-show="!collapsed" class="classify-summary__content">
            <div
                v-for="(item, idx) in items"
                :key="idx"
                class="classify-summary__item"
            >
                <div class="classify-summary__question">{{ idx + 1 }}、{{ item.question }}</div>
                <div class="classify-summary__answer">{{ item.answerLabel }}</div>
            </div>
        </div>
    </div>
</template>

<style scoped>
.classify-summary {
    margin: 8px 0;
    border: 1px solid var(--td-border-level-1-color);
    border-radius: var(--td-radius-medium);
    background: var(--td-bg-color-container);
    overflow: hidden;
}

.classify-summary__header {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 12px;
    background: var(--td-bg-color-secondarycontainer);
    cursor: pointer;
    user-select: none;
}

.classify-summary__icon {
    flex-shrink: 0;
    width: 16px;
    height: 16px;
    color: var(--td-brand-color);
}

.classify-summary__title {
    flex: 1;
    font-size: 12px;
    line-height: 16px;
    color: var(--td-text-color-secondary);
}

.classify-summary__arrow {
    flex-shrink: 0;
    width: 16px;
    height: 16px;
    color: var(--td-text-color-placeholder);
    transition: transform 0.2s ease;
}

.classify-summary__arrow--collapsed {
    transform: rotate(180deg);
}

.classify-summary__content {
    display: flex;
    flex-direction: column;
    gap: 16px;
    padding: 12px;
    border-top: 1px solid var(--td-border-level-1-color);
}

.classify-summary__item {
    display: flex;
    flex-direction: column;
    gap: 8px;
}

.classify-summary__question {
    font-size: 12px;
    line-height: 20px;
    color: var(--td-text-color-placeholder);
}

.classify-summary__answer {
    font-size: 13px;
    line-height: 20px;
    color: var(--td-text-color-primary);
}
</style>
