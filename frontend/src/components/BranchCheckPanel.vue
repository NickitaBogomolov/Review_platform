<template>
  <section class="card">
    <div class="card-header">
      <span class="branch">{{ check.dev_branch }}</span> → <span class="branch">{{ check.tst_branch }}</span>
      <span v-if="check.error" class="badge warn">не выполнена</span>
      <span v-else-if="check.ok" class="badge ok">✓ Совпадает</span>
      <span v-else-if="!check.commits.length" class="badge warn">нет коммитов</span>
      <span v-else class="badge err">Расхождений: {{ problems.length }}</span>
    </div>
    <div class="card-body stack">
      <div v-if="check.error" class="error-box">{{ check.error }}</div>
      <div v-if="check.warning" class="warn-box">{{ check.warning }}</div>

      <details v-if="check.commits.length">
        <summary class="small" style="cursor: pointer">
          Коммиты {{ check.ticket_key }} в {{ check.dev_branch }}: {{ check.commits.length }}
        </summary>
        <div v-for="c in check.commits" :key="c.id" class="small" style="margin-top: 6px">
          <a v-if="c.web_url" :href="c.web_url" target="_blank" rel="noopener" class="mono">{{ c.short_id }}</a>
          <span v-else class="mono">{{ c.short_id }}</span>
          {{ c.title }}
          <span class="muted"><template v-if="c.author"> · {{ c.author }}</template><template v-if="c.created_at"> · {{ formatDate(c.created_at) }}</template></span>
        </div>
      </details>

      <details v-if="check.tst_commits?.length">
        <summary class="small" style="cursor: pointer">
          Уже в {{ check.tst_branch }}: {{ check.tst_commits.length }}
        </summary>
        <div v-for="c in check.tst_commits" :key="c.id" class="small" style="margin-top: 6px">
          <a v-if="c.web_url" :href="c.web_url" target="_blank" rel="noopener" class="mono">{{ c.short_id }}</a>
          <span v-else class="mono">{{ c.short_id }}</span>
          {{ c.title }}
          <span class="muted"><template v-if="c.author"> · {{ c.author }}</template><template v-if="c.created_at"> · {{ formatDate(c.created_at) }}</template></span>
        </div>
      </details>

      <div v-for="f in problems" :key="f.path" class="branch-file">
        <div class="branch-file-head">
          <span class="badge err">{{ statusLabel[f.status] }}</span>
          <a v-if="f.file_id" href="#" class="mono small" @click.prevent="$emit('open-file', f.file_id)">{{ f.path }}</a>
          <span v-else class="mono small">{{ f.path }}</span>
        </div>
        <template v-if="f.dev_only.length">
          <div class="small muted branch-lines-title">Есть в {{ check.dev_branch }}, не несётся в {{ check.tst_branch }}</div>
          <div class="branch-lines">
            <div v-for="(l, i) in f.dev_only" :key="i" :class="l.type"><span class="sign">{{ l.type === 'add' ? '+' : '−' }}</span>{{ l.text }}<span v-if="l.count > 1" class="muted"> ×{{ l.count }}</span></div>
          </div>
        </template>
        <template v-if="f.mr_only.length">
          <div class="small muted branch-lines-title">Несётся в {{ check.tst_branch }}, нет в {{ check.dev_branch }}</div>
          <div class="branch-lines">
            <div v-for="(l, i) in f.mr_only" :key="i" :class="l.type"><span class="sign">{{ l.type === 'add' ? '+' : '−' }}</span>{{ l.text }}<span v-if="l.count > 1" class="muted"> ×{{ l.count }}</span></div>
          </div>
        </template>
        <div v-if="f.truncated" class="small muted" style="margin-top: 4px">Показаны не все строки.</div>
      </div>

      <div v-if="matching.length" class="small">
        <span class="badge ok">✓ совпадают</span> <span class="mono">{{ matching.map((f) => f.path).join(', ') }}</span>
      </div>
      <div v-if="applied.length" class="small">
        <span class="badge info">уже применено</span> <span class="mono">{{ applied.map((f) => f.path).join(', ') }}</span>
        <div class="muted" style="margin-top: 2px">Файлов нет в MR, но такие же правки уже влиты в {{ check.tst_branch }} коммитами тикета.</div>
      </div>
      <div v-if="ignored.length" class="muted small">
        Не участвуют в сверке (служебные): {{ ignored.map((f) => f.path).join(', ') }}
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import { formatDate } from '../utils/format'

const props = defineProps({ check: { type: Object, required: true } })
defineEmits(['open-file'])

const statusLabel = computed(() => ({
  differs: 'отличается',
  only_in_dev: `нет в ${props.check.tst_branch}`,
  only_in_mr: `нет в ${props.check.dev_branch}`,
}))
const problems = computed(() => props.check.files.filter((f) => f.status in statusLabel.value))
const matching = computed(() => props.check.files.filter((f) => f.status === 'same'))
const applied = computed(() => props.check.files.filter((f) => f.status === 'already_applied'))
const ignored = computed(() => props.check.files.filter((f) => f.status === 'ignored'))
</script>

<style scoped>
.branch-file-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.branch-lines-title { margin: 6px 0 2px; }
.branch-lines {
  font-family: var(--mono); font-size: 12px; line-height: 20px; border: 1px solid var(--border); border-radius: 4px;
  max-height: 260px; overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere; tab-size: 4;
}
.branch-lines > div { padding: 0 8px; }
.branch-lines .add { background: var(--add-bg); }
.branch-lines .del { background: var(--del-bg); }
.branch-lines .sign { display: inline-block; width: 14px; color: var(--text-3); user-select: none; }
</style>
