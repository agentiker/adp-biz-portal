<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { getSharedResult } from '@/platform/platformService'
import type { ShipmentResult } from '@/platform/generated'

const route = useRoute()
const loading = ref(true)
const errored = ref(false)
const result = ref<ShipmentResult | null>(null)

const STATUS_LABELS: Record<string, string> = {
  found: '已找到',
  not_found: '无记录',
  needs_clarification: '需澄清',
  upstream_error: '业务系统暂不可用',
}

onMounted(async () => {
  const token = typeof route.query.token === 'string' ? route.query.token : ''
  if (!token) {
    loading.value = false
    errored.value = true
    return
  }
  try {
    const response = await getSharedResult(token)
    result.value = response.result
  } catch {
    // Invalid, expired, or revoked links come back as 404 — one friendly state.
    errored.value = true
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <main class="shared-result">
    <section v-if="loading" class="state">
      <span class="ring"></span>
      <p>正在加载查询结果…</p>
    </section>

    <section v-else-if="errored || !result" class="state">
      <h1>链接无效或已过期</h1>
      <p>该结果链接可能已过期、被撤销，或无法访问。请回到对话重新发起查询。</p>
    </section>

    <section v-else class="card">
      <header class="card-head">
        <span class="kicker">查询结果 / {{ result.query }}</span>
        <h1>{{ result.title }}</h1>
        <span class="status" :class="result.status">{{ STATUS_LABELS[result.status] || result.status }}</span>
      </header>
      <p class="summary">{{ result.summary }}</p>

      <div v-if="result.evidence.length" class="evidence">
        <div class="evidence-head"><span>业务字段</span><span>当前值</span><span>来源</span></div>
        <div v-for="item in result.evidence" :key="item.label" class="evidence-row">
          <span class="label">{{ item.label }}</span>
          <strong :class="{ unknown: !item.known }">{{ item.value }}</strong>
          <span class="source">{{ item.source }}<small v-if="item.capturedAt">{{ item.capturedAt }}</small></span>
        </div>
      </div>
      <p v-else class="empty">当前结果没有可展示的业务字段。</p>

      <footer class="foot">结果只读，仅展示本次查询。业务结论只引用已核实的数据。</footer>
    </section>
  </main>
</template>

<style scoped>
.shared-result { max-width: 720px; margin: 0 auto; padding: 24px 16px; color: #1f2933; }
.state { text-align: center; padding: 48px 16px; color: #52606d; }
.state h1 { font-size: 20px; margin-bottom: 8px; color: #1f2933; }
.ring { display: inline-block; width: 28px; height: 28px; border: 3px solid #cbd2d9; border-top-color: #2f6feb; border-radius: 50%; animation: spin 0.8s linear infinite; margin-bottom: 12px; }
@keyframes spin { to { transform: rotate(360deg); } }
.card { border: 1px solid #e4e7eb; border-radius: 14px; padding: 20px; background: #fff; }
.card-head { display: flex; flex-direction: column; gap: 6px; margin-bottom: 12px; }
.kicker { font-size: 12px; letter-spacing: 0.04em; color: #7b8794; text-transform: uppercase; }
.card-head h1 { font-size: 20px; line-height: 1.3; }
.status { align-self: flex-start; font-size: 12px; padding: 2px 10px; border-radius: 999px; background: #eef2f7; color: #3e4c59; }
.status.found { background: #e3f9e5; color: #0b7a3b; }
.status.upstream_error { background: #fbeae5; color: #ab1a1a; }
.summary { white-space: pre-wrap; line-height: 1.6; color: #3e4c59; margin-bottom: 16px; }
.evidence { border: 1px solid #eef2f7; border-radius: 10px; overflow: hidden; }
.evidence-head, .evidence-row { display: grid; grid-template-columns: 1fr 1.2fr 1fr; gap: 8px; padding: 10px 12px; }
.evidence-head { background: #f5f7fa; font-size: 12px; color: #7b8794; }
.evidence-row { border-top: 1px solid #eef2f7; align-items: center; }
.evidence-row .label { color: #52606d; }
.evidence-row strong.unknown { color: #9aa5b1; font-weight: 500; }
.evidence-row .source { font-size: 13px; color: #52606d; display: flex; flex-direction: column; }
.evidence-row .source small { color: #9aa5b1; }
.empty { color: #7b8794; padding: 16px 0; }
.foot { margin-top: 16px; font-size: 12px; color: #9aa5b1; }
</style>
