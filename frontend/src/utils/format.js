export const SEVERITY_LABEL = { critical: 'Критично', major: 'Важно', minor: 'Средне', info: 'Инфо' }
export const SEVERITY_ORDER = { critical: 0, major: 1, minor: 2, info: 3 }
export const SOURCE_LABEL = { llm: 'ИИ', lint: 'Линтер', reviewer: 'Ревьюер' }
export const STATUS_LABEL = { pending: 'В очереди', running: 'Анализ…', done: 'Готово', failed: 'Ошибка' }
export const VERDICT_LABEL = { pending: 'На ревью', approved: 'Одобрено', changes_requested: 'Нужны правки' }
export const CHANGE_LABEL = { added: 'новый', modified: 'изменён', deleted: 'удалён', renamed: 'переименован' }

export function formatDate(iso) {
  if (!iso) return ''
  return new Date(iso).toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' })
}

export function splitPath(path) {
  const idx = path.lastIndexOf('/')
  return idx === -1 ? { dir: '', name: path } : { dir: path.slice(0, idx + 1), name: path.slice(idx + 1) }
}
