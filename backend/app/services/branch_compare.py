"""Сверка MR в тестовую ветку с коммитами того же тикета в dev-ветке.

Цель — убедиться, что в тестовую ветку несётся то же самое, что накопилось по тикету в dev-ветке.
С одной стороны — коммиты тикета в dev-ветке, с другой — коммиты тикета, уже влитые в тестовую ветку,
плюс этот MR: тикет может доезжать несколькими MR.

Ветки расходятся, поэтому номера строк и контекст сравнивать нельзя. Для каждого файла считается
«чистый итог» правок: сколько раз строка добавлена минус сколько раз удалена. Правка, откатанная
следующим коммитом тикета, в итог не попадает.
"""
import re
from collections import Counter

from .diff_utils import make_unified_diff, parse_unified_diff
from .gitlab_client import GitLabError
from .tz_matcher import is_ignored

MAX_LINES_PER_FILE = 200


def find_ticket_commits(commits, key, branch):
    """Коммиты ветки, в сообщении которых есть номер тикета.

    Merge-коммиты не берём: их изменения уже есть в обычных коммитах. Исключение — у тикета нашлись
    только merge-коммиты: значит, номер есть лишь в их сообщениях. Обратное вливание самой ветки
    (`Merge branch 'develop_dev' into RCK2-1`) не берём никогда: оно принесло бы чужие правки.
    """
    pattern = re.compile(rf"(?<![A-Za-z0-9]){re.escape(key)}(?![A-Za-z0-9])", re.IGNORECASE)
    matched = [c for c in commits if pattern.search(c["message"])]
    plain = [c for c in matched if len(c["parent_ids"]) < 2]
    if plain:
        return plain
    back_merge = re.compile(rf"^Merge (remote-tracking )?branch '(origin/)?{re.escape(branch)}'")
    return [c for c in matched if not back_merge.match(c["message"])]


def _commit_hunks(gl, project, commit, change):
    diff = change["diff"]
    if not diff:  # GitLab не отдаёт diff больших файлов
        parent = commit["parent_ids"][0] if commit["parent_ids"] else None
        old = gl.get_file_content(project, change["old_path"], parent) if change["change_type"] != "added" else ""
        new = gl.get_file_content(project, change["new_path"], commit["id"]) if change["change_type"] != "deleted" else ""
        diff = make_unified_diff(old or "", new or "")
    return parse_unified_diff(diff)


def _net_lines(hunks, net=None):
    """Пробелы и пустые строки не сравниваем: при ручном переносе правок они легко меняются."""
    net = Counter() if net is None else net
    for hunk in hunks:
        for line in hunk["lines"]:
            text = " ".join(line["text"].split())
            if not text:
                continue
            if line["type"] == "add":
                net[text] += 1
            elif line["type"] == "del":
                net[text] -= 1
    return net


def collect_changes(gl, project, commits):
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


def compare_changes(dev_changes, tst_changes, mr_files, ignore_patterns=(), mr_merged=False):
    """Сравнивает итоги правок. Возвращает [{path, file_id, status, dev_only, mr_only, truncated}].

    mr_merged — MR уже влит: его правки входят в коммиты тестовой ветки, и второй раз их не считаем.

    status:
      same            — файл есть в MR, правки совпадают
      differs         — файл несётся в тестовую ветку, но правки отличаются
      only_in_dev     — правки dev-ветки в тестовую ветку не несутся
      only_in_mr      — файл несётся в тестовую ветку, но коммиты тикета в dev-ветке его не трогали
      already_applied — файла нет в MR, правки совпадают с уже влитыми в тестовую ветку
      ignored         — служебный файл
    """
    mr_by_path = {f.path: f for f in mr_files}
    result = []
    for path in sorted(set(dev_changes) | set(tst_changes) | set(mr_by_path)):
        mr_file = mr_by_path.get(path)
        item = {"path": path, "file_id": mr_file.id if mr_file else None,
                "dev_only": [], "mr_only": [], "truncated": False}
        result.append(item)
        if is_ignored(path, ignore_patterns):
            item["status"] = "ignored"
            continue
        if path not in dev_changes:
            item["status"] = "only_in_mr"
            continue
        if not mr_file and path not in tst_changes:
            item["status"] = "only_in_dev"

        dev_net = dev_changes[path]
        tst_net = Counter(tst_changes.get(path, {}))
        if mr_file and not mr_merged:
            _net_lines(mr_file.hunks or [], tst_net)

        dev_only = _line_items("add", +dev_net - +tst_net) + _line_items("del", -dev_net - -tst_net)
        mr_only = _line_items("add", +tst_net - +dev_net) + _line_items("del", -tst_net - -dev_net)
        item["truncated"] = len(dev_only) > MAX_LINES_PER_FILE or len(mr_only) > MAX_LINES_PER_FILE
        item["dev_only"] = dev_only[:MAX_LINES_PER_FILE]
        item["mr_only"] = mr_only[:MAX_LINES_PER_FILE]
        if "status" not in item:
            if dev_only or mr_only:
                item["status"] = "differs"
            else:
                item["status"] = "same" if mr_file else "already_applied"
    return result


def _commit_info(commits):
    return [{k: c[k] for k in ("id", "short_id", "title", "author", "created_at", "web_url")} for c in commits]


def check_against_dev(gl, cfg, project, key, mr_files, mr_merged=False):
    """Результат сверки для Review.branch_check. Ошибка GitLab не роняет ревью, а показывается в панели."""
    dev_branch = cfg["GITLAB_DEV_BRANCH"]
    tst_branch = cfg["GITLAB_TST_BRANCH"]
    result = {"dev_branch": dev_branch, "tst_branch": tst_branch, "ticket_key": key,
              "commits": [], "tst_commits": [], "files": [], "warning": None, "error": None, "ok": False}
    if not key:
        result["warning"] = f"Номер тикета не определён — не по чему искать коммиты в {dev_branch}"
        return result

    limit = cfg["GITLAB_MAX_BRANCH_COMMITS"]
    try:
        all_dev = gl.list_branch_commits(project, dev_branch, limit)
        all_tst = gl.list_branch_commits(project, tst_branch, limit)
        commits = find_ticket_commits(all_dev, key, dev_branch)
        tst_commits = find_ticket_commits(all_tst, key, tst_branch)
        files = compare_changes(collect_changes(gl, project, commits), collect_changes(gl, project, tst_commits),
                                mr_files, cfg["TZ_IGNORE_PATTERNS"], mr_merged)
    except GitLabError as exc:
        result["error"] = str(exc)
        return result

    result["commits"] = _commit_info(commits)
    result["tst_commits"] = _commit_info(tst_commits)
    result["files"] = files
    warnings = []
    if not commits:
        warnings.append(f"В ветке {dev_branch} нет коммитов с номером {key}")
    for branch, branch_commits in ((dev_branch, all_dev), (tst_branch, all_tst)):
        if len(branch_commits) >= limit:
            warnings.append(f"Просмотрены только последние {limit} коммитов {branch} — более ранние коммиты "
                            "тикета могли не попасть в сверку (GITLAB_MAX_BRANCH_COMMITS)")
    result["warning"] = ". ".join(warnings) or None
    result["ok"] = bool(commits) and not any(
        f["status"] in ("differs", "only_in_dev", "only_in_mr") for f in files)
    return result
