# ADR-0006. Целевая раскладка репозитория и границы зависимостей

**Статус:** proposed — рекомендован вариант B; принятие после `W0-DEC-01`<br>
**Дата:** 2026-08-28<br>
**Владельцы:** architecture owner, lane ARC<br>
**Утверждено:** не утверждено<br>
**Decision deadline:** `W0-DEC-01`; до старта `W1-OPS-02` и `W1-WEB-01`<br>
**Supersedes:** нет<br>
**Superseded by:** нет<br>
**Связанные task IDs:** W0-ARC-01, W0-DEC-01, W0-ARC-02, W1-INT-00, W1-OPS-02, W1-WEB-01, W1-META-01, W1-STO-01, W1-JOB-01, W1-ENG-01, W1-AI-01, W1-API-01, W1-MIG-01, W1-INT-01<br>
**Затронутые принципы Bible:** P-04, P-05, P-06, P-10, P-11, P-12, P-13, P-15, P-17

## 1. Контекст

Roadmap задаёт десять capability lanes и требует, чтобы задачи волны
редактировали непересекающиеся каталоги. Физически такого разделения не
существует: таблица lanes прямо оговаривает, что до ADR target layout она
задаёт логическое, а не физическое владение. Без этого решения задача не
может заполнить поля `allowed_paths` и `forbidden_shared_files`,
`W1-OPS-02` не может написать dependency checker, а `W1-WEB-01` не знает,
где создавать web-корень.

### 1.1. Подтверждённые факты

Числа получены 2026-08-28 на рабочем дереве коммита `b3a56a3c` по
отслеживаемым файлам: `git ls-files -z '*.py' | xargs -0 wc -l`.
Неотслеживаемые файлы в подсчёт не входят. Разделитель `-z` обязателен: без
него 46 файлов с кириллицей в пути молча теряются и счёт занижается на
6 153 строки. Репозиторий продолжает меняться, поэтому числа являются
снимком названного коммита; пункт, снятый на более позднем коммите, называет
его отдельно.

- 1114 файлов `.py` и 418 467 строк; файлов `.ts` и `.tsx` — 0;
- в действующем контуре четыре точки сборки процесса, а не одна:
  `uvicorn backend.app.main:app`, `python -m backend.app.agent_gateway`,
  `python -m backend.app.security.issuer_service` и
  `python -m audit_worker`; все четыре объявлены в `deploy/systemd/`;
- главная из них, `backend/app/main.py`, совмещает несовместимые роли:
  `sys.path.insert` в строке 18, ручной разбор `.env` в строках 21–27,
  условная регистрация роутеров с импортами внутри `if` в строках
  263–280, WebSocket-эндпоинты и HTML-роуты в том же файле;
- слоёв `api/application/domain/adapters` нет: `backend/app` состоит из
  десяти плоских подпакетов; `backend/**` содержит 224 649 строк, из них
  `services/` — 160 файлов и 83 469 строк, `pipeline/` — 154 файла и
  70 537 строк;
- `pyproject.toml`, `setup.py`, конфигураций `ruff`, `mypy` и
  `import-linter` в репозитории нет; единственный Python-конфиг —
  `pytest.ini`;
- импорт работает от корня репозитория; в дереве 359 вхождений
  `sys.path.insert/append`, пять из них — в production-модулях
  `backend/app`;
- зависимости идут в обе стороны: `backend` → `audit_worker` (21 импорт в
  семи файлах), `backend` → `scripts` (2), `backend` → `experiments` (3),
  `norms/_core.py:28` → `backend.app.core.config`, а
  `backend/app/services/storage/read_canary.py:794` импортирует приватную
  функцию HTTP-роутера;
- `scripts/` импортирует `tests/` (24 вхождения в четырёх файлах), а
  `scripts/deploy_audit_worker.py:118` включает `tests/distributed_audit_e2e/`
  в production-bundle;
- `os.environ` встречается 115 раз в `services/` и 76 раз в `pipeline/`;
  `os.getenv` в этих каталогах не используется, по репозиторию — четыре
  вхождения в `scripts/` и `tests/`; каталог `models/` от окружения свободен;
- `contracts/` уже существует как импортируемый пакет: 20 отслеживаемых
  файлов, protobuf-контракты `agent_stream/v1` и `worker_certificate/v1`,
  снимок HTTP-поверхности `http/v1`; его импортируют
  `backend/app/agent_gateway` (12 вхождений), `audit_worker` (7) и
  `tests` (28);
- фактическим контрактом физической раскладки служат `BUNDLE_INCLUDE` в
  `scripts/deploy_audit_worker.py` и пары `WorkingDirectory` + `python -m`
  в шести unit-файлах `deploy/systemd/`;
- границы импорта охраняют отдельные ad-hoc тесты, а не конфигурация:
  `tests/test_distributed_workers_flag_off.py:334`,
  `tests/test_distributed_workers_central_handoff.py:600`,
  `tests/test_distributed_workers_pipeline_provider.py:916`,
  `backend/tests/test_critic_v2_ui_cache.py:290`;
- CI по состоянию на более поздний коммит `55aa4b6d` состоит из двух job в
  `.github/workflows/ci.yml` — `regression-gate`,
  где шаг гейта помечен `continue-on-error: true`, и `chaos` с тем же
  флагом на уровне job; сам файл объявляет режим observe-first. Проверок
  границ импорта, typecheck и frontend-джоба в CI нет;
- каталоги `src/`, `web/`, `db/`, `infra/`, `migration/`, `var/` свободны;
  имена каталогов верхнего уровня со stdlib не пересекаются.

### 1.2. Предположения

- новый контур получает собственный процесс развёртывания не раньше W2,
  поэтому `deploy/systemd/**` и bundle в волнах 0–1 не меняются;
- объём нового кода волны 1 измеряется тысячами строк, поэтому tooling
  монорепозитория пока не окупается;
- число исполнителей соответствует ADR-0015 и не превышает одного
  владельца на lane.

## 2. Forces и требования

Обязательные свойства:

- десять lanes получают непересекающиеся физические каталоги — это
  проверяемый критерий G0, а не декларация;
- правила импорта выражаются конфигурацией и проверяются в CI;
- composition root нового контура существует ровно один, имеет одного
  владельца и меняется только integration task;
- новый контур не обязан ждать переноса legacy: оба контура живут в одном
  checkout одновременно;
- domain-модули не читают окружение, файловую систему, HTTP, часы и
  случайность (P-06);
- любая связь с legacy проходит через именованный anti-corruption adapter
  с метрикой, владельцем и датой удаления (ADR-0003, P-10).

Ограничения совместимости:

- legacy остаётся рабочим продуктом и эталоном поведения (ADR-0001);
  переименование `backend/`, `frontend/`, `norms/`, `audit_worker/`
  ломает systemd unit, bundle и `scripts/production_source_guard.py`,
  поэтому в этом решении не выполняется;
- `contracts/agent_stream/v1` и `contracts/worker_certificate/v1`
  обслуживают работающих удалённых воркеров: они остаются действующими и
  не переезжают;
- действует один релизопригодный checkout: вариант A ADR-0016, `AGENTS.md`
  и `CLAUDE.md` не меняются этой задачей;
- корень репозитория остаётся на `sys.path` у legacy-процессов, поэтому
  имя пакета нового контура не должно затенять модуль stdlib или
  существующий пакет.

Security, consistency, RPO/RTO: решение не вводит новых хранилищ и не
меняет границу безопасности. Требование одно — конфигурация и секреты
читаются только в composition root, а журналы нового контура подчиняются
контракту redaction `W0-LOG-01` (P-13). RPO/RTO определяют ADR-0007 и
ADR-0008.

Объёмы и SLO не изменяются: раскладка не входит в runtime-путь legacy.

Срок и команда: в W0 находятся 13 owner-only решений при WIP=1, поэтому
раскладка обязана быть выполнима силами одного интегратора и не требовать
одновременного переезда существующего кода.

Намеренно не оптимизируется:

- скорость импорта, размер артефакта и время сборки;
- публикация пакетов во внешний индекс;
- разделение на несколько репозиториев;
- перенос legacy-кода в новую структуру.

## 3. Рассмотренные варианты

### Вариант A. Новый контур внутри `backend/app`

Новые модули создаются как подпакеты действующего приложения, например
`backend/app/newcore/metadata`.

Преимущества: ноль изменений в развёртывании, bundle и systemd; знакомый
путь импорта; отсутствует вторая точка входа.

Недостатки: ownership zone нового контура физически вложена в крупнейший
legacy-хотспот; `backend/app/main.py` остаётся общим composition root для
обоих контуров, а Bible запрещает два параллельных изменения composition
root; правило «новый контур не импортирует legacy» невыразимо
конфигурацией, потому что оба контура — один пакет; каталог `backend/`
уже содержит 224 649 строк, и любое правило границ придётся описывать
списком исключений.

Стоимость: минимальная на старте, растущая на каждой задаче W1.

Риски: неотличимость нового кода от legacy в отчётах и в bundle;
невозможность объявить legacy retirement по каталогу в W5.

### Вариант B. Отдельный корень нового контура рядом с legacy

Новый control plane живёт в `src/auditmanager/**` как устанавливаемый
дистрибутив, web-приложение — в `web/**`, реестр контрактов расширяется в
`contracts/**`, миграции — в `db/migrations/**`, инфраструктура — в
`infra/**`. Legacy-каталоги остаются нетронутыми, обращение к ним — только
через `src/auditmanager/analysis/adapters/legacy_bridge/**` и `migration/**`.

Преимущества: каждая lane получает собственный каталог; правило границ
выражается списком разрешённых рёбер, а не списком исключений; новый
composition root отделён от четырёх точек сборки legacy, поэтому владельцы
не конкурируют; retirement legacy в W5 выполняется удалением каталогов;
установка пакета в venv убирает необходимость в `sys.path`-мутациях.

Недостатки: две раскладки сосуществуют месяцами; появляется риск «вечного
второго дома», если волна не доводит вертикальный сценарий до primary;
нужен отдельный набор правил, чтобы новый каталог не превратился во второй
`utils`.

Стоимость: один integration task на skeleton и `pyproject.toml`, один — на
CI-проверку границ.

Риски: дрейф правил при отсутствии машинной проверки; поэтому проверка
объявлена частью решения, а не пожеланием.

### Вариант C. Монорепозиторий с workspace-tooling

Разделение на публикуемые пакеты по bounded context с менеджером
workspace и task runner.

Преимущества: границы обеспечены сборкой; версии модулей независимы.

Недостатки: P-15 требует вводить абстракцию после двух подтверждённых
применений — сейчас нет ни одного; для работы схемы legacy тоже нужно
превратить в пакет, что противоречит ADR-0001 и расходует бюджет P-17;
lead time измеряется неделями при WIP=1.

Стоимость: наибольшая; требует отдельного решения по релизам.

Риски: программа тратит критический путь W0 на инструментальную задачу,
не приближающую первый вертикальный сценарий.

## 4. Предлагаемое решение

Рекомендуется **вариант B**. Ниже — предмет решения; оставшиеся развилки
перечислены в §4.7.

### 4.1. Целевая раскладка

```text
<repo>/
  src/
    auditmanager/          # новый control plane, устанавливаемый дистрибутив
      shared/              # kernel: типы ID, ошибки, ports часов, UUID, событий
      access/              # Identity and Access
      documents/           # Projects and Documents
      ingest/              # Versions and Ingest
      storage/             # Storage and Blobs
      analysis/            # порт анализа, legacy bridge, реестры и replay
      jobs/                # Audit Jobs and Runs, outbox
      workers/             # Worker Control
      findings/            # Findings and Reviews
      decisions/           # Expert Decisions and Knowledge Base
      comparison/          # Comparison
      export/              # Export
      operations/          # Operations and Audit Trail
      api/                 # HTTP/BFF композиция нового контура
      bootstrap/           # composition root: settings, container, entrypoints
  web/                     # Next.js приложение по ADR-0017
  contracts/               # реестр контрактов, семейство и версия
  db/migrations/           # схема PostgreSQL нового контура
  migration/               # инструменты сопоставления контуров
  infra/                   # CI, systemd, nginx, runbooks, dashboards
  var/                     # runtime-состояние, не версионируется
  backend/ frontend/ audit_worker/ norms/ prompts/ scripts/ tests/
  experiments/ deploy/     # действующий контур, раскладка не меняется
```

Соответствие модулей и bounded contexts Bible §3.3:

| Bounded context | Модуль |
| --- | --- |
| Identity and Access | `access` |
| Projects and Documents | `documents` |
| Versions and Ingest | `ingest` |
| Storage and Blobs | `storage` |
| Audit Jobs and Runs | `jobs` |
| Findings and Reviews | `findings` |
| Expert Decisions and Knowledge Base | `decisions` |
| Comparison | `comparison` |
| Export | `export` |
| Worker Control | `workers` |
| Operations and Audit Trail | `operations` |

Четыре модуля не являются bounded context и добавлены осознанно:
`shared` — общий kernel типов и ports, не владеющий данными; `analysis` —
физическое место «Analysis port» из схемы Bible §1: он не владеет
таблицами, а публикует порт к движку анализа и хранит content-addressed
реестры профилей, промптов и норм; `api` — композиция HTTP/BFF без
бизнес-правил; `bootstrap` — composition root. Ни один из четырёх не
получает права владеть сущностью предметной области. Раскладка остаётся
раскладкой одного развёртываемого приложения: границы обеспечивают модули
и проверка импортов, а не сеть (P-05).

Внутри каждого модуля `src/auditmanager/<module>/` действует одна и та же
раскладка слоёв:

```text
<module>/
  domain/        # правила и инварианты, без I/O
  ports/         # интерфейсы, объявленные модулем
  application/   # commands, queries, unit of work
  adapters/      # PostgreSQL, S3, HTTP, legacy; реализуют ports
  tests/         # domain unit, contract и integration тесты модуля
  __init__.py    # публичный API модуля
```

Каталог `web/` воспроизводит раскладку ADR-0017 без изменений:

```text
web/src/
  app/        # Next App Router: route/layout/loading/error, тонкие re-exports
  _app/       # FSD App: providers и frontend infrastructure
  _pages/     # FSD Pages: композиция полного экрана
  widgets/
  features/
  entities/
  shared/     # ui-kit, generated API, runtime schemas, lib/config
```

Модуль создаётся задачей, которая первой в него пишет, поверх skeleton,
созданного `W1-INT-00`. Пустые каталоги-заглушки не создаются: имена в
таблице зарезервированы, чтобы последующая задача не изобрела синоним, а
не чтобы существовать без кода.

### 4.2. Зоны владения

Каждый путь принадлежит ровно одной зоне. Зона задаётся glob, а не
словесным описанием. Путь, не попавший ни в одну зону, принадлежит
integration task волны.

| Lane | Каталоги | Открывающая задача |
| --- | --- | --- |
| ARC | `docs/architecture/**`, `contracts/README.md`, `contracts/domain/**`, `src/auditmanager/shared/**` | W0-ARC-01 |
| META | `src/auditmanager/documents/**`, `src/auditmanager/findings/**`, `src/auditmanager/decisions/**` | W1-META-01 |
| META | `db/migrations/**` | W1-META-02 |
| STO | `src/auditmanager/storage/**`, `src/auditmanager/ingest/**` | W1-STO-01 |
| JOB | `src/auditmanager/jobs/**`, `src/auditmanager/workers/**` | W1-JOB-01 |
| ENG | `src/auditmanager/analysis/domain/**`, `src/auditmanager/analysis/ports/**`, `src/auditmanager/analysis/application/**`, `src/auditmanager/analysis/tests/**`, `src/auditmanager/analysis/adapters/legacy_bridge/**`, `src/auditmanager/analysis/adapters/stages/**`, `src/auditmanager/analysis/__init__.py`, `src/auditmanager/analysis/adapters/__init__.py` | W1-ENG-01 |
| AI | `src/auditmanager/analysis/adapters/registry/**`, `src/auditmanager/analysis/adapters/replay/**` | W1-AI-01 |
| API | `src/auditmanager/api/**`, `src/auditmanager/access/**`, `contracts/api/**` | W1-API-01 |
| WEB | `web/**` | W1-WEB-01 |
| MIG | `migration/**` | W1-MIG-01 |
| OPS | `infra/**`, `.github/workflows/**`, `src/auditmanager/operations/**` | W1-OPS-01 |

Модули `src/auditmanager/comparison/**` и `src/auditmanager/export/**` в
волнах 0–1 не открываются; владелец назначается волной, которая их
открывает. Семейства `contracts/**`, не названные в таблице, имеют
владельцев по §4.5. Каталог `var/**` кодом не является, в git не
попадает и зоны владения не получает.

Отдельно перечислены файлы с собственной задачей-владельцем — независимо
от того, лежат они внутри зоны или вне её. Остальные задачи их не касаются:

| Hotspot | Задача-владелец | Почему |
| --- | --- | --- |
| `pyproject.toml`, `pytest.ini` | W1-INT-00 | root dependency и общий контракт запуска тестов |
| `src/auditmanager/bootstrap/**` | W1-INT-00, далее integration task волны | composition root, ADR-0002 |
| `db/migrations/` head | W1-META-02 | единственный владелец migration head |
| `contracts/api/v1/**` | W1-API-01 | OpenAPI seed нового контура |
| `contracts/domain/v1/**` | W0-ARC-02 | domain contract v1 |
| `web/package.json`, lockfile | W1-WEB-01 | root lockfile web |
| `.github/workflows/**` | W1-OPS-02 | общий build и CI gate |
| `deploy/systemd/**`, `scripts/deploy_audit_worker.py`, `scripts/production_source_guard.py` | integration task волны, назначенная OPS | контракт выкатки действующего контура |
| `backend/app/main.py`, `backend/app/agent_gateway/__main__.py`, `backend/app/security/issuer_service.py`, `audit_worker/__main__.py` | integration task волны | четыре composition root действующего контура |
| `frontend/package.json`, `frontend/package-lock.json`, `frontend/tsconfig*.json` | W1-WEB-02 | зависимости и typecheck действующего фронтенда |
| `frontend/static/js/app.js`, `frontend/index.html`, `backend/app/pipeline/manager.py` | задача волны, назначенная ENG или WEB | legacy-хотспоты; две задачи на один хотспот не запускаются |

#### Ограниченное pre-G1 владение `W0-INT-01`

Таблица выше закрепляет `pytest.ini`, `.github/workflows/**` и
frontend-манифесты за задачами волны 1. Но собрать clean-room CI и перевести
regression gate в enforce нужно ДО G1 — это и есть `W0-INT-01`, и без правки
ровно этих файлов задача невыполнима. Роадмап требовал согласовать
исключение здесь, а не обходить его молча.

Поправка внесена, пока ADR имеет статус `proposed`: после принятия изменение
оформлялось бы новым ADR, а не правкой задним числом (§9 Bible).

| Файл | Владелец до G1 | Владелец после G1 | Граница исключения |
| --- | --- | --- | --- |
| `pytest.ini` | `W0-INT-01` | `W1-INT-00` | только регистрация lane markers и выборка по умолчанию; секции нового контура не создаются |
| `requirements*.txt`, `constraints*.txt` | `W0-INT-01` | `W1-INT-00` (`pyproject.toml`) | материализация frozen dependency receipt §4.1 quality/runtime contract |
| `.github/workflows/**` | `W0-INT-01` | `W1-OPS-02` | подключение probe, бюджетов, JUnit/receipt и enforce действующего гейта; job'ы нового контура не добавляются |
| `frontend/tsconfig*.json` | `W0-INT-01` | `W1-WEB-02` | включение `strict` действующего typecheck; состав `include` не расширяется |
| `frontend/package.json`, `frontend/package-lock.json` | `W1-WEB-02` | `W1-WEB-02` | **исключение НЕ распространяется**: смена зависимостей фронтенда остаётся за владельцем |

Исключение прекращается автоматически с открытием соответствующей задачи
волны 1. Оно не даёт права менять состав зависимостей фронтенда и не
разрешает создавать skeleton нового контура — это по-прежнему `W1-INT-00`.

### 4.3. Правила зависимостей

Правила пронумерованы, чтобы конфигурация checker и запись исключения
ссылались на конкретный пункт.

- **R-01.** Слои модуля упорядочены сверху вниз:
  `adapters → application → ports → domain`; импорт разрешён только вниз.
  Одного упорядоченного контракта слоёв недостаточно: он разрешает
  `adapters → application`, что этим правилом запрещено. Поэтому проверка
  состоит из двух частей — упорядоченный контракт слоёв и отдельный
  запрет пары `adapters → application`. Каталог `tests` в упорядоченный
  контракт не входит: он импортирует любой слой своего модуля и публичный
  API соседних модулей, а обратный импорт `tests` из production-кода
  запрещается отдельным правилом.
- **R-02.** `domain` не импортирует `os`, `sys`, `io`, `pathlib`,
  `shutil`, `tempfile`, `subprocess`, `socket`, `time`, `random`,
  `uuid`, `logging`, `urllib`, `requests`, `httpx`, `aiohttp`,
  `fastapi`, `starlette`, `sqlalchemy`, `psycopg`, `asyncpg`, `boto3`,
  `botocore`, `redis`, `contracts`. Часы, случайность и идентификаторы
  поступают через ports из `shared`.
- **R-03.** Межмодульный импорт разрешён только через публичный API
  `auditmanager.<module>`: application ports, команды, запросы, DTO и
  типизированные ошибки. Deep import во внутренние пакеты соседнего
  модуля запрещён. Публикация события выполняется через порт
  `auditmanager.shared.ports`, реализация подключается в `bootstrap`;
  импортировать `jobs` или `operations` ради публикации события не
  требуется и запрещено.
- **R-04.** Допустимые межмодульные рёбра образуют ациклический граф:

| Модуль | Может импортировать |
| --- | --- |
| `shared` | ничего из `auditmanager` |
| `access`, `documents`, `storage`, `operations` | `shared` |
| `ingest` | `shared`, `documents`, `storage` |
| `findings`, `comparison` | `shared`, `documents`, `storage` |
| `analysis` | `shared`, `storage` |
| `decisions` | `shared`, `findings` |
| `jobs` | `shared`, `documents`, `storage`, `analysis` |
| `workers` | `shared`, `jobs` |
| `export` | `shared`, `documents`, `storage`, `findings`, `decisions` |
| `api` | публичный API любого модуля выше |
| `bootstrap` | любой модуль, включая `adapters` |

- **R-05.** `src/**` не импортирует `backend`, `audit_worker`, `scripts`,
  `experiments`, `norms`, `tests`. Единственное исключение —
  `src/auditmanager/analysis/adapters/legacy_bridge/**`: именованный
  compatibility mode с метрикой, владельцем и датой удаления,
  зарегистрированный в `EXCEPTIONS.md`. Запрет не распространяется на
  каталог `tests` внутри модулей нового контура: он является частью
  модуля.
- **R-06.** Действующий контур не импортирует `auditmanager`. Обратная
  связь возможна только по HTTP или через route gate и открывается
  отдельной integration task.
- **R-07.** `contracts/**` — листовой пакет: он не импортирует ни один из
  контуров, но импортируется обоими.
- **R-08.** `web/**` не содержит Python, `src/**` не содержит
  фронтенд-кода. Единственная связь — сгенерированный из OpenAPI клиент.
- **R-09.** В `src/**` и `web/**` запрещены мутации `sys.path`. Пакет
  устанавливается в окружение, тесты запускаются от установленного
  дистрибутива.
- **R-10.** Окружение читается только в
  `src/auditmanager/bootstrap/settings.py` и передаётся дальше
  типизированным объектом. `os.environ` в остальных файлах `src/**`
  запрещён.
- **R-11.** Новый контур не пишет в дерево исходников. Запись выполняют
  только адаптеры и только по пути из настроек; целевой путь проверяется
  на принадлежность каталогу данных, а не каталогу репозитория. Вне
  `bootstrap/settings.py` и `*/adapters/**` запрещены литералы файловых
  путей и вызовы записи: `open`, `os.makedirs`, `os.remove`, `os.rename`,
  `shutil.*`, `tempfile.*`, `Path.open`, `Path.write_text`,
  `Path.write_bytes`, `Path.mkdir`. Список вызовов не исчерпывающий и
  конкретизируется `W1-OPS-02`. Runtime-состояние живёт в PostgreSQL, S3
  или `var/**`.
- **R-12.** Тесты нового контура лежат в `src/auditmanager/<module>/tests/**`
  и принадлежат владельцу модуля. Кассеты и fixtures в репозитории —
  только синтетические или обезличенные.
- **R-13.** Имя каталога верхнего уровня не совпадает с именем модуля
  stdlib и с именем существующего пакета репозитория.
- **R-14.** Каталоги `utils`, `common`, `helpers`, `base` без
  подтверждённой семантики не создаются ни на одном уровне `src/**`.
  `shared` содержит только явно названные подпакеты.
- **R-15.** `migration/**` — единственная зона с двусторонним доступом:
  ей разрешено импортировать оба контура, потому что её работа —
  сопоставлять их. Пакет `migration` не импортируется из `src/**` и
  `backend/**`, не входит в production-bundle и удаляется вместе с
  завершением миграции в W5.

### 4.4. Composition root

Composition root нового контура — `src/auditmanager/bootstrap/`:

- `settings.py` — типизированная конфигурация, единственное место чтения
  окружения и файлов конфигурации;
- `container.py` — явная сборка объектного графа; service locator и
  глобальные синглтоны запрещены;
- `asgi.py` — фабрика `create_app()`; приложение не собирается на импорте
  модуля;
- `entrypoints/` — процессы, запускаемые как
  `python -m auditmanager.bootstrap.entrypoints.<name>`.

Роутеры регистрируются из декларативного реестра. Условная регистрация
допустима только как значение настройки с именованным флагом, владельцем и
датой удаления; импорт внутри `if` запрещён. Файлы `bootstrap/**` не
редактируются lane-задачей: изменение composition root — предмет
integration task, и это правило не отменяется режимом worktree. Четыре
composition root действующего контура из §1.1 остаются на своих местах и
перечислены в таблице hotspots §4.2.

### 4.5. Реестр контрактов

| Семейство | Содержимое | Lane | Задача-владелец | Состояние |
| --- | --- | --- | --- | --- |
| `contracts/http/v1/**` | снимок HTTP-поверхности действующего контура | ENG | задача волны, назначенная ENG | заморожен, характеризация |
| `contracts/agent_stream/v1/**` | gRPC-контур удалённых воркеров | JOB | integration task волны | действует |
| `contracts/worker_certificate/v1/**` | сертификаты воркеров | OPS | integration task волны | действует |
| `contracts/domain/v1/**` | идентификаторы, состояния, ошибки | ARC | W0-ARC-02 | создаётся |
| `contracts/api/v1/**` | OpenAPI нового control plane | API | W1-API-01 | создаётся |
| `contracts/packages/v1/**` | input/result package движка анализа | ENG | W1-ENG-01 по ADR-0012 | создаётся |
| `contracts/*.py`, `contracts/*/__init__.py`, `contracts/*/README.md` | инициализация пакета контрактов | ARC | W0-ARC-02 | действует |

Правила: семейство контракта — каталог, версия — подкаталог `v<major>`; у
каждого семейства один владелец версии; consumer не меняет schema
provider'а в своей задаче (P-04); неизвестная major-версия отклоняется явно.
Правила версионирования и таблица владельцев живут в `contracts/README.md`
под владением ARC. Каталог `contracts/http/v1/**` остаётся снимком
legacy-поверхности и новым контуром не переиспользуется.

### 4.6. Механическая проверка границ

Правила R-01…R-15 обязаны проверяться автоматически. Минимальный набор
проверок:

| Проверка | Что закрывает | Владелец |
| --- | --- | --- |
| C-1 слои внутри модуля | R-01, R-02 | W1-OPS-02 |
| C-2 граф межмодульных рёбер и запрет deep import | R-03, R-04 | W1-OPS-02 |
| C-3 запрет legacy-импортов из `src/**` и учёт исключений | R-05, R-06, R-07, R-15 | W1-OPS-02 |
| C-4 AST-проверка `sys.path`, `os.environ`, записи в файловую систему | R-09, R-10, R-11 | W1-OPS-02 |
| C-5 границы слоёв и slices web | R-08 | W1-WEB-01 |
| C-6 имена каталогов верхнего уровня и запрет `utils`-каталогов | R-13, R-14 | W1-OPS-02 |
| C-7 непересечение зон владения из §4.2 | §4.2 | W1-OPS-02 |
| C-8 машиночитаемость реестра исключений | §4.6 | W1-OPS-02 |

Проверки выполняются отдельным job в `.github/workflows/**`, не
объединённым с `regression-gate` и без `continue-on-error`. Блокирующая
область job — `src/**`, `web/**`, `contracts/**` и `migration/**`. Корень
репозитория и legacy-каталоги job читает только ради правил R-06 и R-13;
прочие правила к ним не применяются. Поэтому блокирующий режим нового
контура не зависит от состояния регресс-гейта.

Обход правила оформляется записью в `EXCEPTIONS.md`. Чтобы проверка C-8
была выполнима, запись обязана иметь машиночитаемый заголовок с полями
`id`, `principle`, `rule`, `owner`, `expires`, `closing_task`; формат
фиксирует `W1-OPS-02`. Исключение без даты истечения считается новой
архитектурой и требует ADR.

### 4.7. Оставшиеся развилки

- **D-1.** `src/auditmanager/**` против плоского `auditmanager/**` в корне.
  Рекомендуется src-layout: он исключает случайный импорт из рабочего
  каталога и делает установку пакета обязательной, что и убирает
  `sys.path`-мутации. До закрытия развилки конфигурация checker не
  фиксируется, поэтому принятие ADR закрывает её первым действием.
- **D-2.** Тесты нового контура рядом с модулем (рекомендуется) против
  общего каталога `tests/`. Выбор влияет на `pytest.ini` — hotspot
  `W1-INT-00`.
- **D-3.** Пакетный менеджер и lockfile web-приложения. Решает
  `W1-WEB-01`; ADR фиксирует только то, что lockfile является hotspot.
- **D-4.** Владельцы модулей `comparison` и `export` не назначаются до
  волны, которая их открывает.

## 5. Контракты и данные

- **Source of truth.** Раскладка, зоны владения и правила импорта — этот
  ADR. Словарь, идентификаторы, состояния и ошибки — domain contract v1
  (`W0-ARC-02`, ADR-0018). HTTP-контракт нового контура — OpenAPI
  `W1-API-01`. Схема PostgreSQL — `db/migrations` под владением
  `W1-META-02`.
- **ID и FK.** Решение не вводит идентификаторов. Типы идентификаторов как
  value objects живут в `src/auditmanager/shared/**` и определяются
  domain contract v1; область уникальности задаёт он же.
- **Версии контрактов.** `contracts/<семейство>/v<major>/`; повышение
  major — отдельная integration task; аддитивное необязательное поле
  версию не повышает; неизвестная major-версия отклоняется явно.
- **State machine.** Бизнес-состояний решение не описывает. Единственный
  жизненный цикл — состояние зоны владения:
  `зарезервирована → открыта задачей → под проверкой границ → закрыта
  при retirement`. Переход «открыта» выполняет только задача из §4.2.
- **Consistency и transaction boundary.** Не применимо: решение не
  выполняет операций над данными.
- **Idempotency и retry.** Создание skeleton идемпотентно: повторный
  запуск `W1-INT-00` не создаёт второй корень и не переносит существующие
  файлы.
- **Retention и удаление.** Legacy-каталоги удаляются только в W5 после
  observation и restore drill (P-11). Каталог `var/**` не версионируется,
  канонической копией не является и восстанавливается из PostgreSQL и S3
  (P-12).

## 6. Последствия

### Положительные

- задача волны получает заполнимые `allowed_paths` и
  `forbidden_shared_files`, а конфликт двух исполнителей становится
  видимым до кода;
- `W1-OPS-02` получает предмет проверки, а G1 — измеримый критерий
  «checker не находит cross-module imports»;
- новый код физически отделён от legacy, поэтому его объём, покрытие и
  retirement считаются по каталогу;
- composition root нового контура не совпадает ни с одной из четырёх
  точек сборки legacy, и владельцы не конкурируют;
- установка дистрибутива снимает потребность в `sys.path`-мутациях в
  новом коде.

### Отрицательные и долг

- две раскладки сосуществуют до W5; читателю репозитория нужно знать, что
  каталог `backend/` — действующий контур, а `src/` — новый;
- появляется второй набор зависимостей и вторая команда запуска тестов;
- 359 существующих `sys.path`-мутаций и обратные импорты legacy этим
  решением не устраняются: они остаются зафиксированным долгом и
  закрываются задачами волн 2–5;
- риск «мёртвого каталога», если волна не доводит вертикальный сценарий
  до primary; ответ — критерий пересмотра §11.

### Новые эксплуатационные обязанности

- метрики и алерты: счётчик вызовов `legacy_bridge` по каждому адаптеру и
  срок жизни каждого исключения из `EXCEPTIONS.md`; рост числа исключений
  разбирается на gate волны;
- backup и restore: `var/**` в резервную копию не включается и должен
  восстанавливаться перестроением; это проверяется до первого canary;
- capacity и cost: не изменяются;
- security rotation и audit: настройки и секреты читаются только в
  `bootstrap/settings.py`, поэтому ротация проверяется в одной точке.

## 7. План внедрения

```text
baseline → contract → shadow → parity → canary → primary → observation → cleanup
```

| Шаг | Владелец | Task ID | Feature mode | Критерий перехода |
| --- | --- | --- | --- | --- |
| baseline | ARC | W0-ARC-01 | нет | зафиксированы факты §1.1 и квитанция CP0 |
| contract | владелец программы | W0-DEC-01, W0-ARC-01 | нет | ADR-0002 ратифицирован, ADR-0006 переведён в `accepted`, D-1 закрыта |
| shadow | интегратор, OPS | W1-INT-00, W1-OPS-02 | checker блокирует `src/**`, legacy вне его области | skeleton и `pyproject.toml` созданы, C-1…C-8 запускаются в CI, negative test падает на подсаженном нарушении |
| parity | lanes W1 | W1-META-01…W1-WEB-04, W1-INT-01 | код работает на fixtures | walking skeleton проходит цепочку W1-INT-01 |
| canary | WEB, API | W1-WEB-04 и W2 | route gate `/next/*` | пилотный route отдаёт данные нового контура |
| primary | интегратор | W4 | cutover по маршрутам | маршрут переведён и обратим |
| observation | OPS | G4 | нет | окно наблюдения §5.1 roadmap выдержано |
| cleanup | ARC, ENG | W5 | нет | legacy-каталоги удалены после restore drill |

`W1-INT-00` — новая integration task, которую этот ADR добавляет в волну
1: она создаёт skeleton, `pyproject.toml`, `bootstrap/**` и правит
`pytest.ini`. Без неё лейны волны 1 не имеют корня, в который пишут, а
`W1-INT-01` собирает walking skeleton уже поверх готовых модулей.

## 8. Rollback и failure modes

| Failure mode | Detection | Stop condition | Recovery/Rollback |
| --- | --- | --- | --- |
| Новый модуль импортирует legacy напрямую | C-3 в CI | сборка задачи красная | импорт переносится в `legacy_bridge` либо оформляется исключение с датой |
| Установка дистрибутива ломает запуск действующего контура | smoke по четырём точкам входа §1.1 и регресс-гейт | новых падений больше, чем зафиксировано CP0 | удалить установку пакета; действующий контур от неё не зависит |
| Изменение раскладки ломает bundle выкатки | dry-run `scripts/deploy_audit_worker.py` и `production_source_guard.py` | несовпадение `fileset_sha256` | `BUNDLE_INCLUDE` не меняется этой задачей; откат коммита раскладки |
| Имя каталога затеняет модуль stdlib | C-6 | сборка красная | переименование до первого импорта |
| Две задачи меняют один hotspot | таблица §4.2 и ревью | вторая задача не стартует | изменение выносится в integration task |
| Skeleton создан, но lane не начата | отсутствие коммитов и тестов в зоне 60 дней | пересмотр §11 | каталог удаляется, имя остаётся зарезервированным |
| Checker превращается в вечный allowlist | C-8: рост числа записей и просроченные `expires` | исключение без даты истечения | запись отклоняется, требуется ADR |

## 9. Доказательства принятия

- contract tests: конфигурация C-1…C-8 запускается локально и в CI и
  падает на намеренно подсаженном нарушении каждого из правил R-01…R-15,
  для которых объявлена проверка;
- migration dry-run: `scripts/deploy_audit_worker.py` в режиме dry-run
  даёт неизменный состав bundle, `scripts/production_source_guard.py`
  проходит;
- semantic parity: не применима — решение не меняет поведение; вместо неё
  фиксируется, что число новых падений регресс-гейта не превышает
  зафиксированные квитанцией CP0 79 и не растёт;
- нагрузочный baseline: не применим, runtime-путь legacy не затронут;
- security review: подтверждено, что окружение и секреты нового контура
  читаются только в `bootstrap/settings.py`, а `var/**` не попадает в git;
- canary и restore drill: не применимы на этом шаге; выполняются на G2 и
  G4;
- непересечение зон §4.2 проверяется C-7, а раскладка `web/**` сверена с
  §2.1 ADR-0017 дословно.

## 10. Параллельные задачи

| Task ID | Владелец файлов/контракта | Frozen input | Output | Зависимости |
| --- | --- | --- | --- | --- |
| W0-ARC-01 | ARC: `docs/architecture/**` | ADR-0001–0005, roadmap §3.2 | этот ADR | W0-DEC-01 |
| W0-ARC-02 | ARC/API: `contracts/domain/v1/**` | ADR-0003, §4.5 | глоссарий и domain contract v1 | W0-ARC-01 |
| W1-INT-00 | интегратор волны, ARC/OPS: `pyproject.toml`, `bootstrap/**`, `pytest.ini` | §4.1, §4.4 | skeleton нового контура | W0-ARC-01 |
| W1-OPS-02 | OPS: `.github/workflows/**`, конфигурация checker | R-01…R-15 | C-1…C-8 в CI | W0-ARC-01, W1-INT-00 |
| W1-WEB-01 | WEB: `web/**` | §4.1, ADR-0017 §2.1 | Next shell, strict TS, route gates | W0-ARC-01 |
| W1-META-01 | META: `src/auditmanager/{documents,findings,decisions}/**` | domain contract v1 | value objects и state machines без I/O | W0-ARC-02, W1-INT-00 |
| W1-STO-01 | STO: `src/auditmanager/{storage,ingest}/**` | domain contract v1 | BlobRef/Manifest ports и validators | W0-ARC-02, W1-INT-00 |
| W1-JOB-01 | JOB: `src/auditmanager/{jobs,workers}/**` | ADR-0009 | durable state machine | W0-ADR-03, W1-INT-00 |
| W1-ENG-01 | ENG: зона ENG по §4.2 | ADR-0012, golden fixtures | legacy input/result adapter | W0-ADR-08, W0-BEH-02 |
| W1-AI-01 | AI: `src/auditmanager/analysis/adapters/{registry,replay}/**` | ADR-0013 | валидаторы PromptBundle, NormsSnapshot, AnalysisProfile | W0-ADR-04 |
| W1-API-01 | API: `src/auditmanager/{api,access}/**`, `contracts/api/v1/**` | domain contract v1, ADR-0010 | health, auth, error envelope и OpenAPI seed | W0-ARC-02, W0-ADR-06 |
| W1-MIG-01 | MIG: `migration/**` | inventory W0-DATA-01 | dry-run, journal, report framework | W0-DATA-01 |
| W1-INT-01 | интегратор: composition root и общий deployment | §4.1, §4.4 | walking skeleton | задачи W1 лейнов |

## 11. Критерии пересмотра

- ADR пересматривается, если `W0-DEC-01` отклоняет ADR-0002: модульный
  монолит является предпосылкой раскладки;
- если на G1 checker не может выразить правило R-03 или R-04 без списка
  исключений длиннее десяти записей — правило либо инструмент выбраны
  неверно;
- если через 60 дней после создания зоны в ней нет ни одного теста, зона
  закрывается; тот же срок используется в §8;
- если ADR-0002 разрешает выделить отдельный сервис, раскладка
  пересматривается новым ADR: этот документ описывает один
  развёртываемый control plane;
- после retirement legacy в W5 раскладка перестаёт быть двухконтурной, и
  §4.1 заменяется новым ADR со ссылкой `supersedes`.

## 12. Ссылки

- [ADR Bible](../ADR_BIBLE.md) — §3.3 bounded contexts, §5.1 слои, §6
  правила параллельной работы, §7 антипаттерны
- [ADR-0001](ADR-0001-hybrid-strangler-migration.md) — сосуществование
  контуров
- [ADR-0002](ADR-0002-modular-monolith-control-plane.md) — модульный
  монолит и связь модулей
- [ADR-0003](ADR-0003-contracts-and-data-ownership.md) — владельцы
  контрактов и anti-corruption adapter
- [ADR-0005](ADR-0005-parallel-delivery.md) — непересекающиеся каталоги
- [ADR-0016](ADR-0016-workspace-isolation.md) — hotspots, не зависящие от
  режима изоляции
- [ADR-0017](ADR-0017-frontend-route-strangler-and-fsd.md) — §2.1
  раскладка web
- [ADR-0018](ADR-0018-domain-contract-v1.md) — идентификаторы, состояния
  и ошибки нового контура
- [Roadmap](../HYBRID_REWRITE_ROADMAP.md) — §3.2 lanes, G0 и G1, волна 1
- [Реестр исключений](../EXCEPTIONS.md)
- [Квитанция CP0](../checkpoints/CP0.json) — исходное состояние и число
  новых падений
- ADR-0007, ADR-0008, ADR-0009, ADR-0010 и ADR-0012 на дату этого решения
  не написаны: номера зарезервированы реестром за задачами `W0-ADR-01`,
  `W0-ADR-02`, `W0-ADR-03`, `W0-ADR-06` и `W0-ADR-08`
- исходные измерения §1.1: рабочее дерево коммита `b3a56a3c`, 2026-08-28

### Внешние источники

| Источник | URL | Версия/редакция | Дата проверки | Кто проверил | На что опирается решение |
| --- | --- | --- | --- | --- | --- |
| import-linter | https://import-linter.readthedocs.io/en/stable/contract_types/ | 2.13 от 2026-07-03; типы `layers`, `forbidden`, `independence`, `protected`, `acyclic_siblings` подтверждены страницами раздела | 2026-08-28 | ARC | кандидат для C-1…C-3 |
| Steiger и плагин FSD | https://github.com/feature-sliced/steiger | `steiger` 0.6.0, `@feature-sliced/steiger-plugin` 0.7.0; статус beta | 2026-08-28 | ARC | кандидат для C-5; статус beta учитывается при выборе |
| eslint-plugin-boundaries | https://www.jsboundaries.dev/docs/ | npm 7.2.0 от 2026-08-09; сайт документации показывает 7.1.0, поэтому версия правил подтверждается только реестром npm | 2026-08-28 | ARC | кандидат для C-5: правило `boundaries/dependencies` |
| Python Packaging User Guide, src layout | https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/ | страница обновлена 2026-08-19 | 2026-08-28 | ARC | обоснование D-1 и R-09 |
| Next.js project structure | https://nextjs.org/docs/app/getting-started/project-structure | страница обновлена 2026-07-21; Next.js 16.3.3 | 2026-08-28 | ARC | конвенции каталога `app/` для `web/**` |
| Feature-Sliced Design | https://fsd.how/ | методология v2.1; слой Processes помечен deprecated | 2026-08-28 | ARC | слои `web/src/**` в редакции ADR-0017 |

Инструменты в таблице являются кандидатами и этим ADR не выбираются:
выбор, версию и дату проверки фиксирует `W1-OPS-02` для Python-контура и
`W1-WEB-01` для web-контура.
