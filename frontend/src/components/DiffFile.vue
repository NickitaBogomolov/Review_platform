<template>
  <div :id="`file-${file.id}`" class="diff-file" :class="{ collapsed }">
    <div class="diff-file-header">
      <button class="btn sm ghost" :title="collapsed ? 'Развернуть' : 'Свернуть'" @click="$emit('update:collapsed', !collapsed)">
        {{ collapsed ? '▸' : '▾' }}
      </button>
      <span class="path">
        <template v-if="file.change_type === 'renamed'">
          <span class="dir">{{ file.old_path }} → </span>
        </template>
        <span class="dir">{{ parts.dir }}</span>{{ parts.name }}
      </span>
      <span class="badge" :class="{ ok: file.change_type === 'added', err: file.change_type === 'deleted' }">{{ CHANGE_LABEL[file.change_type] }}</span>
      <span v-if="file.tz_status === 'matched'" class="badge ok" title="Объект есть в ТЗ">✓ в ТЗ</span>
      <span v-else-if="file.tz_status === 'extra'" class="badge err" title="Файл изменён, но его нет в списке объектов ТЗ">✗ нет в ТЗ</span>
      <span v-else-if="file.tz_status === 'ignored'" class="badge" title="Служебный файл — не участвует в сверке">служебный</span>
      <span v-if="counts.llm" class="badge ai">ИИ {{ counts.llm }}</span>
      <span v-if="counts.lint" class="badge lint">Линт {{ counts.lint }}</span>
      <span v-if="counts.reviewer" class="badge rev">💬 {{ counts.reviewer }}</span>
      <div style="flex: 1" />
      <span class="stat-add">+{{ file.additions }}</span>
      <span class="stat-del">−{{ file.deletions }}</span>
      <label class="check small"><input type="checkbox" :checked="viewed" @change="$emit('update:viewed', $event.target.checked)" /> Просмотрено</label>
    </div>

    <div v-if="!collapsed" class="diff-body">
      <div v-if="tzObject" class="tz-note">
        <b>По ТЗ:</b> {{ tzObject.display_name ? tzObject.display_name + ' — ' : '' }}{{ tzObject.change_description || 'описание изменения не указано' }}
      </div>

      <div v-if="orphanFindings.length" class="file-level">
        <FindingCard
          v-for="f in orphanFindings"
          :key="f.id"
          :finding="f"
          :location="f.line ? `стр. ${f.line} (вне диффа)` : 'к файлу'"
          @locate="revealLine(f.line)"
        />
      </div>

      <div v-if="!file.hunks.length" class="diff-empty">
        {{ file.change_type === 'renamed' ? 'Файл переименован без изменений.' : 'Нет текстовых изменений (возможно, бинарный файл).' }}
      </div>

      <div v-else-if="tooLarge && !forceShow" class="diff-empty">
        Большой дифф ({{ file.additions + file.deletions }} строк).
        <button class="btn sm" @click="forceShow = true">Показать</button>
      </div>

      <!-- INLINE -->
      <table v-else-if="viewMode === 'inline'" class="diff">
        <colgroup><col class="num" /><col class="num" /><col /></colgroup>
        <tbody>
          <template v-for="sec in sections" :key="`s${sec.gapIndex}`">
            <tr v-if="!sec.tail && (sec.header || sec.hidden)" class="hunk">
              <td class="num" colspan="2">
                <button v-if="sec.hidden" class="expand-btn" :title="`Показать ${Math.min(sec.hidden, STEP)} строк выше`" @click="expand(sec)">↑</button>
              </td>
              <td class="code">
                {{ sec.header }}
                <button v-if="sec.hidden > STEP" class="expand-btn" @click="expand(sec, true)">показать все {{ sec.hidden }}</button>
              </td>
            </tr>
            <template v-for="(l, i) in sec.lines" :key="`l${sec.gapIndex}-${i}`">
              <tr :class="[l.type, { 'has-finding': hasOpen(keysOf(l)) }]">
                <td class="num clickable" @click="openForm(l.type === 'del' ? 'old' : 'new', l.type === 'del' ? l.old : l.new)">
                  <span class="add-comment">+</span>{{ l.old ?? '' }}
                </td>
                <td class="num clickable" @click="openForm(l.type === 'del' ? 'old' : 'new', l.type === 'del' ? l.old : l.new)">{{ l.new ?? '' }}</td>
                <td class="code" v-html="render(l)" />
              </tr>
              <tr v-if="threadVisible(keysOf(l))" class="thread">
                <td colspan="3">
                  <FindingCard v-for="f in findingsFor(keysOf(l))" :key="f.id" :finding="f" />
                  <CommentForm
                    v-if="formKey && keysOf(l).includes(formKey)"
                    :file-id="file.id"
                    :line="form.line"
                    :side="form.side"
                    @cancel="form = null"
                    @done="form = null"
                  />
                </td>
              </tr>
            </template>
            <tr v-if="sec.tail && sec.hidden" class="hunk">
              <td class="num" colspan="2"><button class="expand-btn" title="Показать ниже" @click="expand(sec)">↓</button></td>
              <td class="code">
                <button class="expand-btn" @click="expand(sec, true)">показать оставшиеся {{ sec.hidden }} строк</button>
              </td>
            </tr>
          </template>
        </tbody>
      </table>

      <!-- SIDE-BY-SIDE -->
      <table v-else class="diff">
        <colgroup><col class="num" /><col /><col class="num" /><col /></colgroup>
        <tbody>
          <template v-for="sec in sections" :key="`s${sec.gapIndex}`">
            <tr v-if="!sec.tail && (sec.header || sec.hidden)" class="hunk">
              <td class="num"><button v-if="sec.hidden" class="expand-btn" @click="expand(sec)">↑</button></td>
              <td class="code" colspan="3">
                {{ sec.header }}
                <button v-if="sec.hidden > STEP" class="expand-btn" @click="expand(sec, true)">показать все {{ sec.hidden }}</button>
              </td>
            </tr>
            <template v-for="(row, i) in splitRowsOf(sec)" :key="`r${sec.gapIndex}-${i}`">
              <tr :class="{ 'has-finding': hasOpen(rowKeys(row)) }">
                <td
                  class="num"
                  :class="[row.left ? row.left.type : 'empty', { clickable: row.left }]"
                  @click="row.left && openForm('old', row.left.old)"
                >
                  <span v-if="row.left" class="add-comment">+</span>{{ row.left?.old ?? '' }}
                </td>
                <td class="code split-left" :class="row.left ? (row.left.type === 'ctx' ? '' : row.left.type) : 'empty'" v-html="row.left ? render(row.left) : ''" />
                <td
                  class="num"
                  :class="[row.right ? row.right.type : 'empty', { clickable: row.right }]"
                  @click="row.right && openForm('new', row.right.new)"
                >
                  <span v-if="row.right" class="add-comment">+</span>{{ row.right?.new ?? '' }}
                </td>
                <td class="code" :class="row.right ? (row.right.type === 'ctx' ? '' : row.right.type) : 'empty'" v-html="row.right ? render(row.right) : ''" />
              </tr>
              <tr v-if="threadVisible(rowKeys(row))" class="thread">
                <td colspan="4">
                  <FindingCard v-for="f in findingsFor(rowKeys(row))" :key="f.id" :finding="f" />
                  <CommentForm
                    v-if="formKey && rowKeys(row).includes(formKey)"
                    :file-id="file.id"
                    :line="form.line"
                    :side="form.side"
                    @cancel="form = null"
                    @done="form = null"
                  />
                </td>
              </tr>
            </template>
            <tr v-if="sec.tail && sec.hidden" class="hunk">
              <td class="num"><button class="expand-btn" @click="expand(sec)">↓</button></td>
              <td class="code" colspan="3">
                <button class="expand-btn" @click="expand(sec, true)">показать оставшиеся {{ sec.hidden }} строк</button>
              </td>
            </tr>
          </template>
        </tbody>
      </table>

      <div class="file-footer">
        <button v-if="!form || form.line !== null" class="btn sm ghost" @click="openForm('new', null)">💬 Комментарий к файлу</button>
        <CommentForm v-else :file-id="file.id" :line="null" side="new" @cancel="form = null" @done="form = null" />
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, reactive, ref } from 'vue'
import { api } from '../api'
import { EXPAND_STEP as STEP, buildSections, toSplitRows } from '../utils/diffRows'
import { CHANGE_LABEL, splitPath } from '../utils/format'
import { highlight, highlightSegments } from '../utils/highlight'
import CommentForm from './CommentForm.vue'
import FindingCard from './FindingCard.vue'

const props = defineProps({
  reviewId: { type: [Number, String], required: true },
  file: { type: Object, required: true },
  findings: { type: Array, default: () => [] },
  tzObject: { type: Object, default: null },
  viewMode: { type: String, default: 'inline' },
  collapsed: { type: Boolean, default: false },
  viewed: { type: Boolean, default: false },
})
defineEmits(['update:collapsed', 'update:viewed'])

const parts = computed(() => splitPath(props.file.path))
const content = ref(null)
const expanded = reactive({})
const form = ref(null)
const forceShow = ref(false)
const tooLarge = computed(() => props.file.additions + props.file.deletions > 1500)

const sections = computed(() => buildSections(props.file, content.value, expanded))
const formKey = computed(() => (form.value && form.value.line !== null ? `${form.value.side}:${form.value.line}` : null))

const findingsByKey = computed(() => {
  const map = {}
  for (const f of props.findings) {
    if (f.line == null) continue
    const k = `${f.side || 'new'}:${f.line}`
    ;(map[k] ||= []).push(f)
  }
  return map
})

const visibleKeys = computed(() => {
  const set = new Set()
  for (const sec of sections.value)
    for (const l of sec.lines) for (const k of keysOf(l)) set.add(k)
  return set
})

const orphanFindings = computed(() =>
  props.findings.filter((f) => f.line == null || !visibleKeys.value.has(`${f.side || 'new'}:${f.line}`)),
)

const counts = computed(() => {
  const c = { llm: 0, lint: 0, reviewer: 0 }
  for (const f of props.findings) if (f.status !== 'dismissed') c[f.source]++
  return c
})

function keysOf(l) {
  if (l.type === 'del') return [`old:${l.old}`]
  if (l.type === 'add') return [`new:${l.new}`]
  return [`new:${l.new}`, `old:${l.old}`]
}

function rowKeys(row) {
  const keys = []
  if (row.left) keys.push(`old:${row.left.old}`)
  if (row.right) keys.push(`new:${row.right.new}`)
  return [...new Set(keys)]
}

function findingsFor(keys) {
  const out = []
  for (const k of keys) if (findingsByKey.value[k]) out.push(...findingsByKey.value[k])
  return out
}

function hasOpen(keys) {
  return findingsFor(keys).some((f) => f.status === 'open' && f.source !== 'reviewer')
}

function threadVisible(keys) {
  return findingsFor(keys).length > 0 || (formKey.value && keys.includes(formKey.value))
}

const splitCache = new WeakMap()
function splitRowsOf(sec) {
  if (!splitCache.has(sec)) splitCache.set(sec, toSplitRows(sec.lines))
  return splitCache.get(sec)
}

function render(l) {
  return l.segs ? highlightSegments(l.segs) : highlight(l.text)
}

function openForm(side, line) {
  form.value = { side, line }
}

async function ensureContent() {
  if (content.value) return true
  try {
    content.value = await api.fileContent(props.reviewId, props.file.id)
    return true
  } catch (e) {
    alert(`Не удалось загрузить файл: ${e.message}`)
    return false
  }
}

async function expand(sec, all = false) {
  if (!(await ensureContent())) return
  const current = expanded[sec.gapIndex] || 0
  expanded[sec.gapIndex] = current + (all ? sec.hidden : Math.min(sec.hidden, STEP))
}

// Раскрыть контекст так, чтобы строка с замечанием вне диффа стала видна.
async function revealLine(line) {
  if (!line || !(await ensureContent())) return
  for (const sec of sections.value) {
    if (sec.hidden) expanded[sec.gapIndex] = (expanded[sec.gapIndex] || 0) + sec.hidden
  }
}
</script>

<style scoped>
.tz-note { padding: 6px 12px; font-size: 13px; background: var(--ok-bg); border-bottom: 1px solid var(--border); color: #24663b; }
.file-level { padding: 8px 12px; background: var(--surface-2); border-bottom: 1px solid var(--border); }
.file-footer { padding: 6px 12px; border-top: 1px solid var(--border); }
</style>
