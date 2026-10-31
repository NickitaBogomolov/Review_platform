<template>
  <main class="container stack">
    <section class="card">
      <div class="card-header">Новое ревью</div>
      <form class="card-body new-review" @submit.prevent="create">
        <input
          v-model.trim="mrUrl"
          class="input"
          placeholder="Ссылка на merge request: https://gitlab.../group/project/-/merge_requests/123"
          :disabled="creating"
        />
        <input
          v-model.trim="ticketKey"
          class="input ticket"
          placeholder="Тикет (необяз.), напр. RCK2-3232"
          :disabled="creating"
        />
        <button class="btn primary" :disabled="creating || !mrUrl">
          <span v-if="creating" class="spinner" />
          {{ creating ? 'Анализируем MR…' : 'Начать ревью' }}
        </button>
      </form>
      <div v-if="creating" class="card-body muted small" style="padding-top: 0">
        Загружаем изменения из GitLab, сверяем с ТЗ, прогоняем линтер и отправляем значимые изменения модели.
        Это может занять пару минут.
      </div>
      <div v-if="error" class="card-body" style="padding-top: 0"><div class="error-box">{{ error }}</div></div>
    </section>

    <section class="card">
      <div class="card-header">Все MR проекта</div>
      <form class="card-body new-review" @submit.prevent="sync">
        <input
          v-model.trim="project"
          class="input"
          placeholder="Проект GitLab: group/project (по умолчанию из GITLAB_PROJECT)"
          :disabled="syncing"
        />
        <select v-model="mrState" class="input ticket" :disabled="syncing">
          <option value="all">Все MR</option>
          <option value="opened">Открытые</option>
          <option value="merged">Влитые</option>
          <option value="closed">Закрытые</option>
        </select>
        <button class="btn primary" :disabled="syncing || !project">
          <span v-if="syncing" class="spinner" />
          {{ syncing ? 'Импортируем MR…' : 'Загрузить все MR' }}
        </button>
      </form>
      <div v-if="syncing" class="card-body muted small" style="padding-top: 0">
        Новые MR анализируются, MR с новыми коммитами перезапускаются, неизменённые пропускаются.
        Для большого проекта это может занять много времени.
      </div>
      <div v-if="syncResult" class="card-body small" style="padding-top: 0">
        {{ syncResult.project }}: всего {{ syncResult.total }} · новых {{ syncResult.created }} ·
        обновлено {{ syncResult.updated }} · без изменений {{ syncResult.skipped }}
        <span v-if="syncResult.failed" class="badge err">с ошибкой {{ syncResult.failed }}</span>
      </div>
      <div v-if="syncError" class="card-body" style="padding-top: 0"><div class="error-box">{{ syncError }}</div></div>
    </section>

    <section class="card">
      <div class="card-header">
        Ревью
        <span class="badge">{{ reviews.length }}</span>
        <div style="flex: 1" />
        <input v-model="q" class="input" style="max-width: 260px; font-weight: 400" placeholder="Поиск: тикет, название" @input="debouncedLoad" />
      </div>
      <div v-if="loading" class="card-body muted"><span class="spinner" /> Загрузка…</div>
      <div v-else-if="!reviews.length" class="card-body muted">Пока нет ни одного ревью — вставьте ссылку на MR выше.</div>
      <div v-else style="overflow-x: auto">
        <table class="list">
          <thead>
            <tr>
              <th>Merge request</th>
              <th>Тикет</th>
              <th>Соответствие ТЗ</th>
              <th>Замечания</th>
              <th>Статус</th>
              <th>Создано</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in reviews" :key="r.id" class="clickable" @click="open(r.id)">
              <td>
                <div style="font-weight: 600">{{ r.mr_title || r.mr_url }}</div>
                <div class="muted small">
                  {{ r.gitlab_project }} !{{ r.mr_iid }}<span v-if="r.mr_author"> · {{ r.mr_author }}</span>
                </div>
              </td>
              <td><span v-if="r.ticket_key" class="mono">{{ r.ticket_key }}</span><span v-else class="muted">—</span></td>
              <td><TzBadge :check="r.tz_check" /></td>
              <td>
                <div class="stat-row" style="gap: 4px">
                  <span class="badge ai" title="ИИ">ИИ {{ r.counts.llm || 0 }}</span>
                  <span class="badge lint" title="Линтер">Линт {{ r.counts.lint || 0 }}</span>
                  <span v-if="r.counts.reviewer" class="badge rev">💬 {{ r.counts.reviewer }}</span>
                </div>
              </td>
              <td>
                <span v-if="r.status !== 'done'" class="badge" :class="{ err: r.status === 'failed' }">{{ STATUS_LABEL[r.status] }}</span>
                <span v-else class="badge" :class="verdictClass(r.verdict)">{{ VERDICT_LABEL[r.verdict] }}</span>
              </td>
              <td class="muted small">{{ formatDate(r.created_at) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </main>
</template>

<script setup>
import { inject, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'
import TzBadge from '../components/TzBadge.vue'
import { STATUS_LABEL, VERDICT_LABEL, formatDate } from '../utils/format'

const router = useRouter()
const reviewer = inject('reviewer')
const reviews = ref([])
const loading = ref(true)
const creating = ref(false)
const error = ref('')
const mrUrl = ref('')
const ticketKey = ref('')
const q = ref('')
const project = ref('')
const mrState = ref('all')
const syncing = ref(false)
const syncResult = ref(null)
const syncError = ref('')

async function load() {
  try {
    reviews.value = await api.listReviews(q.value.trim())
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

let timer = null
function debouncedLoad() {
  clearTimeout(timer)
  timer = setTimeout(load, 300)
}

async function create() {
  error.value = ''
  creating.value = true
  try {
    const review = await api.createReview({
      mr_url: mrUrl.value,
      ticket_key: ticketKey.value || null,
      reviewer: reviewer.value || null,
    })
    router.push({ name: 'review', params: { id: review.id } })
  } catch (e) {
    error.value = e.message
  } finally {
    creating.value = false
  }
}

async function sync() {
  syncError.value = ''
  syncResult.value = null
  syncing.value = true
  try {
    syncResult.value = await api.syncReviews({
      project: project.value,
      state: mrState.value,
      reviewer: reviewer.value || null,
    })
    await load()
  } catch (e) {
    syncError.value = e.message
  } finally {
    syncing.value = false
  }
}

async function loadDefaults() {
  try {
    const h = await api.health()
    if (h.gitlab_project && !project.value) project.value = h.gitlab_project
    if (h.gitlab_mr_state) mrState.value = h.gitlab_mr_state
  } catch {
    /* health необязателен */
  }
}

function open(id) {
  router.push({ name: 'review', params: { id } })
}

function verdictClass(v) {
  return v === 'approved' ? 'ok' : v === 'changes_requested' ? 'err' : 'info'
}

onMounted(() => {
  load()
  loadDefaults()
})
</script>

<style scoped>
.new-review { display: flex; gap: 8px; flex-wrap: wrap; }
.new-review .input { flex: 3 1 360px; }
.new-review .input.ticket { flex: 1 1 200px; }
</style>
