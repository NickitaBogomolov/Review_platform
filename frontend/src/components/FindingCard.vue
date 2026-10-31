<template>
  <div class="finding" :class="[finding.source, finding.status]">
    <div class="finding-head">
      <span class="badge" :class="badgeClass">
        <template v-if="finding.source === 'llm'">✦ ИИ</template>
        <template v-else-if="finding.source === 'lint'">Линтер · {{ finding.rule }}</template>
        <template v-else>{{ finding.author || 'Ревьюер' }}</template>
      </span>
      <span class="sev" :class="finding.severity">{{ SEVERITY_LABEL[finding.severity] }}</span>
      <a v-if="location" class="small mono" href="#" @click.prevent="$emit('locate', finding)">{{ location }}</a>
      <span v-if="finding.status === 'accepted'" class="badge ok">принято</span>
      <span v-if="finding.status === 'dismissed'" class="badge">отклонено</span>
      <div class="actions">
        <template v-if="finding.source !== 'reviewer'">
          <template v-if="finding.status === 'open'">
            <button class="btn sm" title="Замечание по делу — нужно исправить" @click="actions.setStatus(finding, 'accepted')">✓ Принять</button>
            <button class="btn sm" title="Ложное срабатывание / не актуально" @click="actions.setStatus(finding, 'dismissed')">✕ Отклонить</button>
          </template>
          <button v-else class="btn sm ghost" @click="actions.setStatus(finding, 'open')">Вернуть</button>
        </template>
        <button v-else class="btn sm ghost danger" title="Удалить комментарий" @click="actions.remove(finding)">Удалить</button>
      </div>
    </div>
    <template v-if="finding.status !== 'dismissed' || expanded">
      <div class="finding-msg">{{ finding.message }}</div>
      <div v-if="finding.suggestion" class="finding-suggestion">{{ finding.suggestion }}</div>
    </template>
    <a v-else href="#" class="small muted" @click.prevent="expanded = true">{{ short }}</a>
  </div>
</template>

<script setup>
import { computed, inject, ref } from 'vue'
import { SEVERITY_LABEL } from '../utils/format'

const props = defineProps({
  finding: { type: Object, required: true },
  location: { type: String, default: '' },
})
defineEmits(['locate'])
const actions = inject('reviewActions')
const expanded = ref(false)
const badgeClass = computed(() => ({ llm: 'ai', lint: 'lint', reviewer: 'rev' })[props.finding.source])
const short = computed(() => {
  const m = props.finding.message
  return m.length > 90 ? m.slice(0, 90) + '…' : m
})
</script>
