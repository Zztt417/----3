<template>
  <aside class="telemetry-panel" :class="{ 'is-open': open }">
    <div class="telemetry-head">
      <div>
        <p class="eyebrow">SYSTEM TELEMETRY</p>
        <h2>运行状态</h2>
      </div>
      <button class="icon-button telemetry-close" type="button" aria-label="关闭状态面板" @click="$emit('close')">
        ×
      </button>
    </div>

    <div class="telemetry-card status-card">
      <div class="telemetry-status">
        <span class="status-dot" :class="statusTone"></span>
        <div>
          <strong>{{ statusLabel }}</strong>
          <small>{{ status?.startup_error || (status ? 'FastAPI bridge online' : 'connecting…') }}</small>
        </div>
      </div>
      <div class="signal-line" :class="{ 'is-active': busy }" aria-hidden="true">
        <span></span>
      </div>
    </div>

    <div class="telemetry-card">
      <p class="eyebrow">MODEL</p>
      <p class="telemetry-value mono">{{ status?.model || '—' }}</p>
      <p class="telemetry-muted break-all">{{ status?.base_url || '等待连接' }}</p>
    </div>

    <div class="telemetry-card">
      <p class="eyebrow">MEMORY</p>
      <div class="metric-row">
        <span>Long-term</span>
        <strong>{{ status?.long_term_enabled ? 'ON' : 'OFF' }}</strong>
      </div>
      <div class="metric-row">
        <span>This session</span>
        <strong>{{ session?.memory_count ?? 0 }}</strong>
      </div>
      <div class="metric-row">
        <span>Window</span>
        <strong>{{ status?.short_term_keep ?? '—' }} / {{ status?.short_term_max ?? '—' }}</strong>
      </div>
    </div>

    <div class="telemetry-card">
      <p class="eyebrow">TOOLS</p>
      <div class="tool-cloud">
        <span v-for="tool in status?.tools || []" :key="tool" class="tool-chip mono">{{ tool }}</span>
        <span v-if="!(status?.tools || []).length" class="telemetry-muted">未加载</span>
      </div>
    </div>

    <div class="telemetry-card telemetry-note">
      <p class="eyebrow">SESSION</p>
      <p class="mono session-id">{{ session?.id || '—' }}</p>
      <p class="telemetry-muted">Short-term JSONL · Chroma vector memory</p>
      <p v-if="status?.mcp_tools?.length" class="telemetry-muted">MCP · {{ status.mcp_tools.join(', ') }}</p>
    </div>

    <div v-if="status?.warnings?.length" class="telemetry-card telemetry-warning">
      <p class="eyebrow">NOTES</p>
      <p v-for="warning in status.warnings" :key="warning">{{ warning }}</p>
    </div>
  </aside>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  status: { type: Object, default: null },
  session: { type: Object, default: null },
  busy: { type: Boolean, default: false },
  open: { type: Boolean, default: false }
})

defineEmits(['close'])

const statusTone = computed(() => {
  if (!props.status) return 'is-pending'
  if (props.status.startup_error || props.status.status === 'degraded') return 'is-danger'
  return 'is-ok'
})

const statusLabel = computed(() => {
  if (!props.status) return '连接中'
  if (props.status.startup_error) return '需要配置'
  if (props.status.status === 'degraded') return '降级运行'
  if (props.status.long_term_enabled) return '记忆在线'
  if (props.status.memory_enabled) return '短期记忆'
  return '基础模式'
})
</script>