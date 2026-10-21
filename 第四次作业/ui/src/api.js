const rawBase = import.meta.env.VITE_API_BASE_URL || ''
const BASE = rawBase.replace(/\/$/, '')

async function request(path, options = {}) {
  const response = await fetch(`${BASE}${path}`, {
    headers: {
      'Content-Type': 'application/json',
      ...(options.headers || {})
    },
    ...options
  })

  if (!response.ok) {
    let message = `请求失败（${response.status}）`
    try {
      const payload = await response.json()
      if (payload?.detail) message = payload.detail
    } catch {
      // 非 JSON 错误响应保留默认提示
    }
    throw new Error(message)
  }

  if (response.status === 204) return null
  return response.json()
}

export const api = {
  status: () => request('/api/status'),
  sessions: () => request('/api/sessions'),
  createSession: (title = '') =>
    request('/api/sessions', {
      method: 'POST',
      body: JSON.stringify({ title })
    }),
  renameSession: (id, title) =>
    request(`/api/sessions/${encodeURIComponent(id)}`, {
      method: 'PATCH',
      body: JSON.stringify({ title })
    }),
  deleteSession: (id) =>
    request(`/api/sessions/${encodeURIComponent(id)}`, {
      method: 'DELETE'
    }),
  history: (id, limit = 120) =>
    request(`/api/sessions/${encodeURIComponent(id)}/history?limit=${limit}`),
  chat: (sessionId, message) =>
    request('/api/chat', {
      method: 'POST',
      body: JSON.stringify({ session_id: sessionId, message })
    })
}