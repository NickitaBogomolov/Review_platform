async function request(method, url, body) {
  const resp = await fetch(`/api${url}`, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : {},
    body: body ? JSON.stringify(body) : undefined,
  })
  if (resp.status === 204) return null
  let data = null
  try {
    data = await resp.json()
  } catch {
    /* пустой ответ */
  }
  if (!resp.ok) throw new Error((data && data.error) || `Ошибка ${resp.status}`)
  return data
}

export const api = {
  health: () => request('GET', '/health'),
  listReviews: (q = '') => request('GET', `/reviews${q ? `?q=${encodeURIComponent(q)}` : ''}`),
  createReview: (payload) => request('POST', '/reviews', payload),
  syncReviews: (payload = {}) => request('POST', '/reviews/sync', payload),
  getReview: (id) => request('GET', `/reviews/${id}`),
  updateReview: (id, payload) => request('PATCH', `/reviews/${id}`, payload),
  deleteReview: (id) => request('DELETE', `/reviews/${id}`),
  rerunReview: (id, payload = {}) => request('POST', `/reviews/${id}/rerun`, payload),
  fileContent: (id, fileId) => request('GET', `/reviews/${id}/files/${fileId}/content`),
  addComment: (id, payload) => request('POST', `/reviews/${id}/comments`, payload),
  updateFinding: (fid, payload) => request('PATCH', `/findings/${fid}`, payload),
  deleteFinding: (fid) => request('DELETE', `/findings/${fid}`),
  lintRules: () => request('GET', '/lint-rules'),
  listCustomRules: () => request('GET', '/custom-lint-rules'),
  createCustomRule: (payload) => request('POST', '/custom-lint-rules', payload),
  updateCustomRule: (id, payload) => request('PATCH', `/custom-lint-rules/${id}`, payload),
  deleteCustomRule: (id) => request('DELETE', `/custom-lint-rules/${id}`),
}

export const reviewerName = {
  get() {
    try {
      return localStorage.getItem('reviewer') || ''
    } catch {
      return ''
    }
  },
  set(value) {
    try {
      localStorage.setItem('reviewer', value)
    } catch {
      /* приватный режим */
    }
  },
}
