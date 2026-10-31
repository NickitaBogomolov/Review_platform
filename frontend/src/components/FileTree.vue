<template>
  <nav class="card file-tree">
    <div class="card-header small">
      Файлы <span class="badge">{{ files.length }}</span>
      <div style="flex: 1" />
      <span class="muted small" style="font-weight: 400">{{ viewedCount }}/{{ files.length }} просм.</span>
    </div>
    <div style="padding: 6px">
      <div v-for="f in files" :key="f.id" class="item" :title="title(f)" @click="$emit('select', f)">
        <span class="dot" :class="f.tz_status" />
        <span class="name">
          <span class="dir">{{ splitPath(f.path).dir }}</span>
          <span :style="{ textDecoration: f.change_type === 'deleted' ? 'line-through' : 'none' }">{{ splitPath(f.path).name }}</span>
        </span>
        <span v-if="openCount(f)" class="badge ai" title="Открытые замечания ИИ и линтера">{{ openCount(f) }}</span>
        <span v-if="viewed[f.id]" class="small" style="color: var(--ok)" title="Просмотрено">✓</span>
      </div>
    </div>
    <div class="legend small muted">
      <span><span class="dot matched" /> в ТЗ</span>
      <span><span class="dot extra" /> нет в ТЗ</span>
      <span><span class="dot ignored" /> служебный</span>
    </div>
  </nav>
</template>

<script setup>
import { computed } from 'vue'
import { splitPath } from '../utils/format'

const props = defineProps({
  files: { type: Array, required: true },
  findings: { type: Array, default: () => [] },
  viewed: { type: Object, default: () => ({}) },
})
defineEmits(['select'])

const viewedCount = computed(() => props.files.filter((f) => props.viewed[f.id]).length)
const openByFile = computed(() => {
  const m = {}
  for (const f of props.findings) if (f.file_id && f.status === 'open' && f.source !== 'reviewer') m[f.file_id] = (m[f.file_id] || 0) + 1
  return m
})
function openCount(f) {
  return openByFile.value[f.id] || 0
}
function title(f) {
  const s = { matched: 'Есть в ТЗ', extra: 'Нет в ТЗ', ignored: 'Служебный файл' }[f.tz_status] || ''
  return `${f.path}\n${s}  +${f.additions} −${f.deletions}`
}
</script>

<style scoped>
.legend { display: flex; gap: 10px; padding: 8px 12px; border-top: 1px solid var(--border); flex-wrap: wrap; }
.legend .dot { display: inline-block; vertical-align: 0; }
</style>
