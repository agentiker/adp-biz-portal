<!-- 模型选择器：基于 tdesign-vue-next 实现，支持搜索、分组、UI 标签、禁用、资源不可用提示等 -->
<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import {
    Popup as TPopup,
    Input as TInput,
    Tag as TTag,
    Tooltip as TTooltip,
    Button as TButton,
    Loading as TLoading,
    MessagePlugin,
} from 'tdesign-vue-next';
import CustomizedIcon from '../CustomizedIcon.vue';
import { fetchModelList, type ListModelRawItem } from '../../service/api';
import useAgentStore from '../../composables/useAgentStore';
import type { ThemeProps } from '../../model/type';
import { themePropsDefaults } from '../../model/type';

/** 接口下发的 UI 标签 */
export interface ModelUiTag {
    /** 标签文案 */
    text: string;
    /** 标签主题：info / success / warning / danger */
    theme?: 'info' | 'success' | 'warning' | 'danger' | string;
    /** 鼠标悬浮提示 */
    tips?: string;
}

/** 模型选项 */
export interface ModelOption {
    /** 唯一值（与 selected.value 对齐） */
    value: string;
    /** 模型名（用于内部 key 等） */
    name?: string;
    /** 展示名 */
    text: string;
    /** 模型图标 */
    icon?: string;
    /** 描述（hover 右侧 Tooltip 展示） */
    model_desc?: string;
    /** 模型 token 限制等左侧 chip 文案 */
    prompt_words_limit?: string;
    /** 模型能力标签 */
    model_tags?: string[];
    /** 接口下发的 UI 标签 */
    model_ui_tags?: ModelUiTag[];
    /** 资源状态：2=资源不可用 */
    resource_status?: number;
    /** 是否专属资源 */
    is_exclusive?: boolean;
    /** 提供方类型：Self=自有，Third=第三方 */
    provider_type?: 'Self' | 'Third' | string;
    /** 提供方分组名 */
    provider_ailas_name?: string;
    /** 是否为限时免费 */
    is_free?: boolean;
    /** 是否为分组头部（动态标记，由 addSourceHeadFlag 注入） */
    sourceHead?: boolean;
}

/** 选中模型（与 ModelOption 兼容） */
export type SelectedModel = Partial<ModelOption> & { value?: string; text?: string };

/** 模型选择器 i18n 文本 */
export interface ModelSelectorI18n {
    /** 触发器占位（未选中时） */
    placeholder?: string;
    /** 升级提示（第三方模型受限时 tooltip 文案） */
    upgradeTip?: string;
    /** 升级按钮 */
    upgradeAction?: string;
    /** 分组头「升级」标签 */
    upgradeTag?: string;
    /** 搜索框 placeholder */
    searchPlaceholder?: string;
    /** 加载中 */
    loading?: string;
    /** 暂无数据 */
    empty?: string;
    /** 资源不可用 */
    resourceUnavailable?: string;
    /** 切换模型失败 toast */
    switchModelFailed?: string;
}

const defaultModelSelectorI18n: Required<ModelSelectorI18n> = {
    placeholder: '请选择',
    upgradeTip: '企业版可使用第三方模型',
    upgradeAction: '去升级',
    upgradeTag: '升级',
    searchPlaceholder: '搜索',
    loading: '加载中...',
    empty: '暂无数据',
    resourceUnavailable: '资源不可用',
    switchModelFailed: '切换模型失败',
};

const defaultModelSelectorI18nEn: Required<ModelSelectorI18n> = {
    placeholder: 'Select',
    upgradeTip: 'Enterprise plan required to use third-party models',
    upgradeAction: 'Upgrade',
    upgradeTag: 'Upgrade',
    searchPlaceholder: 'Search',
    loading: 'Loading...',
    empty: 'No data',
    resourceUnavailable: 'Resource unavailable',
    switchModelFailed: 'Failed to switch model',
};

interface Props extends ThemeProps {
    /** 候选模型列表（受控逗逃口：传入非空数组时使用父层数据，否则由组件内部拉取） */
    options?: ModelOption[];
    /** 当前选中模型 */
    selected?: SelectedModel;
    /** 历史对话选中的模型（用于非企业版时保留显示） */
    historyModel?: SelectedModel | null;
    /**
     * 占位文案（外部 prop 优先；未传时由 i18n.placeholder → language 默认值 fallback）
     * @deprecated 优先使用 `i18n.placeholder`，本 prop 仅为兼容旧调用方。
     */
    placeholder?: string;
    /** 是否为按钮模式（紧凑形态） */
    isButtonMode?: boolean;
    /** 是否为企业版用户（控制第三方模型可否选择） */
    isEnterpriseUser?: boolean;
    /** 是否为海外站（海外站所有套餐都可使用第三方模型） */
    isIntl?: boolean;

    /**
     * 升级提示文案（外部 prop 优先；未传时由 i18n.upgradeTip → language 默认值 fallback）
     * @deprecated 优先使用 `i18n.upgradeTip`。
     */
    upgradeTipText?: string;
    /**
     * 升级按钮文案（外部 prop 优先；未传时由 i18n.upgradeAction → language 默认值 fallback）
     * @deprecated 优先使用 `i18n.upgradeAction`。
     */
    upgradeActionText?: string;
    /** 弹层最大高度 */
    listMaxHeight?: number;
    /** 是否在挂载时自动拉取模型列表 */
    autoFetch?: boolean;
    /** 应用 ID（用于拉取模型列表时传递 AppBizId） */
    applicationId?: string;
    /** 当前语言标识，用于自动选择内部默认 i18n（如 'zh-CN'、'en-US'） */
    language?: string;
    /** 组件内文案 i18n 覆盖 */
    i18n?: Partial<ModelSelectorI18n>;
}

const props = withDefaults(defineProps<Props>(), {
    ...themePropsDefaults,
    options: () => [],
    selected: () => ({} as SelectedModel),
    historyModel: null,
    placeholder: '',
    isButtonMode: false,
    isEnterpriseUser: true,
    isIntl: false,

    upgradeTipText: '',
    upgradeActionText: '',
    listMaxHeight: 264,
    autoFetch: true,
    applicationId: '',
    language: 'zh-CN',
    i18n: () => ({}),
});

const emit = defineEmits<{
    (e: 'update:selected', model: ModelOption): void;
    (e: 'change', model: ModelOption): void;

    (e: 'upgradeClick'): void;
    (e: 'consoleBuy'): void;
    (e: 'buyPkg'): void;
    (e: 'update:options', options: ModelOption[]): void;
    (e: 'options-loaded', options: ModelOption[]): void;
    (e: 'fetch-error', err: unknown): void;
    (e: 'update:loading', loading: boolean): void;
}>();

/** 弹层可见性 */
const popupVisible = ref(false);
/** 搜索关键字 */
const searchValue = ref('');
/** 内部拉取的模型列表（父层未传 options 时使用） */
const innerOptions = ref<ModelOption[]>([]);
/** 请求 loading */
const loading = ref(false);
/** 内部选中状态（优先使用 props.selected，否则使用内部维护的值） */
const innerSelected = ref<ModelOption | null>(null);

/**
 * 合并 i18n：按 language 选择内部默认（zh/en），再叠加外部 props.i18n。
 */
const mergedI18n = computed<Required<ModelSelectorI18n>>(() => {
    const defaults = props.language?.startsWith('en')
        ? defaultModelSelectorI18nEn
        : defaultModelSelectorI18n;
    return { ...defaults, ...props.i18n };
});

/** 触发器占位文案：外部 prop 优先，其次走 i18n */
const displayPlaceholder = computed(() => props.placeholder || mergedI18n.value.placeholder);
/** 升级提示文案 */
const displayUpgradeTip = computed(() => props.upgradeTipText || mergedI18n.value.upgradeTip);
/** 升级按钮文案 */
const displayUpgradeAction = computed(() => props.upgradeActionText || mergedI18n.value.upgradeAction);

/** 监听外部 props.selected 变化，同步更新内部状态 */
watch(
    () => props.selected,
    (newVal) => {
        if (newVal && newVal.value) {
            innerSelected.value = newVal as ModelOption;
        }
    },
    { immediate: true, deep: true },
);

/** 当前实际展示的选中模型 */
const currentSelected = computed<SelectedModel | undefined>(() => {
    // 如果外部传入了有效的 selected（有 value），以外部为准
    if (props.selected && props.selected.value) return props.selected;
    // 否则使用内部选中状态
    return innerSelected.value || undefined;
});

/** 原始接口字段 -> ModelOption 映射 */
function mapRawToOption(raw: ListModelRawItem): ModelOption {
    return {
        value: raw.ModelName,
        name: raw.ModelName,
        text: raw.AliasName || raw.ModelName,
        icon: raw.Icon || '',
        model_desc: raw.ModelDesc,
        prompt_words_limit: raw.PromptWordsLimit,
        model_tags: raw.ModelTags || [],
        model_ui_tags: raw.ModelUiTags || [],
        resource_status: raw.ResourceStatus,
        is_exclusive: raw.IsExclusive,
        provider_type: (raw.ProviderType as ModelOption['provider_type']) || 'Third',
        provider_ailas_name: raw.ProviderAliasName,
        is_free: raw.IsFree,
    } as ModelOption;
}

/** 拉取模型列表 */
async function loadModelList(): Promise<ModelOption[]> {
    loading.value = true;
    emit('update:loading', true);
    try {
        const list = await fetchModelList(          
            {
                AppType: 'knowledge_qa',
                Pattern: 'ClawAgent',  
                ModelCategory: "corp_assistant",              
                SpaceId: 'default_space',
            },
            props.applicationId
        );
        const mapped = (list || []).map(mapRawToOption);
        innerOptions.value = mapped;
        emit('update:options', mapped);
        emit('options-loaded', mapped);
        return mapped;
    } catch (err) {
        emit('fetch-error', err);
        return [];
    } finally {
        loading.value = false;
        emit('update:loading', false);
    }
}

/** 暴露给父层的手动刷新 */
function refresh(): Promise<ModelOption[]> {
    return loadModelList();
}

defineExpose({ refresh });

/** Agent store：用于读取当前 Agent 绑定模型 / 提交模型变更 */
const { getAgentDetailByAppId, modifyAgentByPath } = useAgentStore();
/** 模型切换提交状态（提交期间禁止重复选择） */
const switchingModel = ref(false);

async function syncSelectedModelFromAgent(applicationId: string) {
    if (!applicationId) return;
    const detail = await getAgentDetailByAppId(applicationId);
    if (!detail?.model) return;
    const agentModel = detail.model;
    // 在已加载的模型列表中查找对应项
    const allOptions = effectiveOptions.value;
    const matched = allOptions.find((opt) => opt.value === agentModel.ModelId);
    if (matched) {
        // 使用列表中完整的 ModelOption（含 icon / tags 等完整信息）
        innerSelected.value = matched;
        emit('update:selected', matched);
        emit('change', matched);
    } else {
        // 列表中未找到：构造一个基本 ModelOption 作为选中态
        const fallback: ModelOption = {
            value: agentModel.ModelId,
            name: agentModel.ModelId,
            text: agentModel.Alias || agentModel.ModelId,
        };
        innerSelected.value = fallback;
        emit('update:selected', fallback);
        emit('change', fallback);
    }
}

onMounted(async () => {
    // 受控逗逃口：父层显式传入非空 options 时不自动拉取
    if (props.autoFetch && props.applicationId && (!props.options || props.options.length === 0)) {
        await loadModelList();
    }
    // 如果外部未传入有效选中，则从 AgentDetail 获取当前绑定模型
    if (props.applicationId && (!props.selected || !props.selected.value)) {
        await syncSelectedModelFromAgent(props.applicationId);
    }
});

// 监听 applicationId 变化，存在时重新拉取模型列表并同步 Agent 绑定模型
watch(
    () => props.applicationId,
    async (newId) => {
        if (newId && (!props.options || props.options.length === 0)) {
            await loadModelList();
        }
        // applicationId 变化后，若外部未指定选中模型，则从 AgentDetail 同步
        if (newId && (!props.selected || !props.selected.value)) {
            await syncSelectedModelFromAgent(newId);
        }
    },
);

/** 给列表添加分组头部标识：每个 provider 的首项 sourceHead=true */
function addSourceHeadFlag(list: ModelOption[]): ModelOption[] {
    if (!list || list.length === 0) return [];
    let lastProvider: string | undefined;
    return list.map((model) => {
        const currentProvider = model.provider_ailas_name;
        const isFirstInGroup = currentProvider !== lastProvider;
        lastProvider = currentProvider;
        return isFirstInGroup ? { ...model, sourceHead: true } : { ...model };
    });
}

/** 是否第三方受限模型（需企业版） */
function isThirdPartyModel(model: ModelOption): boolean {
    if (props.isIntl) return false;
    return !props.isEnterpriseUser && model.provider_type === 'Third';
}

/** 是否包含下线类标签 */
function isOfflineUiTagModel(model: ModelOption): boolean {
    const tags = model?.model_ui_tags || [];
    if (!Array.isArray(tags)) return false;
    return tags.some((t) => ['即将下线', '已下线'].includes(t.text));
}

/** 是否禁用 */
function isDisabledModel(model: ModelOption): boolean {
    return isThirdPartyModel(model) || isOfflineUiTagModel(model);
}

/** 当前生效的模型列表：父层显式传入非空 options 时使用父层数据，否则使用内部拉取的 innerOptions */
const effectiveOptions = computed<ModelOption[]>(() => {
    if (props.options && props.options.length > 0) return props.options;
    return innerOptions.value;
});

/** 经过过滤（企业版/历史模型保留）的基础列表 */
const filteredOptions = computed<ModelOption[]>(() => {
    const list = effectiveOptions.value;
    if (props.isIntl) return list;
    if (props.isEnterpriseUser) return list;
    // 非企业版：过滤掉第三方模型，但保留历史对话选中的第三方模型
    return list.filter((model) => {
        if (model.provider_type === 'Self') return true;
        if (props.historyModel && model.value === props.historyModel.value) return true;
        return false;
    });
});
/** 原始（带分组标识） */
const originOptions = computed<ModelOption[]>(() => addSourceHeadFlag(filteredOptions.value));

/** 渲染列表（应用搜索） */
const localOptions = computed<ModelOption[]>(() => {
    const query = searchValue.value.trim().toLowerCase();
    if (!query) return originOptions.value;
    return originOptions.value.filter((model) => {
        return (
            (model.text || '').toLowerCase().includes(query) ||
            (model.prompt_words_limit || '').toLowerCase().includes(query)
        );
    });
});

/** 当前选中模型资源是否不可用 */
const isSelectedResourceExhausted = computed(() => currentSelected.value?.resource_status === 2);

/** 当前选中模型 UI 标签 */
const selectedUiTags = computed<ModelUiTag[]>(() => {
    const tags = currentSelected.value?.model_ui_tags || [];
    return Array.isArray(tags) ? tags : [];
});

/** UI 标签 theme -> tdesign Tag theme */
function tagTheme(theme?: string): 'primary' | 'warning' | 'danger' | 'success' | 'default' {
    const map: Record<string, 'primary' | 'warning' | 'danger' | 'success' | 'default'> = {
        info: 'primary',
        success: 'success',
        warning: 'warning',
        danger: 'danger',
    };
    return map[theme || ''] || 'default';
}

/** 关键字高亮：返回 HTML 字符串（已做简单转义） */
function highlightText(text?: string, keyword?: string): string {
    const raw = text || '';
    const kw = (keyword || '').trim();
    const escaped = raw.replace(/[&<>"']/g, (c: string) => {
        const m: Record<string, string> = {
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&#39;',
        };
        return m[c] || c;
    });
    if (!kw) return escaped;
    const safeKw = kw.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    return escaped.replace(new RegExp(safeKw, 'gi'), (match) => `<em class="model-selector__highlight">${match}</em>`);
}

/** 选中模型：采用乐观更新策略 —— 立即关闭弹层并切换 UI，
 *  后台异步提交 ModifyAgent；失败时回滚到原选中态并提示。
 *  这样模型名称处会显示 loading 图标，而不会卡在选择列表上。
 */
async function handlePick(model: ModelOption) {
    if (!model || isDisabledModel(model)) return;
    if (switchingModel.value) return;

    // 同模型重复点击：仅关闭弹层，不发请求
    if (currentSelected.value?.value === model.value) {
        popupVisible.value = false;
        return;
    }

    // 1) 乐观更新：立即关闭弹层 + 切换本地选中态
    const prevSelected = innerSelected.value;
    innerSelected.value = model;
    emit('update:selected', model);
    emit('change', model);
    popupVisible.value = false;

    // 2) 无 applicationId 时跳过持久化（保持纯展示组件的可用性）
    if (!props.applicationId) return;

    // 3) 后台异步提交（触发器上的 loading 图标由 switchingModel 驱动）
    switchingModel.value = true;
    try {
        // 仅传 ModelId / Alias 两个必要字段，其它由后端从模型元信息推断
        // 对齐 v3 AgentModelConfig.json_name：ModelId / Alias
        await modifyAgentByPath(props.applicationId, {
            model: {
                ModelId: model.value,
                Alias: model.text || '',
            },
        });
    } catch (err) {
        console.error('[ModelSelector] ModifyAgent 切换模型失败:', err);
        MessagePlugin.error(mergedI18n.value.switchModelFailed);
        // 4) 失败回滚：恢复到提交前的选中态
        innerSelected.value = prevSelected;
        if (prevSelected) {
            emit('update:selected', prevSelected);
            emit('change', prevSelected);
        }
    } finally {
        switchingModel.value = false;
    }
}

/** 阻止分组标题点击冒泡导致选中 */
function preventClick(e: Event) {
    e.preventDefault();
    e.stopPropagation();
}

/** 弹层可见性变化：每次打开时清空搜索 */
function handleVisibleChange(visible: boolean) {
    popupVisible.value = visible;
    if (!visible) {
        searchValue.value = '';
    }
}

function handleClear() {
    searchValue.value = '';
}



function handleUpgradeClick() {
    emit('upgradeClick');
}

/** 当弹层关闭时，确保搜索内容清空 */
watch(popupVisible, (v) => {
    if (!v) searchValue.value = '';
});
</script>

<template>
    <div
        class="model-selector"
        :class="{ 'model-selector--button': isButtonMode }"
        :style="{ width: isButtonMode ? '100%' : '368px' }"
    >
        <t-popup
            :visible="popupVisible"
            trigger="click"
            placement="bottom-left"
            :show-arrow="false"
            overlay-class-name="model-selector__popup"
            destroy-on-close
            @visible-change="handleVisibleChange"
        >
            <!-- 触发器 -->
            <template v-if="isButtonMode">
                <t-button theme="default" variant="text" class="model-selector__trigger-btn">
                    <span class="model-selector__trigger-inner">
                        <span v-if="currentSelected && currentSelected.icon" class="model-selector__trigger-icon">
                            <img :src="currentSelected.icon" alt="" />
                        </span>
                        <span class="model-selector__trigger-text" :title="currentSelected && currentSelected.text">
                            {{ (currentSelected && currentSelected.text) || displayPlaceholder }}
                        </span>
                        <!-- 模型切换中：在模型名称右侧显示 loading 图标，提示后台保存中 -->
                        <t-loading v-if="switchingModel" size="14px" class="model-selector__switching" />
                        <t-tooltip
                            v-for="(uiTag, idx) in selectedUiTags"
                            :key="`sel-ui-tag-btn-${idx}`"
                            :content="uiTag.tips"
                            placement="top"
                            :disabled="!uiTag.tips"
                        >
                            <t-tag  :theme="tagTheme(uiTag.theme)" variant="light">
                                {{ uiTag.text }}
                            </t-tag>
                        </t-tooltip>
                        <CustomizedIcon remote name="arrow_down_line" size="s" :show-hover-bg="false" :theme="theme" />
                    </span>
                </t-button>
            </template>
            <template v-else>
                <div
                    class="model-selector__header"
                    :class="{ 'model-selector__header--warning': isSelectedResourceExhausted }"
                >
                    <div class="model-selector__header-left">
                        <span v-if="currentSelected && currentSelected.icon" class="model-selector__trigger-icon">
                            <img :src="currentSelected.icon" alt="" />
                        </span>
                        <span class="model-selector__trigger-text" :title="currentSelected && currentSelected.text">
                            {{ (currentSelected && currentSelected.text) || displayPlaceholder }}
                        </span>
                        <!-- 模型切换中：在模型名称右侧显示 loading 图标 -->
                        <t-loading v-if="switchingModel" size="14px" class="model-selector__switching" />
                        <t-tooltip
                            v-for="(uiTag, idx) in selectedUiTags"
                            :key="`sel-ui-tag-${idx}`"
                            :content="uiTag.tips"
                            placement="top"
                            :disabled="!uiTag.tips"
                        >
                            <t-tag  :theme="tagTheme(uiTag.theme)" variant="light">
                                {{ uiTag.text }}
                            </t-tag>
                        </t-tooltip>
                        <t-tooltip v-if="isSelectedResourceExhausted" placement="top">
                            <template #content>
                                <slot name="resourceErrorTip" :is-exclusive="currentSelected && currentSelected.is_exclusive">
                                    <span>{{ mergedI18n.resourceUnavailable }}</span>
                                </slot>
                            </template>
                            <CustomizedIcon remote class="model-selector__warning-icon" name="basic_warning_line" size="s" :show-hover-bg="false" :theme="theme" color="var(--td-error-color)" />
                        </t-tooltip>
                    </div>
                    <CustomizedIcon remote class="model-selector__arrow" name="arrow_down_line" size="s" :show-hover-bg="false" :theme="theme" />
                </div>
            </template>

            <!-- 弹层内容 -->
            <template #content>
                <div class="model-selector__panel">
                    <t-input
                        v-model="searchValue"
                        class="model-selector__search"
                        :placeholder="mergedI18n.searchPlaceholder"
                        clearable
                        @clear="handleClear"
                    >
                        <template #prefix-icon>
                            <CustomizedIcon remote name="basic_search_line" size="xs" :show-hover-bg="false" :theme="theme" />
                        </template>
                    </t-input>

                    <div
                        class="model-selector__list"
                        :style="{ maxHeight: `${listMaxHeight}px` }"
                    >
                        <template v-if="localOptions.length > 0">
                            <div v-for="item in localOptions" :key="item.value" class="model-selector__row">
                                <!-- 分组头部 -->
                                <div
                                    v-if="item.sourceHead && !searchValue.trim()"
                                    class="model-selector__group-head"
                                    @click="preventClick"
                                >
                                    <span>{{ item.provider_ailas_name }}</span>
                                    <!-- 第三方模型分组头：显示升级标签 -->
                                    <t-tooltip
                                        v-if="isThirdPartyModel(item)"
                                        placement="top"
                                        overlay-class-name="model-selector__upgrade-tip"
                                    >
                                        <template #content>
                                            <div class="model-selector__upgrade-tip-content">
                                                <span>{{ displayUpgradeTip }}</span>
                                                <t-button
                                                    theme="primary"
                                                    variant="text"
                                                    
                                                    @click="handleUpgradeClick"
                                                >
                                                    {{ displayUpgradeAction }}
                                                </t-button>
                                            </div>
                                        </template>
                                        <t-tag  theme="primary" variant="light-outline">
                                            <template #icon>
                                                <CustomizedIcon remote name="basic_star_line" size="s" :show-hover-bg="false" :theme="theme" />
                                            </template>
                                            {{ mergedI18n.upgradeTag }}
                                        </t-tag>
                                    </t-tooltip>
                                </div>

                                <!-- 选项 -->
                                <div
                                    class="model-selector__item"
                                    :class="{
                                        'is-disabled': isDisabledModel(item) || switchingModel,
                                        'is-active': currentSelected && currentSelected.value === item.value,
                                    }"
                                    @click="handlePick(item)"
                                >
                                    <div class="model-selector__item-left">
                                        <img v-if="item.icon" :src="item.icon" alt="" />
                                    </div>
                                    <div class="model-selector__item-right">
                                        <div class="model-selector__item-header">
                                            <t-tooltip
                                                v-if="item.model_desc"
                                                placement="right-top"
                                                overlay-class-name="model-selector__desc-tip"
                                            >
                                                <template #content>
                                                    <div class="model-selector__desc-tip-title">{{ item.text }}</div>
                                                    <div class="model-selector__desc-tip-content">
                                                        {{ item.model_desc }}
                                                    </div>
                                                </template>
                                                <span
                                                    class="model-selector__item-text"
                                                    v-html="highlightText(item.text, searchValue)"
                                                ></span>
                                            </t-tooltip>
                                            <span
                                                v-else
                                                class="model-selector__item-text"
                                                v-html="highlightText(item.text, searchValue)"
                                            ></span>

                                            <!-- 接口下发的 UI 标签 -->
                                            <t-tooltip
                                                v-for="(uiTag, uiIdx) in item.model_ui_tags || []"
                                                :key="`ui-tag-${item.value}-${uiIdx}`"
                                                :content="uiTag.tips"
                                                placement="top"
                                                :disabled="!uiTag.tips"
                                            >
                                                <t-tag
                                                    
                                                    :theme="tagTheme(uiTag.theme)"
                                                    variant="light"
                                                >
                                                    {{ uiTag.text }}
                                                </t-tag>
                                            </t-tooltip>

                                            <!-- 资源不可用警告 -->
                                            <t-tooltip
                                                v-if="item.resource_status === 2"
                                                placement="top"
                                                overlay-class-name="model-selector__err-tip"
                                            >
                                                <template #content>
                                                    <slot name="resourceErrorTip" :is-exclusive="item.is_exclusive">
                                                        <span>{{ mergedI18n.resourceUnavailable }}</span>
                                                    </slot>
                                                </template>
                                                <CustomizedIcon
                                                    remote
                                                    class="model-selector__warning-icon"
                                                    name="basic_warning_line"
                                                    size="s"
                                                    :show-hover-bg="false"
                                                    :theme="theme"
                                                    color="var(--td-error-color)"
                                                />
                                            </t-tooltip>
                                        </div>

                                        <div class="model-selector__item-tags">
                                            <span
                                                v-if="item.prompt_words_limit"
                                                class="model-selector__chip"
                                                v-html="highlightText(item.prompt_words_limit, searchValue)"
                                            ></span>
                                            <span
                                                v-for="(tag, tIdx) in (item.model_tags || []).slice(0, 4)"
                                                :key="`tag-${item.value}-${tIdx}`"
                                                class="model-selector__chip"
                                                v-html="highlightText(tag, searchValue)"
                                            ></span>
                                            <t-tooltip
                                                v-if="(item.model_tags || []).length > 4"
                                                :content="(item.model_tags || []).slice(4).join(',')"
                                                placement="top-right"
                                            >
                                                <span class="model-selector__chip more-tags">...</span>
                                            </t-tooltip>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </template>

                        <!-- 空数据 -->
                        <div v-else-if="loading" class="model-selector__empty">
                            {{ mergedI18n.loading }}
                        </div>
                        <div v-else class="model-selector__empty">
                            {{ mergedI18n.empty }}
                        </div>
                    </div>


                </div>
            </template>
        </t-popup>
    </div>
</template>

<style scoped>
.model-selector {
    display: inline-block;
}

.model-selector--button {
    width: 100%;
}

/* 普通模式触发器 */
.model-selector__header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    width: 100%;
    height: 32px;
    padding: 0 var(--td-size-4);
    background: var(--td-bg-color-container, #fff);
    border: 1px solid var(--td-component-border, rgba(16, 32, 69, 0.1));
    border-radius: var(--td-radius-default, 4px);
    cursor: pointer;
    box-sizing: border-box;
    transition: border-color 0.2s;
}

.model-selector__header:hover {
    border-color: var(--td-brand-color, #0052d9);
}

.model-selector__header--warning {
    border-color: var(--td-error-color, #d54941);
    background: var(--td-error-color-light, #fdecea);
}

.model-selector__header-left {
    display: flex;
    align-items: center;
    gap: var(--td-size-2);
    overflow: hidden;
}

.model-selector__trigger-text {
    max-width: 200px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--td-text-color-primary);
    font-size: var(--td-font-size-body-medium);
}

.model-selector__arrow {
    color: var(--td-text-color-placeholder);
    flex-shrink: 0;
}

.model-selector__warning-icon {
    color: var(--td-error-color, #d54941);
    font-size: var(--td-font-size-body-medium);
}

/* 模型切换中的 loading 图标：紧贴模型名称右侧 */
.model-selector__switching {
    display: inline-flex;
    align-items: center;
    color: var(--td-brand-color, #0052d9);
    flex-shrink: 0;
}

/* 按钮模式触发器 */
.model-selector__trigger-btn {
    padding: var(--td-size-2) var(--td-size-4);
    outline: none;
}

.model-selector__trigger-inner {
    display: inline-flex;
    align-items: center;
    gap: var(--td-size-2);
    font-size: var(--td-font-size-body-small);
}

.model-selector__trigger-icon img {
    width: 16px;
    height: 16px;
    display: block;
}

/* 弹层面板 */
.model-selector__panel {
    width: 368px;
    box-sizing: border-box;
    padding: var(--td-size-4);
}

.model-selector__search {
    margin-bottom: var(--td-size-4);
}

/* 列表 */
.model-selector__list {
    overflow-y: auto;
    overflow-x: hidden;
    scrollbar-color: var(--td-scrollbar-color) transparent;
    scrollbar-width: thin;
}

.model-selector__list::-webkit-scrollbar {
    width: 4px;
    background: transparent;
}

.model-selector__list::-webkit-scrollbar-thumb {
    border-radius: var(--td-radius-small);
    background-color: var(--td-scrollbar-color, rgba(0, 0, 0, 0.1));
}

.model-selector__list::-webkit-scrollbar-thumb:hover {
    background-color: var(--td-scrollbar-hover-color, rgba(0, 0, 0, 0.3));
}

.model-selector__group-head {
    display: flex;
    align-items: center;
    gap: var(--td-size-4);
    padding: 6px 12px 2px;
    color: var(--td-text-color-placeholder, rgba(0, 0, 0, 0.4));
    font-size: var(--td-font-size-body-small);
    font-weight: 400;
    line-height: 16px;
    cursor: default;
}

.model-selector__item {
    display: flex;
    flex-direction: row;
    gap: var(--td-size-4);
    padding: 8px 12px;
    border-radius: var(--td-radius-default, 4px);
    cursor: pointer;
    transition: background-color 0.2s;
}

.model-selector__item:hover {
    background: var(--td-bg-color-container-hover, #f3f3f3);
}

.model-selector__item.is-active {
    background: var(--td-brand-color-light, #ecf2fe);
}

.model-selector__item.is-disabled {
    opacity: 0.5;
    cursor: not-allowed;
}

.model-selector__item.is-disabled:hover {
    background: transparent;
}

.model-selector__item-left {
    height: 44px;
    flex-shrink: 0;
}

.model-selector__item-left img {
    width: 20px;
    height: 20px;
    padding: var(--td-size-1);
    border-radius: var(--td-radius-small);
    display: block;
}

.model-selector__item-right {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: var(--td-size-2);
    flex: 1;
    min-width: 0;
}

.model-selector__item-header {
    display: flex;
    align-items: center;
    gap: var(--td-size-2);
    width: 100%;
    min-width: 0;
}

.model-selector__item-text {
    flex: 0 1 auto;
    min-width: 20px;
    max-width: 220px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    color: var(--td-text-color-primary);
    font-size: var(--td-font-size-body-medium);
    line-height: var(--td-line-height-body-medium);
}

.model-selector__item-tags {
    display: flex;
    align-items: center;
    gap: var(--td-size-2);
    flex-wrap: wrap;
}

.model-selector__chip {
    font-size: var(--td-font-size-body-small);
    line-height: 16px;
    color: var(--td-text-color-placeholder);
    padding: var(--td-size-1) var(--td-size-3);
    border-radius: var(--td-radius-small);
    border: 1px solid var(--td-component-border, rgba(16, 32, 69, 0.1));
}

.more-tags {
    cursor: pointer;
}

.more-tags:hover {
    background: var(--td-bg-color-container-hover, #e5e7eb);
}

/* 高亮 */
.model-selector__item-text :deep(.model-selector__highlight),
.model-selector__chip :deep(.model-selector__highlight) {
    color: var(--td-brand-color, #0052d9);
    font-style: normal;
}

/* 空态 */
.model-selector__empty {
    height: 200px;
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--td-text-color-placeholder);
    font-size: var(--td-font-size-body-medium);
}


</style>

<style>
/* 非 scoped 样式：覆盖 popup 内部以便外部 overlay-class-name 生效 */
.model-selector__popup .t-popup__content {
    padding: 0;
}

.model-selector__upgrade-tip-content {
    display: inline-flex;
    align-items: center;
    column-gap: var(--td-size-2);
    white-space: nowrap;
}

.model-selector__desc-tip {
    max-width: 320px;
}

.model-selector__desc-tip-title {
    font-weight: 500;
    margin-bottom: var(--td-size-2);
}

.model-selector__desc-tip-content {
    white-space: normal;
    word-break: break-all;
}

.model-selector__highlight {
    color: var(--td-brand-color, #0052d9);
    font-style: normal;
}
</style>
