<template>
  <main class="container wide">
    <div v-if="loading" class="muted"><span class="spinner" /> Загрузка…</div>
    <div v-else-if="loadError" class="error-box">{{ loadError }}</div>
    <template v-else-if="review">
      <!-- Шапка MR -->
      <div class="mr-head">
        <div class="mr-title-row">
          <span class="badge" :class="verdictClass">{{ VERDICT_LABEL[review.verdict] }}</span>
          <h1>{{ review.mr_title || review.mr_url }}</h1>
        </div>
        <div class="muted small mr-meta">
          <span>{{ review.gitlab_project }} !{{ review.mr_iid }}</span>
          <span v-if="review.mr_author">автор <b>{{ review.mr_author }}</b></span>
          <span v-if="review.source_branch">
            <span class="branch">{{ review.source_branch }}</span> → <span class="branch">{{ review.target_branch }}</span>
          </span>
          <span v-if="review.ticket_key" class="mono">{{ review.ticket_key }}</span>
          <a :href="review.mr_url" target="_blank" rel="noopener">Открыть в GitLab ↗</a>
        </div>
        <div class="mr-actions">
          <button class="btn" :disabled="rerunning" @click="rerun">
            <span v-if="rerunning" class="spinner" /> {{ rerunning ? 'Анализ…' : '⟳ Перезапустить анализ' }}
          </button>
          <div style="flex: 1" />
          <button class="btn" :class="{ success: review.verdict === 'approved' }" @click="setVerdict('approved')">✓ Одобрить</button>
          <button class="btn" :class="{ active: review.verdict === 'changes_requested' }" style="color: var(--err)" @click="setVerdict('changes_requested')">
            ✕ Нужны правки
          </button>
        </div>
      </div>

      <div v-if="review.status === 'failed'" class="error-box" style="margin-top: 12px">
        <b>Анализ завершился с ошибкой:</b> {{ review.error }}
      </div>

      <div class="tabs">
        <button class="tab" :class="{ active: tab === 'overview' }" @click="tab = 'overview'">Обзор</button>
        <button class="tab" :class="{ active: tab === 'changes' }" @click="tab = 'changes'">
          Изменения <span class="count">{{ review.files.length }}</span>
        </button>
        <button class="tab" :class="{ active: tab === 'findings' }" @click="tab = 'findings'">
          Замечания <span class="count">{{ openTotal }}</span>
        </button>
      </div>

      <!-- ОБЗОР -->
      <div v-if="tab === 'overview'" class="grid-2">
        <div class="stack">
          <TzPanel :check="review.tz_check" :ticket="review.ticket" @open-file="openFile" />
          <section v-if="review.mr_description" class="card">
            <div class="card-header">Описание MR</div>
            <div class="card-body small" style="white-space: pre-wrap">{{ review.mr_description }}</div>
          </section>
        </div>
        <div class="stack">
          <section class="card">
            <div class="card-header">Итоги проверки</div>
            <div class="card-body stack">
              <div class="stat-row">
                <div class="stat"><div class="value" style="color: var(--ai)">{{ bySource.llm }}</div><div class="label">замечаний ИИ</div></div>
                <div class="stat"><div class="value" style="color: var(--lint)">{{ bySource.lint }}</div><div class="label">замечаний линтера</div></div>
                <div class="stat"><div class="value" style="color: var(--rev)">{{ bySource.reviewer }}</div><div class="label">комментариев</div></div>
              </div>
              <div class="stat-row" style="gap: 6px">
                <span v-for="s in ['critical', 'major', 'minor', 'info']" :key="s" class="sev" :class="s">
                  {{ SEVERITY_LABEL[s] }}: {{ bySeverity[s] || 0 }}
                </span>
              </div>
              <div v-if="review.llm_stats" class="small muted">
                <b>Модель ({{ review.llm_stats.mode }}):</b>
                отправлено {{ review.llm_stats.fragments_sent }} фрагм. из {{ review.llm_stats.files_sent }} файлов,
                ~{{ review.llm_stats.est_tokens }} токенов, запросов: {{ review.llm_stats.batches }}.
                Косметических ханков отброшено: {{ review.llm_stats.hunks_cosmetic }} из {{ review.llm_stats.hunks_total }}.
                <span v-if="review.llm_stats.truncated">Обрезано фрагментов: {{ review.llm_stats.truncated }}.</span>
                <div v-for="(e, i) in review.llm_stats.errors" :key="i" style="color: var(--err)">⚠ {{ e }}</div>
              </div>
            </div>
          </section>

          <section class="card">
            <div class="card-header">Заключение ревьюера</div>
            <div class="card-body stack">
              <textarea v-model="summary" class="input" rows="5" placeholder="Итог ревью, что нужно исправить…" @blur="saveSummary" />
              <div class="muted small">
                Ревьюер: {{ review.reviewer || reviewer || '—' }} · обновлено {{ formatDate(review.updated_at) }}
              </div>
            </div>
          </section>

          <div style="text-align: right">
            <button class="btn danger sm" @click="remove">Удалить ревью</button>
          </div>
        </div>
      </div>

      <!-- ИЗМЕНЕНИЯ -->
      <div v-else-if="tab === 'changes'">
        <div class="changes-toolbar">
          <div class="btn-group">
            <button class="btn sm" :class="{ active: viewMode === 'inline' }" @click="setViewMode('inline')">Inline</button>
            <button class="btn sm" :class="{ active: viewMode === 'split' }" @click="setViewMode('split')">Рядом</button>
          </div>
          <label class="check"><input v-model="filters.llm" type="checkbox" /> <span class="badge ai">ИИ</span></label>
          <label class="check"><input v-model="filters.lint" type="checkbox" /> <span class="badge lint">Линтер</span></label>
          <label class="check"><input v-model="filters.reviewer" type="checkbox" /> <span class="badge rev">Комментарии</span></label>
          <label class="check"><input v-model="filters.hideDismissed" type="checkbox" /> скрыть отклонённые</label>
          <div style="flex: 1" />
          <button class="btn sm" @click="collapseAll(true)">Свернуть все</button>
          <button class="btn sm" @click="collapseAll(false)">Развернуть все</button>
        </div>
        <div class="changes-layout">
          <FileTree :files="review.files" :findings="review.findings" :viewed="viewed" @select="(f) => openFile(f.id)" />
          <div>
            <DiffFile
              v-for="f in review.files"
              :key="f.id"
              :review-id="review.id"
              :file="f"
              :findings="visibleFindingsByFile[f.id] || []"
              :tz-object="tzObjectFor(f)"
              :view-mode="viewMode"
              :collapsed="!!collapsed[f.id]"
              :viewed="!!viewed[f.id]"
              @update:collapsed="(v) => (collapsed[f.id] = v)"
              @update:viewed="(v) => setViewed(f.id, v)"
            />
            <div v-if="generalFindings.length" class="card">
              <div class="card-header">Общие замечания к MR</div>
              <div class="card-body"><FindingCard v-for="f in generalFindings" :key="f.id" :finding="f" /></div>
            </div>
          </div>
        </div>
      </div>

      <!-- ВСЕ ЗАМЕЧАНИЯ -->
      <div v-else class="card">
        <div class="card-header">
          Все замечания
          <div style="flex: 1" />
          <label class="check" style="font-weight: 400"><input v-model="filters.hideDismissed" type="checkbox" /> скрыть отклонённые</label>
        </div>
        <div class="card-body">
          <div v-if="!sortedFindings.length" class="muted">Замечаний нет 🎉</div>
          <FindingCard
            v-for="f in sortedFindings"
            :key="f.id"
            :finding="f"
            :location="locationOf(f)"
            @locate="openFile(f.file_id)"
          />
        </div>
      </div>
    </template>
  </main>
</template>

<script setup>
import { computed, inject, nextTick, provide, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'
import DiffFile from '../components/DiffFile.vue'
import FileTree from '../components/FileTree.vue'
import FindingCard from '../components/FindingCard.vue'
import TzPanel from '../components/TzPanel.vue'
import { SEVERITY_LABEL, SEVERITY_ORDER, VERDICT_LABEL, formatDate } from '../utils/format'

const props = defineProps({ id: { type: String, required: true } })
const router = useRouter()
const reviewer = inject('reviewer')

const review = ref(null)
const loading = ref(true)
const loadError = ref('')
const rerunning = ref(false)
const tab = ref('overview')
const summary = ref('')
const collapsed = reactive({})
const viewed = reactive({})
const filters = reactive({ llm: true, lint: true, reviewer: true, hideDismissed: false })
const viewMode = ref(safeGet('viewMode') || 'inline')

function safeGet(key) {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}
function safeSet(key, value) {
  try {
    localStorage.setItem(key, value)
  } catch {
    /* ignore */
  }
}

function setViewMode(m) {
  viewMode.value = m
  safeSet('viewMode', m)
}

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    applyReview(await api.getReview(props.id))
  } catch (e) {
    loadError.value = e.message
  } finally {
    loading.value = false
  }
}

function applyReview(data) {
  review.value = data
  summary.value = data.summary || ''
  Object.keys(viewed).forEach((k) => delete viewed[k])
  // id файлов меняются при перезапуске анализа — «просмотрено» храним по пути файла
  let byPath = []
  try {
    byPath = JSON.parse(safeGet(`viewedPaths:${data.id}`) || '[]')
  } catch {
    /* ignore */
  }
  for (const f of data.files) {
    viewed[f.id] = byPath.includes(f.path)
    collapsed[f.id] = viewed[f.id]
  }
}

function setViewed(fileId, value) {
  viewed[fileId] = value
  collapsed[fileId] = value
  const paths = review.value.files.filter((f) => viewed[f.id]).map((f) => f.path)
  safeSet(`viewedPaths:${review.value.id}`, JSON.stringify(paths))
}

watch(() => props.id, load, { immediate: true })

// --- действия с замечаниями (используются в FindingCard / CommentForm)
provide('reviewActions', {
  async setStatus(finding, status) {
    const updated = await api.updateFinding(finding.id, { status })
    Object.assign(finding, updated)
  },
  async addComment(payload) {
    const created = await api.addComment(review.value.id, { ...payload, author: reviewer.value || null })
    review.value.findings.push(created)
  },
  async remove(finding) {
    if (!confirm('Удалить комментарий?')) return
    await api.deleteFinding(finding.id)
    review.value.findings = review.value.findings.filter((f) => f.id !== finding.id)
  },
})

const visibleFindings = computed(() =>
  (review.value?.findings || []).filter((f) => filters[f.source] && !(filters.hideDismissed && f.status === 'dismissed')),
)
const visibleFindingsByFile = computed(() => {
  const m = {}
  for (const f of visibleFindings.value) if (f.file_id) (m[f.file_id] ||= []).push(f)
  return m
})
const generalFindings = computed(() => visibleFindings.value.filter((f) => !f.file_id))
const sortedFindings = computed(() =>
  (review.value?.findings || [])
    .filter((f) => !(filters.hideDismissed && f.status === 'dismissed'))
    .slice()
    .sort((a, b) => SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity] || (a.file_id || 0) - (b.file_id || 0) || (a.line || 0) - (b.line || 0)),
)
const bySource = computed(() => {
  const c = { llm: 0, lint: 0, reviewer: 0 }
  for (const f of review.value?.findings || []) if (f.status !== 'dismissed') c[f.source]++
  return c
})
const bySeverity = computed(() => {
  const c = {}
  for (const f of review.value?.findings || [])
    if (f.status !== 'dismissed' && f.source !== 'reviewer') c[f.severity] = (c[f.severity] || 0) + 1
  return c
})
const openTotal = computed(() => (review.value?.findings || []).filter((f) => f.status === 'open' && f.source !== 'reviewer').length)
const verdictClass = computed(() => ({ approved: 'ok', changes_requested: 'err', pending: 'info' })[review.value?.verdict])

function tzObjectFor(file) {
  if (!file.tz_object_id || !review.value.ticket) return null
  return review.value.ticket.objects.find((o) => o.id === file.tz_object_id) || null
}

function locationOf(f) {
  if (!f.file_id) return 'MR целиком'
  const file = review.value.files.find((x) => x.id === f.file_id)
  if (!file) return ''
  const name = file.path.split('/').slice(-2).join('/')
  return f.line ? `${name}:${f.line}` : name
}

async function openFile(fileId) {
  if (!fileId) return
  tab.value = 'changes'
  collapsed[fileId] = false
  await nextTick()
  document.getElementById(`file-${fileId}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

function collapseAll(v) {
  for (const f of review.value.files) collapsed[f.id] = v
}

async function setVerdict(verdict) {
  const next = review.value.verdict === verdict ? 'pending' : verdict
  const data = await api.updateReview(review.value.id, { verdict: next, reviewer: reviewer.value || review.value.reviewer })
  Object.assign(review.value, { verdict: data.verdict, reviewer: data.reviewer, updated_at: data.updated_at })
}

async function saveSummary() {
  if (summary.value === (review.value.summary || '')) return
  const data = await api.updateReview(review.value.id, { summary: summary.value })
  review.value.summary = data.summary
  review.value.updated_at = data.updated_at
}

async function rerun() {
  rerunning.value = true
  try {
    applyReview(await api.rerunReview(review.value.id))
  } catch (e) {
    alert(e.message)
  } finally {
    rerunning.value = false
  }
}

async function remove() {
  if (!confirm('Удалить ревью со всеми замечаниями?')) return
  await api.deleteReview(review.value.id)
  router.push('/')
}
</script>

<style scoped>
.mr-head { border-bottom: 1px solid var(--border); padding-bottom: 12px; }
.mr-title-row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.mr-title-row h1 { font-size: 20px; margin: 0; font-weight: 600; }
.mr-meta { display: flex; gap: 12px; flex-wrap: wrap; margin-top: 6px; align-items: center; }
.mr-actions { display: flex; gap: 8px; margin-top: 12px; flex-wrap: wrap; }
</style>
