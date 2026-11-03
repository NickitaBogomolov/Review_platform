"""Правила линтера, которые пользователи заводят сами: регулярное выражение и текст замечания."""
import re

from .base import Rule

MAX_PATTERN_LENGTH = 500


def compile_pattern(pattern):
    """Как и сам PL/PLUS, поиск регистронезависимый. Ошибка в выражении — ValueError с текстом для пользователя."""
    if len(pattern) > MAX_PATTERN_LENGTH:
        raise ValueError(f"Регулярное выражение длиннее {MAX_PATTERN_LENGTH} символов")
    try:
        return re.compile(pattern, re.IGNORECASE)
    except re.error as exc:
        raise ValueError(f"Некорректное регулярное выражение: {exc}") from exc


class RegexRule(Rule):
    """Проверяет файл построчно; на строку — не больше одного замечания."""

    def __init__(self, rule_id, pattern, message, severity="minor", scope="code"):
        super().__init__()
        self.id = rule_id
        self.severity = severity
        self.title = message
        self.message = message
        self.scope = scope
        self.pattern = compile_pattern(pattern)

    def check(self, src):
        lines = src.raw if self.scope == "raw" else src.code
        for i, line in enumerate(lines, 1):
            if self.pattern.search(line):
                yield self.issue(i, self.message)
