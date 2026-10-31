<template>
  <header class="topbar">
    <router-link to="/" class="logo">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M8 6l-6 6 6 6M16 6l6 6-6 6" />
      </svg>
      Code Review
    </router-link>
    <div class="spacer" />
    <div v-if="health" class="modes">
      <span class="mode" :class="{ mock: health.gitlab_mock }">GitLab: {{ health.gitlab_mock ? 'демо' : 'API' }}</span>
      <span class="mode" :class="{ mock: health.tz_portal_mode === 'stub' }">ТЗ: {{ health.tz_portal_mode === 'stub' ? 'заглушка' : 'API' }}</span>
      <span class="mode" :class="{ mock: health.llm_mode === 'stub' }">Модель: {{ health.llm_mode === 'stub' ? 'заглушка' : health.llm_mode }}</span>
    </div>
    <label class="who">
      <input v-model="reviewer" placeholder="Ваше имя (ревьюер)" @change="saveReviewer" />
    </label>
  </header>
  <router-view />
</template>

<script setup>
import { onMounted, provide, ref } from 'vue'
import { api, reviewerName } from './api'

const health = ref(null)
const reviewer = ref(reviewerName.get())
provide('reviewer', reviewer)

function saveReviewer() {
  reviewerName.set(reviewer.value.trim())
}

onMounted(async () => {
  try {
    health.value = await api.health()
  } catch {
    health.value = null
  }
})
</script>
