"""Правила линтера для PL/PLUS (ЦФТ).

Правила эвристические и рассчитаны на типовые ошибки в операциях ТБП.
Добавляйте свои: наследуйтесь от Rule, задайте id/severity/title и добавьте класс в ALL_RULES.
"""
import re

from .base import Rule

KW = re.IGNORECASE


class TrailingWhitespace(Rule):
    id = "PLP001"
    severity = "info"
    title = "Пробелы в конце строки"

    def check(self, src):
        for i, line in enumerate(src.raw, 1):
            if line != line.rstrip():
                yield self.issue(i, "Лишние пробелы/табуляции в конце строки")


class MixedIndent(Rule):
    id = "PLP002"
    severity = "info"
    title = "Смешанные табы и пробелы в отступе"

    def check(self, src):
        for i, line in enumerate(src.raw, 1):
            indent = line[: len(line) - len(line.lstrip())]
            if " \t" in indent:
                yield self.issue(i, "В отступе смешаны пробелы и табуляция")


class LineTooLong(Rule):
    id = "PLP003"
    severity = "info"
    title = "Слишком длинная строка"

    def check(self, src):
        limit = self.config.get("LINT_MAX_LINE_LENGTH", 150)
        for i, line in enumerate(src.raw, 1):
            length = len(line.expandtabs(4))
            if length > limit:
                yield self.issue(i, f"Длина строки {length} > {limit}")


class DebugOutput(Rule):
    id = "PLP010"
    severity = "major"
    title = "Отладочный вывод"
    PATTERN = re.compile(
        r"\b(debug_pipe|stdio\s*\.\s*put_line_buf|stdio\s*\.\s*put_line_pipe|"
        r"stdio\s*\.\s*put_line|dbms_output\s*\.\s*put(_line)?)\s*\(",
        KW,
    )

    def check(self, src):
        for i, line in enumerate(src.code, 1):
            m = self.PATTERN.search(line)
            if m:
                yield self.issue(
                    i,
                    f"Оставлен отладочный вывод `{m.group(1)}`",
                    "Удалите отладку перед слиянием или используйте штатное журналирование",
                )


class WhenOthersNull(Rule):
    id = "PLP011"
    severity = "major"
    title = "Подавление исключений (when others then null)"
    PATTERN = re.compile(r"\bwhen\s+others\s+then\s+null\s*;", KW)

    def check(self, src):
        text = "\n".join(src.code)
        for m in self.PATTERN.finditer(text):
            line = text.count("\n", 0, m.start()) + 1
            yield self.issue(
                line,
                "Исключение молча подавляется: `when others then null`",
                "Залогируйте ошибку и/или пробросьте её дальше (raise), либо обработайте конкретные исключения",
            )


class ExplicitTransaction(Rule):
    id = "PLP012"
    severity = "major"
    title = "Явное управление транзакцией"
    PATTERN = re.compile(r"(?<![\w.])(commit|rollback)(?!\s+to\b)\s*(work\s*)?;", KW)

    def check(self, src):
        for i, line in enumerate(src.code, 1):
            m = self.PATTERN.search(line)
            if m:
                yield self.issue(
                    i,
                    f"Явный `{m.group(1).lower()}` внутри операции",
                    "Транзакциями управляет платформа; если это действительно нужно — обоснуйте "
                    "(для отката используйте savepoint / rollback to)",
                )


class SelectStar(Rule):
    id = "PLP013"
    severity = "minor"
    title = "select *"
    PATTERN = re.compile(r"\bselect\s+(\w+\s*\.\s*)?\*", KW)

    def check(self, src):
        for i, line in enumerate(src.code, 1):
            if self.PATTERN.search(line):
                yield self.issue(i, "Используется `select *`", "Перечислите нужные поля явно")


class NullComparison(Rule):
    id = "PLP014"
    severity = "critical"
    title = "Сравнение с null через = / <>"
    PATTERN = re.compile(r"(!=|<>|\^=|(?<![<>!:^])=)\s*null\b", KW)

    def check(self, src):
        for i, line in enumerate(src.code, 1):
            if self.PATTERN.search(line):
                yield self.issue(
                    i,
                    "Сравнение с null через `=`/`<>` всегда даёт null (условие не выполнится)",
                    "Используйте `is null` / `is not null`",
                )


class TodoComment(Rule):
    id = "PLP015"
    severity = "info"
    title = "TODO / FIXME"
    PATTERN = re.compile(r"\b(TODO|FIXME|XXX|HACK)\b", KW)

    def check(self, src):
        for i, comment in enumerate(src.comments, 1):
            m = self.PATTERN.search(comment)
            if m:
                yield self.issue(i, f"Незавершённая доработка: {m.group(1).upper()}")


class CommentedOutCode(Rule):
    id = "PLP016"
    severity = "minor"
    title = "Закомментированный код"
    CODE_LIKE = re.compile(
        r"(:=|;\s*$|^(if|elsif)\b.*\bthen\s*$|^(for|while)\b.*\bloop\s*$|^end\s+(if|loop)\b)",
        KW,
    )

    def check(self, src):
        for i, (raw, comment) in enumerate(zip(src.raw, src.comments), 1):
            # интересуют только строки, целиком состоящие из однострочного комментария
            if not comment or src.code[i - 1].strip() or not raw.lstrip().startswith("--"):
                continue
            if self.CODE_LIKE.search(comment):
                yield self.issue(
                    i,
                    "Похоже на закомментированный код",
                    "Удалите неиспользуемый код — он сохранён в истории git",
                )


class HardcodedId(Rule):
    id = "PLP017"
    severity = "info"
    title = "Захардкоженный идентификатор"
    PATTERN = re.compile(r"(?<![\w.'])\d{9,}(?![\w.])")

    def check(self, src):
        for i, line in enumerate(src.code, 1):
            m = self.PATTERN.search(line)
            if m:
                yield self.issue(
                    i,
                    f"Числовая константа `{m.group(0)}` похожа на захардкоженный ID",
                    "Получайте объект по коду/реквизиту или вынесите в настройку",
                )


class AutonomousTransaction(Rule):
    id = "PLP018"
    severity = "minor"
    title = "pragma autonomous_transaction"
    PATTERN = re.compile(r"\bpragma\s+autonomous_transaction\b", KW)

    def check(self, src):
        for i, line in enumerate(src.code, 1):
            if self.PATTERN.search(line):
                yield self.issue(i, "Автономная транзакция — проверьте обоснованность")


class GotoUsage(Rule):
    id = "PLP019"
    severity = "minor"
    title = "goto"
    PATTERN = re.compile(r"\bgoto\s+\w+", KW)

    def check(self, src):
        for i, line in enumerate(src.code, 1):
            if self.PATTERN.search(line):
                yield self.issue(i, "Используется `goto`", "Перестройте логику через циклы/процедуры")


class DynamicSqlConcat(Rule):
    id = "PLP020"
    severity = "major"
    title = "Динамический SQL с конкатенацией"
    PATTERN = re.compile(r"\bexecute\s+immediate\b([^;]*)", KW)

    def check(self, src):
        text = "\n".join(src.code)
        for m in self.PATTERN.finditer(text):
            if "||" in m.group(1):
                line = text.count("\n", 0, m.start()) + 1
                yield self.issue(
                    line,
                    "`execute immediate` со склейкой строк — риск SQL-инъекции и потери производительности",
                    "Используйте bind-переменные (using ...)",
                )


class EmptyBlock(Rule):
    id = "PLP021"
    severity = "minor"
    title = "Пустой блок (только null;)"
    PATTERN = re.compile(r"\b(then|else|loop|begin)\s+null\s*;\s*(end|elsif|else)\b", KW)

    def check(self, src):
        text = "\n".join(src.code)
        for m in self.PATTERN.finditer(text):
            if m.group(1).lower() == "then" and re.search(r"others\s+$", text[max(0, m.start() - 30):m.start()], KW):
                continue  # покрыто PLP011
            line = text.count("\n", 0, m.start()) + 1
            yield self.issue(line, "Пустая ветка/блок — проверьте, не забыта ли логика")


ALL_RULES = [
    TrailingWhitespace,
    MixedIndent,
    LineTooLong,
    DebugOutput,
    WhenOthersNull,
    ExplicitTransaction,
    SelectStar,
    NullComparison,
    TodoComment,
    CommentedOutCode,
    HardcodedId,
    AutonomousTransaction,
    GotoUsage,
    DynamicSqlConcat,
    EmptyBlock,
]
