// Построение строк для отображения диффа (inline и side-by-side), как в GitLab.

const EXPAND_STEP = 20

function rangeEnd(start, count) {
  return count === 0 ? start : start + count - 1
}

// Внутристрочный дифф: общий префикс/суффикс, середина помечается как изменённая.
export function intraline(a, b) {
  let p = 0
  const max = Math.min(a.length, b.length)
  while (p < max && a[p] === b[p]) p++
  let s = 0
  while (s < max - p && a[a.length - 1 - s] === b[b.length - 1 - s]) s++
  const common = p + s
  if (common === 0 || common < Math.min(a.length, b.length) * 0.3) return null
  const seg = (t) => {
    const out = []
    if (p) out.push({ text: t.slice(0, p) })
    const mid = t.slice(p, t.length - s)
    if (mid) out.push({ text: mid, changed: true })
    if (s) out.push({ text: t.slice(t.length - s) })
    return out
  }
  return [seg(a), seg(b)]
}

// Пары del/add внутри блока изменений -> сегменты для подсветки.
function annotateBlocks(lines) {
  const out = lines.map((l) => ({ ...l }))
  let i = 0
  while (i < out.length) {
    if (out[i].type === 'ctx') {
      i++
      continue
    }
    const dels = []
    const adds = []
    while (i < out.length && out[i].type !== 'ctx') {
      ;(out[i].type === 'del' ? dels : adds).push(out[i])
      i++
    }
    const n = Math.min(dels.length, adds.length)
    for (let k = 0; k < n; k++) {
      const segs = intraline(dels[k].text, adds[k].text)
      if (segs) {
        dels[k].segs = segs[0]
        adds[k].segs = segs[1]
      }
      dels[k].pair = adds[k]
      adds[k].pair = dels[k]
    }
  }
  return out
}

/**
 * Возвращает «секции»: для каждого ханка — строка-заголовок с информацией о скрытом промежутке
 * перед ним (gap), раскрытые строки промежутка и строки ханка. В конце — хвостовой промежуток.
 *
 * expanded: { [gapIndex]: число раскрытых строк }
 * content:  { old: [...], new: [...] } | null
 */
export function buildSections(file, content, expanded) {
  const hunks = file.hunks || []
  const sections = []
  let prevOld = 0
  let prevNew = 0
  const linesOf = content ? (content.new.length ? content.new : content.old) : null

  hunks.forEach((h, idx) => {
    const gapLen = Math.max(0, h.old_start - 1 - prevOld)
    const revealed = Math.min(gapLen, expanded[idx] || 0)
    const gapLines = []
    // раскрываем снизу вверх (ближайшие к ханку строки)
    for (let k = gapLen - revealed; k < gapLen; k++) {
      const o = prevOld + 1 + k
      const n = prevNew + 1 + k
      gapLines.push({ type: 'ctx', old: o, new: n, text: linesOf ? linesOf[(content.new.length ? n : o) - 1] ?? '' : '' })
    }
    sections.push({
      gapIndex: idx,
      hidden: gapLen - revealed,
      header: h.header,
      section: h.section,
      lines: [...gapLines, ...annotateBlocks(h.lines)],
    })
    prevOld = rangeEnd(h.old_start, h.old_count)
    prevNew = rangeEnd(h.new_start, h.new_count)
  })

  // хвост файла после последнего ханка
  const total = file.new_lines_total || file.old_lines_total || 0
  const tail = hunks.length ? Math.max(0, total - prevNew) : 0
  if (tail > 0 && file.change_type !== 'deleted') {
    const idx = hunks.length
    const revealed = Math.min(tail, expanded[idx] || 0)
    const lines = []
    for (let k = 0; k < revealed; k++) {
      lines.push({ type: 'ctx', old: prevOld + 1 + k, new: prevNew + 1 + k, text: linesOf ? linesOf[prevNew + k] ?? '' : '' })
    }
    sections.push({ gapIndex: idx, hidden: tail - revealed, tail: true, header: '', section: '', lines })
  }
  return sections
}

// Для side-by-side: превращаем строки секции в пары (левая/правая колонка).
export function toSplitRows(lines) {
  const rows = []
  let i = 0
  while (i < lines.length) {
    const l = lines[i]
    if (l.type === 'ctx') {
      rows.push({ left: l, right: l })
      i++
      continue
    }
    const dels = []
    const adds = []
    while (i < lines.length && lines[i].type !== 'ctx') {
      ;(lines[i].type === 'del' ? dels : adds).push(lines[i])
      i++
    }
    const n = Math.max(dels.length, adds.length)
    for (let k = 0; k < n; k++) rows.push({ left: dels[k] || null, right: adds[k] || null })
  }
  return rows
}

export { EXPAND_STEP }
