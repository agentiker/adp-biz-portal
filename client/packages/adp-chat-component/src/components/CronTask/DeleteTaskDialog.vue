<template>
    <t-dialog
        v-model:visible="dialogVisible"
        :header="mergedI18n.deleteDialogTitle"
        theme="danger"
        :confirm-btn="{ content: mergedI18n.del, theme: 'danger', loading }"
        :cancel-btn="mergedI18n.cancel"
        :close-on-overlay-click="!loading"
        :close-on-esc-keydown="!loading"
        :on-confirm="onConfirm"
        :on-close="onClose"
    >
        <div class="delete-task-dialog__content">{{ mergedI18n.deleteDialogContent }}</div>
    </t-dialog>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue';
import {
    Dialog as TDialog,
    MessagePlugin,
} from 'tdesign-vue-next';
import type { ThemeProps } from '../../model/type';
import { themePropsDefaults } from '../../model/type';
import type { CronTaskI18n, TimerTask, TimerTaskSummary } from '../../model/cronTask';
import { getCronTaskI18nByLanguage } from '../../model/cronTask';
import { AppTriggerScope } from '../../model/appTrigger';
import { deleteAppTrigger } from '../../service/appTriggerApi';
import { getTimerId } from '../../utils/cronTask';
import { getTriggerId } from '../../utils/appTrigger';

interface Props extends ThemeProps {
    visible: boolean;
    task?: TimerTask | TimerTaskSummary | Record<string, any> | null;
    applicationId: string;
    spaceId?: string;
    /**
     * 触发器作用域（proto AppTriggerScope）。
     * USER(2) = C 端访客，默认，需配合 userId；APP(1) = B 端管理员。
     */
    scope?: number;
    /** C 端访客 ID，scope=USER 时必填 */
    userId?: string;
    language?: string;
    i18n?: Partial<CronTaskI18n>;
}

const props = withDefaults(defineProps<Props>(), {
    ...themePropsDefaults,
    visible: false,
    task: null,
    spaceId: '',
    scope: AppTriggerScope.USER,
    userId: '',
    language: 'zh-CN',
    i18n: () => ({}),
});

const emit = defineEmits<{
    (e: 'update:visible', val: boolean): void;
    (e: 'success', task: any): void;
}>();

const mergedI18n = computed<Required<CronTaskI18n>>(() => ({
    ...getCronTaskI18nByLanguage(props.language),
    ...props.i18n,
}));

const loading = ref(false);

const dialogVisible = computed({
    get: () => props.visible,
    set: (val) => {
        if (loading.value) return;
        emit('update:visible', val);
    },
});

async function onConfirm() {
    // 兼容 AppTrigger:TriggerId + TimerTask:TimerId
    const id = getTriggerId(props.task) || getTimerId(props.task);
    if (!id) {
        emit('update:visible', false);
        return;
    }
    loading.value = true;
    try {
        await deleteAppTrigger(id, props.applicationId, props.scope, undefined, props.userId);
        MessagePlugin.success(mergedI18n.value.deleteSuccess);
        emit('success', props.task);
        emit('update:visible', false);
    } catch (e) {
        console.error('[DeleteTaskDialog] delete failed:', e);
        MessagePlugin.error(mergedI18n.value.deleteFailed);
    } finally {
        loading.value = false;
    }
}

function onClose() {
    if (loading.value) return;
    emit('update:visible', false);
}
</script>

<style scoped>
.delete-task-dialog__content {
    font-size: var(--td-font-size-body-medium);
    line-height: var(--td-line-height-body-medium);
    color: var(--td-text-color-secondary);
    padding: var(--td-size-4) 0;
}
</style>
