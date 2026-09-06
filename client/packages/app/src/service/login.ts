import { httpService } from './httpService'
import Cookies from 'js-cookie'
import { usePlatformStore } from '@/stores/platform'

export const isLoggedIn = () => {
  return !!Cookies.get('token')
}

export const logout = async (callback?: () => void) => {
  let path = window.location.pathname.split('/static/app')[0]
  if (path == '') {
    path = '/'
  }
  try {
    if (Cookies.get('token')) {
      await fetch('/api/v1/auth/logout', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: '{}',
      })
    }
  } catch {
    // Local cleanup must still happen when the server is unavailable.
  } finally {
    Cookies.remove('token', { path })
    Cookies.remove('token', { path: '/' })
    usePlatformStore().clearSession()
    callback?.()
  }
}

export const fetchLoginProviders = async () => {
  try {
    const response: any = await httpService.get('/account/providers')
    return response
  } catch (error) {
    console.error('获取登录方式列表失败:', error)
    throw new Error('获取登录方式列表失败')
  }
}
