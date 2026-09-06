<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowRightIcon, CheckCircleIcon, LockOnIcon, MobileIcon, UserSafetyIcon } from 'tdesign-icons-vue-next'
import Cookies from 'js-cookie'
import { fetchLoginProviders, isLoggedIn } from '@/service/login'
import { loginPlatform } from '@/platform/platformService'
import { useUserStore } from '@/stores/user'
import { usePlatformStore } from '@/stores/platform'

const router = useRouter()
const userStore = useUserStore()
const platformStore = usePlatformStore()
const phone = ref('')
const password = ref('')
const submitting = ref(false)
const errorMessage = ref('')
const oauthProviders = ref<{ name: string; url: string }[]>([])
const showProviderHint = ref(false)

onMounted(async () => {
  if (isLoggedIn()) {
    await router.replace({ name: platformStore.canManage ? 'admin' : 'portal' })
    return
  }
  try {
    const response = await fetchLoginProviders()
    oauthProviders.value = response?.Providers || []
    showProviderHint.value = oauthProviders.value.length === 0
  } catch {
    showProviderHint.value = true
  }
})

const submit = async () => {
  errorMessage.value = ''
  const normalizedPhone = phone.value.replace(/\s/g, '')
  if (!/^1\d{10}$/.test(normalizedPhone)) {
    errorMessage.value = '请输入有效的 11 位手机号'
    return
  }
  if (password.value.length !== 6) {
    errorMessage.value = '初始口令为 6 位数字，请联系管理员获取'
    return
  }
  submitting.value = true
  try {
    const result = await loginPlatform(normalizedPhone, password.value)
    Cookies.set('token', result.token, { path: '/', sameSite: 'Lax' })
    platformStore.setSession(result)
    userStore.setUserInfo(result.user.name, '')
    await router.replace({ name: platformStore.canManage ? 'admin' : 'portal' })
  } catch {
    errorMessage.value = '登录失败，请检查手机号和口令，或联系客户经理'
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <main class="auth-page">
    <section class="auth-context">
      <div class="auth-brand"><span class="brand-mark">O</span><span><strong>OceanDesk</strong><small>货代业务接入平台</small></span></div>
      <div class="context-content"><p class="context-kicker">OCEAN FREIGHT OPERATIONS</p><h1>把每一次查询，<br /><em>变成可信的业务进度。</em></h1><p class="context-copy">从企业登录、权限范围到 M3 业务证据，OceanDesk 让跨渠道的货物查询保持清晰、可追溯。</p><div class="context-points"><span><CheckCircleIcon />按企业范围访问</span><span><CheckCircleIcon />关键字段附带来源</span><span><CheckCircleIcon />会话与渠道相互隔离</span></div></div>
      <div class="auth-context-footer"><span>OceanDesk Platform</span><span>v0.1 · 中国大陆区域</span></div>
    </section>
    <section class="auth-panel">
      <div class="auth-panel-inner">
        <div class="mobile-brand"><span class="brand-mark">O</span><strong>OceanDesk</strong></div>
        <p class="panel-kicker">客户门户登录</p><h2>欢迎回来</h2><p class="panel-intro">使用销售或客服为你开通的账号登录。</p>
        <form class="auth-form" @submit.prevent="submit">
          <label for="phone">手机号</label><div class="field-wrap"><MobileIcon /><input id="phone" v-model="phone" inputmode="numeric" autocomplete="username" placeholder="请输入 11 位手机号" /></div>
          <label for="password">初始口令</label><div class="field-wrap"><LockOnIcon /><input id="password" v-model="password" type="password" inputmode="numeric" autocomplete="current-password" maxlength="6" placeholder="6 位数字口令" /></div>
          <p class="form-help"><UserSafetyIcon />平台不会通过聊天、模型或诊断日志记录你的口令。</p>
          <p v-if="errorMessage" class="auth-error">{{ errorMessage }}</p>
          <button class="login-submit" type="submit" :disabled="submitting">{{ submitting ? '正在验证…' : '登录客户门户' }}<ArrowRightIcon /></button>
        </form>
        <div class="login-divider"><span>其他登录方式</span></div>
        <div v-if="oauthProviders.length" class="oauth-list"><a v-for="provider in oauthProviders" :key="provider.name" class="oauth-button" :href="provider.url">{{ provider.name }}<ArrowRightIcon /></a></div>
        <div v-else class="oauth-empty"><span>{{ showProviderHint ? '当前未配置第三方登录' : '正在加载登录方式…' }}</span></div>
        <p class="login-footnote">没有账号或忘记口令？<strong>联系你的销售 / 客服</strong></p>
      </div>
    </section>
  </main>
</template>

<style scoped>
.auth-page { min-height: 100vh; display: grid; grid-template-columns: minmax(420px, .95fr) minmax(460px, 1.05fr); background: #f8fbf9; color: #19332f; }.auth-context { display: flex; flex-direction: column; justify-content: space-between; padding: 34px clamp(34px, 6vw, 92px) 29px; min-height: 100vh; background: #17312e; color: #f2f8f5; position: relative; overflow: hidden; }.auth-context::after { content: ''; position: absolute; width: 540px; height: 540px; border: 1px solid rgba(158,216,196,.15); border-radius: 50%; right: -280px; bottom: -220px; box-shadow: 0 0 0 38px rgba(158,216,196,.035), 0 0 0 78px rgba(158,216,196,.025); }.auth-brand, .mobile-brand { display: flex; align-items: center; gap: 10px; }.brand-mark { display: grid; place-items: center; width: 31px; height: 31px; border-radius: 8px; color: #17312e; background: #b8e2d2; font-size: 18px; font-weight: 800; }.auth-brand strong, .auth-brand small { display: block; }.auth-brand strong { font-size: 15px; letter-spacing: .01em; }.auth-brand small { color: #97b8ad; font-size: 10px; margin-top: 2px; }.context-content { max-width: 525px; padding: 54px 0 48px; position: relative; z-index: 1; }.context-kicker, .panel-kicker { margin: 0 0 17px; color: #8ec5b3; font-size: 10px; letter-spacing: .18em; font-weight: 700; }.context-content h1 { margin: 0; color: #f3f8f5; font-size: clamp(35px, 4vw, 54px); line-height: 1.12; letter-spacing: 0; font-weight: 730; }.context-content h1 em { color: #a7dac8; font-style: normal; }.context-copy { max-width: 420px; margin: 22px 0 25px; color: #a9c2b9; font-size: 13px; line-height: 1.8; }.context-points { display: grid; gap: 11px; }.context-points span { display: flex; align-items: center; gap: 8px; color: #d5e9e1; font-size: 11px; }.context-points :deep(svg) { color: #87cbb3; width: 15px; }.auth-context-footer { display: flex; justify-content: space-between; color: #789c90; font-size: 10px; letter-spacing: .03em; position: relative; z-index: 1; }.auth-panel { display: flex; align-items: center; justify-content: center; padding: 42px 40px; background: #f8fbf9; }.auth-panel-inner { width: min(390px, 100%); }.mobile-brand { display: none; }.panel-kicker { color: #43877a; margin-bottom: 12px; }.auth-panel h2 { margin: 0; font-size: 31px; letter-spacing: 0; color: #18332f; }.panel-intro { margin: 8px 0 28px; color: #7d8c88; font-size: 12px; }.auth-form { display: grid; gap: 9px; }.auth-form label { margin-top: 8px; color: #4d6761; font-size: 11px; font-weight: 650; }.field-wrap { display: flex; align-items: center; gap: 8px; height: 44px; border: 1px solid #d7e4e0; background: white; padding: 0 12px; transition: .2s ease; }.field-wrap:focus-within { border-color: #258779; box-shadow: 0 0 0 3px rgba(37,135,121,.1); }.field-wrap :deep(svg) { width: 16px; color: #8da19b; }.field-wrap input { border: 0; outline: 0; min-width: 0; flex: 1; height: 100%; color: #24433d; background: transparent; font: inherit; font-size: 12px; }.form-help { display: flex; gap: 6px; align-items: flex-start; margin: 9px 0 0; color: #889893; font-size: 10px; line-height: 1.5; }.form-help :deep(svg) { flex: 0 0 auto; width: 14px; color: #66998c; }.auth-error { margin: 7px 0 0; padding: 9px 10px; background: #fff2ef; color: #a4534c; font-size: 11px; }.login-submit { height: 45px; display: flex; justify-content: center; align-items: center; gap: 8px; margin-top: 12px; border: 0; color: white; background: #147d72; font-size: 12px; font-weight: 700; cursor: pointer; transition: .2s ease; }.login-submit:hover { background: #0f685f; }.login-submit:disabled { opacity: .6; cursor: wait; }.login-submit :deep(svg) { width: 16px; }.login-divider { display: flex; align-items: center; gap: 11px; margin: 25px 0 16px; color: #9aa8a4; font-size: 10px; }.login-divider::before, .login-divider::after { content: ''; flex: 1; height: 1px; background: #e1eae6; }.oauth-list { display: grid; gap: 8px; }.oauth-button { height: 42px; display: flex; justify-content: space-between; align-items: center; padding: 0 13px; border: 1px solid #d8e4e0; color: #4d6b64; text-decoration: none; font-size: 11px; background: white; }.oauth-button:hover { border-color: #98c5b9; color: #147d72; }.oauth-button :deep(svg) { width: 15px; }.oauth-empty { display: flex; justify-content: center; align-items: center; min-height: 42px; border: 1px dashed #d9e4e0; color: #9aa8a4; font-size: 10px; }.login-footnote { margin: 26px 0 0; text-align: center; color: #8c9a96; font-size: 10px; }.login-footnote strong { color: #4f7770; font-weight: 650; margin-left: 3px; }.login-submit:focus-visible, .oauth-button:focus-visible { outline: 3px solid rgba(20,125,114,.22); outline-offset: 2px; }
@media (max-width: 800px) { .auth-page { display: block; }.auth-context { min-height: 250px; padding: 22px 23px 25px; }.auth-context::after { width: 330px; height: 330px; right: -200px; bottom: -230px; }.context-content { padding: 34px 0 3px; }.context-content h1 { font-size: 31px; }.context-copy, .context-points { display: none; }.auth-context-footer { display: none; }.auth-panel { padding: 33px 22px 44px; align-items: flex-start; min-height: calc(100vh - 250px); }.mobile-brand { display: flex; margin-bottom: 38px; color: #21443d; }.mobile-brand strong { font-size: 14px; }.mobile-brand .brand-mark { width: 28px; height: 28px; font-size: 16px; } }
@media (max-width: 480px) { .auth-context { min-height: 215px; }.context-content { padding-top: 28px; }.context-content h1 { font-size: 27px; }.auth-panel { min-height: calc(100vh - 215px); padding: 28px 17px 38px; }.auth-panel h2 { font-size: 27px; }.mobile-brand { margin-bottom: 28px; } }
</style>
