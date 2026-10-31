"""Оркестрация ревью: GitLab → портал ТЗ → сверка → линтер → модель → БД.

Выполняется синхронно (ревьюеров двое, очередь пока не нужна).
"""
import logging
import os

from flask import current_app

from ..extensions import db
from ..linters import lint_file
from ..models import Finding, Review, ReviewFile, Ticket, TzObject, utcnow
from . import context_builder, prompts
from .diff_utils import added_line_numbers, diff_stats, make_unified_diff, parse_unified_diff
from .gitlab_client import GitLabError, get_gitlab_client, parse_mr_url
from .llm_client import LLMError, get_llm_client, parse_llm_response
from .tz_matcher import extract_ticket_key, match_objects, tail_matches
from .tz_portal import TzPortalError, get_tz_portal_client

log = logging.getLogger(__name__)

MR_STATES = {"opened", "merged", "closed", "locked", "all"}


class ReviewError(Exception):
    pass


def _is_code(path, extensions):
    return bool(path) and os.path.splitext(path)[1].lower() in extensions


def sync_ticket(key):
    """Подтягивает тикет и объекты ТЗ с портала и сохраняет в БД. Возвращает Ticket или None."""
    cfg = current_app.config
    data = get_tz_portal_client(cfg).get_ticket(key)
    ticket = Ticket.query.filter_by(key=key).first()
    if data is None:
        return ticket
    if ticket is None:
        ticket = Ticket(key=key)
        db.session.add(ticket)
    ticket.title = data.get("title")
    ticket.description = data.get("description")
    ticket.developer = data.get("developer")
    ticket.analyst = data.get("analyst")
    ticket.portal_url = data.get("portal_url")
    ticket.fetched_at = utcnow()
    ticket.objects.clear()
    for obj in data.get("objects") or []:
        ticket.objects.append(TzObject(
            system_name=obj["system_name"],
            display_name=obj.get("display_name"),
            change_description=obj.get("change_description"),
        ))
    db.session.flush()
    return ticket


def create_review(mr_url, ticket_key=None, reviewer=None):
    cfg = current_app.config
    project, iid = parse_mr_url(mr_url, cfg.get("GITLAB_URL", ""))
    review = Review(mr_url=mr_url.strip(), gitlab_project=project, mr_iid=iid,
                    ticket_key=(ticket_key or "").strip().upper() or None,
                    reviewer=reviewer, status="pending")
    db.session.add(review)
    db.session.commit()
    run_review(review)
    return review


def sync_project(project=None, state=None, reviewer=None):
    """Импорт всех MR проекта: новые MR анализируются, обновлённые (новый head_sha) и упавшие — перезапускаются.

    Возвращает сводку {project, state, total, created, updated, skipped, failed}.
    """
    cfg = current_app.config
    project = (project or cfg.get("GITLAB_PROJECT") or "").strip().strip("/")
    if not project:
        raise ReviewError("Не задан проект GitLab (GITLAB_PROJECT)")
    state = (state or cfg.get("GITLAB_MR_STATE") or "all").lower()
    if state not in MR_STATES:
        raise ReviewError(f"Некорректное состояние MR: {state}")

    mrs = get_gitlab_client(cfg).list_merge_requests(project, state)
    summary = {"project": project, "state": state, "total": len(mrs),
               "created": 0, "updated": 0, "skipped": 0, "failed": 0}
    for mr in mrs:
        review = (Review.query.filter_by(gitlab_project=project, mr_iid=mr["iid"])
                  .order_by(Review.id.desc()).first())
        if review is None:
            review = Review(mr_url=mr["web_url"] or f"{project}/-/merge_requests/{mr['iid']}",
                            gitlab_project=project, mr_iid=mr["iid"], reviewer=reviewer,
                            status="pending")
            db.session.add(review)
            db.session.commit()
            summary["created"] += 1
        elif review.status == "done" and review.head_sha and review.head_sha == mr["head_sha"]:
            summary["skipped"] += 1
            continue
        else:
            summary["updated"] += 1
        run_review(review)
        if review.status == "failed":
            summary["failed"] += 1
    return summary


def run_review(review):
    """(Пере)запуск анализа. Замечания ревьюера сохраняются, lint/llm пересчитываются."""
    review.status = "running"
    review.error = None
    db.session.commit()
    try:
        _run(review)
        review.status = "done"
    except (GitLabError, TzPortalError, ReviewError) as exc:
        db.session.rollback()
        review.status = "failed"
        review.error = str(exc)
    except Exception as exc:  # noqa: BLE001
        log.exception("Ошибка ревью %s", review.id)
        db.session.rollback()
        review.status = "failed"
        review.error = f"Внутренняя ошибка: {exc}"
    db.session.commit()
    return review


def _run(review):
    cfg = current_app.config
    gl = get_gitlab_client(cfg)

    # --- 1. MR из GitLab
    mr = gl.get_merge_request(review.gitlab_project, review.mr_iid)
    review.mr_title = mr["title"]
    review.mr_description = mr["description"]
    review.mr_author = mr["author"]
    review.source_branch = mr["source_branch"]
    review.target_branch = mr["target_branch"]
    review.base_sha = mr["base_sha"]
    review.head_sha = mr["head_sha"]

    # --- 2. Тикет и ТЗ
    key = review.ticket_key or extract_ticket_key(
        cfg["TICKET_REGEX"], mr["title"], mr["source_branch"], mr["description"]
    )
    review.ticket_key = key
    ticket = sync_ticket(key) if key else None
    review.ticket = ticket

    # --- 3. Файлы MR (пересоздаём; замечания ревьюера к удалённым файлам теряют привязку)
    reviewer_findings = [f for f in review.findings if f.source == "reviewer"]
    old_paths = {f.id: f.path for f in review.files}
    for f in list(review.findings):
        if f.source != "reviewer":
            review.findings.remove(f)
    for f in reviewer_findings:
        f._old_path = old_paths.get(f.file_id)
        f.file_id = None
    db.session.flush()
    review.files.clear()
    db.session.flush()

    changes = gl.get_merge_request_changes(review.gitlab_project, review.mr_iid)
    for ch in changes:
        old_content = new_content = None
        is_code = _is_code(ch["new_path"] or ch["old_path"], cfg["CODE_EXTENSIONS"])
        if ch["change_type"] != "added":
            old_content = gl.get_file_content(review.gitlab_project, ch["old_path"], review.base_sha)
        if ch["change_type"] != "deleted":
            new_content = gl.get_file_content(review.gitlab_project, ch["new_path"], review.head_sha)
        diff = ch["diff"]
        if not diff and (old_content or new_content):
            diff = make_unified_diff(old_content or "", new_content or "")
        hunks = parse_unified_diff(diff)
        adds, dels = diff_stats(hunks)
        review.files.append(ReviewFile(
            old_path=ch["old_path"], new_path=ch["new_path"], change_type=ch["change_type"],
            diff=diff, hunks=hunks, old_content=old_content, new_content=new_content,
            additions=adds, deletions=dels, is_code=is_code,
        ))
    db.session.flush()

    # восстановить привязку замечаний ревьюера по пути файла
    by_path = {f.path: f.id for f in review.files}
    for f in reviewer_findings:
        f.file_id = by_path.get(getattr(f, "_old_path", None))

    # --- 4. Сверка с ТЗ
    tz_objects = [o.to_dict() for o in ticket.objects] if ticket else []
    files_info = [{"id": f.id, "old_path": f.old_path, "new_path": f.new_path,
                   "change_type": f.change_type} for f in review.files]
    check = match_objects(tz_objects, files_info, cfg["TZ_IGNORE_PATTERNS"])
    for f in review.files:
        status, obj_id = check["file_status"].get(f.id, (None, None))
        f.tz_status = status
        f.tz_object_id = obj_id
    check.pop("file_status")
    check["ticket_found"] = ticket is not None
    check["ticket_key"] = key
    check["objects_total"] = len(tz_objects)
    if key and ticket is None:
        check["warning"] = f"Тикет {key} не найден на портале ТЗ"
    elif not key:
        check["warning"] = "Номер тикета не найден в названии MR, ветке или описании"
    review.tz_check = check

    # --- 5. Линтер (только добавленные строки)
    for f in review.files:
        if not f.is_code or f.change_type == "deleted" or not f.new_content:
            continue
        for issue in lint_file(f.path, f.new_content, cfg, only_lines=added_line_numbers(f.hunks)):
            review.findings.append(Finding(
                file_id=f.id, source="lint", rule=issue.rule, severity=issue.severity,
                line=issue.line, side="new", message=issue.message, suggestion=issue.suggestion,
            ))

    # --- 6. Модель
    _run_llm(review, ticket, tz_objects)
    db.session.flush()


def _run_llm(review, ticket, tz_objects):
    cfg = current_app.config
    obj_by_id = {o["id"]: o for o in tz_objects}
    files = []
    for f in sorted(review.files, key=lambda x: (x.tz_status != "matched", x.id)):
        if not f.is_code or f.change_type == "deleted":
            continue
        obj = obj_by_id.get(f.tz_object_id)
        files.append({
            "file_id": f.id, "path": f.path, "change_type": f.change_type,
            "hunks": f.hunks, "new_content": f.new_content, "tz_status": f.tz_status,
            "tz_change": (obj or {}).get("change_description"),
        })
    header = prompts.build_header(ticket.to_dict(with_objects=False) if ticket else None,
                                  cfg["LLM_MAX_TZ_CHARS"])
    batches, stats = context_builder.build_batches(
        files, header, cfg["LLM_MAX_INPUT_TOKENS"], cfg["LLM_CONTEXT_LINES"]
    )
    stats["mode"] = cfg["LLM_MODE"]
    stats["errors"] = []
    if not batches:
        review.llm_stats = stats
        return
    try:
        client = get_llm_client(cfg)
    except LLMError as exc:
        stats["errors"].append(str(exc))
        review.llm_stats = stats
        return

    files_by_id = {f.id: f for f in review.files}
    count = 0
    for batch in batches:
        try:
            answer = client.complete(prompts.SYSTEM_PROMPT, batch["text"])
        except LLMError as exc:
            stats["errors"].append(str(exc))
            continue
        for item in parse_llm_response(answer):
            file_id = _resolve_file(item.get("file"), batch["files"])
            line = item["line"]
            if file_id is not None and line is not None:
                total = len((files_by_id[file_id].new_content or "").splitlines())
                if total and not (1 <= line <= total):
                    line = None
            review.findings.append(Finding(
                file_id=file_id, source="llm", severity=item["severity"],
                line=line if file_id is not None else None, side="new",
                message=item["message"], suggestion=item["suggestion"],
            ))
            count += 1
    stats["comments"] = count
    review.llm_stats = stats


def _resolve_file(path, batch_files):
    if not batch_files:
        return None
    if path:
        for f in batch_files:
            if f["path"] == path:
                return f["file_id"]
        for f in batch_files:
            if tail_matches(path, f["path"]) or tail_matches(f["path"], path):
                return f["file_id"]
    if len(batch_files) == 1:
        return batch_files[0]["file_id"]
    return None
