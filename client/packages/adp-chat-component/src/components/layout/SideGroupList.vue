<!--
  侧边栏分组列表组件
  @description
    通用的"标题 + 若干列表项"分组，用于在侧边栏承载「定时任务」「远程终端」「最近任务」等分组。
    UI 风格参考 HistoryList.vue，保持整体一致；结构参考 smart-webim/conversation-list.vue 的 task-group。
    组件本身不关心业务语义，仅负责渲染 + 事件外抛，具体数据 / 图标 / 激活态由父层决定。
-->
<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { Icon as TIcon, Dropdown as TDropdown } from 'tdesign-vue-next';
import CustomizedIcon from '../CustomizedIcon.vue';
import type { ThemeProps } from '../../model/type';
import { themePropsDefaults } from '../../model/type';

/** 分组列表项「更多操作」菜单选项（对齐 smart-webim task-group menuOptions） */
export interface SideGroupMenuOption {
    /** 菜单项显示文案 */
    label: string;
    /** 菜单项值，随 menuSelect 事件回传 */
    value: string;
}

/** 分组列表项 */
export interface SideGroupItem {
    /** 唯一 id，作为选中 / 事件参数 */
    id: string;
    /** 显示文案（会做 ellipsis） */
    label: string;
    /**
     * 前置图标名（可选）。传了就在标题前显示一枚小图标。
     * 默认走 CustomizedIcon 的远程图标库；若需本地图标可通过 iconRemote=false 关闭。
     */
    icon?: string;
    /** 是否远程图标（默认 true） */
    iconRemote?: boolean;
    /** 右上角的辅助文字（如更新时间），仅在非 hover/active 状态显示 */
    extraText?: string;
    /** 禁用点击（如未完成配置的远程终端占位） */
    disabled?: boolean;
}

interface Props extends ThemeProps {
    /** 分组标题（如"定时任务"/"远程终端"） */
    title: string;
    /** 列表项 */
    items?: SideGroupItem[];
    /** 当前选中项 id */
    activeId?: string;
    /**
     * 空数据时是否隐藏整个分组。true 表示 items 为空则完全不渲染，避免出现空标题。
     * 默认 true。
     */
    hideWhenEmpty?: boolean;
    /**
     * 是否显示右侧删除按钮（hover / active 才可见）。
     * 默认 false —— 定时任务 / 远程终端类分组一般不由这里发起删除。
     */
    showDelete?: boolean;
    /** 分组标题右侧「设置 / 添加」入口图标（如"渠道设置"）。传了才显示。 */
    headerActionIcon?: string;
    /** 分组标题右侧入口 tooltip 文案 */
    headerActionTip?: string;
    /**
     * 空数据时展示的占位文案，仅在 hideWhenEmpty=false 时生效。
     * 不传则使用默认「暂无数据」。
     */
    emptyText?: string;
    /**
     * 是否支持点击标题「下拉收起」列表（对齐 smart-webim task-group）。
     * 默认 true —— 有数据时标题右侧出现折叠箭头，点击标题折叠 / 展开列表体。
     */
    collapsible?: boolean;
    /** 初始是否折叠（仅 collapsible=true 时生效），默认展开 */
    defaultCollapsed?: boolean;
    /**
     * 列表项 hover 时右侧「更多操作」三点菜单选项（对齐 smart-webim task-group show-more-btn + menu-options）。
     * 不传或为空数组则不显示三点菜单。点击某项后通过 menuSelect 事件回传 { value, item }。
     */
    menuOptions?: SideGroupMenuOption[];
}

const props = withDefaults(defineProps<Props>(), {
    ...themePropsDefaults,
    items: () => [],
    activeId: '',
    hideWhenEmpty: true,
    showDelete: false,
    headerActionIcon: '',
    headerActionTip: '',
    emptyText: '暂无数据',
    collapsible: true,
    defaultCollapsed: false,
    menuOptions: () => [],
});

const emit = defineEmits<{
    /** 点击某个列表项 */
    (e: 'select', item: SideGroupItem): void;
    /** 点击某项右侧删除按钮 */
    (e: 'delete', item: SideGroupItem): void;
    /** 点击分组标题右侧的「设置 / 添加」入口 */
    (e: 'headerAction'): void;
    /** 折叠状态变更 */
    (e: 'toggleCollapse', collapsed: boolean): void;
    /** 选择某项「更多操作」菜单项 */
    (e: 'menuSelect', payload: { value: string; item: SideGroupItem }): void;
}>();

/** 是否启用「更多操作」三点菜单 */
const hasMenu = computed(() => props.menuOptions.length > 0);

/** TDesign Dropdown options 结构（content 为展示文案，value 随点击回传） */
const dropdownOptions = computed(() =>
    props.menuOptions.map((opt) => ({ content: opt.label, value: opt.value })),
);

/** 折叠状态：受控于 defaultCollapsed 初值，之后由自身维护 */
const collapsed = ref(props.defaultCollapsed);
watch(
    () => props.defaultCollapsed,
    (val) => {
        collapsed.value = val;
    },
);

const shouldRender = computed(() => {
    if (props.hideWhenEmpty && props.items.length === 0) return false;
    return true;
});

/** 点击标题：折叠 / 展开列表体（无数据时不响应，避免空组也能折叠） */
const toggleCollapse = () => {
    if (!props.collapsible || props.items.length === 0) return;
    collapsed.value = !collapsed.value;
    emit('toggleCollapse', collapsed.value);
};

const handleClick = (item: SideGroupItem, event?: MouseEvent) => {
    if (item.disabled) return;
    // 点击「更多操作」三点按钮时不触发列表项选中（该按钮由 TDropdown 自行处理开合，
    // 故不能在其上 stopPropagation，否则 Dropdown 无法展开，只能在此按 target 过滤）
    const target = event?.target as HTMLElement | null;
    if (target?.closest?.('.side-group-item__more')) return;
    emit('select', item);
};

const handleDeleteClick = (event: Event, item: SideGroupItem) => {
    event.stopPropagation();
    if (item.disabled) return;
    emit('delete', item);
};

const handleHeaderAction = (event: Event) => {
    event.stopPropagation();
    emit('headerAction');
};

/** 选择某项「更多操作」菜单项：回传菜单值与所属列表项 */
const handleMenuSelect = (value: string, item: SideGroupItem) => {
    if (item.disabled) return;
    emit('menuSelect', { value, item });
};

/**
 * TDropdown @click 回调适配：回调参数类型为 DropdownOption（string | number | object），
 * 对象形态时取其 value 字段。做类型收敛，避免不同 tdesign-vue-next 小版本的
 * 类型定义差异（data 可能为 undefined / 联合类型无 .value）导致编译失败。
 */
const onDropdownClick = (data: unknown, item: SideGroupItem): void => {
    const value = (typeof data === 'object' && data !== null)
        ? (data as Record<string, unknown>).value
        : data;
    handleMenuSelect(String(value ?? ''), item);
};

/**
 * 当前处于「更多操作」菜单展开态的列表项 id。
 * 用于在下拉菜单展开期间强制保持该项的三点按钮可见——否则鼠标移到浮层菜单上时，
 * 列表项失去 hover，三点按钮 display:none，触发元素消失导致菜单被关闭、点不到菜单项。
 */
const openMenuItemId = ref('');

/** 下拉浮层显隐变化：记录/清除当前展开态的列表项 id */
const handleMenuVisibleChange = (visible: boolean, item: SideGroupItem) => {
    openMenuItemId.value = visible ? item.id : '';
};
</script>

<template>
    <div v-if="shouldRender" class="side-group-list">
        <div class="side-group-header" :class="{ collapsed }">
            <span
                class="side-group-header__title-wrap"
                :class="{ 'is-collapsible': collapsible && items.length > 0 }"
                role="button"
                tabindex="0"
                @click="toggleCollapse"
                @keydown.enter.prevent="toggleCollapse"
                @keydown.space.prevent="toggleCollapse"
            >
                <span class="side-group-header__title">{{ title }}</span>
                <CustomizedIcon
                    v-if="collapsible && items.length > 0"
                    name="arrow_down_small_line"
                    remote
                    size="xs"
                    :theme="theme"
                    :show-hover-bg="false"
                    class="side-group-header__caret"
                />
            </span>
            <span
                v-if="headerActionIcon"
                class="side-group-header__action"
                :title="headerActionTip"
                role="button"
                tabindex="0"
                @click="handleHeaderAction"
                @keydown.enter.prevent="handleHeaderAction($event)"
            >
                <CustomizedIcon
                    :name="headerActionIcon"
                    remote
                    size="xs"
                    :theme="theme"
                    :show-hover-bg="false"
                />
            </span>
        </div>
        <div v-show="!collapsed" class="side-group-body">
            <div
                v-for="item in items"
                :key="item.id"
                class="side-group-item"
                :class="{
                    active: activeId === item.id,
                    'is-disabled': item.disabled,
                    'menu-open': openMenuItemId === item.id,
                }"
                @click="handleClick(item, $event)"
            >
                <CustomizedIcon
                    v-if="item.icon"
                    :name="item.icon"
                    :remote="item.iconRemote !== false"
                    size="xs"
                    :theme="theme"
                    :show-hover-bg="false"
                    class="side-group-item__icon"
                />
                <div class="side-group-item__label" :title="item.label">{{ item.label }}</div>
                <span
                    v-if="showDelete && !item.disabled"
                    class="side-group-item__delete"
                    aria-label="删除"
                    role="button"
                    tabindex="0"
                    @click="handleDeleteClick($event, item)"
                    @keydown.enter.stop.prevent="handleDeleteClick($event, item)"
                >
                    <TIcon name="delete" size="14px" />
                </span>
                <!-- 更多操作三点菜单：hover / active 时显示（对齐 smart-webim task-group）。
                     注意：不能在触发按钮上 stopPropagation，否则 TDropdown(trigger=click) 无法展开；
                     列表项选中已在 handleClick 内按 .side-group-item__more target 过滤规避。 -->
                <TDropdown
                    v-else-if="hasMenu && !item.disabled"
                    :options="dropdownOptions"
                    trigger="click"
                    placement="bottom-right"
                    :popup-props="{ onVisibleChange: (v: boolean) => handleMenuVisibleChange(v, item) }"
                    @click="(data) => onDropdownClick(data, item)"
                >
                    <span
                        class="side-group-item__more"
                        aria-label="更多操作"
                        role="button"
                        tabindex="0"
                    >
                        <TIcon name="ellipsis" size="16px" />
                    </span>
                </TDropdown>
                <span v-if="item.extraText" class="side-group-item__extra">
                    {{ item.extraText }}
                </span>
            </div>
            <!-- 空态占位：仅当 hideWhenEmpty=false 且 items 为空时展示 -->
            <div v-if="items.length === 0" class="side-group-empty">
                {{ emptyText }}
            </div>
        </div>
    </div>
</template>

<style scoped>
.side-group-list {
    width: 100%;
    padding: 0 var(--td-size-2);
    margin-bottom: var(--td-comp-margin-xs, 4px);
}

.side-group-header {
    font-size: 11px;
    font-weight: 500;
    letter-spacing: 0.02em;
    text-transform: uppercase;
    height: var(--td-comp-size-s);
    line-height: var(--td-comp-size-s);
    color: var(--td-text-color-placeholder);
    padding-left: var(--td-comp-paddingLR-s);
    padding-right: 4px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: var(--td-comp-margin-xs);
}

.side-group-header__title {
    color: var(--td-text-color-placeholder);
    font-size: 11px;
    font-weight: 500;
    letter-spacing: 0.03em;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

/* 标题点击热区：包住标题文案 + 折叠箭头，仅可折叠时给手型 */
.side-group-header__title-wrap {
    display: flex;
    align-items: center;
    flex: 1;
    min-width: 0;
    height: 100%;
    border-radius: var(--td-radius-small);
    user-select: none;
}

.side-group-header__title-wrap.is-collapsible {
    cursor: pointer;
}

.side-group-header__title-wrap:focus-visible {
    outline: 2px solid var(--td-brand-color);
    outline-offset: 1px;
}

/* 折叠箭头：默认隐藏，hover 标题或已折叠时显示；折叠态旋转 -90° */
.side-group-header__caret {
    flex-shrink: 0;
    margin-left: var(--td-size-2);
    color: var(--td-text-color-placeholder);
    opacity: 0;
    transition: opacity 0.15s ease, transform 0.2s ease;
}

.side-group-header__title-wrap:hover .side-group-header__caret,
.side-group-header.collapsed .side-group-header__caret {
    opacity: 1;
}

.side-group-header.collapsed .side-group-header__caret {
    transform: rotate(-90deg);
}

.side-group-header__action {
    flex-shrink: 0;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 20px;
    height: 20px;
    border-radius: var(--td-radius-small);
    color: var(--td-text-color-placeholder);
    cursor: pointer;
    transition: background 0.15s ease, color 0.15s ease;
}

.side-group-header__action:hover {
    background: var(--td-bg-color-container-hover);
    color: var(--td-text-color-primary);
}

.side-group-header__action:focus-visible {
    outline: 2px solid var(--td-brand-color);
    outline-offset: 1px;
}

.side-group-item {
    min-height: 36px;
    line-height: var(--td-line-height-body-small);
    cursor: pointer;
    padding: var(--td-size-4) 10px;
    border-radius: var(--td-radius-medium);
    transition: background 0.15s ease, color 0.15s ease;
    color: var(--td-text-color-primary);
    display: flex;
    align-items: center;
    font-size: var(--td-font-size-body-medium);
    margin-bottom: var(--td-size-1);
}

.side-group-item.active {
    background: var(--td-bg-color-container-active);
    font-weight: 500;
}

.side-group-item:hover:not(.active):not(.is-disabled) {
    background: var(--td-bg-color-container-hover);
}

.side-group-item.is-disabled {
    cursor: not-allowed;
    color: var(--td-text-color-disabled);
}

.side-group-item__icon {
    flex-shrink: 0;
    margin-right: var(--td-size-4);
}

.side-group-item__label {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.side-group-item__extra {
    flex-shrink: 0;
    margin-left: var(--td-size-4);
    font-size: 11px;
    color: var(--td-text-color-placeholder);
    opacity: 0;
    transition: opacity 0.15s ease;
}

.side-group-item:not(:hover):not(.active) .side-group-item__extra {
    opacity: 1;
}

/* hover / active 时让位给删除按钮（若开启） */
.side-group-item:hover .side-group-item__extra,
.side-group-item.active .side-group-item__extra {
    display: none;
}

.side-group-item__delete {
    flex-shrink: 0;
    margin-left: var(--td-size-4);
    display: none;
    align-items: center;
    justify-content: center;
    width: 20px;
    height: 20px;
    border-radius: var(--td-radius-small);
    color: var(--td-text-color-placeholder);
    cursor: pointer;
    transition: background 0.15s ease, color 0.15s ease;
}

.side-group-item:hover .side-group-item__delete,
.side-group-item.active .side-group-item__delete {
    display: inline-flex;
}

.side-group-item__delete:hover {
    background: var(--td-bg-color-container-active);
    color: var(--td-error-color);
}

.side-group-item__delete:focus-visible {
    outline: 2px solid var(--td-brand-color);
    outline-offset: 1px;
}

/* 更多操作三点按钮：默认隐藏，hover / active 时显示（与删除按钮一致的显隐规则） */
.side-group-item__more {
    flex-shrink: 0;
    margin-left: var(--td-size-4);
    display: none;
    align-items: center;
    justify-content: center;
    width: 20px;
    height: 20px;
    border-radius: var(--td-radius-small);
    color: var(--td-text-color-placeholder);
    cursor: pointer;
    transition: background 0.15s ease, color 0.15s ease;
}

.side-group-item:hover .side-group-item__more,
.side-group-item.active .side-group-item__more,
.side-group-item.menu-open .side-group-item__more {
    display: inline-flex;
}

.side-group-item__more:hover {
    background: var(--td-bg-color-container-active);
    color: var(--td-text-color-primary);
}

.side-group-item__more:focus-visible {
    outline: 2px solid var(--td-brand-color);
    outline-offset: 1px;
}

.side-group-empty {
    padding: 8px var(--td-comp-paddingLR-s, 10px);
    font-size: var(--td-font-size-body-small, 12px);
    color: var(--td-text-color-placeholder);
    line-height: var(--td-line-height-body-small);
}
</style>
