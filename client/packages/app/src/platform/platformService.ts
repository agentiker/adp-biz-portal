import { httpService } from '@/service/httpService'
import type {
  AdminOverview,
  AdminConfigState,
  AdminConfigVersion,
  AdminAuditEvent,
  AdminConversationList,
  AdminConversationDetail,
  AdminEnterprise,
  AdpApp,
  CreateAdpAppRequest,
  UpdateAdpAppRequest,
  AdminPasswordResetResult,
  AdminUser,
  AdminUserCreateResult,
  EnterpriseScope,
  PlatformLoginResult,
  PlatformUser,
  PortalOverview,
  PortalSession,
  PortalSessionDetail,
  SharedResultResponse,
  ShipmentResult,
  PlatformConfigPayload,
  PlatformRole,
  WebInboundStatus,
  InboundReceipt,
  ChannelCredential,
  ChannelIdentity,
  IntegrationBinding,
  AdpConfigStatus,
} from './types'

const useMock = import.meta.env.VITE_PLATFORM_USE_MOCK === 'true'

const demoUser: PlatformUser = {
  id: 'usr_demo_01',
  name: '林晓岚',
  phone: '138****9021',
  role: 'customer',
  roleLabel: '客户员工',
}

const demoEnterprise: EnterpriseScope = {
  id: 'ent_demo_01',
  name: '远洋国际物流（上海）有限公司',
  customerCode: 'M3-SH-2048',
  permissions: ['提单查询', '船期查询', '节点追踪'],
}

const platformRoleLabels: Record<PlatformRole, string> = {
  customer: '客户员工',
  staff: '客服 / 销售',
  admin: '平台管理员',
  ops: '运维人员',
}

const mockEnterprises: AdminEnterprise[] = [
  { id: 'ent_demo_01', name: demoEnterprise.name, customerCode: demoEnterprise.customerCode, status: 'active' },
  { id: 'ent_demo_02', name: '东海供应链（宁波）有限公司', customerCode: 'M3-NB-1180', status: 'active' },
  { id: 'ent_demo_03', name: '北辰国际货运代理有限公司', customerCode: 'M3-QD-0772', status: 'active' },
  { id: 'ent_demo_04', name: '示例停用企业', customerCode: 'M3-DEMO-OFF', status: 'suspended' },
]

const mockUsers: AdminUser[] = [
  {
    ...demoUser,
    status: 'active',
    enterprises: [{ id: mockEnterprises[0].id, name: mockEnterprises[0].name, customerCode: mockEnterprises[0].customerCode, status: mockEnterprises[0].status }],
  },
  {
    id: 'usr_demo_02',
    name: '王钊',
    phone: '139****1486',
    role: 'staff',
    roleLabel: platformRoleLabels.staff,
    status: 'active',
    enterprises: [
      { id: mockEnterprises[0].id, name: mockEnterprises[0].name, customerCode: mockEnterprises[0].customerCode, status: mockEnterprises[0].status },
      { id: mockEnterprises[1].id, name: mockEnterprises[1].name, customerCode: mockEnterprises[1].customerCode, status: mockEnterprises[1].status },
    ],
  },
  {
    id: 'usr_demo_03',
    name: '陈璐',
    phone: '138****4108',
    role: 'ops',
    roleLabel: platformRoleLabels.ops,
    status: 'disabled',
    enterprises: [],
  },
]

const cloneEnterprise = (enterprise: AdminEnterprise): AdminEnterprise => ({ ...enterprise })
const cloneAdminUser = (user: AdminUser): AdminUser => ({
  ...user,
  enterprises: user.enterprises.map(cloneEnterprise),
})
const roleLabelFor = (role: PlatformRole) => platformRoleLabels[role]

const demoSessions: PortalSession[] = [
  {
    id: 'conv_1024',
    title: 'MSCU 货物节点追踪',
    query: 'MSCU',
    channel: '官网',
    preview: '已核实当前船期与最近节点，共 4 条证据。',
    updatedAt: '今天 10:42',
    evidence: true,
  },
  {
    id: 'conv_1019',
    title: '宁波到鹿特丹船期',
    query: '宁波到鹿特丹',
    channel: '官网',
    preview: '已返回预计离港时间，实际靠泊时间暂未产生。',
    updatedAt: '昨天 16:18',
    evidence: true,
  },
  {
    id: 'conv_1011',
    title: '提单号格式确认',
    query: '',
    channel: '官网',
    preview: '已完成格式校验，等待补充箱号。',
    updatedAt: '09 月 03 日',
    evidence: false,
  },
]

const overview: PortalOverview = {
  user: demoUser,
  enterprise: demoEnterprise,
  enterprises: [demoEnterprise],
  stats: { activeShipments: 18, pendingMilestones: 3, recentQueries: 26 },
  services: [
    { name: 'M3 业务数据', detail: '只读查询网关', status: 'healthy', updatedAt: '刚刚同步' },
    { name: 'AI 助手', detail: '回答与证据整理', status: 'healthy', updatedAt: '运行正常' },
    { name: '消息投递', detail: '官网会话', status: 'degraded', updatedAt: '1 个延迟任务' },
  ],
  sessions: demoSessions,
}

const adminOverview: AdminOverview = {
  metrics: [
    { label: '已接入企业', value: '248', note: '本月新增 12 家', tone: 'neutral' },
    { label: '待绑定身份', value: '17', note: '需要客服跟进', tone: 'warning' },
    { label: '渠道在线', value: '3 / 4', note: '微信客服需关注', tone: 'success' },
    { label: '失败执行', value: '2', note: '过去 24 小时', tone: 'warning' },
  ],
  activities: [
    { action: '发布配置 v1.8', actor: '周明 / 平台管理员', target: '官网客户门户', at: '今天 09:26', tone: 'success' },
    { action: '停用账号', actor: '陈璐 / 客服主管', target: '138****4108', at: '昨天 18:04', tone: 'warning' },
    { action: '新增企业范围', actor: '王钊 / 业务主管', target: '华东客户组', at: '昨天 15:32', tone: 'neutral' },
    { action: '测试 M3 连接', actor: '系统', target: 'M3-SH-2048', at: '昨天 11:10', tone: 'success' },
  ],
  config: {
    version: 'v1.8',
    status: 'published',
    updatedAt: '2026-09-05 09:26 by 周明',
    items: ['客户登录与会话', 'M3 只读工具', '官网渠道', '审计记录'],
  },
}

const mockConfigPayload: PlatformConfigPayload = {
  items: [...adminOverview.config.items],
  featureFlags: { portal: true, m3ReadOnly: true, audit: true, webChannel: true },
  notes: '',
}

const mockConfigVersion = (version: number, status: AdminConfigVersion['status'], payload = mockConfigPayload): AdminConfigVersion => ({
  id: `cfg_demo_${version}`,
  version,
  status,
  payload: { ...payload, items: [...payload.items], featureFlags: { ...payload.featureFlags } },
  validationErrors: [],
  createdByAccountId: 'acct_demo_admin',
  publishedByAccountId: status === 'published' ? 'acct_demo_admin' : null,
  rolledBackByAccountId: null,
  createdAt: '2026-09-05T01:26:00.000Z',
  updatedAt: '2026-09-05T01:26:00.000Z',
  publishedAt: status === 'published' ? '2026-09-05T01:26:00.000Z' : null,
  rolledBackAt: null,
  rollbackSourceVersion: null,
})

const mockConfigState: AdminConfigState = {
  published: mockConfigVersion(8, 'published'),
  draft: null,
  history: [mockConfigVersion(8, 'published')],
}

const mockBindings: IntegrationBinding[] = []
const mockChannelCredentials: ChannelCredential[] = []
const mockChannelIdentities: ChannelIdentity[] = []

async function requestOrMock<T>(path: string, fallback: T, options?: { method?: 'GET' | 'POST'; data?: unknown }): Promise<T> {
  if (useMock) return fallback
  if (options?.method === 'POST') {
    return httpService.post<T>(path, (options.data || {}) as object)
  }
  return httpService.get<T>(path)
}

export async function loginPlatform(phone: string, password: string): Promise<PlatformLoginResult> {
  const fallback: PlatformLoginResult = {
    token: `platform-demo-${Date.now()}`,
    user: { ...demoUser, phone: phone.replace(/^(\d{3})\d{4}(\d{4})$/, '$1****$2') || demoUser.phone },
    enterprise: demoEnterprise,
    enterprises: [demoEnterprise],
    permissions: ['shipment.read'],
    mustReset: false,
  }
  return requestOrMock('/api/v1/auth/login', fallback, { method: 'POST', data: { phone, password } })
}

export async function getPlatformSession(): Promise<PlatformLoginResult> {
  return requestOrMock('/api/v1/auth/session', {
    token: '',
    user: demoUser,
    enterprise: demoEnterprise,
    enterprises: [demoEnterprise],
    permissions: ['shipment.read'],
    mustReset: false,
  })
}

export async function getPortalOverview(): Promise<PortalOverview> {
  return requestOrMock('/api/v1/portal/overview', overview)
}

export async function getPortalSessions(): Promise<PortalSession[]> {
  return requestOrMock('/api/v1/portal/sessions', demoSessions)
}

export async function getPortalSession(conversationId: string): Promise<PortalSessionDetail> {
  if (useMock) {
    const session = demoSessions.find((item) => item.id === conversationId)
    if (!session) throw new Error('会话不存在或无权访问')
    const restored = session.query ? await lookupShipment(session.query, conversationId) : null
    const run = restored ? {
      runId: `run_${conversationId}`,
      status: restored.status,
      query: restored.query,
      title: restored.title,
      summary: restored.summary,
      traceId: restored.traceId,
      startedAt: session.updatedAt,
      completedAt: session.updatedAt,
      evidence: restored.evidence,
    } : null
    return {
      conversation: session,
      messages: restored ? [{ id: `msg_${conversationId}`, direction: 'assistant', messageType: 'shipment.result', body: restored.summary, runId: run?.runId || null, traceId: restored.traceId, createdAt: session.updatedAt }] : [],
      runs: run ? [run] : [],
      result: restored,
    }
  }
  return httpService.get<PortalSessionDetail>(`/api/v1/portal/sessions/${encodeURIComponent(conversationId)}`)
}

export async function getSharedResult(token: string): Promise<SharedResultResponse> {
  // Public, no-login read of one result. An invalid/expired/revoked token
  // returns 404 (not 401), so this never triggers the auth logout interceptor.
  return httpService.get<SharedResultResponse>(`/api/v1/portal/shared/${encodeURIComponent(token)}`)
}

export async function submitWebInbound(text: string, conversationId?: string | null, messageId?: string, enterpriseId?: string | null): Promise<InboundReceipt> {
  return httpService.post<InboundReceipt>('/api/v1/channels/web/inbound', {
    text,
    ...(conversationId ? { conversationId } : {}),
    ...(messageId ? { messageId } : {}),
    // Only the enterprise scope is accepted from the browser, and the server
    // still checks it against current memberships.
    ...(enterpriseId ? { enterpriseId } : {}),
  })
}

export async function getWebInboundStatus(inboundMessageId: string): Promise<WebInboundStatus> {
  return httpService.get<WebInboundStatus>(`/api/v1/channels/web/inbound/${encodeURIComponent(inboundMessageId)}`)
}

export async function lookupShipment(query: string, conversationId?: string | null): Promise<ShipmentResult> {
  const normalized = query.trim().toUpperCase()
  const found = normalized.length > 4 && !normalized.includes('UNKNOWN') && !normalized.includes('不存在')
  const fallback: ShipmentResult = found
    ? {
      query: normalized,
      conversationId: conversationId || `conv_demo_${Date.now()}`,
        status: 'found',
        title: '已找到 1 条可访问记录',
        summary: '以下结果来自当前企业授权范围。未返回的字段表示 M3 暂无可核实数据。',
        traceId: 'trc_m3_7f28c1',
        evidence: [
          { label: '提单号', value: normalized, source: 'M3 / shipment.lookup', capturedAt: '2026-09-05 10:44:12', known: true },
          { label: '船名 / 航次', value: 'EVER GIVEN · 118E', source: 'M3 / shipment.schedule', capturedAt: '2026-09-05 10:44:13', known: true },
          { label: '预计抵港', value: '2026-09-24 08:00（当地时间）', source: 'M3 / shipment.schedule', capturedAt: '2026-09-05 10:44:13', known: true },
          { label: '当前节点', value: '已离港 · 新加坡', source: 'M3 / shipment.milestones', capturedAt: '2026-09-05 10:44:14', known: true },
          { label: '实际抵港', value: '暂无数据', source: 'M3 / shipment.milestones', capturedAt: '2026-09-05 10:44:14', known: false },
        ],
      }
    : {
      query: normalized,
      conversationId: conversationId || `conv_demo_${Date.now()}`,
        status: 'not_found',
        title: '未找到可访问的业务记录',
        summary: '请检查提单号或箱号是否正确。如果记录属于其他企业，平台不会返回其存在性。',
        traceId: 'trc_m3_7f28c2',
        evidence: [],
      }
  return requestOrMock('/api/v1/tools/shipment/lookup', fallback, {
    method: 'POST',
    data: { query, ...(conversationId ? { conversationId } : {}) },
  })
}

export async function getAdminOverview(): Promise<AdminOverview> {
  return requestOrMock('/api/v1/admin/overview', {
    ...adminOverview,
    config: {
      ...adminOverview.config,
      version: mockConfigState.published ? `v${mockConfigState.published.version}` : adminOverview.config.version,
      status: 'published',
      updatedAt: mockConfigState.published?.updatedAt || adminOverview.config.updatedAt,
      items: mockConfigState.published?.payload.items || adminOverview.config.items,
      published: mockConfigState.published,
      draft: mockConfigState.draft,
      history: mockConfigState.history,
    },
  })
}

export async function getAdminConfig(): Promise<AdminConfigState> {
  return requestOrMock('/api/v1/admin/config', mockConfigState)
}

export async function saveAdminConfigDraft(payload: PlatformConfigPayload): Promise<AdminConfigState> {
  if (useMock) {
    const latest = Math.max(...mockConfigState.history.map((item) => item.version), mockConfigState.published?.version || 0)
    const draft = mockConfigVersion(mockConfigState.draft?.version || latest + 1, 'draft', payload)
    draft.publishedByAccountId = null
    draft.publishedAt = null
    mockConfigState.draft = draft
    mockConfigState.history = [draft, ...mockConfigState.history.filter((item) => item.version !== draft.version)]
    return mockConfigState
  }
  return httpService.post<AdminConfigState>('/api/v1/admin/config/draft', { payload })
}

export async function publishAdminConfig(): Promise<AdminConfigState> {
  if (useMock) {
    if (!mockConfigState.draft) throw new Error('没有可发布的配置草稿')
    const previous = mockConfigState.published
    const published = { ...mockConfigState.draft, status: 'published' as const, publishedAt: new Date().toISOString(), updatedAt: new Date().toISOString(), publishedByAccountId: 'acct_demo_admin' }
    mockConfigState.published = published
    mockConfigState.draft = null
    mockConfigState.history = [published, ...(previous ? [{ ...previous, status: 'rolled_back' as const, rolledBackAt: new Date().toISOString(), rollbackSourceVersion: published.version }] : []), ...mockConfigState.history.filter((item) => item.version !== published.version && item.version !== previous?.version)]
    return mockConfigState
  }
  return httpService.post<AdminConfigState>('/api/v1/admin/config/publish', {})
}

export async function rollbackAdminConfig(version: number): Promise<AdminConfigState> {
  if (useMock) {
    const target = mockConfigState.history.find((item) => item.version === version)
    if (!target || target.status === 'draft') throw new Error('目标配置版本不存在或仍是草稿')
    if (!mockConfigState.published || mockConfigState.published.version === version) throw new Error('目标版本已经是当前发布版本')
    const now = new Date().toISOString()
    const previous = { ...mockConfigState.published, status: 'rolled_back' as const, rolledBackAt: now, rollbackSourceVersion: version }
    const published = { ...target, status: 'published' as const, publishedAt: now, updatedAt: now, rolledBackAt: null, rollbackSourceVersion: null }
    mockConfigState.published = published
    mockConfigState.history = [published, previous, ...mockConfigState.history.filter((item) => item.version !== version && item.version !== previous.version)]
    return mockConfigState
  }
  return httpService.post<AdminConfigState>('/api/v1/admin/config/rollback', { version })
}

export async function listEnterprises(): Promise<AdminEnterprise[]> {
  if (useMock) return mockEnterprises.map(cloneEnterprise)
  return httpService.get<AdminEnterprise[]>('/api/v1/admin/enterprises')
}

export type EnterpriseInput = {
  name: string
  customerCode?: string
  unifiedSocialCreditCode?: string
  contactPerson?: string
  contactPhone?: string
  adpAppId?: string
}

export async function createEnterprise(input: EnterpriseInput): Promise<AdminEnterprise> {
  if (useMock) {
    const enterprise: AdminEnterprise = {
      id: `ent_demo_${Date.now()}`,
      name: input.name.trim(),
      customerCode: (input.customerCode || '').trim(),
      unifiedSocialCreditCode: input.unifiedSocialCreditCode?.trim() || undefined,
      contactPerson: input.contactPerson?.trim() || undefined,
      contactPhone: input.contactPhone?.trim() || undefined,
      status: 'active',
    }
    mockEnterprises.unshift(enterprise)
    return cloneEnterprise(enterprise)
  }
  return httpService.post<AdminEnterprise>('/api/v1/admin/enterprises', input)
}

export async function updateEnterprise(id: string, input: Omit<EnterpriseInput, 'customerCode'>): Promise<AdminEnterprise> {
  if (useMock) {
    const enterprise = mockEnterprises.find((item) => item.id === id)
    if (!enterprise) throw new Error('企业不存在')
    if (input.name !== undefined) enterprise.name = input.name.trim()
    if (input.unifiedSocialCreditCode !== undefined) enterprise.unifiedSocialCreditCode = input.unifiedSocialCreditCode.trim() || undefined
    if (input.contactPerson !== undefined) enterprise.contactPerson = input.contactPerson.trim() || undefined
    if (input.contactPhone !== undefined) enterprise.contactPhone = input.contactPhone.trim() || undefined
    return cloneEnterprise(enterprise)
  }
  return httpService.post<AdminEnterprise>(`/api/v1/admin/enterprises/${id}`, input)
}

export async function listPlatformUsers(): Promise<AdminUser[]> {
  if (useMock) return mockUsers.map(cloneAdminUser)
  return httpService.get<AdminUser[]>('/api/v1/admin/users')
}

export async function createPlatformUser(data: { name: string; phone: string; role: string; enterpriseId?: string }): Promise<AdminUserCreateResult> {
  if (useMock) {
    const role = data.role as PlatformRole
    const enterprise = data.enterpriseId ? mockEnterprises.find((item) => item.id === data.enterpriseId) : undefined
    const user: AdminUser = {
      id: `usr_demo_${Date.now()}`,
      name: data.name.trim(),
      phone: data.phone.replace(/^(\d{3})\d{4}(\d{4})$/, '$1****$2'),
      role,
      roleLabel: roleLabelFor(role),
      status: 'active',
      enterprises: enterprise ? [cloneEnterprise(enterprise)] : [],
    }
    mockUsers.unshift(user)
    return { user: cloneAdminUser(user), initialPassword: '123456' }
  }
  return httpService.post<AdminUserCreateResult>('/api/v1/admin/users', data)
}

export async function updatePlatformUserAccess(
  userId: string,
  data: { role: PlatformRole; enterpriseId: string },
): Promise<{ user: AdminUser }> {
  if (useMock) {
    const user = mockUsers.find((item) => item.id === userId)
    if (!user) throw new Error('用户不存在')
    user.role = data.role
    user.roleLabel = roleLabelFor(data.role)
    if (data.enterpriseId) {
      const enterprise = mockEnterprises.find((item) => item.id === data.enterpriseId)
      if (!enterprise) throw new Error('企业不存在')
      if (enterprise.status !== 'active') throw new Error('不能绑定已停用企业')
      user.enterprises = [cloneEnterprise(enterprise)]
    } else {
      user.enterprises = []
    }
    return { user: cloneAdminUser(user) }
  }
  return httpService.post<{ user: AdminUser }>(`/api/v1/admin/users/${encodeURIComponent(userId)}/access`, data)
}

export async function resetPlatformUserPassword(userId: string): Promise<AdminPasswordResetResult> {
  return requestOrMock(`/api/v1/admin/users/${encodeURIComponent(userId)}/reset-password`, { userId, initialPassword: '123456' }, { method: 'POST', data: {} })
}

export async function disablePlatformUser(userId: string): Promise<{ userId: string; status: AdminUser['status'] }> {
  if (useMock) {
    const user = mockUsers.find((item) => item.id === userId)
    if (!user) throw new Error('用户不存在')
    user.status = 'disabled'
    return { userId, status: user.status }
  }
  return httpService.post<{ userId: string; status: AdminUser['status'] }>(`/api/v1/admin/users/${encodeURIComponent(userId)}/disable`, {})
}

export async function listAuditEvents(): Promise<AdminAuditEvent[]> {
  return requestOrMock('/api/v1/admin/audit', [])
}

export async function listAdminConversations(
  params: { limit?: number; offset?: number; enterpriseId?: string } = {},
): Promise<AdminConversationList> {
  if (useMock) return { items: [], total: 0, limit: params.limit ?? 50, offset: params.offset ?? 0 }
  const query = new URLSearchParams()
  if (params.limit != null) query.set('limit', String(params.limit))
  if (params.offset != null) query.set('offset', String(params.offset))
  if (params.enterpriseId) query.set('enterpriseId', params.enterpriseId)
  const suffix = query.toString() ? `?${query.toString()}` : ''
  return httpService.get<AdminConversationList>(`/api/v1/admin/conversations${suffix}`)
}

export async function getAdminConversation(conversationId: string): Promise<AdminConversationDetail> {
  return httpService.get<AdminConversationDetail>(`/api/v1/admin/conversations/${conversationId}`)
}

export async function listAdminBindings(): Promise<IntegrationBinding[]> {
  if (useMock) return mockBindings.map((item) => ({ ...item }))
  return httpService.get<IntegrationBinding[]>('/api/v1/admin/bindings')
}

export async function getAdminAdpConfig(): Promise<AdpConfigStatus> {
  return httpService.get<AdpConfigStatus>('/api/v1/admin/adp-config')
}

export async function listAdpApps(): Promise<AdpApp[]> {
  if (useMock) return []
  return httpService.get<AdpApp[]>('/api/v1/admin/adp-apps')
}

export async function createAdpApp(input: CreateAdpAppRequest): Promise<AdpApp> {
  return httpService.post<AdpApp>('/api/v1/admin/adp-apps', input)
}

export async function updateAdpApp(id: string, input: UpdateAdpAppRequest): Promise<AdpApp> {
  return httpService.post<AdpApp>(`/api/v1/admin/adp-apps/${id}`, input)
}

export async function deleteAdpApp(id: string): Promise<{ deleted: boolean }> {
  return httpService.delete<{ deleted: boolean }>(`/api/v1/admin/adp-apps/${id}`)
}

export async function createAdminBinding(data: {
  applicationId: string
  upstreamAppId: string
  enterpriseId: string
  workspaceId: string
  externalAccountId: string
  vendor?: string
}): Promise<IntegrationBinding> {
  return httpService.post<IntegrationBinding>('/api/v1/admin/bindings', data)
}

export async function listChannelCredentials(): Promise<ChannelCredential[]> {
  if (useMock) return mockChannelCredentials.map((item) => ({ ...item }))
  return httpService.get<ChannelCredential[]>('/api/v1/admin/channel-credentials')
}

export async function createChannelCredential(data: {
  channel: string
  channelInstanceId: string
  credential: string
}): Promise<ChannelCredential> {
  if (useMock) {
    const now = new Date().toISOString()
    const item: ChannelCredential = {
      id: `cred_demo_${Date.now()}`,
      enterpriseId: null,
      connectionId: null,
      channel: data.channel,
      channelInstanceId: data.channelInstanceId,
      credentialMask: '********',
      version: 1,
      keyVersion: 'local-demo',
      fingerprint: 'demo',
      status: 'active',
      createdAt: now,
      updatedAt: now,
      rotatedAt: null,
      expiresAt: null,
    }
    mockChannelCredentials.unshift(item)
    return { ...item }
  }
  return httpService.post<ChannelCredential>('/api/v1/admin/channel-credentials', data)
}

export async function rotateChannelCredential(id: string, credential: string): Promise<ChannelCredential> {
  if (useMock) {
    const item = mockChannelCredentials.find((row) => row.id === id)
    if (!item) throw new Error('渠道凭据不存在')
    item.version += 1
    item.updatedAt = new Date().toISOString()
    item.rotatedAt = item.updatedAt
    return { ...item }
  }
  return httpService.post<ChannelCredential>(`/api/v1/admin/channel-credentials/${encodeURIComponent(id)}/rotate`, { credential })
}

export async function disableChannelCredential(id: string): Promise<ChannelCredential> {
  if (useMock) {
    const item = mockChannelCredentials.find((row) => row.id === id)
    if (!item) throw new Error('渠道凭据不存在')
    item.status = 'disabled'
    item.updatedAt = new Date().toISOString()
    return { ...item }
  }
  return httpService.post<ChannelCredential>(`/api/v1/admin/channel-credentials/${encodeURIComponent(id)}/disable`, {})
}

export async function listAdminChannelIdentities(): Promise<ChannelIdentity[]> {
  if (useMock) return mockChannelIdentities.map((item) => ({ ...item }))
  return httpService.get<ChannelIdentity[]>('/api/v1/admin/channel-identities')
}

export async function listMyChannelIdentities(): Promise<ChannelIdentity[]> {
  if (useMock) return mockChannelIdentities.map((item) => ({ ...item }))
  return httpService.get<ChannelIdentity[]>('/api/v1/channel-identities')
}

export async function startChannelIdentityBinding(
  channel: string,
  channelInstanceId?: string,
): Promise<{ identity: ChannelIdentity; state: string }> {
  // The external identity is deliberately not sent: a customer cannot see
  // their own WeChat OpenID, so the trusted channel adapter supplies it when
  // the one-time state arrives from the real sender. The instance is resolved
  // server-side when the channel has exactly one active instance.
  return httpService.post<{ identity: ChannelIdentity; state: string }>('/api/v1/channel-identities', {
    channel,
    ...(channelInstanceId ? { channelInstanceId } : {}),
  })
}

export async function revokeMyChannelIdentity(id: string): Promise<{ identity: ChannelIdentity }> {
  return httpService.post<{ identity: ChannelIdentity }>(`/api/v1/channel-identities/${encodeURIComponent(id)}/revoke`, {})
}

export async function revokeAdminChannelIdentity(id: string): Promise<{ identity: ChannelIdentity }> {
  if (useMock) {
    const item = mockChannelIdentities.find((row) => row.id === id)
    if (!item) throw new Error('渠道身份不存在')
    item.status = 'revoked'
    item.revokedAt = new Date().toISOString()
    item.updatedAt = item.revokedAt
    return { identity: { ...item } }
  }
  return httpService.post<{ identity: ChannelIdentity }>(`/api/v1/admin/channel-identities/${encodeURIComponent(id)}/revoke`, {})
}

export const platformDemo = { user: demoUser, enterprise: demoEnterprise }
