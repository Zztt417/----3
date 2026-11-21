<template>
  <div v-if="open" class="settings-modal" role="dialog" aria-modal="true" aria-labelledby="settings-title">
    <section class="settings-card" :class="{ 'is-skills': activeTab !== 'api' }">
      <header class="settings-head">
        <div>
          <p class="eyebrow">CONTROL CENTER</p>
          <h2 id="settings-title">设置</h2>
        </div>
        <button
          class="icon-button settings-close"
          type="button"
          aria-label="关闭设置"
          :disabled="saving || testing"
          @click="$emit('close')"
        >
          ×
        </button>
      </header>

      <div class="settings-tabs" role="tablist" aria-label="设置分类">
        <button type="button" :class="{ active: activeTab === 'api' }" @click="activeTab = 'api'">
          模型 API
        </button>
        <button type="button" :class="{ active: activeTab === 'skills' }" @click="selectSkillsTab">
          Skills
        </button>
        <button type="button" :class="{ active: activeTab === 'mcp' }" @click="selectMcpTab">
          MCP
        </button>
      </div>

      <template v-if="activeTab === 'api'">
        <p class="settings-intro">
          选择服务商和模型后，接口地址由后台自动匹配，只需填写对应平台的 API Key。
        </p>

        <div class="settings-source">
          <span class="status-dot" :class="settings?.api_key_configured ? 'is-ok' : 'is-danger'"></span>
          <div>
            <strong>{{ sourceLabel }}</strong>
            <small>{{ settings?.config_path || '正在读取本机配置…' }}</small>
          </div>
        </div>

        <form class="settings-form" @submit.prevent="save">
          <label class="settings-field">
            <span>服务商 / 模型</span>
            <select v-model="selection" :disabled="saving || testing">
              <optgroup v-for="provider in providers" :key="provider.id" :label="provider.name">
                <option
                  v-for="model in provider.models"
                  :key="`${provider.id}|${model}`"
                  :value="`${provider.id}|${model}`"
                >
                  {{ model }}
                </option>
              </optgroup>
            </select>
          </label>

          <div class="settings-endpoint">
            <span>BASE URL · 自动匹配</span>
            <code>{{ selectedProvider?.base_url || '—' }}</code>
          </div>

          <label class="settings-field">
            <span>LLM API Key</span>
            <input
              v-model="form.api_key"
              type="password"
              :placeholder="settings?.api_key_configured ? `已配置 ${settings.api_key_hint}，留空保持不变` : '请输入当前服务商的 API Key'"
              autocomplete="new-password"
              :disabled="saving || testing"
            />
          </label>

          <p class="settings-hint">
            Key 只保存在本机配置文件中，不会返回给页面。Ollama 本地服务会自动使用 `local` 作为占位 Key。
          </p>

          <p v-if="feedback" class="settings-feedback" :class="feedback.tone">
            {{ feedback.message }}
          </p>

          <footer class="settings-actions">
            <button
              class="settings-button secondary"
              type="button"
              :disabled="saving || testing || !settings?.settings_editable"
              @click="test"
            >
              {{ testing ? '测试中…' : '测试连接' }}
            </button>
            <span class="settings-spacer"></span>
            <button class="settings-button ghost" type="button" :disabled="saving || testing" @click="$emit('close')">
              取消
            </button>
            <button class="settings-button primary" type="submit" :disabled="saving || testing || !settings?.settings_editable">
              {{ saving ? '保存中…' : '保存并应用' }}
            </button>
          </footer>
        </form>
      </template>

      <template v-else-if="activeTab === 'skills'">
        <p class="settings-intro">
          安装和管理标准 <code>SKILL.md</code> 技能。Agent 只会注入与当前问题匹配的已启用 Skills。
        </p>

        <div class="skills-search-row">
          <input v-model="skillsQuery" type="search" placeholder="搜索已安装 Skills…" @keyup.enter="loadSkills" />
          <button class="settings-button secondary" type="button" :disabled="skillsLoading" @click="refreshSkills">
            {{ skillsLoading ? '扫描中…' : '刷新' }}
          </button>
        </div>
        <p class="settings-hint break-all">目录：{{ skillsDir || '~/.mybot/skills' }}</p>

        <p v-if="skillFeedback" class="settings-feedback" :class="skillFeedback.tone">
          {{ skillFeedback.message }}
        </p>

        <div class="skills-list">
          <article v-for="skill in skills" :key="skill.id" class="skill-card">
            <div class="skill-card-main">
              <div class="skill-card-head">
                <strong>{{ skill.name }}</strong>
                <span class="skill-status" :class="{ enabled: skill.enabled }">
                  {{ skill.enabled ? '已启用' : '已停用' }}
                </span>
              </div>
              <p>{{ skill.description || '暂无描述' }}</p>
              <div class="skill-tags">
                <span v-for="tag in skill.tags" :key="tag">{{ tag }}</span>
                <span v-if="skill.version" class="skill-version">v{{ skill.version }}</span>
              </div>
            </div>
            <div class="skill-actions">
              <button type="button" @click="openSkill(skill.id)">详情</button>
              <button type="button" @click="toggleSkill(skill)">{{ skill.enabled ? '停用' : '启用' }}</button>
              <button class="danger" type="button" @click="removeSkill(skill)">删除</button>
            </div>
          </article>
          <p v-if="!skillsLoading && !skills.length" class="settings-hint">还没有安装 Skills。</p>
        </div>

        <section class="skills-market">
          <div class="skills-market-head">
            <div>
              <p class="eyebrow">REMOTE CATALOG</p>
              <h3>技能市场</h3>
            </div>
            <div class="skills-market-actions">
              <select v-model="catalogSource">
                <option value="openai">OpenAI Skills</option>
                <option value="anthropic">Anthropic Skills</option>
              </select>
              <button class="settings-button secondary" type="button" :disabled="catalogLoading" @click="loadCatalog">
                {{ catalogLoading ? '加载中…' : '浏览目录' }}
              </button>
            </div>
          </div>

          <div class="catalog-list">
            <div v-for="item in catalog" :key="`${item.repo}/${item.path}`" class="catalog-item">
              <div>
                <strong>{{ item.name }}</strong>
                <small>{{ item.repo }}/{{ item.path }}</small>
              </div>
              <button class="settings-button secondary" type="button" :disabled="skillInstalling" @click="installCatalog(item)">
                {{ skillInstalling ? '安装中…' : '安装' }}
              </button>
            </div>
            <p v-if="!catalogLoading && !catalog.length" class="settings-hint">点击“浏览目录”加载官方 Skills。</p>
          </div>
        </section>

        <form class="manual-skill-form" @submit.prevent="installManual">
          <p class="eyebrow">MANUAL INSTALL</p>
          <div class="manual-skill-grid">
            <input v-model.trim="manual.repo" placeholder="owner/repo" required />
            <input v-model.trim="manual.path" placeholder="skills/.curated/pdf" required />
            <input v-model.trim="manual.ref" placeholder="main" />
            <button class="settings-button primary" type="submit" :disabled="skillInstalling">
              {{ skillInstalling ? '安装中…' : '从 GitHub 安装' }}
            </button>
          </div>
        </form>

        <p class="settings-hint">
          技能内容是外部输入，请在安装前查看详情；本项目不会自动执行 Skill 里的脚本。
        </p>

        <div v-if="selectedSkill" class="skill-detail">
          <div class="skill-detail-head">
            <div>
              <p class="eyebrow">SKILL PREVIEW</p>
              <h3>{{ selectedSkill.name }}</h3>
            </div>
            <button class="icon-button" type="button" @click="selectedSkill = null">×</button>
          </div>
          <p class="settings-hint">{{ selectedSkill.path }}</p>
          <div class="skill-tags">
            <span v-for="tag in selectedSkill.tags" :key="tag">{{ tag }}</span>
          </div>
          <pre class="skill-content">{{ selectedSkill.content }}</pre>
          <p class="settings-hint">文件：{{ selectedSkill.files?.join(' · ') || 'SKILL.md' }}</p>
        </div>
      </template>
      <template v-else>
        <p class="settings-intro">
          从官方 MCP Registry 搜索服务，安装后可自动注册为 <code>mcp__服务__工具</code>。外部 MCP 工具默认需要本机配置和用户确认。
        </p>

        <div class="mcp-search-row">
          <input
            v-model.trim="mcpQuery"
            type="search"
            placeholder="搜索 MCP Registry，例如 github、filesystem…"
            @keyup.enter="searchMcp"
          />
          <button class="settings-button secondary" type="button" :disabled="mcpSearchLoading" @click="searchMcp">
            {{ mcpSearchLoading ? '搜索中…' : '搜索 Registry' }}
          </button>
          <button class="settings-button ghost" type="button" :disabled="mcpServersLoading" @click="loadMcpServers">
            {{ mcpServersLoading ? '刷新中…' : '刷新已安装' }}
          </button>
        </div>

        <p v-if="mcpFeedback" class="settings-feedback" :class="mcpFeedback.tone">
          {{ mcpFeedback.message }}
        </p>

        <section class="mcp-installed">
          <div class="mcp-section-head">
            <div>
              <p class="eyebrow">INSTALLED</p>
              <h3>已安装 MCP</h3>
            </div>
            <span class="mcp-count">{{ mcpServers.length }}</span>
          </div>
          <div class="mcp-server-list">
            <article v-for="server in mcpServers" :key="server.id" class="mcp-server-card">
              <div class="mcp-server-main">
                <div class="mcp-server-title">
                  <strong>{{ server.name || server.id }}</strong>
                  <span class="mcp-status" :class="{ connected: server.connected }">
                    {{ server.connected ? '已连接' : server.enabled ? '未连接' : '已停用' }}
                  </span>
                </div>
                <p>{{ server.registry_name || server.id }} · {{ server.transport }} · v{{ server.version || '—' }}</p>
                <div class="skill-tags">
                  <span v-for="name in server.tool_names" :key="name">{{ name }}</span>
                </div>
                <p v-if="server.error" class="mcp-server-error">{{ server.error }}</p>
              </div>
              <div class="skill-actions">
                <button type="button" @click="toggleMcp(server)">{{ server.enabled ? '停用' : '启用' }}</button>
                <button type="button" :disabled="!server.enabled" @click="restartMcp(server)">重启</button>
                <button class="danger" type="button" @click="removeMcp(server)">删除</button>
              </div>
            </article>
            <p v-if="!mcpServersLoading && !mcpServers.length" class="settings-hint">还没有安装 MCP 服务。</p>
          </div>
        </section>

        <section class="mcp-registry">
          <div class="mcp-section-head">
            <div>
              <p class="eyebrow">OFFICIAL REGISTRY</p>
              <h3>MCP Registry</h3>
            </div>
            <span class="mcp-count">{{ mcpResults.length }}</span>
          </div>
          <div class="mcp-result-list">
            <article v-for="server in mcpResults" :key="server.name" class="mcp-result-card">
              <div class="mcp-result-main">
                <strong>{{ server.title || server.name }}</strong>
                <p>{{ server.description || '暂无描述' }}</p>
                <small>{{ server.name }} · v{{ server.version || '—' }}</small>
                <div class="mcp-badges">
                  <span v-if="server.remotes?.length">remote</span>
                  <span v-if="server.packages?.length">package</span>
                  <span v-if="server.repository?.url">source</span>
                </div>
              </div>
              <button class="settings-button secondary" type="button" @click="openMcpDetail(server)">配置安装</button>
            </article>
            <p v-if="!mcpSearchLoading && !mcpResults.length" class="settings-hint">输入关键词搜索官方 Registry。</p>
          </div>
        </section>

        <div v-if="mcpSelected" class="mcp-detail">
          <div class="mcp-detail-head">
            <div>
              <p class="eyebrow">INSTALL CONFIGURATION</p>
              <h3>{{ mcpSelected.title || mcpSelected.name }}</h3>
            </div>
            <button class="icon-button" type="button" @click="mcpSelected = null">×</button>
          </div>
          <p class="settings-hint">{{ mcpSelected.description || '暂无描述' }}</p>

          <label class="settings-field">
            <span>连接方式</span>
            <select v-model="mcpTransport" @change="resetMcpInputs">
              <option v-if="mcpRemotes.length" value="streamable-http">Streamable HTTP</option>
              <option v-if="mcpPackages.length" value="stdio">stdio / 本地包</option>
            </select>
          </label>

          <template v-if="mcpTransport === 'stdio'">
            <label class="settings-field">
              <span>安装包</span>
              <select v-model.number="mcpPackageIndex" @change="resetMcpInputs">
                <option v-for="(pkg, index) in mcpPackages" :key="`${pkg.identifier}-${index}`" :value="index">
                  {{ pkg.registryType }} · {{ pkg.identifier }}@{{ pkg.version }}
                </option>
              </select>
            </label>
            <p class="settings-hint">
              {{ selectedMcpPackage?.runtimeHint || 'runtime' }} {{ selectedMcpPackage?.identifier || '' }}
            </p>
            <label v-for="field in mcpEnvFields" :key="field.name" class="settings-field">
              <span>{{ field.name }}{{ field.isRequired ? ' *' : '' }}</span>
              <input
                v-model="mcpEnvValues[field.name]"
                :type="field.isSecret ? 'password' : 'text'"
                :placeholder="field.description || field.default || ''"
              />
            </label>
          </template>

          <template v-else>
            <label class="settings-field">
              <span>远程端点</span>
              <select v-model.number="mcpRemoteIndex" @change="resetMcpInputs">
                <option v-for="(remote, index) in mcpRemotes" :key="`${remote.url}-${index}`" :value="index">
                  {{ remote.url }}
                </option>
              </select>
            </label>
            <label v-for="field in mcpHeaderFields" :key="field.name" class="settings-field">
              <span>{{ field.name }}{{ field.isRequired ? ' *' : '' }}</span>
              <input
                v-model="mcpHeaderValues[field.name]"
                :type="field.isSecret ? 'password' : 'text'"
                :placeholder="field.description || field.value || ''"
              />
            </label>
          </template>

          <label class="settings-field">
            <span>工具白名单（可选，逗号分隔）</span>
            <input v-model.trim="mcpToolsInput" placeholder="留空表示暴露该服务全部工具" />
          </label>

          <p class="settings-hint">
            MCP 工具来自外部服务，安装前请确认来源、命令和凭据。不会自动执行未确认的启动命令。
          </p>

          <div class="settings-actions">
            <span class="settings-spacer"></span>
            <button class="settings-button ghost" type="button" @click="mcpSelected = null">取消</button>
            <button class="settings-button primary" type="button" :disabled="mcpInstalling" @click="installSelectedMcp">
              {{ mcpInstalling ? '安装中…' : '安装并连接' }}
            </button>
          </div>
        </div>
      </template>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { api } from '../api'

const props = defineProps({
  open: { type: Boolean, default: false },
  busy: { type: Boolean, default: false }
})

const emit = defineEmits(['close', 'saved'])

const activeTab = ref('api')
const settings = ref(null)
const saving = ref(false)
const testing = ref(false)
const feedback = ref(null)
const selection = ref('')
const form = reactive({ provider_id: '', model: '', api_key: '' })

const skills = ref([])
const skillsDir = ref('')
const skillsQuery = ref('')
const skillsLoading = ref(false)
const skillFeedback = ref(null)
const skillInstalling = ref(false)
const catalogSource = ref('openai')
const catalog = ref([])
const catalogLoading = ref(false)
const selectedSkill = ref(null)
const manual = reactive({ repo: 'openai/skills', path: '', ref: 'main' })

const mcpServers = ref([])
const mcpServersLoading = ref(false)
const mcpQuery = ref('')
const mcpResults = ref([])
const mcpSearchLoading = ref(false)
const mcpFeedback = ref(null)
const mcpSelected = ref(null)
const mcpTransport = ref('streamable-http')
const mcpPackageIndex = ref(0)
const mcpRemoteIndex = ref(0)
const mcpEnvValues = ref({})
const mcpHeaderValues = ref({})
const mcpToolsInput = ref('')
const mcpInstalling = ref(false)

const providers = computed(() => settings.value?.providers || [])
const selectedProvider = computed(() =>
  providers.value.find((provider) => provider.id === form.provider_id) || null
)
const sourceLabel = computed(() => {
  if (!settings.value) return '正在读取配置'
  if (!settings.value.api_key_configured) return '尚未配置模型 API Key'
  return settings.value.source === 'local' ? '已保存本机模型配置' : '已从环境变量读取模型配置'
})

const mcpPackages = computed(() => mcpSelected.value?.packages || [])
const mcpRemotes = computed(() =>
  (mcpSelected.value?.remotes || []).filter((remote) => remote?.type === 'streamable-http')
)
const selectedMcpPackage = computed(() => mcpPackages.value[mcpPackageIndex.value] || null)
const selectedMcpRemote = computed(() => mcpRemotes.value[mcpRemoteIndex.value] || null)
const mcpEnvFields = computed(() => selectedMcpPackage.value?.environmentVariables || [])
const mcpHeaderFields = computed(() => selectedMcpRemote.value?.headers || [])

function setSkillFeedback(message, tone = 'is-info') {
  skillFeedback.value = { message, tone }
}

function makeSelection(providerId, model) {
  return providerId && model ? `${providerId}|${model}` : ''
}

function parseSelection() {
  const [providerId, ...modelParts] = selection.value.split('|')
  form.provider_id = providerId || ''
  form.model = modelParts.join('|')
  if (form.provider_id === 'ollama' && !form.api_key) form.api_key = 'local'
}

function applySettings(data) {
  settings.value = data
  form.provider_id = data.provider_id || data.providers?.[0]?.id || ''
  form.model = data.model || data.providers?.find((item) => item.id === form.provider_id)?.models?.[0] || ''
  form.api_key = ''
  selection.value = makeSelection(form.provider_id, form.model)
}

async function loadSettings() {
  if (!props.open) return
  feedback.value = null
  try {
    applySettings(await api.llmSettings())
  } catch (err) {
    feedback.value = { tone: 'is-error', message: err.message }
  }
}

async function test() {
  if (testing.value || saving.value) return
  testing.value = true
  feedback.value = { tone: 'is-pending', message: '正在测试模型连接…' }
  try {
    const result = await api.testLlmSettings({
      provider_id: form.provider_id,
      model: form.model,
      api_key: form.api_key
    })
    feedback.value = {
      tone: 'is-success',
      message: `连接成功 · ${result.provider_id} / ${result.model} · ${result.latency_ms} ms`
    }
  } catch (err) {
    feedback.value = { tone: 'is-error', message: err.message }
  } finally {
    testing.value = false
  }
}

async function save() {
  if (saving.value || testing.value || props.busy) return
  saving.value = true
  feedback.value = { tone: 'is-pending', message: '正在保存并应用模型配置…' }
  try {
    const result = await api.updateLlmSettings({
      provider_id: form.provider_id,
      model: form.model,
      api_key: form.api_key
    })
    applySettings(result)
    feedback.value = result.applied
      ? { tone: 'is-success', message: '模型配置已保存，新的对话会立即使用该模型。' }
      : { tone: 'is-error', message: result.startup_error || '配置已保存，但 Agent 初始化失败。' }
    emit('saved', result)
  } catch (err) {
    feedback.value = { tone: 'is-error', message: err.message }
  } finally {
    saving.value = false
  }
}

async function selectSkillsTab() {
  activeTab.value = 'skills'
  if (!skills.value.length) await loadSkills()
}

async function loadSkills() {
  skillsLoading.value = true
  skillFeedback.value = null
  try {
    const result = await api.skills(skillsQuery.value.trim())
    skills.value = result.items || []
    skillsDir.value = result.skills_dir || ''
  } catch (err) {
    setSkillFeedback(err.message, 'is-error')
  } finally {
    skillsLoading.value = false
  }
}

async function refreshSkills() {
  skillsLoading.value = true
  skillFeedback.value = null
  try {
    const result = await api.refreshSkills()
    skills.value = (result.items || []).filter((item) => {
      const needle = skillsQuery.value.trim().toLowerCase()
      return !needle || `${item.name} ${item.description} ${(item.tags || []).join(' ')}`.toLowerCase().includes(needle)
    })
    skillsDir.value = result.skills_dir || ''
    setSkillFeedback('Skills 目录已重新扫描。', 'is-success')
  } catch (err) {
    setSkillFeedback(err.message, 'is-error')
  } finally {
    skillsLoading.value = false
  }
}

async function toggleSkill(skill) {
  try {
    const updated = await api.setSkillEnabled(skill.id, !skill.enabled)
    const index = skills.value.findIndex((item) => item.id === skill.id)
    if (index >= 0) skills.value[index] = { ...skills.value[index], ...updated }
    setSkillFeedback(`${updated.name} 已${updated.enabled ? '启用' : '停用'}。`, 'is-success')
  } catch (err) {
    setSkillFeedback(err.message, 'is-error')
  }
}

async function openSkill(skillId) {
  try {
    selectedSkill.value = await api.skillDetail(skillId)
  } catch (err) {
    setSkillFeedback(err.message, 'is-error')
  }
}

async function removeSkill(skill) {
  if (!window.confirm(`删除 Skill「${skill.name}」？`)) return
  try {
    await api.deleteSkill(skill.id)
    skills.value = skills.value.filter((item) => item.id !== skill.id)
    setSkillFeedback(`已删除 ${skill.name}。`, 'is-success')
  } catch (err) {
    setSkillFeedback(err.message, 'is-error')
  }
}

async function loadCatalog() {
  catalogLoading.value = true
  setSkillFeedback('正在读取 GitHub 技能目录…', 'is-pending')
  try {
    const result = await api.skillCatalog(catalogSource.value, skillsQuery.value.trim())
    catalog.value = result.items || []
    setSkillFeedback(`找到 ${catalog.value.length} 个技能。`, 'is-success')
  } catch (err) {
    setSkillFeedback(err.message, 'is-error')
  } finally {
    catalogLoading.value = false
  }
}

async function installCatalog(item) {
  if (skillInstalling.value) return
  skillInstalling.value = true
  setSkillFeedback(`正在安装 ${item.name}…`, 'is-pending')
  try {
    await api.installSkill({ repo: item.repo, path: item.path, ref: item.ref })
    await loadSkills()
    setSkillFeedback(`${item.name} 安装完成。`, 'is-success')
  } catch (err) {
    setSkillFeedback(err.message, 'is-error')
  } finally {
    skillInstalling.value = false
  }
}

async function installManual() {
  if (skillInstalling.value) return
  skillInstalling.value = true
  setSkillFeedback(`正在安装 ${manual.path}…`, 'is-pending')
  try {
    await api.installSkill({ repo: manual.repo, path: manual.path, ref: manual.ref || 'main' })
    manual.path = ''
    await loadSkills()
    setSkillFeedback('Skill 安装完成。', 'is-success')
  } catch (err) {
    setSkillFeedback(err.message, 'is-error')
  } finally {
    skillInstalling.value = false
  }
}

function setMcpFeedback(message, tone = 'is-pending') {
  mcpFeedback.value = { message, tone }
}

async function selectMcpTab() {
  activeTab.value = 'mcp'
  if (!mcpServers.value.length) await loadMcpServers()
}

async function loadMcpServers() {
  mcpServersLoading.value = true
  try {
    const result = await api.mcpServers()
    mcpServers.value = result.items || []
  } catch (err) {
    setMcpFeedback(err.message, 'is-error')
  } finally {
    mcpServersLoading.value = false
  }
}

async function searchMcp() {
  if (mcpQuery.value && mcpQuery.value.length < 3) {
    setMcpFeedback('MCP Registry 搜索词至少需要 3 个字符。', 'is-error')
    return
  }
  mcpSearchLoading.value = true
  setMcpFeedback('正在搜索官方 MCP Registry…', 'is-pending')
  try {
    const result = await api.mcpRegistrySearch(mcpQuery.value)
    mcpResults.value = result.items || []
    setMcpFeedback(`找到 ${mcpResults.value.length} 个 MCP 服务。`, 'is-success')
  } catch (err) {
    setMcpFeedback(err.message, 'is-error')
  } finally {
    mcpSearchLoading.value = false
  }
}

function resetMcpInputs() {
  const env = {}
  for (const field of mcpEnvFields.value) {
    env[field.name] = field.default || ''
  }
  const headers = {}
  for (const field of mcpHeaderFields.value) {
    headers[field.name] = ''
  }
  mcpEnvValues.value = env
  mcpHeaderValues.value = headers
}

function openMcpDetail(server) {
  mcpSelected.value = server
  mcpTransport.value = (server.remotes || []).some((item) => item?.type === 'streamable-http')
    ? 'streamable-http'
    : 'stdio'
  mcpPackageIndex.value = 0
  mcpRemoteIndex.value = 0
  mcpToolsInput.value = ''
  resetMcpInputs()
}

async function installSelectedMcp() {
  if (!mcpSelected.value || mcpInstalling.value) return
  const missingEnv = mcpEnvFields.value.find(
    (field) => field.isRequired && !String(mcpEnvValues.value[field.name] || '').trim()
  )
  const missingHeader = mcpHeaderFields.value.find(
    (field) => field.isRequired && !String(mcpHeaderValues.value[field.name] || '').trim()
  )
  if (missingEnv || missingHeader) {
    setMcpFeedback(`请填写必填项：${(missingEnv || missingHeader).name}`, 'is-error')
    return
  }
  mcpInstalling.value = true
  setMcpFeedback('正在安装并连接 MCP 服务…这可能需要下载依赖。', 'is-pending')
  try {
    const tools = mcpToolsInput.value
      .split(/[,，]/)
      .map((item) => item.trim())
      .filter(Boolean)
    const installed = await api.installMcp({
      name: mcpSelected.value.name,
      version: mcpSelected.value.version || 'latest',
      transport: mcpTransport.value,
      package_index: mcpPackageIndex.value,
      remote_index: mcpRemoteIndex.value,
      env: mcpEnvValues.value,
      headers: mcpHeaderValues.value,
      tools
    })
    setMcpFeedback(`${installed.name || installed.id} 已安装并注册 ${installed.tool_names?.length || 0} 个工具。`, 'is-success')
    mcpSelected.value = null
    await loadMcpServers()
  } catch (err) {
    setMcpFeedback(err.message, 'is-error')
  } finally {
    mcpInstalling.value = false
  }
}

async function toggleMcp(server) {
  try {
    await api.setMcpEnabled(server.id, !server.enabled)
    await loadMcpServers()
    setMcpFeedback(`${server.name || server.id} 已${server.enabled ? '停用' : '启用'}。`, 'is-success')
  } catch (err) {
    setMcpFeedback(err.message, 'is-error')
  }
}

async function restartMcp(server) {
  try {
    setMcpFeedback(`正在重启 ${server.name || server.id}…`, 'is-pending')
    await api.restartMcp(server.id)
    await loadMcpServers()
    setMcpFeedback(`${server.name || server.id} 已重启。`, 'is-success')
  } catch (err) {
    setMcpFeedback(err.message, 'is-error')
  }
}

async function removeMcp(server) {
  if (!window.confirm(`删除 MCP 服务「${server.name || server.id}」？`)) return
  try {
    await api.deleteMcp(server.id)
    await loadMcpServers()
    setMcpFeedback(`已删除 ${server.name || server.id}。`, 'is-success')
  } catch (err) {
    setMcpFeedback(err.message, 'is-error')
  }
}
function handleKeydown(event) {
  if (event.key !== 'Escape' || !props.open || saving.value || testing.value) return
  if (selectedSkill.value) {
    selectedSkill.value = null
    return
  }
  if (mcpSelected.value) {
    mcpSelected.value = null
    return
  }
  emit('close')
}

watch(selection, () => {
  if (selection.value) parseSelection()
})

watch(
  () => props.open,
  (open) => {
    if (!open) return
    loadSettings()
    if (activeTab.value === 'skills') loadSkills()
    if (activeTab.value === 'mcp') loadMcpServers()
  }
)

onMounted(() => window.addEventListener('keydown', handleKeydown))
onUnmounted(() => window.removeEventListener('keydown', handleKeydown))
</script>