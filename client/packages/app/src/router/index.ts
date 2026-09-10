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
      path: '/admin/users',
      name: 'admin-users',
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
      path: '/admin/conversations',
      name: 'admin-conversations',
      component: () => import('@/pages/Admin.vue'),
    },
    {
      path: '/admin/audit',
      name: 'admin-audit',
      component: () => import('@/pages/Admin.vue'),
    },
    {
      // 渠道会话：/:applicationId/channel/:conversationId
      // 渠道（访客）会话不落地本地 chat_conversation 表，权威源在 CAPI DescribeConversationList。
      // 通过 URL 里的 /channel/ 段显式区分：
      //   1) 刷新时前端可直接判定为渠道会话，跳过普通 /chat/messages 首屏拉取
      //   2) 侧栏点击渠道会话时 router.push 到该变体，保持刷新可复原
      // 注意：必须放在通用 home 路由之前，确保 /channel/ 段优先匹配（vue-router 从上到下匹配）。
      path: '/:applicationId/channel/:conversationId',
      name: 'home-channel',
      component: () => import('@/pages/Home.vue'),
    },
    {
      // 定时任务会话：/:applicationId/timertask/:conversationId?triggerId=xxx
      // 定时任务（AppTrigger）触发的会话与渠道会话同源（不在本地 chat_conversation 表，走 CAPI）。
      // 通过 URL 里的 /timertask/ 段显式区分：
      //   1) 刷新时前端判定为定时任务会话，走 DescribeConversationMessageList 拉首屏
      //   2) 右侧默认展开定时任务执行记录面板（sidebar 模式，对齐企微机器人体验）
      //   3) query.triggerId 用于刷新后自动定位到具体触发器详情
      // 必须放在通用 home 路由之前。
      path: '/:applicationId/timertask/:conversationId',
      name: 'home-timertask',
      component: () => import('@/pages/Home.vue'),
    },
    {
      // 统一层级结构：/:applicationId?/:conversationId?
      // 例：/                       -> 未选应用
      //     /appA                   -> 选中应用 appA，无会话
      //     /appA/convX             -> 应用 appA 下的普通会话 convX
      path: '/:applicationId?/:conversationId?',
      name: 'home',
      component: () => import('@/pages/Home.vue'),
    },
    {
      path: '/login',
      name: 'login',
      component: () => import('@/pages/Login.vue'),
    },
    {
      path: '/share/:shareId?',
      name: 'share',
      meta:{
        unauthorized: true
      },
      component: () => import('@/pages/Share.vue'),
    },
    {
      path: '/shared',
      name: 'shared-result',
      meta: {
        unauthorized: true,
      },
      component: () => import('@/pages/SharedResult.vue'),
    },
  ],
})

router.beforeEach(
  async (to: RouteLocationNormalized, _from: RouteLocationNormalized) => {
    const platformRoute = to.path === '/portal' || to.path.startsWith('/portal/') || to.path === '/admin' || to.path.startsWith('/admin/')
    const platformStore = usePlatformStore()
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

    if (!isLoggedIn()) return { name: 'login' }
    return
  },
)

export default router
