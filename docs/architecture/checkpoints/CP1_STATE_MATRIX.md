# CP1 state matrix — safe legacy: redaction, auth, watchdog

**Статус:** заготовка формы (поток E, `WAVE_0_0_04_PLAN.md` §3). Это **не**
квитанция `CP1.json` и **не** verdict.<br>
**Составлена:** 2026-09-07<br>
**Составитель:** интегратор программы (единственный владелец этого файла)<br>
**P0_SOURCE_SHA** (на нём измерено состояние; ниже по тексту — «BASE»):
`c8475ed72a13a98566ddd9c7e6297ff232d40f62`<br>
**P0_PLANNING_SHA** (planning-docs: этот файл и task cards):
`7d9ddc65dbd2ef64a8e472299d7748254e2b566e`<br>
**CP1_BASE_SHA:** не определён — присваивается опубликованному `origin/main`
после завершения P0; именно на него встают потоки L, S и O.<br>
**Отношение к origin:** `origin/main@16414088`; ни `P0_SOURCE_SHA`, ни
`P0_PLANNING_SHA` в него не входят — fast-forward, divergence нет, **ничего из
этого не опубликовано**.<br>
**Политика окна:** [acceptance-rework/v1](../ACCEPTANCE_REWORK_POLICY_V1.md),
`enforced` с 2026-09-07.

Форма заполняется по правилам [checkpoints/README.md](README.md): фиксируется
**измеренное**, а не планируемое; отсутствующие данные помечаются явно с
указанием поставщика, а не выдаются за ноль.

## 0. Граница наблюдаемости (обязательная преамбула)

`production_state` во всех трёх строках — **не наблюдаем из этого окружения**.
Это измеренный факт, а не «пока не смотрели»:

| Проверка | Результат |
| --- | --- |
| хост | `adm1.hlab.kz` |
| `/home/coder/auditmanager/current` | отсутствует |
| `/home/coder/auditmanager/releases` | отсутствует |
| `/home/coder/auditmanager/**` | только `locks/` с двумя lock-файлами worker'ов от 2026-09-04 |
| слушатель на `:8081` / `:8080` | нет |
| systemd-юнит `auditmanager-backend.service` | не зарегистрирован |
| `crontab -l` (root) | пусто — cron-watchdog не установлен |

Следствие: ни одно поле `production_state` в CP1 нельзя заполнить работой в
этом репозитории. Поставщик данных — **legacy production operator**; без его
первички CP1 остаётся `captured` с честным `quality_gate: failed` по
production-части, а `authorizes_next_cutover` остаётся `false`.

`AGENTS.md` описывает чекаут как `/home/coder/projects/PDF-proverka`; фактически
работа идёт в `/root/projects/PDF-proverka/PDF-proverka`. Расхождение путей
внесено в раздел 4 как долг документации.

## 1. Матрица

### L — redaction (`W0-LOG-01`)

| Поле | Значение |
| --- | --- |
| **repo_state** | **Реализовано в репозитории.** `backend/app/core/action_log.py` (1100 строк) делит журнал на три канала: durable audit (`actions-*.jsonl`, фиксированная схема, allowlist `_AUDIT_FIELDS` — 16 полей с пределами длины), diagnostic (`diag-*.jsonl`, непроверенный ввод только после `_scrub()`), metrics (счётчики + гистограмма `dur_ms`, идентификаторов в labels нет). Deny-by-default реализован по **имени** поля для durable audit; value-redaction `_scrub()` применяется и к allowlist-полям как defence in depth. `ACTION_LOG_REDACTION` default `True`. |
| **production_state** | **не наблюдаем** (см. §0). Действует ли redaction на legacy production, каков ретеншн и разделены ли файлы — неизвестно. |
| **evidence** | `backend/app/core/action_log.py:24-39` (описание трёх каналов), `:144-164` (два независимых механизма), `:166-193` (allowlist), `:420-427`, `:444` (`_split_channels`), `:474-523` (метрики), `:532`; `backend/app/core/config.py:1208-1225` (default ON); тесты `backend/tests/test_action_log.py`, `tests/test_action_log_api.py`, `tests/test_ci_redaction.py`; `DATA_INVENTORY_V1.md` §7 (D-17, фактический allowlist с привязкой к строкам). |
| **gap** | (1) **Нет отдельного redaction contract как документа** — контракт существует только как комментарий в коде `action_log.py:144-164`; план L1 требует «инвентарь трёх каналов → redaction contract → deny-by-default тесты → runbook/rollback». (2) **Нет runbook/rollback** для L2. (3) **EXC-0002, компенсирующий контроль №4 не реализован**: требование «значение флага входит в production startup checks; старт в режиме `0` вне разбора инцидента отклоняется» не имеет реализации — startup-проверок в `backend/app/` на BASE нет вовсе (`grep ACTION_LOG_REDACTION` даёт только `action_log.py` и default в `config.py`). По преамбуле `EXCEPTIONS.md` неподтверждённый обязательный контроль означает fail-closed, а не «допустимо». (4) L2 (production-включение) не выполнялся. (5) `CP0.json.known_defects` всё ещё содержит «action log пишет query, текст исключения и traceback без redaction» — запись **устарела** (относится к CP0@`723310f6`); снятие — за интегратором, не за L. |
| **owner** | OPS/logging |
| **dependency** | P0 (публикация BASE). Внутри потока: contract → deny-by-default тесты → runbook/rollback. L2 идёт **первым** в production-очереди (`L2 → S2 → отдельная неделя → O2 → E2`). Не зависит от S и O. |
| **allowed_paths** | `backend/app/core/action_log.py`, `backend/tests/test_action_log.py`, `tests/test_action_log_api.py`, `tests/test_ci_redaction.py`, `docs/action_log.md`, новый `docs/architecture/REDACTION_CONTRACT_V1.md`, новый runbook в `docs/ops/`. |
| **shared_files** | `backend/app/core/config.py` (флаг + будущая startup-проверка) — **интегратор**; `docs/architecture/EXCEPTIONS.md` (EXC-0002) — **интегратор**. Изменения запрашиваются заявкой, поток их не коммитит. |
| **rollback_target** | *Репозиторный:* `CP1_BASE_SHA` — **не определён до публикации P0** (см. шапку). До публикации репозиторного отката у потока нет: `P0_SOURCE_SHA` не опубликован и точкой возврата для потоков не служит. *Runtime kill-switch:* `ACTION_LOG_REDACTION=0` — но это **EXC-0002**, постоянный аварийный режим с четырьмя компенсирующими контролями, а не штатный откат. *Production rollback target:* **не определён** — release-манифест недоступен; поставщик — legacy production operator. Пустое поле не заполняется нулём. |

### S — auth (`W0-SEC-03`)

| Поле | Значение |
| --- | --- |
| **repo_state** | **На BASE — выключено.** `PORTAL_AUTH_ENABLED` default `False` (`config.py:1156`, `portal_auth.py:118`), startup-политики нет, `/api/info` в списке неаутентифицированных маршрутов (`portal_auth.py:40,48`), потому что его дёргает cron-watchdog. **Кандидат кода существует вне BASE:** ветка `review/g0-sec03-code@2d624433` — startup policy fail-closed вне local/dev, `+191` строк в `portal_auth.py`, `+271` в новом `tests/test_portal_startup_policy.py`, всего 9 файлов / +694 −19. Кандидат стоит на **старой базе**: ahead 1, behind 16 от `origin/main`. |
| **production_state** | **не наблюдаем** (см. §0). Наблюдаемый факт из `EXC-0001` — default `false`; фактическое состояние деплоя, наличие private perimeter и список сотрудников не подтверждены. Provisioning receipt отсутствует. |
| **evidence** | `backend/app/core/config.py:1150-1157`, `backend/app/core/portal_auth.py:40,48,107,118,141,271`; `docs/architecture/EXCEPTIONS.md` (EXC-0001, active, expiry 2026-10-15); `CP0.json.open_exceptions[0]`; `git diff --stat origin/main...review/g0-sec03-code`; `docs/portal_auth.md`; контр-первичка по связке с watchdog — `docs/distributed_audit_workers/12f1_phaseb/staged/webapp-watchdog.sh:7,21,46`. |
| **gap** | (1) Кандидат `2d624433` **должен быть перенесён на BASE отдельным review** (план P0, шаг 4) — наличие кода не выдавать за rollout. (2) Provisioning не начат: нет списка 3–4 сотрудников, уникальных hashes (генерируются **вне репозитория и журналов**), защищённой выдачи и подтверждения входа. (3) Нет rotation/revocation и rollback rehearsal. (4) S2 не выполнялся; `EXC-0001` закрывается **фактом включения**, а не готовностью. (5) Взаимная блокировка с O: `/api/info` открыт именно ради watchdog — включение auth без миграции watchdog либо ломает watchdog, либо оставляет дыру. Оговорка о первичке: связку подтверждают комментарий `portal_auth.py:40` и наблюдавшиеся инциденты, но **не** версионированный `staged/webapp-watchdog.sh` — он `/api/info` не запрашивает (строка O, gap 1). Связка принимается как действующая по fail-closed. |
| **owner** | OPS/API + владелец доступа |
| **dependency** | P0 → перенос кандидата на BASE → provisioning → S2. S2 идёт **вторым**, строго после наблюдения L2. Шаг 4 `W0-OPS-02` (O2) **не в одну календарную неделю** с S2 (`ADR-0010:419`, план §3). Контракт `/api/info` — согласование с O обязательно. |
| **allowed_paths** | `backend/app/core/portal_auth.py`, `tests/test_portal_auth.py`, `tests/test_portal_startup_policy.py`, `docs/portal_auth.md`, `.env.example`. |
| **shared_files** | `backend/app/main.py` (+19 в кандидате), `backend/app/core/config.py` (+10), `.github/workflows/ci.yml` (+7), `conftest.py` (+32), `docs/architecture/QUALITY_RUNTIME_CONTRACT_V1.md` (+17), `docs/architecture/EXCEPTIONS.md` (EXC-0001) — **все интегратора**. Перенос кандидата на BASE выполняет интегратор либо поток по явной заявке с пофайловым diff. |
| **rollback_target** | *Репозиторный:* `CP1_BASE_SHA` — **не определён до публикации P0** (см. шапку). До публикации репозиторного отката у потока нет: `P0_SOURCE_SHA` не опубликован и точкой возврата для потоков не служит. *Runtime:* `PORTAL_AUTH_ENABLED=false` — но откат в `false` **восстанавливает EXC-0001**, поэтому допустим только как аварийная мера с записью, а не как штатное состояние после S2. *Production rollback target:* **не определён**; поставщик — legacy production operator. Требование `EXC-0001`: rollback проверяется runbook'ом до включения, а не после. |

### O — watchdog (`W0-OPS-02`, шаги 1–3)

| Поле | Значение |
| --- | --- |
| **repo_state** | **Не начато; действующий watchdog не версионируется.** Health endpoint — `/api/info` (`main.py:346`), явно fail-soft («обязан отвечать всегда», `main.py:329,363`). **Отдельных liveness/readiness endpoint'ов нет** — `/healthz`, `/readyz`, `/livez` в `backend/app/` отсутствуют; существующие `/health` к watchdog отношения не имеют (`projects_v2_shadow.py:66`, регулярка подавления шумных маршрутов `action_log.py:647`, `/api/lms/health` в тесте). Kill-семантика **документом не зафиксирована, и два источника противоречат друг другу**: комментарии шести модулей описывают watchdog, убивающий бэкенд при неответе `/api/info` > 5 с, а единственный версионированный скрипт этого не делает (gap 1). Сам скрипт лежит как **staged-копия внутри docs**: `docs/distributed_audit_workers/12f1_phaseb/staged/webapp-watchdog.sh` (порт 8081, юнит `auditmanager-backend.service`, аварийный бэкенд, cooldown-файлы, ссылки на `$HOME/projects/PDF-proverka`). |
| **production_state** | **не наблюдаем** (см. §0): cron пуст, юнита нет, `:8081` закрыт. Какая именно ревизия watchdog работает на production и совпадает ли она со staged-копией — **неизвестно**. |
| **evidence** | `backend/app/main.py:117,329,346-363,381`; `backend/app/core/portal_auth.py:40,48`; `backend/app/core/action_log.py:642`; `backend/app/api/routers/action_log.py:6`; `backend/app/api/routers/audit.py:252`; `backend/app/pipeline/manager.py:2569,5172`; `backend/app/services/distributed_workers/database.py:10`; `docs/distributed_audit_workers/12f1_phaseb/staged/webapp-watchdog.sh`; `CP0.json.known_defects` — «инфраструктура (nginx, TLS, cron-watchdog) не версионируется»; `docs/supervision_oom.md`. |
| **gap** | (1) **Версионированный скрипт противоречит комментариям кода и, скорее всего, не является рабочей ревизией.** `staged/webapp-watchdog.sh` к `/api/info` не обращается вовсе: `API_URL` присваивается на строке 7 и **нигде не используется**, `curl` отсутствует, живость меряется `port_open()` — `ss -ltn | grep 127.0.0.1:8081` (строки 21, 46). Бэкенд он также **не убивает**: `kill -0` (строка 32) — проба живости fallback-pid, `kill $FB` (строка 55) — совет, печатаемый человеку; порога 5 с нет. Его действия: поднять аварийный бэкенд при мёртвом `user@.service` и закрытом порте, `reset-failed` + `start` при `failed`, не трогать `inactive`. Противоположное поведение описано в шести модулях — `api/routers/action_log.py:6`, `services/distributed_workers/database.py:10`, `pipeline/manager.py:2569,5172`, `api/routers/audit.py:252`, `main.py:117`, `core/portal_auth.py:40`, — причём два из них ссылаются на **наблюдавшиеся инциденты** («вотчдог убивал живой бэкенд (инциденты 03.07)», `audit.py:252`; `main.py:117`). Комментарии описывают наблюдение, поэтому вывод fail-closed: staged-копия **не** источник истины о kill-семантике, рабочая ревизия — другая. Шаг 1 обязан достать её с хоста, а не переписать комментарии под staged-копию. (2) Шаг 1 — kill-семантика не зафиксирована документом. (3) Шаг 2 — liveness/readiness endpoint'ы отсутствуют. (4) Шаг 3 — shadow-прогон и измерение расхождений не выполнялись, shadow receipt отсутствует. (5) Действующая production-ревизия watchdog не идентифицирована: staged-копия под `docs/` не доказывает, что на хосте лежит она же — с учётом gap 1 это уже не гипотеза, а зафиксированное расхождение. (6) Инцидент 23.08.2026 (OOM убил сам `systemd --user`, портал лежал 12 ч 40 мин) обработан только внутри staged-скрипта — в архитектурных документах требования к супервизии супервизора нет. |
| **owner** | OPS |
| **dependency** | P0 → шаги 1–3 параллельно L и S (production не трогают). O2 (шаг 4: атомарное переключение + закрытие `/api/info`) идёт **последним** и **не в одну неделю с S2**. Жёсткая связка с S: `/api/info` останется неаутентифицированным, пока watchdog не переведён на новые зонды. Связку поддерживают комментарии и инциденты, но **не** версионированный скрипт (gap 1), поэтому она держится по fail-closed: allowlist не трогают в одиночку ни S, ни O — до идентификации рабочей ревизии (gap 5). |
| **allowed_paths** | новый `docs/ops/WATCHDOG_CONTRACT_V1.md`, новый модуль зондов `backend/app/api/routers/health.py`, `tests/test_health_probes.py`, `docs/supervision_oom.md`, версионируемая копия watchdog в `deploy/` или `scripts/server/`. |
| **shared_files** | `backend/app/main.py` (регистрация роутера зондов) и `backend/app/core/portal_auth.py:48` (allowlist маршрутов) — **интегратора**; пересекается с S. `docs/architecture/EXCEPTIONS.md` — интегратора. |
| **rollback_target** | *Репозиторный:* `CP1_BASE_SHA` — **не определён до публикации P0** (см. шапку). До публикации репозиторного отката у потока нет: `P0_SOURCE_SHA` не опубликован и точкой возврата для потоков не служит. *Runtime:* старый watchdog остаётся активен до шага 4 — это и есть откат для шагов 1–3. Для O2 откат — обратное переключение cron/юнита на прежнюю ревизию скрипта, **но её идентификатор неизвестен** (см. gap 4): до идентификации O2 не имеет проверяемого отката и стартовать не может. *Production rollback target:* **не определён**; поставщик — legacy production operator. |

### Решения владельца по потоку O (O-DEC-01…04)

Приняты 2026-09-07 и зафиксированы здесь как **вход** для окон потока O.
Реализация и переразбиение scope выполняются отдельными окнами, не этой
записью.

**O-DEC-01 — safe stop до probes.** Дефект `scripts/server/stop_server.sh`
против I-17 исправляется отдельным safety-window **до** реализации probes. Это
security/production bugfix, product-capability slot он **не расходует**.
Минимальный контракт safe stop: `pgrep -f` как источник сигнала удаляется;
`kill -0` означает только существование PID, а не принадлежность; start path
атомарно сохраняет PID, `/proc` start tick и command fingerprint; stop path
перед каждым TERM/KILL заново сверяет все признаки; отсутствие, недоступность
или несовпадение identity — fail-closed, сигнал не отправляется, команда
завершается диагностируемым отказом; `SIGTERM → bounded wait → SIGKILL`
допускается только для всё ещё доказанного процесса или группы; metadata
удаляется только после доказанной остановки либо отдельной процедурой очистки
stale record; PID reuse, foreign port owner, command mismatch и missing metadata
покрыты негативными тестами. Механика `process_start_time`, `pid_exists`,
`is_alive`, `live_command_fingerprint` уже существует в
`audit_worker/process_registry.py` — переиспользуется этот контракт либо общий
извлечённый helper; третья несовместимая проверка не создаётся.

**O-DEC-02 — bounded operational probes не расходуют capability slot.** Новые
probe endpoints разрешены как **ограниченная операционная поверхность без
бизнес-семантики**. Они **не являются product/business endpoints** и legacy
product-capability slot **не расходуют**. Границы исключения: только
loopback/private operational listener; fixed minimal response без путей,
конфигурации, customer data и секретов; ни writer, ни storage format, ни
domain/business response; endpoint не включается в публичный API/OpenAPI;
`/api/info` не закрывается до production shadow/cutover; любое расширение
ответа или публичной доступности требует **нового** решения о capability slot.

*Противоречие, которое обязано быть снято до freeze.* Roadmap относит
`W0-OPS-02` к классу задач, которые «не создают endpoint, writer или storage
format» ([HYBRID_REWRITE_ROADMAP.md](../HYBRID_REWRITE_ROADMAP.md), правила
capability slot). Формулировка обязана быть заменена на «не создают
product/business endpoint; могут добавить bounded operational probes в рамках
`W0-OPS-02`». Правка roadmap выполняется отдельным окном, не этой записью.

**O-DEC-03 — liveness вне event loop.** Liveness обязан обслуживаться вне
основного asyncio event loop. FastAPI-router внутри той же петли сам по себе
неприемлем: под насыщением он молчит вместе с `/api/info` и повторяет исходный
дефект. Целевая семантика: out-of-loop listener отвечает на liveness, пока жив
сам процесс и probe runtime; readiness вычисляется по heartbeat основного event
loop и возвращает not-ready при его устаревании; **readiness failure не является
разрешением убить процесс**; restart разрешается только отдельным контрактом
после shadow, безопасной process identity и подтверждённой production-ревизии
watchdog.

*Следствие для scope, которое здесь не исправляется.* Строка `allowed_paths`
потока O в [task cards](CP1_TASK_CARDS.md) называет
`backend/app/api/routers/health.py` — то есть ровно FastAPI-router внутри петли.
Этому решению она не удовлетворяет и подлежит переразбиению отдельными окнами
(`O-SAFE-STOP` / `O-PROBES`); scope потока этой записью не переписывается.

**O-DEC-04 — chaos только non-root.** Шесть signal/process chaos tests
выполняются отдельным job с non-root uid. Запуск под uid 0 не является evidence
и **не расходует acceptance attempt**, если был остановлен preflight-проверкой
окружения до старта полного гейта. Текущий локальный uid — 0, `ci_runtime_probe`
даёт `USER_IS_ROOT`, поэтому приёмка этих шести проверок в данном окружении
невозможна.

## 2. Пересечения, которые закреплены за интегратором

| Файл / артефакт | Кто хочет менять | Правило |
| --- | --- | --- |
| `backend/app/main.py` | S (startup policy), O (роутер зондов) | только интегратор; заявка с пофайловым diff |
| `backend/app/core/config.py` | S (auth), L (startup-проверка redaction) | только интегратор |
| `.github/workflows/ci.yml` | S (+7), уже изменён BASE (+6, `concurrency`) | только интегратор |
| `docs/architecture/EXCEPTIONS.md` | L (EXC-0002), S (EXC-0001) | только интегратор (правило плана §3) |
| `contracts/**`, `QUALITY_RUNTIME_CONTRACT_V1.md`, `DOMAIN_CONTRACT_V1.md` | S | только интегратор |
| `docs/architecture/checkpoints/CP1.json`, этот файл | E | только интегратор |
| `conftest.py` | S | только интегратор |

**Незакрытый долг реестра:** `EXC-0003` («необезличенные фикстуры
stage-comparison») существует только на ветке `review/0.0.04-debts@b0b79211` и
на BASE отсутствует. Свести его в `EXCEPTIONS.md` — задача интегратора,
отдельным коммитом, вне окон L/S/O.

## 3. Что CP1.json сможет заполнить, а что нет

| Поле квитанции | Источник | Готовность |
| --- | --- | --- |
| `checkpoint_id`, `checkpoint_status`, `verdict` | интегратор | после L2/S2/O2 |
| `quality_gate` | полный гейт + production-часть | **`failed`, пока production не наблюдаем** (§0). Красный чекпоинт фиксируется честно: README, «Красный чекпоинт — нормальное явление» |
| `source_commit`, `repository_parent` | git | доступно |
| `environment_profile` | локальный прогон | доступно |
| `test_receipt` | `python scripts/ci_regression_gate.py` | **не запускать до заморозки кандидата** (§2 политики) |
| `known_defects` | этот файл, раздел 1 «gap» | заполнено предварительно |
| `open_exceptions` | `EXCEPTIONS.md` + EXC-0003 | EXC-0001, EXC-0002 готовы; EXC-0003 не сведён |
| `production rollback targets` | release-манифест production | **отсутствует; поставщик — legacy production operator** |
| `cleanup_receipt` | интегратор | **пусто и обязано остаться пустым до observation**: правило 5 README (P-11) запрещает до наблюдения удалять rollback-копии, старые blob'ы, JSON-проекции и compatibility-флаги. `ACTION_LOG_REDACTION` сюда же — постоянный kill-switch, срока удаления не имеет |
| `authorizes_next_cutover` | отдельный gate | остаётся `false` |

## 4. Долги документации, замеченные при составлении

1. `AGENTS.md` называет чекаут `/home/coder/projects/PDF-proverka`; фактический —
   `/root/projects/PDF-proverka/PDF-proverka`.
2. `AGENTS.md` запрещает per-task worktrees, но в программе их шесть
   (`wt/adr`, `wt/phase1`, `wt/release004`, `wt/scope004`, `wt/sec03`, `wt/w1`),
   и `W0-WS-01` принят как пилот именно worktree-изоляции. Текст и практика
   разошлись — решение за владельцем `W0-DEC-02`.
3. `CP0.json.known_defects` содержит устаревшую запись про отсутствие redaction.
4. `/root/projects/PDF-proverka/.git` — пустой каталог, не репозиторий; он
   маскирует настоящий чекаут уровнем ниже.
