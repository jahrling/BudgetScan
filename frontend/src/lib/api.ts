export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

export async function apiFetch<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, { credentials: 'include', ...init })
  if (!res.ok) {
    throw new ApiError(res.status, `HTTP ${res.status}`)
  }
  if (res.status === 204) return undefined as T
  return res.json()
}

export interface UserRead {
  id: number
  username: string
  created_at: string
  updated_at: string
}

export const authApi = {
  me: () => apiFetch<UserRead>('/api/auth/me'),
  needsSetup: () => apiFetch<{ needs_setup: boolean }>('/api/auth/needs-setup'),
  setup: (username: string, password: string) =>
    apiFetch<UserRead>('/api/auth/setup', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    }),
  login: (username: string, password: string) =>
    apiFetch<UserRead>('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    }),
  logout: () =>
    apiFetch<void>('/api/auth/logout', { method: 'POST' }),
}
