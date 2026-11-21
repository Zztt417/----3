<template>
  <div class="app-shell">
    <div class="ambient-grid" aria-hidden="true"></div>

    <header class="topbar">
      <button
        v-if="activeView === 'chat'"
        class="icon-button mobile-menu"
        type="button"
        aria-label="打开会话列表"
        @click="sidebarOpen = !sidebarOpen"
      >
        <span></span><span></span><span></span>
      </button>

      <div class="brand">
        <div class="brand-mark" aria-hidden="true"><img src="/favicon.png?v=20261114" alt="" /></div>
        <div class="brand-copy">
          <p class="eyebrow">LOCAL / AGENT CONSOLE</p>
          <h1>MyBot</h1>
        </div>
      </div>

      <nav class="view-nav" aria-label="主导航">
        <button
          type="button"
          :class="{ active: activeView === 'hotspots' }"
          @click="switchView('hotspots')"
        >
          热点
        </button>
        <button
          type="button"
          :class="{ active: activeView === 'chat' }"
          @click="switchView('chat')"
        >
          对话
        </button>
      </nav>

      <div class="topbar-meta">
        <button
          class="api-settings-trigger"
          :class="{ 'needs-config': status && !status.api_key_configured }"
          type="button"
          title="配置模型 API"
          @click="openSettings"
        >
          <span class="api-settings-dot"></span>
          <span>{{ status?.api_key_configured ? 'API' : '配置 API' }}</span>
        </button>
        <span class="status-pill" :class="statusTone">
          <span class="status-dot"></span>
          {{ statusLabel }}
        </span>
        <span class="topbar-model mono">{{ status?.model || 'connecting…' }}</span>
      </div>
    </header>

    <main class="workspace" :class="{ 'is-hotspot-view': activeView === 'hotspots' }">
      <template v-if="activeView === 'hotspots'">
        <HotspotPanel expanded @discuss="discussHotspot" />
      </template>

      <template v-else>
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
          :streaming-status="streamingStatus"
          :error="error"
          :loading="loading"
          :models="modelOptions"
          :selected-model="selectedModel"
          @update:selected-model="selectedModel = $event"
          @send="send"
          @quick-send="sendQuick"
          @retry="retry"
          @regenerate="regenerateMessage"
          @toggle-telemetry="telemetryOpen = !telemetryOpen"
        />

        <TelemetryPanel
          :status="status"
          :session="currentSession"
          :busy="isSending"
          :open="telemetryOpen"
          @close="telemetryOpen = false"
        />
      </template>
    </main>

    <div
      v-if="sidebarOpen || telemetryOpen || settingsOpen"
      class="scrim"
      aria-hidden="true"
      @click="closeOverlays"
    ></div>

    <SettingsPanel
      :open="settingsOpen"
      :busy="isSending"
      @close="settingsOpen = false"
      @saved="handleSettingsSaved"
    />
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { api } from './api'
import ChatPanel from './components/ChatPanel.vue'
import HotspotPanel from './components/HotspotPanel.vue'
import SessionRail from './components/SessionRail.vue'
import SettingsPanel from './components/SettingsPanel.vue'
import TelemetryPanel from './components/TelemetryPanel.vue'

const sessions = ref([])
const currentSessionId = ref('')
const messages = ref([])
const draft = ref('')
const status = ref(null)
const loading = ref(true)
const activeView = ref('hotspots')
const isSending = ref(false)
const error = ref('')
const sidebarOpen = ref(false)
const telemetryOpen = ref(false)
const settingsOpen = ref(false)
const lastPrompt = ref('')
const streamingStatus = ref('')
const selectedModel = ref('')

const currentSession = computed(
  () => sessions.value.find((session) => session.id === currentSessionId.value) || null
)

const modelOptions = computed(() => {
  const configured = Array.isArray(status.value?.models) ? status.value.models : []
  return [...new Set(configured.filter(Boolean))].slice(0, 3)
})

function syncSelectedModel() {
  const options = modelOptions.value
  if (!options.length) {
    selectedModel.value = ''
    return
  }
  const saved = window.localStorage.getItem('mybot.selectedModel') || ''
  if (options.includes(saved)) {
    selectedModel.value = saved
    return
  }
  if (!options.includes(selectedModel.value)) {
    selectedModel.value = options.includes(status.value?.model)
      ? status.value.model
      : options[0]
  }
}

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
    syncSelectedModel()
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

async function createSession(title = '') {
  if (isSending.value) return false
  try {
    const session = await api.createSession(title)
    currentSessionId.value = session.id
    messages.value = []
    error.value = ''
    await refreshSessionList()
    closeOverlays()
    return true
  } catch (err) {
    error.value = err.message
    return false
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

async function streamAssistantReply(prompt, options = {}) {
  const {
    temporaryUserId = '',
    restoreAssistant = null,
    restoreDraft = ''
  } = options
  const assistantId = `assistant-${Date.now()}`
  let assistantCreated = false
  let assistantText = ''
  let doneEvent = null

  error.value = ''
  streamingStatus.value = '正在连接模型…'
  isSending.value = true
  if (restoreAssistant) {
    messages.value = messages.value.filter((item) => item.id !== restoreAssistant.id)
  }

  try {
    await api.chatStream(currentSessionId.value, prompt, selectedModel.value, (event) => {
      if (event.type === 'status') {
        streamingStatus.value = event.message || 'agent 正在处理…'
        return
      }
      if (event.type === 'token') {
        if (!assistantCreated) {
          messages.value.push({
            id: assistantId,
            role: 'assistant',
            content: '',
            streaming: true
          })
          assistantCreated = true
        }
        assistantText += event.content || ''
        const target = messages.value.find((item) => item.id === assistantId)
        if (target) target.content = assistantText
        streamingStatus.value = '正在生成回答…'
        return
      }
      if (event.type === 'done') {
        doneEvent = event
        const finalText = event.answer || assistantText
        if (!assistantCreated) {
          messages.value.push({
            id: assistantId,
            role: 'assistant',
            content: finalText,
            streaming: false
          })
          assistantCreated = true
        } else {
          const target = messages.value.find((item) => item.id === assistantId)
          if (target) {
            target.content = finalText
            target.streaming = false
          }
        }
        if (event.session) updateSession(event.session)
        return
      }
      if (event.type === 'error') {
        throw new Error(event.message || '流式对话失败')
      }
    })

    if (!doneEvent) {
      throw new Error('流式连接结束，但没有收到完成事件')
    }

    try {
      await refreshSessionList()
    } catch (refreshError) {
      console.warn('刷新会话列表失败', refreshError)
    }
  } catch (err) {
    messages.value = messages.value.filter(
      (item) => item.id !== temporaryUserId && item.id !== assistantId
    )
    if (restoreAssistant) messages.value.push(restoreAssistant)
    if (restoreDraft) draft.value = restoreDraft
    error.value = err.message
  } finally {
    isSending.value = false
    streamingStatus.value = ''
  }
}

async function send() {
  const message = draft.value.trim()
  if (!message || isSending.value) return

  if (!currentSessionId.value) {
    await createSession()
    if (!currentSessionId.value) return
  }

  lastPrompt.value = message
  const temporaryId = `local-${Date.now()}`
  messages.value.push({ id: temporaryId, role: 'user', content: message })
  draft.value = ''
  await streamAssistantReply(message, {
    temporaryUserId: temporaryId,
    restoreDraft: message
  })
}

async function regenerateMessage(assistantId) {
  if (isSending.value) return
  const assistantIndex = messages.value.findIndex((item) => item.id === assistantId)
  if (assistantIndex < 0) return
  let prompt = ''
  for (let index = assistantIndex - 1; index >= 0; index -= 1) {
    if (messages.value[index].role === 'user') {
      prompt = messages.value[index].content || ''
      break
    }
  }
  if (!prompt.trim()) return
  lastPrompt.value = prompt
  const oldAssistant = messages.value[assistantIndex]
  await streamAssistantReply(prompt, { restoreAssistant: oldAssistant })
}

async function sendQuick(prompt) {
  draft.value = prompt
  await send()
}

function retry() {
  if (draft.value.trim()) send()
}

async function discussHotspot({ title, platform }) {
  const safeTitle = String(title || '').replace(/\s+/g, ' ').trim().slice(0, 30)
  const created = await createSession(`热点讨论：${safeTitle}`)
  if (!created) return
  activeView.value = 'chat'
  draft.value = `请结合热点面板中的「${title}」（平台：${platform}）分析这个话题，并给出可执行的内容创意。`
  closeOverlays()
  await send()
}

function openSettings() {
  sidebarOpen.value = false
  telemetryOpen.value = false
  settingsOpen.value = true
}

async function handleSettingsSaved() {
  try {
    await loadStatus()
    await refreshSessions()
  } catch (err) {
    error.value = err.message
  }
}

function switchView(view) {
  activeView.value = view
  closeOverlays()
}

function closeOverlays() {
  sidebarOpen.value = false
  telemetryOpen.value = false
  settingsOpen.value = false
}

function handleResize() {
  if (window.innerWidth > 820) sidebarOpen.value = false
  if (window.innerWidth > 1180) telemetryOpen.value = false
}

watch(selectedModel, (model) => {
  if (model) window.localStorage.setItem('mybot.selectedModel', model)
})

onMounted(() => {
  bootstrap()
  window.addEventListener('resize', handleResize)
})

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
})
</script>