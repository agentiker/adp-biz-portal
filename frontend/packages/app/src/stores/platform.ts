import { defineStore } from 'pinia'
import type { EnterpriseScope, PlatformRole, PlatformUser } from '@/platform/types'

export const usePlatformStore = defineStore('platform', {
  state: () => ({
    user: null as PlatformUser | null,
    enterprise: null as EnterpriseScope | null,
    permissions: [] as string[],
    mustReset: false,
  }),

  getters: {
    isAuthenticated: (state) => Boolean(state.user),
    canManage: (state) => state.permissions.includes('platform.manage'),
    role: (state): PlatformRole | null => state.user?.role || null,
  },

  actions: {
    setSession(payload: { user: PlatformUser; enterprise: EnterpriseScope | null; permissions?: string[]; mustReset?: boolean }) {
      this.user = payload.user
      this.enterprise = payload.enterprise
      this.permissions = payload.permissions || []
      this.mustReset = Boolean(payload.mustReset)
    },
    clearSession() {
      this.$reset()
    },
  },
})
