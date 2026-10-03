<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ApiIcon,
  BrowseIcon,
  BrowseOffIcon,
  CheckCircleIcon,
  ChevronRightIcon,
  HistoryIcon,
  LockOnIcon,
  RefreshIcon,
  SearchIcon,
  SettingIcon,
  UsergroupIcon,
  UserIcon,
  ErrorCircleIcon,
} from 'tdesign-icons-vue-next'
import PlatformShell from '@/components/PlatformShell.vue'
import AdminAdpApiKeys from '@/components/admin/AdminAdpApiKeys.vue'
import AdminChannelManagement from '@/components/admin/AdminChannelManagement.vue'
import PlatformSelect from '@/components/admin/PlatformSelect.vue'
import {
  createEnterprise,
  createPlatformUser,
  createAdpApp,
  deleteAdpApp,
  disablePlatformUser,
  getAdminConfig,
  getAdminConversation,
  getAdminOverview,
  listAdpApps,
  listAdminConversations,
  listAuditEvents,
  listEnterprises,
  listPlatformUsers,
  resetPlatformUserPassword,
  rollbackAdminConfig,
  saveAdminConfigDraft,
  publishAdminConfig,
  updateAdpApp,
  updateEnterprise,
  updatePlatformUserAccess,
} from '@/platform/platformService'
import type { AdpApp, AdminAuditEvent, AdminConfigState, AdminConversationSummary, AdminConversationDetail, AdminEnterprise, AdminOverview, AdminUser, PlatformConfigPayload, PlatformRole } from '@/platform/types'
import { logout } from '@/service/login'
import { usePlatformStore } from '@/stores/platform'

const route = useRoute()
const router = useRouter()
const overview = ref<AdminOverview | null>(null)
const configState = ref<AdminConfigState | null>(null)
const enterprises = ref<AdminEnterprise[]>([])
const users = ref<AdminUser[]>([])
// 登录口令仅哈希存储、服务端不留明文；这里只在本会话内缓存「创建/重置」时一次性返回的口令，
// 供列表用小眼睛按需显示，刷新页面即失效，不做任何持久化。
const revealedPasswords = ref<Record<string, string>>({})
const passwordVisible = ref<Record<string, boolean>>({})
const togglePassword = (id: string) => {
  passwordVisible.value = { ...passwordVisible.value, [id]: !passwordVisible.value[id] }
}
const auditEvents = ref<AdminAuditEvent[]>([])
const conversations = ref<AdminConversationSummary[]>([])
const conversationTotal = ref(0)
const conversationOffset = ref(0)
const conversationSearch = ref('')
const conversationDetail = ref<AdminConversationDetail | null>(null)
const conversationDetailLoading = ref(false)
const CONVERSATION_PAGE = 50
const loading = ref(false)
const loadError = ref('')
const toast = ref('')
const enterpriseSearch = ref('')
const userSearch = ref('')
const userEnterpriseFilter = ref('')
const auditSearch = ref('')
const modal = ref<'enterprise' | 'user' | 'config' | 'access' | 'adpApp' | null>(null)
const detail = ref<{ title: string; lines: string[] } | null>(null)
const secretMessage = ref('')
const enterpriseForm = ref({ id: '', name: '', customerCode: '', unifiedSocialCreditCode: '', contactPerson: '', contactPhone: '', adpAppId: '' })
const adpApps = ref<AdpApp[]>([])
type AdpProviderType = 'tencent_adp' | 'aliyun_adp' | 'volcengine_adp'
const adpProviderOptions: Array<{ value: AdpProviderType; label: string; registered: boolean }> = [
  { value: 'tencent_adp', label: '腾讯云 ADP', registered: true },
  { value: 'aliyun_adp', label: '阿里云 ADP（待接入）', registered: false },
  { value: 'volcengine_adp', label: '火山引擎 ADP（待接入）', registered: false },
]
const adpAppForm = ref({ id: '', name: '', applicationId: '', providerType: 'tencent_adp' as AdpProviderType, providerSchemaVersion: 1, providerSettingsText: '{}', credentialsText: '', appKey: '', tcSecretAppId: '', tcSecretId: '', tcSecretKey: '', vendor: 'Tencent', serviceVendor: 'ChinaTencentCloud', agentId: 'platform-default', privateUrl: '', isDefault: false })
const isTencentAdp = computed(() => adpAppForm.value.providerType === 'tencent_adp')
const selectedProvider = computed(() => adpProviderOptions.find((item) => item.value === adpAppForm.value.providerType))
const adpAppActionId = ref<string | null>(null)
const userForm = ref({ name: '', phone: '', role: 'customer' as PlatformRole, enterpriseId: '' })
const configForm = ref({ itemsText: '', portal: true, m3ReadOnly: true, audit: true, webChannel: true, notes: '' })
const configActionLoading = ref(false)
const createActionLoading = ref(false)
const userActionLoading = ref<string | null>(null)
const accessUser = ref<AdminUser | null>(null)
const accessRole = ref<PlatformRole>('customer')
const accessEnterpriseId = ref<string>('')
const accessActionLoading = ref(false)
const accessFormError = ref('')
const platformStore = usePlatformStore()

const roleOptions: Array<{ value: PlatformRole; label: string }> = [
  { value: 'customer', label: '客户员工' },
  { value: 'staff', label: '客服 / 销售' },
  { value: 'ops', label: '运维人员' },
  { value: 'admin', label: '平台管理员' },
]
const roleSelectOptions = computed(() => roleOptions.map((item) => ({ value: item.value, label: item.label })))
const enterpriseSelectOptions = computed(() => enterprises.value.map((item) => ({ value: item.id, label: item.name + (item.status === 'active' ? '' : '（已停用）'), disabled: item.status !== 'active' })))
const enterpriseFilterOptions = computed(() => [{ value: '', label: '全部企业' }, ...enterprises.value.map((item) => ({ value: item.id, label: item.name }))])
const adpAppSelectOptions = computed(() => [{ value: '', label: '平台默认' }, ...adpApps.value.map((item) => ({ value: item.id, label: item.name + (item.status === 'active' ? '' : '（已停用）'), disabled: item.status !== 'active' }))])

const userStatusLabel = (status: AdminUser['status']) => status === 'active' ? '正常' : '已停用'

const errorMessage = (error: unknown, fallback: string) => {
  if (error && typeof error === 'object') {
    const responseData = (error as { response?: { data?: unknown } }).response?.data
    if (responseData && typeof responseData === 'object') {
      const body = responseData as {
        Error?: { Message?: unknown }
        message?: unknown
        detail?: unknown
      }
      const serverMessage = body.Error?.Message ?? body.message ?? body.detail
      if (typeof serverMessage === 'string' && serverMessage.trim()) return serverMessage
    }
    if (error instanceof Error && error.message && !/^Request failed with status code \d+$/.test(error.message)) {
      return error.message
    }
  }
  return fallback
}

const view = computed(() => route.name === 'admin' ? 'overview' : String(route.name || '').replace('admin-', ''))
const pageTitle = computed(() => ({
  'open-api': '开放接口', overview: '运营概览', enterprises: '企业管理', users: '平台用户', bindings: 'ADP 应用配置', channels: '渠道管理', 'agents-tools': 'Agent 与工具', conversations: '历史对话', audit: '审计日志',
} as Record<string, string>)[view.value] || '运营概览')

const resourceMeta = computed(() => ({
  enterprises: { eyebrow: '客户目录', title: '企业管理', description: '登记入驻企业的名称、社会统一识别码与联系人信息；企业成员账号在「平台用户」维护。', icon: UsergroupIcon },
  users: { eyebrow: '身份治理', title: '平台用户', description: '为企业成员分配账号、角色与可见业务范围。', icon: UserIcon },
  bindings: { eyebrow: '平台配置', title: 'ADP 应用配置', description: '管理应用及加密凭据。业务调用优先使用企业绑定的应用，未绑定时使用平台默认应用；未配置或绑定应用停用时停止调用。', icon: ApiIcon },
  channels: { eyebrow: '消息入口', title: '渠道管理', description: '配置渠道实例、凭据和渠道身份，查看每个接入的真实验证边界。', icon: ApiIcon },
  'agents-tools': { eyebrow: '能力编排', title: 'Agent 与工具', description: '登记的 Agent 与工具目录接口尚未接入，当前不展示演示数据。', icon: SettingIcon },
  conversations: { eyebrow: '可追溯性', title: '历史对话', description: '跨企业查看对话、执行轮次与证据（只读）。业务正文不会在这里全量展示。', icon: HistoryIcon },
  audit: { eyebrow: '可追溯性', title: '审计日志', description: '查看脱敏的管理与投递事件、动作与结果。', icon: HistoryIcon },
} as Record<string, { eyebrow: string; title: string; description: string; icon: typeof UserIcon }>)[view.value])

const filteredEnterprises = computed(() => {
  const term = enterpriseSearch.value.trim().toLowerCase()
  return enterprises.value.filter((item) => !term || `${item.name} ${item.customerCode}`.toLowerCase().includes(term))
})
const filteredUsers = computed(() => {
  const term = userSearch.value.trim().toLowerCase()
  const enterpriseId = userEnterpriseFilter.value
  return users.value.filter((item) => {
    if (enterpriseId && !item.enterprises.some((enterprise) => enterprise.id === enterpriseId)) return false
    return !term || `${item.name} ${item.phone} ${item.roleLabel} ${enterpriseSummary(item)}`.toLowerCase().includes(term)
  })
})
const filteredAudit = computed(() => {
  const term = auditSearch.value.trim().toLowerCase()
  return auditEvents.value.filter((item) => !term || `${item.action} ${item.targetType} ${item.targetId || ''} ${item.traceId}`.toLowerCase().includes(term))
})
const filteredConversations = computed(() => {
  const term = conversationSearch.value.trim().toLowerCase()
  return conversations.value.filter((item) => !term || `${item.title} ${item.query || ''} ${item.enterpriseName || ''} ${item.accountName || ''} ${item.channel}`.toLowerCase().includes(term))
})
const publishedConfig = computed(() => configState.value?.published || overview.value?.config.published || null)
const draftConfig = computed(() => configState.value?.draft || overview.value?.config.draft || null)
const configHistory = computed(() => configState.value?.history || overview.value?.config.history || [])

const setToast = (message: string) => {
  toast.value = message
  window.setTimeout(() => { toast.value = '' }, 2600)
}

const loadData = async () => {
  loading.value = true
  loadError.value = ''
  try {
    if (view.value === 'overview') {
      const [overviewData, configData] = await Promise.all([getAdminOverview(), getAdminConfig()])
      overview.value = overviewData
      configState.value = configData
    }
    if (view.value === 'enterprises') {
      const [enterpriseRows, appRows] = await Promise.all([listEnterprises(), listAdpApps()])
      enterprises.value = enterpriseRows
      adpApps.value = appRows
    }
    if (view.value === 'users') {
      const [userRows, enterpriseRows] = await Promise.all([listPlatformUsers(), listEnterprises()])
      users.value = userRows
      enterprises.value = enterpriseRows
    }
    if (view.value === 'bindings') {
      const appRows = await listAdpApps()
      adpApps.value = appRows
    }
    if (view.value === 'audit') auditEvents.value = await listAuditEvents()
    if (view.value === 'conversations') {
      const page = await listAdminConversations({ limit: CONVERSATION_PAGE, offset: conversationOffset.value })
      conversations.value = page.items
      conversationTotal.value = page.total
    }
  } catch {
    loadError.value = '暂时无法加载管理数据，请稍后重试。'
  } finally {
    loading.value = false
  }
}

onMounted(loadData)
watch(view, () => {
  enterpriseSearch.value = ''
  userSearch.value = ''
  userEnterpriseFilter.value = ''
  auditSearch.value = ''
  conversationSearch.value = ''
  conversationOffset.value = 0
  void loadData()
})

const refresh = async () => {
  await loadData()
  if (!loadError.value) setToast('数据已刷新')
}

const openCreate = (target?: 'enterprise' | 'user') => {
  secretMessage.value = ''
  if ((target || 'enterprise') === 'enterprise') {
    enterpriseForm.value = { id: '', name: '', customerCode: '', unifiedSocialCreditCode: '', contactPerson: '', contactPhone: '', adpAppId: '' }
    modal.value = 'enterprise'
  } else {
    userForm.value = { name: '', phone: '', role: 'customer', enterpriseId: enterprises.value[0]?.id || '' }
    modal.value = 'user'
  }
}

const openEditEnterprise = (item: AdminEnterprise) => {
  secretMessage.value = ''
  enterpriseForm.value = {
    id: item.id,
    name: item.name,
    customerCode: item.customerCode,
    unifiedSocialCreditCode: item.unifiedSocialCreditCode || '',
    contactPerson: item.contactPerson || '',
    contactPhone: item.contactPhone || '',
    adpAppId: item.adpAppId || '',
  }
  modal.value = 'enterprise'
}

const adpAppName = (id: string | null | undefined) => id ? (adpApps.value.find((app) => app.id === id)?.name || id) : '平台默认'

const openCreateAdpApp = () => {
  adpAppForm.value = { id: '', name: '', applicationId: '', providerType: 'tencent_adp', providerSchemaVersion: 1, providerSettingsText: '{}', credentialsText: '', appKey: '', tcSecretAppId: '', tcSecretId: '', tcSecretKey: '', vendor: 'Tencent', serviceVendor: 'ChinaTencentCloud', agentId: 'platform-default', privateUrl: '', isDefault: false }
  modal.value = 'adpApp'
}
const openEditAdpApp = (app: AdpApp) => {
  adpAppForm.value = { id: app.id, name: app.name, applicationId: app.applicationId, providerType: app.providerType, providerSchemaVersion: app.providerSchemaVersion, providerSettingsText: JSON.stringify(app.providerSettings || {}, null, 2), credentialsText: '', appKey: '', tcSecretAppId: '', tcSecretId: '', tcSecretKey: '', vendor: app.vendor, serviceVendor: app.serviceVendor, agentId: app.agentId, privateUrl: '', isDefault: app.isDefault }
  modal.value = 'adpApp'
}
const parseJsonObject = (value: string, label: string): Record<string, unknown> => {
  try {
    const parsed = JSON.parse(value || '{}')
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error()
    return parsed as Record<string, unknown>
  } catch {
    throw new Error(`${label} 必须是 JSON 对象`)
  }
}
const parseCredentials = (value: string): Record<string, string> => {
  const parsed = parseJsonObject(value, 'credentials')
  const credentials: Record<string, string> = {}
  for (const [key, item] of Object.entries(parsed)) {
    if (typeof item !== 'string' || !item.trim()) throw new Error('credentials 的值必须是非空字符串')
    credentials[key] = item
  }
  return credentials
}
const submitAdpApp = async () => {
  createActionLoading.value = true
  try {
    const form = adpAppForm.value
    const providerSettings = parseJsonObject(form.providerSettingsText, 'providerSettings')
    const genericCredentials = form.credentialsText.trim() ? parseCredentials(form.credentialsText) : undefined
    if (!isTencentAdp.value && !form.id && !genericCredentials) throw new Error('请填写 credentials')
    const providerFields = {
      providerType: form.providerType,
      providerSchemaVersion: form.providerSchemaVersion,
      providerSettings,
      ...(genericCredentials ? { credentials: genericCredentials } : {}),
    }
    if (form.id) {
      await updateAdpApp(form.id, {
        name: form.name,
        ...providerFields,
        ...(form.appKey.trim() ? { appKey: form.appKey.trim() } : {}),
        ...(form.tcSecretAppId.trim() ? { tcSecretAppId: form.tcSecretAppId.trim() } : {}),
        ...(form.tcSecretId.trim() ? { tcSecretId: form.tcSecretId.trim() } : {}),
        ...(form.tcSecretKey.trim() ? { tcSecretKey: form.tcSecretKey.trim() } : {}),
        vendor: form.vendor,
        serviceVendor: form.serviceVendor,
        agentId: form.agentId,
        ...(form.privateUrl.trim() ? { privateUrl: form.privateUrl.trim() } : {}),
        isDefault: form.isDefault,
      })
      setToast('ADP 应用已更新')
    } else {
      await createAdpApp({
        name: form.name,
        applicationId: form.applicationId,
        ...providerFields,
        ...(isTencentAdp.value ? { appKey: form.appKey, tcSecretAppId: form.tcSecretAppId, tcSecretId: form.tcSecretId, tcSecretKey: form.tcSecretKey } : {}),
        vendor: form.vendor,
        serviceVendor: form.serviceVendor,
        agentId: form.agentId,
        ...(form.privateUrl.trim() ? { privateUrl: form.privateUrl.trim() } : {}),
        isDefault: form.isDefault,
      })
      setToast('ADP 应用已创建')
    }
    modal.value = null
    await loadData()
  } catch (error) {
    setToast(errorMessage(error, adpAppForm.value.id ? 'ADP 应用更新失败' : 'ADP 应用创建失败'))
  } finally {
    createActionLoading.value = false
  }
}
const setDefaultAdpApp = async (app: AdpApp) => {
  adpAppActionId.value = app.id
  try {
    await updateAdpApp(app.id, { isDefault: true })
    setToast(`已将「${app.name}」设为默认 ADP 应用`)
    await loadData()
  } catch (error) {
    setToast(errorMessage(error, '设置默认失败'))
  } finally {
    adpAppActionId.value = null
  }
}
const toggleAdpAppStatus = async (app: AdpApp) => {
  adpAppActionId.value = app.id
  try {
    await updateAdpApp(app.id, { status: app.status === 'active' ? 'disabled' : 'active' })
    setToast(app.status === 'active' ? 'ADP 应用已停用' : 'ADP 应用已启用')
    await loadData()
  } catch (error) {
    setToast(errorMessage(error, '状态更新失败'))
  } finally {
    adpAppActionId.value = null
  }
}
const removeAdpApp = async (app: AdpApp) => {
  if (!window.confirm(`确定删除 ADP 应用「${app.name}」吗？绑定它的企业将回退到平台默认应用。`)) return
  adpAppActionId.value = app.id
  try {
    await deleteAdpApp(app.id)
    setToast('ADP 应用已删除')
    await loadData()
  } catch (error) {
    setToast(errorMessage(error, '删除失败'))
  } finally {
    adpAppActionId.value = null
  }
}

const openConfigEditor = () => {
  const source = draftConfig.value?.payload || publishedConfig.value?.payload
  if (!source) return
  configForm.value = {
    itemsText: source.items.join('\n'),
    portal: source.featureFlags.portal,
    m3ReadOnly: source.featureFlags.m3ReadOnly,
    audit: source.featureFlags.audit,
    webChannel: source.featureFlags.webChannel,
    notes: source.notes,
  }
  modal.value = 'config'
}

const buildConfigPayload = (): PlatformConfigPayload => ({
  items: configForm.value.itemsText.split('\n').map((item) => item.trim()).filter(Boolean),
  featureFlags: {
    portal: configForm.value.portal,
    m3ReadOnly: configForm.value.m3ReadOnly,
    audit: configForm.value.audit,
    webChannel: configForm.value.webChannel,
  },
  notes: configForm.value.notes.trim(),
})

const submitConfigDraft = async () => {
  configActionLoading.value = true
  try {
    configState.value = await saveAdminConfigDraft(buildConfigPayload())
    modal.value = null
    setToast(`配置草稿 v${configState.value.draft?.version || ''} 已保存`)
  } catch (error) {
    setToast(errorMessage(error, '配置草稿保存失败'))
  } finally {
    configActionLoading.value = false
  }
}

const publishConfig = async () => {
  if (!draftConfig.value) return
  if (!window.confirm(`确定发布配置 v${draftConfig.value.version} 吗？发布后将立即成为平台当前配置。`)) return
  configActionLoading.value = true
  try {
    configState.value = await publishAdminConfig()
    await loadData()
    setToast('配置已发布')
  } catch (error) {
    setToast(errorMessage(error, '配置发布失败'))
  } finally {
    configActionLoading.value = false
  }
}

const rollbackConfig = async (version: number) => {
  if (!window.confirm(`确定回滚到配置 v${version} 吗？当前发布版本会保留在历史记录中。`)) return
  configActionLoading.value = true
  try {
    configState.value = await rollbackAdminConfig(version)
    await loadData()
    setToast(`已回滚到配置 v${version}`)
  } catch (error) {
    setToast(errorMessage(error, '配置回滚失败'))
  } finally {
    configActionLoading.value = false
  }
}

const submitEnterprise = async () => {
  createActionLoading.value = true
  try {
    const form = enterpriseForm.value
    if (form.id) {
      await updateEnterprise(form.id, {
        name: form.name,
        unifiedSocialCreditCode: form.unifiedSocialCreditCode,
        contactPerson: form.contactPerson,
        contactPhone: form.contactPhone,
        adpAppId: form.adpAppId,
      })
      setToast('企业已更新')
    } else {
      await createEnterprise({
        name: form.name,
        customerCode: form.customerCode,
        unifiedSocialCreditCode: form.unifiedSocialCreditCode,
        contactPerson: form.contactPerson,
        contactPhone: form.contactPhone,
        adpAppId: form.adpAppId || undefined,
      })
      setToast('企业已创建')
    }
    modal.value = null
    await loadData()
  } catch (error) {
    setToast(errorMessage(error, enterpriseForm.value.id ? '企业更新失败' : '企业创建失败'))
  } finally {
    createActionLoading.value = false
  }
}

const submitUser = async () => {
  createActionLoading.value = true
  try {
    const response = await createPlatformUser(userForm.value)
    modal.value = null
    if (response.user?.id) revealedPasswords.value = { ...revealedPasswords.value, [response.user.id]: response.initialPassword }
    secretMessage.value = `初始密码（仅显示一次）：${response.initialPassword}`
    setToast('平台用户已创建')
    await loadData()
  } catch (error) {
    setToast(errorMessage(error, '用户创建失败'))
  } finally {
    createActionLoading.value = false
  }
}

const openAccessEditor = (user: AdminUser) => {
  if (platformStore.user?.id === user.id) {
    setToast('不能修改当前登录账号的角色或所属企业')
    return
  }
  accessUser.value = user
  accessRole.value = user.role
  accessEnterpriseId.value = user.enterprises[0]?.id || ''
  accessFormError.value = ''
  modal.value = 'access'
}

const submitAccess = async () => {
  if (!accessUser.value) return
  if (platformStore.user?.id === accessUser.value.id) {
    accessFormError.value = '不能修改当前登录账号的角色或所属企业'
    return
  }
  if (!accessEnterpriseId.value) {
    accessFormError.value = '请为该用户选择所属企业。'
    return
  }
  const selected = enterprises.value.find((enterprise) => enterprise.id === accessEnterpriseId.value)
  if (selected && selected.status === 'suspended') {
    accessFormError.value = '不能绑定已停用企业。'
    return
  }
  accessActionLoading.value = true
  accessFormError.value = ''
  try {
    const response = await updatePlatformUserAccess(accessUser.value.id, {
      role: accessRole.value,
      enterpriseId: accessEnterpriseId.value,
    })
    const index = users.value.findIndex((item) => item.id === response.user.id)
    if (index >= 0) users.value.splice(index, 1, response.user)
    modal.value = null
    accessUser.value = null
    setToast('角色与企业范围已更新，旧执行上下文已撤销')
  } catch (error) {
    accessFormError.value = errorMessage(error, '访问范围更新失败，请稍后重试。')
  } finally {
    accessActionLoading.value = false
  }
}

const resetPassword = async (user: AdminUser) => {
  if (!window.confirm(`确定重置 ${user.name} 的登录口令吗？旧会话会立即失效。`)) return
  userActionLoading.value = user.id
  try {
    const response = await resetPlatformUserPassword(user.id)
    revealedPasswords.value = { ...revealedPasswords.value, [user.id]: response.initialPassword }
    passwordVisible.value = { ...passwordVisible.value, [user.id]: true }
    secretMessage.value = `${user.name} 的新初始密码（仅显示一次）：${response.initialPassword}`
    setToast('口令已重置，旧会话已撤销')
    await loadData()
  } catch (error) {
    setToast(errorMessage(error, '口令重置失败'))
  } finally {
    userActionLoading.value = null
  }
}

const disableUser = async (user: AdminUser) => {
  if (!window.confirm(`确定停用 ${user.name} 的账号吗？停用后将无法登录。`)) return
  userActionLoading.value = user.id
  try {
    await disablePlatformUser(user.id)
    setToast('账号已停用，旧会话已撤销')
    await loadData()
  } catch (error) {
    setToast(errorMessage(error, '账号停用失败'))
  } finally {
    userActionLoading.value = null
  }
}

const showEnterpriseDetail = (item: AdminEnterprise) => { detail.value = { title: item.name, lines: [`M3 客户编码：${item.customerCode}`, `社会统一识别码：${item.unifiedSocialCreditCode || '—'}`, `企业联系人：${item.contactPerson || '—'}`, `联系电话：${item.contactPhone || '—'}`, `ADP 应用：${adpAppName(item.adpAppId)}`, `状态：${item.status === 'active' ? '正常' : '已停用'}`] } }
const enterpriseSummary = (item: AdminUser) => item.enterprises[0]?.name || '未绑定企业'
const showUserDetail = (item: AdminUser) => { detail.value = { title: item.name, lines: [`手机号：${item.phone}`, `角色：${item.roleLabel}`, `所属企业：${enterpriseSummary(item)}`, `状态：${userStatusLabel(item.status)}`] } }
const showAuditDetail = (item: AdminAuditEvent) => { detail.value = { title: item.action, lines: [`Trace ID：${item.traceId}`, `目标：${item.targetType} / ${item.targetId || '—'}`, `结果：${item.outcome}`, `时间：${item.createdAt}`] } }

const conversationPageInfo = computed(() => {
  const start = conversationTotal.value === 0 ? 0 : conversationOffset.value + 1
  const end = Math.min(conversationOffset.value + conversations.value.length, conversationTotal.value)
  return { start, end }
})
const changeConversationPage = async (direction: -1 | 1) => {
  const next = conversationOffset.value + direction * CONVERSATION_PAGE
  if (next < 0 || next >= conversationTotal.value) return
  conversationOffset.value = next
  await loadData()
}
const openConversationDetail = async (item: AdminConversationSummary) => {
  conversationDetailLoading.value = true
  conversationDetail.value = null
  try {
    conversationDetail.value = await getAdminConversation(item.id)
  } catch (error) {
    setToast(errorMessage(error, '无法加载会话详情'))
  } finally {
    conversationDetailLoading.value = false
  }
}

const handleLogout = () => logout(() => router.replace({ name: 'login' }))
</script>

<template>
  <PlatformShell mode="admin" :title="pageTitle" @logout="handleLogout">
    <div v-if="toast" class="toast"><CheckCircleIcon />{{ toast }}</div>
    <div v-if="loadError" class="inline-alert"><ErrorCircleIcon />{{ loadError }}<button type="button" @click="refresh"><RefreshIcon />重试</button></div>
    <div v-if="!platformStore.canManage" class="permission-empty"><LockOnIcon /><strong>当前账号没有后台管理权限</strong><p>请联系平台管理员申请 `platform.manage` 权限。</p></div>
    <template v-else-if="view === 'overview'">
      <section class="admin-intro"><div><p class="eyebrow">运营控制台 / 运行状态</p><h1>平台运行概览</h1><p>掌握企业、身份、渠道与业务工具的可用状态。权限变更和配置发布都会留下审计记录。</p></div><button class="subtle-button" :disabled="loading" @click="refresh"><RefreshIcon />{{ loading ? '刷新中…' : '刷新数据' }}</button></section>
      <div v-if="loading && !overview" class="resource-loading">正在加载平台数据…</div>
      <template v-else-if="overview">
        <section class="admin-metric-grid"><article v-for="metric in overview.metrics" :key="metric.label" class="admin-metric" :class="`metric-${metric.tone}`"><span>{{ metric.label }}</span><strong>{{ metric.value || '—' }}</strong><small>{{ metric.note || '尚未接入' }}</small></article></section>
        <section class="admin-columns"><article class="admin-panel config-panel"><div class="admin-panel-heading"><div><p class="section-kicker">发布状态</p><h2>当前配置</h2></div><span class="published-badge"><span></span>已发布</span></div><div class="config-version"><strong>{{ publishedConfig ? `v${publishedConfig.version}` : overview.config.version || '—' }}</strong><span>当前发布版本</span><small>{{ publishedConfig?.updatedAt || overview.config.updatedAt || '—' }}</small></div><div class="config-items"><span v-for="item in (publishedConfig?.payload.items || overview.config.items)" :key="item"><CheckCircleIcon />{{ item }}</span><span v-if="!(publishedConfig?.payload.items || overview.config.items).length">暂无配置能力</span></div><div class="config-actions"><button class="outline-action" :disabled="configActionLoading" @click="openConfigEditor">编辑草稿</button><button class="primary-action" :disabled="configActionLoading || !draftConfig || draftConfig.validationErrors.length > 0" @click="publishConfig">{{ configActionLoading ? '处理中…' : '发布配置' }}<ChevronRightIcon /></button></div><div v-if="draftConfig" class="draft-summary"><span class="draft-dot"></span><strong>待发布草稿 v{{ draftConfig.version }}</strong><small>已保存 {{ draftConfig.updatedAt || draftConfig.createdAt || '—' }}</small></div><div v-if="draftConfig?.validationErrors.length" class="config-errors"><ErrorCircleIcon /><div><strong>草稿存在校验错误</strong><span v-for="error in draftConfig.validationErrors" :key="error">{{ error }}</span></div></div><div v-if="configHistory.length > 1" class="config-history"><div class="config-history-heading"><strong>历史版本</strong><small>发布记录保留，可按版本回滚</small></div><template v-for="item in configHistory" :key="item.version"><div v-if="item.version !== publishedConfig?.version && item.status !== 'draft'" class="config-history-row"><span><strong>v{{ item.version }}</strong><small>{{ item.status === 'rolled_back' ? '已回滚' : '已发布' }} · {{ item.updatedAt || item.createdAt || '—' }}</small></span><button class="text-action" :disabled="configActionLoading" @click="rollbackConfig(item.version)">回滚</button></div></template></div></article><article class="admin-panel activity-panel"><div class="admin-panel-heading"><div><p class="section-kicker">最近操作</p><h2>审计活动</h2></div><RouterLink to="/admin/audit">查看全部<ChevronRightIcon /></RouterLink></div><div v-if="overview.activities.length" class="activity-list"><div v-for="activity in overview.activities" :key="activity.action + activity.at" class="activity-row"><span class="activity-mark" :class="`tone-${activity.tone}`"><CheckCircleIcon v-if="activity.tone === 'success'" /><ErrorCircleIcon v-else-if="activity.tone === 'warning'" /><HistoryIcon v-else /></span><span class="activity-main"><strong>{{ activity.action }}</strong><small>{{ activity.actor }} · {{ activity.target }}</small></span><time>{{ activity.at }}</time></div></div><div v-else class="panel-empty">暂无审计活动</div></article></section>
        <section class="guardrail-strip"><span class="guardrail-icon"><LockOnIcon /></span><div><strong>业务数据权限独立于平台管理员角色</strong><p>管理员可以管理账号和配置，但不会因为进入后台而自动获得客户 M3 业务数据。</p></div><RouterLink to="/admin/agents-tools">查看权限模型<ChevronRightIcon /></RouterLink></section>
      </template>
    </template>
    <template v-else-if="view === 'enterprises'">
      <section class="admin-intro"><div><p class="eyebrow">运营控制台 / {{ resourceMeta?.eyebrow }}</p><h1>{{ resourceMeta?.title }}</h1><p>{{ resourceMeta?.description }}</p></div><div class="resource-actions"><button class="subtle-button" :disabled="loading" @click="refresh"><RefreshIcon />刷新</button><button class="primary-action" @click="openCreate('enterprise')"><UsergroupIcon />新增企业</button></div></section>
      <section class="resource-panel admin-panel enterprises-panel"><div class="resource-toolbar"><div class="resource-search"><SearchIcon /><input v-model="enterpriseSearch" placeholder="搜索企业名称或客户编码" /></div><span class="resource-count">{{ filteredEnterprises.length }} 家企业</span></div><div v-if="loading && !enterprises.length" class="resource-loading">正在加载企业目录…</div><div v-else-if="!filteredEnterprises.length" class="panel-empty">暂无企业记录</div><div v-else class="resource-table"><div class="resource-table-head"><span>企业</span><span>客户编码 / 社会统一识别码</span><span>状态</span><span>操作</span></div><div v-for="item in filteredEnterprises" :key="item.id" class="resource-row"><span class="resource-name"><UsergroupIcon /><strong>{{ item.name }}</strong></span><span class="resource-detail user-scope"><strong>{{ item.customerCode }}</strong><small>{{ item.unifiedSocialCreditCode || '未填写识别码' }}</small></span><span class="row-status" :class="`row-status--${item.status === 'active' ? 'success' : 'warning'}`"><i></i>{{ item.status === 'active' ? '正常' : '已停用' }}</span><span class="row-actions"><button class="text-action" @click="openEditEnterprise(item)">编辑</button><button class="row-more" aria-label="查看企业详情" @click="showEnterpriseDetail(item)"><ChevronRightIcon /></button></span></div></div></section>
    </template>
    <template v-else-if="view === 'users'">
      <section class="admin-intro"><div><p class="eyebrow">运营控制台 / {{ resourceMeta?.eyebrow }}</p><h1>{{ resourceMeta?.title }}</h1><p>{{ resourceMeta?.description }}</p></div><div class="resource-actions"><button class="subtle-button" :disabled="loading" @click="refresh"><RefreshIcon />刷新</button><button class="primary-action" @click="openCreate('user')"><UserIcon />新增用户</button></div></section>
      <div v-if="secretMessage" class="secret-alert"><LockOnIcon /><span>{{ secretMessage }}</span><button type="button" aria-label="关闭" @click="secretMessage = ''">×</button></div>
      <section class="resource-panel admin-panel users-panel"><div class="resource-toolbar"><div class="resource-search"><SearchIcon /><input v-model="userSearch" placeholder="搜索用户姓名、手机号、角色或企业" /></div><div class="toolbar-filter"><PlatformSelect v-model="userEnterpriseFilter" :options="enterpriseFilterOptions" placeholder="全部企业" aria-label="按企业筛选" /></div><span class="resource-count">{{ filteredUsers.length }} 位用户</span></div><div v-if="loading && !users.length" class="resource-loading">正在加载平台用户…</div><div v-else-if="!filteredUsers.length" class="panel-empty">暂无用户记录</div><div v-else class="resource-table"><div class="resource-table-head"><span>用户</span><span>角色与所属企业</span><span>状态</span><span>登录口令</span><span>操作</span></div><div v-for="item in filteredUsers" :key="item.id" class="resource-row user-row"><span class="resource-name"><UserIcon /><strong>{{ item.name }}<small>{{ item.phone }}</small></strong></span><span class="resource-detail user-scope"><strong>{{ item.roleLabel }}</strong><small>{{ enterpriseSummary(item) }}</small></span><span class="row-status" :class="`row-status--${item.status === 'active' ? 'success' : 'warning'}`"><i></i>{{ userStatusLabel(item.status) }}</span><span class="row-secret"><template v-if="revealedPasswords[item.id]"><code class="secret-code">{{ passwordVisible[item.id] ? revealedPasswords[item.id] : '••••••' }}</code><button type="button" class="secret-eye" :aria-label="passwordVisible[item.id] ? '隐藏登录口令' : '显示登录口令'" @click="togglePassword(item.id)"><BrowseOffIcon v-if="passwordVisible[item.id]" /><BrowseIcon v-else /></button></template><span v-else class="secret-none" title="登录口令仅以哈希存储、不可查看；如需请点「重置」生成新的一次性口令">——</span></span><span class="row-actions"><button class="row-more" aria-label="查看用户详情" @click="showUserDetail(item)"><ChevronRightIcon /></button><button class="text-action" :disabled="item.status !== 'active' || platformStore.user?.id === item.id || userActionLoading === item.id" @click="openAccessEditor(item)">调整</button><button class="text-action" :disabled="item.status !== 'active' || userActionLoading === item.id" @click="resetPassword(item)">{{ userActionLoading === item.id ? '处理中…' : '重置' }}</button><button class="text-action text-action--danger" :disabled="item.status !== 'active' || userActionLoading === item.id" @click="disableUser(item)">{{ userActionLoading === item.id ? '处理中…' : '停用' }}</button></span></div></div></section>
    </template>
    <template v-else-if="view === 'conversations'">
      <section class="admin-intro"><div><p class="eyebrow">运营控制台 / {{ resourceMeta?.eyebrow }}</p><h1>{{ resourceMeta?.title }}</h1><p>{{ resourceMeta?.description }}</p></div><button class="subtle-button" :disabled="loading" @click="refresh"><RefreshIcon />刷新</button></section>
      <section class="resource-panel admin-panel conversations-panel"><div class="resource-toolbar"><div class="resource-search"><SearchIcon /><input v-model="conversationSearch" placeholder="搜索标题、企业、账号或渠道" /></div><span class="resource-count">{{ conversationPageInfo.start }}–{{ conversationPageInfo.end }} / 共 {{ conversationTotal }} 条</span><span class="pager"><button class="text-action" :disabled="loading || conversationOffset === 0" @click="changeConversationPage(-1)">上一页</button><button class="text-action" :disabled="loading || conversationPageInfo.end >= conversationTotal" @click="changeConversationPage(1)">下一页</button></span></div><div v-if="loading && !conversations.length" class="resource-loading">正在加载历史对话…</div><div v-else-if="!filteredConversations.length" class="panel-empty">暂无对话记录</div><div v-else class="resource-table"><div class="resource-table-head"><span>对话</span><span>企业 / 账号</span><span>更新时间</span><span>操作</span></div><div v-for="item in filteredConversations" :key="item.id" class="resource-row"><span class="resource-name"><HistoryIcon /><strong>{{ item.title }}<small>{{ item.channel }}{{ item.query ? ' · ' + item.query : '' }}</small></strong></span><span class="resource-detail user-scope"><strong>{{ item.enterpriseName || '—' }}</strong><small>{{ item.accountName || '—' }}</small></span><span class="resource-detail">{{ item.updatedAt ? new Date(item.updatedAt).toLocaleString('zh-CN', { hour12: false }) : '—' }}</span><span class="row-actions"><button class="text-action" @click="openConversationDetail(item)">查看</button></span></div></div></section>
    </template>
    <template v-else-if="view === 'audit'">
      <section class="admin-intro"><div><p class="eyebrow">运营控制台 / {{ resourceMeta?.eyebrow }}</p><h1>{{ resourceMeta?.title }}</h1><p>{{ resourceMeta?.description }}</p></div><button class="subtle-button" :disabled="loading" @click="refresh"><RefreshIcon />刷新</button></section>
      <section class="resource-panel admin-panel"><div class="resource-toolbar"><div class="resource-search"><SearchIcon /><input v-model="auditSearch" placeholder="搜索动作、目标或 Trace ID" /></div><span class="resource-count">{{ filteredAudit.length }} 条记录</span></div><div v-if="loading && !auditEvents.length" class="resource-loading">正在加载审计记录…</div><div v-else-if="!filteredAudit.length" class="panel-empty">暂无审计记录</div><div v-else class="resource-table"><div class="resource-table-head"><span>动作</span><span>目标</span><span>结果</span><span></span></div><div v-for="item in filteredAudit" :key="item.id" class="resource-row"><span class="resource-name"><HistoryIcon /><strong>{{ item.action }}</strong></span><span class="resource-detail">{{ item.targetType }} / {{ item.targetId || '—' }}</span><span class="row-status" :class="`row-status--${item.outcome === 'success' || item.outcome === 'found' ? 'success' : 'warning'}`"><i></i>{{ item.outcome }}</span><button class="row-more" aria-label="查看审计详情" @click="showAuditDetail(item)"><ChevronRightIcon /></button></div></div></section>
    </template>
    <template v-else-if="view === 'open-api'"><AdminAdpApiKeys /></template>
    <template v-else-if="view === 'bindings'">
      <section class="admin-intro"><div><p class="eyebrow">运营控制台 / {{ resourceMeta?.eyebrow }}</p><h1>{{ resourceMeta?.title }}</h1><p>{{ resourceMeta?.description }}</p></div><div class="resource-actions"><button class="subtle-button" :disabled="loading" @click="refresh"><RefreshIcon />刷新</button><button class="primary-action" @click="openCreateAdpApp"><ApiIcon />新增 ADP 应用</button></div></section>
      <section class="resource-panel admin-panel adp-apps-panel"><div class="resource-toolbar"><div class="toolbar-heading"><p class="section-kicker">应用注册表</p><strong class="toolbar-title">ADP 应用</strong></div><span class="resource-count">{{ adpApps.length }} 个应用</span></div><div v-if="loading && !adpApps.length" class="resource-loading">正在加载 ADP 应用…</div><div v-else-if="adpApps.length" class="resource-table"><div class="resource-table-head"><span>应用</span><span>Provider / AgentId</span><span>状态</span><span>操作</span></div><div v-for="app in adpApps" :key="app.id" class="resource-row"><span class="resource-name"><ApiIcon /><strong>{{ app.name }}<small>{{ app.applicationId }}</small></strong></span><span class="resource-detail user-scope"><strong>{{ app.providerType }} · {{ app.vendor }}</strong><small>{{ app.agentId }} · schema v{{ app.providerSchemaVersion }}</small></span><span class="row-status" :class="`row-status--${app.status === 'active' ? 'success' : 'warning'}`"><i></i>{{ app.status === 'active' ? '启用' : '停用' }}<em v-if="app.isDefault" class="default-badge">默认</em></span><span class="row-actions"><button class="text-action" :disabled="adpAppActionId === app.id || app.isDefault || app.status !== 'active'" @click="setDefaultAdpApp(app)">设为默认</button><button class="text-action" :disabled="adpAppActionId === app.id" @click="openEditAdpApp(app)">编辑</button><button class="text-action" :disabled="adpAppActionId === app.id" @click="toggleAdpAppStatus(app)">{{ app.status === 'active' ? '停用' : '启用' }}</button><button class="text-action text-action--danger" :disabled="adpAppActionId === app.id" @click="removeAdpApp(app)">删除</button></span></div></div></section>
      <p class="adp-config-note">请先新增应用并设为平台默认，或在企业管理中绑定应用。业务调用不再回退到服务器默认配置。</p>
    </template>
    <template v-else-if="view === 'channels'">
      <AdminChannelManagement />
    </template>
    <template v-else>
      <section class="admin-intro"><div><p class="eyebrow">运营控制台 / {{ resourceMeta?.eyebrow }}</p><h1>{{ resourceMeta?.title }}</h1><p>{{ resourceMeta?.description }}</p></div><button class="subtle-button" :disabled="loading" @click="refresh"><RefreshIcon />刷新</button></section>
      <section class="unavailable-panel admin-panel"><component :is="resourceMeta?.icon" /><strong>尚未接入</strong><p>该资源的服务端目录接口尚未提供，因此这里不会展示演示数据或提供无效操作。</p></section>
    </template>

    <div v-if="modal" class="modal-backdrop" @click.self="!createActionLoading && !accessActionLoading && !configActionLoading ? modal = null : undefined">
      <form v-if="modal === 'enterprise'" class="modal-card" @submit.prevent="submitEnterprise"><div class="modal-heading"><div><p class="section-kicker">客户目录</p><h2>{{ enterpriseForm.id ? '编辑企业' : '新增企业' }}</h2></div><button type="button" class="modal-close" aria-label="关闭" :disabled="createActionLoading" @click="modal = null">×</button></div><label>企业名称<input v-model="enterpriseForm.name" required maxlength="255" /></label><label>M3 客户编码<input v-model="enterpriseForm.customerCode" :required="!enterpriseForm.id" :disabled="!!enterpriseForm.id" pattern="[A-Za-z0-9][A-Za-z0-9._\-]{1,127}" /><small v-if="enterpriseForm.id" class="field-hint">客户编码创建后不可修改</small></label><label>社会统一识别码<input v-model="enterpriseForm.unifiedSocialCreditCode" required minlength="18" maxlength="18" placeholder="18 位统一社会信用代码" /></label><label>企业联系人（选填）<input v-model="enterpriseForm.contactPerson" maxlength="128" /></label><label>联系电话（选填）<input v-model="enterpriseForm.contactPhone" maxlength="32" /></label><label>ADP 应用<PlatformSelect v-model="enterpriseForm.adpAppId" :options="adpAppSelectOptions" placeholder="平台默认" aria-label="ADP 应用" /><small class="field-hint">留空则使用平台默认 ADP 应用</small></label><div class="modal-actions"><button type="button" class="outline-action" :disabled="createActionLoading" @click="modal = null">取消</button><button type="submit" class="primary-action" :disabled="createActionLoading">{{ createActionLoading ? '保存中…' : (enterpriseForm.id ? '保存' : '创建企业') }}</button></div></form>
      <form v-else-if="modal === 'user'" class="modal-card" @submit.prevent="submitUser"><div class="modal-heading"><div><p class="section-kicker">身份治理</p><h2>新增平台用户</h2></div><button type="button" class="modal-close" aria-label="关闭" :disabled="createActionLoading" @click="modal = null">×</button></div><label>姓名<input v-model="userForm.name" required maxlength="255" /></label><label>手机号<input v-model="userForm.phone" required inputmode="numeric" pattern="1[0-9]{10}" /></label><label>角色<PlatformSelect :model-value="userForm.role" :options="roleSelectOptions" aria-label="角色" @update:model-value="userForm.role = $event as PlatformRole" /></label><label>所属企业<PlatformSelect v-model="userForm.enterpriseId" :options="enterpriseSelectOptions" placeholder="请选择企业" aria-label="所属企业" /><small class="field-hint">每个平台用户关联一个企业</small></label><div class="modal-actions"><button type="button" class="outline-action" :disabled="createActionLoading" @click="modal = null">取消</button><button type="submit" class="primary-action" :disabled="createActionLoading">{{ createActionLoading ? '创建中…' : '创建用户' }}</button></div></form>
      <form v-else-if="modal === 'access'" class="modal-card access-editor-card" @submit.prevent="submitAccess"><div class="modal-heading"><div><p class="section-kicker">身份治理</p><h2>调整角色与企业</h2></div><button type="button" class="modal-close" aria-label="关闭" :disabled="accessActionLoading" @click="modal = null">×</button></div><div v-if="accessUser" class="access-user-summary"><UserIcon /><div><strong>{{ accessUser.name }}</strong><small>{{ accessUser.phone }} · 当前所属：{{ enterpriseSummary(accessUser) }}</small></div></div><p class="modal-help">每个平台用户只关联一个企业。角色与所属企业保存后立即生效，该用户已有的执行上下文会被撤销。</p><label>角色<PlatformSelect :model-value="accessRole" :options="roleSelectOptions" :disabled="accessActionLoading" aria-label="角色" @update:model-value="accessRole = $event as PlatformRole" /></label><label>所属企业<PlatformSelect v-model="accessEnterpriseId" :options="enterpriseSelectOptions" :disabled="accessActionLoading" placeholder="请选择企业" aria-label="所属企业" /></label><div v-if="accessFormError" class="form-error" role="alert"><ErrorCircleIcon /><span>{{ accessFormError }}</span></div><div class="modal-actions"><button type="button" class="outline-action" :disabled="accessActionLoading" @click="modal = null">取消</button><button type="submit" class="primary-action" :disabled="accessActionLoading">{{ accessActionLoading ? '保存中…' : '保存' }}</button></div></form>
      <form v-else-if="modal === 'config'" class="modal-card config-editor-card" @submit.prevent="submitConfigDraft"><div class="modal-heading"><div><p class="section-kicker">平台配置</p><h2>编辑配置草稿</h2></div><button type="button" class="modal-close" aria-label="关闭" @click="modal = null">×</button></div><p class="modal-help">每行一项能力。保存后生成草稿，发布前仍可继续修改。</p><label>能力清单<textarea v-model="configForm.itemsText" required maxlength="1800" rows="7" placeholder="例如：客户登录与会话&#10;M3 只读工具"></textarea></label><fieldset class="flag-fieldset"><legend>功能开关</legend><label class="checkbox-row"><input v-model="configForm.portal" type="checkbox" /><span>客户门户</span></label><label class="checkbox-row"><input v-model="configForm.m3ReadOnly" type="checkbox" /><span>M3 只读工具</span></label><label class="checkbox-row"><input v-model="configForm.audit" type="checkbox" /><span>审计记录</span></label><label class="checkbox-row"><input v-model="configForm.webChannel" type="checkbox" /><span>官网渠道</span></label></fieldset><label>变更说明<textarea v-model="configForm.notes" maxlength="500" rows="3" placeholder="可选，说明本次配置变更原因"></textarea></label><div class="modal-actions"><button type="button" class="outline-action" :disabled="configActionLoading" @click="modal = null">取消</button><button type="submit" class="primary-action" :disabled="configActionLoading">{{ configActionLoading ? '保存中…' : '保存草稿' }}</button></div></form>
      <form v-else-if="modal === 'adpApp'" class="modal-card modal-card--wide" @submit.prevent="submitAdpApp">
        <div class="modal-heading"><div><p class="section-kicker">应用注册表</p><h2>{{ adpAppForm.id ? '编辑 ADP 应用' : '新增 ADP 应用' }}</h2></div><button type="button" class="modal-close" aria-label="关闭" :disabled="createActionLoading" @click="modal = null">×</button></div>
        <div class="modal-columns">
          <section class="modal-section">
            <h3 class="modal-section-title">应用基础信息</h3>
            <div class="modal-section-fields">
              <label>应用名称<input v-model="adpAppForm.name" required maxlength="128" /></label>
              <label>ApplicationId<input v-model="adpAppForm.applicationId" :required="!adpAppForm.id" :disabled="!!adpAppForm.id" pattern="[A-Za-z0-9][A-Za-z0-9._\-]{1,63}" /><small v-if="adpAppForm.id" class="field-hint">ApplicationId 创建后不可修改</small></label>
              <label>Provider 类型<select v-model="adpAppForm.providerType"><option v-for="option in adpProviderOptions" :key="option.value" :value="option.value">{{ option.label }}</option></select></label>
              <small v-if="selectedProvider && !selectedProvider.registered" class="provider-warning">该 Provider 已完成配置契约，但尚未注册执行适配器；保存后业务调用会安全拒绝。</small>
              <label>Provider Schema 版本<input v-model.number="adpAppForm.providerSchemaVersion" type="number" min="1" max="100" required /></label>
              <label>Vendor<input v-model="adpAppForm.vendor" maxlength="32" placeholder="Tencent" /></label>
              <label>ServiceVendor<input v-model="adpAppForm.serviceVendor" maxlength="32" placeholder="ChinaTencentCloud" /></label>
              <label>AgentId<input v-model="adpAppForm.agentId" maxlength="128" placeholder="platform-default" /></label>
              <label>PrivateUrl（选填）<input v-model="adpAppForm.privateUrl" maxlength="512" /></label>
              <label class="checkbox-row"><input v-model="adpAppForm.isDefault" type="checkbox" /><span>设为平台默认应用</span></label>
            </div>
          </section>
          <section class="modal-section">
            <h3 class="modal-section-title">Provider 配置</h3>
            <label>非敏感 Provider Settings（JSON）<textarea v-model="adpAppForm.providerSettingsText" rows="5" spellcheck="false" placeholder="{}"></textarea><small class="field-hint">只放端点、区域等非敏感配置；密钥必须放在下方 credentials。</small></label>
            <template v-if="isTencentAdp">
              <div class="modal-notice"><LockOnIcon /><span>腾讯兼容字段会加密保存，编辑时留空表示不修改。</span></div>
              <div class="modal-section-fields"><label>AppKey<input v-model="adpAppForm.appKey" :required="!adpAppForm.id" type="password" autocomplete="new-password" :placeholder="adpAppForm.id ? '留空则不修改' : ''" /></label><label>TC_SECRET_APPID<input v-model="adpAppForm.tcSecretAppId" :required="!adpAppForm.id" :placeholder="adpAppForm.id ? '留空则不修改' : ''" /></label><label>TC_SECRET_ID<input v-model="adpAppForm.tcSecretId" :required="!adpAppForm.id" type="password" autocomplete="new-password" :placeholder="adpAppForm.id ? '留空则不修改' : ''" /></label><label>TC_SECRET_KEY<input v-model="adpAppForm.tcSecretKey" :required="!adpAppForm.id" type="password" autocomplete="new-password" :placeholder="adpAppForm.id ? '留空则不修改' : ''" /></label></div>
            </template>
            <template v-else>
              <div class="modal-notice"><LockOnIcon /><span>通用 credentials 使用 JSON 提交，服务端加密保存且永不回显。</span></div>
              <label>Credentials（JSON）<textarea v-model="adpAppForm.credentialsText" :required="!adpAppForm.id" rows="8" spellcheck="false" placeholder='{"accessKeyId":"…","accessKeySecret":"…"}'></textarea><small class="field-hint">仅填写当前 Provider 的凭据键；编辑已有应用时留空表示保留原凭据。</small></label>
            </template>
          </section>
        </div>
        <div class="modal-actions"><button type="button" class="outline-action" :disabled="createActionLoading" @click="modal = null">取消</button><button type="submit" class="primary-action" :disabled="createActionLoading">{{ createActionLoading ? '保存中…' : (adpAppForm.id ? '保存' : '创建应用') }}</button></div>
      </form>
    </div>
    <div v-if="detail" class="modal-backdrop" @click.self="detail = null"><section class="modal-card detail-card"><div class="modal-heading"><div><p class="section-kicker">详情</p><h2>{{ detail.title }}</h2></div><button type="button" class="modal-close" aria-label="关闭" @click="detail = null">×</button></div><p v-for="line in detail.lines" :key="line" class="detail-line">{{ line }}</p><div class="modal-actions"><button type="button" class="primary-action" @click="detail = null">完成</button></div></section></div>
    <div v-if="conversationDetailLoading || conversationDetail" class="modal-backdrop" @click.self="conversationDetail = null; conversationDetailLoading = false"><section class="modal-card conversation-detail-card"><div class="modal-heading"><div><p class="section-kicker">历史对话</p><h2>{{ conversationDetail?.conversation.title || '会话详情' }}</h2></div><button type="button" class="modal-close" aria-label="关闭" @click="conversationDetail = null; conversationDetailLoading = false">×</button></div><div v-if="conversationDetailLoading" class="resource-loading">正在加载会话详情…</div><template v-else-if="conversationDetail"><p class="conversation-meta">{{ conversationDetail.conversation.enterpriseName || '—' }} · {{ conversationDetail.conversation.accountName || '—' }} · {{ conversationDetail.conversation.channel }}</p><div class="conversation-thread"><div v-for="msg in conversationDetail.messages" :key="msg.id" class="conversation-msg" :class="`conversation-msg--${msg.direction}`"><span class="conversation-msg-role">{{ msg.direction === 'assistant' ? '助手' : '用户' }}</span><p>{{ msg.body || '（无正文）' }}</p><time>{{ msg.createdAt ? new Date(msg.createdAt).toLocaleString('zh-CN', { hour12: false }) : '' }}</time></div><div v-if="!conversationDetail.messages.length" class="panel-empty">该会话暂无消息</div></div><div v-if="conversationDetail.runs.length" class="conversation-runs"><strong>执行轮次</strong><div v-for="run in conversationDetail.runs" :key="run.runId" class="conversation-run"><span class="row-status" :class="`row-status--${run.status === 'found' || run.status === 'completed' ? 'success' : 'warning'}`"><i></i>{{ run.status }}</span><span>{{ run.title }}</span><small>{{ run.evidence.length }} 条证据</small></div></div></template><div class="modal-actions"><button type="button" class="primary-action" @click="conversationDetail = null">完成</button></div></section></div>
  </PlatformShell>
</template>

<style scoped>
.admin-intro { display: flex; justify-content: space-between; align-items: flex-end; gap: 24px; margin-bottom: 28px; }.eyebrow, .section-kicker { margin: 0 0 9px; font-size: 10px; letter-spacing: .13em; text-transform: uppercase; color: #7b8c89; font-weight: 700; }h1 { margin: 0; font-size: 31px; line-height: 1.18; color: #142322; }.admin-intro p:not(.eyebrow) { margin: 10px 0 0; color: #72827f; font-size: 13px; max-width: 650px; }.subtle-button, .primary-action, .outline-action { min-height: 38px; display: inline-flex; align-items: center; justify-content: center; gap: 7px; padding: 0 13px; border-radius: 6px; font-size: 12px; font-weight: 650; cursor: pointer; }.subtle-button { background: #fff; border: 1px solid #d8e3e0; color: #45615d; }.subtle-button:hover { border-color: #91bcb3; color: #147d72; }.subtle-button :deep(svg), .primary-action :deep(svg), .outline-action :deep(svg) { width: 16px; }.admin-metric-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 13px; margin-bottom: 23px; }.admin-metric { min-height: 126px; border: 1px solid #e0e7e5; background: #fff; padding: 17px 18px; border-top: 1px solid #cadbd6; }.admin-metric.metric-warning { border-top-color: #d7a35f; }.admin-metric.metric-success { border-top-color: #65ad91; }.admin-metric span, .admin-metric small { display: block; color: #778883; font-size: 11px; }.admin-metric strong { display: block; font-size: 29px; line-height: 1; color: #18332f; margin: 16px 0 9px; }.admin-metric small { color: #8c9b97; font-size: 10px; }.admin-columns { display: grid; grid-template-columns: .95fr 1.25fr; gap: 17px; }.admin-panel { border: 1px solid #e0e7e5; background: #fff; }.admin-panel-heading { display: flex; justify-content: space-between; align-items: flex-start; padding: 20px 20px 15px; }.admin-panel-heading h2 { margin: 0; color: #17312e; font-size: 19px; }.admin-panel-heading a { display: inline-flex; align-items: center; gap: 3px; color: #147d72; font-size: 11px; text-decoration: none; }.admin-panel-heading a :deep(svg) { width: 14px; }.published-badge { display: inline-flex; align-items: center; gap: 5px; color: #31816d; font-size: 10px; background: #e8f5ef; padding: 5px 7px; }.published-badge span { width: 6px; height: 6px; border-radius: 50%; background: #41a47d; }.config-version { margin: 0 20px; padding: 15px; display: grid; grid-template-columns: auto 1fr; column-gap: 10px; background: #f3f8f5; }.config-version strong { color: #2e655b; font-size: 23px; grid-row: span 2; align-self: center; }.config-version span, .config-version small { color: #71847e; font-size: 10px; }.config-version small { grid-column: 2; margin-top: 3px; }.config-items { display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px 8px; padding: 17px 20px; }.config-items span { display: flex; align-items: center; gap: 5px; color: #688079; font-size: 10px; }.config-items :deep(svg) { width: 14px; color: #3a9878; }.config-actions { display: flex; gap: 8px; padding: 0 20px 4px; }.outline-action { border: 1px solid #d7e3df; color: #56726b; background: #fff; }.primary-action { border: 1px solid #147d72; color: white; background: #147d72; }.primary-action:hover { background: #0e685f; }.primary-action:disabled, .outline-action:disabled { opacity: .55; cursor: not-allowed; }.activity-list { border-top: 1px solid #edf1f0; }.activity-row { display: flex; align-items: center; gap: 10px; min-height: 66px; padding: 10px 20px; border-bottom: 1px solid #edf1f0; }.activity-row:last-child { border-bottom: 0; }.activity-mark { display: grid; place-items: center; width: 27px; height: 27px; border-radius: 50%; background: #e8f5ef; color: #3d9477; }.activity-mark.tone-warning { background: #fff4e2; color: #ae7734; }.activity-mark.tone-neutral { background: #edf2f1; color: #718781; }.activity-mark :deep(svg) { width: 14px; }.activity-main { min-width: 0; flex: 1; }.activity-main strong, .activity-main small { display: block; }.activity-main strong { color: #31504a; font-size: 11px; }.activity-main small { color: #899892; font-size: 10px; margin-top: 3px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.activity-row time { color: #97a39f; font-size: 9px; white-space: nowrap; }.guardrail-strip { display: flex; align-items: center; gap: 12px; margin-top: 18px; padding: 15px 17px; border: 1px solid #dce7e3; background: #f1f7f4; }.guardrail-icon { display: grid; place-items: center; width: 31px; height: 31px; background: #dceee8; color: #367d6c; border-radius: 6px; }.guardrail-icon :deep(svg) { width: 16px; }.guardrail-strip strong, .guardrail-strip p { display: block; }.guardrail-strip strong { color: #345950; font-size: 11px; }.guardrail-strip p { color: #788c86; font-size: 10px; margin: 3px 0 0; }.guardrail-strip a { display: inline-flex; align-items: center; gap: 3px; margin-left: auto; color: #277668; text-decoration: none; font-size: 10px; white-space: nowrap; }.guardrail-strip a :deep(svg) { width: 14px; }.toast { position: fixed; top: 79px; right: 30px; display: flex; align-items: center; gap: 7px; z-index: 50; padding: 10px 13px; border: 1px solid #bfe0d2; background: #effaf5; color: #32765f; box-shadow: 0 8px 24px rgba(35,80,67,.12); font-size: 11px; }.toast :deep(svg) { width: 15px; }.inline-alert { display: flex; align-items: center; gap: 8px; margin-bottom: 18px; padding: 11px 13px; border: 1px solid #e7d7bc; background: #fff9ed; color: #876236; font-size: 12px; }.inline-alert :deep(svg) { width: 16px; }.inline-alert button { margin-left: auto; border: 0; background: transparent; color: #8f642e; display: flex; align-items: center; gap: 5px; cursor: pointer; }.inline-alert button :deep(svg) { width: 14px; }.permission-empty, .unavailable-panel { min-height: 280px; display: grid; place-items: center; align-content: center; gap: 10px; border: 1px dashed #d4e3df; color: #879792; text-align: center; }.permission-empty strong, .unavailable-panel strong { color: #35534d; font-size: 15px; }.permission-empty p, .unavailable-panel p { max-width: 420px; margin: 0; font-size: 11px; line-height: 1.6; }.permission-empty :deep(svg), .unavailable-panel :deep(svg) { width: 28px; color: #71958b; }.resource-loading { padding: 40px 20px; text-align: center; color: #7b8d87; font-size: 11px; }.secret-alert { display: flex; align-items: center; gap: 8px; margin: -9px 0 17px; padding: 11px 13px; border: 1px solid #c7e0d5; background: #eff9f4; color: #296c59; font-size: 11px; }.secret-alert :deep(svg) { width: 15px; }.secret-alert button { margin-left: auto; border: 0; background: none; color: #397766; font-size: 18px; cursor: pointer; }.users-panel { margin-top: 18px; }.resource-name strong small { display: block; margin-top: 3px; color: #8a9995; font-size: 10px; font-weight: 400; }.row-actions { display: flex; align-items: center; justify-content: flex-end; gap: 2px; }
.row-secret { display: inline-flex; align-items: center; gap: 6px; min-width: 0; }
.secret-code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; letter-spacing: .12em; color: #24433d; }
.secret-eye { display: inline-grid; place-items: center; width: 24px; height: 24px; padding: 0; border: 0; background: transparent; color: #6d8781; cursor: pointer; border-radius: 5px; }
.secret-eye:hover { color: #147d72; background: #eef6f2; }
.secret-eye :deep(svg) { width: 15px; }
.secret-none { color: #9aa8a4; font-size: 12px; cursor: default; }.text-action { border: 0; padding: 4px 5px; color: #317c70; background: transparent; font-size: 10px; cursor: pointer; }.text-action--danger { color: #a24e4e; }.text-action:disabled { color: #b8c2bf; cursor: not-allowed; }.unavailable-note { margin: 0; padding: 0 20px 17px; color: #8a9894; font-size: 10px; }.modal-backdrop { position: fixed; inset: 0; z-index: 100; display: grid; place-items: center; padding: 20px; background: rgba(20,35,34,.38); }.modal-card { width: min(440px, 100%); display: grid; gap: 13px; padding: 22px; border: 1px solid #dbe7e2; background: #fff; box-shadow: 0 18px 50px rgba(24,50,44,.2); }.modal-heading { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 4px; }.modal-heading h2 { margin: 0; color: #17312e; font-size: 20px; }.modal-card label { display: grid; gap: 6px; color: #527069; font-size: 11px; font-weight: 650; }.modal-card input, .modal-card select { min-height: 38px; border: 1px solid #d6e3df; padding: 0 10px; color: #24433d; background: #fff; font: inherit; font-size: 12px; }.modal-card input:focus, .modal-card select:focus { outline: 2px solid rgba(20,125,114,.18); border-color: #147d72; }.modal-close { border: 0; background: transparent; color: #82918d; font-size: 22px; cursor: pointer; }.modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 5px; }.detail-line { margin: 0; padding: 9px 10px; background: #f4f8f6; color: #56736b; font-size: 11px; }
.draft-summary { display: flex; align-items: center; gap: 7px; margin: 9px 20px 0; padding: 9px 10px; background: #fff9ed; border: 1px solid #f0e2c7; color: #795e3d; }.draft-summary strong { font-size: 10px; }.draft-summary small { margin-left: auto; color: #9a876d; font-size: 9px; }.draft-dot { width: 7px; height: 7px; border-radius: 50%; background: #d89d4f; }.config-errors { display: flex; gap: 8px; margin: 10px 20px 0; padding: 10px; background: #fff3f1; border: 1px solid #ebc9c3; color: #99534c; }.config-errors > :deep(svg) { flex: 0 0 auto; width: 16px; margin-top: 1px; }.config-errors strong, .config-errors span { display: block; font-size: 10px; line-height: 1.45; }.config-errors span { margin-top: 3px; color: #a86860; }.config-history { margin: 13px 20px 20px; border-top: 1px solid #edf1f0; }.config-history-heading { display: flex; justify-content: space-between; align-items: baseline; padding: 11px 0 7px; }.config-history-heading strong { color: #526b65; font-size: 10px; }.config-history-heading small { color: #9aa8a4; font-size: 9px; }.config-history-row { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 8px 0; border-top: 1px solid #f0f3f2; }.config-history-row span strong, .config-history-row span small { display: block; }.config-history-row span strong { color: #49665f; font-size: 10px; }.config-history-row span small { margin-top: 2px; color: #93a19d; font-size: 9px; }.modal-help { margin: -2px 0 2px; color: #7a8d87; font-size: 11px; line-height: 1.5; }.modal-card textarea { width: 100%; min-height: 80px; resize: vertical; border: 1px solid #d6e3df; padding: 9px 10px; color: #24433d; background: #fff; font: inherit; font-size: 12px; line-height: 1.45; }.modal-card textarea:focus { outline: 2px solid rgba(20,125,114,.18); border-color: #147d72; }.config-editor-card { width: min(520px, 100%); max-height: min(720px, calc(100vh - 40px)); overflow: auto; }.flag-fieldset { display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; margin: 0; padding: 11px 12px 12px; border: 1px solid #dbe7e2; }.flag-fieldset legend { padding: 0 4px; color: #527069; font-size: 11px; font-weight: 650; }.checkbox-row { display: flex !important; grid-template-columns: none !important; align-items: center; gap: 8px !important; color: #4e6b64 !important; font-weight: 500 !important; }.checkbox-row input { width: 15px; height: 15px; min-height: 0; margin: 0; accent-color: #147d72; }.checkbox-row span { font-size: 11px; }.config-editor-card .modal-actions { position: sticky; bottom: -22px; margin: 0 -22px -22px; padding: 13px 22px 22px; background: #fff; border-top: 1px solid #edf1f0; }
.access-editor-card { width: min(560px, 100%); max-height: min(760px, calc(100vh - 32px)); overflow: auto; }.access-user-summary { display: flex; align-items: center; gap: 10px; padding: 11px 12px; background: #f3f8f5; color: #2e655b; }.access-user-summary :deep(svg) { flex: 0 0 auto; width: 17px; }.access-user-summary strong, .access-user-summary small { display: block; }.access-user-summary strong { font-size: 12px; }.access-user-summary small { margin-top: 3px; color: #71847e; font-size: 10px; }.scope-fieldset { display: grid; gap: 7px; min-inline-size: 0; margin: 0; padding: 11px 12px 12px; border: 1px solid #dbe7e2; }.scope-fieldset legend { padding: 0 4px; color: #527069; font-size: 11px; font-weight: 650; }.scope-help { margin: -1px 0 3px; color: #7a8d87; font-size: 10px; line-height: 1.45; }.scope-option { display: flex !important; grid-template-columns: none !important; align-items: flex-start; gap: 9px !important; padding: 7px 8px; color: #365950 !important; font-weight: 500 !important; cursor: pointer; }.scope-option:hover { background: #f4f8f6; }.scope-option input { width: 15px; height: 15px; min-height: 0; margin: 1px 0 0; accent-color: #147d72; }.scope-option input:disabled { cursor: not-allowed; }.scope-option span { min-width: 0; }.scope-option strong, .scope-option small { display: block; }.scope-option strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 11px; }.scope-option small { margin-top: 3px; color: #82938e; font-size: 9px; }.scope-option--suspended { background: #fffaf1; color: #755f3d !important; }.scope-option--suspended:hover { background: #fff6e5; }.scope-empty { padding: 8px; color: #879792; font-size: 10px; }.form-error { display: flex; align-items: flex-start; gap: 7px; padding: 9px 10px; border: 1px solid #ebc9c3; background: #fff3f1; color: #99534c; font-size: 10px; line-height: 1.45; }.form-error :deep(svg) { flex: 0 0 auto; width: 15px; margin-top: 1px; }.access-editor-card .modal-actions { position: sticky; bottom: -22px; margin: 0 -22px -22px; padding: 13px 22px 22px; background: #fff; border-top: 1px solid #edf1f0; }
.resource-panel { overflow: hidden; }
.resource-actions { display: flex; align-items: center; gap: 8px; }
.resource-toolbar { min-height: 62px; display: flex; align-items: center; gap: 14px; padding: 0 20px; border-bottom: 1px solid #e8efec; background: #fbfdfc; }
.resource-search { min-width: 0; width: min(420px, 100%); height: 36px; display: flex; align-items: center; gap: 8px; padding: 0 10px; border: 1px solid #d7e3df; background: #fff; transition: border-color .2s ease, box-shadow .2s ease; }
.resource-search:focus-within { border-color: #258779; box-shadow: 0 0 0 3px rgba(37,135,121,.09); }
.resource-search :deep(svg) { flex: 0 0 auto; width: 16px; color: #8ca19a; }
.resource-search input { min-width: 0; flex: 1; height: 100%; border: 0; outline: 0; color: #24433d; background: transparent; font: inherit; font-size: 12px; }
.resource-search input::placeholder { color: #a0ada9; }
.resource-count { flex: 0 0 auto; margin-left: auto; color: #7d8e89; font-size: 11px; white-space: nowrap; }
.resource-table { width: 100%; }
.resource-table-head, .resource-row { display: grid; grid-template-columns: minmax(180px, 1.4fr) minmax(150px, 1fr) minmax(100px, .7fr) 40px; column-gap: 16px; align-items: center; padding: 0 20px; }
.resource-table-head { min-height: 42px; color: #82918d; background: #f7faf9; border-bottom: 1px solid #e8efec; font-size: 10px; font-weight: 700; letter-spacing: .04em; }
.resource-row { min-height: 68px; color: #34524b; border-bottom: 1px solid #edf2f0; }
.resource-row:last-child { border-bottom: 0; }
.resource-row:hover { background: #fbfdfc; }
.resource-name { min-width: 0; display: flex; align-items: center; gap: 10px; }
.resource-name :deep(svg) { flex: 0 0 auto; width: 18px; height: 18px; color: #528a7f; }
.resource-name strong { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #27453e; font-size: 12px; font-weight: 650; }
.resource-detail { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #71847e; font-size: 11px; }
.row-status { display: inline-flex; align-items: center; gap: 6px; min-width: 0; color: #5d766e; font-size: 10px; white-space: nowrap; }
.row-status i { width: 7px; height: 7px; flex: 0 0 7px; border-radius: 50%; background: #d0a25e; }
.row-status--success { color: #33806c; }.row-status--success i { background: #45a57f; }.row-status--warning { color: #92703b; }.row-status--warning i { background: #d09b4c; }
.row-more { width: 32px; height: 32px; display: grid; place-items: center; justify-self: end; border: 1px solid transparent; border-radius: 6px; color: #718781; background: #f5f9f7; cursor: pointer; transition: .2s ease; }
.row-more:hover { border-color: #b8d4cb; color: #147d72; background: #eaf5f1; }
.row-more :deep(svg) { width: 15px; }
.users-panel { margin-top: 18px; }
.users-panel .resource-table-head, .users-panel .resource-row { grid-template-columns: minmax(160px, 1.1fr) minmax(170px, 1fr) minmax(84px, .55fr) minmax(120px, .75fr) minmax(210px, 1fr); }
.enterprises-panel .resource-table-head, .enterprises-panel .resource-row { grid-template-columns: minmax(180px, 1.4fr) minmax(170px, 1fr) minmax(90px, .6fr) minmax(130px, auto); }
.conversations-panel .resource-table-head, .conversations-panel .resource-row { grid-template-columns: minmax(200px, 1.6fr) minmax(160px, 1fr) minmax(140px, .9fr) minmax(90px, auto); }
.adp-apps-panel .resource-table-head, .adp-apps-panel .resource-row { grid-template-columns: minmax(180px, 1.3fr) minmax(180px, 1.1fr) minmax(120px, .8fr) minmax(220px, auto); }
.adp-apps-panel .resource-toolbar { justify-content: space-between; }
.adp-apps-panel .toolbar-heading { display: flex; flex-direction: column; gap: 2px; }
.adp-apps-panel .toolbar-heading .section-kicker { margin: 0; }
.adp-apps-panel .toolbar-title { font-size: 14px; font-weight: 650; line-height: 1.2; color: var(--ink, #142322); }
.toolbar-title { margin: 0; color: #17312e; font-size: 18px; }
.adp-config-panel .admin-panel-heading .row-status { font-size: 10px; }
.adp-config-summary { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; padding: 4px 20px 10px; }
.adp-config-summary > div { display: flex; flex-direction: column; gap: 5px; padding: 12px 14px; background: #f4f8f6; border: 1px solid #e6efec; border-radius: 6px; }
.adp-config-summary span { color: #71847e; font-size: 10px; }
.adp-config-summary strong { color: #24433d; font-size: 14px; word-break: break-all; }
.adp-config-note { margin: 0; padding: 4px 20px 18px; color: #8a9894; font-size: 10px; line-height: 1.6; }
@media (max-width: 560px) { .adp-config-summary { grid-template-columns: 1fr; } }
.modal-card--wide { width: min(760px, 100%); gap: 12px; --control-height: 34px; }
.modal-card--wide .modal-heading { margin-bottom: 0; }
.modal-card--wide label { gap: 4px; }
.modal-columns { display: grid; grid-template-columns: 1fr 1fr; gap: 10px 24px; align-items: start; }
.modal-section { display: flex; flex-direction: column; gap: 10px; }
.modal-section-title { margin: 0; font-size: 12px; font-weight: 700; color: #2e655b; padding-bottom: 6px; border-bottom: 1px solid #e6efec; }
.modal-section-fields { display: grid; gap: 10px; }
.modal-card--wide .modal-notice { padding: 7px 10px; }
@media (max-width: 620px) { .modal-columns { grid-template-columns: 1fr; } }
.toolbar-filter { width: min(220px, 45%); flex: 0 0 auto; }
.default-badge { margin-left: 6px; padding: 1px 6px; border-radius: 4px; background: #e8f5ef; color: #2e6b58; font-size: 9px; font-style: normal; }
.modal-notice { display: flex; align-items: center; gap: 8px; padding: 9px 11px; background: #f3f8f5; color: #3a6a5e; font-size: 11px; }
.modal-notice :deep(svg) { flex: 0 0 auto; width: 15px; }
.pager { display: inline-flex; gap: 4px; margin-left: 12px; }
.conversation-detail-card { width: min(640px, 100%); max-height: min(760px, calc(100vh - 32px)); overflow: auto; }
.conversation-meta { margin: -4px 0 4px; color: #71847e; font-size: 11px; }
.conversation-thread { display: grid; gap: 8px; }
.conversation-msg { padding: 9px 11px; border: 1px solid #e6edea; background: #f7faf9; }
.conversation-msg--assistant { background: #eff7f3; border-color: #d5e8e0; }
.conversation-msg-role { color: #4e6b64; font-size: 10px; font-weight: 700; }
.conversation-msg p { margin: 4px 0 3px; color: #2c4a43; font-size: 12px; line-height: 1.5; white-space: pre-wrap; overflow-wrap: anywhere; }
.conversation-msg time { color: #97a39f; font-size: 9px; }
.conversation-runs { margin-top: 12px; display: grid; gap: 6px; }
.conversation-runs > strong { color: #526b65; font-size: 11px; }
.conversation-run { display: flex; align-items: center; gap: 8px; font-size: 11px; color: #45615d; }
.conversation-run small { margin-left: auto; color: #93a19d; font-size: 10px; }
.field-hint { color: #93a19d; font-weight: 400; font-size: 10px; }.provider-warning { display: block; margin: -4px 0 2px; padding: 8px 10px; color: #8a6331; background: #fff8e9; border: 1px solid #eedbb5; font-size: 10px; line-height: 1.45; }
.modal-card input:disabled { background: #f2f5f4; color: #8a9995; cursor: not-allowed; }
.resource-name strong small { display: block; margin-top: 3px; color: #8a9995; font-size: 10px; font-weight: 400; }
.user-scope strong, .user-scope small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.user-scope strong { color: #3d5d55; font-size: 11px; font-weight: 650; }.user-scope small { margin-top: 3px; color: #879792; font-size: 10px; }
.row-actions { min-width: 0; display: flex; align-items: center; justify-content: flex-end; gap: 6px; white-space: nowrap; }
.text-action { border: 0; padding: 5px 6px; color: #317c70; background: transparent; font-size: 10px; cursor: pointer; }.text-action:hover { color: #0e685f; background: #eef7f4; }.text-action--danger { color: #a24e4e; }.text-action--danger:hover { color: #8b3d3d; background: #fff3f1; }.text-action:disabled { color: #b8c2bf; background: transparent; cursor: not-allowed; }
@media (max-width: 850px) { .admin-metric-grid { grid-template-columns: repeat(2, 1fr); }.admin-columns { grid-template-columns: 1fr; }.guardrail-strip { align-items: flex-start; flex-wrap: wrap; }.guardrail-strip a { margin-left: 43px; }.resource-table-head, .resource-row { grid-template-columns: 1.3fr 1fr .7fr 28px; gap: 9px; padding-left: 14px; padding-right: 14px; }.resource-toolbar { padding: 0 14px; } }
@media (max-width: 560px) { .admin-intro { display: block; }.admin-intro .subtle-button { margin-top: 16px; }.admin-intro h1, h1 { font-size: 26px; }.admin-metric-grid { gap: 9px; }.admin-metric { min-height: 105px; padding: 14px; }.admin-metric strong { font-size: 24px; margin: 13px 0 7px; }.config-items { grid-template-columns: 1fr; }.config-actions { flex-wrap: wrap; }.resource-actions { margin-top: 16px; }.resource-table-head { display: none; }.resource-row { grid-template-columns: 1fr auto 24px; gap: 8px; min-height: 75px; }.resource-detail { grid-column: 1 / 2; margin-left: 25px; margin-top: -22px; }.row-status { grid-column: 2 / 3; grid-row: 1; }.row-more { grid-column: 3 / 4; grid-row: 1; }.resource-toolbar { flex-wrap: wrap; padding: 12px 14px; }.resource-search { max-width: none; flex-basis: 100%; }.resource-count { margin-left: auto; }.toast { top: 70px; right: 15px; left: 15px; }.access-editor-card { max-height: calc(100vh - 24px); padding: 18px; }.access-editor-card .modal-actions { margin: 0 -18px -18px; padding: 12px 18px 18px; } }
@media (max-width: 850px) {
  .resource-actions { display: flex; flex-wrap: wrap; justify-content: flex-end; }
  .users-panel .resource-table-head, .users-panel .resource-row { grid-template-columns: minmax(150px, 1fr) minmax(150px, 1fr) 82px minmax(108px, .7fr) minmax(200px, auto); }
}
@media (max-width: 760px) {
  .users-panel .resource-table-head { display: none; }
  .users-panel .resource-row.user-row { grid-template-columns: minmax(0, 1fr) auto; grid-template-areas: 'user status' 'scope scope' 'secret secret' 'actions actions'; row-gap: 8px; min-height: 118px; padding: 14px; }
  .users-panel .user-row .resource-name { grid-area: user; }
  .users-panel .user-row .row-secret { grid-area: secret; padding-left: 28px; }
  .users-panel .user-row .user-scope { grid-area: scope; margin: 0; padding-left: 28px; }
  .users-panel .user-row .row-status { grid-area: status; }
  .users-panel .user-row .row-actions { grid-area: actions; justify-content: flex-start; padding-top: 8px; border-top: 1px solid #edf2f0; }
  .users-panel .user-row .row-actions .row-more { margin-left: auto; order: 4; }
}
@media (max-width: 560px) {
  .resource-actions { align-items: stretch; justify-content: flex-start; gap: 8px; }
  .resource-actions button { flex: 1 1 auto; }
  .resource-table-head { display: none; }
  .resource-row:not(.user-row) { grid-template-columns: minmax(0, 1fr) auto 30px; grid-template-areas: 'name status more' 'detail detail more'; row-gap: 3px; min-height: 82px; padding: 13px 14px; }
  .resource-row:not(.user-row) .resource-name { grid-area: name; }
  .resource-row:not(.user-row) .resource-detail { grid-area: detail; margin: 0 0 0 28px; align-self: start; }
  .resource-row:not(.user-row) .row-status { grid-area: status; }
  .resource-row:not(.user-row) .row-more { grid-area: more; align-self: center; }
  .users-panel .resource-row.user-row { grid-template-columns: minmax(0, 1fr) auto; grid-template-areas: 'user status' 'scope scope' 'secret secret' 'actions actions'; row-gap: 8px; min-height: 118px; padding: 14px; }
  .users-panel .user-row .resource-name { grid-area: user; }
  .users-panel .user-row .row-secret { grid-area: secret; padding-left: 28px; }
  .users-panel .user-row .user-scope { grid-area: scope; margin: 0; padding-left: 28px; }
  .users-panel .user-row .row-status { grid-area: status; }
  .users-panel .user-row .row-actions { grid-area: actions; justify-content: flex-start; padding-top: 8px; border-top: 1px solid #edf2f0; }
  .users-panel .user-row .row-actions .row-more { margin-left: auto; order: 4; }
  .resource-toolbar { align-items: stretch; }
  .resource-count { align-self: center; }
}

/* M1-UI-01: keep the admin surface on one spacing and interaction scale. */
.admin-intro { gap: var(--space-6); margin-bottom: var(--space-6); }
.admin-intro > div:first-child { min-width: 0; }
.subtle-button, .primary-action, .outline-action {
  min-height: var(--control-height);
  border-radius: var(--radius-control);
  white-space: nowrap;
}
.subtle-button:focus-visible, .primary-action:focus-visible, .outline-action:focus-visible,
.text-action:focus-visible, .row-more:focus-visible, .modal-close:focus-visible,
.resource-search:focus-within, .platform-nav-item:focus-visible {
  outline: 2px solid rgba(20, 125, 114, .34);
  outline-offset: 2px;
}
.admin-metric-grid { gap: var(--space-4); margin-bottom: var(--space-7); }
.admin-columns { gap: var(--space-6); }
.config-actions { gap: var(--space-3); }
.guardrail-strip { gap: var(--space-3); margin-top: var(--space-6); }
.guardrail-strip > div { min-width: 0; }
.guardrail-strip p { overflow-wrap: anywhere; }
.guardrail-strip a { min-height: var(--control-height); padding: 0 var(--space-2); }
.secret-alert { gap: var(--space-2); margin: 0 0 var(--space-6); }
.secret-alert > span { min-width: 0; overflow-wrap: anywhere; }
.secret-alert button, .modal-close {
  width: var(--control-height);
  height: var(--control-height);
  display: inline-grid;
  place-items: center;
  flex: 0 0 var(--control-height);
  padding: 0;
}
.draft-summary { gap: var(--space-2); margin-top: var(--space-3); }
.draft-summary strong, .draft-summary small,
.config-history-heading strong, .config-history-heading small { min-width: 0; }
.draft-summary small, .config-history-heading small { overflow-wrap: anywhere; }
.config-history-row { gap: var(--space-3); }
.resource-panel + .resource-panel { margin-top: var(--space-6); }
.resource-actions { gap: var(--space-3); }
.resource-toolbar { min-height: 64px; gap: var(--space-4); }
.resource-search { height: var(--control-height); }
.resource-table-head, .resource-row { column-gap: var(--space-4); }
.row-more { width: var(--control-height); height: var(--control-height); }
.row-actions { gap: var(--space-2); }
.text-action { min-width: var(--control-height); min-height: var(--control-height); padding: 0 var(--space-2); }
.inline-alert { gap: var(--space-2); }
.inline-alert > :not(button) { min-width: 0; }
.inline-alert button { min-height: var(--control-height); padding: 0 var(--space-2); }
.modal-backdrop { padding: var(--space-4); }
.modal-card { gap: var(--space-4); padding: var(--space-6); max-height: min(720px, calc(100vh - 24px)); overflow: auto; }
.modal-card input, .modal-card select { min-height: var(--control-height); }
.modal-actions { gap: var(--space-3); margin-top: 0; }
.modal-help, .scope-help { min-width: 0; overflow-wrap: anywhere; }
.config-editor-card, .access-editor-card { max-height: min(760px, calc(100vh - 24px)); }
.config-editor-card .modal-actions, .access-editor-card .modal-actions {
  bottom: -1px;
  margin: 0 calc(var(--space-6) * -1);
  padding: var(--space-4) var(--space-6) var(--space-6);
}
.admin-columns,
.admin-columns > .admin-panel,
.config-panel,
.activity-panel {
  min-width: 0;
  width: 100%;
}
.config-version > *,
.config-history-row > span,
.activity-main,
.activity-row time {
  min-width: 0;
}
.config-version span,
.config-version small,
.config-history-row span small,
.activity-main strong,
.activity-row time {
  overflow-wrap: anywhere;
}
.activity-row time {
  overflow: hidden;
  text-overflow: ellipsis;
}
.flag-fieldset { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--space-3); padding: var(--space-3); }
.checkbox-row { min-height: var(--control-height); }
.scope-fieldset { gap: var(--space-2); padding: var(--space-3); }
.scope-option { min-height: var(--control-height); gap: var(--space-2); padding: var(--space-2); }
.scope-option small { overflow-wrap: anywhere; }
.scope-option input, .checkbox-row input { flex: 0 0 auto; }

@media (max-width: 850px) {
  .resource-actions { justify-content: flex-end; }
  .resource-table-head, .resource-row { column-gap: var(--space-3); }
}

@media (max-width: 760px) {
  .users-panel .resource-row.user-row { row-gap: var(--space-3); }
  .users-panel .user-row .row-actions { gap: var(--space-2); padding-top: var(--space-3); }
}

@media (max-width: 560px) {
  .admin-intro .subtle-button { margin-top: var(--space-4); }
  .resource-actions .subtle-button { margin-top: 0; }
  .admin-metric-grid { gap: var(--space-3); }
  .resource-actions { width: 100%; gap: var(--space-2); }
  .resource-actions button { flex: 1 1 0; min-width: 0; white-space: normal; line-height: 1.25; }
  .resource-toolbar { gap: var(--space-3); padding: var(--space-3) var(--space-4); }
  .resource-row:not(.user-row) { grid-template-columns: minmax(0, 1fr) auto var(--control-height); column-gap: var(--space-2); }
  .users-panel .resource-row.user-row { row-gap: var(--space-3); padding: var(--space-4); }
  .users-panel .user-row .row-actions { gap: var(--space-1); padding-top: var(--space-3); }
  .modal-backdrop { padding: var(--space-3); }
  .modal-card { padding: 18px; }
  .config-editor-card .modal-actions, .access-editor-card .modal-actions {
    margin: 0 -18px;
    padding: var(--space-3) 18px 18px;
  }
  .flag-fieldset { grid-template-columns: 1fr; }
}
</style>
