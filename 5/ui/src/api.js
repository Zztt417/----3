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

async function chatStreamRequest(sessionId, message, model, onEvent) {
  const response = await fetch(`${BASE}/api/chat/stream`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream'
    },
    body: JSON.stringify({ session_id: sessionId, message, model: model || null })
  })

  if (!response.ok) {
    let detail = `请求失败（${response.status}）`
    try {
      const payload = await response.json()
      if (payload?.detail) detail = payload.detail
    } catch {
      // 非 JSON 错误响应保留默认提示
    }
    throw new Error(detail)
  }

  if (!response.body) throw new Error('浏览器不支持流式响应')

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  const dispatch = (chunk) => {
    for (const line of chunk.split('\n')) {
      if (!line.startsWith('data:')) continue
      const raw = line.slice(5).trim()
      if (!raw) continue
      try {
        onEvent(JSON.parse(raw))
      } catch (error) {
        if (error instanceof SyntaxError) continue
        throw error
      }
    }
  }

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const events = buffer.split('\n\n')
    buffer = events.pop() || ''
    for (const event of events) dispatch(event)
  }

  if (buffer.trim()) dispatch(buffer)
}

export const api = {
  status: () => request('/api/status'),
  llmSettings: () => request('/api/settings/llm'),
  updateLlmSettings: (payload) =>
    request('/api/settings/llm', {
      method: 'PUT',
      body: JSON.stringify(payload)
    }),
  testLlmSettings: (payload) =>
    request('/api/settings/llm/test', {
      method: 'POST',
      body: JSON.stringify(payload)
    }),
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
  chat: (sessionId, message, model = '') =>
    request('/api/chat', {
      method: 'POST',
      body: JSON.stringify({ session_id: sessionId, message, model: model || null })
    }),
  chatStream: (sessionId, message, model, onEvent) =>
    chatStreamRequest(sessionId, message, model, onEvent),
  hotspots: () => request('/api/hotspots'),
  refreshHotspots: () => request('/api/hotspots/refresh', { method: 'POST' }),
  skills: (q = '') => request(`/api/skills?q=${encodeURIComponent(q)}`),
  refreshSkills: () => request('/api/skills/refresh', { method: 'POST' }),
  skillCatalog: (source = 'openai', q = '') =>
    request(`/api/skills/catalog?source=${encodeURIComponent(source)}&q=${encodeURIComponent(q)}`),
  skillDetail: (id) => request(`/api/skills/${encodeURIComponent(id)}`),
  installSkill: (payload) =>
    request('/api/skills/install', {
      method: 'POST',
      body: JSON.stringify(payload)
    }),
  setSkillEnabled: (id, enabled) =>
    request(`/api/skills/${encodeURIComponent(id)}/${enabled ? 'enable' : 'disable'}`, {
      method: 'POST'
    }),
  deleteSkill: (id) => request(`/api/skills/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  mcpRegistrySearch: (q = '', cursor = '', limit = 20) =>
    request(`/api/mcp/registry/search?q=${encodeURIComponent(q)}&cursor=${encodeURIComponent(cursor)}&limit=${limit}`),
  mcpRegistryDetail: (name, version = 'latest') =>
    request(`/api/mcp/registry/detail?name=${encodeURIComponent(name)}&version=${encodeURIComponent(version)}`),
  mcpServers: () => request('/api/mcp/servers'),
  installMcp: (payload) =>
    request('/api/mcp/servers/install', {
      method: 'POST',
      body: JSON.stringify(payload)
    }),
  setMcpEnabled: (id, enabled) =>
    request(`/api/mcp/servers/${encodeURIComponent(id)}/${enabled ? 'enable' : 'disable'}`, {
      method: 'POST'
    }),
  restartMcp: (id) =>
    request(`/api/mcp/servers/${encodeURIComponent(id)}/restart`, { method: 'POST' }),
  deleteMcp: (id) => request(`/api/mcp/servers/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  mcpTools: (id) => request(`/api/mcp/servers/${encodeURIComponent(id)}/tools`)
}