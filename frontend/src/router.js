import { createRouter, createWebHistory } from 'vue-router'
import ReviewList from './views/ReviewList.vue'
import ReviewDetail from './views/ReviewDetail.vue'
import LintRules from './views/LintRules.vue'

export default createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'reviews', component: ReviewList },
    { path: '/reviews/:id', name: 'review', component: ReviewDetail, props: true },
    { path: '/linters', name: 'lint-rules', component: LintRules },
  ],
})
