"""Подготовка компактного контекста для модели.

Цель — отправлять в модель только значимые изменения:
  1. Косметика отбрасывается: изменения только в пробелах/регистре (PL/PLUS регистронезависим),
     перенос строк без изменения, пустые строки, правки только комментариев.
  2. Вокруг значимых строк берётся небольшое окно контекста (LLM_CONTEXT_LINES) + заголовок
     процедуры/секции, в которой находится изменение (одна строка вместо всего тела).
  3. Общий отступ фрагмента срезается.
  4. Стиль/форматирование уже проверены линтером — модель про это не спрашиваем.
  5. Если всё не помещается в LLM_MAX_INPUT_TOKENS — режем на несколько запросов (батчей),
     файлы из ТЗ идут первыми.
"""
import math
import re
from collections import Counter

from .diff_utils import content_lines

SCOPE_RE = re.compile(
    r"^\s*((create\s+or\s+replace\s+)?(procedure|function|cursor)\s+[\w$#.]+|"
    r"(public|private|validate|execute)\b|"
    r"type\s+[\w$#]+\s+is\b)",
    re.IGNORECASE,
)


def estimate_tokens(text):
    # Грубая оценка: для кода и кириллицы у токенизаторов Qwen ~3 символа на токен.
    return math.ceil(len(text) / 3) if text else 0


def _norm(text):
    return re.sub(r"\s+", " ", text).strip().casefold()


def _is_trivial(text):
    stripped = text.strip()
    return not stripped or stripped.startswith("--") or stripped in ("/*", "*/") or stripped.startswith("*")


def find_scope(new_lines, line_no, max_scan=800):
    """Ищет ближайший заголовок процедуры/секции выше строки line_no (1-based)."""
    if not new_lines:
        return ""
    start = min(line_no, len(new_lines)) - 1
    for idx in range(start, max(-1, start - max_scan), -1):
        if SCOPE_RE.match(new_lines[idx]):
            return new_lines[idx].strip()
    return ""


def analyse_hunk(hunk):
    """Делит изменения ханка на значимые и косметические.

    Возвращает (significant_adds: set[new_no], significant_dels: list[(anchor_new_no, text)]).
    """
    sig_adds, sig_dels = set(), []
    lines = hunk["lines"]
    i = 0
    while i < len(lines):
        if lines[i]["type"] == "ctx":
            i += 1
            continue
        block = []
        while i < len(lines) and lines[i]["type"] != "ctx":
            block.append(lines[i])
            i += 1
        anchor = lines[i]["new"] if i < len(lines) else (hunk["new_start"] + hunk["new_count"])
        dels = [l for l in block if l["type"] == "del"]
        adds = [l for l in block if l["type"] == "add"]
        pool = Counter(_norm(l["text"]) for l in dels if not _is_trivial(l["text"]))
        for l in adds:
            if _is_trivial(l["text"]):
                continue
            key = _norm(l["text"])
            if pool.get(key):
                pool[key] -= 1  # строка просто переформатирована / перенесена
                continue
            sig_adds.add(l["new"])
        for l in dels:
            if _is_trivial(l["text"]):
                continue
            key = _norm(l["text"])
            if pool.get(key):
                pool[key] -= 1
                first_add = next((a["new"] for a in adds), anchor)
                sig_dels.append((first_add, l["text"]))
    return sig_adds, sig_dels


def _dedent(texts):
    indents = []
    for t in texts:
        if t.strip():
            indents.append(len(t) - len(t.lstrip()))
    cut = min(indents) if indents else 0
    return [t[cut:] if len(t) >= cut else t.lstrip() for t in texts]


def build_fragments(file, context_lines):
    """Строит фрагменты одного файла. Возвращает (fragments, hunks_total, hunks_skipped)."""
    new_lines = content_lines(file.get("new_content")) if file.get("new_content") else None
    hunks = file.get("hunks") or []
    fragments = []
    skipped = 0
    for hunk in hunks:
        sig_adds, sig_dels = analyse_hunk(hunk)
        if not sig_adds and not sig_dels:
            skipped += 1
            continue
        hunk_new = {l["new"]: l["text"] for l in hunk["lines"] if l["new"] is not None}
        if new_lines is None:
            source = hunk_new
            max_line = max(hunk_new) if hunk_new else 0
        else:
            source = {i + 1: t for i, t in enumerate(new_lines)}
            max_line = len(new_lines)

        anchors = set(sig_adds) | {a for a, _ in sig_dels}
        show = set()
        for n in anchors:
            for k in range(n - context_lines, n + context_lines + 1):
                if 1 <= k <= max_line and k in source:
                    show.add(k)
        dels_by_anchor = {}
        for anchor, text in sig_dels:
            dels_by_anchor.setdefault(anchor, []).append(text)

        # группируем показываемые строки в непрерывные диапазоны
        ordered = sorted(show | {a for a in dels_by_anchor if a > max_line})
        ranges, cur = [], []
        for n in ordered:
            if cur and n != cur[-1] + 1:
                ranges.append(cur)
                cur = []
            cur.append(n)
        if cur:
            ranges.append(cur)

        for rng in ranges:
            rows = []  # (marker, line_no|None, text)
            for n in rng:
                for text in dels_by_anchor.pop(n, []):
                    rows.append(("-", None, text))
                if n in source:
                    rows.append(("+" if n in sig_adds else " ", n, source[n]))
            texts = _dedent([r[2] for r in rows])
            scope = find_scope(new_lines, rng[0]) if new_lines else hunk.get("section", "")
            body = []
            for (marker, n, _), text in zip(rows, texts):
                num = f"{n:>5}" if n is not None else "     "
                body.append(f"{num}{marker} {text.rstrip()}")
            fragments.append({
                "scope": scope,
                "text": "\n".join(body),
                "lines": [n for _, n, _ in rows if n is not None],
                "changed": sorted(n for m, n, _ in rows if m == "+"),
            })
        # удалённые строки, якорь которых не попал в диапазоны
        for anchor, texts in dels_by_anchor.items():
            body = "\n".join(f"     - {t.strip()}" for t in texts)
            fragments.append({"scope": find_scope(new_lines, anchor) if new_lines else "",
                              "text": body, "lines": [], "changed": []})
    return fragments, len(hunks), skipped


def render_file_header(file):
    parts = [f"### Файл: {file['path']} ({file['change_type']})"]
    if file.get("tz_change"):
        parts.append(f"Изменение по ТЗ: {file['tz_change']}")
    elif file.get("tz_status") == "extra":
        parts.append("Файла нет в списке объектов ТЗ.")
    return "\n".join(parts)


def render_fragment(fragment):
    head = f"@@ {fragment['scope']}" if fragment["scope"] else "@@"
    return f"{head}\n{fragment['text']}"


def build_batches(files, header_text, max_tokens, context_lines):
    """files: [{file_id, path, change_type, hunks, new_content, tz_change, tz_status}]

    Возвращает (batches, stats). Батч: {"files": [{file_id, path, fragments: [...]}], "text": str}
    """
    stats = {
        "files_total": len(files),
        "files_sent": 0,
        "hunks_total": 0,
        "hunks_cosmetic": 0,
        "fragments_sent": 0,
        "truncated": 0,
        "est_tokens": 0,
        "batches": 0,
    }
    header_tokens = estimate_tokens(header_text)
    budget = max(500, max_tokens - header_tokens)

    batches = []
    current = {"files": [], "parts": [], "tokens": 0}

    def flush():
        if current["parts"]:
            text = header_text + "\n\n" + "\n\n".join(current["parts"])
            batches.append({"files": current["files"], "text": text})
            stats["est_tokens"] += estimate_tokens(text)
        current["files"], current["parts"], current["tokens"] = [], [], 0

    for file in files:
        fragments, total, skipped = build_fragments(file, context_lines)
        stats["hunks_total"] += total
        stats["hunks_cosmetic"] += skipped
        if not fragments:
            continue
        stats["files_sent"] += 1
        file_header = render_file_header(file)
        header_cost = estimate_tokens(file_header)
        entry = None
        for frag in fragments:
            frag_text = render_fragment(frag)
            cost = estimate_tokens(frag_text)
            if cost + header_cost > budget:
                # фрагмент целиком не влезает даже в пустой батч — обрезаем
                keep = max(1, (budget - header_cost) * 3)
                frag_text = frag_text[:keep] + "\n... (фрагмент обрезан)"
                cost = estimate_tokens(frag_text)
                stats["truncated"] += 1
            need = cost + (header_cost if entry is None else 0)
            if current["tokens"] + need > budget and current["parts"]:
                flush()
                entry = None
                need = cost + header_cost
            if entry is None:
                entry = {"file_id": file["file_id"], "path": file["path"], "fragments": []}
                current["files"].append(entry)
                current["parts"].append(file_header)
            current["parts"].append(frag_text)
            entry["fragments"].append(frag)
            current["tokens"] += need
            stats["fragments_sent"] += 1
    flush()
    stats["batches"] = len(batches)
    return batches, stats
