import click
from flask import Flask, jsonify

from .config import Config
from .extensions import db, migrate



def create_app(config_object=Config):
    app = Flask(__name__)
    app.config.from_object(config_object)
    app.json.ensure_ascii = False

    db.init_app(app)
    migrate.init_app(app, db)

    from . import models  # noqa: F401  (регистрация моделей для миграций)
    from .api import api_bp

    app.register_blueprint(api_bp, url_prefix="/api")

    @app.cli.command("sync-mrs")
    @click.option("--project", default=None, help="group/project (по умолчанию GITLAB_PROJECT)")
    @click.option("--state", default=None, help="opened / merged / closed / all (по умолчанию GITLAB_MR_STATE)")
    def sync_mrs(project, state):
        """Импортировать все MR проекта GitLab и проанализировать новые/обновлённые."""
        from .services.review_service import sync_project

        summary = sync_project(project, state)
        click.echo(
            "{project} [{state}]: всего {total}, новых {created}, обновлено {updated}, "
            "без изменений {skipped}, с ошибкой {failed}".format(**summary)
        )

    @app.cli.command("seed-demo")
    def seed_demo():
        """В демо-режиме (GITLAB_MOCK) загрузить заготовленный MR, если в базе нет ни одного готового ревью."""
        from .models import Review
        from .services.review_service import sync_project

        if not app.config["GITLAB_MOCK"]:
            click.echo("GITLAB_MOCK выключен — демо-данные не загружаются")
            return
        if Review.query.filter_by(status="done").first() is not None:
            click.echo("В базе уже есть готовые ревью — демо-данные не загружаются")
            return
        summary = sync_project()
        click.echo("Загружен демо-пример: {project}, MR: {total}".format(**summary))

    @app.errorhandler(404)
    def not_found(_):
        return jsonify(error="Не найдено"), 404

    return app
