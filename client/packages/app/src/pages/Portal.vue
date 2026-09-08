<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ArrowRightIcon,
  CheckCircleIcon,
  ChevronRightIcon,
  TimeIcon,
  CloudIcon,
  FileSearchIcon,
  LinkIcon,
  LockOnIcon,
  RefreshIcon,
  SearchIcon,
  ServerIcon,
  ErrorCircleIcon,
} from 'tdesign-icons-vue-next'
import PlatformShell from '@/components/PlatformShell.vue'
import { getPortalOverview, getPortalSession, getPortalSessions, getWebInboundStatus, lookupShipment, submitWebInbound } from '@/platform/platformService'
import type { PortalOverview, PortalSession, ShipmentResult } from '@/platform/types'
import { logout } from '@/service/login'
import { useUserStore } from '@/stores/user'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
const overview = ref<PortalOverview | null>(null)
const sessions = ref<PortalSession[]>([])
const result = ref<ShipmentResult | null>(null)
const query = ref('')
const loading = ref(false)
const overviewLoading = ref(true)
const loadError = ref('')
const queryError = ref('')
const lookupNotice = ref('')
const activeConversationId = ref<string | null>(null)
const selectedEnterpriseId = ref<string>('')

const view = computed(() => {
  if (route.name === 'portal-lookup') return 'lookup'
  if (route.name === 'portal-sessions') return 'sessions'
  if (route.name === 'portal-settings') return 'settings'
  return 'overview'
})

const pageTitle = computed(() => ({ overview: '概览', lookup: '业务查询', sessions: '我的会话', settings: '账号与绑定' })[view.value])
const displayName = computed(() => overview.value?.user.name || userStore.name)
const enterprises = computed(() => overview.value?.enterprises || [])
// A user with several memberships must state which enterprise a question is
// about; the server refuses to guess, so the scope comes from this selection.
const needsEnterpriseChoice = computed(() => enterprises.value.length > 1)
const activeEnterprise = computed(() => {
  if (overview.value?.enterprise) return overview.value.enterprise
  return enterprises.value.find((item) => item.id === selectedEnterpriseId.value) || null
})
const enterpriseName = computed(() => activeEnterprise.value?.name || '暂无授权企业范围')
const customerCode = computed(() => activeEnterprise.value?.customerCode || '—')
const permissions = computed(() => activeEnterprise.value?.permissions || [])
const hasEnterprise = computed(() => Boolean(activeEnterprise.value))

onMounted(async () => {
  try {
    overview.value = await getPortalOverview()
    sessions.value = overview.value.sessions
    userStore.setUserInfo(overview.value.user.name, '')
    const conversationId = typeof route.query.conversationId === 'string' ? route.query.conversationId : ''
    if (route.name === 'portal-lookup' && conversationId) {
      await restoreSession(conversationId)
    }
  } catch {
    loadError.value = '暂时无法加载工作区，请稍后重试。'
  } finally {
    overviewLoading.value = false
  }
})

const restoreSession = async (conversationId: string) => {
  loading.value = true
  queryError.value = ''
  lookupNotice.value = ''
  try {
    const detail = await getPortalSession(conversationId)
    activeConversationId.value = conversationId
    result.value = detail.result
    query.value = detail.result?.query || detail.conversation.query || ''
    if (!detail.result) lookupNotice.value = '该会话还没有已完成的查询结果。'
  } catch {
    result.value = null
    queryError.value = '会话暂时无法恢复，请稍后重试。'
  } finally {
    loading.value = false
  }
}

const submitLookup = async () => {
  queryError.value = ''
  if (!query.value.trim()) {
    queryError.value = '请输入提单号或箱号'
    return
  }
  if (!hasEnterprise.value) {
    queryError.value = needsEnterpriseChoice.value
      ? '请先选择本次查询的企业范围。'
      : '当前账号没有授权企业范围，请联系平台管理员。'
    return
  }
  loading.value = true
  result.value = null
  lookupNotice.value = ''
  try {
    if (import.meta.env.VITE_PLATFORM_USE_MOCK === 'true') {
      result.value = await lookupShipment(query.value, activeConversationId.value)
    } else {
      const receipt = await submitWebInbound(
        query.value,
        activeConversationId.value,
        undefined,
        activeEnterprise.value?.id,
      )
      let status = await getWebInboundStatus(receipt.inboundMessageId)
      for (let attempt = 0; attempt < 40 && !status.conversationId; attempt += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, 250))
        status = await getWebInboundStatus(receipt.inboundMessageId)
        if (status.taskStatus === 'failed' || status.replyStatus === 'failed') throw new Error('web channel task failed')
      }
      if (!status.conversationId) throw new Error('web channel task timeout')
      const detail = await getPortalSession(status.conversationId)
      if (!detail.result) throw new Error('web channel result unavailable')
      result.value = detail.result
    }
    if (!result.value) throw new Error('查询结果为空')
    activeConversationId.value = result.value.conversationId
    await router.replace({ path: '/portal/lookup', query: { conversationId: activeConversationId.value } })
    try {
      sessions.value = await getPortalSessions()
    } catch {
      // The lookup result remains useful even if the session list refresh fails.
    }
  } catch {
    queryError.value = '查询暂时不可用，请稍后重试。'
  } finally {
    loading.value = false
  }
}

const openLookup = async (value = '', conversationId: string | null = null) => {
  query.value = value
  activeConversationId.value = conversationId
  queryError.value = ''
  lookupNotice.value = ''
  await router.push({ path: '/portal/lookup', query: conversationId ? { conversationId } : undefined })
  if (conversationId) {
    await restoreSession(conversationId)
  } else if (value) {
    await submitLookup()
  }
}

const refresh = async () => {
  loadError.value = ''
  overviewLoading.value = true
  try {
    overview.value = await getPortalOverview()
    sessions.value = overview.value.sessions
  } catch {
    loadError.value = '刷新失败，请检查网络连接。'
  } finally {
    overviewLoading.value = false
  }
}

const handleLogout = () => logout(() => router.replace({ name: 'login' }))

const statusLabel = (status: string) => ({ healthy: '运行正常', degraded: '有延迟', offline: '暂不可用' })[status] || status
const statusClass = (status: string) => `status-${status}`
const resultStatusLabel = (status: ShipmentResult['status']) => ({
  found: '已核实',
  not_found: '未找到',
  needs_clarification: '需要补充',
  upstream_error: '上游暂不可用',
}[status] || '查询结果')
const resultStatusClass = (status: ShipmentResult['status']) => `result-status--${status}`
</script>

<template>
  <PlatformShell mode="portal" :title="pageTitle" @logout="handleLogout">
    <div v-if="loadError" class="inline-alert inline-alert--warning" role="alert"><ErrorCircleIcon />{{ loadError }}<button type="button" @click="refresh"><RefreshIcon />重试</button></div>

    <div v-if="overviewLoading" class="page-loading" role="status"><span class="loading-ring"></span><strong>正在加载工作区</strong></div>

    <template v-else-if="view === 'overview'">
      <section class="portal-intro">
        <div>
          <p class="eyebrow">客户业务门户 / 2026 年 09 月 05 日</p>
          <h1>你好，{{ displayName }}<span class="title-dot">。</span></h1>
          <p class="intro-copy">在授权范围内查询货物状态、船期和关键节点。每个结论都附带可追溯的业务证据。</p>
        </div>
        <button class="subtle-button" @click="refresh"><RefreshIcon />刷新数据</button>
      </section>

      <section class="scope-strip">
        <div class="scope-icon"><LockOnIcon /></div>
        <div><span class="scope-label">当前数据范围</span><strong>{{ enterpriseName }}</strong></div>
        <span class="scope-divider"></span>
        <div><span class="scope-label">M3 客户编码</span><strong>{{ customerCode }}</strong></div>
        <div class="scope-permissions"><span v-for="permission in permissions" :key="permission">{{ permission }}</span><span v-if="!permissions.length" class="scope-empty">未配置查询权限</span></div>
      </section>

      <section class="lookup-hero">
        <div class="lookup-hero-copy"><span class="section-kicker">从这里开始</span><h2>查一票货物</h2><p>输入提单号或箱号，获取当前企业授权范围内的最新信息。</p></div>
        <label v-if="needsEnterpriseChoice" class="scope-picker">
          <span>本次查询的企业范围</span>
          <select v-model="selectedEnterpriseId" aria-label="选择企业范围">
            <option value="">请选择企业</option>
            <option v-for="item in enterprises" :key="item.id" :value="item.id">{{ item.name }}</option>
          </select>
        </label>
        <form class="lookup-form" @submit.prevent="openLookup(query)">
          <SearchIcon class="lookup-form-icon" />
          <input v-model="query" aria-label="提单号或箱号" placeholder="例如：EGLV123456789" :disabled="!hasEnterprise" />
          <button type="submit" :class="{ 'is-loading': loading }" :disabled="loading || !hasEnterprise">{{ loading ? '查询中…' : hasEnterprise ? '开始查询' : '暂无授权' }}<ArrowRightIcon /></button>
        </form>
        <span class="form-hint"><CloudIcon />{{ hasEnterprise ? '数据来自 M3 只读查询网关 · 不保存平台外的业务数据' : needsEnterpriseChoice ? '您可访问多个企业，请先选择本次查询的企业范围' : '当前账号没有可查询的企业范围，请联系平台管理员' }}</span>
      </section>

      <section class="metric-grid">
        <article class="metric-card"><span class="metric-label">活跃中的货物</span><strong>{{ overview?.stats.activeShipments ?? '—' }}</strong><span class="metric-note">{{ overview?.stats.activeShipments === null ? '尚未接入统计' : '当前授权范围' }}</span></article>
        <article class="metric-card"><span class="metric-label">待确认节点</span><strong>{{ overview?.stats.pendingMilestones ?? '—' }}</strong><span class="metric-note metric-note--attention">需要关注的节点</span></article>
        <article class="metric-card"><span class="metric-label">近 30 天查询</span><strong>{{ overview?.stats.recentQueries ?? '—' }}</strong><span class="metric-note">全部查询均可追溯</span></article>
      </section>

      <section class="portal-columns">
        <div class="panel-block sessions-panel"><div class="panel-heading"><div><span class="section-kicker">最近活动</span><h2>我的会话</h2></div><RouterLink to="/portal/sessions">查看全部<ChevronRightIcon /></RouterLink></div>
          <div v-if="sessions.length" class="session-list"><button v-for="session in sessions.slice(0, 3)" :key="session.id" class="session-row" @click="openLookup(session.query || '', session.id)"><span class="session-type"><FileSearchIcon /></span><span class="session-main"><strong>{{ session.title }}</strong><small>{{ session.preview }}</small></span><span class="session-meta"><span>{{ session.updatedAt }}</span><span v-if="session.evidence" class="evidence-chip"><CheckCircleIcon />有证据</span></span></button></div>
          <div v-else class="empty-state"><FileSearchIcon /><p>还没有查询会话</p><button @click="openLookup()">发起第一次查询</button></div>
        </div>
        <div class="panel-block service-panel"><div class="panel-heading"><div><span class="section-kicker">运行状态</span><h2>服务健康度</h2></div><span class="service-time">实时</span></div>
          <div v-if="overview?.services.length" class="service-list"><div v-for="service in overview.services" :key="service.name" class="service-row"><span class="service-icon"><ServerIcon /></span><span class="service-main"><strong>{{ service.name }}</strong><small>{{ service.detail }}</small></span><span class="service-status" :class="statusClass(service.status)"><i></i>{{ statusLabel(service.status) }}</span></div></div>
          <div v-else class="panel-empty">服务状态尚未接入</div>
          <div class="evidence-note"><CheckCircleIcon /><span>业务结论只引用已核实的 M3 返回值。</span></div>
        </div>
      </section>
    </template>

    <template v-else-if="view === 'lookup'">
      <section class="page-heading"><div><p class="eyebrow">客户业务门户 / 查询中心</p><h1>业务查询</h1><p>输入一个业务标识，平台会在你的授权范围内检索 M3 数据。</p></div><div class="heading-badge"><LockOnIcon />仅限当前企业</div></section>
      <section class="lookup-workspace">
        <form class="lookup-form lookup-form--large" @submit.prevent="submitLookup"><SearchIcon class="lookup-form-icon" /><input v-model="query" aria-label="提单号或箱号" placeholder="提单号、箱号或其他已授权业务标识" :disabled="!hasEnterprise" /><button type="submit" :disabled="loading || !hasEnterprise"><span class="lookup-submit-label"><span class="lookup-submit-label-full">{{ loading ? '查询中…' : hasEnterprise ? '开始查询' : '暂无授权' }}</span><span class="lookup-submit-label-short">{{ loading ? '查询中' : hasEnterprise ? '查询' : '无授权' }}</span></span><ArrowRightIcon /></button></form>
        <p v-if="lookupNotice" class="lookup-notice"><FileSearchIcon />{{ lookupNotice }}</p>
        <p v-if="queryError" class="field-error"><ErrorCircleIcon />{{ queryError }}</p>
        <div class="query-examples"><span>试试：</span><button type="button" @click="query = 'EGLV123456789'">EGLV123456789</button><button type="button" @click="query = 'UNKNOWN-001'">查询无记录示例</button></div>
      </section>
      <section v-if="loading" class="result-state result-state--loading"><span class="loading-ring"></span><strong>正在核实业务数据</strong><p>平台正在调用受控 M3 查询工具，请稍候。</p></section>
      <section v-else-if="result" class="result-section"><div class="result-header"><div><span class="section-kicker">查询结果 / {{ result.query }}</span><h2>{{ result.title }}</h2><p>{{ result.summary }}</p></div><span class="result-status" :class="resultStatusClass(result.status)"><CheckCircleIcon v-if="result.status === 'found'" /><SearchIcon v-else-if="result.status === 'needs_clarification'" /><ErrorCircleIcon v-else />{{ resultStatusLabel(result.status) }}</span></div><div v-if="result.evidence.length" class="evidence-table"><div class="evidence-table-head"><span>业务字段</span><span>当前值</span><span>来源与时间</span></div><div v-for="item in result.evidence" :key="item.label" class="evidence-row"><span class="evidence-label">{{ item.label }}</span><strong :class="{ unknown: !item.known }">{{ item.value }}</strong><span class="evidence-source"><span>{{ item.source }}</span><small>{{ item.capturedAt }}</small></span></div></div><div v-else class="result-empty">当前结果没有可展示的证据字段。</div><div class="trace-line"><LinkIcon />本次查询 Trace ID：<code>{{ result.traceId }}</code><span>·</span><span>结果仅对当前会话可见</span></div></section>
      <section v-else class="result-state result-state--empty"><div class="empty-icon"><SearchIcon /></div><strong>等待一次查询</strong><p>业务结论会在这里展示，并标注每个字段的真实来源。</p><button type="button" @click="submitLookup" :disabled="!query.trim() || !hasEnterprise">提交当前查询</button></section>
    </template>

    <template v-else-if="view === 'sessions'">
      <section class="page-heading"><div><p class="eyebrow">客户业务门户 / 工作记录</p><h1>我的会话</h1><p>你的查询记录只对当前账号可见，不会与同企业其他成员共享。</p></div><button class="subtle-button" @click="openLookup()"><SearchIcon />发起查询</button></section>
      <section class="sessions-page panel-block"><div class="list-toolbar"><span>{{ sessions.length }} 个会话</span><span class="list-sort-label"><TimeIcon />按最近更新</span></div><div v-if="sessions.length" class="session-list session-list--full"><button v-for="session in sessions" :key="session.id" class="session-row" @click="openLookup(session.query || '', session.id)"><span class="session-type"><FileSearchIcon /></span><span class="session-main"><strong>{{ session.title }}</strong><small>{{ session.preview }}</small></span><span class="session-meta"><span>{{ session.channel }} · {{ session.updatedAt }}</span><span v-if="session.evidence" class="evidence-chip"><CheckCircleIcon />有证据</span><ChevronRightIcon /></span></button></div><div v-else class="panel-empty">还没有查询会话</div></section>
    </template>

    <template v-else>
      <section class="page-heading"><div><p class="eyebrow">客户业务门户 / 访问控制</p><h1>账号与绑定</h1><p>查看当前账号的身份状态和渠道绑定。修改权限请联系销售或平台管理员。</p></div></section>
      <section class="settings-grid"><article class="settings-card"><div class="settings-card-heading"><span class="settings-symbol"><LockOnIcon /></span><div><span class="section-kicker">平台身份</span><h2>账号状态</h2></div><span class="account-status">{{ overview?.user.status === 'disabled' ? '已停用' : '正常' }}</span></div><dl><div><dt>登录手机号</dt><dd>{{ overview?.user.phone || '—' }}</dd></div><div><dt>账号角色</dt><dd>{{ overview?.user.roleLabel || '—' }}</dd></div><div><dt>所属企业</dt><dd>{{ enterpriseName }}</dd></div></dl></article><article class="settings-card"><div class="settings-card-heading"><span class="settings-symbol"><LinkIcon /></span><div><span class="section-kicker">渠道身份</span><h2>已绑定入口</h2></div><span class="account-status">未接入</span></div><div class="binding-row"><span class="binding-logo">—</span><span><strong>渠道绑定信息</strong><small>后端尚未提供绑定记录</small></span><span class="binding-state binding-state--muted">尚未接入</span></div><div class="binding-help">需要接入微信服务号或企业微信？请联系你的客户经理完成身份绑定。</div></article></section>
    </template>
  </PlatformShell>
</template>

<style scoped>
.portal-intro, .page-heading { display: flex; justify-content: space-between; align-items: flex-end; gap: 24px; margin-bottom: 25px; }
.eyebrow, .section-kicker { margin: 0 0 9px; font-size: 10px; letter-spacing: .13em; text-transform: uppercase; color: #7b8c89; font-weight: 700; }
h1 { margin: 0; font-size: 31px; line-height: 1.18; font-weight: 740; color: #142322; }
.title-dot { color: #147d72; }
.intro-copy, .page-heading p:not(.eyebrow) { margin: 10px 0 0; color: #72827f; font-size: 13px; max-width: 580px; }
.subtle-button { min-height: 44px; display: inline-flex; align-items: center; gap: 8px; padding: 0 13px; background: white; border: 1px solid #d8e3e0; border-radius: 6px; color: #45615d; cursor: pointer; font-weight: 600; font-size: 12px; }
.subtle-button:hover { border-color: #91bcb3; color: #147d72; }
.subtle-button :deep(svg) { width: 16px; }
.scope-strip { display: flex; align-items: center; gap: 14px; border-top: 1px solid #dbe6e2; border-bottom: 1px solid #dbe6e2; min-height: 70px; padding: 11px 0; margin-bottom: 25px; }
.scope-icon { width: 34px; height: 34px; border-radius: 7px; display: grid; place-items: center; background: #dceee9; color: #147d72; }
.scope-icon :deep(svg) { width: 18px; }
.scope-strip strong, .scope-strip span { display: block; }
.scope-strip strong { font-size: 12px; margin-top: 4px; max-width: 330px; }
.scope-label { color: #86938f; font-size: 10px; }
.scope-divider { width: 1px; height: 32px; background: #dbe6e2; margin: 0 13px; }
.scope-permissions { margin-left: auto; display: flex; gap: 6px; flex-wrap: wrap; justify-content: flex-end; }
.scope-permissions span { display: inline-flex; padding: 5px 8px; border-radius: 4px; background: #f0f5f3; color: #5d7771; font-size: 10px; }
.scope-permissions .scope-empty { color: #987046; background: #fff5e6; }
.lookup-hero { background: #e5f1ed; border: 1px solid #d4e6df; padding: 26px 28px 22px; margin-bottom: 19px; }
.lookup-hero h2, .panel-heading h2, .result-header h2, .settings-card h2 { margin: 0; font-size: 20px; color: #17312e; }
.lookup-hero p { margin: 6px 0 18px; color: #5d7972; font-size: 12px; }
.lookup-form { height: 48px; display: flex; align-items: center; border: 1px solid #bdd8d0; background: #fff; border-radius: 6px; padding-left: 14px; max-width: 740px; }
.scope-picker { display: flex; flex-direction: column; gap: 6px; max-width: 320px; margin-bottom: 12px; }
.scope-picker span { color: #4a635e; font-size: 12px; font-weight: 600; }
.scope-picker select { height: 38px; border: 1px solid #bdd8d0; border-radius: 6px; background: #fff; padding: 0 10px; color: #17312e; font: inherit; font-size: 13px; }
.scope-picker select:focus-visible { outline: 2px solid #147d72; outline-offset: 1px; }
.lookup-form:focus-within { border-color: #147d72; box-shadow: 0 0 0 3px rgba(20,125,114,.12); }
.lookup-form-icon { width: 18px; color: #8a9f9a; flex: 0 0 auto; }
.lookup-form input { min-width: 0; flex: 1; height: 100%; border: 0; outline: 0; background: transparent; padding: 0 12px; color: #17312e; font: inherit; font-size: 13px; }
.lookup-form button { height: 100%; display: inline-flex; align-items: center; gap: 8px; border: 0; background: #147d72; color: white; padding: 0 17px; border-radius: 0 5px 5px 0; font-size: 12px; font-weight: 650; cursor: pointer; }
.lookup-form button:hover { background: #0f685f; }
.lookup-form button:disabled { opacity: .6; cursor: not-allowed; }
.lookup-form button.is-loading { cursor: wait; }
.lookup-form button :deep(svg) { width: 15px; }
.form-hint { margin-top: 10px; display: flex; align-items: center; gap: 6px; color: #78918b; font-size: 10px; }
.form-hint :deep(svg) { width: 13px; }
.metric-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; margin-bottom: 24px; }
.metric-card { border: 1px solid #e0e7e5; background: #fff; min-height: 119px; padding: 17px 18px; }
.metric-label, .metric-note { display: block; color: #7a8a87; font-size: 11px; }
.metric-card strong { display: block; font-size: 29px; color: #17312e; margin: 8px 0 6px; }
.metric-note--attention { color: #a36c31; }
.metric-up { color: #218469; font-weight: 700; }
.portal-columns { display: grid; grid-template-columns: minmax(0, 1.25fr) minmax(0, .9fr); gap: 18px; }
.panel-block { border: 1px solid #e0e7e5; background: #fff; }
.panel-heading { display: flex; align-items: flex-start; justify-content: space-between; padding: 20px 20px 14px; }
.panel-heading a { display: inline-flex; align-items: center; gap: 3px; color: #147d72; font-size: 11px; text-decoration: none; }
.panel-heading a :deep(svg) { width: 14px; }
.session-list { border-top: 1px solid #edf1f0; }
.session-row { width: 100%; display: flex; align-items: center; gap: 12px; min-height: 70px; border: 0; border-bottom: 1px solid #edf1f0; background: transparent; padding: 11px 20px; text-align: left; cursor: pointer; }
.session-row:last-child { border-bottom: 0; }
.session-row:hover { background: #f7faf9; }
.session-type { display: grid; place-items: center; width: 30px; height: 30px; border-radius: 6px; background: #eef5f2; color: #568077; flex: 0 0 30px; }
.session-type :deep(svg) { width: 16px; }
.session-main { min-width: 0; flex: 1; }
.session-main strong, .session-main small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.session-main strong { color: #213d39; font-size: 12px; font-weight: 650; }
.session-main small { color: #7d8c89; font-size: 10px; margin-top: 4px; }
.session-meta { display: flex; flex-direction: column; align-items: flex-end; gap: 5px; color: #91a09d; font-size: 10px; white-space: nowrap; }
.evidence-chip { display: inline-flex; align-items: center; gap: 3px; color: #36816c; font-size: 10px; }
.evidence-chip :deep(svg) { width: 12px; }
.service-time { color: #31816d; background: #e5f2ed; padding: 4px 7px; font-size: 10px; border-radius: 4px; }
.service-list { padding: 0 20px; }
.service-row { min-height: 58px; display: flex; align-items: center; gap: 11px; border-bottom: 1px solid #edf1f0; }
.service-icon { color: #66847c; display: grid; place-items: center; width: 26px; }
.service-icon :deep(svg) { width: 17px; }
.service-main { min-width: 0; flex: 1; }
.service-main strong, .service-main small { display: block; }
.service-main strong { font-size: 11px; color: #29423f; }
.service-main small { color: #899894; font-size: 10px; margin-top: 2px; }
.service-status { display: flex; align-items: center; gap: 5px; font-size: 10px; color: #66817a; }
.service-status i { width: 6px; height: 6px; border-radius: 50%; background: #39a77e; }
.service-status.status-degraded { color: #a16e38; }.service-status.status-degraded i { background: #d29143; }.service-status.status-offline { color: #a34f4f; }.service-status.status-offline i { background: #bc5c5c; }
.evidence-note { display: flex; align-items: center; gap: 7px; margin: 16px 20px 18px; padding: 10px; background: #f2f8f5; color: #598075; font-size: 10px; }
.evidence-note :deep(svg) { color: #338871; width: 15px; flex: 0 0 auto; }
.inline-alert { display: flex; align-items: center; gap: 8px; margin-bottom: 18px; padding: 11px 13px; border: 1px solid #e7d7bc; background: #fff9ed; color: #876236; font-size: 12px; }.inline-alert :deep(svg) { width: 16px; }.inline-alert button { min-height: 44px; margin: -11px -5px -11px auto; padding: 0 8px; border: 0; background: transparent; color: #8f642e; display: flex; align-items: center; gap: 5px; cursor: pointer; }.inline-alert button :deep(svg) { width: 14px; }
.page-loading { min-height: 300px; display: grid; place-items: center; align-content: center; gap: 12px; color: #71827e; font-size: 12px; }
.page-loading .loading-ring { display: block; }
.page-heading { align-items: flex-start; }.heading-badge { display: inline-flex; align-items: center; gap: 7px; border: 1px solid #d6e7e1; color: #548077; background: #eff7f4; padding: 8px 10px; font-size: 11px; }.heading-badge :deep(svg) { width: 15px; }
.lookup-workspace { border: 1px solid #e0e7e5; background: #f6faf8; padding: 24px; }.lookup-form--large { max-width: 100%; background: white; }.query-examples { display: flex; gap: 9px; align-items: center; margin-top: 12px; color: #7c8d89; font-size: 10px; }.query-examples button { min-height: 44px; border: 0; background: transparent; color: #317c70; font-size: 10px; cursor: pointer; padding: 0 4px; }.field-error { display: flex; align-items: center; gap: 6px; margin: 9px 0 0; color: #a24e4e; font-size: 11px; }.field-error :deep(svg) { width: 14px; }
.result-section { margin-top: 20px; border: 1px solid #dfe8e4; background: #fff; }.result-header { display: flex; justify-content: space-between; gap: 20px; padding: 22px 24px 18px; border-bottom: 1px solid #edf1f0; }.result-header p { margin: 7px 0 0; color: #778985; font-size: 12px; }.result-status { display: inline-flex; align-items: center; gap: 5px; height: 27px; padding: 0 9px; font-size: 10px; white-space: nowrap; }.result-status--found { color: #2e7f6a; background: #e7f5ef; }.result-status--not_found { color: #97632f; background: #fff5e6; }.result-status--needs_clarification { color: #7a6298; background: #f3eef9; }.result-status--upstream_error { color: #a24e4e; background: #fff0f0; }.result-status :deep(svg) { width: 14px; }.evidence-table-head, .evidence-row { display: grid; grid-template-columns: 1fr 1.55fr 1.35fr; gap: 16px; align-items: center; }.evidence-table-head { padding: 11px 24px; background: #f7faf9; color: #849390; font-size: 10px; }.evidence-row { min-height: 60px; padding: 11px 24px; border-top: 1px solid #edf1f0; }.evidence-label { color: #667874; font-size: 11px; }.evidence-row strong { color: #27433e; font-size: 12px; }.evidence-row strong.unknown { color: #9aa7a3; font-weight: 500; }.evidence-source span, .evidence-source small { display: block; }.evidence-source span { color: #58746c; font-size: 10px; }.evidence-source small { color: #9aa6a3; font-size: 9px; margin-top: 3px; }.trace-line { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; color: #869692; font-size: 10px; padding: 13px 24px; background: #fbfcfb; }.trace-line :deep(svg) { width: 14px; color: #6d8e86; }.trace-line code { color: #547a72; background: #eff5f2; padding: 2px 4px; }.result-empty, .panel-empty { padding: 24px; color: #879792; font-size: 11px; text-align: center; }.lookup-notice { display: flex; align-items: center; gap: 6px; margin: 10px 0 0; color: #7a684e; font-size: 11px; }.lookup-notice :deep(svg) { width: 14px; }.result-state { margin-top: 20px; min-height: 260px; border: 1px dashed #d4e3df; display: grid; place-items: center; align-content: center; color: #71827e; text-align: center; }.result-state strong { color: #35534d; font-size: 14px; margin-top: 12px; }.result-state p { margin: 5px 0 0; font-size: 11px; }.empty-icon { width: 42px; height: 42px; display: grid; place-items: center; background: #eef5f2; color: #689088; border-radius: 50%; }.empty-icon :deep(svg) { width: 20px; }.loading-ring { width: 28px; height: 28px; border: 2px solid #d8e9e4; border-top-color: #147d72; border-radius: 50%; animation: spin .8s linear infinite; }.result-state--loading strong { margin-top: 15px; }@keyframes spin { to { transform: rotate(360deg); } }
.sessions-page { margin-top: 20px; }.list-toolbar { min-height: 52px; display: flex; justify-content: space-between; align-items: center; padding: 0 20px; color: #788985; font-size: 11px; border-bottom: 1px solid #e8efec; }.list-toolbar button { display: flex; gap: 5px; align-items: center; border: 0; background: transparent; color: #648078; font-size: 10px; }.list-toolbar button :deep(svg) { width: 14px; }.session-list--full .session-row { min-height: 84px; padding: 16px 20px; }.session-list--full .session-meta { flex-direction: row; align-items: center; gap: 12px; }.session-list--full .session-meta > svg { width: 15px; color: #9aaba6; }
.settings-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 18px; margin-top: 21px; }.settings-card { border: 1px solid #e0e7e5; background: #fff; padding: 22px; }.settings-card-heading { display: flex; align-items: center; gap: 11px; padding-bottom: 18px; border-bottom: 1px solid #edf1f0; }.settings-symbol { display: grid; place-items: center; width: 34px; height: 34px; background: #e7f3ef; color: #397e70; border-radius: 6px; }.settings-symbol :deep(svg) { width: 18px; }.settings-card-heading h2 { font-size: 16px; }.account-status { margin-left: auto; color: #33816d; background: #e8f5ef; padding: 4px 7px; font-size: 10px; }.settings-card dl { margin: 0; }.settings-card dl div { display: flex; justify-content: space-between; gap: 15px; padding: 13px 0; border-bottom: 1px solid #f0f3f2; }.settings-card dl div:last-child { border-bottom: 0; }.settings-card dt { color: #8a9895; font-size: 11px; }.settings-card dd { margin: 0; color: #34514b; font-size: 11px; text-align: right; }.binding-row { display: flex; align-items: center; gap: 11px; padding: 21px 0 18px; }.binding-logo { width: 32px; height: 32px; display: grid; place-items: center; color: #fff; background: #1c4d46; border-radius: 7px; font-weight: 800; }.binding-row strong, .binding-row small { display: block; }.binding-row strong { color: #34514b; font-size: 12px; }.binding-row small { color: #899994; font-size: 10px; margin-top: 4px; }.binding-state { display: inline-flex; align-items: center; gap: 4px; margin-left: auto; color: #35816d; font-size: 10px; }.binding-state :deep(svg) { width: 13px; }.binding-help { padding: 12px; background: #f4f8f6; color: #71827d; font-size: 10px; line-height: 1.6; }
@media (max-width: 800px) { .portal-columns, .settings-grid { grid-template-columns: minmax(0, 1fr); }.scope-strip { flex-wrap: wrap; }.scope-divider { display: none; }.scope-permissions { width: 100%; margin-left: 48px; justify-content: flex-start; }.metric-grid { gap: 9px; }.metric-card { padding: 14px; }.metric-card strong { font-size: 24px; } }
@media (max-width: 560px) { .portal-intro, .page-heading { display: block; }.portal-intro .subtle-button, .page-heading .subtle-button { margin-top: 16px; }.portal-intro h1, h1 { font-size: 26px; }.scope-strip { align-items: flex-start; }.scope-strip strong { max-width: 240px; }.lookup-hero { padding: 21px 16px 17px; }.lookup-form { height: 46px; }.lookup-form button { padding: 0 11px; }.lookup-form button { font-size: 0; }.lookup-form button :deep(svg) { width: 17px; }.metric-grid { grid-template-columns: 1fr; }.metric-card { min-height: 88px; }.metric-card strong { display: inline-block; margin-right: 8px; }.portal-columns { gap: 14px; }.session-row { padding: 11px 13px; gap: 8px; }.session-meta > span:first-child { display: none; }.result-header { display: block; padding: 19px 16px 16px; }.result-status { margin-top: 13px; }.evidence-table-head, .evidence-row { grid-template-columns: 1fr 1.35fr; gap: 8px; padding-left: 16px; padding-right: 16px; }.evidence-table-head span:last-child, .evidence-row .evidence-source { display: none; }.lookup-workspace { padding: 16px; }.query-examples { flex-wrap: wrap; }.settings-card { padding: 17px; } }
.result-state { padding: 24px 16px; }
.result-state button, .empty-state button { min-height: 44px; margin-top: 16px; padding: 0 14px; border: 1px solid #b8d6ce; border-radius: 6px; background: #fff; color: #28776d; font-size: 11px; font-weight: 650; cursor: pointer; }
.result-state button:hover, .empty-state button:hover { border-color: #147d72; background: #f3faf7; }
.result-state button:disabled { cursor: not-allowed; opacity: .55; }
.lookup-submit-label-short { display: none; }
.list-sort-label { display: inline-flex; gap: 5px; align-items: center; color: #648078; font-size: 10px; }
.list-sort-label :deep(svg) { width: 14px; }
:where(button, a, input):focus-visible { outline: 3px solid rgba(20, 125, 114, .3); outline-offset: 2px; }
@media (max-width: 560px) {
  .lookup-form button { min-width: 64px; padding: 0 9px; font-size: 11px; }
  .lookup-submit-label-full { display: none; }
  .lookup-submit-label-short { display: inline; }
  .lookup-form button :deep(svg) { width: 15px; }
}
</style>
