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

function open(id) {
  router.push({ name: 'review', params: { id } })
}

function verdictClass(v) {
  return v === 'approved' ? 'ok' : v === 'changes_requested' ? 'err' : 'info'
}

onMounted(load)
</script>

<style scoped>
.new-review { display: flex; gap: 8px; flex-wrap: wrap; }
.new-review .input { flex: 3 1 360px; }
.new-review .input.ticket { flex: 1 1 200px; }
</style>
