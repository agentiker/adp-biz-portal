<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, RouterLink } from 'vue-router'
import {
  ApiIcon,
  ChatMessageIcon,
  HistoryIcon,
  ChevronRightIcon,
  DashboardIcon,
  FileSearchIcon,
  LogoutIcon,
  MenuIcon,
  SearchIcon,
  SettingIcon,
  UsergroupIcon,
  UserIcon,
} from 'tdesign-icons-vue-next'
import { useUserStore } from '@/stores/user'
import { usePlatformStore } from '@/stores/platform'

type ShellMode = 'portal' | 'admin'

const props = withDefaults(defineProps<{ mode: ShellMode; title?: string; fullBleed?: boolean }>(), { title: '', fullBleed: false })
const emit = defineEmits<{ logout: [] }>()
const route = useRoute()
const userStore = useUserStore()
const platformStore = usePlatformStore()
const menuOpen = ref(false)

const portalNav = [
  { label: '概览', to: '/portal', icon: DashboardIcon },
  { label: '业务查询', to: '/portal/lookup', icon: SearchIcon },
  { label: '我的会话', to: '/portal/sessions', icon: FileSearchIcon },
  { label: '账号与绑定', to: '/portal/settings', icon: SettingIcon },
]

const adminNav = [
  { label: '运营概览', to: '/admin', icon: DashboardIcon },
  { label: '企业管理', to: '/admin/enterprises', icon: UsergroupIcon },
  { label: '平台用户', to: '/admin/users', icon: UserIcon },
  { label: '开放接口', to: '/admin/open-api', icon: ApiIcon },
  { label: 'ADP 应用配置', to: '/admin/bindings', icon: ApiIcon },
  { label: '渠道管理', to: '/admin/channels', icon: ApiIcon },
  { label: 'ADP Chat 调试', to: '/admin/adp-chat', icon: ChatMessageIcon },
  { label: 'Agent 与工具', to: '/admin/agents-tools', icon: SettingIcon },
  { label: '历史对话', to: '/admin/conversations', icon: FileSearchIcon },
  { label: '审计日志', to: '/admin/audit', icon: HistoryIcon },
]

const navItems = computed(() => (props.mode === 'admin' ? adminNav : portalNav))

/**
 * 命中的导航项：取「是当前路径前缀」的最长那一项。
 * 不能用 `route.path === item.to` —— 带路由参数的页面（如
 * `/admin/adp-chat/:applicationId?/:conversationId?`）一旦写入 params，
 * 精确匹配就会失败、左侧高亮丢失。也不能直接 startsWith，否则 `/admin`
 * 会连带把所有 `/admin/*` 子页都点亮。
 */
const activeNavTo = computed(() => {
  let best = ''
  for (const item of navItems.value) {
    const matched = route.path === item.to || route.path.startsWith(`${item.to}/`)
    if (matched && item.to.length > best.length) best = item.to
  }
  return best
})
const pageTitle = computed(() => props.title || navItems.value.find((item) => item.to === activeNavTo.value)?.label || '工作台')
const displayName = computed(() => platformStore.user?.name || userStore.name || '—')
const roleLabel = computed(() => platformStore.user?.roleLabel || '—')
const enterpriseName = computed(() => platformStore.enterprise?.name || '暂无授权企业范围')
const workspaceName = computed(() => props.mode === 'admin' ? '平台管理工作区' : enterpriseName.value)
const workspaceCode = computed(() => props.mode === 'admin' ? '受控配置与审计' : (platformStore.enterprise?.customerCode ? `客户编码 ${platformStore.enterprise.customerCode}` : '未绑定客户编码'))

const handleLogout = () => emit('logout')
</script>

<template>
  <div class="platform-shell" :class="[`platform-shell--${mode}`, { 'platform-shell--full-bleed': fullBleed }]">
    <aside class="platform-sidebar" :class="{ 'is-open': menuOpen }">
      <div class="platform-brand">
        <div class="brand-mark">O</div>
        <div>
          <strong>OceanDesk</strong>
          <span>{{ mode === 'admin' ? '运营控制台' : '客户业务门户' }}</span>
        </div>
        <button class="mobile-close" aria-label="关闭菜单" @click="menuOpen = false">×</button>
      </div>

      <div class="workspace-switcher">
        <span class="workspace-label">{{ mode === 'admin' ? '当前工作区' : '当前企业' }}</span>
        <strong>{{ workspaceName }}</strong>
        <span class="workspace-code">{{ workspaceCode }}</span>
      </div>

      <nav class="platform-nav" aria-label="主导航">
        <span class="nav-section-label">{{ mode === 'admin' ? '管理' : '工作区' }}</span>
        <RouterLink
          v-for="item in navItems"
          :key="item.to"
          :to="item.to"
          class="platform-nav-item"
          :class="{ active: item.to === activeNavTo }"
          @click="menuOpen = false"
        >
          <component :is="item.icon" />
          <span>{{ item.label }}</span>
          <ChevronRightIcon v-if="item.to === activeNavTo" class="nav-current" />
        </RouterLink>
      </nav>

      <div class="platform-sidebar-footer">
        <div class="secure-note"><span class="secure-dot"></span><span>数据范围已锁定</span></div>
        <button class="logout-link" @click="handleLogout"><LogoutIcon />退出登录</button>
      </div>
    </aside>

    <div v-if="menuOpen" class="sidebar-backdrop" @click="menuOpen = false"></div>

    <section class="platform-main">
      <header class="platform-topbar">
        <div class="topbar-left">
          <button class="menu-trigger" aria-label="打开菜单" @click="menuOpen = true"><MenuIcon /></button>
          <div class="breadcrumb"><span>{{ mode === 'admin' ? '运营中心' : 'OceanDesk' }}</span><ChevronRightIcon /><strong>{{ pageTitle }}</strong></div>
        </div>
        <div class="topbar-right">
          <div class="environment-badge"><span class="status-dot"></span>平台工作区</div>
          <div class="profile-chip">
            <span class="profile-avatar">{{ displayName.slice(0, 1) }}</span>
            <span class="profile-copy"><strong>{{ displayName }}</strong><small>{{ roleLabel }}</small></span>
          </div>
        </div>
      </header>
      <main class="platform-content"><slot /></main>
    </section>
  </div>
</template>

<style scoped>
.platform-shell { --ink: #142322; --muted: #6e7c7b; --line: #dfe7e5; --paper: #fbfcfb; --accent: #147d72; --accent-soft: #e5f2ef; display: flex; min-height: 100vh; background: var(--paper); color: var(--ink); }
.platform-sidebar { width: 252px; flex: 0 0 252px; background: #f2f6f4; border-right: 1px solid var(--line); display: flex; flex-direction: column; padding: 24px 16px 18px; position: relative; z-index: 20; }
.platform-brand { display: flex; align-items: center; gap: 10px; padding: 0 10px 24px; border-bottom: 1px solid var(--line); }
.brand-mark { width: 30px; height: 30px; border-radius: 8px; background: var(--ink); color: #e6f4ee; display: grid; place-items: center; font-weight: 800; font-size: 18px; }
.platform-brand strong, .platform-brand span { display: block; }
.platform-brand strong { font-size: 15px; }
.platform-brand span { color: var(--muted); font-size: 11px; margin-top: 1px; }
.workspace-switcher { margin: 20px 8px 22px; padding: 14px 13px; border: 1px solid #d5e3df; background: #e9f1ee; border-radius: 8px; }
.workspace-switcher strong, .workspace-switcher span { display: block; }
.workspace-label, .workspace-code { font-size: 11px; color: var(--muted); }
.workspace-switcher strong { font-size: 13px; margin: 7px 0 5px; line-height: 1.4; }
.platform-nav { display: grid; gap: 4px; }
.nav-section-label { text-transform: uppercase; font-size: 10px; letter-spacing: .14em; color: #899795; margin: 0 12px 6px; }
.platform-nav-item { min-height: 42px; display: flex; align-items: center; gap: 11px; padding: 0 12px; border-radius: 7px; color: #586865; text-decoration: none; font-size: 13px; transition: .2s ease; }
.platform-nav-item:hover { color: var(--ink); background: #e4eeeb; }
.platform-nav-item.active { color: var(--accent); background: #dceee9; font-weight: 650; }
.platform-nav-item :deep(svg) { width: 18px; height: 18px; flex: 0 0 18px; }
.nav-current { margin-left: auto; width: 15px !important; height: 15px !important; }
.platform-sidebar-footer { margin-top: auto; padding: 16px 10px 0; border-top: 1px solid var(--line); }
.secure-note { display: flex; align-items: center; gap: 7px; color: #72817e; font-size: 11px; margin-bottom: 16px; }
.secure-dot, .status-dot { width: 7px; height: 7px; border-radius: 50%; display: inline-block; background: #2e9b77; }
.logout-link { display: flex; gap: 9px; align-items: center; border: 0; background: none; padding: 0; color: #73817f; font-size: 12px; cursor: pointer; }
.logout-link:hover { color: #a04444; }
.logout-link :deep(svg) { width: 16px; }
.platform-main { min-width: 0; flex: 1; display: flex; flex-direction: column; }
.platform-topbar { min-height: 70px; border-bottom: 1px solid var(--line); display: flex; align-items: center; justify-content: space-between; padding: 0 34px; background: rgba(251,252,251,.96); }
.topbar-left, .topbar-right, .breadcrumb, .profile-chip, .environment-badge { display: flex; align-items: center; }
.breadcrumb { gap: 8px; color: #82908e; font-size: 12px; }
.breadcrumb strong { color: var(--ink); font-weight: 650; }
.breadcrumb :deep(svg) { width: 14px; }
.environment-badge { gap: 7px; font-size: 11px; color: #66817a; margin-right: 20px; }
.profile-chip { gap: 9px; }
.profile-avatar { width: 31px; height: 31px; display: grid; place-items: center; border-radius: 50%; background: #cfe7df; color: #17675e; font-weight: 700; font-size: 13px; }
.profile-copy strong, .profile-copy small { display: block; }
.profile-copy strong { font-size: 12px; line-height: 1.1; }
.profile-copy small { font-size: 10px; color: var(--muted); margin-top: 3px; }
.platform-content { width: min(1240px, 100%); padding: 34px 40px 56px; margin: 0 auto; }
/* fullBleed 用于聊天这类需要「满高 + 内部滚动」的页面：外层锁到视口高度，
   页面自己的 flex 链路才能生效；否则 .platform-shell 的 min-height:100vh
   会让内容撑高整页滚动。 */
.platform-shell--full-bleed { height: 100vh; overflow: hidden; }
.platform-shell--full-bleed .platform-sidebar { overflow-y: auto; }
.platform-shell--full-bleed .platform-main { min-height: 0; }
.platform-shell--full-bleed .platform-content { width: 100%; max-width: none; padding: 0; flex: 1; min-height: 0; overflow: hidden; display: flex; flex-direction: column; }
.menu-trigger, .mobile-close { display: none; }
.sidebar-backdrop { display: none; }
@media (max-width: 900px) {
  .platform-sidebar { position: fixed; inset: 0 auto 0 0; transform: translateX(-102%); transition: transform .22s ease; box-shadow: 12px 0 30px rgba(25,49,45,.12); }
  .platform-sidebar.is-open { transform: translateX(0); }
  .sidebar-backdrop { display: block; position: fixed; inset: 0; background: rgba(20,35,34,.32); z-index: 10; }
  .mobile-close { display: block; margin-left: auto; border: 0; background: none; font-size: 25px; color: var(--muted); line-height: 1; cursor: pointer; }
  .menu-trigger { display: grid; place-items: center; width: 36px; height: 36px; border: 1px solid var(--line); background: white; color: var(--ink); border-radius: 7px; margin-right: 12px; cursor: pointer; }
  .menu-trigger :deep(svg) { width: 18px; }
  .platform-topbar { padding: 0 20px; }
  .platform-content { padding: 26px 22px 46px; }
}
@media (max-width: 560px) {
  .platform-topbar { min-height: 62px; padding: 0 15px; }
  .breadcrumb span, .breadcrumb svg, .environment-badge { display: none; }
  .platform-content { padding: 22px 15px 38px; }
  .profile-copy { display: none; }
}

/* M1-UI-01: navigation controls use the same 44px interaction target as the admin page. */
.platform-nav-item { min-height: var(--control-height); }
.logout-link { min-height: var(--control-height); width: 100%; padding: 0 var(--space-2); }
.logout-link:focus-visible, .platform-nav-item:focus-visible,
.menu-trigger:focus-visible, .mobile-close:focus-visible {
  outline: 2px solid rgba(20, 125, 114, .34);
  outline-offset: 2px;
}
.topbar-left, .topbar-right, .breadcrumb { min-width: 0; }
.breadcrumb strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

@media (max-width: 900px) {
  .mobile-close, .menu-trigger {
    width: var(--control-height);
    height: var(--control-height);
    flex: 0 0 var(--control-height);
  }
  .mobile-close { display: grid; place-items: center; }
}

@media (prefers-reduced-motion: reduce) {
  .platform-sidebar, .platform-nav-item { transition-duration: .01ms; }
}
</style>
