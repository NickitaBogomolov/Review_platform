from flask import current_app, jsonify, request

from ..extensions import db
from ..linters import available_rules
from ..models import Finding, Review, ReviewFile, Ticket
from ..services.diff_utils import content_lines
from ..services.gitlab_client import GitLabError
from ..services.review_service import ReviewError, create_review, run_review, sync_project, sync_ticket
from ..services.tz_portal import TzPortalError
from . import api_bp

VERDICTS = {"pending", "approved", "changes_requested"}
FINDING_STATUSES = {"open", "accepted", "dismissed"}
SEVERITIES = {"info", "minor", "major", "critical"}


def _error(message, code=400):
    return jsonify(error=message), code


def _get_or_404(model, obj_id):
    obj = db.session.get(model, obj_id)
    if obj is None:
        from flask import abort
        abort(404)
    return obj


@api_bp.get("/health")
def health():
    cfg = current_app.config
    return jsonify(
        status="ok",
        gitlab_mock=cfg["GITLAB_MOCK"],
        gitlab_project=cfg["GITLAB_PROJECT"] or None,
        gitlab_mr_state=cfg["GITLAB_MR_STATE"],
        tz_portal_mode=cfg["TZ_PORTAL_MODE"],
        llm_mode=cfg["LLM_MODE"],
    )


@api_bp.get("/lint-rules")
def lint_rules():
    disabled = set(current_app.config["LINT_DISABLED_RULES"])
    return jsonify([{**r, "enabled": r["id"] not in disabled} for r in available_rules()])


@api_bp.get("/reviews")
def list_reviews():
    q = Review.query.order_by(Review.created_at.desc())
    search = (request.args.get("q") or "").strip()
    if search:
        like = f"%{search}%"
        q = q.filter(db.or_(Review.ticket_key.ilike(like), Review.mr_title.ilike(like),
                            Review.mr_url.ilike(like)))
    return jsonify([r.to_dict() for r in q.limit(200).all()])


@api_bp.post("/reviews")
def post_review():
    data = request.get_json(silent=True) or {}
    mr_url = (data.get("mr_url") or "").strip()
    if not mr_url:
        return _error("Укажите ссылку на merge request")
    try:
        review = create_review(mr_url, data.get("ticket_key"), data.get("reviewer"))
    except GitLabError as exc:
        return _error(str(exc))
    return jsonify(review.to_dict()), 201


@api_bp.post("/reviews/sync")
def sync_reviews():
    """Импорт всех MR проекта. {project?, state?, reviewer?}; по умолчанию GITLAB_PROJECT / GITLAB_MR_STATE."""
    data = request.get_json(silent=True) or {}
    try:
        summary = sync_project(data.get("project"), data.get("state"), data.get("reviewer"))
    except (GitLabError, ReviewError) as exc:
        return _error(str(exc))
    return jsonify(summary)


@api_bp.get("/reviews/<int:review_id>")
def get_review(review_id):
    return jsonify(_get_or_404(Review, review_id).to_dict(full=True))


@api_bp.patch("/reviews/<int:review_id>")
def patch_review(review_id):
    review = _get_or_404(Review, review_id)
    data = request.get_json(silent=True) or {}
    if "verdict" in data:
        if data["verdict"] not in VERDICTS:
            return _error("Некорректный вердикт")
        review.verdict = data["verdict"]
    if "summary" in data:
        review.summary = data["summary"]
    if "reviewer" in data:
        review.reviewer = data["reviewer"]
    db.session.commit()
    return jsonify(review.to_dict())


@api_bp.delete("/reviews/<int:review_id>")
def delete_review(review_id):
    review = _get_or_404(Review, review_id)
    db.session.delete(review)
    db.session.commit()
    return "", 204


@api_bp.post("/reviews/<int:review_id>/rerun")
def rerun_review(review_id):
    review = _get_or_404(Review, review_id)
    data = request.get_json(silent=True) or {}
    if data.get("ticket_key"):
        review.ticket_key = data["ticket_key"].strip().upper()
    run_review(review)
    return jsonify(review.to_dict(full=True))


@api_bp.get("/reviews/<int:review_id>/files/<int:file_id>/content")
def file_content(review_id, file_id):
    f = _get_or_404(ReviewFile, file_id)
    if f.review_id != review_id:
        return _error("Не найдено", 404)
    return jsonify(old=content_lines(f.old_content), new=content_lines(f.new_content))


@api_bp.post("/reviews/<int:review_id>/comments")
def add_comment(review_id):
    review = _get_or_404(Review, review_id)
    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    if not message:
        return _error("Пустой комментарий")
    file_id = data.get("file_id")
    if file_id is not None and not any(f.id == file_id for f in review.files):
        return _error("Файл не относится к ревью")
    severity = data.get("severity") or "info"
    finding = Finding(
        review_id=review.id, file_id=file_id, source="reviewer",
        severity=severity if severity in SEVERITIES else "info",
        line=data.get("line"), side=data.get("side") if data.get("side") in ("new", "old") else "new",
        message=message, suggestion=data.get("suggestion") or "", author=data.get("author"),
    )
    db.session.add(finding)
    db.session.commit()
    return jsonify(finding.to_dict()), 201


@api_bp.patch("/findings/<int:finding_id>")
def patch_finding(finding_id):
    finding = _get_or_404(Finding, finding_id)
    data = request.get_json(silent=True) or {}
    if "status" in data:
        if data["status"] not in FINDING_STATUSES:
            return _error("Некорректный статус")
        finding.status = data["status"]
    if finding.source == "reviewer" and "message" in data and data["message"].strip():
        finding.message = data["message"].strip()
    db.session.commit()
    return jsonify(finding.to_dict())


@api_bp.delete("/findings/<int:finding_id>")
def delete_finding(finding_id):
    finding = _get_or_404(Finding, finding_id)
    if finding.source != "reviewer":
        return _error("Удалять можно только комментарии ревьюера; замечания ИИ/линтера — отклоняйте")
    db.session.delete(finding)
    db.session.commit()
    return "", 204


@api_bp.get("/tickets/<key>")
def get_ticket(key):
    key = key.upper()
    try:
        ticket = sync_ticket(key) if request.args.get("refresh") else Ticket.query.filter_by(key=key).first()
        if ticket is None:
            ticket = sync_ticket(key)
        db.session.commit()
    except TzPortalError as exc:
        return _error(str(exc), 502)
    if ticket is None:
        return _error("Тикет не найден", 404)
    return jsonify(ticket.to_dict())
