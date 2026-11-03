"""Демо-сценарии должны показывать ровно то, что обещано в их описании и в README."""
import pytest

from app.models import CustomLintRule

MR = "https://gitlab.local/demo/ibso/-/merge_requests/{}"

SCENARIOS = {
    2: ("RCK2-3435", True, {"src/DEPOSIT/CALC_PERCENT.plp": "same"}),
    3: ("RCK2-3501", True, {"src/LOAN/CALC_SCHEDULE.plp": "same"}),
    4: ("RCK2-3502", False, {"src/PAYMENT/SEND_PAYMENT.plp": "differs", "src/PAYMENT/LOG_PAYMENT.plp": "only_in_dev",
                             "src/CLIENT/UPD_PHONE.plp": "only_in_mr"}),
    5: ("RCK2-3510", True, {"src/CARD/BLOCK_CARD.plp": "same", "src/CARD/OPEN_CARD.plp": "already_applied"}),
    6: ("RCK2-3620", True, {"src/ACC/CLOSE_ACC.plp": "same"}),
    7: ("RCK2-3700", False, {"src/REP/EXPORT_REPORT.plp": "only_in_mr"}),
    9: ("RCK2-3800", False, {"src/FEE/CALC_FEE.plp": "differs"}),
    10: ("RCK2-3900", True, {"src/BATCH/RUN_BATCH.plp": "same"}),
}


def review(client, iid):
    rid = client.post("/api/reviews", json={"mr_url": MR.format(iid)}).get_json()["id"]
    data = client.get(f"/api/reviews/{rid}").get_json()
    assert data["status"] == "done", data["error"]
    return data


@pytest.mark.parametrize("iid", SCENARIOS)
def test_branch_check_matches_scenario(client, iid):
    key, ok, files = SCENARIOS[iid]
    data = review(client, iid)
    assert data["ticket_key"] == key
    assert data["branch_check"]["ok"] is ok
    assert {f["path"]: f["status"] for f in data["branch_check"]["files"]} == files


def test_cherry_pick_reverted_debug_is_not_counted(client):
    commits = review(client, 2)["branch_check"]["commits"]
    assert len(commits) == 4
    assert "Merge" not in " ".join(c["title"] for c in commits)


def test_tz_object_not_in_mr_is_not_an_error(client):
    tz = review(client, 2)["tz_check"]
    assert tz["ok"] is True and [o["system_name"] for o in tz["missing"]] == ["DEPOSIT\\CLOSE_DEPOSIT.plp"]


def test_manual_errors_show_exact_lines(client):
    data = review(client, 4)
    assert [e["path"] for e in data["tz_check"]["extra"]] == ["src/CLIENT/UPD_PHONE.plp"]
    item = next(f for f in data["branch_check"]["files"] if f["status"] == "differs")
    assert {l["text"] for l in item["dev_only"]} == {"l_limit := 100000;", "CHECK_LIMIT(l_sum, l_limit);"}
    assert {l["text"] for l in item["mr_only"]} == {"l_limit := 10000;"}


def test_second_mr_and_merged_mr_use_tst_commits(client):
    assert [c["title"] for c in review(client, 5)["branch_check"]["tst_commits"]] == [
        "RCK2-3510 Лимит при открытии карты"]
    assert [c["title"] for c in review(client, 6)["branch_check"]["tst_commits"]] == ["RCK2-3620 Закрытие счёта"]


def test_no_dev_commits_warns(client):
    assert "нет коммитов" in review(client, 7)["branch_check"]["warning"]


def test_mr_to_dev_has_no_branch_check(client):
    data = review(client, 8)
    assert data["target_branch"] == "develop_dev" and data["branch_check"] is None


def test_different_base_shows_only_removed_lines(client):
    item = review(client, 9)["branch_check"]["files"][0]
    assert item["dev_only"] == [{"type": "del", "text": "l_fee := 10;", "count": 1}]
    assert item["mr_only"] == [{"type": "del", "text": "l_fee := 15;", "count": 1}]


def test_seed_demo_loads_all_and_is_idempotent(app, client):
    runner = app.test_cli_runner()
    assert runner.invoke(args=["seed-demo"]).exit_code == 0
    assert runner.invoke(args=["seed-demo"]).exit_code == 0

    rules = client.get("/api/custom-lint-rules").get_json()
    assert [r["enabled"] for r in rules] == [True, True, False]
    reviews = client.get("/api/reviews").get_json()
    assert len(reviews) == 10 and all(r["status"] == "done" for r in reviews)

    lint_mr = client.get(f"/api/reviews/{next(r['id'] for r in reviews if r['mr_iid'] == 10)}").get_json()
    found = {(f["rule"], f["line"]) for f in lint_mr["findings"] if (f["rule"] or "").startswith("USR")}
    assert found == {("USR001", 4), ("USR002", 3)}


def test_seed_demo_keeps_existing_rules_and_refreshes_old_reviews(app, client):
    from app.extensions import db

    db.session.add(CustomLintRule(pattern="x", message="своё"))
    db.session.commit()
    client.post("/api/reviews/sync", json={})
    old = next(r for r in client.get("/api/reviews").get_json() if r["mr_iid"] == 2)
    from app.models import Review

    db.session.get(Review, old["id"]).branch_check = None  # ревью, созданное до появления сверки
    db.session.commit()

    assert app.test_cli_runner().invoke(args=["seed-demo"]).exit_code == 0
    assert [r["message"] for r in client.get("/api/custom-lint-rules").get_json()] == ["своё"]
    assert client.get(f"/api/reviews/{old['id']}").get_json()["branch_check"]["ok"] is True


def test_seed_demo_skipped_without_mock(app, client):
    app.config["GITLAB_MOCK"] = False
    assert app.test_cli_runner().invoke(args=["seed-demo"]).exit_code == 0
    assert client.get("/api/reviews").get_json() == []
    assert client.get("/api/custom-lint-rules").get_json() == []
