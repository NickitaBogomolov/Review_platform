from collections import Counter
from types import SimpleNamespace

from app.services.branch_compare import check_against_dev, collect_changes, compare_changes, find_ticket_commits
from app.services.diff_utils import make_unified_diff, parse_unified_diff
from app.services.gitlab_client import GitLabError


def commit(sha, message, parents=("p",)):
    return {"id": sha, "short_id": sha, "title": message, "message": message, "parent_ids": list(parents),
            "author": "a", "created_at": None, "web_url": None}


def change(path, old, new, change_type="modified", old_path=None):
    return {"old_path": old_path or path, "new_path": path, "change_type": change_type,
            "diff": make_unified_diff("\n".join(old), "\n".join(new)), "too_large": False}


def mr_file(path, old, new, file_id=1):
    return SimpleNamespace(id=file_id, path=path, new_content="\n".join(new) + "\n",
                           hunks=parse_unified_diff(make_unified_diff("\n".join(old), "\n".join(new))))


class FakeGitLab:
    def __init__(self, dev=(), tst=(), changes=None, contents=None):
        self.branches = {"develop_dev": list(dev), "develop_tst": list(tst)}
        self.changes, self.contents = changes or {}, contents or {}

    def list_branch_commits(self, project, branch, limit=5000):
        return self.branches[branch][:limit]

    def get_commit_changes(self, project, sha):
        return self.changes.get(sha, [])

    def get_file_content(self, project, path, ref):
        return self.contents.get((path, ref))


def by_path(files):
    return {f["path"]: f for f in files}


def test_find_commits_exact_number_case_insensitive_without_merges():
    commits = [
        commit("1", "RCK2-3435 правка расчёта"),
        commit("2", "rck2-3435 lower"),
        commit("3", "RCK2-34350 другой тикет"),
        commit("4", "XRCK2-3435 другой тикет"),
        commit("5", "Без номера\n\nСм. RCK2-3435 в теле"),
        commit("6", "Merge branch 'RCK2-3435' into 'develop_dev'", ("a", "b")),
    ]
    assert [c["id"] for c in find_ticket_commits(commits, "RCK2-3435", "develop_dev")] == ["1", "2", "5"]


def test_merge_commits_used_only_when_no_plain_commits():
    commits = [
        commit("1", "RCK2-1 описание тикета", ("a", "b")),
        commit("2", "Merge branch 'RCK2-1' into 'develop_dev'", ("a", "b")),
        commit("3", "Merge branch 'develop_dev' into RCK2-1", ("c", "d")),
        commit("4", "Merge remote-tracking branch 'origin/develop_dev' into RCK2-1", ("c", "d")),
    ]
    assert [c["id"] for c in find_ticket_commits(commits, "RCK2-1", "develop_dev")] == ["1", "2"]


def test_later_commit_reverting_change_nets_out():
    gl = FakeGitLab(changes={
        "1": [change("a.plp", ["x"], ["x", "tmp", "keep"])],
        "2": [change("a.plp", ["x", "tmp", "keep"], ["x", "keep"])],
    })
    # API отдаёт от новых к старым
    net = collect_changes(gl, "p", [commit("2", "m"), commit("1", "m")])
    assert +net["a.plp"] == Counter({"keep": 1})


def test_add_then_revert_whole_file_is_dropped_and_rename_followed():
    gl = FakeGitLab(changes={
        "1": [change("t.plp", [], ["a"], "added")],
        "2": [change("t.plp", ["a"], [], "deleted")],
        "3": [change("old.plp", ["x"], ["x", "y"])],
        "4": [change("new.plp", ["x", "y"], ["x", "y", "z"], "renamed", old_path="old.plp")],
    })
    net = collect_changes(gl, "p", [commit(s, "m") for s in "4321"])
    assert set(net) == {"new.plp"}
    assert +net["new.plp"] == Counter({"y": 1, "z": 1})


def test_diff_too_large_falls_back_to_file_contents():
    big = {"old_path": "a.plp", "new_path": "a.plp", "change_type": "modified", "diff": "", "too_large": True}
    gl = FakeGitLab(changes={"1": [big]}, contents={("a.plp", "p"): "x\n", ("a.plp", "1"): "x\ny\n"})
    assert +collect_changes(gl, "p", [commit("1", "m")])["a.plp"] == Counter({"y": 1})


def test_same_changes_at_different_positions_match():
    dev = {"a.plp": Counter({"new_line": 1, "old_line": -1})}
    mr = [mr_file("a.plp", ["head", "ctx", "old_line"], ["head", "ctx", "new_line"])]
    assert compare_changes(dev, {}, mr)[0]["status"] == "same"


def test_manual_transfer_with_other_whitespace_and_order_matches():
    gl = FakeGitLab(changes={
        "1": [change("a.plp", ["x"], ["x", "\tl_a  := 1;"])],
        "2": [change("a.plp", ["x", "\tl_a  := 1;"], ["x", "\tl_a  := 1;", "", "\tl_b := 2;"])],
    })
    dev = collect_changes(gl, "p", [commit("2", "m"), commit("1", "m")])
    mr = [mr_file("a.plp", ["x"], ["x", "    l_b := 2;", "    l_a := 1;"])]
    assert compare_changes(dev, {}, mr)[0]["status"] == "same"


def test_changed_text_in_manual_transfer_is_reported():
    gl = FakeGitLab(changes={"1": [change("a.plp", ["x"], ["x", "l_a := 1;"])]})
    dev = collect_changes(gl, "p", [commit("1", "m")])
    item = compare_changes(dev, {}, [mr_file("a.plp", ["x"], ["x", "l_a := 2;"])])[0]
    assert item["status"] == "differs"
    assert item["dev_only"] == [{"type": "add", "text": "l_a := 1;", "count": 1}]
    assert item["mr_only"] == [{"type": "add", "text": "l_a := 2;", "count": 1}]


def test_differences_reported_both_ways():
    dev = {"a.plp": Counter({"only_dev": 1, "both": 1, "gone_in_dev": -1})}
    mr = [mr_file("a.plp", ["gone_in_dev", "gone_in_mr"], ["gone_in_dev", "both", "only_mr"])]
    item = compare_changes(dev, {}, mr)[0]
    assert item["status"] == "differs"
    assert {(l["type"], l["text"]) for l in item["dev_only"]} == {("add", "only_dev"), ("del", "gone_in_dev")}
    assert {(l["type"], l["text"]) for l in item["mr_only"]} == {("add", "only_mr"), ("del", "gone_in_mr")}


def test_lost_line_is_found_even_if_same_text_exists_elsewhere_in_file():
    dev = {"a.plp": Counter({"end if;": 1, "fix": 1})}
    mr = [mr_file("a.plp", ["begin", "end if;"], ["begin", "end if;", "fix"])]
    item = compare_changes(dev, {}, mr)[0]
    assert item["status"] == "differs"
    assert item["dev_only"] == [{"type": "add", "text": "end if;", "count": 1}]


def test_ticket_delivered_by_several_mrs():
    dev = {
        "in_mr.plp": Counter({"from_previous_mr": 1, "fix": 1}),
        "delivered.plp": Counter({"x": 1}),
        "partly.plp": Counter({"x": 1, "forgotten": 1}),
        "lost.plp": Counter({"forgotten": 1}),
    }
    tst = {
        "in_mr.plp": Counter({"from_previous_mr": 1}),
        "delivered.plp": Counter({"x": 1}),
        "partly.plp": Counter({"x": 1}),
        "tst_only.plp": Counter({"y": 1}),
    }
    mr = [mr_file("in_mr.plp", ["from_previous_mr"], ["from_previous_mr", "fix"])]
    res = by_path(compare_changes(dev, tst, mr))
    assert res["in_mr.plp"]["status"] == "same"
    assert res["delivered.plp"]["status"] == "already_applied"
    assert res["partly.plp"]["status"] == "differs"
    assert res["partly.plp"]["dev_only"] == [{"type": "add", "text": "forgotten", "count": 1}]
    assert res["lost.plp"]["status"] == "only_in_dev"
    assert res["lost.plp"]["dev_only"] == [{"type": "add", "text": "forgotten", "count": 1}]
    assert res["tst_only.plp"]["status"] == "only_in_mr"


def test_merged_mr_is_not_counted_twice():
    dev = {"a.plp": Counter({"fix": 1})}
    tst = {"a.plp": Counter({"fix": 1})}
    mr = [mr_file("a.plp", ["x"], ["x", "fix"])]
    assert compare_changes(dev, tst, mr, mr_merged=True)[0]["status"] == "same"
    assert compare_changes(dev, tst, mr)[0]["status"] == "differs"


def test_ignored_files_do_not_affect_result():
    dev = {"README.md": Counter({"x": 1})}
    assert compare_changes(dev, {}, [], ["*.md"])[0]["status"] == "ignored"


CFG = {"GITLAB_DEV_BRANCH": "develop_dev", "GITLAB_TST_BRANCH": "develop_tst",
       "GITLAB_MAX_BRANCH_COMMITS": 100, "TZ_IGNORE_PATTERNS": []}


def test_check_many_dev_commits_against_one_mr():
    gl = FakeGitLab(
        dev=[commit("2", "T-1 вторая правка"), commit("1", "T-1 первая правка")],
        changes={"1": [change("a.plp", ["x"], ["x", "y"])], "2": [change("a.plp", ["x", "y"], ["x", "y", "z"])]},
    )
    res = check_against_dev(gl, CFG, "p", "T-1", [mr_file("a.plp", ["x"], ["x", "y", "z"])])
    assert res["ok"] is True and res["warning"] is None
    assert [c["id"] for c in res["commits"]] == ["2", "1"]
    assert "message" not in res["commits"][0]


def test_check_counts_commits_already_in_tst():
    gl = FakeGitLab(
        dev=[commit("2", "T-1 b"), commit("1", "T-1 a")],
        tst=[commit("t1", "T-1 a"), commit("t0", "T-2 чужой")],
        changes={"1": [change("a.plp", ["x"], ["x", "y"])], "2": [change("b.plp", ["x"], ["x", "z"])],
                 "t1": [change("a.plp", ["x"], ["x", "y"])], "t0": [change("c.plp", ["x"], ["x", "q"])]},
    )
    res = check_against_dev(gl, CFG, "p", "T-1", [mr_file("b.plp", ["x"], ["x", "z"])])
    assert res["ok"] is True
    assert [c["id"] for c in res["tst_commits"]] == ["t1"]
    assert {f["path"]: f["status"] for f in res["files"]} == {"a.plp": "already_applied", "b.plp": "same"}


def test_check_without_commits_is_not_ok_and_warns():
    res = check_against_dev(FakeGitLab(dev=[commit("1", "T-2 x")]), CFG, "p", "T-1", [])
    assert res["ok"] is False and "нет коммитов" in res["warning"]


def test_check_without_ticket_warns():
    res = check_against_dev(FakeGitLab(), CFG, "p", None, [])
    assert res["ok"] is False and res["warning"]


def test_check_warns_when_history_limit_reached():
    gl = FakeGitLab(dev=[commit("1", "T-1 x"), commit("2", "other")])
    res = check_against_dev(gl, {**CFG, "GITLAB_MAX_BRANCH_COMMITS": 2}, "p", "T-1", [])
    assert "GITLAB_MAX_BRANCH_COMMITS" in res["warning"]


def test_gitlab_error_is_reported_not_raised():
    class Broken(FakeGitLab):
        def list_branch_commits(self, project, branch, limit=5000):
            raise GitLabError("Ветка не найдена")

    res = check_against_dev(Broken(), CFG, "p", "T-1", [])
    assert res["error"] == "Ветка не найдена" and res["ok"] is False
