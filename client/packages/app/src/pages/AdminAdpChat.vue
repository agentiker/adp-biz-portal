<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ADPChat, type ApiConfig, type Application, type ChatConversation } from 'adp-chat-component'
import {
  AddIcon,
  CheckCircleFilledIcon,
  ChevronDownIcon,
  DeleteIcon,
  LinkIcon,
  LoadingIcon,
  RefreshIcon,
} from 'tdesign-icons-vue-next'
import PlatformShell from '@/components/PlatformShell.vue'
import { getBaseURL } from '@/utils/url'
import { logout } from '@/service/login'
import { useUiStore } from '@/stores/ui'

type ConversationsChange = {
  list: ChatConversation[]
  chattingIds: string[]
  loading: boolean
  error: unknown
}

const route = useRoute()
const router = useRouter()
const uiStore = useUiStore()

const currentApplicationId = ref(typeof route.params.applicationId === 'string' ? route.params.applicationId : '')
const currentConversationId = ref(typeof route.params.conversationId === 'string' ? route.params.conversationId : '')

const applications = ref<Application[]>([])
const conversations = ref<ChatConversation[]>([])
const chattingIds = ref<string[]>([])
const conversationsLoading = ref(false)
const conversationsError = ref(false)

const contextToken = ref('')
const contextLoading = ref(true)
const contextError = ref('')
const lastEvent = ref('等待 ADP 请求')

const appSwitcherOpen = ref(false)
const pendingDelete = ref<ChatConversation | null>(null)

const adpChatRef = ref<InstanceType<typeof ADPChat> | null>(null)
let renewTimer: ReturnType<typeof setTimeout> | null = null

const pageTitle = 'ADP Chat 调试'

const apiConfig = computed<ApiConfig>(() => ({
  baseURL: getBaseURL(),
  timeout: 1000 * 60,
  headers: contextToken.value
    ? {
        Authorization: `Bearer ${contextToken.value}`,
        'X-Admin-ADP-Context': '1',
      }
    : undefined,
  apiDetailConfig: {
    applicationListApi: '/application/list',
    conversationListApi: '/chat/conversations',
    conversationDetailApi: '/chat/messages',
    sendMessageApi: '/chat/message',
    conversationDeleteApi: '/chat/conversation/delete',
    rateApi: '/feedback/rate',
    shareApi: '/share/create',
    userInfoApi: '/account/info',
    // uploadApi / asrUrlApi / systemConfigApi 是 service 层公共导出，
    // 保留以免 Sender/Chat 请求路径落空；本调试页并不主动使用它们。
    uploadApi: '/file/upload',
    asrUrlApi: '/helper/asr/url',
    systemConfigApi: '/system/config',
  },
}))

const selectedApplication = computed(() =>
  applications.value.find((item) => item.ApplicationId === currentApplicationId.value),
)
const applicationName = computed(
  () => selectedApplication.value?.Name || selectedApplication.value?.ApplicationId || '未选择应用',
)
const applicationAvatar = computed(() => selectedApplication.value?.Avatar || '')

/** 会话按最近活跃时间倒序，进行中的置顶感由转圈体现，不额外重排 */
const sortedConversations = computed(() =>
  [...conversations.value].sort((a, b) => {
    const at = Number(b.LastActiveAt ?? 0) - Number(a.LastActiveAt ?? 0)
    return Number.isNaN(at) ? 0 : at
  }),
)

/** 上下文状态：building / failed / ready，用于顶栏状态点与整页态 */
const contextState = computed<'building' | 'failed' | 'ready'>(() => {
  if (contextError.value) return 'failed'
  if (contextToken.value) return 'ready'
  return 'building'
})

// 相对时间：当天 HH:mm / 1-6 天前 / 否则 M/D（沿用原 HistoryList 的展示口径）
const formatUpdateTime = (value?: number | string): string => {
  if (value === undefined || value === null || value === '') return ''
  const raw = typeof value === 'string' ? Number(value) : value
  if (!Number.isFinite(raw)) return ''
  const ms = raw < 1e12 ? raw * 1000 : raw
  const date = new Date(ms)
  if (Number.isNaN(date.getTime())) return ''
  const now = new Date()
  const sameDay =
    date.getFullYear() === now.getFullYear() &&
    date.getMonth() === now.getMonth() &&
    date.getDate() === now.getDate()
  if (sameDay) {
    return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`
  }
  const dayDiff = Math.floor((now.getTime() - date.getTime()) / 86400000)
  if (dayDiff >= 1 && dayDiff <= 6) return `${dayDiff} 天前`
  return `${date.getMonth() + 1}/${date.getDate()}`
}

const isChatting = (id?: string) => !!id && chattingIds.value.includes(id)

const syncRoute = (
  applicationId = currentApplicationId.value,
  conversationId = currentConversationId.value,
) => {
  const params: Record<string, string> = {}
  if (applicationId) params.applicationId = applicationId
  if (conversationId) params.conversationId = conversationId
  // SSE 每回吐一次 conversationId 都会同步，必须用 replace，否则历史被刷爆
  void router.replace({ name: 'admin-adp-chat', params })
}

const selectApplication = (app: Application) => {
  appSwitcherOpen.value = false
  const id = app.ApplicationId || ''
  if (id === currentApplicationId.value) return
  currentApplicationId.value = id
  currentConversationId.value = ''
  lastEvent.value = `已选择应用 ${app.Name || id || '未命名应用'}`
  syncRoute()
}

const selectConversation = (conversation: ChatConversation) => {
  if (conversation.Id === currentConversationId.value) return
  currentApplicationId.value = conversation.ApplicationId || currentApplicationId.value
  currentConversationId.value = conversation.Id
  lastEvent.value = `已恢复会话 ${conversation.Id}`
  syncRoute()
}

const startNewConversation = () => {
  // force 刷新 agentId 对 claw 应用是必需的，交给组件内部完成；页面只清选中 + 同步路由
  adpChatRef.value?.startNewConversation?.()
  currentConversationId.value = ''
  lastEvent.value = '已开始新会话'
  syncRoute()
}

const confirmDelete = (conversation: ChatConversation) => {
  if (isChatting(conversation.Id)) return
  pendingDelete.value = conversation
}

const performDelete = async () => {
  const target = pendingDelete.value
  pendingDelete.value = null
  if (!target) return
  try {
    await adpChatRef.value?.deleteConversation?.(target)
    if (target.Id === currentConversationId.value) {
      currentConversationId.value = ''
      syncRoute()
    }
    lastEvent.value = '会话已删除'
  } catch {
    // 组件内部已回滚列表并提示，这里不再重复报错
    lastEvent.value = '删除失败，已恢复列表'
  }
}

const handleConversationsChange = (payload: ConversationsChange) => {
  conversations.value = payload.list
  chattingIds.value = payload.chattingIds
  conversationsLoading.value = payload.loading
  conversationsError.value = payload.error != null
}

const handleConversationChange = (conversationId: string) => {
  if (conversationId === currentConversationId.value) return
  currentConversationId.value = conversationId
  lastEvent.value = `会话已切换为 ${conversationId}`
  syncRoute()
}

const handleDataLoaded = (type: string, data: unknown) => {
  if (type === 'applications' && Array.isArray(data)) {
    applications.value = data as Application[]
    if (!currentApplicationId.value && applications.value[0]?.ApplicationId) {
      currentApplicationId.value = applications.value[0].ApplicationId
      syncRoute()
    }
    lastEvent.value = applications.value.length
      ? `已加载 ${applications.value.length} 个可用应用`
      : '未找到已绑定应用'
  }
}

const handleMessage = (_code: unknown, message: string) => {
  if (message) lastEvent.value = message
}

const reloadConversations = () => {
  void adpChatRef.value?.loadConversations?.()
}

const handleLogout = () => logout(() => router.replace({ name: 'login' }))

// 路由 → state 回灌：浏览器前进/后退时把选中项拉回一致
watch(
  () => [route.params.applicationId, route.params.conversationId],
  ([appId, convId]) => {
    const nextApp = typeof appId === 'string' ? appId : ''
    const nextConv = typeof convId === 'string' ? convId : ''
    if (nextApp && nextApp !== currentApplicationId.value) currentApplicationId.value = nextApp
    if (nextConv !== currentConversationId.value) currentConversationId.value = nextConv
  },
)

const scheduleRenew = (expiresAtIso: string) => {
  if (renewTimer) clearTimeout(renewTimer)
  // 服务端返回的是不带时区的 ISO（naive UTC）。JS `new Date()` 会按浏览器本地时区
  // 解析这种字符串，在 UTC+8 环境下会把到期时间当成 8 小时前 → 续期定时器空转、
  // 每秒重签一次 token。没有时区后缀时按 UTC 处理。
  const hasTz = /([zZ])|([+-]\d{2}:?\d{2})$/.test(expiresAtIso)
  const expiresAt = new Date(hasTz ? expiresAtIso : `${expiresAtIso}Z`).getTime()
  if (!Number.isFinite(expiresAt)) return
  // 到期前 60s 续期；下限 30s 兜底，任何解析异常都不会退化成高频轮询
  const delay = Math.min(Math.max(expiresAt - Date.now() - 60_000, 30_000), 1000 * 60 * 30)
  renewTimer = setTimeout(() => {
    void loadContext({ silent: true })
  }, delay)
}

const loadContext = async ({ silent }: { silent?: boolean } = {}) => {
  if (!silent) contextLoading.value = true
  contextError.value = ''
  try {
    const response = await fetch('/api/v1/admin/adp-chat/context', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: '{}',
    })
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}))
      throw new Error(payload?.message || payload?.error || `无法建立调试上下文（${response.status}）`)
    }
    const payload = await response.json()
    if (!payload?.contextToken) throw new Error('服务端未返回调试上下文')
    contextToken.value = payload.contextToken
    if (typeof payload.expiresAt === 'string') scheduleRenew(payload.expiresAt)
    lastEvent.value = silent ? '调试上下文已续期' : '已建立 Admin 调试上下文'
  } catch (error) {
    contextError.value = error instanceof Error ? error.message : '无法建立 ADP 调试上下文'
    lastEvent.value = '调试上下文建立失败'
  } finally {
    if (!silent) contextLoading.value = false
  }
}

const closeSwitcherOnEscape = (event: KeyboardEvent) => {
  if (event.key === 'Escape') appSwitcherOpen.value = false
}

onMounted(() => {
  void loadContext()
  window.addEventListener('keydown', closeSwitcherOnEscape)
})

onUnmounted(() => {
  if (renewTimer) clearTimeout(renewTimer)
  window.removeEventListener('keydown', closeSwitcherOnEscape)
})
</script>

<template>
  <PlatformShell mode="admin" :title="pageTitle" :full-bleed="true" @logout="handleLogout">
    <div class="adp-chat-page">
      <!-- 左栏：会话列表 -->
      <aside class="conv-rail">
        <div class="rail-head">
          <div class="rail-head-title">
            <span class="section-kicker">会话</span>
            <span class="rail-count">{{ conversations.length }}</span>
          </div>
          <button
            class="primary-action"
            type="button"
            :disabled="!contextToken || !currentApplicationId"
            @click="startNewConversation"
          >
            <AddIcon /><span>新建</span>
          </button>
        </div>

        <div class="rail-body">
          <p v-if="!currentApplicationId" class="rail-hint">请选择一个应用后开始调试。</p>
          <p v-else-if="conversationsLoading && !conversations.length" class="rail-hint">
            <LoadingIcon class="spin" />正在加载会话…
          </p>
          <div v-else-if="conversationsError" class="rail-error">
            <span>会话列表加载失败。</span>
            <button class="subtle-button" type="button" @click="reloadConversations">
              <RefreshIcon />重试
            </button>
          </div>
          <p v-else-if="!conversations.length" class="rail-empty">
            该应用还没有会话，点上方“新建”开始。
          </p>
          <ul v-else class="conv-list">
            <li
              v-for="conversation in sortedConversations"
              :key="conversation.Id"
              class="conv-row"
              :class="{ active: conversation.Id === currentConversationId }"
              @click="selectConversation(conversation)"
            >
              <span class="conv-title">{{ conversation.Title || '未命名会话' }}</span>
              <span class="conv-meta">{{ formatUpdateTime(conversation.LastActiveAt) }}</span>
              <LoadingIcon v-if="isChatting(conversation.Id)" class="conv-spin spin" />
              <button
                v-else
                class="conv-delete"
                type="button"
                aria-label="删除会话"
                @click.stop="confirmDelete(conversation)"
              >
                <DeleteIcon />
              </button>
            </li>
          </ul>
        </div>
      </aside>

      <!-- 右栏：聊天区 -->
      <section class="chat-column">
        <header class="chat-topbar">
          <div class="topbar-app">
            <span v-if="applicationAvatar" class="app-avatar" :style="{ backgroundImage: `url(${applicationAvatar})` }"></span>
            <span v-else class="app-avatar app-avatar--fallback">{{ applicationName.slice(0, 1) }}</span>
            <div class="topbar-app-copy">
              <strong>{{ applicationName }}</strong>
              <small>ADP 调试会话</small>
            </div>
          </div>

          <div class="topbar-right">
            <div v-if="applications.length > 1" class="app-switcher">
              <button class="subtle-button" type="button" @click="appSwitcherOpen = !appSwitcherOpen">
                切换应用<ChevronDownIcon />
              </button>
              <div v-if="appSwitcherOpen" class="switcher-panel" @focusout="appSwitcherOpen = false">
                <button
                  v-for="app in applications"
                  :key="app.ApplicationId"
                  class="switcher-row"
                  type="button"
                  @click="selectApplication(app)"
                >
                  <span>{{ app.Name || app.ApplicationId }}</span>
                  <CheckCircleFilledIcon v-if="app.ApplicationId === currentApplicationId" class="switcher-check" />
                </button>
              </div>
            </div>
            <span class="status-chip" :class="`status-chip--${contextState}`">
              <i></i>{{ lastEvent }}
            </span>
          </div>
        </header>

        <div class="chat-body">
          <ADPChat
            v-if="contextToken"
            ref="adpChatRef"
            :api-config="apiConfig"
            :auto-load="true"
            :theme="uiStore.theme || 'light'"
            :language="uiStore.language || 'zh'"
            :current-application-id="currentApplicationId"
            :current-conversation-id="currentConversationId"
            :ai-warning-text="'内容由 AI 生成，仅供参考'"
            @select-application="selectApplication"
            @select-conversation="selectConversation"
            @conversations-change="handleConversationsChange"
            @conversation-change="handleConversationChange"
            @data-loaded="handleDataLoaded"
            @message="handleMessage"
          />
          <div v-else-if="contextState === 'failed'" class="chat-state">
            <p class="form-error">{{ contextError }}</p>
            <button class="subtle-button" type="button" @click="loadContext()">
              <RefreshIcon />重试
            </button>
          </div>
          <div v-else class="chat-state" aria-live="polite">
            <LoadingIcon class="spin" />正在建立 ADP 调试上下文…
          </div>
        </div>

        <div v-if="contextToken && !applications.length" class="chat-alerts">
          <LinkIcon />
          <span>暂未加载到应用。请先在“ADP 应用配置”中绑定可用的应用与 Workspace。</span>
        </div>
      </section>
    </div>

    <!-- 删除确认 -->
    <div v-if="pendingDelete" class="modal-backdrop" @click.self="pendingDelete = null">
      <div class="modal-card">
        <h3>删除会话</h3>
        <p>确认删除“{{ pendingDelete.Title || '该会话' }}”？删除后不可恢复。</p>
        <div class="modal-actions">
          <button class="subtle-button" type="button" @click="pendingDelete = null">取消</button>
          <button class="danger-action" type="button" @click="performDelete">删除</button>
        </div>
      </div>
    </div>
  </PlatformShell>
</template>

<style scoped>
.adp-chat-page {
  display: grid;
  grid-template-columns: 308px 1fr;
  height: 100%;
  min-height: 0;
  overflow: hidden;
  background: #f7faf9;
  color: #142322;
}

/* 左栏 */
.conv-rail {
  display: flex;
  flex-direction: column;
  min-height: 0;
  border-right: 1px solid #dfe7e5;
  background: #fbfcfb;
}
.rail-head {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 16px 16px 12px;
  border-bottom: 1px solid #eaf1ef;
}
.rail-head-title {
  display: flex;
  align-items: baseline;
  gap: 8px;
}
.section-kicker {
  font-size: 11px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: #7c8c89;
  font-weight: 650;
}
.rail-count {
  font-size: 12px;
  color: #98a5a2;
}
.rail-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 8px;
}
.rail-hint,
.rail-empty {
  margin: 0;
  padding: 18px 12px;
  color: #6d817b;
  font-size: 12px;
  line-height: 1.6;
  display: flex;
  align-items: center;
  gap: 7px;
}
.rail-error {
  padding: 16px 12px;
  color: #8b4742;
  font-size: 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  align-items: flex-start;
}
.conv-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 2px;
}
.conv-row {
  display: grid;
  grid-template-columns: 1fr auto auto;
  align-items: center;
  gap: 8px;
  padding: 9px 10px;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.15s ease;
}
.conv-row:hover {
  background: #f0f5f3;
}
.conv-row.active {
  background: #dceee9;
}
.conv-title {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
  color: #22322f;
}
.conv-row.active .conv-title {
  color: #0f6a60;
  font-weight: 620;
}
.conv-meta {
  font-size: 11px;
  color: #9aa7a4;
  white-space: nowrap;
}
.conv-delete {
  display: grid;
  place-items: center;
  width: 24px;
  height: 24px;
  border: 0;
  background: none;
  color: #a6b2af;
  border-radius: 6px;
  cursor: pointer;
  opacity: 0;
  transition: opacity 0.15s ease, color 0.15s ease, background 0.15s ease;
}
.conv-row:hover .conv-delete {
  opacity: 1;
}
.conv-delete:hover {
  color: #b0514b;
  background: #fbeceb;
}
.conv-delete :deep(svg) {
  width: 15px;
}
.conv-spin {
  color: #40a57b;
}
.conv-spin :deep(svg),
.spin :deep(svg) {
  width: 15px;
}
.spin {
  animation: adp-spin 0.9s linear infinite;
  display: inline-flex;
}
@keyframes adp-spin {
  to {
    transform: rotate(360deg);
  }
}

/* 右栏 */
.chat-column {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}
.chat-topbar {
  flex: 0 0 auto;
  min-height: 60px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 10px 24px;
  border-bottom: 1px solid #dfe7e5;
  background: #fbfcfb;
}
.topbar-app {
  display: flex;
  align-items: center;
  gap: 11px;
  min-width: 0;
}
.app-avatar {
  width: 34px;
  height: 34px;
  flex: 0 0 34px;
  border-radius: 9px;
  background-size: cover;
  background-position: center;
}
.app-avatar--fallback {
  display: grid;
  place-items: center;
  background: #cfe7df;
  color: #17675e;
  font-weight: 700;
  font-size: 15px;
}
.topbar-app-copy {
  min-width: 0;
}
.topbar-app-copy strong {
  display: block;
  font-size: 14px;
  color: #18312d;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.topbar-app-copy small {
  display: block;
  font-size: 11px;
  color: #85938f;
  margin-top: 1px;
}
.topbar-right {
  display: flex;
  align-items: center;
  gap: 14px;
}
.app-switcher {
  position: relative;
}
.switcher-panel {
  position: absolute;
  top: calc(100% + 6px);
  right: 0;
  z-index: 30;
  min-width: 220px;
  padding: 6px;
  border: 1px solid #dfe7e5;
  border-radius: 10px;
  background: #fff;
  box-shadow: 0 12px 30px rgba(25, 49, 45, 0.14);
  display: grid;
  gap: 2px;
}
.switcher-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 9px 10px;
  border: 0;
  background: none;
  border-radius: 7px;
  font-size: 13px;
  color: #33433f;
  text-align: left;
  cursor: pointer;
}
.switcher-row:hover {
  background: #fbfdfc;
}
.switcher-check {
  color: #147d72;
}
.switcher-check :deep(svg),
.switcher-row :deep(svg) {
  width: 16px;
}
.status-chip {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  max-width: 320px;
  font-size: 11px;
  color: #70817d;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.status-chip i {
  width: 7px;
  height: 7px;
  flex: 0 0 7px;
  border-radius: 50%;
  background: #40a57b;
}
.status-chip--building i {
  background: #d6a53c;
}
.status-chip--failed i {
  background: #c0564e;
}
.chat-body {
  flex: 1;
  min-height: 0;
  display: flex;
}
.chat-body > * {
  flex: 1;
  min-height: 0;
}
.chat-state {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  color: #6d817b;
  font-size: 13px;
}
.form-error {
  margin: 0;
  max-width: 460px;
  text-align: center;
  color: #8b4742;
  line-height: 1.6;
}
.chat-alerts {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: 9px;
  margin: 0 24px 16px;
  padding: 10px 13px;
  border-radius: 8px;
  font-size: 12px;
  color: #667d76;
  border: 1px solid #d5e5df;
  background: #edf6f2;
}
.chat-alerts :deep(svg) {
  flex: 0 0 auto;
  width: 16px;
  color: #438e7f;
}

/* 按钮语言 */
.subtle-button {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 34px;
  padding: 0 12px;
  border: 1px solid #d6e3df;
  background: #fff;
  border-radius: 8px;
  color: #33433f;
  font-size: 12px;
  cursor: pointer;
  transition: border-color 0.15s ease, background 0.15s ease;
}
.subtle-button:hover {
  border-color: #b7cfc8;
  background: #fbfdfc;
}
.subtle-button :deep(svg) {
  width: 15px;
}
.primary-action {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 34px;
  padding: 0 14px;
  border: 0;
  border-radius: 8px;
  background: #147d72;
  color: #fff;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s ease;
}
.primary-action:hover {
  background: #10665d;
}
.primary-action:disabled {
  background: #b9ccc7;
  cursor: not-allowed;
}
.primary-action :deep(svg) {
  width: 15px;
}
.danger-action {
  min-height: 38px;
  padding: 0 16px;
  border: 0;
  border-radius: 8px;
  background: #c0564e;
  color: #fff;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}
.danger-action:hover {
  background: #a8463f;
}

/* 删除确认弹窗 */
.modal-backdrop {
  position: fixed;
  inset: 0;
  z-index: 60;
  display: grid;
  place-items: center;
  background: rgba(20, 35, 34, 0.32);
}
.modal-card {
  width: min(380px, calc(100vw - 40px));
  padding: 22px 22px 18px;
  border-radius: 12px;
  background: #fff;
  box-shadow: 0 20px 48px rgba(20, 35, 34, 0.24);
}
.modal-card h3 {
  margin: 0 0 8px;
  font-size: 16px;
  color: #18312d;
}
.modal-card p {
  margin: 0 0 18px;
  font-size: 13px;
  line-height: 1.6;
  color: #5f716d;
}
.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}

@media (max-width: 760px) {
  .adp-chat-page {
    grid-template-columns: 1fr;
  }
  .conv-rail {
    display: none;
  }
}
</style>
