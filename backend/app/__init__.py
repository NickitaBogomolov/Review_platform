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

    @app.errorhandler(404)
    def not_found(_):
        return jsonify(error="Не найдено"), 404

    return app
