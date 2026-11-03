import pytest

from app.linters import RegexRule, available_rules, compile_pattern, lint_file

ALL_IDS = [r["id"] for r in available_rules()]

CODE = """procedure P is
begin
\tdebug_pipe('x', 0);
\tif l_a = null then null; end if;
\tl_s := 'when others then null;';
\t-- l_x := 5;
\tcommit;
\trollback to sp1;
exception
\twhen others then null;
end;
"""


def rules(issues):
    return {(i.rule, i.line) for i in issues}


def test_rules_found():
    found = rules(lint_file("A.plp", CODE))
    assert ("PLP010", 3) in found
    assert ("PLP014", 4) in found
    assert ("PLP016", 6) in found
    assert ("PLP012", 7) in found
    assert ("PLP011", 10) in found


def test_strings_and_savepoints_ignored():
    found = rules(lint_file("A.plp", CODE))
    assert ("PLP011", 5) not in found  # внутри строкового литерала
    assert ("PLP012", 8) not in found  # rollback to savepoint допустим


def test_only_lines_and_disabled():
    issues = lint_file("A.plp", CODE, {"LINT_DISABLED_RULES": ["PLP010", "PLP021"]}, only_lines={3, 4})
    assert rules(issues) == {("PLP014", 4)}


def test_regex_rule_scope_and_only_lines():
    text = "l_a := 1; -- old_api\nold_api(1);\nl_s := 'old_api';\nOLD_API(2);\n"
    code_rule = RegexRule("USR001", r"old_api", "Не использовать old_api", "major")
    raw_rule = RegexRule("USR002", r"old_api", "В тексте", scope="raw")
    cfg = {"LINT_DISABLED_RULES": ALL_IDS}

    assert rules(lint_file("A.plp", text, cfg, extra_rules=[code_rule])) == {("USR001", 2), ("USR001", 4)}
    assert {i.line for i in lint_file("A.plp", text, cfg, extra_rules=[raw_rule])} == {1, 2, 3, 4}
    issues = lint_file("A.plp", text, cfg, only_lines={4}, extra_rules=[code_rule])
    assert [(i.line, i.severity, i.message) for i in issues] == [(4, "major", "Не использовать old_api")]


def test_compile_pattern_rejects_bad_regex():
    with pytest.raises(ValueError):
        compile_pattern("(")
    with pytest.raises(ValueError):
        compile_pattern("a" * 501)
