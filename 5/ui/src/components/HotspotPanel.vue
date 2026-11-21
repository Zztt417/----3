<template>
  <section class="hotspot-panel" :class="{ 'is-collapsed': collapsed, 'is-expanded': expanded }">
    <header class="hotspot-head">
      <div class="hotspot-title">
        <div class="hotspot-eyebrow-row">
          <p class="eyebrow">TREND RADAR</p>
          <span v-if="snapshot?.stale" class="stale-chip mono">CACHED</span>
        </div>
        <h2>热点灵感</h2>
        <p class="hotspot-sub">抖音 · B站 · 小红书 · 微博</p>
      </div>
      <div class="hotspot-actions">
        <span class="hotspot-updated mono">{{ updatedLabel }}</span>
        <button class="ghost-button" type="button" :disabled="loading || refreshing" @click="load(true)">
          {{ refreshing ? '生成中…' : '刷新' }}
        </button>
        <button v-if="!expanded" class="ghost-button" type="button" @click="collapsed = !collapsed">
          {{ collapsed ? '展开' : '收起' }}
        </button>
      </div>
    </header>

    <div v-if="!collapsed" class="hotspot-body">
      <div v-if="loading" class="hotspot-loading">
        <span class="loading-ring" aria-hidden="true"></span>
        正在获取热点并生成 AI 分析…
      </div>

      <div v-else-if="error && !snapshot" class="hotspot-error">
        <span>{{ error }}</span>
        <button type="button" @click="load(true)">重试</button>
      </div>

      <template v-else-if="snapshot">
        <nav class="platform-tabs" aria-label="热点平台">
          <button
            v-for="platform in snapshot.platforms"
            :key="platform.id"
            type="button"
            :class="{ active: platform.id === activePlatformId }"
            @click="activePlatformId = platform.id"
          >
            <span>{{ platform.name }}</span>
            <span v-if="platform.maintenance" class="tab-count maintenance-count">维护</span>
            <span v-else class="tab-count mono">{{ platform.items.length }}</span>
          </button>
        </nav>

        <div v-if="activePlatform" class="hotspot-content">
          <div v-if="activePlatform.maintenance" class="platform-maintenance">
            <span class="maintenance-mark" aria-hidden="true">!</span>
            <div>
              <strong>服务器正在维护</strong>
              <p>小红书热点数据暂不可用，其他平台和对话功能不受影响。</p>
            </div>
          </div>

          <div v-else-if="activePlatform.error && !activePlatform.items.length" class="platform-error">
            {{ activePlatform.name }} 暂时不可用：{{ activePlatform.error }}
          </div>

          <div v-else class="hotspot-grid">
            <article v-for="item in activePlatform.items" :key="item.id" class="hotspot-card">
              <div class="hotspot-card-head">
                <span class="hotspot-rank mono">#{{ item.rank }}</span>
                <span class="level-badge" :class="levelClass(item.level)">{{ item.level }}</span>
              </div>
              <a
                class="hotspot-title-link"
                :href="item.url"
                target="_blank"
                rel="noopener noreferrer"
              >
                {{ item.title }}
              </a>
              <p class="hotspot-comment">{{ item.comment }}</p>
              <div class="hotspot-card-foot">
                <div class="hotspot-tags">
                  <span v-for="tag in item.tags" :key="tag">#{{ tag }}</span>
                </div>
                <button class="discuss-button" type="button" @click="$emit('discuss', { title: item.title, platform: item.platform })">
                  讨论
                </button>
              </div>
            </article>
          </div>
        </div>

        <div class="inspiration-block">
          <div class="inspiration-head">
            <div>
              <p class="eyebrow">INSPIRATION</p>
              <h3>基于热点的灵感</h3>
            </div>
            <span class="inspiration-count mono">{{ recommendations.length }} 条</span>
          </div>
          <div v-if="recommendations.length" class="inspiration-grid">
            <article v-for="recommendation in recommendations" :key="recommendation.title" class="inspiration-card">
              <div class="inspiration-meta mono">
                <span>{{ recommendation.platform }}</span>
                <span>{{ recommendation.format }}</span>
              </div>
              <strong>{{ recommendation.title }}</strong>
              <p>{{ recommendation.reason }}</p>
              <button class="discuss-button" type="button" @click="$emit('discuss', { title: recommendation.title, platform: recommendation.platform })">
                继续讨论
              </button>
            </article>
          </div>
          <p v-else class="hotspot-empty">暂无灵感推荐。</p>
        </div>

        <p v-if="snapshot.warnings?.length" class="hotspot-inline-error">
          {{ snapshot.warnings.join('；') }}
        </p>
        <p v-if="error" class="hotspot-inline-error">{{ error }}</p>
      </template>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'

const props = defineProps({
  expanded: { type: Boolean, default: false }
})

defineEmits(['discuss'])

const snapshot = ref(null)
const loading = ref(true)
const refreshing = ref(false)
const error = ref('')
const collapsed = ref(false)
const activePlatformId = ref('')

const activePlatform = computed(
  () => snapshot.value?.platforms?.find((platform) => platform.id === activePlatformId.value) || null
)
const recommendations = computed(() => snapshot.value?.recommendations || [])
const updatedLabel = computed(() => {
  if (!snapshot.value?.generated_at) return '等待数据'
  return `更新于 ${formatTime(snapshot.value.generated_at)}`
})

async function load(force = false) {
  if (force) {
    refreshing.value = true
  } else {
    loading.value = true
  }
  error.value = ''
  try {
    const data = force ? await api.refreshHotspots() : await api.hotspots()
    snapshot.value = data
    if (!activePlatformId.value || !data.platforms?.some((platform) => platform.id === activePlatformId.value)) {
      activePlatformId.value = data.platforms?.[0]?.id || ''
    }
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
    refreshing.value = false
  }
}

function levelClass(level) {
  if (level === '高') return 'level-high'
  if (level === '中') return 'level-mid'
  return 'level-low'
}

function formatTime(value) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value || '')
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  }).format(date)
}

onMounted(() => load(false))
</script>