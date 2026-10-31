"""Минимальный лексер PL/PLUS (ЦФТ): отделяет код от комментариев и строковых литералов.

Поддерживаются: `-- комментарий`, `/* многострочный */`, строки `'...'` с экранированием `''`.
"""


def preprocess(lines):
    code_out, comments_out = [], []
    in_block_comment = False
    in_string = False
    for line in lines:
        code = []
        comment = []
        i = 0
        n = len(line)
        while i < n:
            ch = line[i]
            nxt = line[i + 1] if i + 1 < n else ""
            if in_block_comment:
                if ch == "*" and nxt == "/":
                    in_block_comment = False
                    code.append("  ")
                    i += 2
                else:
                    comment.append(ch)
                    code.append(" ")
                    i += 1
                continue
            if in_string:
                if ch == "'" and nxt == "'":
                    code.append("  ")
                    i += 2
                elif ch == "'":
                    in_string = False
                    code.append("'")
                    i += 1
                else:
                    code.append(" ")
                    i += 1
                continue
            if ch == "-" and nxt == "-":
                comment.append(line[i + 2:])
                code.append(" " * (n - i))
                break
            if ch == "/" and nxt == "*":
                in_block_comment = True
                code.append("  ")
                i += 2
                continue
            if ch == "'":
                in_string = True
                code.append("'")
                i += 1
                continue
            code.append(ch)
            i += 1
        code_out.append("".join(code))
        comments_out.append("".join(comment).strip())
    return code_out, comments_out
