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
        <article
          v-for="message in messages"
          :key="message.id"
          class="message"
          :class="message.role"
        >
          <div class="message-meta mono">
            <span>{{ message.role === 'user' ? 'YOU' : 'AGENT' }}</span>
            <span>{{ message.role === 'user' ? 'LOCAL' : 'FINAL' }}</span>
          </div>
          <div class="message-body markdown" v-html="renderMarkdown(message.content)"></div>
        </article>

        <div v-if="isSending" class="thinking" aria-live="polite">
          <span class="thinking-dots" aria-hidden="true"><i></i><i></i><i></i></span>
          <em>agent 正在调度工具</em>
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
  loading: { type: Boolean, default: false }
})

const emit = defineEmits(['update:draft', 'send', 'quick-send', 'retry', 'toggle-telemetry'])

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

watch(() => [props.messages.length, props.isSending, props.loading], scrollToBottom)
watch(() => props.draft, () => nextTick(resizeTextarea))
</script>