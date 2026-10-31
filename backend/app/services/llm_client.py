"""Клиент модели (дообученный Qwen).

LLM_MODE=stub   — заглушка: реальных вызовов нет, возвращает пустой список замечаний
                  (или демо-замечания при GITLAB_MOCK=true, чтобы было видно, как они отображаются).
LLM_MODE=openai — OpenAI-совместимый /v1/chat/completions (так Qwen обычно отдают vLLM / TGI / Ollama).

Если у вас свой роут — реализуйте класс с методом complete(system, user) -> str
и подключите его в get_llm_client().
"""
import json
import re

import requests


class LLMError(Exception):
    pass


class StubLLMClient:
    def __init__(self, demo=False):
        self.demo = demo

    def complete(self, system, user):
        if not self.demo:
            return "[]"
        # Демо-ответ: замечание к первой изменённой строке каждого файла.
        comments = []
        current_file = None
        for line in user.splitlines():
            m = re.match(r"^### Файл: (.+?) \(", line)
            if m:
                current_file = m.group(1)
                continue
            m = re.match(r"^\s*(\d+)\+ ", line)
            if m and current_file:
                comments.append({
                    "file": current_file,
                    "line": int(m.group(1)),
                    "severity": "minor",
                    "message": "[демо-заглушка ИИ] Здесь будет замечание модели к изменённой строке.",
                    "suggestion": "Подключите модель: LLM_MODE=openai или свой клиент в app/services/llm_client.py",
                })
                current_file = None
        return json.dumps(comments, ensure_ascii=False)


class OpenAICompatibleClient:
    def __init__(self, url, model, api_key="", timeout=180):
        if not url:
            raise LLMError("Не задан LLM_API_URL")
        self.url = url
        self.model = model
        self.timeout = timeout
        self.headers = {"Content-Type": "application/json"}
        if api_key:
            self.headers["Authorization"] = f"Bearer {api_key}"

    def complete(self, system, user):
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.1,
        }
        try:
            resp = requests.post(self.url, json=payload, headers=self.headers, timeout=self.timeout)
        except requests.RequestException as exc:
            raise LLMError(f"Модель недоступна: {exc}") from exc
        if not resp.ok:
            raise LLMError(f"Модель вернула {resp.status_code}: {resp.text[:300]}")
        try:
            return resp.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, ValueError) as exc:
            raise LLMError(f"Неожиданный ответ модели: {resp.text[:300]}") from exc


SEVERITIES = {"info", "minor", "major", "critical"}


def parse_llm_response(text):
    """Достаёт из ответа JSON-массив замечаний. Если JSON нет — возвращает одно общее замечание."""
    if text is None:
        return []
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()  # reasoning-модели Qwen
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned.strip())
    data = None
    try:
        data = json.loads(cleaned)
    except ValueError:
        start, end = cleaned.find("["), cleaned.rfind("]")
        if start != -1 and end > start:
            try:
                data = json.loads(cleaned[start:end + 1])
            except ValueError:
                data = None
    if isinstance(data, dict):
        data = data.get("comments") or data.get("findings") or []
    if not isinstance(data, list):
        return [{"file": None, "line": None, "severity": "info", "message": cleaned, "suggestion": ""}] if cleaned else []
    result = []
    for item in data:
        if not isinstance(item, dict) or not item.get("message"):
            continue
        line = item.get("line")
        try:
            line = int(line) if line is not None else None
        except (TypeError, ValueError):
            line = None
        severity = str(item.get("severity") or "info").lower()
        result.append({
            "file": item.get("file"),
            "line": line,
            "severity": severity if severity in SEVERITIES else "info",
            "message": str(item["message"]),
            "suggestion": str(item.get("suggestion") or ""),
        })
    return result


def get_llm_client(config):
    if config.get("LLM_MODE") == "openai":
        return OpenAICompatibleClient(
            config["LLM_API_URL"], config["LLM_MODEL"], config.get("LLM_API_KEY", ""), config["LLM_TIMEOUT"]
        )
    return StubLLMClient(demo=bool(config.get("GITLAB_MOCK")))
