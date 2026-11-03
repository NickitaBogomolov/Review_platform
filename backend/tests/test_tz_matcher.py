from app.services.tz_matcher import extract_ticket_key, match_objects, tail_matches

REGEX = r"[A-Z][A-Z0-9]+-\d+"


def test_tail_matches_backslash_and_case():
    assert tail_matches("AC_FIN\\RECALC_COMM.plp", "src/ibso/AC_FIN/recalc_comm.PLP")
    assert not tail_matches("AC_FIN\\RECALC_COMM.plp", "src/OTHER/RECALC_COMM.plp")
    assert not tail_matches("AC_FIN\\RECALC_COMM.plp", "RECALC_COMM.plp")
    assert tail_matches("RECALC_COMM.plp", "src/AC_FIN/RECALC_COMM.plp")


def test_match_objects_both_directions():
    objects = [
        {"id": 1, "system_name": "AC_FIN\\A.plp"},
        {"id": 2, "system_name": "PR_CRED\\B.plp"},
    ]
    files = [
        {"id": 10, "old_path": "src/AC_FIN/A.plp", "new_path": "src/AC_FIN/A.plp", "change_type": "modified"},
        {"id": 11, "old_path": "src/CLIENT/C.plp", "new_path": "src/CLIENT/C.plp", "change_type": "modified"},
        {"id": 12, "old_path": "README.md", "new_path": "README.md", "change_type": "modified"},
    ]
    res = match_objects(objects, files, ["*.md"])
    assert [m["file_id"] for m in res["matched"]] == [10]
    assert [o["id"] for o in res["missing"]] == [2]
    assert [e["file_id"] for e in res["extra"]] == [11]
    assert [i["file_id"] for i in res["ignored"]] == [12]
    assert res["ok"] is False


def test_renamed_file_matches_old_path():
    objects = [{"id": 1, "system_name": "AC_FIN\\OLD.plp"}]
    files = [{"id": 1, "old_path": "src/AC_FIN/OLD.plp", "new_path": "src/AC_FIN/NEW.plp", "change_type": "renamed"}]
    assert match_objects(objects, files)["ok"]


def test_extract_ticket_key():
    assert extract_ticket_key(REGEX, "RCK2-3232: правки") == "RCK2-3232"
    assert extract_ticket_key(REGEX, "Без номера", "feature/rck2-3232-max") == "RCK2-3232"
    assert extract_ticket_key(REGEX, "нет", "develop", None) is None


def test_object_missing_from_mr_is_not_an_error():
    objects = [{"id": 1, "system_name": "AC_FIN\A.plp"}, {"id": 2, "system_name": "PR_CRED\B.plp"}]
    files = [{"id": 10, "old_path": "src/AC_FIN/A.plp", "new_path": "src/AC_FIN/A.plp", "change_type": "modified"}]
    res = match_objects(objects, files)
    assert [o["id"] for o in res["missing"]] == [2]
    assert res["ok"] is True
