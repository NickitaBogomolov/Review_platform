<template>
  <span v-if="!check" class="muted">—</span>
  <span v-else-if="!check.ticket_found" class="badge warn" :title="check.warning">ТЗ не найдено</span>
  <span v-else-if="check.ok" class="badge ok">✓ Совпадает</span>
  <span v-else class="badge err" :title="title">
    <template v-if="check.missing.length">−{{ check.missing.length }} не изменено</template>
    <template v-if="check.missing.length && check.extra.length"> · </template>
    <template v-if="check.extra.length">+{{ check.extra.length }} лишних</template>
  </span>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({ check: { type: Object, default: null } })
const title = computed(() => {
  if (!props.check) return ''
  const parts = []
  if (props.check.missing.length) parts.push('Нет в MR: ' + props.check.missing.map((o) => o.system_name).join(', '))
  if (props.check.extra.length) parts.push('Нет в ТЗ: ' + props.check.extra.map((f) => f.path).join(', '))
  return parts.join('\n')
})
</script>
