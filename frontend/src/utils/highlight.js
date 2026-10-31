// Лёгкая подсветка PL/PLUS (ЦФТ): ключевые слова, строки, комментарии, ::[КЛАСС], [РЕКВИЗИТ].
const KEYWORDS = new Set(
  `and any all as asc begin between body by case cast close commit constant create cursor declare default
  delete desc distinct else elsif end exception execute exists exit fetch for from function goto group
  having if immediate in index insert into is like locate loop not null of on open or order others package
  pragma private procedure public raise record ref replace return returning reverse rollback rowtype
  savepoint select set table then this to type update using validate values when where while with
  type is_null nvl decode true false varchar2 varchar number integer date boolean string memo`
    .split(/\s+/)
    .filter(Boolean),
)

const TOKEN_RE =
  /(--.*$)|(\/\*.*?(?:\*\/|$))|('(?:[^']|'')*'?)|(::\[[^\]]*\])|(\[[^\]\s]+\])|(\b\d+(?:\.\d+)?\b)|([A-Za-zА-Яа-яЁё_][\wА-Яа-яЁё$#]*)/g

export function escapeHtml(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
}

export function highlight(text) {
  if (!text) return ''
  let out = ''
  let last = 0
  TOKEN_RE.lastIndex = 0
  let m
  while ((m = TOKEN_RE.exec(text)) !== null) {
    if (m.index > last) out += escapeHtml(text.slice(last, m.index))
    const tok = escapeHtml(m[0])
    if (m[1] || m[2]) out += `<span class="hl-c">${tok}</span>`
    else if (m[3]) out += `<span class="hl-s">${tok}</span>`
    else if (m[4]) out += `<span class="hl-t">${tok}</span>`
    else if (m[5]) out += `<span class="hl-a">${tok}</span>`
    else if (m[6]) out += `<span class="hl-n">${tok}</span>`
    else if (KEYWORDS.has(m[0].toLowerCase())) out += `<span class="hl-k">${tok}</span>`
    else out += tok
    last = m.index + m[0].length
    if (m[0].length === 0) TOKEN_RE.lastIndex++
  }
  if (last < text.length) out += escapeHtml(text.slice(last))
  return out
}

// Подсветка с выделением изменённой части строки (intraline diff).
export function highlightSegments(segments) {
  return segments
    .map((s) => (s.changed ? `<span class="ix">${highlight(s.text)}</span>` : highlight(s.text)))
    .join('')
}
