"""Сверка MR в тестовую ветку с коммитами того же тикета в dev-ветке.

Ветки расходятся, поэтому номера строк и контекст сравнивать нельзя. Для каждого файла считается
«чистый итог» правок: сколько раз строка добавлена минус сколько раз удалена. Правка, откатанная
следующим коммитом тикета, в итог не попадает.
"""
import re
from collections import Counter

from .diff_utils import content_lines, make_unified_diff, parse_unified_diff
from .gitlab_client import GitLabError
from .tz_matcher import is_ignored

MAX_LINES_PER_FILE = 200


def find_ticket_commits(commits, key, dev_branch):
    """Коммиты, в сообщении которых есть номер тикета.

    Merge-коммиты не берём: их изменения уже есть в обычных коммитах ветки, а обратное вливание
    (`Merge develop_dev into RCK2-1`) принесло бы чужие правки. Исключение — у тикета нашлись только
    вливания в dev-ветку: значит, номер есть лишь в сообщении merge-коммита.
    """
    pattern = re.compile(rf"(?<![A-Za-z0-9]){re.escape(key)}(?![A-Za-z0-9])", re.IGNORECASE)
    matched = [c for c in commits if pattern.search(c["message"])]
    plain = [c for c in matched if len(c["parent_ids"]) < 2]
    if plain:
        return plain
    into_dev = re.compile(rf"\binto\s+'?{re.escape(dev_branch)}'?(\s|$)")
    return [c for c in matched if into_dev.search(c["message"])]


def _commit_hunks(gl, project, commit, change):
    diff = change["diff"]
    if not diff:  # GitLab не отдаёт diff больших файлов
        parent = commit["parent_ids"][0] if commit["parent_ids"] else None
        old = gl.get_file_content(project, change["old_path"], parent) if change["change_type"] != "added" else ""
        new = gl.get_file_content(project, change["new_path"], commit["id"]) if change["change_type"] != "deleted" else ""
        diff = make_unified_diff(old or "", new or "")
    return parse_unified_diff(diff)


def _net_lines(hunks, net=None):
    net = Counter() if net is None else net
    for hunk in hunks:
        for line in hunk["lines"]:
            if line["type"] == "add":
                net[line["text"]] += 1
            elif line["type"] == "del":
                net[line["text"]] -= 1
    return net


def collect_dev_changes(gl, project, commits):
    """{path: Counter(строка -> итог)}; переименования прослеживаются, файлы с нулевым итогом отбрасываются."""
    net = {}
    renamed = set()
    for commit in reversed(commits):  # от старых к новым
        for change in gl.get_commit_changes(project, commit["id"]):
            path = change["new_path"] or change["old_path"]
            if change["change_type"] == "renamed":
                net[path] = net.pop(change["old_path"], Counter())
                renamed.discard(change["old_path"])
                renamed.add(path)
            _net_lines(_commit_hunks(gl, project, commit, change), net.setdefault(path, Counter()))
    return {path: lines for path, lines in net.items() if path in renamed or any(lines.values())}


def _line_items(kind, lines):
    return [{"type": kind, "text": text, "count": count} for text, count in sorted(lines.items())]


def compare_changes(dev_changes, mr_files, load_content, ignore_patterns=()):
    """Сравнивает итоги правок. Возвращает [{path, file_id, status, dev_only, mr_only, applied, truncated}].

    status: same | differs | only_in_dev | only_in_mr | already_applied | ignored

    Правка из dev-ветки не считается потерянной, если её результат уже есть в итоговой версии файла:
    например, тикет доехал до тестовой ветки в предыдущем MR.
    """
    mr_by_path = {f.path: f for f in mr_files}
    result = []
    for path in sorted(set(dev_changes) | set(mr_by_path)):
        mr_file = mr_by_path.get(path)
        item = {"path": path, "file_id": mr_file.id if mr_file else None,
                "dev_only": [], "mr_only": [], "applied": 0, "truncated": False}
        result.append(item)
        if is_ignored(path, ignore_patterns):
            item["status"] = "ignored"
            continue
        if path not in dev_changes:
            item["status"] = "only_in_mr"
            continue

        dev_net = dev_changes[path]
        mr_net = _net_lines(mr_file.hunks or []) if mr_file else Counter()
        content = mr_file.new_content if mr_file else load_content(path)
        present = set(content_lines(content))

        lost_added = +dev_net - +mr_net
        lost_removed = -dev_net - -mr_net
        dev_only_added = Counter({t: n for t, n in lost_added.items() if t not in present})
        dev_only_removed = Counter({t: n for t, n in lost_removed.items() if t in present})
        item["applied"] = (sum(lost_added.values()) - sum(dev_only_added.values())
                           + sum(lost_removed.values()) - sum(dev_only_removed.values()))
        dev_only = _line_items("add", dev_only_added) + _line_items("del", dev_only_removed)
        mr_only = _line_items("add", +mr_net - +dev_net) + _line_items("del", -mr_net - -dev_net)

        item["truncated"] = len(dev_only) > MAX_LINES_PER_FILE or len(mr_only) > MAX_LINES_PER_FILE
        item["dev_only"] = dev_only[:MAX_LINES_PER_FILE]
        item["mr_only"] = mr_only[:MAX_LINES_PER_FILE]
        if mr_file:
            item["status"] = "differs" if dev_only or mr_only else "same"
        elif dev_only or (content is None and not any(dev_net.values())):
            item["status"] = "only_in_dev"
        else:
            item["status"] = "already_applied"
    return result


def check_against_dev(gl, cfg, project, key, mr_files, head_sha):
    """Результат сверки для Review.branch_check. Ошибка GitLab не роняет ревью, а показывается в панели."""
    dev_branch = cfg["GITLAB_DEV_BRANCH"]
    result = {"dev_branch": dev_branch, "tst_branch": cfg["GITLAB_TST_BRANCH"], "ticket_key": key,
              "commits": [], "files": [], "warning": None, "error": None, "ok": False}
    if not key:
        result["warning"] = f"Номер тикета не определён — не по чему искать коммиты в {dev_branch}"
        return result

    limit = cfg["GITLAB_MAX_BRANCH_COMMITS"]
    try:
        all_commits = gl.list_branch_commits(project, dev_branch, limit)
        commits = find_ticket_commits(all_commits, key, dev_branch)
        dev_changes = collect_dev_changes(gl, project, commits)
        files = compare_changes(dev_changes, mr_files, lambda path: gl.get_file_content(project, path, head_sha),
                                cfg["TZ_IGNORE_PATTERNS"])
    except GitLabError as exc:
        result["error"] = str(exc)
        return result

    result["commits"] = [{k: c[k] for k in ("id", "short_id", "title", "author", "created_at", "web_url")}
                         for c in commits]
    result["files"] = files
    warnings = []
    if not commits:
        warnings.append(f"В ветке {dev_branch} нет коммитов с номером {key}")
    if len(all_commits) >= limit:
        warnings.append(f"Просмотрены только последние {limit} коммитов {dev_branch} — более ранние коммиты "
                        "тикета могли не попасть в сверку (GITLAB_MAX_BRANCH_COMMITS)")
    result["warning"] = ". ".join(warnings) or None
    result["ok"] = bool(commits) and not any(
        f["status"] in ("differs", "only_in_dev", "only_in_mr") for f in files)
    return result
