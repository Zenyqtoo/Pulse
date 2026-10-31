// Thin fetch wrapper: adds the token, turns API errors into readable messages, downloads files.
const TOKEN_KEY = 'pulse_token'

export const tokenStore = {
  get: () => localStorage.getItem(TOKEN_KEY),
  set: (t: string) => localStorage.setItem(TOKEN_KEY, t),
  clear: () => localStorage.removeItem(TOKEN_KEY),
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

type Params = Record<string, string | number | boolean | undefined | null>

export function qs(params?: Params): string {
  if (!params) return ''
  const p = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') p.set(k, String(v))
  })
  const s = p.toString()
  return s ? `?${s}` : ''
}

async function request<T>(method: string, url: string, body?: unknown, params?: Params): Promise<T> {
  const headers: Record<string, string> = {}
  const t = tokenStore.get()
  if (t) headers.Authorization = `Bearer ${t}`
  let payload: BodyInit | undefined
  if (body instanceof FormData) payload = body
  else if (body !== undefined) {
    headers['Content-Type'] = 'application/json'
    payload = JSON.stringify(body)
  }
  let res: Response
  try {
    res = await fetch(url + qs(params), { method, headers, body: payload })
  } catch {
    throw new ApiError(0, 'Нет связи с сервером. Проверьте, что backend запущен.')
  }
  if (res.status === 401 && !url.endsWith('/auth/login')) {
    tokenStore.clear()
    window.dispatchEvent(new Event('pulse:logout'))
  }
  if (!res.ok) {
    let msg = `Ошибка ${res.status}`
    try {
      const data = await res.json()
      if (typeof data.detail === 'string') msg = data.detail
      else if (Array.isArray(data.detail)) msg = 'Проверьте поля: ' + data.detail.map((d: { loc: string[] }) => d.loc.slice(-1)[0]).join(', ')
    } catch { /* not json */ }
    throw new ApiError(res.status, msg)
  }
  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}

export const api = {
  get: <T>(url: string, params?: Params) => request<T>('GET', url, undefined, params),
  post: <T>(url: string, body?: unknown) => request<T>('POST', url, body),
  patch: <T>(url: string, body?: unknown) => request<T>('PATCH', url, body),
  put: <T>(url: string, body?: unknown) => request<T>('PUT', url, body),
  del: <T>(url: string) => request<T>('DELETE', url),
}

export async function download(url: string, params?: Params): Promise<void> {
  const t = tokenStore.get()
  const res = await fetch(url + qs(params), { headers: t ? { Authorization: `Bearer ${t}` } : {} })
  if (!res.ok) {
    let msg = `Ошибка ${res.status}`
    try { msg = (await res.json()).detail ?? msg } catch { /* ignore */ }
    throw new ApiError(res.status, msg)
  }
  const cd = res.headers.get('Content-Disposition') || ''
  const name = /filename=([^;]+)/.exec(cd)?.[1] ?? 'export'
  const blob = await res.blob()
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = name
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(a.href), 2000)
}
