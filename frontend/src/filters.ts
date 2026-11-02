import { useCallback, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'

// The global filter lives in the URL, so every drill-down view is a shareable link (spec 3.8.1, 3.8.4).
export const FILTER_KEYS = ['days', 'date_from', 'date_to', 'source', 'department', 'sentiment', 'priority',
  'status', 'type', 'district', 'lang', 'q', 'urgent', 'is_direct', 'needs_review', 'origin', 'cluster_id', 'platform', 'voice'] as const
export type FilterKey = (typeof FILTER_KEYS)[number]
export type FilterState = Partial<Record<FilterKey, string>>

export function useFilters() {
  const [sp, setSp] = useSearchParams()
  const filters = useMemo(() => {
    const f: FilterState = {}
    FILTER_KEYS.forEach((k) => { const v = sp.get(k); if (v) f[k] = v })
    if (!f.days && !f.date_from) f.days = '30'
    return f
  }, [sp])

  const setFilters = useCallback((patch: FilterState, replace = false) => {
    setSp((prev) => {
      const next = new URLSearchParams(replace ? '' : prev)
      Object.entries(patch).forEach(([k, v]) => { if (v) next.set(k, v); else next.delete(k) })
      if (patch.date_from) next.delete('days')
      if (patch.days) { next.delete('date_from'); next.delete('date_to') }
      next.delete('page')
      return next
    })
  }, [setSp])

  const reset = useCallback(() => setSp(new URLSearchParams()), [setSp])
  const activeCount = Object.keys(filters).filter((k) => k !== 'days' || filters.days !== '30').length
  return { filters, setFilters, reset, activeCount, params: sp, setParams: setSp }
}

export function toSearch(f: FilterState): string {
  const p = new URLSearchParams()
  Object.entries(f).forEach(([k, v]) => { if (v) p.set(k, v) })
  return p.toString()
}
