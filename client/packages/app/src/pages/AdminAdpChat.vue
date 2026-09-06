<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ADPChat, type ApiConfig, type Application, type ChatConversation } from 'adp-chat-component'
import { ChatMessageIcon, CheckCircleIcon, LinkIcon } from 'tdesign-icons-vue-next'
import PlatformShell from '@/components/PlatformShell.vue'
import { getBaseURL } from '@/utils/url'
import { logout } from '@/service/login'
import { useUiStore } from '@/stores/ui'
import Logo from '@/assets/img/favicon.png'

const route = useRoute()
const router = useRouter()
const uiStore = useUiStore()
const currentApplicationId = ref(typeof route.params.applicationId === 'string' ? route.params.applicationId : '')
const currentConversationId = ref(typeof route.params.conversationId === 'string' ? route.params.conversationId : '')
const applications = ref<Application[]>([])
const lastEvent = ref('等待 ADP 请求')
const loadError = ref('')
const contextToken = ref('')
const contextLoading = ref(true)

const apiConfig = computed<ApiConfig>(() => ({
  baseURL: getBaseURL(),
  timeout: 1000 * 60,
  headers: contextToken.value ? {
    Authorization: `Bearer ${contextToken.value}`,
    'X-Admin-ADP-Context': '1',
  } : undefined,
  apiDetailConfig: {
    applicationListApi: '/application/list',
    conversationListApi: '/chat/conversations',
    conversationDetailApi: '/chat/messages',
    sendMessageApi: '/chat/message',
    rateApi: '/feedback/rate',
    shareApi: '/share/create',
    userInfoApi: '/account/info',
    uploadApi: '/file/upload',
    asrUrlApi: '/helper/asr/url',
    systemConfigApi: '/system/config',
  },
}))

const pageTitle = 'ADP Chat 调试'
const selectedApplication = computed(() => applications.value.find((item) => item.ApplicationId === currentApplicationId.value))
const statusLabel = computed(() => selectedApplication.value ? '应用已绑定，可发送测试请求' : '请选择一个已绑定应用')

const syncRoute = (applicationId = currentApplicationId.value, conversationId = currentConversationId.value) => {
  const params: Record<string, string> = {}
  if (applicationId) params.applicationId = applicationId
  if (conversationId) params.conversationId = conversationId
  void router.replace({ name: 'admin-adp-chat', params })
}

const handleSelectApplication = (app: Application) => {
  currentApplicationId.value = app.ApplicationId || ''
  currentConversationId.value = ''
  lastEvent.value = `已选择应用 ${app.Name || app.ApplicationId || '未命名应用'}`
  syncRoute()
}

const handleSelectConversation = (conversation: ChatConversation) => {
  currentApplicationId.value = conversation.ApplicationId || currentApplicationId.value
  currentConversationId.value = conversation.Id
  lastEvent.value = `已恢复会话 ${conversation.Id}`
  syncRoute()
}

const handleCreateConversation = () => {
  currentConversationId.value = ''
  lastEvent.value = '已创建新会话'
  syncRoute()
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
    lastEvent.value = applications.value.length ? `已加载 ${applications.value.length} 个可用应用` : '未找到已绑定应用'
  }
}

const handleMessage = (_code: unknown, message: string) => {
  lastEvent.value = message || 'ADP 请求返回错误'
  loadError.value = message || ''
}

const handleLogout = () => logout(() => router.replace({ name: 'login' }))

const loadContext = async () => {
  contextLoading.value = true
  loadError.value = ''
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
    lastEvent.value = '已建立 5 分钟 Admin 调试上下文'
  } catch (error) {
    loadError.value = error instanceof Error ? error.message : '无法建立 ADP 调试上下文'
    lastEvent.value = '调试上下文建立失败'
  } finally {
    contextLoading.value = false
  }
}

onMounted(() => {
  void loadContext()
})
</script>

<template>
  <PlatformShell mode="admin" :title="pageTitle" :full-bleed="true" @logout="handleLogout">
    <div class="adp-chat-page">
      <header class="adp-debug-header">
        <div class="adp-debug-heading">
          <span class="adp-debug-icon"><ChatMessageIcon /></span>
          <div>
            <p class="eyebrow">开发工具 / ADP API</p>
            <h1>ADP Chat 调试</h1>
            <p>复用生产聊天链路验证应用、会话、流式回复和文件上传。所有应用仍受服务端企业绑定与权限校验。</p>
          </div>
        </div>
        <div class="adp-debug-meta">
          <span class="debug-status"><i></i>{{ statusLabel }}</span>
          <span class="debug-event"><CheckCircleIcon />{{ lastEvent }}</span>
        </div>
      </header>
      <div v-if="loadError" class="adp-debug-alert"><strong>请求失败</strong><span>{{ loadError }}</span></div>
      <div v-if="!applications.length" class="adp-debug-note"><LinkIcon /><span>暂未加载到应用。请先在“身份绑定”中配置可用的应用与 Workspace；没有绑定时后端会拒绝聊天请求。</span></div>
      <section v-if="contextToken" class="adp-chat-stage">
        <ADPChat
          :api-config="apiConfig"
          :auto-load="true"
          :theme="uiStore.theme || 'light'"
          :language="uiStore.language || 'zh'"
          :is-side-panel-overlay="uiStore.isMobile"
          :show-close-button="false"
          :show-overlay-button="false"
          :logo-url="Logo"
          :current-application-id="currentApplicationId"
          :current-conversation-id="currentConversationId"
          :current-conversation-channel="false"
          :enable-cron-task="false"
          :ai-warning-text="'内容由 AI 生成，仅供参考'"
          @select-application="handleSelectApplication"
          @select-conversation="handleSelectConversation"
          @create-conversation="handleCreateConversation"
          @conversation-change="handleConversationChange"
          @data-loaded="handleDataLoaded"
          @message="handleMessage"
        />
      </section>
      <section v-else-if="contextLoading" class="adp-chat-loading" aria-live="polite">正在建立 ADP 调试上下文...</section>
    </div>
  </PlatformShell>
</template>

<style scoped>
.adp-chat-page { flex: 1; min-height: 0; display: flex; flex-direction: column; background: #f7faf9; }
.adp-debug-header { flex: 0 0 auto; display: flex; align-items: flex-start; justify-content: space-between; gap: 24px; padding: 22px 32px 18px; border-bottom: 1px solid #dfe7e5; background: #fbfcfb; }
.adp-debug-heading { display: flex; min-width: 0; gap: 13px; }
.adp-debug-icon { width: 38px; height: 38px; flex: 0 0 38px; display: grid; place-items: center; border-radius: 10px; color: #147d72; background: #dceee9; }
.adp-debug-icon :deep(svg) { width: 21px; }
.eyebrow { margin: 0 0 4px; color: #78908a; font-size: 10px; letter-spacing: .12em; text-transform: uppercase; }
h1 { margin: 0; color: #18312d; font-size: 22px; line-height: 1.2; }
.adp-debug-heading p:last-child { max-width: 700px; margin: 6px 0 0; color: #71827e; font-size: 12px; line-height: 1.55; }
.adp-debug-meta { display: grid; flex: 0 0 auto; justify-items: end; gap: 8px; color: #70817d; font-size: 11px; }
.debug-status, .debug-event { display: inline-flex; align-items: center; gap: 7px; white-space: nowrap; }
.debug-status i { width: 7px; height: 7px; border-radius: 50%; background: #40a57b; }
.debug-event :deep(svg) { width: 14px; color: #6fa293; }
.adp-debug-alert, .adp-debug-note { flex: 0 0 auto; display: flex; align-items: center; gap: 9px; margin: 14px 32px 0; padding: 10px 13px; border-radius: 7px; font-size: 12px; }
.adp-debug-alert { color: #8b4742; border: 1px solid #efc9c4; background: #fff5f3; }
.adp-debug-alert span { overflow-wrap: anywhere; }
.adp-debug-note { color: #667d76; border: 1px solid #d5e5df; background: #edf6f2; }
.adp-debug-note :deep(svg) { flex: 0 0 auto; width: 16px; color: #438e7f; }
.adp-chat-stage { flex: 1; min-height: 0; overflow: hidden; padding: 14px 18px 18px; }
.adp-chat-loading { flex: 1; min-height: 240px; display: grid; place-items: center; color: #6d817b; font-size: 13px; }
.adp-chat-stage :deep(.page-container), .adp-chat-stage :deep(.content) { height: 100%; min-height: 0; }
@media (max-width: 760px) {
  .adp-debug-header { display: block; padding: 18px 16px 14px; }
  .adp-debug-meta { justify-items: start; margin: 13px 0 0 51px; }
  .adp-debug-alert, .adp-debug-note { margin-left: 16px; margin-right: 16px; }
  .adp-chat-stage { padding: 10px 0 0; }
}
</style>
