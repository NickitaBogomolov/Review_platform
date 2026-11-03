<template>
  <section class="card">
    <div class="card-header">
      Соответствие ТЗ
      <TzBadge :check="check" />
      <div style="flex: 1" />
      <a v-if="ticket?.portal_url" :href="ticket.portal_url" target="_blank" rel="noopener" class="small" style="font-weight: 400">Открыть на портале ↗</a>
    </div>
    <div class="card-body stack">
      <div v-if="check?.warning" class="warn-box">{{ check.warning }}</div>

      <dl v-if="ticket" class="kv">
        <dt>Тикет</dt><dd class="mono">{{ ticket.key }}</dd>
        <dt>Задача</dt><dd>{{ ticket.title }}</dd>
        <dt v-if="ticket.analyst">Аналитик</dt><dd v-if="ticket.analyst">{{ ticket.analyst }}</dd>
        <dt v-if="ticket.developer">Разработчик</dt><dd v-if="ticket.developer">{{ ticket.developer }}</dd>
      </dl>

      <div v-if="check && check.ticket_found" style="overflow-x: auto">
        <table class="list">
          <thead>
            <tr><th>Объект ТЗ</th><th>Что меняется</th><th>Файл в MR</th></tr>
          </thead>
          <tbody>
            <tr v-for="m in check.matched" :key="'m' + m.object.id">
              <td>
                <div class="mono">{{ m.object.system_name }}</div>
                <div class="muted small">{{ m.object.display_name }}</div>
              </td>
              <td class="small">{{ m.object.change_description }}</td>
              <td>
                <span class="badge ok">✓ изменён</span>
                <a href="#" class="mono small" style="display: block" @click.prevent="$emit('open-file', m.file_id)">{{ m.path }}</a>
              </td>
            </tr>
            <tr v-for="o in check.missing" :key="'x' + o.id">
              <td>
                <div class="mono">{{ o.system_name }}</div>
                <div class="muted small">{{ o.display_name }}</div>
              </td>
              <td class="small">{{ o.change_description }}</td>
              <td><span class="badge">не изменён в MR</span></td>
            </tr>
            <tr v-if="!check.matched.length && !check.missing.length">
              <td colspan="3" class="muted">В ТЗ нет объектов</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-if="check?.extra?.length">
        <div style="font-weight: 600; margin-bottom: 6px">Изменены в MR, но отсутствуют в ТЗ</div>
        <div v-for="e in check.extra" :key="e.file_id" style="margin-bottom: 4px">
          <span class="badge err">✗ нет в ТЗ</span>
          <a href="#" class="mono small" @click.prevent="$emit('open-file', e.file_id)">{{ e.path }}</a>
        </div>
      </div>

      <div v-if="check?.ignored?.length" class="muted small">
        Не участвуют в сверке (служебные): {{ check.ignored.map((i) => i.path).join(', ') }}
      </div>

      <details v-if="ticket?.description">
        <summary class="small" style="cursor: pointer">Текст ТЗ</summary>
        <div style="white-space: pre-wrap; margin-top: 8px" class="small">{{ ticket.description }}</div>
      </details>
    </div>
  </section>
</template>

<script setup>
import TzBadge from './TzBadge.vue'

defineProps({
  check: { type: Object, default: null },
  ticket: { type: Object, default: null },
})
defineEmits(['open-file'])
</script>
