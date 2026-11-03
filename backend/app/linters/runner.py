from .base import SourceFile
from .plplus_lexer import preprocess
from .plplus_rules import ALL_RULES


def available_rules():
    return [{"id": r.id, "severity": r.severity, "title": r.title} for r in ALL_RULES]


def lint_file(path, text, config=None, only_lines=None, extra_rules=()):
    """Прогоняет правила по файлу.

    only_lines — множество номеров строк (новой версии), по которым нужно вернуть замечания.
    Обычно это добавленные в MR строки: так ревьюер видит только то, что принёс этот MR.
    extra_rules — готовые экземпляры правил в дополнение к встроенным (правила пользователей).
    """
    config = config or {}
    disabled = set(config.get("LINT_DISABLED_RULES") or [])
    raw = (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if raw and raw[-1] == "":
        raw.pop()
    code, comments = preprocess(raw)
    src = SourceFile(path=path, raw=raw, code=code, comments=comments)

    issues = []
    rules = [rule_cls(config) for rule_cls in ALL_RULES if rule_cls.id not in disabled]
    for rule in rules + list(extra_rules):
        for issue in rule.check(src):
            if only_lines is not None and issue.line not in only_lines:
                continue
            issues.append(issue)
    issues.sort(key=lambda x: (x.line, x.rule))
    return issues
