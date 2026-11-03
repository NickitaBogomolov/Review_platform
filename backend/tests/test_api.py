MR = "https://gitlab.local/bank/ibso/-/merge_requests/17"


def test_full_review_flow(client):
    r = client.post("/api/reviews", json={"mr_url": MR})
    assert r.status_code == 201
    rid = r.get_json()["id"]
    d = client.get(f"/api/reviews/{rid}").get_json()
    assert d["status"] == "done", d["error"]
    assert d["ticket_key"] == "RCK2-3232"
    tz = d["tz_check"]
    assert len(tz["matched"]) == 2
    assert [m["system_name"] for m in tz["missing"]] == ["PR_CRED\\CLOSE_CRED.plp"]
    assert [e["path"] for e in tz["extra"]] == ["src/CLIENT/UPD_ADDR.plp"]
    assert d["counts"]["lint"] > 0

    file_id = d["files"][0]["id"]
    c = client.post(f"/api/reviews/{rid}/comments",
                    json={"file_id": file_id, "line": 4, "message": "ok?", "author": "rev"})
    assert c.status_code == 201

    lint = next(f for f in d["findings"] if f["source"] == "lint")
    assert client.patch(f"/api/findings/{lint['id']}", json={"status": "dismissed"}).status_code == 200
    assert client.delete(f"/api/findings/{lint['id']}").status_code == 400

    d2 = client.post(f"/api/reviews/{rid}/rerun").get_json()
    reviewer = [f for f in d2["findings"] if f["source"] == "reviewer"]
    assert len(reviewer) == 1 and reviewer[0]["file_id"] == d2["files"][0]["id"]

    content = client.get(f"/api/reviews/{rid}/files/{d2['files'][0]['id']}/content").get_json()
    assert content["new"][0].startswith("-- Операция")

    assert client.patch(f"/api/reviews/{rid}", json={"verdict": "approved"}).get_json()["verdict"] == "approved"


def test_bad_url(client):
    r = client.post("/api/reviews", json={"mr_url": "not a url"})
    assert r.status_code == 400


def test_sync_project_mrs(client):
    r = client.post("/api/reviews/sync", json={})
    assert r.status_code == 200
    s = r.get_json()
    assert (s["project"], s["total"], s["created"], s["failed"]) == ("bank/ibso", 10, 10, 0)

    reviews = client.get("/api/reviews").get_json()
    assert len(reviews) == 10 and all(r["status"] == "done" for r in reviews)
    assert sorted(r["mr_iid"] for r in reviews) == list(range(1, 11))

    # повторный импорт: MR не менялся — пропускается, дубликат не создаётся
    s2 = client.post("/api/reviews/sync", json={}).get_json()
    assert (s2["created"], s2["updated"], s2["skipped"]) == (0, 0, 10)
    assert len(client.get("/api/reviews").get_json()) == 10

    # фильтр по состоянию: влит только один демо-MR
    assert client.post("/api/reviews/sync", json={"state": "merged"}).get_json()["total"] == 1


def test_sync_bad_state(client):
    assert client.post("/api/reviews/sync", json={"state": "whatever"}).status_code == 400


def test_custom_lint_rules_crud_and_review(client):
    assert client.post("/api/custom-lint-rules", json={"pattern": "(", "message": "x"}).status_code == 400
    assert client.post("/api/custom-lint-rules", json={"pattern": "x"}).status_code == 400
    assert client.post("/api/custom-lint-rules", json={"pattern": "x", "message": "m", "severity": "?"}).status_code == 400

    r = client.post("/api/custom-lint-rules",
                    json={"pattern": r"l_comm\s*:=", "message": "Присваивание комиссии", "severity": "critical"})
    assert r.status_code == 201
    rule = r.get_json()
    assert (rule["rule_id"], rule["scope"], rule["enabled"]) == ("USR001", "code", True)

    rid = client.post("/api/reviews", json={"mr_url": MR}).get_json()["id"]
    findings = client.get(f"/api/reviews/{rid}").get_json()["findings"]
    mine = [f for f in findings if f["rule"] == "USR001"]
    assert mine and all(f["source"] == "lint" and f["severity"] == "critical"
                        and f["message"] == "Присваивание комиссии" for f in mine)

    # выключенное правило при перезапуске анализа не срабатывает
    assert client.patch(f"/api/custom-lint-rules/{rule['id']}", json={"enabled": False}).get_json()["enabled"] is False
    findings = client.post(f"/api/reviews/{rid}/rerun").get_json()["findings"]
    assert not [f for f in findings if f["rule"] == "USR001"]

    assert client.patch(f"/api/custom-lint-rules/{rule['id']}", json={"pattern": "["}).status_code == 400
    assert client.get("/api/custom-lint-rules").get_json()[0]["pattern"] == r"l_comm\s*:="
    assert client.delete(f"/api/custom-lint-rules/{rule['id']}").status_code == 204
    assert client.get("/api/custom-lint-rules").get_json() == []
    assert client.delete(f"/api/custom-lint-rules/{rule['id']}").status_code == 404


def test_mr_to_tst_compared_with_dev_commits(client):
    rid = client.post("/api/reviews", json={"mr_url": MR}).get_json()["id"]
    d = client.get(f"/api/reviews/{rid}").get_json()
    check = d["branch_check"]
    assert d["target_branch"] == "develop_tst"
    assert [c["title"] for c in check["commits"]] == [
        "RCK2-3232: перед закрытием кредита считаем пени",
        "RCK2-3232: новая операция CALC_PENALTY",
        "RCK2-3232: учёт MAX_SUM в тарифе",
    ]
    assert check["tst_commits"] == []
    status = {f["path"]: f["status"] for f in check["files"]}
    assert status == {
        "README.md": "ignored",
        "src/AC_FIN/CALC_PENALTY.plp": "same",
        "src/AC_FIN/RECALC_COMM.plp": "same",
        "src/CLIENT/UPD_ADDR.plp": "only_in_mr",
        "src/PR_CRED/CLOSE_CRED.plp": "only_in_dev",
    }
    assert check["ok"] is False


def test_mr_to_other_branch_is_not_compared(client, app):
    app.config["GITLAB_TST_BRANCH"] = "some_other_branch"
    rid = client.post("/api/reviews", json={"mr_url": MR}).get_json()["id"]
    assert client.get(f"/api/reviews/{rid}").get_json()["branch_check"] is None
