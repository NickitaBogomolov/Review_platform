"""Разбор unified diff (в формате GitLab API) и вспомогательные функции."""
import difflib
import re

HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@ ?(.*)$")


def decode_bytes(data: bytes) -> str:
    """Исходники ЦФТ нередко лежат в cp1251 — пробуем utf-8, затем cp1251."""
    if data is None:
        return None
    for enc in ("utf-8-sig", "cp1251"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def split_lines(text):
    if not text:
        return []
    return text.replace("\r\n", "\n").replace("\r", "\n").split("\n") if text else []


def content_lines(text):
    """Строки файла без завершающей пустой строки после последнего перевода строки."""
    lines = split_lines(text)
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def parse_unified_diff(diff_text):
    """Возвращает список ханков:
    [{header, section, old_start, old_count, new_start, new_count,
      lines: [{type: ctx|add|del, old: int|None, new: int|None, text}]}]
    """
    hunks = []
    current = None
    old_no = new_no = 0
    for raw in content_lines(diff_text):
        if current is None and raw.startswith(("diff --git", "--- ", "+++ ", "index ")):
            continue
        m = HUNK_RE.match(raw)
        if m:
            old_start = int(m.group(1))
            old_count = int(m.group(2)) if m.group(2) is not None else 1
            new_start = int(m.group(3))
            new_count = int(m.group(4)) if m.group(4) is not None else 1
            current = {
                "header": raw,
                "section": (m.group(5) or "").strip(),
                "old_start": old_start,
                "old_count": old_count,
                "new_start": new_start,
                "new_count": new_count,
                "lines": [],
            }
            hunks.append(current)
            old_no, new_no = old_start, new_start
            continue
        if current is None:
            continue
        if raw.startswith("\\"):  # "\ No newline at end of file"
            continue
        tag, text = (raw[:1], raw[1:]) if raw else (" ", "")
        if tag == "+":
            current["lines"].append({"type": "add", "old": None, "new": new_no, "text": text})
            new_no += 1
        elif tag == "-":
            current["lines"].append({"type": "del", "old": old_no, "new": None, "text": text})
            old_no += 1
        else:
            current["lines"].append({"type": "ctx", "old": old_no, "new": new_no, "text": text})
            old_no += 1
            new_no += 1
    return hunks


def make_unified_diff(old_text, new_text, context=3):
    """Строит diff в формате GitLab (без заголовков ---/+++), если GitLab не отдал diff (too_large)."""
    old_lines = content_lines(old_text)
    new_lines = content_lines(new_text)
    out = []
    for line in difflib.unified_diff(old_lines, new_lines, n=context, lineterm=""):
        if line.startswith("---") or line.startswith("+++"):
            continue
        out.append(line)
    return "\n".join(out) + ("\n" if out else "")


def diff_stats(hunks):
    adds = sum(1 for h in hunks for l in h["lines"] if l["type"] == "add")
    dels = sum(1 for h in hunks for l in h["lines"] if l["type"] == "del")
    return adds, dels


def added_line_numbers(hunks):
    return {l["new"] for h in hunks for l in h["lines"] if l["type"] == "add"}


def visible_new_lines(hunks):
    return {l["new"] for h in hunks for l in h["lines"] if l["new"] is not None}
