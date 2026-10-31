from dataclasses import dataclass, field


@dataclass
class LintIssue:
    rule: str
    severity: str  # info | minor | major | critical
    line: int
    message: str
    suggestion: str = ""


@dataclass
class SourceFile:
    """Исходник, подготовленный для правил.

    raw[i]      — строка как есть
    code[i]     — строка, где комментарии и содержимое строковых литералов заменены пробелами
                  (длина и позиции символов сохранены — удобно для регулярок по коду)
    comments[i] — текст комментариев в строке
    """

    path: str
    raw: list
    code: list = field(default_factory=list)
    comments: list = field(default_factory=list)


class Rule:
    id = ""
    severity = "info"
    title = ""

    def __init__(self, config=None):
        self.config = config or {}

    def check(self, src: SourceFile):
        """Возвращает итератор LintIssue."""
        raise NotImplementedError

    def issue(self, line, message, suggestion="", severity=None):
        return LintIssue(self.id, severity or self.severity, line, message, suggestion)
