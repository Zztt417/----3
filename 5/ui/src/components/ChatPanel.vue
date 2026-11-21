<template>
  <section class="chat-panel">
    <header class="chat-head">
      <div class="chat-title">
        <p class="eyebrow">ACTIVE THREAD</p>
        <div class="chat-title-row">
          <h2>{{ session?.title || '新对话' }}</h2>
          <span class="memory-chip">{{ session?.memory_count ?? 0 }} 条记忆</span>
        </div>
        <p class="session-id mono">{{ session?.id || 'NO SESSION' }}</p>
      </div>
      <button class="ghost-button telemetry-toggle" type="button" @click="$emit('toggle-telemetry')">
        状态
      </button>
    </header>

    <div class="signal-trace" :class="{ 'is-active': isSending }" aria-hidden="true"></div>

    <div ref="scrollArea" class="chat-scroll">
      <div v-if="loading" class="loading-state">
        <span class="loading-ring" aria-hidden="true"></span>
        正在同步会话…
      </div>

      <div v-else-if="!messages.length" class="empty-state">
        <p class="eyebrow">READY WHEN YOU ARE</p>
        <h3>先从一个<br /><em>具体任务</em>开始。</h3>
        <p class="empty-copy">
          它能读写文件、联网搜索、解析 PDF，也会在值得记住时写入当前会话的长期记忆。
        </p>

        <div class="prompt-grid">
          <button
            v-for="prompt in quickPrompts"
            :key="prompt.tag"
            class="prompt-card"
            type="button"
            @click="$emit('quick-send', prompt.text)"
          >
            <span class="prompt-tag mono">{{ prompt.tag }}</span>
            <strong>{{ prompt.title }}</strong>
            <span class="prompt-text">{{ prompt.text }}</span>
          </button>
        </div>
      </div>

      <div v-else class="message-stack" aria-live="polite">
        <div
          v-for="(message, index) in messages"
          :key="message.id"
          class="message-row"
          :class="message.role"
        >
          <div v-if="message.role === 'assistant'" class="message-avatar agent-avatar">
            <img src="/favicon.png?v=20261114" alt="Agent" />
          </div>

          <article class="message" :class="[message.role, { streaming: message.streaming }]">
            <div class="message-meta mono">
              <span>{{ message.role === 'user' ? 'YOU' : 'AGENT' }}</span>
              <span>{{ message.role === 'user' ? 'LOCAL' : 'FINAL' }}</span>
            </div>
            <div class="message-body markdown" v-html="renderMarkdown(message.content)"></div>
            <div v-if="message.role === 'assistant'" class="message-actions">
              <button
                class="message-action-button"
                type="button"
                :disabled="message.streaming || !message.content"
                @click="copyMessage(message)"
              >
                {{ copiedId === message.id ? "已复制" : "复制" }}
              </button>
              <button
                class="message-action-button"
                type="button"
                :disabled="isSending || message.streaming || !isLastAssistant(index)"
                @click="$emit('regenerate', message.id)"
              >
                重新生成
              </button>
            </div>
          </article>

          <div v-if="message.role === 'user'" class="message-avatar user-avatar" aria-label="You">
            You
          </div>
        </div>

        <div v-if="isSending" class="thinking" aria-live="polite">
          <span class="thinking-dots" aria-hidden="true"><i></i><i></i><i></i></span>
          <em>{{ streamingStatus || 'agent 正在调度工具' }}</em>
        </div>
      </div>

      <div v-if="error" class="error-banner" role="alert">
        <span>{{ error }}</span>
        <button type="button" @click="$emit('retry')">重试</button>
      </div>
    </div>

    <form class="composer" @submit.prevent="$emit('send')">
      <div class="composer-shell">
        <textarea
          ref="textarea"
          :value="draft"
          rows="1"
          maxlength="20000"
          placeholder="给 agent 一个任务…"
          aria-label="消息输入"
          @input="$emit('update:draft', $event.target.value)"
          @keydown="onKeydown"
        ></textarea>
        <div class="composer-actions">
          <span class="composer-hint mono">ENTER 发送 · SHIFT+ENTER 换行</span>
          <button class="send-button" type="submit" :disabled="!draft.trim() || isSending">
            {{ isSending ? '运行中' : '发送' }}
            <span aria-hidden="true">↗</span>
          </button>
        </div>
      </div>
      <div class="model-switcher">
        <span class="model-switcher-label">
          <span class="mono">MODEL</span>
          当前对话模型
        </span>
        <select
          :value="selectedModel"
          :disabled="isSending || !models.length"
          aria-label="选择对话模型"
          @change="$emit('update:selected-model', $event.target.value)"
        >
          <option v-for="model in models" :key="model" :value="model">{{ model }}</option>
          <option v-if="!models.length" value="">未配置模型</option>
        </select>
      </div>
    </form>
  </section>
</template>

<script setup>
import { nextTick, ref, watch } from 'vue'
import { renderMarkdown } from '../markdown'

const props = defineProps({
  session: { type: Object, default: null },
  messages: { type: Array, default: () => [] },
  draft: { type: String, default: '' },
  isSending: { type: Boolean, default: false },
  error: { type: String, default: '' },
  streamingStatus: { type: String, default: '' },
  loading: { type: Boolean, default: false },
  models: { type: Array, default: () => [] },
  selectedModel: { type: String, default: '' }
})

const emit = defineEmits([
  'update:draft',
  'send',
  'quick-send',
  'retry',
  'regenerate',
  'toggle-telemetry',
  'update:selected-model'
])

const quickPrompts = [
  {
    tag: 'READ',
    title: '梳理项目',
    text: '读取当前目录，告诉我这个项目由哪些模块组成'
  },
  {
    tag: 'REMEMBER',
    title: '记住偏好',
    text: '记住：回答时先说结论，代码保持简洁可维护'
  },
  {
    tag: 'SEARCH',
    title: '联网调研',
    text: '搜索 Vue 3 + FastAPI 本地 Agent 前端的最佳实践'
  }
]

const scrollArea = ref(null)
const textarea = ref(null)
const copiedId = ref('')


function isLastAssistant(index) {
  return !props.messages.slice(index + 1).some((message) => message.role === 'assistant')
}

async function copyMessage(message) {
  const content = message.content || ''
  if (!content) return
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(content)
    } else {
      const textarea = document.createElement('textarea')
      textarea.value = content
      textarea.style.position = 'fixed'
      textarea.style.opacity = '0'
      document.body.appendChild(textarea)
      textarea.select()
      document.execCommand('copy')
      document.body.removeChild(textarea)
    }
    copiedId.value = message.id
    window.setTimeout(() => {
      if (copiedId.value === message.id) copiedId.value = ''
    }, 1600)
  } catch {
    // 剪贴板不可用时保持静默，用户仍可手动选择文本
  }
}

function scrollToBottom() {
  nextTick(() => {
    const element = scrollArea.value
    if (element) element.scrollTop = element.scrollHeight
  })
}

function resizeTextarea() {
  const element = textarea.value
  if (!element) return
  element.style.height = 'auto'
  element.style.height = `${Math.min(element.scrollHeight, 180)}px`
}

function onKeydown(event) {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault()
    emit('send')
  }
}

watch(
  () => [
    props.messages.length,
    props.messages.map((message) => (message.content || '').length).join(','),
    props.isSending,
    props.loading
  ],
  scrollToBottom
)
watch(() => props.draft, () => nextTick(resizeTextarea))
</script>