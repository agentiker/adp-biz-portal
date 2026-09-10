<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  ApiIcon,
  CheckCircleIcon,
  CloseIcon,
  ErrorCircleIcon,
  LinkIcon,
  LockOnIcon,
  RefreshIcon,
  UserIcon,
} from 'tdesign-icons-vue-next'
import {
  createChannelCredential,
  disableChannelCredential,
  listAdminChannelIdentities,
  listChannelCredentials,
  listPlatformUsers,
  revokeAdminChannelIdentity,
  rotateChannelCredential,
} from '@/platform/platformService'
import type { AdminUser, ChannelCredential, ChannelIdentity } from '@/platform/types'

const credentials = ref<ChannelCredential[]>([])
const identities = ref<ChannelIdentity[]>([])
const users = ref<AdminUser[]>([])
const loading = ref(false)
const loadError = ref('')
const toast = ref('')
const modal = ref<'credential' | 'rotate' | 'guide' | null>(null)
const submitting = ref(false)
const activeCredential = ref<ChannelCredential | null>(null)
const identityActionId = ref<string | null>(null)
const formError = ref('')
const credentialChannel = ref<'wechat_official_account' | 'wechat_customer_service' | 'wecom_bot'>('wechat_official_account')
const credentialForm = ref({
  channelInstanceId: '',
  token: '', appId: '', appSecret: '', encodingAesKey: '',
  corpId: '', corpSecret: '', openKfId: '',
  botId: '', secret: '',
})
const rotateToken = ref('')
const modalRef = ref<HTMLElement | null>(null)
const previouslyFocused = ref<HTMLElement | null>(null)

const activeByChannel = (channel: string) => credentials.value.filter((item) => item.channel === channel && item.status === 'active')
const activeWechatCredentials = computed(() => activeByChannel('wechat_official_account'))
const activeKfCredentials = computed(() => activeByChannel('wechat_customer_service'))
const activeBotCredentials = computed(() => activeByChannel('wecom_bot'))
const emptyCredentialForm = () => ({
  channelInstanceId: '',
  token: '', appId: '', appSecret: '', encodingAesKey: '',
  corpId: '', corpSecret: '', openKfId: '',
  botId: '', secret: '',
})
const channelCards = computed(() => [
  {
    id: 'web',
    name: 'Web 官网',
    note: '内置渠道，无需额外凭据',
    status: '本地 E2E 已验证',
    tone: 'success',
    icon: ApiIcon,
  },
  {
    id: 'wechat_official_account',
    name: '微信服务号',
    note: activeWechatCredentials.value.length ? `${activeWechatCredentials.value.length} 个启用实例，等待真实账号联调` : '明文与 AES 回调框架已完成，尚未配置实例',
    status: activeWechatCredentials.value.length ? '已配置' : '未配置',
    tone: activeWechatCredentials.value.length ? 'configured' : 'neutral',
    icon: LinkIcon,
  },
  {
    id: 'wechat_customer_service',
    name: '微信客服',
    note: activeKfCredentials.value.length ? `${activeKfCredentials.value.length} 个启用实例，等待真实账号联调` : '通知同步 + 游标拉取 + 单条答案/图文卡片已就绪，尚未配置实例',
    status: activeKfCredentials.value.length ? '已配置' : '未配置',
    tone: activeKfCredentials.value.length ? 'configured' : 'neutral',
    icon: UserIcon,
  },
  {
    id: 'wecom_bot',
    name: '企业微信机器人',
    note: activeBotCredentials.value.length ? `${activeBotCredentials.value.length} 个启用实例，等待真实 BotId/Secret 联调` : 'WS 长连接真流式已就绪，尚未配置实例',
    status: activeBotCredentials.value.length ? '已配置' : '未配置',
    tone: activeBotCredentials.value.length ? 'configured' : 'neutral',
    icon: ApiIcon,
  },
])

const userById = computed(() => new Map(users.value.map((item) => [item.id, item])))

const errorMessage = (error: unknown, fallback: string) => {
  if (error && typeof error === 'object') {
    const responseData = (error as { response?: { data?: unknown } }).response?.data
    if (responseData && typeof responseData === 'object') {
      const body = responseData as { Error?: { Message?: unknown }; message?: unknown; detail?: unknown }
      const serverMessage = body.Error?.Message ?? body.message ?? body.detail
      if (typeof serverMessage === 'string' && serverMessage.trim()) return serverMessage
    }
    if (error instanceof Error && error.message) return error.message
  }
  return fallback
}

const setToast = (message: string) => {
  toast.value = message
  window.setTimeout(() => { toast.value = '' }, 2800)
}

const loadData = async () => {
  loading.value = true
  loadError.value = ''
  try {
    const [credentialRows, identityRows, userRows] = await Promise.all([
      listChannelCredentials(),
      listAdminChannelIdentities(),
      listPlatformUsers(),
    ])
    credentials.value = credentialRows
    identities.value = identityRows
    users.value = userRows
  } catch (error) {
    loadError.value = errorMessage(error, '暂时无法加载渠道数据，请稍后重试。')
  } finally {
    loading.value = false
  }
}

const CONFIGURABLE_CHANNELS = ['wechat_official_account', 'wechat_customer_service', 'wecom_bot'] as const
const isConfigurableChannel = (id: string) => (CONFIGURABLE_CHANNELS as readonly string[]).includes(id)
const openCredential = (channel: string = 'wechat_official_account') => {
  credentialChannel.value = isConfigurableChannel(channel)
    ? (channel as typeof credentialChannel.value)
    : 'wechat_official_account'
  credentialForm.value = emptyCredentialForm()
  formError.value = ''
  modal.value = 'credential'
}

const openRotate = (item: ChannelCredential) => {
  activeCredential.value = item
  rotateToken.value = ''
  formError.value = ''
  modal.value = 'rotate'
}

const openGuide = (item?: ChannelCredential) => {
  activeCredential.value = item || activeWechatCredentials.value[0] || null
  modal.value = 'guide'
}

const closeModal = () => {
  if (submitting.value) return
  modal.value = null
}

const handleModalKeydown = (event: KeyboardEvent) => {
  if (!modal.value || !modalRef.value) return
  if (event.key === 'Escape') {
    event.preventDefault()
    closeModal()
    return
  }
  if (event.key !== 'Tab') return
  const focusable = Array.from(modalRef.value.querySelectorAll<HTMLElement>(
    'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), a[href]'
  ))
  if (!focusable.length) return
  const first = focusable[0]
  const last = focusable[focusable.length - 1]
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault()
    first.focus()
  }
}

watch(modal, async (value, previous) => {
  if (value && !previous) {
    previouslyFocused.value = document.activeElement instanceof HTMLElement ? document.activeElement : null
    await nextTick()
    const focusable = Array.from(modalRef.value?.querySelectorAll<HTMLElement>(
      'input:not([disabled]), select:not([disabled]), textarea:not([disabled]), button:not([disabled])'
    ) || [])
    const firstFocusable = focusable.find((element) => /^(INPUT|SELECT|TEXTAREA)$/.test(element.tagName)) || focusable[0]
    firstFocusable?.focus()
  } else if (!value && previous) {
    await nextTick()
    previouslyFocused.value?.focus()
    previouslyFocused.value = null
  }
})

const trimmed = (value: string) => value.trim()
const withOptional = (base: Record<string, string>, extras: Record<string, string>) => {
  const out: Record<string, string> = { ...base }
  for (const [key, value] of Object.entries(extras)) {
    if (value.trim()) out[key] = value.trim()
  }
  return out
}

const buildCredential = (): Record<string, string> => {
  const f = credentialForm.value
  if (credentialChannel.value === 'wecom_bot') {
    return { botId: trimmed(f.botId), secret: trimmed(f.secret) }
  }
  if (credentialChannel.value === 'wechat_customer_service') {
    return withOptional(
      { corpId: trimmed(f.corpId) },
      { token: f.token, encodingAESKey: f.encodingAesKey, corpSecret: f.corpSecret, openKfId: f.openKfId },
    )
  }
  return withOptional(
    { token: trimmed(f.token) },
    { appId: f.appId, appSecret: f.appSecret, encodingAesKey: f.encodingAesKey },
  )
}

const credentialSuccessToast = () => ({
  wecom_bot: '企业微信机器人实例已配置，启动 WS 网关即可订阅（本地：python wecom_ws_gateway.py）',
  wechat_customer_service: '微信客服实例已配置，下一步请在企业微信后台填写回调地址',
  wechat_official_account: '微信服务号实例已配置，下一步请在微信后台填写回调地址',
}[credentialChannel.value])

const submitCredential = async () => {
  submitting.value = true
  formError.value = ''
  try {
    await createChannelCredential({
      channel: credentialChannel.value,
      channelInstanceId: credentialForm.value.channelInstanceId.trim(),
      credential: JSON.stringify(buildCredential()),
    })
    modal.value = null
    credentialForm.value = emptyCredentialForm()
    await loadData()
    setToast(credentialSuccessToast())
  } catch (error) {
    formError.value = errorMessage(error, '渠道凭据保存失败。')
  } finally {
    submitting.value = false
  }
}

const submitRotate = async () => {
  if (!activeCredential.value) return
  submitting.value = true
  formError.value = ''
  try {
    await rotateChannelCredential(activeCredential.value.id, JSON.stringify({ token: rotateToken.value }))
    modal.value = null
    rotateToken.value = ''
    await loadData()
    setToast('回调 Token 已轮换，请同步更新微信后台配置')
  } catch (error) {
    formError.value = errorMessage(error, '凭据轮换失败。')
  } finally {
    submitting.value = false
  }
}

const disableCredential = async (item: ChannelCredential) => {
  if (!window.confirm(`确定停用渠道实例 ${item.channelInstanceId} 吗？停用后回调将立即拒绝。`)) return
  submitting.value = true
  try {
    await disableChannelCredential(item.id)
    await loadData()
    setToast('渠道实例已停用')
  } catch (error) {
    setToast(errorMessage(error, '渠道实例停用失败。'))
  } finally {
    submitting.value = false
  }
}

const revokeIdentity = async (item: ChannelIdentity) => {
  if (!window.confirm('确定撤销这个渠道身份吗？撤销后该身份不能继续进入消息队列。')) return
  identityActionId.value = item.id
  try {
    await revokeAdminChannelIdentity(item.id)
    await loadData()
    setToast('渠道身份已撤销')
  } catch (error) {
    setToast(errorMessage(error, '渠道身份撤销失败。'))
  } finally {
    identityActionId.value = null
  }
}

const CALLBACK_PATH: Record<string, string> = {
  wechat_official_account: 'wechat-official-account',
  wechat_customer_service: 'wechat-kf',
}
const callbackUrl = (item: ChannelCredential | null) => {
  if (!item) return ''
  const path = CALLBACK_PATH[item.channel]
  if (!path) return ''  // wecom_bot is an outbound WS long-connection, no callback URL
  return `${window.location.origin}/api/v1/channels/${path}/${encodeURIComponent(item.channelInstanceId)}/callback`
}

const copyCallbackUrl = async (item: ChannelCredential) => {
  try {
    await navigator.clipboard.writeText(callbackUrl(item))
    setToast('回调地址已复制')
  } catch {
    setToast('浏览器未允许复制，请从联调指南中手动复制')
  }
}

const formatTime = (value?: string | null) => value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '—'
const channelLabel = (value: string) => ({ wechat_official_account: '微信服务号', wechat_customer_service: '微信客服', wecom_bot: '企业微信机器人', web: 'Web 官网' } as Record<string, string>)[value] || value
const credentialStatus = (item: ChannelCredential) => item.status === 'active' ? '已配置' : '已停用'
const identityStatus = (value: ChannelIdentity['status']) => ({ active: '已确认', pending: '待确认', revoked: '已撤销', expired: '已过期' } as Record<string, string>)[value] || value
// A binding awaiting channel confirmation has no external identity yet.
const identityDisplay = (value: string | null) => {
  if (!value) return '待渠道确认'
  return value.length <= 10 ? '••••••' : `${value.slice(0, 4)}••••${value.slice(-4)}`
}

onMounted(() => {
  void loadData()
  window.addEventListener('keydown', handleModalKeydown)
})

onBeforeUnmount(() => window.removeEventListener('keydown', handleModalKeydown))
</script>

<template>
  <div v-if="toast" class="channel-toast" role="status" aria-live="polite"><CheckCircleIcon />{{ toast }}</div>
  <section class="channel-intro">
    <div>
      <p class="channel-eyebrow">运营控制台 / 消息入口</p>
      <h1>渠道管理</h1>
      <p>集中配置消息入口、回调凭据和渠道身份。已配置只代表平台凭据可用，不代表第三方渠道已经在线。</p>
    </div>
    <div class="channel-intro-actions">
      <button class="channel-button channel-button--secondary" :disabled="loading" @click="loadData"><RefreshIcon />{{ loading ? '刷新中…' : '刷新' }}</button>
      <button class="channel-button channel-button--primary" @click="openCredential()"><LinkIcon />接入微信服务号</button>
    </div>
  </section>

  <div v-if="loadError" class="channel-alert channel-alert--error"><ErrorCircleIcon /><span>{{ loadError }}</span><button @click="loadData">重试</button></div>

  <section class="channel-catalog" aria-label="渠道目录">
    <article v-for="item in channelCards" :key="item.id" class="channel-card">
      <span class="channel-card-icon"><component :is="item.icon" /></span>
      <div class="channel-card-main"><strong>{{ item.name }}</strong><p>{{ item.note }}</p></div>
      <span class="channel-badge" :class="`channel-badge--${item.tone}`"><i></i>{{ item.status }}</span>
      <div class="channel-card-actions">
        <button v-if="isConfigurableChannel(item.id)" class="channel-text-button" @click="openCredential(item.id)">配置</button>
        <button v-if="item.id === 'wechat_official_account'" class="channel-text-button" @click="openGuide()">联调说明</button>
      </div>
    </article>
  </section>

  <section class="channel-panel">
    <header class="channel-panel-heading">
      <div><p>CHANNEL INSTANCES</p><h2>渠道实例</h2></div>
      <span>{{ credentials.length }} 个实例</span>
    </header>
    <div v-if="loading && !credentials.length" class="channel-empty">正在加载渠道实例…</div>
    <div v-else-if="!credentials.length" class="channel-empty"><LinkIcon /><strong>还没有渠道实例</strong><p>渠道是平台级入口，配置一个实例即可接收第三方消息。</p></div>
    <div v-else class="channel-table">
      <div class="channel-table-head"><span>渠道 / 实例</span><span>平台归属</span><span>凭据</span><span>状态</span><span>操作</span></div>
      <article v-for="item in credentials" :key="item.id" class="channel-table-row">
        <div class="channel-table-primary"><strong>{{ channelLabel(item.channel) }}</strong><small>{{ item.channelInstanceId }}</small></div>
        <div><strong>OceanDesk 平台</strong><small>全局入口渠道</small></div>
        <div><strong>{{ item.credentialMask }} · v{{ item.version }}</strong><small>更新于 {{ formatTime(item.updatedAt) }}</small></div>
        <span class="channel-status" :class="{ 'channel-status--off': item.status !== 'active' }"><i></i>{{ credentialStatus(item) }}</span>
        <div class="channel-row-actions">
          <button @click="openGuide(item)">指南</button>
          <button :disabled="item.status !== 'active' || submitting" @click="copyCallbackUrl(item)">复制地址</button>
          <button :disabled="item.status !== 'active' || submitting" @click="openRotate(item)">轮换</button>
          <button class="channel-danger" :disabled="item.status !== 'active' || submitting" @click="disableCredential(item)">停用</button>
        </div>
      </article>
    </div>
  </section>

  <section class="channel-panel">
    <header class="channel-panel-heading">
      <div><p>平台用户映射</p><h2>渠道身份</h2></div>
      <span>{{ identities.length }} 条绑定</span>
    </header>
    <div v-if="loading && !identities.length" class="channel-empty">正在加载渠道身份…</div>
    <div v-else-if="!identities.length" class="channel-empty"><UserIcon /><strong>暂无渠道身份</strong><p>身份只关联平台用户；企业范围将在每次消息执行时按当前权限解析。</p></div>
    <div v-else class="channel-table channel-identity-table">
      <div class="channel-table-head"><span>渠道身份</span><span>平台用户</span><span>状态</span><span>操作</span></div>
      <article v-for="item in identities" :key="item.id" class="channel-table-row">
        <div class="channel-table-primary"><strong>{{ channelLabel(item.channel) }}</strong><small>{{ item.channelInstanceId }} · {{ identityDisplay(item.externalIdentityId) }}</small></div>
        <div><strong>{{ userById.get(item.userId)?.name || '未知用户' }}</strong><small>{{ userById.get(item.userId)?.phone || item.userId }}</small></div>
        <span class="channel-status" :class="{ 'channel-status--off': item.status !== 'active' }"><i></i>{{ identityStatus(item.status) }}</span>
        <div class="channel-row-actions"><button class="channel-danger" :disabled="item.status !== 'active' || identityActionId === item.id" @click="revokeIdentity(item)">{{ identityActionId === item.id ? '撤销中…' : '撤销' }}</button></div>
      </article>
    </div>
  </section>

  <div v-if="modal" class="channel-modal-backdrop" @click.self="closeModal">
    <form v-if="modal === 'credential'" ref="modalRef" class="channel-modal" role="dialog" aria-modal="true" aria-labelledby="channel-modal-title" @submit.prevent="submitCredential">
      <header><div><p>{{ channelLabel(credentialChannel) }}</p><h2 id="channel-modal-title">配置渠道实例</h2></div><button type="button" aria-label="关闭" :disabled="submitting" @click="closeModal"><CloseIcon /></button></header>
      <div class="channel-modal-notice"><LockOnIcon /><span>凭据会加密保存，提交后不会再次显示。</span></div>
      <label>渠道实例 ID<input v-model="credentialForm.channelInstanceId" required maxlength="128" pattern="[A-Za-z0-9][A-Za-z0-9._\-]{1,127}" placeholder="例如 oa-customer-service" /><small>渠道级唯一标识，保存后不可修改。</small></label>

      <template v-if="credentialChannel === 'wechat_official_account'">
        <label>回调 Token<input v-model="credentialForm.token" required minlength="3" maxlength="512" type="password" autocomplete="new-password" placeholder="与微信后台填写的 Token 一致" /></label>
        <label>微信 AppID（安全模式必填）<input v-model="credentialForm.appId" maxlength="128" autocomplete="off" placeholder="例如 wxxxxxxxxxxxxxxxx" /></label>
        <label>微信 AppSecret（发送消息时使用）<input v-model="credentialForm.appSecret" maxlength="512" type="password" autocomplete="new-password" /></label>
        <label>EncodingAESKey（安全模式）<input v-model="credentialForm.encodingAesKey" maxlength="44" autocomplete="off" placeholder="微信后台生成的 43 位密钥" /><small>填写 AppID 和 EncodingAESKey 后回调可用安全模式；只填 Token 则保持明文兼容。</small></label>
      </template>

      <template v-else-if="credentialChannel === 'wechat_customer_service'">
        <label>企业 CorpID<input v-model="credentialForm.corpId" required maxlength="128" autocomplete="off" placeholder="企业微信的 CorpID" /></label>
        <label>回调 Token<input v-model="credentialForm.token" maxlength="512" type="password" autocomplete="new-password" placeholder="与企业微信回调配置一致" /></label>
        <label>EncodingAESKey<input v-model="credentialForm.encodingAesKey" maxlength="44" autocomplete="off" placeholder="43 位回调加密密钥" /></label>
        <label>客服 Secret（拉取/发送消息）<input v-model="credentialForm.corpSecret" maxlength="512" type="password" autocomplete="new-password" /></label>
        <label>Open KfID（可选，限定客服账号）<input v-model="credentialForm.openKfId" maxlength="128" autocomplete="off" placeholder="留空则不限定" /></label>
        <small>CorpID + Token + EncodingAESKey 用于接收回调；CorpID + Secret 用于拉取消息和发送回复。</small>
      </template>

      <template v-else-if="credentialChannel === 'wecom_bot'">
        <label>BotID<input v-model="credentialForm.botId" required maxlength="128" autocomplete="off" placeholder="智能机器人的 BotID" /></label>
        <label>Secret<input v-model="credentialForm.secret" required maxlength="512" type="password" autocomplete="new-password" placeholder="长连接订阅 Secret" /></label>
        <small>WS 长连接真流式，只需 BotID + Secret；配置后启动 WS 网关即可订阅（无需公网回调）。</small>
      </template>

      <div v-if="formError" class="channel-form-error"><ErrorCircleIcon />{{ formError }}</div>
      <footer><button type="button" class="channel-button channel-button--secondary" :disabled="submitting" @click="closeModal">取消</button><button type="submit" class="channel-button channel-button--primary" :disabled="submitting">{{ submitting ? '保存中…' : '保存实例' }}</button></footer>
    </form>

    <form v-else-if="modal === 'rotate'" ref="modalRef" class="channel-modal" role="dialog" aria-modal="true" aria-labelledby="channel-modal-title" @submit.prevent="submitRotate">
      <header><div><p>凭据轮换</p><h2 id="channel-modal-title">{{ activeCredential?.channelInstanceId }}</h2></div><button type="button" aria-label="关闭" :disabled="submitting" @click="closeModal"><CloseIcon /></button></header>
      <p class="channel-modal-description">保存后旧 Token 立即失效。请在同一维护窗口同步更新微信后台，避免回调中断。</p>
      <label>新回调 Token<input v-model="rotateToken" required minlength="3" maxlength="512" type="password" autocomplete="new-password" /></label>
      <div v-if="formError" class="channel-form-error"><ErrorCircleIcon />{{ formError }}</div>
      <footer><button type="button" class="channel-button channel-button--secondary" :disabled="submitting" @click="closeModal">取消</button><button type="submit" class="channel-button channel-button--primary" :disabled="submitting">{{ submitting ? '轮换中…' : '确认轮换' }}</button></footer>
    </form>

    <section v-else ref="modalRef" class="channel-modal channel-guide" role="dialog" aria-modal="true" aria-labelledby="channel-modal-title">
      <header><div><p>微信服务号</p><h2 id="channel-modal-title">端到端联调指南</h2></div><button type="button" aria-label="关闭" @click="closeModal"><CloseIcon /></button></header>
      <div v-if="activeCredential" class="channel-callback"><span>回调地址</span><code>{{ callbackUrl(activeCredential) }}</code><button type="button" class="channel-button channel-button--secondary" @click="copyCallbackUrl(activeCredential)">复制地址</button></div>
      <div v-else class="channel-modal-notice"><ErrorCircleIcon /><span>请先配置一个启用的微信服务号实例，才能生成回调地址。</span></div>
      <ol>
        <li>在微信公众平台服务器配置中粘贴回调地址，Token 必须与本平台保存值一致。</li>
        <li>可在微信后台选择明文模式，或填写 AppID/EncodingAESKey 后选择安全模式。</li>
        <li>先在平台完成 OpenID 渠道身份确认，再向服务号发送文本消息。</li>
        <li>检查消息是否进入 durable queue、Worker 是否生成回复任务；当前真实客服消息发送尚未配置。</li>
      </ol>
      <div class="channel-guide-warning"><strong>真实联调仍需账号验证</strong><p>本地已覆盖明文与 AES 协议边界，但真实回调、OpenID 身份绑定和发送 API 仍需微信服务号后台验证。</p></div>
      <footer><button type="button" class="channel-button channel-button--primary" @click="closeModal">知道了</button></footer>
    </section>
  </div>
</template>

<style scoped>
.channel-intro { display: flex; justify-content: space-between; gap: 24px; margin-bottom: 24px; }
.channel-intro > div:first-child { min-width: 0; }
.channel-eyebrow, .channel-panel-heading p, .channel-modal header p { margin: 0 0 8px; color: #759189; font-size: 10px; font-weight: 750; letter-spacing: .12em; }
.channel-intro h1 { margin: 0 0 9px; color: #17312e; font-size: 30px; letter-spacing: -.035em; }
.channel-intro p { max-width: 720px; margin: 0; color: #688079; font-size: 12px; line-height: 1.65; }
.channel-intro-actions { display: flex; align-items: flex-start; gap: 10px; }
.channel-button { min-height: 44px; display: inline-flex; align-items: center; justify-content: center; gap: 7px; border-radius: 6px; padding: 0 14px; font: inherit; font-size: 11px; font-weight: 700; cursor: pointer; }
.channel-button :deep(svg) { width: 15px; }
.channel-button--primary { border: 1px solid #147d72; color: #fff; background: #147d72; }
.channel-button--secondary { border: 1px solid #cdded9; color: #3d625a; background: #fff; }
.channel-button:disabled { opacity: .52; cursor: not-allowed; }
.channel-alert { min-height: 48px; display: flex; align-items: center; gap: 9px; margin-bottom: 18px; padding: 10px 13px; border: 1px solid #eadabf; background: #fffaf0; color: #78613f; font-size: 11px; line-height: 1.5; }
.channel-alert--error { border-color: #ebc9c3; background: #fff3f1; color: #99534c; }
.channel-alert :deep(svg) { flex: 0 0 16px; width: 16px; }
.channel-alert span { min-width: 0; flex: 1; }
.channel-alert button { min-height: 38px; border: 0; padding: 0 10px; color: inherit; background: transparent; font: inherit; font-weight: 700; cursor: pointer; }
.channel-toast { position: fixed; z-index: 120; top: 84px; right: 26px; min-height: 44px; display: flex; align-items: center; gap: 8px; padding: 0 14px; color: #276c59; border: 1px solid #bcdaca; background: #eff9f4; box-shadow: 0 12px 34px rgba(31, 72, 61, .14); font-size: 11px; }
.channel-toast :deep(svg) { width: 16px; }
.channel-catalog { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-bottom: 22px; }
.channel-card { min-width: 0; display: grid; grid-template-columns: 38px minmax(0, 1fr); gap: 11px; align-content: start; padding: 16px; border: 1px solid #dce8e4; background: #fff; }
.channel-card-icon { width: 38px; height: 38px; display: grid; place-items: center; color: #247a6e; background: #edf7f3; }
.channel-card-icon :deep(svg) { width: 19px; }
.channel-card-main { min-width: 0; }
.channel-card-main strong { display: block; margin: 1px 0 5px; color: #27453e; font-size: 12px; }
.channel-card-main p { min-height: 32px; margin: 0; color: #7a8e88; font-size: 10px; line-height: 1.55; overflow-wrap: anywhere; }
.channel-badge { grid-column: 1 / 3; display: inline-flex; align-items: center; gap: 6px; justify-self: start; color: #728680; font-size: 10px; }
.channel-badge i, .channel-status i { width: 7px; height: 7px; border-radius: 50%; background: #9baaa6; }
.channel-badge--success { color: #33806c; }.channel-badge--success i { background: #45a57f; }
.channel-badge--configured { color: #39776b; }.channel-badge--configured i { background: #4b9d83; }
.channel-badge--pending { color: #92703b; }.channel-badge--pending i { background: #d09b4c; }
.channel-text-button { grid-column: 1 / 3; min-height: 36px; justify-self: start; border: 0; padding: 0; color: #27786c; background: transparent; font: inherit; font-size: 10px; font-weight: 700; cursor: pointer; }
.channel-panel { margin-top: 18px; overflow: hidden; border: 1px solid #dce8e4; background: #fff; }
.channel-panel-heading { min-height: 68px; display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 0 20px; border-bottom: 1px solid #e8efec; }
.channel-panel-heading p { margin-bottom: 4px; }
.channel-panel-heading h2 { margin: 0; color: #284740; font-size: 15px; }
.channel-panel-heading > span { color: #83948f; font-size: 10px; }
.channel-empty { min-height: 150px; display: grid; place-items: center; align-content: center; gap: 7px; padding: 30px; color: #879792; text-align: center; font-size: 11px; }
.channel-empty :deep(svg) { width: 24px; color: #7fa297; }
.channel-empty strong { color: #536f68; font-size: 12px; }.channel-empty p { margin: 0; }
.channel-table-head, .channel-table-row { display: grid; grid-template-columns: minmax(150px, 1.1fr) minmax(180px, 1.3fr) minmax(150px, 1fr) 80px minmax(225px, auto); column-gap: 14px; align-items: center; padding: 0 20px; }
.channel-identity-table .channel-table-head, .channel-identity-table .channel-table-row { grid-template-columns: minmax(180px, 1.25fr) minmax(180px, 1.2fr) 90px minmax(180px, auto); }
.channel-table-head { min-height: 42px; color: #82918d; background: #f7faf9; border-bottom: 1px solid #e8efec; font-size: 10px; font-weight: 700; }
.channel-table-row { min-height: 76px; border-bottom: 1px solid #edf2f0; color: #46635c; }
.channel-table-row:last-child { border-bottom: 0; }
.channel-table-row > div { min-width: 0; }
.channel-table-row strong, .channel-table-row small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.channel-table-row strong { color: #36564f; font-size: 11px; }.channel-table-row small { margin-top: 4px; color: #899893; font-size: 9px; }
.channel-table-primary strong { color: #235f55; font-size: 12px; }
.channel-status { display: inline-flex; align-items: center; gap: 6px; color: #33806c; font-size: 10px; white-space: nowrap; }
.channel-status i { background: #45a57f; }.channel-status--off { color: #8b7771; }.channel-status--off i { background: #b7a39c; }
.channel-row-actions { display: flex; justify-content: flex-end; gap: 3px; white-space: nowrap; }
.channel-row-actions button { min-height: 40px; border: 0; padding: 0 7px; color: #317c70; background: transparent; font: inherit; font-size: 10px; cursor: pointer; }
.channel-row-actions button:hover { background: #eef7f4; }.channel-row-actions button:disabled { color: #b8c2bf; background: transparent; cursor: not-allowed; }
.channel-row-actions .channel-danger { color: #a24e4e; }.channel-row-actions .channel-danger:hover { background: #fff3f1; }
.channel-modal-backdrop { position: fixed; inset: 0; z-index: 110; display: grid; place-items: center; padding: 16px; background: rgba(20, 35, 34, .42); }
.channel-modal { width: min(540px, 100%); max-height: calc(100vh - 32px); display: grid; gap: 16px; overflow: auto; padding: 24px; border: 1px solid #dbe7e2; background: #fff; box-shadow: 0 20px 60px rgba(24, 50, 44, .22); }
.channel-modal header { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.channel-modal header p { margin-bottom: 5px; }.channel-modal h2 { margin: 0; color: #17312e; font-size: 20px; }
.channel-modal header > button { width: 44px; height: 44px; flex: 0 0 44px; border: 0; color: #82918d; background: transparent; font-size: 22px; cursor: pointer; }
.channel-modal header > button :deep(svg) { width: 18px; height: 18px; }
.channel-modal:focus { outline: none; }
.channel-modal label { display: grid; gap: 7px; color: #527069; font-size: 11px; font-weight: 700; }
.channel-modal input, .channel-modal select { width: 100%; min-height: 44px; border: 1px solid #d6e3df; padding: 0 10px; color: #24433d; background: #fff; font: inherit; font-size: 12px; }
.channel-modal input:focus, .channel-modal select:focus { outline: 2px solid rgba(20, 125, 114, .2); border-color: #147d72; }
.channel-modal label small { color: #82938e; font-size: 9px; font-weight: 400; }
.channel-modal footer { display: flex; justify-content: flex-end; gap: 10px; padding-top: 4px; }
.channel-modal-notice, .channel-form-error { display: flex; align-items: flex-start; gap: 8px; padding: 10px 11px; font-size: 10px; line-height: 1.5; }
.channel-modal-notice { border: 1px solid #d3e5de; color: #3d6f62; background: #f1f8f5; }.channel-form-error { border: 1px solid #ebc9c3; color: #99534c; background: #fff3f1; }
.channel-modal-notice :deep(svg), .channel-form-error :deep(svg) { flex: 0 0 15px; width: 15px; margin-top: 1px; }
.channel-modal-description { margin: 0; color: #70857f; font-size: 11px; line-height: 1.6; }
.channel-callback { display: grid; gap: 8px; padding: 12px; background: #f5f8f7; }
.channel-callback span { color: #6d827c; font-size: 10px; font-weight: 700; }.channel-callback code { overflow-wrap: anywhere; color: #2f5f55; font-size: 10px; line-height: 1.6; }
.channel-callback .channel-button { justify-self: start; }
.channel-guide ol { display: grid; gap: 9px; margin: 0; padding-left: 22px; color: #536f68; font-size: 11px; line-height: 1.55; }
.channel-guide-warning { padding: 12px; border: 1px solid #eadabf; background: #fff9ed; color: #795e3d; }
.channel-guide-warning strong { font-size: 11px; }.channel-guide-warning p { margin: 5px 0 0; font-size: 10px; line-height: 1.55; }
button:focus-visible { outline: 2px solid rgba(20, 125, 114, .34); outline-offset: 2px; }

@media (max-width: 1100px) {
  .channel-catalog { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .channel-table-head, .channel-table-row { grid-template-columns: minmax(140px, 1fr) minmax(160px, 1fr) 80px minmax(210px, auto); }
  .channel-table-head > :nth-child(3), .channel-table-row > :nth-child(3) { display: none; }
  .channel-identity-table .channel-table-head, .channel-identity-table .channel-table-row { grid-template-columns: minmax(160px, 1.2fr) minmax(160px, 1fr) 90px minmax(120px, auto); }
  .channel-identity-table .channel-table-head > :nth-child(3) { display: block; }
  .channel-identity-table .channel-table-row > :nth-child(3) { display: inline-flex; }
}
@media (max-width: 760px) {
  .channel-intro { display: block; }.channel-intro-actions { margin-top: 16px; flex-wrap: wrap; }
  .channel-table-head { display: none; }
  .channel-table-row { grid-template-columns: minmax(0, 1fr) auto; gap: 9px 14px; min-height: 0; padding: 15px 16px; }
  .channel-identity-table .channel-table-row { grid-template-columns: minmax(0, 1fr) auto; }
  .channel-table-row > :nth-child(2), .channel-table-row > :nth-child(3) { display: block; grid-column: 1 / 3; }
  .channel-table-row > .channel-status { grid-column: 2; grid-row: 1; }
  .channel-identity-table .channel-table-row > .channel-status { display: inline-flex; grid-column: 2; grid-row: 1; }
  .channel-row-actions { grid-column: 1 / 3; justify-content: flex-start; flex-wrap: wrap; padding-top: 7px; border-top: 1px solid #edf2f0; }
}
@media (max-width: 520px) {
  .channel-catalog { grid-template-columns: 1fr; }
  .channel-intro h1 { font-size: 26px; }.channel-intro-actions { display: grid; grid-template-columns: 1fr 1fr; }
  .channel-panel-heading { padding: 0 15px; }.channel-table-row { padding: 14px 15px; }
  .channel-modal { padding: 18px; }.channel-modal footer { position: sticky; bottom: -18px; margin: 0 -18px -18px; padding: 12px 18px 18px; background: #fff; border-top: 1px solid #edf1f0; }
  .channel-toast { top: 70px; right: 14px; left: 14px; }
}
</style>
