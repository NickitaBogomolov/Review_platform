<template>
  <form class="comment-form" @submit.prevent="submit">
    <textarea ref="area" v-model="message" class="input" placeholder="Комментарий ревьюера…" @keydown.ctrl.enter="submit" @keydown.meta.enter="submit" />
    <div class="row">
      <select v-model="severity" class="input" style="width: auto">
        <option value="info">Инфо</option>
        <option value="minor">Средне</option>
        <option value="major">Важно</option>
        <option value="critical">Критично</option>
      </select>
      <span class="muted small">Ctrl+Enter — отправить</span>
      <div style="flex: 1" />
      <button type="button" class="btn" @click="$emit('cancel')">Отмена</button>
      <button class="btn primary" :disabled="!message.trim() || saving">Добавить</button>
    </div>
  </form>
</template>

<script setup>
import { inject, onMounted, ref } from 'vue'

const props = defineProps({
  fileId: { type: Number, default: null },
  line: { type: Number, default: null },
  side: { type: String, default: 'new' },
})
const emit = defineEmits(['cancel', 'done'])
const actions = inject('reviewActions')
const message = ref('')
const severity = ref('minor')
const saving = ref(false)
const area = ref(null)

onMounted(() => area.value?.focus())

async function submit() {
  if (!message.value.trim() || saving.value) return
  saving.value = true
  try {
    await actions.addComment({
      file_id: props.fileId,
      line: props.line,
      side: props.side,
      message: message.value,
      severity: severity.value,
    })
    emit('done')
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.comment-form { max-width: 980px; }
.row { display: flex; gap: 8px; align-items: center; margin-top: 6px; flex-wrap: wrap; }
</style>
