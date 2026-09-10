import {
  createRouter,
  createWebHashHistory,
  type RouteLocationNormalized
} from 'vue-router'
import { isLoggedIn } from '@/service/login'
import Cookies from 'js-cookie'
import { getPlatformSession } from '@/platform/platformService'
import { usePlatformStore } from '@/stores/platform'


const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    {
      path: '/portal/lookup',
      name: 'portal-lookup',
      component: () => import('@/pages/Portal.vue'),
    },
    {
      path: '/portal/sessions',
      name: 'portal-sessions',
      component: () => import('@/pages/Portal.vue'),
    },
    {
      path: '/portal/settings',
      name: 'portal-settings',
      component: () => import('@/pages/Portal.vue'),
    },
    {
      path: '/portal/:section(lookup|sessions|settings)?',
      name: 'portal',
      component: () => import('@/pages/Portal.vue'),
    },
    {
      path: '/admin',
      name: 'admin',
      component: () => import('@/pages/Admin.vue'),
    },
    {
      path: '/admin/enterprises',
      name: 'admin-enterprises',
      component: () => import('@/pages/Admin.vue'),
    },
    {
      path: '/admin/bindings',
      name: 'admin-bindings',
      component: () => import('@/pages/Admin.vue'),
    },
    {
      path: '/admin/channels',
      name: 'admin-channels',
      component: () => import('@/pages/Admin.vue'),
    },
    {
      path: '/admin/adp-chat/:applicationId?/:conversationId?',
      name: 'admin-adp-chat',
      component: () => import('@/pages/AdminAdpChat.vue'),
    },
    {
      path: '/admin/agents-tools',
      name: 'admin-agents-tools',
      component: () => import('@/pages/Admin.vue'),
    },
    {
      path: '/admin/audit',
      name: 'admin-audit',
      component: () => import('@/pages/Admin.vue'),
    },
    {
      path: '/login',
      name: 'login',
      component: () => import('@/pages/Login.vue'),
    },
    {
      // 免登录只读分享结果页：微信服务号图文卡片点开的目标页，保留公开可访问。
      // 必须放在下方 catch-all 之前，否则会被 /:pathMatch 抢先匹配并重定向到 login。
      path: '/shared',
      name: 'shared-result',
      meta: {
        unauthorized: true,
      },
      component: () => import('@/pages/SharedResult.vue'),
    },
    {
      // 旧 ADP 控制台聊天页（Home）与旧公开分享页（Share）已下线，平台只保留
      // /admin/adp-chat 一个 ADP agent chat 调试入口和上面的 /shared 只读页。
      // 任何其它未匹配路径统一交给 login 路由，由下方 beforeEach 按 canManage
      // 落到 admin 或 portal；未登录则停在登录页。catch-all 必须是最后一条。
      path: '/:pathMatch(.*)*',
      redirect: { name: 'login' },
    },
  ],
})

router.beforeEach(
  async (to: RouteLocationNormalized, _from: RouteLocationNormalized) => {
    const platformRoute = to.path === '/portal' || to.path.startsWith('/portal/') || to.path === '/admin' || to.path.startsWith('/admin/')
    const platformStore = usePlatformStore()

    // 免登录路由（如 /shared 只读结果页）直接放行，不走平台鉴权。
    if (to.meta.unauthorized) {
      return
    }

    if (to.name === 'login') {
      if (!isLoggedIn()) return
      if (!platformStore.isAuthenticated) {
        try {
          platformStore.setSession(await getPlatformSession())
        } catch {
          Cookies.remove('token', { path: '/' })
          platformStore.clearSession()
          return
        }
      }
      return { name: platformStore.canManage ? 'admin' : 'portal' }
    }

    if (platformRoute) {
      if (!isLoggedIn()) return { name: 'login', query: { redirect: to.fullPath } }
      if (!platformStore.isAuthenticated) {
        try {
          platformStore.setSession(await getPlatformSession())
        } catch {
          Cookies.remove('token', { path: '/' })
          platformStore.clearSession()
          return { name: 'login', query: { redirect: to.fullPath } }
        }
      }
      if (to.path.startsWith('/admin') && !platformStore.canManage) {
        return { name: 'portal' }
      }
      return
    }

    // 到这里的都是非平台、非登录、非免登录路由；旧 Home/Share 页下线后已无此类
    // 具名路由，未匹配路径都会命中 catch-all 重定向到 login，故无需兜底分支。
    return
  },
)

export default router
