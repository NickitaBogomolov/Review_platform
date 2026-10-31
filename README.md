# Review Platform — платформа для code review (PL/PLUS, ЦФТ)

Портал помогает проводить ревью merge request'ов из self-hosted GitLab:

* **Просмотр изменений как в GitLab**: дифф inline и side-by-side, подсветка PL/PLUS, внутристрочные
  изменения, раскрытие скрытого контекста, дерево файлов, отметка «Просмотрено».
* **Сверка с ТЗ**: объекты задачи с портала ТЗ сравниваются с файлами MR. Ошибкой считаются оба случая:
  объект есть в ТЗ, но не изменён в MR, и файл изменён в MR, но его нет в ТЗ.
* **Линтер PL/PLUS**: правила для типовых ошибок в операциях ТБП. Замечания показываются только на строках,
  которые добавил этот MR.
* **Подсказки ИИ**: значимые изменения отправляются дообученной модели (Qwen), а её замечания
  прикрепляются к строкам диффа.
* **Работа ревьюера**: принять или отклонить замечание, оставить свой комментарий к строке или файлу,
  вынести вердикт и написать заключение.

```
           ┌──────────┐   API: ТЗ + значимые изменения   ┌────────────┐
           │  Qwen    │◀────────────────────────────────▶│            │◀── API: изменения MR ── GitLab
           └──────────┘        ответ: замечания          │  backend   │
                                                         │  (Flask)   │◀── API: ТЗ, объекты ── Портал ТЗ
  Vue UI  ◀──────────────── REST /api ──────────────────▶│            │
                                                         └─────┬──────┘
                                                               │
                                                          PostgreSQL
              (тикеты, объекты ТЗ, ревью, файлы MR: код до/после, замечания линтера/ИИ/ревьюера)
```

## Быстрый старт

### Docker

```bash
cp backend/.env.example backend/.env   # по умолчанию включён демо-режим (GITLAB_MOCK=true)
docker compose up --build
```

UI: http://localhost:8080. Вставьте любую ссылку вида `https://gitlab.../group/project/-/merge_requests/1`.
В демо-режиме загрузится тестовый MR `RCK2-3232` с операциями на PL/PLUS.

### Локально (для разработки)

```bash
# Postgres
docker compose up -d db

# backend
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
flask --app wsgi db upgrade
flask --app wsgi run --debug          # http://localhost:5000
pytest                                 # тесты (SQLite in-memory, БД не нужна)

# frontend (в другом терминале)
cd frontend
npm install
npm run dev                            # http://localhost:5173, /api проксируется на :5000
```

## Настройка (`backend/.env`)

| Переменная | Назначение |
|---|---|
| `DATABASE_URL` | строка подключения к PostgreSQL |
| `GITLAB_URL`, `GITLAB_TOKEN` | адрес self-hosted GitLab и токен с правом `read_api` |
| `GITLAB_VERIFY_SSL` | `true` / `false` / путь к CA-бандлу внутреннего УЦ |
| `GITLAB_MOCK` | `true` — вместо GitLab используется демо-MR из `app/fixtures/demo_mr.json` |
| `TZ_PORTAL_MODE` | `stub` (заглушка из `app/fixtures/tz_stub.json`) или `http` |
| `LLM_MODE` | `stub` (без вызовов модели) или `openai` (OpenAI-совместимый endpoint: vLLM / TGI / Ollama) |
| `LLM_API_URL`, `LLM_MODEL`, `LLM_API_KEY` | параметры модели |
| `LLM_MAX_INPUT_TOKENS` | бюджет токенов на один запрос; если изменения не влезают, они делятся на несколько запросов |
| `LLM_CONTEXT_LINES` | сколько строк контекста брать вокруг значимых изменений (по умолчанию 2) |
| `TICKET_REGEX` | как искать номер тикета в названии MR, ветке и описании (по умолчанию `[A-Z][A-Z0-9]+-\d+`) |
| `CODE_EXTENSIONS` | какие файлы считаются кодом (проверяются линтером и уходят в модель), по умолчанию `.plp` |
| `TZ_IGNORE_PATTERNS` | служебные файлы, которые не считаются «лишними» при сверке (`*.md,.gitlab-ci.yml`) |
| `LINT_DISABLED_RULES`, `LINT_MAX_LINE_LENGTH` | настройка линтера |

## Что нужно подключить

### 1. API портала ТЗ — `backend/app/services/tz_portal.py`

Сейчас работает `StubTzPortalClient`, который читает `app/fixtures/tz_stub.json`. Когда появится API,
реализуйте `HttpTzPortalClient.get_ticket(key)` и включите `TZ_PORTAL_MODE=http`. Метод должен вернуть словарь:

```json
{
  "key": "RCK2-3232",
  "title": "Ограничение максимальной комиссии",
  "description": "Текст ТЗ…",
  "developer": "Сидоров А.В.",
  "analyst": "Кузнецова Е.М.",
  "portal_url": "https://tz-portal/…",
  "objects": [
    {"system_name": "AC_FIN\\RECALC_COMM.plp", "display_name": "Пересчёт комиссии",
     "change_description": "Что меняется по ТЗ"}
  ]
}
```

`system_name` — это «хвост» пути файла (`ТБП\операция.plp`). Сравнение идёт по последним компонентам пути,
без учёта регистра, `\` и `/` равнозначны. Например, `AC_FIN\RECALC_COMM.plp` совпадёт с
`src/AC_FIN/RECALC_COMM.plp`. Для переименованных файлов учитываются и старый, и новый путь.

### 2. Модель — `backend/app/services/llm_client.py`

* Если модель доступна по OpenAI-совместимому API (типично для Qwen в vLLM), достаточно задать
  `LLM_MODE=openai` и `LLM_API_URL`.
* Если роут свой, напишите класс с методом `complete(system: str, user: str) -> str` и верните его
  из `get_llm_client()`.
* Промпт лежит в `backend/app/services/prompts.py`. Подгоните его под формат, на котором дообучалась модель.
* Ожидаемый ответ — JSON-массив `[{"file", "line", "severity", "message", "suggestion"}]`.
  Парсер снимает обёртку ```json``` и блоки `<think>`. Если JSON в ответе нет, весь текст сохраняется
  как общее замечание к MR.

## Как экономится контекст модели

Логика в `backend/app/services/context_builder.py`:

1. **Косметика отбрасывается.** Не отправляются изменения только в пробелах, отступах или регистре
   (PL/PLUS регистронезависим), перенесённые строки, пустые строки и правки только в комментариях.
2. **Только окно вокруг изменений.** Берётся ±`LLM_CONTEXT_LINES` строк, а не весь ханк и не весь файл.
3. **Заголовок вместо тела.** Вместо всей процедуры отправляется одна строка: ближайший заголовок
   `procedure` / `function` / `PUBLIC` / `PRIVATE` / `VALIDATE` / `EXECUTE`.
4. **Общий отступ фрагмента срезается.**
5. **Стиль не отправляется.** Форматирование проверяет линтер, и модель прямо просят его не комментировать.
6. **ТЗ сокращается** до `LLM_MAX_TZ_CHARS`. Для каждого файла добавляется только его строка
   «что меняется по ТЗ».
7. **Деление по бюджету.** Если всё не помещается в `LLM_MAX_INPUT_TOKENS`, изменения делятся
   на несколько запросов, файлы из ТЗ идут первыми.

Статистика (сколько фрагментов отправлено, сколько косметических ханков отброшено, примерное число токенов)
показывается на вкладке «Обзор».

## Правила линтера PL/PLUS

| Правило | Важность | Что ищет |
|---|---|---|
| PLP001 | инфо | пробелы в конце строки |
| PLP002 | инфо | табы и пробелы вперемешку в отступе |
| PLP003 | инфо | слишком длинная строка |
| PLP010 | важно | отладочный вывод: `debug_pipe`, `stdio.put_line*`, `dbms_output` |
| PLP011 | важно | `when others then null;` (молча подавленное исключение) |
| PLP012 | важно | явные `commit` / `rollback` (`rollback to savepoint` разрешён) |
| PLP013 | средне | `select *` |
| PLP014 | критично | сравнение с null через `=` / `<>` |
| PLP015 | инфо | TODO / FIXME |
| PLP016 | средне | закомментированный код |
| PLP017 | инфо | захардкоженные ID (числа от 9 знаков) |
| PLP018 | средне | `pragma autonomous_transaction` |
| PLP019 | средне | `goto` |
| PLP020 | важно | `execute immediate` со склейкой строк |
| PLP021 | средне | пустые ветки (`then null; end`) |

Перед проверкой лексер вырезает комментарии и строковые литералы, поэтому `'when others then null;'`
внутри строки не даст ложного срабатывания. Новое правило добавляется так: класс-наследник `Rule`
в `backend/app/linters/plplus_rules.py`, затем запись в `ALL_RULES`.

## REST API

| Метод | Путь | Назначение |
|---|---|---|
| GET | `/api/health` | режимы интеграций (демо / заглушки) |
| GET | `/api/reviews?q=` | список ревью |
| POST | `/api/reviews` | `{mr_url, ticket_key?, reviewer?}`: создать и сразу проанализировать |
| GET | `/api/reviews/:id` | ревью целиком: файлы, ханки, ТЗ, замечания |
| PATCH | `/api/reviews/:id` | `{verdict, summary, reviewer}` |
| POST | `/api/reviews/:id/rerun` | перезапустить анализ (если MR обновился); комментарии ревьюера сохраняются |
| DELETE | `/api/reviews/:id` | удалить ревью |
| GET | `/api/reviews/:id/files/:fid/content` | полный текст файла до и после (для раскрытия контекста) |
| POST | `/api/reviews/:id/comments` | комментарий ревьюера `{file_id, line, side, message, severity, author}` |
| PATCH | `/api/findings/:id` | `{status: open / accepted / dismissed}` |
| DELETE | `/api/findings/:id` | удалить комментарий ревьюера |
| GET | `/api/tickets/:key?refresh=1` | тикет и объекты ТЗ |
| GET | `/api/lint-rules` | список правил линтера |

## Структура

```
backend/
  app/
    api/reviews.py            REST API
    models.py                 Ticket, TzObject, Review, ReviewFile, Finding
    services/
      review_service.py       оркестрация: GitLab → ТЗ → сверка → линтер → модель
      gitlab_client.py        GitLab API (+ демо-клиент)
      tz_portal.py            портал ТЗ (заглушка + каркас HTTP-клиента)
      tz_matcher.py           сверка объектов ТЗ с файлами MR, поиск номера тикета
      context_builder.py      отбор значимых изменений для модели
      llm_client.py, prompts.py
      diff_utils.py           разбор unified diff, кодировки (utf-8 / cp1251)
    linters/                  линтер PL/PLUS
    fixtures/                 демо-MR и заглушка ТЗ
  migrations/                 Alembic (Flask-Migrate)
  tests/
frontend/
  src/views/                  список ревью, страница ревью
  src/components/DiffFile.vue дифф-просмотрщик (inline / side-by-side)
  src/utils/                  построение строк диффа, подсветка PL/PLUS
```

## Ограничения текущей версии

* Анализ синхронный: запрос на создание ревью ждёт ответа модели (таймауты gunicorn и nginx — 600 с).
  Для двух ревьюеров этого достаточно; если понадобится, можно вынести в очередь (RQ / Celery).
* Авторизации и ролей нет. Имя ревьюера вводится в шапке и хранится в браузере.
* Комментарии в GitLab не отправляются, они живут только на портале.
