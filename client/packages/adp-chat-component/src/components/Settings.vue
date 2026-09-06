<script setup lang="tsx">
import { computed } from 'vue';
import CustomizedIcon from './CustomizedIcon.vue';
import type { ThemeProps, LanguageOption } from '../model/type';
import {
    themePropsDefaults,
    defaultLanguageOptions,
    defaultSideI18n,
    defaultSideI18nEn,
} from '../model/type';
import { Space as TSpace, Dropdown as TDropdown, DropdownMenu as TDropdownMenu, DropdownItem as TDropdownItem, Button as TButton } from 'tdesign-vue-next';

interface Props extends ThemeProps {
    /** 语言选项列表 */
    languageOptions?: LanguageOption[];
    /** 切换主题文本；未传时按 language 走 SideI18n.switchTheme 默认值 */
    switchThemeText?: string;
    /** 选择语言文本；未传时按 language 走 SideI18n.selectLanguage 默认值 */
    selectLanguageText?: string;
    /** 退出登录文本；未传时按 language 走 SideI18n.logout 默认值 */
    logoutText?: string;
    /** 是否为移动端 */
    isMobile?: boolean;
    /** 当前语言标识（如 'zh-CN'、'en-US'），仅用于内部默认文案 fallback */
    language?: string;
}

const props = withDefaults(defineProps<Props>(), {
    ...themePropsDefaults,
    languageOptions: () => defaultLanguageOptions,
    switchThemeText: '',
    selectLanguageText: '',
    logoutText: '',
    isMobile: false,
    language: 'zh-CN',
});

/** 内部 i18n fallback：外部未传时按 language 选中/英文 */
const fallbackI18n = computed(() => (props.language?.startsWith('en') ? defaultSideI18nEn : defaultSideI18n));

const displaySwitchTheme = computed(() => props.switchThemeText || fallbackI18n.value.switchTheme);
const displaySelectLanguage = computed(() => props.selectLanguageText || fallbackI18n.value.selectLanguage);
const displayLogout = computed(() => props.logoutText || fallbackI18n.value.logout);

const emit = defineEmits<{
    (e: 'toggleTheme'): void;
    (e: 'changeLanguage', key: string): void;
    (e: 'logout'): void;
}>();

/**
 * 切换主题模式（light <-> dark）。
 */
const toggleTheme = () => {
    emit('toggleTheme');
};

const handleLanguageChange = (key: string) => {
    emit('changeLanguage', key);
};

const handleLogout = () => {
    emit('logout');
};
</script>

<template>
    <t-space>
        <t-dropdown maxColumnWidth="240px" :placement="isMobile ? 'left-top' : 'bottom-left'">
            <t-button theme="default" shape="square" variant="text">
                <CustomizedIcon name="setting" :theme="theme" />
            </t-button>
            
            <t-dropdown-menu>
                <t-dropdown-item>
                    <div @click="toggleTheme" class="dropdown-item">
                        <CustomizedIcon size="m" name="stars" :theme="theme" />
                        {{ displaySwitchTheme }}
                    </div>
                </t-dropdown-item>

                <t-dropdown-item>
                    <div class="dropdown-item">
                        <CustomizedIcon size="m" name="url" :theme="theme" />
                        {{ displaySelectLanguage }}
                    </div>
                    <t-dropdown-menu>
                        <t-dropdown-item v-for="lang in languageOptions" :key="lang.key"
                            @click="handleLanguageChange(lang.key)">
                            <div class="operations-dropdown-container-item">
                                {{ lang.value }}
                            </div>
                        </t-dropdown-item>
                    </t-dropdown-menu>
                </t-dropdown-item>

                <t-dropdown-item>
                    <div @click="handleLogout" class="dropdown-item">
                        <CustomizedIcon name="quit" size="m" :theme="theme" />
                        {{ displayLogout }}
                    </div>
                </t-dropdown-item>
            </t-dropdown-menu>
        </t-dropdown>
    </t-space>
</template>

<style scoped>
.dropdown-item {
    display: flex;
    align-items: center;
    cursor: pointer;
    gap: var(--td-comp-paddingLR-m);
}
</style>
