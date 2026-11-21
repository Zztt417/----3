<template>
  <aside class="session-rail" :class="{ 'is-open': open }">
    <div class="rail-head">
      <div>
        <p class="eyebrow">CONVERSATIONS</p>
        <h2>会话</h2>
      </div>
      <button
        class="icon-button"
        type="button"
        :disabled="busy"
        title="新建会话"
        aria-label="新建会话"
        @click="$emit('create')"
      >
        +
      </button>
    </div>

    <button class="new-session" type="button" :disabled="busy" @click="$emit('create')">
      <span class="new-session-plus" aria-hidden="true">+</span>
      新建对话
    </button>

    <div class="session-list" role="list">
      <div
        v-for="session in sessions"
        :key="session.id"
        class="session-item"
        :class="{ 'is-active': session.id === currentId }"
        role="listitem"
      >
        <button
          class="session-select"
          type="button"
          :disabled="busy"
          @click="$emit('select', session.id)"
        >
          <span class="session-indicator" aria-hidden="true"></span>
          <span class="session-copy">
            <strong>{{ session.display_title || session.title || '未命名会话' }}</strong>
            <small>{{ formatTime(session.updated_at) }} · {{ session.memory_count }} 条记忆</small>
          </span>
        </button>
        <button
          v-if="sessions.length > 1"
          class="session-delete"
          type="button"
          title="删除会话"
          :aria-label="`删除会话：${session.display_title || '未命名会话'}`"
          @click.stop="$emit('delete', session.id)"
        >
          ×
        </button>
      </div>

      <p v-if="!sessions.length" class="rail-empty">还没有会话。</p>
    </div>

    <div class="rail-foot">
      <span class="foot-line" aria-hidden="true"></span>
      <p class="eyebrow">LOCAL MEMORY</p>
      <p>每个会话独立检索。跨会话需要明确询问。</p>
    </div>
  </aside>
</template>

<script setup>
defineProps({
  sessions: { type: Array, default: () => [] },
  currentId: { type: String, default: '' },
  open: { type: Boolean, default: false },
  busy: { type: Boolean, default: false }
})

defineEmits(['select', 'create', 'delete'])

function formatTime(value) {
  if (!value) return '刚刚'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value).slice(0, 16).replace('T', ' ')
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  }).format(date)
}
</script>