<template>
  <div class="app-shell">
    <div class="ambient-grid" aria-hidden="true"></div>

    <header class="topbar">
      <button
        class="icon-button mobile-menu"
        type="button"
        aria-label="打开会话列表"
        @click="sidebarOpen = !sidebarOpen"
      >
        <span></span><span></span><span></span>
      </button>

      <div class="brand">
        <div class="brand-mark" aria-hidden="true"><span></span></div>
        <div class="brand-copy">
          <p class="eyebrow">LOCAL / AGENT CONSOLE</p>
          <h1>MyBot</h1>
        </div>
      </div>

      <div class="topbar-meta">
        <span class="status-pill" :class="statusTone">
          <span class="status-dot"></span>
          {{ statusLabel }}
        </span>
        <span class="topbar-model mono">{{ status?.model || 'connecting…' }}</span>
      </div>
    </header>

    <main class="workspace">
      <SessionRail
        :sessions="sessions"
        :current-id="currentSessionId"
        :open="sidebarOpen"
        :busy="isSending"
        @select="selectSession"
        @create="createSession"
        @delete="deleteSession"
      />

      <ChatPanel
        v-model:draft="draft"
        :session="currentSession"
        :messages="messages"
        :is-sending="isSending"
        :error="error"
        :loading="loading"
        @send="send"
        @quick-send="sendQuick"
        @retry="retry"
        @toggle-telemetry="telemetryOpen = !telemetryOpen"
      />

      <TelemetryPanel
        :status="status"
        :session="currentSession"
        :busy="isSending"
        :open="telemetryOpen"
        @close="telemetryOpen = false"
      />
    </main>

    <div
      v-if="sidebarOpen || telemetryOpen"
      class="scrim"
      aria-hidden="true"
      @click="closeOverlays"
    ></div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { api } from './api'
import ChatPanel from './components/ChatPanel.vue'
import SessionRail from './components/SessionRail.vue'
import TelemetryPanel from './components/TelemetryPanel.vue'

const sessions = ref([])
const currentSessionId = ref('')
const messages = ref([])
const draft = ref('')
const status = ref(null)
const loading = ref(true)
const isSending = ref(false)
const error = ref('')
const sidebarOpen = ref(false)
const telemetryOpen = ref(false)
const lastPrompt = ref('')

const currentSession = computed(
  () => sessions.value.find((session) => session.id === currentSessionId.value) || null
)

const statusTone = computed(() => {
  if (!status.value) return 'is-pending'
  if (status.value.startup_error || status.value.status === 'degraded') return 'is-danger'
  return 'is-ok'
})

const statusLabel = computed(() => {
  if (!status.value) return '连接中'
  if (status.value.startup_error) return '需要配置'
  if (status.value.status === 'degraded') return '降级运行'
  if (status.value.long_term_enabled) return '记忆在线'
  if (status.value.memory_enabled) return '短期记忆'
  return '基础模式'
})

async function loadStatus() {
  try {
    status.value = await api.status()
  } catch (err) {
    error.value = err.message
    status.value = {
      status: 'degraded',
      startup_error: err.message,
      model: '',
      tools: []
    }
  }
}

async function refreshSessionList() {
  sessions.value = await api.sessions()
}

async function loadHistory(sessionId) {
  if (!sessionId) {
    messages.value = []
    return
  }
  const data = await api.history(sessionId, 120)
  messages.value = (data.messages || []).map((message, index) => ({
    ...message,
    id: `history-${index}-${message.role}`
  }))
  if (data.session) updateSession(data.session)
}

function updateSession(nextSession) {
  const index = sessions.value.findIndex((session) => session.id === nextSession.id)
  if (index >= 0) {
    sessions.value[index] = { ...sessions.value[index], ...nextSession }
  }
}

async function refreshSessions() {
  await refreshSessionList()
  if (!currentSessionId.value || !sessions.value.some((item) => item.id === currentSessionId.value)) {
    currentSessionId.value = sessions.value[0]?.id || ''
  }
  await loadHistory(currentSessionId.value)
}

async function bootstrap() {
  loading.value = true
  try {
    await loadStatus()
    await refreshSessions()
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}

async function selectSession(sessionId) {
  if (isSending.value) return
  if (sessionId === currentSessionId.value) {
    closeOverlays()
    return
  }
  currentSessionId.value = sessionId
  error.value = ''
  messages.value = []
  try {
    await loadHistory(sessionId)
  } catch (err) {
    error.value = err.message
  }
  closeOverlays()
}

async function createSession() {
  if (isSending.value) return
  try {
    const session = await api.createSession('')
    currentSessionId.value = session.id
    messages.value = []
    error.value = ''
    await refreshSessionList()
    closeOverlays()
  } catch (err) {
    error.value = err.message
  }
}

async function deleteSession(sessionId) {
  if (isSending.value) return
  const session = sessions.value.find((item) => item.id === sessionId)
  const title = session?.display_title || session?.title || '这个会话'
  if (!window.confirm(`删除「${title}」？对话和长期记忆都会清除。`)) return
  try {
    await api.deleteSession(sessionId)
    await refreshSessions()
  } catch (err) {
    error.value = err.message
  }
}

async function send() {
  const message = draft.value.trim()
  if (!message || isSending.value) return

  if (!currentSessionId.value) {
    await createSession()
    if (!currentSessionId.value) return
  }

  error.value = ''
  lastPrompt.value = message
  const temporaryId = `local-${Date.now()}`
  messages.value.push({ id: temporaryId, role: 'user', content: message })
  draft.value = ''
  isSending.value = true

  try {
    const result = await api.chat(currentSessionId.value, message)
    messages.value.push({
      id: `assistant-${Date.now()}`,
      role: 'assistant',
      content: result.answer
    })
    if (result.session) updateSession(result.session)
    try {
      await refreshSessionList()
    } catch (refreshError) {
      // 会话列表刷新失败不应把已经成功的本轮回复回滚掉
      console.warn('刷新会话列表失败', refreshError)
    }
  } catch (err) {
    messages.value = messages.value.filter((item) => item.id !== temporaryId)
    draft.value = message
    error.value = err.message
  } finally {
    isSending.value = false
  }
}

async function sendQuick(prompt) {
  draft.value = prompt
  await send()
}

function retry() {
  if (draft.value.trim()) send()
}

function closeOverlays() {
  sidebarOpen.value = false
  telemetryOpen.value = false
}

function handleResize() {
  if (window.innerWidth > 820) sidebarOpen.value = false
  if (window.innerWidth > 1180) telemetryOpen.value = false
}

onMounted(() => {
  bootstrap()
  window.addEventListener('resize', handleResize)
})

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
})
</script>