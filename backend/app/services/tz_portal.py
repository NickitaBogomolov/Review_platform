"""Интеграция с порталом написания ТЗ.

Пока API портала нет, используется заглушка (TZ_PORTAL_MODE=stub), читающая
app/fixtures/tz_stub.json. Когда появится API — реализуйте HttpTzPortalClient.get_ticket()
так, чтобы он возвращал словарь того же формата, что и заглушка:

{
  "key": "RCK2-3232",
  "title": "...",
  "description": "Текст ТЗ",
  "developer": "Иванов И.И.",
  "analyst": "Петров П.П.",
  "portal_url": "https://tz-portal/.../RCK2-3232",
  "objects": [
    {"system_name": "AC_FIN\\\\RECALC_COMM.plp",
     "display_name": "Пересчёт комиссии",
     "change_description": "Что меняется по ТЗ"}
  ]
}
"""
import json
import os

import requests


class TzPortalError(Exception):
    pass


class StubTzPortalClient:
    def __init__(self, path=None):
        self.path = path or os.path.join(os.path.dirname(__file__), "..", "fixtures", "tz_stub.json")

    def get_ticket(self, key):
        with open(self.path, encoding="utf-8") as fh:
            data = json.load(fh)
        ticket = data.get(key.upper())
        if ticket is None:
            return None
        return {"key": key.upper(), **ticket}


class HttpTzPortalClient:
    """TODO: реализовать, когда у портала ТЗ появится API."""

    def __init__(self, base_url, token=""):
        self.base_url = base_url
        self.session = requests.Session()
        if token:
            self.session.headers["Authorization"] = f"Bearer {token}"

    def get_ticket(self, key):
        # Пример предполагаемого контракта — поправьте под реальный API портала.
        try:
            resp = self.session.get(f"{self.base_url}/api/tickets/{key}", timeout=30)
        except requests.RequestException as exc:
            raise TzPortalError(f"Портал ТЗ недоступен: {exc}") from exc
        if resp.status_code == 404:
            return None
        if not resp.ok:
            raise TzPortalError(f"Портал ТЗ вернул {resp.status_code}")
        return resp.json()


def get_tz_portal_client(config):
    if config.get("TZ_PORTAL_MODE") == "http":
        return HttpTzPortalClient(config["TZ_PORTAL_URL"], config.get("TZ_PORTAL_TOKEN", ""))
    return StubTzPortalClient()
