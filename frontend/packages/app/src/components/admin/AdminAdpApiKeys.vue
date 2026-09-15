<script setup lang="ts">
import { nextTick, onMounted, ref } from 'vue'
import { BrowseIcon, BrowseOffIcon, CopyIcon, AddIcon, RefreshIcon } from 'tdesign-icons-vue-next'
import { listAdpApiKeys, createAdpApiKey, revokeAdpApiKey, revealAdpApiKey, deleteAdpApiKey } from '@/platform/platformService'
import type { AdpApiKey } from '@/platform/types'
const keys = ref<AdpApiKey[]>([])
const name = ref('')
const showCreate = ref(false)
const nameInput = ref<HTMLInputElement | null>(null)
const createButton = ref<HTMLButtonElement | null>(null)
const visible = ref<Record<string, string>>({})
const busy = ref(false)
const pending = ref('')
const error = ref('')
const notice = ref('')
function trapFocus(event: KeyboardEvent) {
  const controls = Array.from((event.currentTarget as HTMLFormElement).querySelectorAll<HTMLElement>('input:not(:disabled), button:not(:disabled)'))
  const first = controls[0], last = controls[controls.length - 1]
  if (event.shiftKey && event.target === first) { event.preventDefault(); last?.focus() }
  else if (!event.shiftKey && event.target === last) { event.preventDefault(); first?.focus() }
}
async function load() { keys.value = await listAdpApiKeys() }
async function refresh() {
  busy.value = true; error.value = ''; visible.value = {}
  try { await load() } catch { error.value = 'API Key 列表加载失败，请重试。' }
  finally { busy.value = false }
}
async function openCreate() {
  name.value = ''; error.value = ''; showCreate.value = true
  await nextTick(); nameInput.value?.focus()
}
function closeCreate() { if (!busy.value) { showCreate.value = false; createButton.value?.focus() } }
async function create() {
  busy.value = true; error.value = ''; notice.value = ''
  try {
    const result = await createAdpApiKey(name.value.trim())
    const { apiKey: _secret, ...metadata } = result
    keys.value.unshift(metadata)
    showCreate.value = false; name.value = ''; notice.value = 'API Key 已创建'
    createButton.value?.focus()
  } catch { error.value = '创建失败，请重试。' }
  finally { busy.value = false }
}
async function toggle(key: AdpApiKey) {
  if (visible.value[key.id]) { delete visible.value[key.id]; return }
  pending.value = key.id; error.value = ''
  try { visible.value[key.id] = (await revealAdpApiKey(key.id)).apiKey }
  catch { error.value = '无法读取 API Key，请刷新后重试。' }
  finally { pending.value = '' }
}
async function copy(key: AdpApiKey) {
  pending.value = key.id; error.value = ''; notice.value = ''
  try {
    const result = await revealAdpApiKey(key.id)
    await navigator.clipboard.writeText(result.apiKey)
    notice.value = `已复制「${key.name}」的 API Key`
  } catch { error.value = '复制失败，可点击小眼睛查看后手动复制。' }
  finally { pending.value = '' }
}
async function revoke(key: AdpApiKey) {
  if (!window.confirm(`确认撤销「${key.name}」？使用此 Key 的接口调用将无法通过鉴权。`)) return
  pending.value = key.id; error.value = ''
  try {
    const updated = await revokeAdpApiKey(key.id)
    keys.value = keys.value.map(row => row.id === key.id ? updated : row)
    delete visible.value[key.id]
  } catch { error.value = '撤销失败，请重试。' }
  finally { pending.value = '' }
}
async function remove(key: AdpApiKey) {
  if (!window.confirm(`确认删除「${key.name}」？删除后将从列表移除，该 Key 将无法继续调用接口。`)) return
  pending.value = key.id; error.value = ''; notice.value = ''
  try {
    await deleteAdpApiKey(key.id)
    keys.value = keys.value.filter(row => row.id !== key.id)
    delete visible.value[key.id]
    notice.value = 'API Key 已删除'
  } catch { error.value = '删除失败，请重试。' }
  finally { pending.value = '' }
}
onMounted(refresh)
</script>

<template>
  <header class="intro"><div><p class="eyebrow">运营控制台 / 开放接口</p><h1>开放接口</h1><p>管理接口访问凭据，供 ADP 连接器等已授权服务调用。</p></div><div class="actions"><button :disabled="busy || !!pending" @click="refresh"><RefreshIcon />刷新</button><button ref="createButton" class="primary" :disabled="busy" @click="openCreate"><AddIcon />新建 API Key</button></div></header>
  <p v-if="error && !showCreate" class="error" role="alert">{{ error }}</p><p v-if="notice" class="notice" role="status">{{ notice }}</p>
  <section class="panel" aria-label="API Key 列表"><div class="panel-heading"><h2>API Key</h2><span>{{ keys.length }} 个</span></div>
    <div class="table-scroll"><table><colgroup><col style="width:18%" /><col style="width:42%" /><col style="width:20%" /><col style="width:8%" /><col style="width:12%" /></colgroup><thead><tr><th>名字</th><th>API Key</th><th>创建时间</th><th>状态</th><th>操作</th></tr></thead><tbody>
      <tr v-for="key in keys" :key="key.id"><td class="name">{{ key.name }}</td><td><div class="key-cell"><code>{{ visible[key.id] || `${key.prefix}••••••••••••••••` }}</code><template v-if="key.canReveal"><button class="icon" :aria-label="visible[key.id] ? '隐藏 API Key' : '查看完整 API Key'" :title="visible[key.id] ? '隐藏' : '查看完整 API Key'" :disabled="!!pending || busy" @click="toggle(key)"><BrowseOffIcon v-if="visible[key.id]" /><BrowseIcon v-else /></button><button class="icon" aria-label="复制 API Key" title="复制 API Key" :disabled="!!pending || busy" @click="copy(key)"><CopyIcon /></button></template></div><small v-if="!key.canReveal">历史 Key 无法查看，请新建后替换</small></td><td class="date">{{ new Date(key.createdAt).toLocaleString('zh-CN', { hour12: false }) }}</td><td><span class="status" :class="{ revoked: key.revokedAt }">{{ key.revokedAt ? '已撤销' : '有效' }}</span></td><td><button class="danger" :disabled="busy || !!pending || !!key.revokedAt" @click="revoke(key)">撤销</button><button class="danger" :disabled="busy || !!pending" @click="remove(key)">删除</button></td></tr>
      <tr v-if="!keys.length"><td colspan="5" class="empty">{{ busy ? '正在加载…' : '暂无 API Key，点击「新建 API Key」创建。' }}</td></tr>
    </tbody></table></div>
  </section>
  <div v-if="showCreate" class="backdrop" @click.self="closeCreate" @keydown.esc="closeCreate"><form class="dialog" role="dialog" aria-modal="true" aria-labelledby="create-key-title" @submit.prevent="create" @keydown.tab="trapFocus"><h2 id="create-key-title">新建 API Key</h2><label for="api-key-name">API Key 名字</label><input id="api-key-name" ref="nameInput" v-model="name" maxlength="128" required placeholder="例如：生产 ADP 连接器" :disabled="busy" /><p v-if="error" class="error" role="alert">{{ error }}</p><div class="dialog-actions"><button type="button" :disabled="busy" @click="closeCreate">取消</button><button type="submit" class="primary" :disabled="busy || !name.trim()">{{ busy ? '创建中…' : '创建' }}</button></div></form></div>
</template>

<style scoped>
.intro,.actions,.panel-heading,.key-cell,.dialog-actions { display:flex; align-items:center; gap:12px; }.intro { justify-content:space-between; margin-bottom:28px; flex-wrap:wrap; }.eyebrow { font-size:10px; color:#7b8c89; letter-spacing:.1em; }h1 { margin:0; font-size:31px; color:#142322; }.intro p:last-child { font-size:13px; color:#72827f; }h2 { margin:0; font-size:18px; color:#17312e; }button,input { border:1px solid #d8e3e0; border-radius:6px; padding:9px 12px; color:#45615d; background:white; font:inherit; }button { display:inline-flex; align-items:center; justify-content:center; gap:6px; cursor:pointer; font-size:12px; }button:disabled { opacity:.45; cursor:default; }button svg { width:16px; height:16px; }.primary { background:#147d72; border-color:#147d72; color:white; }.panel { background:white; border:1px solid #e0e7e5; }.panel-heading { padding:20px; justify-content:space-between; }.panel-heading span,small { font-size:12px; color:#7b8c89; }.table-scroll { overflow-x:auto; }table { table-layout:fixed; min-width:1100px; width:100%; border-collapse:collapse; font-size:12px; text-align:left; }th { background:#f7faf9; color:#7b8c89; font-weight:500; }th,td { padding:16px 20px; border-top:1px solid #edf1f0; }.name { min-width:100px; max-width:220px; overflow-wrap:anywhere; font-weight:600; color:#31504a; }.date { white-space:nowrap; color:#72827f; }.key-cell { gap:6px; }code { display:block; flex:1; min-width:0; white-space:nowrap; overflow-x:auto; font-size:12px; scrollbar-width:none; }code::-webkit-scrollbar { display:none; }.key-cell .icon { flex-shrink:0; }.icon { padding:5px; border:0; background:transparent; }.status { display:inline-block; padding:4px 8px; border-radius:4px; background:#e8f5ef; color:#31816d; white-space:nowrap; }.revoked { background:#f0f2f1; color:#899892; }.danger { border:0; color:#ac5142; }.empty { text-align:center; padding:50px; color:#7b8c89; }.error { color:#a34231; font-size:13px; }.notice { color:#147d72; font-size:13px; }.backdrop { position:fixed; inset:0; background:#10272266; display:grid; place-items:center; z-index:100; padding:20px; }.dialog { background:white; padding:28px; border-radius:10px; width:min(420px,100%); box-sizing:border-box; box-shadow:0 20px 70px #10272233; }.dialog label { display:block; margin:24px 0 8px; color:#45615d; font-size:13px; }.dialog input { width:100%; box-sizing:border-box; }.dialog-actions { justify-content:flex-end; margin-top:24px; }:focus-visible { outline:2px solid #147d72; outline-offset:3px; }
</style>
