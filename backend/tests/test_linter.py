from app.linters import lint_file

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
