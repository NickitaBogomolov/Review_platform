"""Клиент GitLab API (self-hosted) + фикстурный клиент для локальной разработки."""
import json
import os
import re
from urllib.parse import quote

import requests

from .diff_utils import decode_bytes, make_unified_diff



class GitLabError(Exception):
    pass


def parse_mr_url(url, gitlab_url=""):
    """https://gitlab.local/group/sub/project/-/merge_requests/42 -> ('group/sub/project', 42).

    Если GitLab развёрнут не в корне домена (https://host/gitlab/...), префикс берётся из GITLAB_URL.
    """
    url = (url or "").strip()
    if gitlab_url and url.startswith(gitlab_url + "/"):
        rest = url[len(gitlab_url) + 1:]
        m = re.match(r"^(?P<project>.+?)/-/merge_requests/(?P<iid>\d+)", rest)
        if m:
            return m.group("project"), int(m.group("iid"))
    m = re.match(r"^https?://[^/]+/(?P<project>.+?)/-/merge_requests/(?P<iid>\d+)", url)
    if not m:
        raise GitLabError(
            "Не удалось разобрать ссылку на MR. Ожидается вид "
            "https://gitlab.../group/project/-/merge_requests/123"
        )
    return m.group("project"), int(m.group("iid"))


def _change_type(item):
    if item.get("new_file"):
        return "added"
    if item.get("deleted_file"):
        return "deleted"
    if item.get("renamed_file"):
        return "renamed"
    return "modified"


def _change_item(item):
    return {
        "old_path": item.get("old_path"),
        "new_path": item.get("new_path"),
        "change_type": _change_type(item),
        "diff": item.get("diff") or "",
        "too_large": bool(item.get("too_large") or item.get("collapsed")) and not item.get("diff"),
    }


class GitLabClient:
    def __init__(self, base_url, token, verify=True, timeout=30):
        if not base_url:
            raise GitLabError("Не задан GITLAB_URL")
        self.api = base_url.rstrip("/") + "/api/v4"
        self.session = requests.Session()
        self.session.headers["PRIVATE-TOKEN"] = token or ""
        self.session.verify = verify
        self.timeout = timeout

    def _get(self, path, params=None, raw=False):
        try:
            resp = self.session.get(self.api + path, params=params, timeout=self.timeout)
        except requests.RequestException as exc:
            raise GitLabError(f"GitLab недоступен: {exc}") from exc
        if resp.status_code == 404:
            return None
        if resp.status_code in (401, 403):
            raise GitLabError("GitLab: нет доступа (проверьте GITLAB_TOKEN, нужен scope read_api)")
        if not resp.ok:
            raise GitLabError(f"GitLab вернул {resp.status_code}: {resp.text[:300]}")
        return resp if raw else resp.json()

    @staticmethod
    def _pid(project):
        return quote(project, safe="")

    def get_merge_request(self, project, iid):
        mr = self._get(f"/projects/{self._pid(project)}/merge_requests/{iid}")
        if mr is None:
            raise GitLabError(f"MR !{iid} в проекте {project} не найден")
        refs = mr.get("diff_refs") or {}
        return {
            "title": mr.get("title"),
            "state": mr.get("state"),
            "description": mr.get("description"),
            "author": (mr.get("author") or {}).get("name"),
            "source_branch": mr.get("source_branch"),
            "target_branch": mr.get("target_branch"),
            "base_sha": refs.get("base_sha"),
            "head_sha": refs.get("head_sha") or mr.get("sha"),
            "web_url": mr.get("web_url"),
        }

    def list_merge_requests(self, project, state="all"):
        """Все MR проекта (state: opened / merged / closed / locked / all), от старых к новым."""
        pid = self._pid(project)
        params = {"per_page": 100, "order_by": "created_at", "sort": "asc"}
        if state and state != "all":
            params["state"] = state
        items = []
        page = 1
        while True:
            chunk = self._get(f"/projects/{pid}/merge_requests", params={**params, "page": page})
            if chunk is None:
                raise GitLabError(f"Проект {project} не найден в GitLab")
            items.extend(chunk)
            if len(chunk) < 100:
                break
            page += 1
        return [
            {
                "iid": it["iid"],
                "title": it.get("title"),
                "state": it.get("state"),
                "head_sha": it.get("sha"),
                "web_url": it.get("web_url"),
            }
            for it in items
        ]

    def get_merge_request_changes(self, project, iid):
        """Список изменённых файлов. Сначала /diffs (GitLab >= 15.7), затем /changes."""
        pid = self._pid(project)
        items = []
        page = 1
        while True:
            chunk = self._get(f"/projects/{pid}/merge_requests/{iid}/diffs",
                              params={"page": page, "per_page": 100})
            if chunk is None:
                items = None
                break
            items.extend(chunk)
            if len(chunk) < 100:
                break
            page += 1
        if items is None:
            data = self._get(f"/projects/{pid}/merge_requests/{iid}/changes",
                             params={"access_raw_diffs": "true"})
            items = (data or {}).get("changes", [])
        return [_change_item(it) for it in items]

    def list_branch_commits(self, project, branch, limit=5000):
        """Коммиты ветки от новых к старым, не больше limit. API не умеет искать по сообщению."""
        pid = self._pid(project)
        items = []
        page = 1
        while len(items) < limit:
            chunk = self._get(f"/projects/{pid}/repository/commits",
                              params={"ref_name": branch, "page": page, "per_page": 100})
            if chunk is None:
                raise GitLabError(f"Ветка {branch} в проекте {project} не найдена")
            items.extend(chunk)
            if len(chunk) < 100:
                break
            page += 1
        return [
            {
                "id": it["id"],
                "short_id": it.get("short_id") or it["id"][:8],
                "title": it.get("title"),
                "message": it.get("message") or it.get("title") or "",
                "parent_ids": it.get("parent_ids") or [],
                "author": it.get("author_name"),
                "created_at": it.get("created_at"),
                "web_url": it.get("web_url"),
            }
            for it in items[:limit]
        ]

    def get_commit_changes(self, project, sha):
        """Файлы коммита. Для merge-коммита GitLab отдаёт изменения относительно первого родителя."""
        pid = self._pid(project)
        items = []
        page = 1
        while True:
            chunk = self._get(f"/projects/{pid}/repository/commits/{sha}/diff",
                              params={"page": page, "per_page": 100})
            if chunk is None:
                raise GitLabError(f"Коммит {sha} в проекте {project} не найден")
            items.extend(chunk)
            if len(chunk) < 100:
                break
            page += 1
        return [_change_item(it) for it in items]

    def get_file_content(self, project, path, ref):
        if not path or not ref:
            return None
        resp = self._get(
            f"/projects/{self._pid(project)}/repository/files/{quote(path, safe='')}/raw",
            params={"ref": ref},
            raw=True,
        )
        if resp is None:
            return None
        return decode_bytes(resp.content)


class FixtureGitLabClient:
    """Демо-данные вместо GitLab. Включается GITLAB_MOCK=true.

    app/fixtures/demo_mr.json — MR !1, app/fixtures/demo_scenarios.json — остальные демо-сценарии.
    Ссылка с неизвестным номером MR открывает MR !1.
    """

    def __init__(self):
        fixtures = os.path.join(os.path.dirname(__file__), "..", "fixtures")
        with open(os.path.join(fixtures, "demo_mr.json"), encoding="utf-8") as fh:
            demo = json.load(fh)
        with open(os.path.join(fixtures, "demo_scenarios.json"), encoding="utf-8") as fh:
            scenarios = json.load(fh)
        self.mrs = [{"iid": 1, **demo}] + scenarios["merge_requests"]
        self.branches = {
            "develop_dev": demo["dev_commits"] + scenarios["dev_commits"],
            "develop_tst": scenarios["tst_commits"],
        }

    def _mr(self, iid):
        return next((m for m in self.mrs if m["iid"] == iid), self.mrs[0])

    @staticmethod
    def _changes(files):
        return [
            {
                "old_path": f.get("old_path") or f.get("new_path"),
                "new_path": f.get("new_path") or f.get("old_path"),
                "change_type": f["change_type"],
                "diff": make_unified_diff("\n".join(f.get("old", [])), "\n".join(f.get("new", []))),
                "too_large": False,
            }
            for f in files
        ]

    def get_merge_request(self, project, iid):
        mr = {"state": "opened", **self._mr(iid)["merge_request"]}
        mr["web_url"] = f"mock://{project}/-/merge_requests/{iid}"
        return mr

    def list_merge_requests(self, project, state="all"):
        result = []
        for m in self.mrs:
            mr = m["merge_request"]
            mr_state = mr.get("state", "opened")
            if state in ("all", mr_state):
                result.append({"iid": m["iid"], "title": mr["title"], "state": mr_state, "head_sha": mr["head_sha"],
                               "web_url": f"mock://{project}/-/merge_requests/{m['iid']}"})
        return result

    def get_merge_request_changes(self, project, iid):
        return self._changes(self._mr(iid)["files"])

    def list_branch_commits(self, project, branch, limit=5000):
        commits = sorted(self.branches.get(branch, []), key=lambda c: c["created_at"], reverse=True)
        return [
            {
                "id": c["id"],
                "short_id": c["id"][:8],
                "title": c["message"].split("\n")[0],
                "message": c["message"],
                "parent_ids": c.get("parent_ids", []),
                "author": c.get("author"),
                "created_at": c.get("created_at"),
                "web_url": None,
            }
            for c in commits
        ][:limit]

    def get_commit_changes(self, project, sha):
        commits = [c for branch in self.branches.values() for c in branch]
        commit = next((c for c in commits if c["id"] == sha), None)
        if commit is None:
            raise GitLabError(f"Коммит {sha} в проекте {project} не найден")
        mr_files = {f.get("new_path"): f for m in self.mrs for f in m["files"]}
        # from_mr — коммит содержит ровно те же правки файла, что и демо-MR
        return self._changes([mr_files[f["from_mr"]] if "from_mr" in f else f for f in commit["files"]])

    def get_file_content(self, project, path, ref):
        for m in self.mrs:
            mr = m["merge_request"]
            if ref not in (mr["base_sha"], mr["head_sha"]):
                continue
            side = "old" if ref == mr["base_sha"] else "new"
            for f in m["files"]:
                key = "old_path" if side == "old" else "new_path"
                if (f.get(key) or f.get("new_path") or f.get("old_path")) == path:
                    lines = f.get(side)
                    if not lines and ((side == "old" and f["change_type"] == "added")
                                      or (side == "new" and f["change_type"] == "deleted")):
                        return None
                    return "\n".join(lines) + "\n"
        return None


def get_gitlab_client(config):
    if config.get("GITLAB_MOCK"):
        return FixtureGitLabClient()
    return GitLabClient(
        config["GITLAB_URL"],
        config["GITLAB_TOKEN"],
        verify=config["GITLAB_VERIFY_SSL"],
        timeout=config["GITLAB_TIMEOUT"],
    )
