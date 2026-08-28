# Журнал действий (action log)

Сквозная летопись «кто, что, когда сделал и чем закончилось» для последующего
разбора ошибок: какие действия предшествовали сбою, какие запросы падали, какие
этапы конвейера рушились и почему, когда рестартовал сервер.

## Что пишется

Ниже — какие СОБЫТИЯ и от каких источников попадают в журнал. По каким каналам
перечисленные поля разложены (и почему `path` не лежит рядом с `route`) —
следующий раздел.

| kind | Источник | Содержимое |
|------|----------|------------|
| `api` | `ActionLogMiddleware` (`backend/app/core/action_log.py`) | каждый HTTP-запрос: `actor` (логин портала из session-cookie), `method`, `path`, `route`, `query`, `project_id` (из path-параметров), `status`, `dur_ms`, `ip`; при исключении — `error` + `traceback` |
| `pipeline` | хук в `audit_logger.update_pipeline_log()` — единая воронка всех stage-статусов (manager, stage runner'ы через ctx, prepare_service) | `project_id`, `stage`, `status` (running/done/partial/skipped/error/interrupted), `message`, `error`, `duration_sec` |
| `app_log` | мост `install_logging_bridge()` на root-логгере | WARNING/ERROR/CRITICAL из **всех** модулей backend: `level`, `logger`, `message`, `exc` |
| `system` | lifespan в `main.py` | `startup` / `shutdown` — по ним видны рестарты и падения сервера |
| `worker` | распределённый контур (`distributed_workers/authorization.py`, `routers/audit_workers_admin.py`) | решения безопасности: `event`, `actor`, `severity`, `required_permission`, `reason`, `role`, `auth_enabled` |

## Три канала

Журнал разделён на три канала с разными назначением, владельцем и гарантиями
(принцип **P-13** в `docs/architecture/ADR_BIBLE.md`). Каналы не подменяют друг
друга, и перечисленные поля из таблицы выше распределены между ними, а не
дублируются:

| Канал | Носитель | Что содержит | Гарантии | Ретеншн |
|-------|----------|--------------|----------|---------|
| **durable audit** | `actions-YYYY-MM-DD.jsonl` | только поля allowlist `_AUDIT_FIELDS`: `ts`, `kind`, `eid`, `actor`, `project_id`, `method`, `route`, `status`, `stage`, `event`, `level`, `logger`, `duration_sec` + коды безопасности `worker` | append-only, фиксированная схема, потеря записи — инцидент | `ACTION_LOG_RETENTION_DAYS` (180) |
| **diagnostic** | `diag-YYYY-MM-DD.jsonl` | непроверенный ввод после redaction: `path`, `query`, `message`, `error`, `traceback`, `exc`, `ip`, `dur_ms` + неизвестные поля | допускает потерю и семплирование | `ACTION_LOG_DIAG_RETENTION_DAYS` (14) |
| **метрики** | in-process, `action_log.metrics_snapshot()` | счётчики по `kind`; по HTTP — labels `method × route × status` и гистограмма `dur_ms` | низкокардинальные labels; идентификаторов, путей и пользовательского ввода в labels нет; потолок 500 серий, сверх — `<over-cardinality>` | процесс |

Записи двух файловых каналов связаны correlation id **`eid`**: одно событие даёт
одну строку в `actions-*` и (если есть что диагностировать) одну в `diag-*` с
тем же `eid`. Строка диагностики самодостаточна — в неё продублирован
безопасный контекст (`method`, `route`, `status`, `stage`, `level`, `logger`),
чтобы её можно было читать без джойна.

Разделение `route`/`path` даётся почти бесплатно: middleware и раньше вычислял
оба. `route` — ШАБЛОН вида `/api/audit/{project_id}/log`, идентификаторов не
несёт, поэтому уходит в вечный журнал; сырой `path` несёт `project_id` у 76
эндпоинтов, `session_id` у 26, `object_id` у 11 и `user_id` у 3 — и уходит в
диагностику. `project_id` при этом остался в durable audit **отдельным
структурным полем**, а не подстрокой пути. Если маршрут не сматчился (404),
шаблона нет — durable audit его не выдумывает, сам путь смотрят в диагностике.

## Контракт redaction

Redaction — контракт, а не соглашение: чувствительные значения, query-параметры,
presigned URL, cookies, токены, секреты и ПДн не попадают **ни в один канал по
умолчанию**. Попадание регулируется явным allowlist поля, а не отсутствием
запрета. Текст исключения и traceback считаются непроверенным пользовательским
вводом и проходят ту же обработку.

Работают два независимых механизма, и оба одновременно:

**1. Разделение по имени поля.** В durable audit попадают только имена из
`_AUDIT_FIELDS`. Это закрывает главную дыру: `log_event(kind, **fields)`
принимает произвольные kwargs, а мост `install_logging_bridge()` висит на
root-логгере — то есть ЛЮБОЙ `logger.error()` любого из 43 модулей backend
раньше ложился в вечный журнал дословно, вместе с тем, что автор вызова туда
класть не собирался. Теперь от `app_log` в durable audit остаётся факт
(`level`, `logger`), а текст уходит в диагностику. Незнакомое поле — из нового
вызова, из `**extra` чужого модуля, из кода, который напишут завтра — в вечный
журнал не попадёт никогда. Расширение — только через
`ACTION_LOG_AUDIT_EXTRA_FIELDS`.

**2. Redaction значений** (`_scrub()`), применяется и к полям allowlist —
allowlist разрешает ИМЯ поля, но не подписывается за значение:

| Правило | Пример входа | В журнале |
|---------|--------------|-----------|
| абсолютные пути ФС | `/root/projects/…/projects/AR/13АВ-РД` | `<projects>/AR/13АВ-РД`, `<root>`, `<data>`, `<home>` |
| userinfo и query URL (presigned) | `…/o.pdf?X-Amz-Signature=…` | `…/o.pdf?[redacted]` |
| `Bearer` / `Basic` | `Authorization: Bearer sk-…` | `Authorization: [redacted] [redacted]` |
| «имя=значение» с секретным именем | `token=…`, `DB_PASSWORD="…"`, `Cookie: portal_session=…` | `token=[redacted]` |
| JWT | `eyJ….eyJ….sig` | `[redacted:jwt]` |
| непрозрачный блоб 40+ символов | ключ/подпись/хэш | `[redacted:blob]` |
| вендорский префикс учётных данных | `AKIA…`, `ASIA…`, `sk-`/`sk-ant-`/`sk-or-`, `ghp_`/`gho_`, `github_pat_`, `xoxb-`/`xoxp-`, `AIza…`, `glpat-` | `[redacted:credential]` |
| e-mail | `ivan.petrov@example.com` | `[redacted:email]` |
| IPv4/IPv6 (ПДн) | `10.20.30.40` | `10.20.30.x` (подсеть, не хост) |
| управляющие символы | `\x1b[31m`, подделка строк журнала | пробел |

Порядок правил значим. Правило вендорских префиксов стоит **после**
блоб-правила, а не до: `AKIA<id><secret>` одним куском снимается блоб-правилом
целиком, тогда как срабатывание префикса раньше отрезало бы только голову и
оставило секретный хвост. Префиксное правило добирает то, чего блоб-правило не
видит, — короткие ключи без нужной длины и энтропии (`AKIA` + 16 заглавных =
20 символов). Единственный неоднозначный префикс `sk-` дополнительно требует
цифру в ключе, иначе он съедал бы обычные слова и сегменты путей.

**Query-параметры.** Значение пишется только для параметров из allowlist
(структурные: `limit`, `offset`, `page`, `days`, `format`, `sort`, `status` и
т.п. — см. `_QUERY_SAFE_PARAMS`, расширение — `ACTION_LOG_QUERY_ALLOW_EXTRA`).
Всё остальное — включая свободные `q`/`search`/`query` и любые идентификаторы —
пишется как `имя=[redacted]`: ИМЯ параметра видно (оно из схемы API, а не из
ввода), значение нет.

**Traceback** усекается умно: голова + маркер `… [усечено N симв.] …` + хвост,
потому что текст исключения находится в конце, и обычное `[:N]` его теряло.

**Fail-soft сохраняется.** Ни одна ошибка журнала не ломает основной поток;
redaction, упавшая на своём входе, возвращает `[redacted]`, а не сырое значение.

## Шум-фильтр HTTP

Поллинговые GET фронта (live-status, `*/status`, `/api/usage/*`, картинки
страниц/блоков, статусы job'ов и т.п.) **не пишутся**, иначе журнал распухает
на мегабайты в час. Правила:

- фильтр применяется ТОЛЬКО к успешным GET/HEAD/OPTIONS (<400);
- любой POST/PUT/PATCH/DELETE пишется всегда;
- любой ответ >=400 и любое исключение пишутся всегда (даже на шумовом пути);
- встроенный список — `_NOISE_PATTERNS` в `action_log.py`; расширение без
  правки кода — env `ACTION_LOG_NOISE_EXTRA` (CSV из regex).

## Хранилище

Суточные append-only JSONL в `DATA_DIR/logs/actions/`: `actions-YYYY-MM-DD.jsonl`
(durable audit) и `diag-YYYY-MM-DD.jsonl` (diagnostic). В prod данные прибиты к
MAIN через `AUDIT_DATA_DIR`, поэтому журнал живёт в `logs/actions/` рядом с
`server.log` независимо от deploy-worktree кода. Одна строка = одно событие,
`ts` — локальное время с таймзоной. Файлы удаляются при первой записи нового дня:
`actions-*` старше `ACTION_LOG_RETENTION_DAYS` (180), `diag-*` старше
`ACTION_LOG_DIAG_RETENTION_DAYS` (14). Срок у диагностики короче не случайно:
именно там оседает непроверенный ввод, и хранить его полгода — ровно та
проблема, ради которой каналы разделены.

Запись потокобезопасна (lock) и fail-soft: ошибка журнала никогда не ломает
запрос/конвейер (однократное предупреждение в stderr).

**Суточный бюджет байт — ОБЩИЙ НА ОБА КАНАЛА.** `ACTION_LOG_MAX_DAY_BYTES`
означает ровно то же, что означал до разделения каналов: сколько журнал вправе
занять за сутки суммарно. Default 256 МБ — это не более 256 МБ/сут на
`actions-*` и `diag-*` вместе, а не по 256 МБ на файл (иначе флаг молча удвоил
бы настроенный оператором потолок до 512 МБ/сут). При исчерпании бюджета
события дропаются до следующего дня, а в каждый затронутый файл пишется маркер
`day_cap_reached` — чтобы обрыв был виден в том канале, который читают. На
границе бюджета выигрывает durable audit: он пишется первым, потеря его записи —
инцидент, потеря диагностики допустима. Бюджет пересчитывается по фактическим
размерам обоих файлов, поэтому рестарт посреди дня потолок не обнуляет.

Стационарно диска стало меньше, а не больше: раньше это были 180 дней полных
записей, теперь — 180 дней тонких audit-записей плюс 14 дней диагностики,
которая и составляет основной объём.

## Как читать

```bash
# Сводка за 7 дней: объёмы, ошибки, активность инженеров, топ путей
python scripts/analyze_action_log.py

# Только ошибки за 3 дня
python scripts/analyze_action_log.py --errors --days 3 --limit 50

# Действия конкретного инженера / поиск
python scripts/analyze_action_log.py --user andrey
python scripts/analyze_action_log.py --kind pipeline --q block_analysis

# ДИАГНОСТИКА: сырой path, query, текст ошибки, traceback, message моста
python scripts/analyze_action_log.py --errors --days 3 --channel diag
```

`--channel` (`audit` по умолчанию, `diag` — диагностика) нужен всегда, когда
нужны подробности: в durable audit их нет по построению. Одно и то же событие
находится в обоих режимах по `eid`, который CLI печатает как `#a41cee4f38a7`.

REST (за portal-auth):

- `GET /api/action-log?date_from=&date_to=&kind=&actor=&q=&errors_only=&limit=&offset=`
  — события новые→старые; в ответе `persons` — маппинг логин→ФИО из users.json;
- `GET /api/action-log/stats?days=7` — сводка по дням.

REST отдаёт durable audit — так же, как отдавал до разделения каналов.
Диагностика через HTTP не публикуется: `read_events(channel="diag")` и
`stats(channel="diag")` доступны из Python и из CLI, но не с портала.

Чтение файлов — в `asyncio.to_thread` (не блокирует loop → не дразнит watchdog).

## Флаги

| Env | Default | Что делает |
|-----|---------|-----------|
| `ACTION_LOG_ENABLED` | `true` | мастер-выключатель |
| `ACTION_LOG_HTTP_ENABLED` | `true` | контур HTTP-запросов |
| `ACTION_LOG_PIPELINE_ENABLED` | `true` | контур этапов конвейера |
| `ACTION_LOG_APPLOG_ENABLED` | `true` | мост logging (WARNING+) |
| `ACTION_LOG_RETENTION_DAYS` | `180` | глубина хранения в днях |
| `AUDIT_ACTION_LOG_DIR` | `DATA_DIR/logs/actions` | путь к журналу |
| `ACTION_LOG_NOISE_EXTRA` | `[]` | доп. шумовые regex (CSV) |
| `ACTION_LOG_MAX_DAY_BYTES` | `256 МБ` | потолок суточного объёма ОБОИХ каналов суммарно: сверх — дроп до следующего дня + маркер `day_cap_reached` в каждом затронутом файле (защита диска от штормов) |
| `ACTION_LOG_APPLOG_MAX_PER_MIN` | `600` | потолок app_log-событий в минуту: сверх — дроп + агрегат о числе подавленных |
| `ACTION_LOG_REDACTION` | `true` | контракт redaction и разделение каналов. `0` — **аварийный откат** к прежнему поведению один-в-один (один файл, все поля дословно, включая секреты и ПДн в вечном журнале). Это откат, а не режим эксплуатации |
| `ACTION_LOG_DIAG_ENABLED` | `true` | писать ли диагностический канал. `0` = максимум приватности: на диск не ложится ничего, кроме durable audit, диагностика теряется целиком |
| `ACTION_LOG_DIAG_RETENTION_DAYS` | `14` | глубина хранения диагностики в днях |
| `ACTION_LOG_AUDIT_EXTRA_FIELDS` | `[]` | явное расширение allowlist durable audit (CSV имён полей) — единственный способ пустить новое поле в вечный журнал |
| `ACTION_LOG_QUERY_ALLOW_EXTRA` | `[]` | явное расширение allowlist query-параметров, значение которых разрешено писать (CSV имён) |

## Реализация и гарантии

- `backend/app/core/action_log.py` — ядро: писатель, шум-фильтр, pure-ASGI
  middleware (НЕ BaseHTTPMiddleware — не трогает тело запроса/ответа, безопасен
  для стриминга `chat/stream` и загрузок), мост logging, чтение.
- Middleware добавлен ПОСЛЕДНИМ в `main.py` → внешний: видит 401 от PortalAuth
  (неавторизованные попытки — тоже действия). Событие пишется после полного
  ответа (известны статус и длительность).
- Мост logging добавляет к root ещё и `StreamHandler(stderr, WARNING)`:
  добавление хендлера отключает `logging.lastResort`, а прежнее поведение
  (WARNING+ → stderr → `server.err.log`) должно сохраниться.
- Тело запроса НЕ логируется (пароль из `POST /api/auth/login` не попадает в
  журнал; плюс никакого риска для стриминга/загрузок).
- Разделение каналов и redaction — `_split_channels()` и `_scrub()` в
  `action_log.py`; границы каналов заданы декларативно таблицами
  `_AUDIT_FIELDS` / `_DIAG_LIMITS` / `_DIAG_CONTEXT` рядом с разбором контракта.
- Писатель самолечится: если `logs/actions/` удалили посреди дня, следующая
  запись пересоздаёт директорию (сброс кэш-ключа в except).
- На shutdown lifespan вызывает `uninstall_logging_bridge()` — мост не
  переживает `with TestClient(app)` в тестах.
- Чтение потоковое (`deque`, память O(limit), `errors="replace"` против битого
  UTF-8); `stats(days=N)` — N календарных дней; кривые `date_from/date_to` → 422.
- CLI экранирует управляющие символы недоверенных полей (`\x1b` из path не
  исполняется терминалом) — это осталось: redaction чистит контрольные символы,
  но CLI не вправе полагаться на чужой слой, читая и старые файлы тоже.
- Обратная совместимость чтения: `read_events()`/`stats()`, `GET /api/action-log`
  и CLI продолжают работать с файлами, записанными до разделения каналов
  (`path`/`error` внутри `actions-*`), — это закреплено тестом
  `test_reader_still_understands_pre_split_files`.
- Тестовая изоляция двухуровневая: process-lifetime песочница
  `AUDIT_ACTION_LOG_DIR` в module-level conftest (базовое значение никогда не
  прод) + autouse-фикстуры `_isolate_action_log` per-test.
- Тесты: `backend/tests/test_action_log.py`, `tests/test_action_log_api.py`.
