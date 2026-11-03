# Переход с заглушек на реальные интеграции

Сейчас у платформы три внешние зависимости, и каждая по умолчанию заменена заглушкой:

| Интеграция | Заглушка | Настоящий клиент | Что переключает |
|---|---|---|---|
| GitLab | `FixtureGitLabClient` | `GitLabClient` | `GITLAB_MOCK=false` |
| Портал ТЗ | `StubTzPortalClient` | `HttpTzPortalClient` | `TZ_PORTAL_MODE=http` |
| Модель | `StubLLMClient` | `OpenAICompatibleClient` | `LLM_MODE=openai` |

**Менять код для переключения не нужно:** достаточно задать переменные в `backend/.env` и перезапустить backend.
Интеграции независимы, поэтому подключайте их по одной: сначала GitLab, потом портал ТЗ, потом модель.

Выбор клиента находится в функциях `get_gitlab_client()`, `get_tz_portal_client()` и `get_llm_client()`.

## Готовый `backend/.env`

Файл не попадает в git (указан в `.gitignore`), поэтому токены храните только в нём. Файла `.env.example` в репозитории
нет, хотя README на него ссылается: создайте `backend/.env` вручную.

```dotenv
# --- GitLab
GITLAB_MOCK=false
GITLAB_URL=https://gitlab.bank.local
GITLAB_TOKEN=glpat-xxxxxxxxxxxxxxxxxxxx
GITLAB_VERIFY_SSL=true
GITLAB_PROJECT=group/subgroup/project
GITLAB_MR_STATE=opened
GITLAB_DEV_BRANCH=develop_dev
GITLAB_TST_BRANCH=develop_tst
GITLAB_MAX_BRANCH_COMMITS=5000

# --- Портал ТЗ
TZ_PORTAL_MODE=http
TZ_PORTAL_URL=https://tz-portal.bank.local
TZ_PORTAL_TOKEN=xxxxxxxxxxxxxxxx

# --- Модель
LLM_MODE=openai
LLM_API_URL=http://qwen.bank.local:8000/v1/chat/completions
LLM_MODEL=qwen
LLM_API_KEY=
LLM_TIMEOUT=180
LLM_MAX_INPUT_TOKENS=6000
```

## 1. GitLab

Код: `backend/app/services/gitlab_client.py`. Настоящий клиент уже написан, дописывать его не нужно.

1. Создайте токен: GitLab → **Edit profile → Access tokens** (или **Settings → Access tokens** в проекте). Достаточно роли
   Reporter и scope `read_api`. Платформа только читает данные, запись в GitLab не нужна.
2. Пропишите токен в `GITLAB_TOKEN`, он передаётся в заголовке `PRIVATE-TOKEN`.
3. Задайте `GITLAB_MOCK=false`, `GITLAB_URL` и `GITLAB_PROJECT`.
4. Если сертификат выпущен внутренним УЦ, укажите в `GITLAB_VERIFY_SSL` путь к CA-бандлу. Значение `false` используйте
   только для временной проверки.

Проверьте токен до запуска платформы:

```bash
curl -H "PRIVATE-TOKEN: $GITLAB_TOKEN" \
  "https://gitlab.bank.local/api/v4/projects/group%2Fsubgroup%2Fproject/merge_requests?per_page=1"
```

| Ответ | Что значит |
|---|---|
| JSON-массив | всё настроено |
| `401` | неверный или просроченный токен |
| `403` | у токена нет scope `read_api` |
| `404` | неверный путь проекта или нет доступа к проекту |

Какие запросы делает платформа:

| Зачем | Запрос |
|---|---|
| MR | `GET /projects/:id/merge_requests/:iid` |
| Список MR | `GET /projects/:id/merge_requests` |
| Файлы MR | `GET /projects/:id/merge_requests/:iid/diffs`, для старых версий — `/changes` |
| Содержимое файла | `GET /projects/:id/repository/files/:path/raw?ref=...` |
| Коммиты веток для сверки | `GET /projects/:id/repository/commits?ref_name=...` |
| Правки коммита для сверки | `GET /projects/:id/repository/commits/:sha/diff` |

## 2. Портал ТЗ

Код клиента: `backend/app/services/tz_portal.py`. Клиент `HttpTzPortalClient` уже делает запрос; комментарий `TODO` в нём
означает лишь, что контракт нужно сверить с настоящим порталом.

### Как платформа обращается к порталу

Один запрос на каждый анализ MR:

```http
GET {TZ_PORTAL_URL}/api/tickets/RCK2-3435
Authorization: Bearer {TZ_PORTAL_TOKEN}
```

Заголовок отправляется, только если задан `TZ_PORTAL_TOKEN`. Таймаут 30 секунд.

### Что должен отвечать портал

**`200 OK`, тикет найден:**

```json
{
  "key": "RCK2-3435",
  "title": "Минимальная ставка вклада",
  "description": "Полный текст ТЗ",
  "developer": "Сидоров А.В.",
  "analyst": "Кузнецова Е.М.",
  "portal_url": "https://tz-portal.bank.local/tickets/RCK2-3435",
  "objects": [
    {
      "system_name": "DEPOSIT\\CALC_PERCENT.plp",
      "display_name": "Расчёт процентов",
      "change_description": "Учитывать MIN_RATE"
    }
  ]
}
```

| Поле | Обязательно | Как используется |
|---|---|---|
| `title`, `description` | желательно | заголовок и текст ТЗ; описание также уходит в модель |
| `developer`, `analyst` | нет | показываются на вкладке «Обзор» |
| `portal_url` | нет | ссылка «Открыть на портале» |
| `objects` | желательно | список файлов для сверки с MR |
| `objects[].system_name` | **да** | хвост пути файла в репозитории |
| `objects[].display_name`, `change_description` | нет | показываются в таблице; описание также уходит в модель |

**Важно про `system_name`.** Сравниваются последние компоненты пути, без учёта регистра, `\` и `/` равнозначны.
`DEPOSIT\CALC_PERCENT.plp` совпадёт с `src/DEPOSIT/CALC_PERCENT.plp`, но не с `src/OTHER/CALC_PERCENT.plp`. В JSON обратный
слэш записывается как `\\`.

**Важно про пустой `objects`.** Если список пустой, все файлы MR будут показаны как «нет в ТЗ».

**Остальные ответы:**

| Код | Когда | Что будет в платформе |
|---|---|---|
| `404` | тикета нет | ревью завершится, на вкладке «Обзор» предупреждение «Тикет не найден» |
| `401`, `403`, `5xx` | ошибка доступа или сервера | **анализ MR завершится с ошибкой**, причина показывается в ревью |

Ответ `200` обязан содержать JSON. На другой ответ платформа покажет «Внутренняя ошибка».

### Пример API портала на Python и Flask

Замените `find_ticket()` на обращение к базе портала.

```python
# tz_portal_api.py
import hmac
import os

from flask import Flask, abort, jsonify, request

app = Flask(__name__)
app.json.ensure_ascii = False

API_TOKEN = os.environ.get("TZ_PORTAL_TOKEN", "dev-token")
PUBLIC_URL = os.environ.get("TZ_PORTAL_PUBLIC_URL", "https://tz-portal.bank.local")

TICKETS = {
    "RCK2-3435": {
        "title": "Минимальная ставка вклада",
        "description": "Проценты по вкладу считать не ниже минимальной ставки MIN_RATE.",
        "developer": "Сидоров А.В.",
        "analyst": "Кузнецова Е.М.",
        "objects": [
            {
                "system_name": "DEPOSIT\\CALC_PERCENT.plp",
                "display_name": "Расчёт процентов",
                "change_description": "Учитывать MIN_RATE",
            },
        ],
    },
}


def find_ticket(key):
    """Замените на запрос к базе портала."""
    return TICKETS.get(key)


@app.before_request
def check_token():
    expected = f"Bearer {API_TOKEN}"
    if not hmac.compare_digest(request.headers.get("Authorization", ""), expected):
        return jsonify(error="Нет доступа"), 401


@app.errorhandler(404)
def not_found(_):
    return jsonify(error="Тикет не найден"), 404


@app.get("/api/tickets/<key>")
def get_ticket(key):
    key = key.upper()
    ticket = find_ticket(key)
    if ticket is None:
        abort(404)
    return jsonify(key=key, portal_url=f"{PUBLIC_URL}/tickets/{key}", **ticket)


if __name__ == "__main__":
    app.run(port=5100)
```

Запуск и проверка:

```bash
pip install flask
python tz_portal_api.py
curl -H "Authorization: Bearer dev-token" http://localhost:5100/api/tickets/RCK2-3435
```

После этого в `backend/.env`:

```dotenv
TZ_PORTAL_MODE=http
TZ_PORTAL_URL=http://localhost:5100
TZ_PORTAL_TOKEN=dev-token
```

Если backend запущен в Docker, а портал на вашей машине, вместо `localhost` укажите `host.docker.internal`.

### Если настоящий API портала выглядит иначе

Менять нужно только `HttpTzPortalClient.get_ticket()`: метод должен вернуть словарь описанного формата или `None`, если
тикета нет. Пример для другого адреса, авторизации и названий полей:

```python
class HttpTzPortalClient:
    def __init__(self, base_url, token=""):
        self.base_url = base_url
        self.session = requests.Session()
        self.session.headers["X-Api-Key"] = token

    def get_ticket(self, key):
        try:
            resp = self.session.get(f"{self.base_url}/rest/tasks", params={"number": key}, timeout=30)
        except requests.RequestException as exc:
            raise TzPortalError(f"Портал ТЗ недоступен: {exc}") from exc
        if resp.status_code == 404:
            return None
        if not resp.ok:
            raise TzPortalError(f"Портал ТЗ вернул {resp.status_code}")
        try:
            task = resp.json()
        except ValueError as exc:
            raise TzPortalError("Портал ТЗ вернул не JSON") from exc
        return {
            "key": key,
            "title": task["name"],
            "description": task["specification"],
            "developer": task.get("assignee"),
            "analyst": task.get("author"),
            "portal_url": task.get("url"),
            "objects": [
                {
                    "system_name": obj["path"],
                    "display_name": obj.get("name"),
                    "change_description": obj.get("changes"),
                }
                for obj in task.get("objects", [])
            ],
        }
```

## 3. Модель (ИИ)

Код: `backend/app/services/llm_client.py`, промпт: `backend/app/services/prompts.py`. Сборка запросов и разбор ответов уже
написаны.

### Вариант А: OpenAI-совместимый API

Так Qwen обычно отдают vLLM, TGI и Ollama. Менять код не нужно:

```dotenv
LLM_MODE=openai
LLM_API_URL=http://qwen.bank.local:8000/v1/chat/completions
LLM_MODEL=qwen
LLM_API_KEY=
```

**`LLM_API_URL` указывается полностью, вместе с `/v1/chat/completions`:** платформа ничего к нему не добавляет.

Что отправляет платформа:

```http
POST {LLM_API_URL}
Content-Type: application/json
Authorization: Bearer {LLM_API_KEY}

{
  "model": "qwen",
  "messages": [
    {"role": "system", "content": "Ты — опытный ревьюер кода на PL/PLUS..."},
    {"role": "user", "content": "Задача: RCK2-3435 — ...\nТЗ (кратко): ...\n\n### Файл: src/DEPOSIT/CALC_PERCENT.plp (...)\n..."}
  ],
  "temperature": 0.1
}
```

Заголовок `Authorization` отправляется, только если задан `LLM_API_KEY`.

Что должна вернуть модель:

```json
{
  "choices": [
    {
      "message": {
        "role": "assistant",
        "content": "[{\"file\": \"src/DEPOSIT/CALC_PERCENT.plp\", \"line\": 6, \"severity\": \"major\", \"message\": \"Суть замечания\", \"suggestion\": \"Как исправить\"}]"
      }
    }
  ]
}
```

Проверка:

```bash
curl http://qwen.bank.local:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen","messages":[{"role":"user","content":"Ответь: []"}],"temperature":0.1}'
```

### Вариант Б: свой формат API

Напишите класс с методом `complete(system, user)` и верните его из `get_llm_client()`. Метод получает промпт и должен вернуть
текст ответа модели:

```python
class QwenCustomClient:
    def __init__(self, url, api_key, timeout=180):
        self.url = url
        self.api_key = api_key
        self.timeout = timeout

    def complete(self, system, user):
        try:
            resp = requests.post(
                self.url,
                json={"instruction": system, "input": user},
                headers={"X-Api-Key": self.api_key},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise LLMError(f"Модель недоступна: {exc}") from exc
        if not resp.ok:
            raise LLMError(f"Модель вернула {resp.status_code}: {resp.text[:300]}")
        return resp.json()["output"]


def get_llm_client(config):
    if config.get("LLM_MODE") == "custom":
        return QwenCustomClient(config["LLM_API_URL"], config.get("LLM_API_KEY", ""), config["LLM_TIMEOUT"])
    if config.get("LLM_MODE") == "openai":
        return OpenAICompatibleClient(
            config["LLM_API_URL"], config["LLM_MODEL"], config.get("LLM_API_KEY", ""), config["LLM_TIMEOUT"]
        )
    return StubLLMClient(demo=bool(config.get("GITLAB_MOCK")))
```

Затем задайте `LLM_MODE=custom`.

### Формат ответа модели

Текст ответа должен быть JSON-массивом:

```json
[
  {
    "file": "src/DEPOSIT/CALC_PERCENT.plp",
    "line": 6,
    "severity": "major",
    "message": "Суть замечания",
    "suggestion": "Как исправить"
  }
]
```

- `severity`: `info`, `minor`, `major` или `critical`; другое значение заменяется на `info`.
- `line` и `suggestion` могут отсутствовать. Замечание с `line`, которой нет в файле, прикрепляется к файлу без номера строки.
- Обёртка ` ```json `, блок `<think>...</think>` и объект `{"comments": [...]}` разбираются автоматически.
- Если JSON найти не удалось, весь текст становится одним общим замечанием к MR.

### Что подстроить под вашу модель

- `SYSTEM_PROMPT` и `build_header()` в `prompts.py`: приведите к формату, на котором дообучалась модель.
- `LLM_MAX_INPUT_TOKENS`: установите ниже контекстного окна модели с запасом на ответ. Если правки не помещаются, они делятся
  на несколько запросов.
- `LLM_TIMEOUT`: анализ синхронный, долгие ответы задерживают ревью. В Docker gunicorn ограничивает запрос 600 секундами.
- Если модель недоступна, ревью всё равно завершится: ошибка показывается в блоке «Итоги проверки», остальные проверки работают.

## 4. Как убрать тестовые данные

### Шаг 1. Отключите заглушки

Переменных из раздела «Готовый `backend/.env`» достаточно. При `GITLAB_MOCK=false` команда `seed-demo` больше ничего не загружает.

### Шаг 2. Очистите базу от демо-записей

Демо-ревью и примеры правил сами из базы не удалятся. Выберите подходящий способ:

- **В базе только демо-данные:** выполните `docker compose down -v`, затем `docker compose up --build`. **Эта команда удалит все
  данные PostgreSQL.**
- **В базе есть и нужные данные:** удалите демо-ревью кнопкой «Удалить ревью», а правила `USR` — на вкладке «Линтеры». Демо-тикеты
  останутся в таблице `tickets`, но ни на что не влияют.

### Шаг 3. Удалите код заглушек, если нужно

Этот шаг необязателен. **Тесты работают на заглушках (`TestConfig` включает `GITLAB_MOCK`), поэтому рекомендуется оставить их:**
в рабочей системе заглушки не используются. Если всё же решите удалять, сначала перепишите тесты в `backend/tests/` на
подставные клиенты, затем:

| Что удалить | Где |
|---|---|
| Класс `FixtureGitLabClient` и ветка `GITLAB_MOCK` в `get_gitlab_client()` | `app/services/gitlab_client.py` |
| Класс `StubTzPortalClient`, в `get_tz_portal_client()` оставьте только `HttpTzPortalClient` | `app/services/tz_portal.py` |
| Класс `StubLLMClient`, в `get_llm_client()` оставьте настоящий клиент | `app/services/llm_client.py` |
| Функция `seed_demo_data()` | `app/services/review_service.py` |
| Команда `seed-demo` | `app/__init__.py` |
| `flask seed-demo &&` в команде запуска | `backend/Dockerfile` |
| `demo_mr.json`, `demo_scenarios.json`, `tz_stub.json` | `app/fixtures/` |
| Значение `GITLAB_MOCK` по умолчанию и `"demo/ibso"` | `app/config.py` |

## 5. Проверка после подключения

1. Откройте http://localhost:8080. В шапке должно быть `GitLab: API`, `ТЗ: API` и название режима модели. Оранжевая метка значит,
   что эта интеграция всё ещё на заглушке.
2. Вставьте ссылку на настоящий MR в `develop_tst` с несколькими коммитами тикета в `develop_dev`.
3. На вкладке «Обзор» проверьте: тикет определился, файлы сопоставлены с ТЗ, в панели `develop_dev → develop_tst` есть коммиты,
   в «Итогах проверки» нет ошибок модели.

| Симптом | Где искать причину |
|---|---|
| `Не задан GITLAB_URL` | `GITLAB_URL` в `backend/.env` |
| `GitLab: нет доступа` | токен и scope `read_api` |
| Ошибка SSL при обращении к GitLab | `GITLAB_VERIFY_SSL` |
| Ошибка SSL при обращении к порталу или модели | у них нет отдельной настройки: задайте `REQUESTS_CA_BUNDLE` с путём к CA-бандлу |
| `Портал ТЗ вернул 401` | `TZ_PORTAL_TOKEN` и проверка токена на стороне портала |
| `Тикет ... не найден на портале ТЗ` | номер в названии MR и ответ портала по этому номеру |
| Все файлы «нет в ТЗ» | формат `system_name` и пустой `objects` |
| `Не задан LLM_API_URL` | `LLM_API_URL` в `backend/.env` |
| `Модель вернула 404` | в `LLM_API_URL` нет `/v1/chat/completions` |
| Замечание ИИ одно и содержит весь ответ текстом | модель вернула не JSON: поправьте `SYSTEM_PROMPT` |
| В панели сверки «нет коммитов» | номер тикета в сообщениях коммитов, `GITLAB_DEV_BRANCH` |
