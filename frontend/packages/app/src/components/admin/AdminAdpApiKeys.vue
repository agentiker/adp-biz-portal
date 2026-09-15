<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { listAdpApiKeys, createAdpApiKey, revokeAdpApiKey } from '@/platform/platformService'
import type { AdpApiKey } from '@/platform/types'
const keys = ref<AdpApiKey[]>([])
const name = ref('')
const secret = ref('')
const busy = ref(false)
const error = ref('')
const copied = ref(false)
async function load() { keys.value = await listAdpApiKeys() }
async function refresh() {
  busy.value = true; error.value = ''
  try { await load() } catch { error.value = 'API Key 列表加载失败，请重试。' }
  finally { busy.value = false }
}
async function create() {
  busy.value = true; error.value = ''; copied.value = false
  try {
    const result = await createAdpApiKey(name.value.trim())
    secret.value = result.apiKey; name.value = ''
    await load()
  } catch { error.value = secret.value ? 'Key 已创建，列表刷新失败。请先保存下方 Key。' : '创建失败，请刷新列表后重试。' }
  finally { busy.value = false }
}
async function revoke(key: AdpApiKey) {
  if (!window.confirm(`撤销「${key.name}」后，使用此 Key 的连接器将无法调用工具。确认撤销？`)) return
  busy.value = true; error.value = ''
  try { await revokeAdpApiKey(key.id); await load() }
  catch { error.value = '撤销或刷新失败，请刷新列表确认状态。' }
  finally { busy.value = false }
}
async function copy() {
  try { await navigator.clipboard.writeText(secret.value); copied.value = true }
  catch { error.value = '复制失败，请手动选中并复制 Key。' }
}
onMounted(refresh)
</script>

<template>
  <section class="keys-panel" aria-labelledby="connector-keys-title">
    <div class="heading"><h2 id="connector-keys-title">连接器 API Key</h2><button :disabled="busy" @click="refresh">刷新</button></div>
    <p>供 ADP 连接器调用业务工具。将 Key 保存到连接器安全凭据，Header 为 <code>X-ADP-Service-Token</code>。每轮调用仍需执行上下文。</p>
    <form @submit.prevent="create"><label for="connector-key-name">Key 名称</label><input id="connector-key-name" v-model="name" maxlength="128" required placeholder="例如：生产 ADP 连接器" :disabled="busy || !!secret" /><button :disabled="busy || !!secret || !name.trim()">创建 API Key</button></form>
    <p v-if="error" role="alert" class="error">{{ error }}</p>
    <div v-if="secret" class="secret" role="status"><strong>仅显示一次，请立即保存</strong><p>关闭后无法再次查看。轮换时，先配置新 Key，再撤销旧 Key。</p><textarea :value="secret" readonly aria-label="新 API Key" spellcheck="false" /><div><button @click="copy">{{ copied ? '已复制' : '复制 Key' }}</button><button @click="secret = ''">已保存，关闭</button></div></div>
    <p v-if="busy">正在处理…</p>
    <p v-else-if="!keys.length">暂无 API Key，请创建后配置到 ADP 连接器。</p>
    <ul v-if="keys.length"><li v-for="key in keys" :key="key.id"><div><strong>{{ key.name }}</strong><small>{{ key.prefix }}… · {{ new Date(key.createdAt).toLocaleString('zh-CN') }}</small></div><span>{{ key.revokedAt ? '已撤销' : '有效' }}</span><button :disabled="busy || !!key.revokedAt" @click="revoke(key)">撤销</button></li></ul>
  </section>
</template>

<style scoped>
.keys-panel { margin-bottom: 20px; padding: 20px; border: 1px solid #e0e7e5; background: white; color: #31504a; }
.heading, form, li, .secret > div { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.heading { justify-content: space-between; } h2 { margin: 0; font-size: 19px; }
p, small { font-size: 12px; line-height: 1.7; color: #687e77; } button, input, textarea { padding: 9px 12px; border: 1px solid #cbdcd6; border-radius: 5px; background: white; color: #31504a; }
button { cursor: pointer; } button:disabled { opacity: .5; cursor: default; } input { min-width: 0; flex: 1; } ul { list-style: none; padding: 0; } li { border-top: 1px solid #edf1f0; padding: 14px 0; } li > div { flex: 1; } small { display: block; }
.secret { margin-top: 16px; padding: 16px; background: #eff9f4; } textarea { display: block; width: 100%; box-sizing: border-box; margin-bottom: 12px; overflow-wrap: anywhere; } .error { color: #a34231; } code { overflow-wrap: anywhere; }
</style>
