import { useQuery, useQueryClient } from '@tanstack/react-query'
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'
import { api, tokenStore } from './api'
import type { Meta, User } from './types'

interface Ctx {
  user: User | null
  meta: Meta | undefined
  login: (login: string, password: string) => Promise<void>
  logout: () => void
  can: (role: 'operator' | 'admin') => boolean
  deptName: (code: string | null | undefined) => string
}

const AppCtx = createContext<Ctx>(null as unknown as Ctx)
const RANK = { viewer: 0, operator: 1, admin: 2 }

export function AppProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient()
  const [user, setUser] = useState<User | null>(null)
  const [checked, setChecked] = useState(!tokenStore.get())

  useEffect(() => {
    if (!tokenStore.get()) return
    api.get<User>('/api/auth/me').then(setUser).catch(() => tokenStore.clear()).finally(() => setChecked(true))
  }, [])

  const logout = useCallback(() => {
    tokenStore.clear()
    setUser(null)
    qc.clear()
  }, [qc])

  useEffect(() => {
    const h = () => { setUser(null); qc.clear() }
    window.addEventListener('pulse:logout', h)
    return () => window.removeEventListener('pulse:logout', h)
  }, [qc])

  const { data: meta } = useQuery({ queryKey: ['meta'], queryFn: () => api.get<Meta>('/api/meta'), enabled: !!user, staleTime: 60_000 })

  const login = async (login: string, password: string) => {
    const r = await api.post<{ token: string; user: User }>('/api/auth/login', { login, password })
    tokenStore.set(r.token)
    setUser(r.user)
  }
  const can = (role: 'operator' | 'admin') => !!user && RANK[user.role] >= RANK[role]
  const deptName = (code: string | null | undefined) =>
    meta?.departments.find((d) => d.code === code)?.name ?? code ?? '—'

  if (!checked) return null
  return <AppCtx.Provider value={{ user, meta, login, logout, can, deptName }}>{children}</AppCtx.Provider>
}

export const useApp = () => useContext(AppCtx)
