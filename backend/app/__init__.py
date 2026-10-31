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

    @app.errorhandler(404)
    def not_found(_):
        return jsonify(error="Не найдено"), 404

    return app
