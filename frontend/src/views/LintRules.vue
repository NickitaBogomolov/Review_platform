<template>
  <main class="container stack">
    <section class="card">
      <div class="card-header">{{ editingId ? `Редактирование правила ${editingRuleId}` : 'Новое правило' }}</div>
      <form class="card-body stack rule-form" @submit.prevent="save">
        <label>
          <span class="field-label">Регулярное выражение</span>
          <input
            v-model="form.pattern"
            class="input mono"
            maxlength="500"
            placeholder="например: \bdbms_lock\s*\.\s*sleep\b"
            :disabled="saving"
          />
        </label>
        <label>
          <span class="field-label">Текст замечания</span>
          <textarea v-model="form.message" class="input" rows="2" placeholder="Что увидит ревьюер на найденной строке" :disabled="saving" />
        </label>
        <div class="rule-options">
          <label>
            <span class="field-label">Важность</span>
            <select v-model="form.severity" class="input" :disabled="saving">
              <option v-for="s in SEVERITIES" :key="s" :value="s">{{ SEVERITY_LABEL[s] }}</option>
            </select>
          </label>
          <label>
            <span class="field-label">Где искать</span>
            <select v-model="form.scope" class="input" :disabled="saving">
              <option v-for="(label, value) in SCOPE_LABEL" :key="value" :value="value">{{ label }}</option>
            </select>
          </label>
        </div>
        <div v-if="error" class="error-box">{{ error }}</div>
        <div class="rule-actions">
          <button class="btn primary" :disabled="saving || !form.pattern.trim() || !form.message.trim()">
            <span v-if="saving" class="spinner" />
            {{ editingId ? 'Сохранить' : 'Добавить правило' }}
          </button>
          <button v-if="editingId" type="button" class="btn" :disabled="saving" @click="resetForm">Отмена</button>
        </div>
        <div class="muted small">
          Выражение проверяется по каждой строке отдельно, без учёта регистра (синтаксис Python <code>re</code>).
          Правила срабатывают на добавленных в MR строках файлов с кодом. Уже проведённые ревью обновятся после
          перезапуска анализа.
        </div>
      </form>
    </section>

    <section class="card">
      <div class="card-header">Мои правила <span class="badge">{{ rules.length }}</span></div>
      <div v-if="loading" class="card-body muted"><span class="spinner" /> Загрузка…</div>
      <div v-else-if="!rules.length" class="card-body muted">Своих правил пока нет — добавьте первое в форме выше.</div>
      <div v-else style="overflow-x: auto">
        <table class="list">
          <thead>
            <tr><th>Вкл.</th><th>Код</th><th>Выражение</th><th>Замечание</th><th>Важность</th><th>Где искать</th><th /></tr>
          </thead>
          <tbody>
            <tr v-for="r in rules" :key="r.id" :class="{ 'rule-off': !r.enabled }">
              <td><input type="checkbox" :checked="r.enabled" :title="r.enabled ? 'Выключить' : 'Включить'" @change="toggle(r)" /></td>
              <td class="mono">{{ r.rule_id }}</td>
              <td class="mono rule-pattern">{{ r.pattern }}</td>
              <td class="rule-message">{{ r.message }}</td>
              <td><span class="sev" :class="r.severity">{{ SEVERITY_LABEL[r.severity] }}</span></td>
              <td class="small">{{ SCOPE_LABEL[r.scope] }}</td>
              <td style="white-space: nowrap">
                <button class="btn sm ghost" @click="edit(r)">Изменить</button>
                <button class="btn sm ghost danger" @click="remove(r)">Удалить</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section class="card">
      <details>
        <summary class="card-header" style="cursor: pointer">Встроенные правила <span class="badge">{{ builtin.length }}</span></summary>
        <table class="list">
          <thead>
            <tr><th>Вкл.</th><th>Код</th><th>Правило</th><th>Важность</th></tr>
          </thead>
          <tbody>
            <tr v-for="r in builtin" :key="r.id" :class="{ 'rule-off': !r.enabled }">
              <td><input type="checkbox" :checked="r.enabled" :title="r.enabled ? 'Выключить' : 'Включить'" @change="toggleBuiltin(r, $event)" /></td>
              <td class="mono">{{ r.id }}</td>
              <td>{{ r.title }}</td>
              <td><span class="sev" :class="r.severity">{{ SEVERITY_LABEL[r.severity] }}</span></td>
            </tr>
          </tbody>
        </table>
      </details>
    </section>
  </main>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { api } from '../api'
import { SEVERITY_LABEL } from '../utils/format'

const SEVERITIES = ['critical', 'major', 'minor', 'info']
const SCOPE_LABEL = { code: 'Только код', raw: 'Вся строка, включая комментарии и текст в кавычках' }
const EMPTY = { pattern: '', message: '', severity: 'minor', scope: 'code' }

const rules = ref([])
const builtin = ref([])
const loading = ref(true)
const saving = ref(false)
const error = ref('')
const editingId = ref(null)
const form = reactive({ ...EMPTY })
const editingRuleId = computed(() => rules.value.find((r) => r.id === editingId.value)?.rule_id)

function resetForm() {
  Object.assign(form, EMPTY)
  editingId.value = null
  error.value = ''
}

function edit(rule) {
  const { pattern, message, severity, scope } = rule
  Object.assign(form, { pattern, message, severity, scope })
  editingId.value = rule.id
  error.value = ''
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

async function save() {
  saving.value = true
  error.value = ''
  try {
    if (editingId.value) {
      const updated = await api.updateCustomRule(editingId.value, { ...form })
      rules.value = rules.value.map((r) => (r.id === updated.id ? updated : r))
    } else {
      rules.value.push(await api.createCustomRule({ ...form }))
    }
    resetForm()
  } catch (e) {
    error.value = e.message
  } finally {
    saving.value = false
  }
}

async function toggle(rule) {
  try {
    Object.assign(rule, await api.updateCustomRule(rule.id, { enabled: !rule.enabled }))
  } catch (e) {
    error.value = e.message
  }
}

async function toggleBuiltin(rule, event) {
  error.value = ''
  try {
    Object.assign(rule, await api.updateLintRule(rule.id, { enabled: !rule.enabled }))
  } catch (e) {
    error.value = e.message
    event.target.checked = rule.enabled
  }
}

async function remove(rule) {
  if (!confirm(`Удалить правило ${rule.rule_id}?`)) return
  try {
    await api.deleteCustomRule(rule.id)
    rules.value = rules.value.filter((r) => r.id !== rule.id)
    if (editingId.value === rule.id) resetForm()
  } catch (e) {
    error.value = e.message
  }
}

onMounted(async () => {
  try {
    const [custom, standard] = await Promise.all([api.listCustomRules(), api.lintRules()])
    rules.value = custom
    builtin.value = standard
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.rule-form label { display: block; }
.field-label { display: block; font-size: 12px; font-weight: 600; color: var(--text-2); margin-bottom: 4px; }
.rule-options { display: flex; gap: 12px; flex-wrap: wrap; }
.rule-options label { flex: 1 1 240px; }
.rule-actions { display: flex; gap: 8px; }
.rule-pattern { overflow-wrap: anywhere; min-width: 200px; }
.rule-message { white-space: pre-wrap; overflow-wrap: anywhere; min-width: 200px; }
.rule-off td { opacity: .55; }
details > summary.card-header { display: list-item; }
</style>
