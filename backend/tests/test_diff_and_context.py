from app.services.context_builder import analyse_hunk, build_batches
from app.services.diff_utils import make_unified_diff, parse_unified_diff


def _hunks(old, new):
    return parse_unified_diff(make_unified_diff("\n".join(old), "\n".join(new)))


def test_parse_line_numbers():
    hunks = _hunks(["a", "b", "c"], ["a", "B", "c", "d"])
    lines = hunks[0]["lines"]
    assert [(l["type"], l["old"], l["new"]) for l in lines] == [
        ("ctx", 1, 1), ("del", 2, None), ("add", None, 2), ("ctx", 3, 3), ("add", None, 4)
    ]


def test_deleted_comment_line_is_not_header():
    diff = "@@ -1,2 +1,1 @@\n--- comment\n x := 1;\n"
    hunks = parse_unified_diff(diff)
    assert hunks[0]["lines"][0] == {"type": "del", "old": 1, "new": None, "text": "-- comment"}


def test_cosmetic_changes_are_skipped():
    old = ["begin", "  x := 1;", "  Y := 2;", "end;"]
    new = ["begin", "\tx   :=   1;", "  y := 2;", "  -- комментарий", "", "end;"]
    adds, dels = analyse_hunk(_hunks(old, new)[0])
    assert adds == set() and dels == []


def test_significant_change_detected():
    old = ["begin", "  x := 1;", "end;"]
    new = ["begin", "  x := 2;", "end;"]
    adds, dels = analyse_hunk(_hunks(old, new)[0])
    assert adds == {2}
    assert dels == [(2, "  x := 1;")]


def test_batches_respect_budget():
    old = [f"line_{i} := {i};" for i in range(400)]
    new = [f"line_{i} := {i + 1};" if i % 10 == 0 else old[i] for i in range(400)]
    hunks = _hunks(old, new)
    files = [{"file_id": 1, "path": "src/T/A.plp", "change_type": "modified", "hunks": hunks,
              "new_content": "\n".join(new), "tz_change": None, "tz_status": "matched"}]
    batches, stats = build_batches(files, "HDR", max_tokens=600, context_lines=1)
    assert stats["batches"] > 1
    assert all(len(b["text"]) / 3 <= 700 for b in batches)
    sent = sum(len(f["fragments"]) for b in batches for f in b["files"])
    assert sent == stats["fragments_sent"] and sent > 0
