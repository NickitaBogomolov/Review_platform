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
    assert (s["project"], s["total"], s["created"], s["failed"]) == ("bank/ibso", 1, 1, 0)

    reviews = client.get("/api/reviews").get_json()
    assert len(reviews) == 1 and reviews[0]["mr_iid"] == 1 and reviews[0]["status"] == "done"

    # повторный импорт: MR не менялся — пропускается, дубликат не создаётся
    s2 = client.post("/api/reviews/sync", json={}).get_json()
    assert (s2["created"], s2["updated"], s2["skipped"]) == (0, 0, 1)
    assert len(client.get("/api/reviews").get_json()) == 1


def test_sync_bad_state(client):
    assert client.post("/api/reviews/sync", json={"state": "whatever"}).status_code == 400
