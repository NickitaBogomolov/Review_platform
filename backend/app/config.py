from dotenv import load_dotenv

load_dotenv()

import os


def _bool(value, default=False):
    if value is None or value == "":
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _list(value, default=""):
    raw = value if value is not None else default
    return [item.strip() for item in raw.split(",") if item.strip()]


def _verify(value):
    """GITLAB_VERIFY_SSL: true/false или путь к CA-бандлу."""
    if value is None or value == "":
        return True
    low = value.strip().lower()
    if low in ("1", "true", "yes", "on"):
        return True
    if low in ("0", "false", "no", "off"):
        return False
    return value


class Config:
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL", "postgresql+psycopg://review:review@localhost:5432/review"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    JSON_AS_ASCII = False

    GITLAB_URL = os.getenv("GITLAB_URL", "").rstrip("/")
    GITLAB_TOKEN = os.getenv("GITLAB_TOKEN", "")
    GITLAB_VERIFY_SSL = _verify(os.getenv("GITLAB_VERIFY_SSL"))
    # по умолчанию демо-режим: вместо GitLab — заготовленный MR из app/fixtures/demo_mr.json
    GITLAB_MOCK = _bool(os.getenv("GITLAB_MOCK"), default=True)
    GITLAB_TIMEOUT = int(os.getenv("GITLAB_TIMEOUT", "30"))
    # проект, из которого импортируются все MR (group/subgroup/project)
    GITLAB_PROJECT = (os.getenv("GITLAB_PROJECT", "").strip().strip("/")
                      or ("demo/ibso" if GITLAB_MOCK else ""))
    # какие MR импортировать: opened / merged / closed / all
    GITLAB_MR_STATE = os.getenv("GITLAB_MR_STATE", "all").strip().lower()

    TZ_PORTAL_MODE = os.getenv("TZ_PORTAL_MODE", "stub")
    TZ_PORTAL_URL = os.getenv("TZ_PORTAL_URL", "").rstrip("/")
    TZ_PORTAL_TOKEN = os.getenv("TZ_PORTAL_TOKEN", "")

    LLM_MODE = os.getenv("LLM_MODE", "stub")
    LLM_API_URL = os.getenv("LLM_API_URL", "")
    LLM_API_KEY = os.getenv("LLM_API_KEY", "")
    LLM_MODEL = os.getenv("LLM_MODEL", "qwen")
    LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "180"))
    LLM_MAX_INPUT_TOKENS = int(os.getenv("LLM_MAX_INPUT_TOKENS", "6000"))
    LLM_CONTEXT_LINES = int(os.getenv("LLM_CONTEXT_LINES", "2"))
    LLM_MAX_TZ_CHARS = int(os.getenv("LLM_MAX_TZ_CHARS", "1500"))

    TICKET_REGEX = os.getenv("TICKET_REGEX", r"[A-Z][A-Z0-9]+-\d+")

    CODE_EXTENSIONS = [e.lower() for e in _list(os.getenv("CODE_EXTENSIONS"), ".plp")]
    TZ_IGNORE_PATTERNS = _list(os.getenv("TZ_IGNORE_PATTERNS"), "*.md,.gitlab-ci.yml,.gitignore")
    LINT_DISABLED_RULES = [r.upper() for r in _list(os.getenv("LINT_DISABLED_RULES"), "")]
    LINT_MAX_LINE_LENGTH = int(os.getenv("LINT_MAX_LINE_LENGTH", "150"))


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    GITLAB_MOCK = True
    GITLAB_PROJECT = "bank/ibso"
    GITLAB_MR_STATE = "all"
    TZ_PORTAL_MODE = "stub"
    LLM_MODE = "stub"
