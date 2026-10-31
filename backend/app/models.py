from datetime import datetime, timezone

from sqlalchemy.dialects.postgresql import JSONB

from .extensions import db

JSONType = db.JSON().with_variant(JSONB(), "postgresql")


def utcnow():
    return datetime.now(timezone.utc)


def iso(dt):
    return dt.isoformat() if dt else None


class Ticket(db.Model):
    """Задача с портала ТЗ (например RCK2-3232)."""

    __tablename__ = "tickets"

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(64), unique=True, nullable=False, index=True)
    title = db.Column(db.String(500))
    description = db.Column(db.Text)  # текст ТЗ
    developer = db.Column(db.String(200))
    analyst = db.Column(db.String(200))
    portal_url = db.Column(db.String(1000))
    fetched_at = db.Column(db.DateTime(timezone=True), default=utcnow)

    objects = db.relationship(
        "TzObject", backref="ticket", cascade="all, delete-orphan", order_by="TzObject.id"
    )

    def to_dict(self, with_objects=True):
        data = {
            "id": self.id,
            "key": self.key,
            "title": self.title,
            "description": self.description,
            "developer": self.developer,
            "analyst": self.analyst,
            "portal_url": self.portal_url,
            "fetched_at": iso(self.fetched_at),
        }
        if with_objects:
            data["objects"] = [o.to_dict() for o in self.objects]
        return data


class TzObject(db.Model):
    """Объект, который по ТЗ правится в рамках задачи (файл в репозитории, напр. ТБП\\операция.plp)."""

    __tablename__ = "tz_objects"

    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False)
    system_name = db.Column(db.String(500), nullable=False)
    display_name = db.Column(db.String(500))
    change_description = db.Column(db.Text)

    def to_dict(self):
        return {
            "id": self.id,
            "system_name": self.system_name,
            "display_name": self.display_name,
            "change_description": self.change_description,
        }


class Review(db.Model):
    __tablename__ = "reviews"

    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey("tickets.id", ondelete="SET NULL"))
    ticket_key = db.Column(db.String(64), index=True)

    mr_url = db.Column(db.String(1000), nullable=False)
    gitlab_project = db.Column(db.String(500), nullable=False)
    mr_iid = db.Column(db.Integer, nullable=False)
    mr_title = db.Column(db.String(1000))
    mr_description = db.Column(db.Text)
    mr_author = db.Column(db.String(200))
    source_branch = db.Column(db.String(500))
    target_branch = db.Column(db.String(500))
    base_sha = db.Column(db.String(64))
    head_sha = db.Column(db.String(64))

    # pending | running | done | failed
    status = db.Column(db.String(20), nullable=False, default="pending")
    error = db.Column(db.Text)
    tz_check = db.Column(JSONType)  # результат сверки объектов ТЗ и файлов MR
    llm_stats = db.Column(JSONType)  # статистика отправки в модель (токены, фрагменты)

    # pending | approved | changes_requested
    verdict = db.Column(db.String(30), nullable=False, default="pending")
    summary = db.Column(db.Text)
    reviewer = db.Column(db.String(200))

    created_at = db.Column(db.DateTime(timezone=True), default=utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    ticket = db.relationship("Ticket")
    files = db.relationship(
        "ReviewFile", backref="review", cascade="all, delete-orphan", order_by="ReviewFile.id"
    )
    findings = db.relationship(
        "Finding", backref="review", cascade="all, delete-orphan", order_by="Finding.id"
    )

    def counts(self):
        result = {"lint": 0, "llm": 0, "reviewer": 0, "open": 0}
        for f in self.findings:
            result[f.source] = result.get(f.source, 0) + 1
            if f.status == "open" and f.source != "reviewer":
                result["open"] += 1
        return result

    def to_dict(self, full=False):
        data = {
            "id": self.id,
            "ticket_key": self.ticket_key,
            "mr_url": self.mr_url,
            "gitlab_project": self.gitlab_project,
            "mr_iid": self.mr_iid,
            "mr_title": self.mr_title,
            "mr_author": self.mr_author,
            "source_branch": self.source_branch,
            "target_branch": self.target_branch,
            "head_sha": self.head_sha,
            "status": self.status,
            "error": self.error,
            "tz_check": self.tz_check,
            "llm_stats": self.llm_stats,
            "verdict": self.verdict,
            "summary": self.summary,
            "reviewer": self.reviewer,
            "created_at": iso(self.created_at),
            "updated_at": iso(self.updated_at),
            "counts": self.counts(),
            "files_count": len(self.files),
        }
        if full:
            data["mr_description"] = self.mr_description
            data["ticket"] = self.ticket.to_dict() if self.ticket else None
            data["files"] = [f.to_dict() for f in self.files]
            data["findings"] = [f.to_dict() for f in self.findings]
        return data


class ReviewFile(db.Model):
    __tablename__ = "review_files"

    id = db.Column(db.Integer, primary_key=True)
    review_id = db.Column(db.Integer, db.ForeignKey("reviews.id", ondelete="CASCADE"), nullable=False)
    old_path = db.Column(db.String(1000))
    new_path = db.Column(db.String(1000))
    # added | modified | deleted | renamed
    change_type = db.Column(db.String(20), nullable=False)
    diff = db.Column(db.Text)
    hunks = db.Column(JSONType)
    old_content = db.Column(db.Text)
    new_content = db.Column(db.Text)
    additions = db.Column(db.Integer, default=0)
    deletions = db.Column(db.Integer, default=0)
    # matched | extra | ignored — статус относительно ТЗ
    tz_status = db.Column(db.String(20))
    tz_object_id = db.Column(db.Integer, db.ForeignKey("tz_objects.id", ondelete="SET NULL"))
    is_code = db.Column(db.Boolean, default=False)

    @property
    def path(self):
        return self.new_path or self.old_path

    def to_dict(self):
        return {
            "id": self.id,
            "old_path": self.old_path,
            "new_path": self.new_path,
            "path": self.path,
            "change_type": self.change_type,
            "hunks": self.hunks or [],
            "additions": self.additions,
            "deletions": self.deletions,
            "tz_status": self.tz_status,
            "tz_object_id": self.tz_object_id,
            "is_code": self.is_code,
            "has_content": bool(self.old_content or self.new_content),
            "new_lines_total": len(self.new_content.splitlines()) if self.new_content else 0,
            "old_lines_total": len(self.old_content.splitlines()) if self.old_content else 0,
        }


class Finding(db.Model):
    """Замечание: от линтера (lint), модели (llm) или ревьюера (reviewer)."""

    __tablename__ = "findings"

    id = db.Column(db.Integer, primary_key=True)
    review_id = db.Column(db.Integer, db.ForeignKey("reviews.id", ondelete="CASCADE"), nullable=False)
    file_id = db.Column(db.Integer, db.ForeignKey("review_files.id", ondelete="CASCADE"))
    source = db.Column(db.String(20), nullable=False)  # lint | llm | reviewer
    rule = db.Column(db.String(50))
    severity = db.Column(db.String(20), default="info")  # info | minor | major | critical
    line = db.Column(db.Integer)  # номер строки (None — замечание к файлу / MR целиком)
    side = db.Column(db.String(10), default="new")  # new | old
    message = db.Column(db.Text, nullable=False)
    suggestion = db.Column(db.Text)
    # open | accepted | dismissed
    status = db.Column(db.String(20), nullable=False, default="open")
    author = db.Column(db.String(200))
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "file_id": self.file_id,
            "source": self.source,
            "rule": self.rule,
            "severity": self.severity,
            "line": self.line,
            "side": self.side,
            "message": self.message,
            "suggestion": self.suggestion,
            "status": self.status,
            "author": self.author,
            "created_at": iso(self.created_at),
        }
