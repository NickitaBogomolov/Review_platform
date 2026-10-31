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
            "description": mr.get("description"),
            "author": (mr.get("author") or {}).get("name"),
            "source_branch": mr.get("source_branch"),
            "target_branch": mr.get("target_branch"),
            "base_sha": refs.get("base_sha"),
            "head_sha": refs.get("head_sha") or mr.get("sha"),
            "web_url": mr.get("web_url"),
        }

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
        return [
            {
                "old_path": it.get("old_path"),
                "new_path": it.get("new_path"),
                "change_type": _change_type(it),
                "diff": it.get("diff") or "",
                "too_large": bool(it.get("too_large") or it.get("collapsed")) and not it.get("diff"),
            }
            for it in items
        ]

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
    """Отдаёт демо-MR из app/fixtures/demo_mr.json на любую ссылку. Включается GITLAB_MOCK=true."""

    def __init__(self, path=None):
        path = path or os.path.join(os.path.dirname(__file__), "..", "fixtures", "demo_mr.json")
        with open(path, encoding="utf-8") as fh:
            self.data = json.load(fh)

    def get_merge_request(self, project, iid):
        mr = dict(self.data["merge_request"])
        mr["web_url"] = f"mock://{project}/-/merge_requests/{iid}"
        return mr

    def get_merge_request_changes(self, project, iid):
        result = []
        for f in self.data["files"]:
            result.append({
                "old_path": f.get("old_path") or f.get("new_path"),
                "new_path": f.get("new_path") or f.get("old_path"),
                "change_type": f["change_type"],
                "diff": make_unified_diff("\n".join(f.get("old", [])), "\n".join(f.get("new", []))),
                "too_large": False,
            })
        return result

    def get_file_content(self, project, path, ref):
        side = "old" if ref == self.data["merge_request"]["base_sha"] else "new"
        for f in self.data["files"]:
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
