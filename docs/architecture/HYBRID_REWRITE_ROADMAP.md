# Roadmap гибридной миграции AuditManager

**Статус:** proposed — программный roadmap для утверждения; согласован по
терминам с ADR Bible и действующим планом хранения.<br>
**Редакция:** 2026-08-28.<br>
**Горизонт:** два несмешиваемых planning scenario: 11–19 календарных месяцев
для четырёх опытных специалистов либо 15–34 месяца для одного human integrator
с агентами. Это диапазоны до калибровки волнами 0–1, а не обещание срока;
решение фиксируется ADR-0015.

Roadmap организует уже согласованные работы по identity, S3 и PostgreSQL вместе
с новым frontend и изоляцией pipeline. Он не отменяет детальные этапы хранения:
они становятся capability lanes внутри общей гибридной миграции.

## 1. Целевой результат программы

- Next.js/React/TypeScript является основным пользовательским приложением;
- новый модульный control plane владеет API и бизнес-переходами;
- PostgreSQL является источником изменяемых метаданных;
- private S3 является источником долговечных байтов;
- jobs/runs имеют durable state, retries и observability;
- pipeline работает через versioned input/result package;
- legacy frontend, файловая каноника и прямые JSON writers отключены;
- отдельные stage алгоритмы могут оставаться Python-модулями, если соблюдают
  новый контракт и проходят quality gates.

## 2. Что не делаем

- не строим второй полностью независимый продукт до первого production slice;
- не переписываем весь pipeline до PostgreSQL/S3/control plane;
- не дробим новый backend на microservices заранее;
- не переносим старые каталоги как новую domain model;
- не обещаем feature parity по списку endpoint: parity определяется критическими
  пользовательскими маршрутами и бизнес-инвариантами;
- не удаляем legacy до observation и restore drill.

### 2.1. Ступенчатый бюджет изменений legacy

Полный capability freeze начинается на G1, когда contracts, skeleton и route
strangler уже способны принимать новую работу. До G1 действует sustainment
budget:

- максимум **1 активный product-capability slot на волну** — это измеримый
  pre-G1 gate;
- доля human integration capacity, затраченная на слот, еженедельно считается
  как `legacy integration hours / available integration hours`; denominator —
  зафиксированные в начале недели часы назначенного integrator за вычетом
  отпуска/on-call/обязательного support, numerator — task/time log capability
  slot; до появления observed baseline целевые 20% являются отчётной метрикой,
  а не stop gate;
- слот выбирается владельцем продукта на contract gate волны, имеет измеримый
  пользовательский результат, owner, deadline и парную target-contour task;
- список не ограничен только уже начатыми обязательствами, но новый слот не
  открывается, пока прежний не завершён или явно снят;
- capability slot не разрешает создавать новую файловую канонику, независимый
  writer или storage format: такая работа сразу проектируется в новом контуре;
- security/data-loss/production bugfix не расходует capability slot;
- characterization tests, response models, JSON Schema, snapshots, telemetry и
  backward-compatible validation существующего endpoint разрешены всегда, если
  golden test доказывает отсутствие изменения бизнес-поведения;
- `W0-LOG-01`, `W0-SEC-04` и `W0-OPS-02` относятся к этому классу: они не
  создают endpoint, writer или storage format и не меняют бизнес-семантику
  ответов, поэтому capability slot не расходуют;
- рефакторинг без characterization test и прямой пользы текущему обязательству
  не начинается.

После G1 новые legacy endpoint/capability равны **0**. Срочное исключение
регистрируется по §10 Bible и дополнительно доказывает, что новый контур не
может закрыть потребность в согласованный срок. Уже спроектированная функция не
считается автоматически разрешённой ни до, ни после G1.

## 3. Единицы планирования

### 3.1. Волна

Набор задач, использующих frozen contract versions. Внутри волны общие
контракты не меняются. Волна заканчивается integration gate и доказательствами.

### 3.2. Capability lane

Долгоживущая область владения с непересекающимися по умолчанию файлами:

| Lane | Ответственность | Целевая зона владения после ADR layout |
| --- | --- | --- |
| ARC | ADR, contracts, dependency rules | `docs/architecture/**`, contract registry |
| META | domain model, PostgreSQL, migrations | metadata modules, `db/migrations/**` |
| STO | ingest, blobs, manifests, S3/cache | storage/ingest modules |
| JOB | jobs, outbox, run state, worker control | job/orchestration modules |
| ENG | legacy bridge и analysis stages | analysis port/adapter, stage runners |
| AI | prompts, norms, routing, model calls, evals и cost | analysis profiles, prompt/norm registry, replay/evals |
| API | HTTP/BFF, auth integration | API composition и route contracts |
| WEB | Next.js, design system, routes | новое web-приложение |
| MIG | inventory, backfill, parity, reconciliation | migration tools/reports |
| OPS | CI, telemetry, infra, backup/DR | `infra/**`, runbooks, dashboards |

Фактические каталоги утверждает ADR target layout. До него таблица задаёт
логическое, а не физическое владение.

### 3.3. Integration task

Отдельная задача, которая единственная имеет право соединить несколько lanes,
изменить composition root, root lockfile или общий deployment manifest. Такой
код не прячется внутри одной implementation-задачи.

## 4. Правила независимой параллельной работы

1. В начале волны frozen contracts публикуются одним commit/change set.
2. Одна task редактирует одну ownership zone; shared files принадлежат
   интегратору.
3. Provider, consumer, contract tests и migration scanner работают параллельно
   на fixtures/mocks одной версии.
4. Task размером больше трёх инженерных дней дробится, если не является
   миграцией или integration gate.
5. Изменение общего контракта не совмещается с его реализацией несколькими
   исполнителями.
6. В одном checkout не запускаются две задачи на один hotspot.
7. Каждый change обратим флагом/route gate до завершения observation.
8. Незавершённый эксперимент не пишет в production root и не меняет defaults.
9. Merge-ready означает: локальная проверка, contract version, telemetry и
   отсутствие скрытых TODO на соседнюю задачу.
10. Новый WIP стартует только при свободной ownership zone и понятном integration
    slot; количество агентов само по себе не является причиной начать задачу.

### Шаблон task card

```text
task_id:
lane:
outcome:
parallel_safe: yes/no
frozen_inputs:
depends_on:
allowed_paths:
forbidden_shared_files:
non_goals:
deliverables:
verification:
telemetry:
feature_mode_or_rollback:
integration_task:
```

## 5. Граф зависимостей программы

```text
W0: constitution + behavior/data baselines
   │
   ├──────────────┬──────────────┬──────────────┬──────────────┐
   ▼              ▼              ▼              ▼              ▼
W1 META         W1 STO       W1 JOB/ENG/AI     W1 API/WEB     W1 OPS/MIG
   └──────────────┴──────────────┴──────────────┴──────────────┘
                                  │
                                  ▼
                    G1: platform walking skeleton
                                  │
                                  ▼
             W2: build + local/production-copy shadow slice
                                  │
                                  ▼
                  W2-INT-01/02 passed
                                  │
                                  ├───────────────┐
                                  │               │
                                  │      X1B: storage-facing minimum
                                  │      этапа 1Б (`projects_v2_primary`)
                                  │               │
                                  └───────┬───────┘
                                          ▼
                              W2-INT-03: opt-in canary
                                          │
                                          ▼
                              G2: production canary gate
                                  │
                 ┌────────────────┼────────────────┐
                 ▼                ▼                ▼
          W3 decisions/KB   W3 comparison     W3 export/admin
                 └────────────────┼────────────────┘
                                  ▼
                     G3: journey/contour parity
                                  │
                                  ▼
                  W4: PG/S3/Next primary cutovers
                                  │
                                  ▼
                 W5: pipeline ports + legacy retirement
```

`X1B` блокирует только публикацию `W2-INT-03`, а не parallel-safe разработку и
shadow `W2-INT-01/02`. Тем самым зависимость от незакрытого этапа 1Б видна в
графе и не превращает все задачи W1/W2 в последовательные.

### 5.1. Числовая политика gates

`W0-OPS-01` фиксирует по каждому критическому journey:

- `B_p95` — baseline P95 latency;
- `B_error` — долю технически неуспешных операций;
- `B_cost` — P95 фактической или явно помеченной estimated стоимости аудита;
- `B_quality` — baseline утверждённого expert-eval score vector (минимум
  precision/critical-recall или их доменные эквиваленты; одной acceptance rate
  недостаточно);
- `B_runs_7d` — медиану завершённых production-аудитов за 7 дней по последним
  восьми полным неделям.

Если baseline недоступен или метод измерения различается между контурами, gate
не считается пройденным. Следующая таблица — **черновик входных данных для
`W0-ADR-07`/ADR-0011**, а не действующая политика до принятия ADR:

| Показатель | Gate G2 | Gate G4 |
| --- | --- | --- |
| Потеря/неверная привязка данных | 0 | 0 |
| Contour invariant mismatch | 0 | 0 |
| P95 latency нового route | `≤ 1.20 × B_p95` | `≤ 1.10 × B_p95` либо принятый absolute SLO |
| Technical error rate | `≤ max(B_error, 1%)` | `≤ max(B_error, 0.5%)` |
| P95 cost/audit | `≤ 1.20 × B_cost` либо отдельный принятый budget | `≤ 1.10 × B_cost` либо отдельный принятый budget |
| Live analysis quality | каждая primary metric `≥ B_quality − 5 п.п.`, critical regression = 0 | каждая primary metric `≥ B_quality`, critical regression = 0 |
| Critical accessibility violations | 0 | 0 |
| Непрерывное observation | ≥ 7 суток и ≥ `max(10, ceil(B_runs_7d))` runs | ≥ 14 суток и ≥ `max(30, ceil(2 × B_runs_7d))` runs |

Gate G0 требует принять ADR-0011 до первого использующего budgets production
canary. Только значения из accepted ADR-0011 обязательны на G2/G4: он может
принять, изменить или отклонить этот черновик. После acceptance утверждённые
значения ADR-0011 подставляются в эту таблицу; с этого момента ссылки на §5.1
означают её актуальную нормативную редакцию. Устное решение на gate формулы не
меняет.

## 6. Волна 0. Конституция и доказательства текущего поведения

**Оценка:** сценарий A — 7–9 недель; default-сценарий B — 9–12 недель.<br>
**Fallback:** 10–14 недель, если один из review-batch распался либо provisioning
или внешнее решение добавило lead time.<br>
**Production behavior:** бизнес-семантика не меняется, кроме одного управляемого
legacy capability slot; security fail-closed hardening может включаться отдельным
runbook/change.

Цель — превратить неформализованное поведение в frozen contracts и измеримый
baseline. Это единственная волна с намеренно ограниченным параллелизмом на
архитектурных решениях.

### Параллельные задачи волны 0

| Task ID | Lane | Результат | Зависимости | Parallel-safe |
| --- | --- | --- | --- | --- |
| W0-DEC-01 | ARC | явная запись: Bible/ADR-0002 и сценарий исполнения ADR-0015 | нет | нет: решение владельца программы |
| W0-WS-01 | ARC/OPS | non-production pilot worktree isolation в disposable clone или по time-boxed exception | ADR-0005 | да, не меняет production/release default |
| W0-DEC-02 | ARC/OPS | принять shared checkout или hybrid worktrees по ADR-0016 evidence | W0-WS-01 | нет: процессное решение владельца |
| W0-ARC-01 | ARC | ADR-0006 target layout и dependency boundaries | W0-DEC-01, ADR-0001–0005 | нет: один владелец shared layout |
| W0-ARC-02 | ARC/API | glossary + domain contract v1: IDs, states, errors | ADR-0003 | после W0-ARC-01 |
| W0-BEH-01 | ENG | каталог 20–30 критических user journeys | нет | да |
| W0-BEH-02 | ENG/MIG | golden fixtures для deterministic contour upload/audit/findings/decisions | W0-BEH-01 | после W0-BEH-01; не вызывает live LLM |
| W0-LLM-01 | AI | inventory prompts/norms/routing/transports/model parameters и mutable sources | нет | да |
| W0-LLM-02 | AI/ENG | sanitized cassettes, replay и expert-eval `B_quality` одного critical journey | W0-LLM-01, W0-BEH-01 | после inventory; параллельно data/storage |
| W0-ADR-04 | AI/ARC | принять ADR-0013: analysis profile/replay/cost | W0-LLM-01, W0-LLM-02 | нет: один contract owner |
| W0-DATA-01 | MIG | inventory writers/readers/volumes/orphans | нет | да |
| W0-DATA-02 | MIG | mapping legacy identity → UID и ambiguity report | текущие identity rules | да |
| W0-LEG-01 | ARC/ENG | sustainment register: ≤1 active capability slot/волна; weekly human hours/available-hours и 20% reporting target; owner/deadline/target task | inventory текущего backlog | да |
| W0-OPS-01 | OPS | baseline: latency/errors/RSS/disk/job duration, runs/week и cost/audit | нет | да |
| W0-WEB-01 | WEB | route/feature inventory старого UI и deeplinks — [inventory v1](WEB_ROUTE_INVENTORY_V1.md) | нет | да |
| W0-SEC-01 | OPS/API | auth/data-flow threat model без изменения кода | нет | да |
| W0-SEC-02 | OPS/MIG | data classification inventory и draft retention matrix | W0-SEC-01, W0-DATA-01 | да после inventory |
| W0-SEC-03 | OPS/API | до 2026-10-15 закрыть EXC-0001: production auth preflight, staff credential provisioning, enabled/fail-closed вне local mode | W0-SEC-01 + подтверждённый список пользователей | security change, отдельный runbook/provisioning/rollback |
| W0-ADR-05 | ARC/OPS | ADR-0014: решение либо owner/deadline каждой незакрытой TTL | W0-SEC-02 | нет: business/legal decision |
| W0-ADR-01 | META/OPS | принять ADR-0007 PostgreSQL topology/migrations | W0-DATA-01 | нет: co-review `CB-W0-01` с W0-ADR-02; отдельный acceptance |
| W0-ADR-02 | STO/OPS | принять ADR-0008 S3 provider/bucket/RPO/RTO/C-07 | W0-DATA-01, W0-OPS-01 | нет: co-review `CB-W0-01` с W0-ADR-01; отдельный acceptance |
| W0-ADR-03 | JOB/ARC | принять ADR-0009 durable jobs/outbox | W0-BEH-01, W0-DATA-01 | да после inventory |
| W0-ADR-06 | API/OPS | принять ADR-0010 AuthN/AuthZ/object scope | W0-SEC-01 | нет: co-review `CB-W0-02` с W0-ADR-07; отдельный acceptance |
| W0-ADR-07 | OPS/ARC | принять ADR-0011 Observability/SLO и числовые budgets | W0-OPS-01 | нет: co-review `CB-W0-02` с W0-ADR-06; отдельный acceptance |
| W0-ADR-08 | ENG/ARC | принять ADR-0012 legacy analysis package protocol | W0-BEH-01, W0-LLM-01 | да после inventory |
| W0-ADR-09 | WEB/API | принять ADR-0017 typed pilot/FSD/route strangler | W0-WEB-01, W0-BEH-01 | да после route inventory |
| W0-LOG-01 | OPS | **P0.** redaction contract + разделение diagnostic logs / durable audit / metrics в действующем журнале | нет | да; P-17 contract-hardening, slot не расходует |
| W0-STD-01 | ARC/OPS | applicability matrix корпоративного стандарта: принять/адаптировать/отложить/отклонить/требует подтверждения → связанный ADR, причина, компенсирующий контроль, владелец проверки | нет | да; evidence для ADR, contract slot не занимает |
| W0-SEC-04 | OPS/API | inventory cookie-authenticated mutations, единая Origin/intent policy, автоматический coverage test, trusted proxy headers, поэтапный CSP | W0-SEC-01 | да; отдельно от W0-SEC-03, её срок не трогает |
| W0-OPS-02 | OPS | liveness/readiness контракт и миграция watchdog: фиксация действующего watchdog → новые endpoints → shadow → атомарное переключение → закрытие `/api/info` | нет | да; владелец kill-семантики — OPS, не security |
| W0-ARC-03 | ARC/OPS | frozen runtime/quality contract v1: clean-room профиль, совместимые зависимости, test lanes, timeout и baseline policy | ADR-0005, аудит 2026-08-28 | нет: один владелец shared contract |
| W0-ENG-02 | ENG | bounded lifecycle CPU/thread executors и stage runners без зависания shutdown | W0-ARC-03 | да; отдельный legacy hotspot, бизнес-семантику stages не меняет |
| W0-WEB-02 | WEB | disposition семи Vitest-падений и strict typecheck действующего UI без ослабления контрактов — [disposition](WEB_FRONTEND_DISPOSITION_W0-WEB-02.md) | W0-ARC-03, W0-WEB-01 | да; единственный владелец legacy frontend hotspots |
| W0-OPS-03 | OPS | runtime probe, timeout/JUnit harness, test-lane markers и provisioning norm corpus без правки shared workflow/defaults — [runbook](../ops/TEST_HARNESS_RUNBOOK.md) | W0-ARC-03 | да; готовит integration, но не включает enforce |
| W0-INT-01 | ARC/OPS | интегрировать dependency pins, test harness, frontend gate и CI; полный clean-room прогон и перевод regression gate в enforce | W0-ARC-03, W0-ENG-02, W0-WEB-02, W0-OPS-03 | нет: root dependencies, pytest и workflow принадлежат интегратору |

### Контур стабилизации quality baseline: аудит 2026-08-28

Контур добавлен после запуска приложения и всех доступных test lanes на текущем
`dev`. Он не объявляет ограничение конкретной песочницы дефектом продукта и не
подменяет `W0-OPS-01`: тот измеряет production behavior/SLO, а этот контур
доказывает воспроизводимость локальной и CI-проверки, требуемую Bible §5.7 и
Definition of Done п. 11.

Факт готовности файлов задачи и ADR-статус — разные вещи. На дату evidence
владелец сообщил о завершении `W0-DEC-01`, `W0-ARC-01` и `W0-ARC-02`, но Bible,
ADR-0002, ADR-0006, ADR-0015 и ADR-0018 в реестре всё ещё имеют статус
`proposed`. До появления явной acceptance-записи это не разрешает необратимый W1
production-код; задачи ниже допустимы как reversible contract-hardening и
подготовка evidence.

Зафиксированная evidence-квитанция:

- Uvicorn импортирует приложение и завершает startup; HTTP loopback текущей
  sandbox недоступен, поэтому endpoint smoke в ней не является доказательством;
- pytest собирает 7041 тест, из них два chaos-теста штатно исключены основным
  профилем;
- канонический `scripts/ci_regression_gate.py` в restricted sandbox не завершает
  прогон и не создаёт пригодный JUnit: полный-app `TestClient` блокируется там же,
  где bounded probe зависает на AnyIO worker-thread wake-up, а socket probe
  получает `PermissionError`. На том же exact dependency tuple вне sandbox
  минимальный `TestClient` вернул HTTP 200, а три сфокусированных
  TestClient/route/socket файла дали `30 passed`; поэтому это capability mismatch
  среды, а не доказанная dependency regression;
- fresh venv из текущих CI manifests собирается неполно: root/proto requirements
  не объявляют как минимум `passlib`, `pytest-asyncio`, `PyMuPDF`, `Pillow`,
  `openpyxl` и `grpcio-health-checking`. Проверенный полный freeze и правило его
  materialization зафиксированы в runtime/quality contract v1;
- после отделения environment-sensitive файлов backend-пакет дал
  `1567 passed / 10 skipped / 1 failed`; единственное assertion-падение уже
  присутствует в `ci_known_failures.txt` и не является новой регрессией;
- отдельно воспроизводятся незавершающиеся executor/stage lifecycle paths в
  `cpu_pool`, `block_context`, `debt_control`, `findings_verify`, post-review hook
  и section-optimization pipeline;
- полный frontend Vitest дал `395 passed / 7 failed`; lint и build зелёные,
  strict typecheck падает на `distributed-feature.js`;
- оба chaos-теста в текущей sandbox завершаются `PermissionError` на создании
  socket. Их логика должна проверяться на non-root runner с разрешённым loopback;
  sandbox-результат не заносится в product baseline;
- CI остаётся observe-first: regression и chaos имеют `continue-on-error`, а
  источник `norms/vault` не provisioned. Blind `--record` на такой машине
  запрещён.

#### W0-ARC-03 — runtime/quality contract v1

- **Outcome:** один versioned clean-room профиль фиксирует Python/OS/user mode,
  совместимый dependency set, наличие loopback/process capabilities, команды
  test lanes, per-test timeout, JUnit и правила baseline.
- **Frozen inputs:** `requirements.txt`, `pytest.ini`, frontend lockfile,
  `.github/workflows/ci.yml`, текущие 35 baseline entries и evidence выше.
- **Allowed paths:** `docs/architecture/**`; production/runtime/test defaults не
  меняются.
- **Forbidden shared files:** root dependencies/lockfiles, `pytest.ini`,
  `.github/workflows/**`, frontend manifests и composition roots.
- **Non-goals:** выбор новой backend/frontend архитектуры, исправление тестов,
  пересоздание known-failure baseline.
- **Deliverable:** [Quality/runtime contract v1](QUALITY_RUNTIME_CONTRACT_V1.md)
  с version/checksum входов, профилями `unit`, `contract`, `integration`,
  `network`, `chaos`, локальными командами и правилом обновления.
- **Verification:** профиль однозначно определяет, где socket/process тест
  обязан исполняться, где допустим явный skip и какой timeout превращает hang в
  диагностируемый failure с node ID.
- **Telemetry:** не применима к документационному change; сам contract фиксирует
  обязательные CI-метрики completion, duration, timeout и stale/missing report.
- **Rollback/integration:** документационный change обратим; frozen version
  потребляет `W0-INT-01`, несовместимое изменение создаёт v2.
- **ADR escalation:** если contract выбирает новый package/dependency manager,
  test framework или release topology как долгоживущий cross-context pattern,
  до реализации создаётся отдельный ADR; фиксация совместимых версий и команд
  существующих инструментов нового ADR не требует.
- **Execution receipt (2026-08-28):** задача завершена в разрешённом docs-only
  scope. Frozen Python receipt имеет SHA-256
  `557e95885700a44013febcc6559fa8ee278923507b71df8adba761e1e247f99c`;
  clean venv дал `7039/7041` collected, `pip check` без конфликтов,
  `86 passed` domain-contract и `30 passed` сфокусированных runtime-тестов.
  Non-root полный regression/enforce остаётся acceptance `W0-INT-01`, а не этой
  документационной задачи.

#### W0-ENG-02 — executor/stage lifecycle

- **Outcome:** завершение или ошибка stage освобождает thread/process resources;
  shutdown ограничен временем, повтор безопасен, зависший worker диагностируем.
- **Frozen inputs:** runtime/quality contract v1 и текущая бизнес-семантика stage
  outputs; assertion/golden expectations не переписываются этой задачей.
- **Allowed paths:** `backend/app/services/common/cpu_pool.py` и перечисленные в
  evidence lifecycle tests. Если исправление требует `backend/app/pipeline/manager.py`,
  composition root или иного legacy hotspot, работа останавливается и переносится
  в `W0-INT-01` с явным владельцем.
- **Forbidden shared files:** `requirements*.txt`, `pytest.ini`, workflow,
  composition roots и frontend hotspots.
- **Non-goals:** изменение порядка stages, result schema, retry/business policy и
  параллельный рефакторинг каждого зависшего сервиса.
- **Deliverables:** characterization tests для normal/error/cancel/shutdown,
  bounded cleanup и lifecycle telemetry без high-cardinality labels.
- **Verification:** перечисленные lifecycle tests завершаются в clean-room
  профиле под per-test timeout; после процесса не остаются executor/worker tasks.
- **Rollback/integration:** поведение за флагом не требуется, если меняется только
  cleanup; при изменении runtime scheduling нужен именованный compatibility mode
  с owner/expiry. Общие hotspots соединяет `W0-INT-01`.
- **Execution receipt (2026-08-31):** [квитанция](receipts/W0-ENG-02.json).
  Два дефекта воспроизведены измерением: shutdown возвращался за 0.00 с, а
  процесс не выходил и за 45 с при зависшем воркере; поздний `run()` поднимал
  новый пул уже после завершения бэкенда. После правки — 5.01 с и отсутствие
  воскрешения. Тесты 7 → 18, регресс-гейт без новых падений. Пять других
  lifecycle-путей из evidence в этом окружении не воспроизвелись — расхождение
  передано владельцу контракта, догадками не правилось.

#### W0-WEB-02 — legacy frontend contract disposition

- **Outcome:** каждое из семи Vitest-падений классифицировано как regression,
  устаревший characterization contract или незавершённая функция; решение имеет
  ссылку на journey/route inventory. Удаление проверки ради зелёного CI запрещено.
- **Frozen inputs:** route inventory `W0-WEB-01`, четыре падающих test files и
  действующий UI как baseline фактического поведения.
- **Allowed paths:** `frontend/static/js/app.js`,
  `frontend/static/js/distributed-feature.js`, связанные legacy CSS/HTML и четыре
  падающих test files; в этой задаче других владельцев этих hotspots нет.
- **Forbidden shared files:** `frontend/package*.json`, `frontend/tsconfig*.json`
  и CI workflow; ими владеет `W0-INT-01`.
- **Non-goals:** перенос route на Next.js, новый API и изменение OpenAPI.
- **Legacy budget:** characterization/test repair и восстановление уже
  утверждённого поведения slot не расходуют. Новая либо сознательно изменённая
  пользовательская семантика требует `W0-LEG-01` capability slot или отдельной
  target-contour task.
- **Verification:** полный Vitest, lint, strict typecheck и build зелёные; любое
  намеренное изменение поведения имеет golden/route disposition.
- **Telemetry:** число необъяснённых contract failures равно нулю; для
  восстановленного пользовательского поведения сохраняется существующая route
  telemetry либо явно фиксируется причина неприменимости.
- **Rollback/integration:** один обратимый legacy change; dependency/typecheck
  wiring соединяет `W0-INT-01`.
- **Execution receipt (2026-08-31), принято ЧАСТИЧНО:**
  [disposition](WEB_FRONTEND_DISPOSITION_W0-WEB-02.md). Регрессий ноль: все семь
  падений — устаревшие characterization contracts, у каждого назван
  коммит-причина. Найдено скрытое восьмое падение (тест краснел строкой выше).
  Vitest 403/403, lint/typecheck/build зелёные; RI-1 закрыт регрессионным
  тестом `frontend/tests/discussions_route_removal.test.js`.
  **Не закрыто:** буквальный `strict: true` даёт 69 ошибок, поэтому acceptance
  §11 контракта по этому пункту остаётся открытой. `tsconfig` и типизация
  модулей принадлежат `W0-INT-01`.

#### W0-OPS-03 — диагностируемый test harness

- **Outcome:** hang становится bounded failure, каждый lane отдаёт JUnit и
  machine-readable summary, отсутствие обязательного corpus/dependency является
  явной причиной отказа, а не сменой baseline.
- **Frozen inputs:** runtime/quality contract v1, текущий regression-gate и
  политика optional external sources.
- **Allowed paths:** `scripts/ci_regression_gate.py`, новые `scripts/ci_*`, узкие
  runtime-probe tests и OPS runbook. `.github/workflows/**`, `pytest.ini` и root
  dependency files запрещены до integration task.
- **Non-goals:** исправление business assertions, автоматическая перезапись
  baseline, включение платных provider calls и изменение production watchdog.
- **Deliverables:** minimal ASGI/TestClient probe, timeout/JUnit wrapper,
  классификация test lanes, проверка non-root/loopback и provisioning contract
  для `norms/vault`.
- **Verification:** намеренно зависший synthetic test завершается failure с node
  ID и свежим отчётом; старый JUnit не переиспользуется; missing norm corpus не
  разрешает `--record`.
- **Telemetry:** каждый lane публикует completion status, duration, tests
  seen/passed/failed/skipped, timeout node ID и причину environment skip.
- **Rollback/integration:** новые probes сначала observe-only; defaults и workflow
  меняет только `W0-INT-01`.
- **Execution receipt (2026-08-31), задача НЕ завершена:** часть 1 —
  [квитанция](receipts/W0-OPS-03-part1.json), часть 2 —
  [квитанция](receipts/W0-OPS-03-part2.json), эксплуатация —
  [runbook](../ops/TEST_HARNESS_RUNBOOK.md). Часть 2 закрыла §7 timeout harness,
  §8 JUnit/receipt и §3.3 provisioning; по §5 сделан только инвентарь объёма.
  Ревью нашло два блокирующих дефекта harness — публикацию секретов из
  командной строки (P-13) и неработающий cleanup process-group; оба исправлены
  отдельным review-fix коммитом с регрессионными тестами.
  **Не закрыто:** materialized markers. Размечено 13 функций — доли процента
  набора; остальные не имеют primary lane marker, что §5 объявляет inventory
  failure. Абсолютное число неразмеченных здесь намеренно не приводится: оно
  меняется с каждым новым тестом и устаревает быстрее документа. Актуальное
  даёт `python scripts/ci_lane_inventory.py`, снимок с отпечатком — в
  квитанции части 2. Сама разметка, регистрация маркера `network` в
  `pytest.ini` и включение enforce принадлежат `W0-INT-01`; до них
  `W0-OPS-03` считать завершённой нельзя.
- **Clean-room репетиция (2026-08-31):**
  [квитанция](receipts/W0-OPS-03-cleanroom-rehearsal.json). Прогон на
  непривилегированном пользователе с чистым чекаутом и изолированным run-root
  по §3.2. Впервые доказано наличие capabilities для `network` и `chaos`:
  probe проходит для всех пяти lanes. Репетиция НЕ является приёмкой — §11
  закрепляет её за `W0-INT-01`, — но снимает evidence, которое иначе пришлось
  бы добывать интегратору. Пять находок, из них **четыре** блокируют
  clean-room acceptance: манифесты не объявляют `pytest`; они же разрешаются в
  несогласованный набор, не воспроизводящий frozen receipt (27 эндпоинтов
  OpenAPI разошлись); три теста пишут в жёстко зашитый машинный путь вне
  репозитория, и §3.2 не объявляет переменную, которая это чинит; Node/npm не
  соответствуют пинам §3.1, из-за чего frontend gate не проверялся вовсе —
  непроверенный гейт не является пройденным.
- **Открытый пункт (F10):** у `scripts/ci_regression_gate.py` нет собственного
  wall-budget — на машине с зависающими тестами он не отказывает, а висит
  неопределённо долго. Это тот же класс отказа, ради которого §7 вводит
  бюджеты, но получил их только новый lane-раннер. Реализация бюджета —
  `W0-OPS-03` (файл в его allowed paths); подключение в CI и clean-room
  приёмка — `W0-INT-01`. Подробности в
  [квитанции части 2](receipts/W0-OPS-03-part2.json).

#### W0-INT-01 — clean-room integration и enforce

- **Outcome:** совместимый dependency set закреплён root-файлами, backend и
  frontend gates завершаются на fresh non-root runner, regression CI блокирует
  новые падения.
- **Frozen inputs:** outputs `W0-ENG-02`, `W0-WEB-02`, `W0-OPS-03` и
  runtime/quality contract v1.
- **Allowed shared paths:** `requirements*.txt`, `pytest.ini`,
  `.github/workflows/**`, `frontend/package*.json`, `frontend/tsconfig*.json` и
  только явно перечисленные composition/hotspot files из незакрытых provider
  tasks.
- **Ownership gate:** proposed ADR-0006 §4.2/§10 сейчас резервирует часть этих
  файлов за `W1-INT-00`, `W1-OPS-02` и `W1-WEB-02`. До root-правок architecture
  owner обязан согласовать в ADR-0006 ограниченное pre-G1 владение
  `W0-INT-01`; если ADR-0006 к тому времени accepted, изменение оформляется
  новым ADR, а не правкой задним числом. До reconciliation задача готовит только
  evidence и change plan.
- **Non-goals:** blind `ci_regression_gate.py --record`, объявление sandbox
  socket failure product regression, перевод chaos в blocking до отдельной
  stability evidence.
- **Acceptance:** fresh install проходит dependency check; minimal TestClient
  отвечает за bounded время; основной набор собирается и завершается; нет новых
  падений сверх разобранного baseline; каждая оставшаяся baseline-запись имеет
  owner, closing task и expiry/review date; frontend test/typecheck/lint/build
  зелёные; network/chaos реально стартуют на runner с loopback; regression
  `continue-on-error` удалён, chaos остаётся отдельным наблюдаемым job.
- **Telemetry:** CI хранит lane summaries/JUnit, время до первого failure,
  timeout count и age/owner оставшихся baseline entries.
- **Rollback:** до выполнения всех acceptance criteria observe-first сохраняется;
  изменение dependency/CI интегрируется одним revertable change set, предыдущий
  совместимый dependency set документирован.

Эта ветка добавляет один non-ADR shared contract slot (`W0-ARC-03`) и один
integration slot (`W0-INT-01`), но не увеличивает число owner-only ADR decisions.
До калибровки ADR-0015 planning delta учитывается как 2–3 integrator-days и риск
до одной календарной недели; ENG/WEB/OPS implementation после contract freeze
идут параллельно только в разных ownership zones. В сценарии A одновременно
допустимы три задачи при трёх фактических владельцах; в сценарии B запускаются не
более двух, третья ждёт свободный implementation slot.

### Очередь решений и календарь W0

Волна содержит 13 owner-only решений. Два заранее ограниченных review-batch
сокращают очередь до 11 shared contract slots:

- `CB-W0-01`: `W0-ADR-01/02` — совместная topology/data-ownership сессия;
- `CB-W0-02`: `W0-ADR-06/07` — совместная production-boundary/SLO сессия.

Batch не объединяет ADR: каждый документ принимается или возвращается отдельно,
а W1 зависит от соответствующего individual acceptance. Если пару нельзя
рассмотреть на общей evidence base, она распадается на два slots и W0 переходит
в fallback 10–14 недель. Inventories, проекты ADR и provisioning могут
готовиться параллельно; очередь acceptance остаётся WIP=1.

Review-slot открывается только после готовности обоих проектов batch и общей
evidence base; третья contract task в это время запрещена. Planning allowance
равен 2–3 owner-days на slot: 11 slots дают 22–33 последовательных owner-days.
Evidence/inventory (2–4 недели) перекрывается с ранними решениями, provisioning
и G0 reconciliation добавляют 1–2 недели с частичным перекрытием.

`W0-SEC-03` включает не только переключение конфигурации. До rollout оператор:

1. подтверждает список трёх-четырёх сотрудников и владельца lifecycle доступа;
2. генерирует уникальные credentials/hashes утверждённым способом, не помещая
   секреты в git, task tracker, manifest или logs;
3. передаёт начальные credentials по утверждённому защищённому каналу и получает
   подтверждение входа;
4. документирует rotation/revocation и проверяет login/logout, cookie/WS,
   liveness, fail-closed startup и rollback на production-like deployment.

Provisioning имеет собственный недельный lead-time внутри оценки W0. Дедлайн
исключения синхронизирован на 2026-10-15; отсутствие подтверждённого списка или
безопасного канала выдачи блокирует rollout, а не разрешает общий пароль.

### Порядок изменений, затрагивающих production

Волна содержит три изменения, которые касаются действующего production и имеют
потенциал самоблокировки: включение auth (риск локаута пользователей),
переключение watchdog (риск kill-петли), правка живого журнала. Формально это не
cutover'ы, но по последствиям они того же класса, поэтому исполняются
последовательно:

1. `W0-LOG-01` — первым. Единственное изменение без риска локаута или убийства
   процесса и единственное, которое уменьшает текущую экспозицию данных.
2. `W0-SEC-03` — вторым. Жёсткий срок и риск локаута; не конкурирует за внимание
   с шагом 4 `W0-OPS-02`.
3. `W0-OPS-02` — шаги 1–3 (фиксация watchdog, новые endpoints, shadow) идут
   параллельно чему угодно; **шаг 4, атомарное переключение, не выполняется в
   одну неделю с включением auth**.
4. `W0-SEC-04` — inventory и CSP в режиме Report-Only параллельны всему;
   enforcement Origin/intent включается последним, после зелёного coverage test.

Если review-нагрузка на интегратора не позволяет вести все четыре, в W1
переносится `W0-SEC-04`: у него единственного нет ни срока, ни текущей утечки.

### Decision timeout `W0-STD-01`

Корпоративный стандарт является рекомендательным входом, а не нормативным
источником. Матрица применимости содержит дату запроса подтверждения и
decision timeout, отсчитываемый от даты отправки запроса, а не от начала работы
над матрицей.

По истечении timeout неподтверждённые положения стандарта остаются справочным
evidence и не имеют нормативной силы; соответствующие ADR принимаются по
собственным основаниям. Поздний ответ владельца стандарта не переоткрывает
принятые ADR автоматически — изменение решения оформляется новым ADR по §9
Bible.

Timeout относится **только** к нормативной силе рекомендации. На runtime-политику
он не распространяется: требования P-14 остаются fail-closed независимо от
статуса подтверждения стандарта.

### Gate G0

- существуют явные записи `W0-DEC-01` и `W0-DEC-02`; Bible, ADR-0002 и новый
  workspace mode не считаются принятыми по факту старта кода;
- приняты ADR-0006–0013, ADR-0017 и ADR-0018 до соответствующих W1
  implementation tasks;
- для ADR-0014 либо принята числовая retention matrix, либо каждый незакрытый
  класс имеет owner/deadline и остаётся жёстким blocker production canary;
- определены источники истины и владельцы contracts;
- 20–30 критических journeys имеют deterministic fixtures, а хотя бы один
  LLM-journey проходит replay на записанных ответах;
- inventory не содержит неразобранной категории данных;
- baseline содержит P50/P95/MAX, error rate, RSS, disk и стоимость;
- `W0-SEC-03` закрыла EXC-0001 либо G0 не пройден;
- redaction contract действует, durable audit отделён от diagnostic logs, а
  чувствительные значения не попадают ни в один канал по умолчанию (`W0-LOG-01`);
- матрица `W0-STD-01` закрыта либо помечена истёкшим decision timeout; ни один
  ADR не ссылается на неподтверждённое положение стандарта как на обязательное;
- target layout даёт непересекающиеся ownership zones;
- `W0-INT-01` закрыта: clean-room regression завершается с пригодным JUnit,
  dependency/TestClient probe зелёный, frontend gate не имеет необъяснённых
  падений, а known-failure baseline не является вечным allowlist;
- legacy sustainment register соблюдает предел 1 active capability slot;
  human integration hours имеют явный denominator и еженедельный 20% reporting
  target, но до baseline не используются как stop gate; contract-hardening
  помечается отдельно;
- неизвестные/неоднозначные данные имеют статус, владельца и решение.

Если G0 не пройден, массовая генерация нового кода не начинается.

## 7. Волна 1. Независимые foundations и walking skeleton

**Оценка:** 6–10 недель.<br>
**Production behavior:** новые компоненты выключены или работают на fixtures;
до G1 может поставляться только оставшийся governed legacy capability slot.

Frozen inputs волны: domain contract v1, manifest v1/v2, OpenAPI seed, Job/Result
package v1, AnalysisProfile/replay contract v1, metric names v1.

### Integration task W1-INT-00

Открывает новый контур: `pyproject.toml`, каталоги модулей по ADR-0006 §4.1,
composition root `src/auditmanager/bootstrap/**` и правку `pytest.ini`.
Владелец — интегратор волны, lane ARC/OPS; зависимости — `W0-ARC-01` и
`W0-INT-01`.
Выполняется до задач лейнов волны: без неё модули не имеют корня, в
который пишут. `W1-INT-01` соединяет уже готовые модули и остаётся
замыкающей.

### Независимые задачи

| Task ID | Lane | Allowed ownership | Результат | Depends on |
| --- | --- | --- | --- | --- |
| W1-META-01 | META | metadata domain | value objects, aggregates и state machines без I/O | W0-ARC-02 |
| W1-META-02 | META | migrations | migration harness + начальная PostgreSQL schema | W0-ADR-01, W1-META-01 contract |
| W1-META-03 | META | metadata adapters | repository/UoW integration tests с реальной DB | W1-META-02 |
| W1-STO-01 | STO | storage domain | BlobRef/Manifest ports и validators | W0-ARC-02 |
| W1-STO-02 | STO | local adapter | streaming local adapter + contract suite | W1-STO-01 |
| W1-STO-03 | STO/OPS | S3 adapter isolated | multipart/verify/abort на test bucket/emulator | W0-ADR-02, W1-STO-01 |
| W1-JOB-01 | JOB | job domain | durable state machine, attempt/run semantics | W0-ADR-03 |
| W1-JOB-02 | JOB | outbox | outbox writer/dispatcher contract tests | W1-META-02, W1-JOB-01 |
| W1-ENG-01 | ENG | analysis bridge | legacy input/result adapter на golden fixture | W0-ADR-08, W0-BEH-02 |
| W1-AI-01 | AI | analysis registry | PromptBundle/NormsSnapshot/AnalysisProfile validators | W0-ADR-04 |
| W1-AI-02 | AI/ENG | replay adapter | cassette transport + ModelCallRecord contract tests | W0-LLM-02, W1-AI-01 |
| W1-API-01 | API | API seed | health/auth/error envelope + OpenAPI generation | W0-ARC-02, W0-ADR-06 |
| W1-API-02 | API | pilot contract | golden response master + response models ровно 8 distributed GET | W0-ADR-09, W1-API-01 |
| W1-WEB-01 | WEB | new web root | Next shell, strict TS, route gates | W0-ARC-01 |
| W1-WEB-02 | WEB | generated boundary | client/schemas 8 GET, mock adapter, legacy 3-file coverage + новый strict TS check | W1-API-02 contract |
| W1-WEB-03 | WEB | design system | primitives, tokens, loading/error/permission states | W1-WEB-01 |
| W1-WEB-04 | WEB | FSD pilot | `_pages/distributed-overview`; `audit-workers.js` и mutations вне scope | W1-WEB-02, W1-WEB-03, W0-ADR-09 |
| W1-MIG-01 | MIG | migration tools | dry-run/journal/report framework | W0-DATA-01 |
| W1-OPS-01 | OPS | telemetry | trace/log/metrics skeleton и local dashboards | W0-ADR-07 + metric names v1 |
| W1-OPS-02 | OPS | CI | dependency boundary, contract, migration и build gates | W0-ARC-01, W0-INT-01, W1-INT-00 |

Задачи внутри одного lane последовательны. Разные lanes параллельны только при
разных фактических владельцах и свободном WIP: в сценарии A `JOB/ENG/AI` имеют
одного pipeline/analysis engineer и между собой последовательны. W1-META-02
является единственным владельцем migration head; W1-API-01 — OpenAPI seed;
W1-WEB-02/W1-WEB-04 не редактируют OpenAPI. Последовательность
`W1-API-02 → W1-WEB-02 → W1-WEB-04` обязательна: генерация client до
типизированной response schema запрещена. W1-API-02 является разрешённым P-17
contract-hardening существующих GET и не расходует legacy capability slot.

### Integration task W1-INT-01

Соединить ровно один walking skeleton:

```text
Next demo route
  → generated client
  → control plane command
  → PostgreSQL metadata
  → local blob adapter
  → queued job/outbox
  → legacy engine fixture
  → validated result record
  → read model в UI
```

### Integration task W1-INT-02

Опубликовать внутренний read-only route `/next/distributed` через reverse proxy.
Он использует ровно 8 GET `/api/workers/distributed/*`; `audit-workers.js`,
worker/provider/job admin endpoints и retry/transfer/intake mutations не
переносятся. Route выключен по умолчанию, имеет telemetry и route-level rollback.
Это первый FSD/Next route; ждать массового W4 cutover не нужно.

### Gate G1

- skeleton выполняется в CI и локально одной документированной командой;
- schema/API/package compatibility tests зелёные;
- ни один domain module не читает filesystem/env/HTTP напрямую;
- DB/S3/job failures дают typed error и trace;
- production defaults не изменены;
- backend dependency checker не находит cross-module imports;
- Steiger/ESLint boundaries не находят deep/cross-layer imports, а pilot route
  проходит runtime schema validation и zero critical accessibility violations;
- pre-G1 legacy capability slot завершён или снят; с G1 budget новых legacy
  endpoint/capability = 0, contract-hardening остаётся разрешённым по P-17.

## 8. Волна 2. Первый production vertical slice

**Оценка:** 8–12 недель.<br>
**Сценарий:** `upload → version → start audit → progress → findings`.

Цель — как можно раньше получить узкий, но настоящий новый маршрут. Это важнее,
чем предварительно реализовать все таблицы и экраны.

Production-публикация W2-INT-03 разрешена только после storage-facing минимума
этапа 1Б. До этого те же компоненты работают на fixtures, production-копии или
в shadow без нового авторитетного writer. Бэкфилл исторических решений, полный
UI-переход и строгая Фаза E этапа 1 этот canary не блокируют.

### Contract tasks до параллельного старта

| Task ID | Владелец | Результат |
| --- | --- | --- |
| W2-C-01 | ARC/STO | IngestBundle/InputManifest contract freeze |
| W2-C-02 | ARC/JOB | Job/Attempt/Run/Progress/Result contract freeze |
| W2-C-03 | ARC/API | Project/Version/Audit/Findings OpenAPI freeze |
| W2-C-04 | ARC/MIG | contour parity: run correspondence, set `finding_uid`, page/sheet bindings, decisions и schema/checksum invariants |
| W2-C-05 | ARC/AI/ENG | analysis replay + live quality/cost policy без требования text equality |

### Параллельные implementation tasks

| Task ID | Lane | Результат | Не делает |
| --- | --- | --- | --- |
| W2-STO-01 | STO | streaming browser ingest, limits, checksum, staging | не публикует version напрямую |
| W2-STO-02 | STO | Storage Service publish/materialize + local/S3 shadow mode | не меняет metadata current |
| W2-META-01 | META | project/document/version commands и current transaction | не вызывает engine напрямую |
| W2-JOB-01 | JOB | submit/cancel/retry/progress durable flow | не парсит legacy result |
| W2-ENG-01 | ENG | реальный legacy engine adapter за package v1 | не пишет DB/S3 напрямую |
| W2-ENG-02 | ENG | validated findings result mapper | не меняет identity contract |
| W2-AI-01 | AI | immutable analysis profile + model call ledger shadow | не меняет prompts/routing без новой версии |
| W2-AI-02 | AI/MIG | replay parity report + live eval sample/cost report | не требует совпадения live текстов |
| W2-API-01 | API | upload/projects/audit/findings endpoints | не содержит domain rules |
| W2-WEB-01 | WEB | projects + upload routes на mock/generated client | не редактирует OpenAPI |
| W2-WEB-02 | WEB | audit progress + findings route | не читает legacy endpoint |
| W2-MIG-01 | MIG | legacy project/version read mapper и parity report | dry-run only |
| W2-OPS-01 | OPS | slice dashboards, alerts, runbook и canary routing | не меняет business state |
| W2-TEST-01 | ARC/QA | cross-provider contract/E2E tests | не реализует providers |

Разные lanes выполняются параллельно. Внутри lane порядок последовательный:
`W2-STO-01 → W2-STO-02`, `W2-ENG-01 → W2-ENG-02`,
`W2-AI-01 → W2-AI-02` и
`W2-WEB-01 → W2-WEB-02`. API, META, JOB, MIG, OPS и TEST не ждут завершения
чужой реализации, если их frozen contract уже опубликован.

### Integration tasks

- W2-INT-01: fixture/local end-to-end;
- W2-INT-02: shadow на production-копии данных;
- W2-INT-03: opt-in canary для ограниченного списка объектов/пользователей.

### Gate G2

- пользователь может пройти весь slice без ручной правки файлов;
- metadata и blobs имеют 100% checksum/FK/schema contour parity;
- progress переживает restart control plane;
- повтор upload/submit не создаёт дубль;
- один и тот же package + response cassettes дают replay parity post-LLM логики;
- live LLM results проходят утверждённую expert quality/cost policy; текстовое
  совпадение двух live-прогонов не требуется;
- error/rollback проверены на canary;
- выполнены числовые budgets и observation из §5.1;
- ADR-0010 и ADR-0014 приняты; `EXC-0001` закрыт задачей `W0-SEC-03`;
- legacy остаётся primary для остальных маршрутов.

## 9. Волна 3. Параллельная миграция независимых вертикальных сценариев

**Оценка:** 12–20 недель.<br>
**Production behavior:** новые маршруты включаются независимо.

После G2 работа максимально параллельна: каждый slice имеет собственный
contract-task, implementation tasks и route/data cutover.

| Slice | Основные задачи | Shared dependency | Может идти параллельно |
| --- | --- | --- | --- |
| W3-A Versions | создание/merge/history/current | Document/Version contract | со всеми ниже после freeze |
| W3-B Decisions/KB | finding UID, decision history, unresolved flow | Finding/Decision contract | W3-C–F |
| W3-C Comparison | sessions/pairs/artifacts/viewer | Version/Blob refs | W3-B, D, E, F |
| W3-D Export | registered export, auth, expiry, ZIP/Excel stream | Blob/Auth contract | W3-B, C, E, F |
| W3-E Worker admin | workers/jobs/attempts/capabilities | Job/Auth contract | W3-B, C, D, F |
| W3-F Discussions | threads/events/attachments | Identity/Auth contract | W3-B–E |
| W3-G Object/admin | objects, disciplines, quotas, roles | Auth/Object contract | W3-B–F |

Для каждого slice обязательны отдельные задачи:

1. `C` — frozen contract;
2. `META/STO/JOB` — provider changes в своих ownership zones;
3. `API` — endpoint/BFF;
4. `WEB` — route на generated client;
5. `MIG` — dry-run/backfill/parity;
6. `OPS` — metrics/runbook;
7. `INT` — canary и removal старого writer/route.

### Gate G3

- все критические journeys из W0 имеют новый маршрут или утверждённый legacy
  exception;
- новые expert decisions никогда не зависят от `latest`/`F-NNN`;
- historical backfill не имеет неучтённых orphans;
- comparison/export/attachments используют `blob_id`;
- Next routes покрывают сохранённые ссылки и permissions;
- каждый analysis run с LLM имеет AnalysisProfile/PromptBundle/NormsSnapshot и
  ModelCallRecord; live quality/cost не хуже утверждённого budget;
- каждый legacy fallback имеет счётчик, владельца и дату отключения.

## 10. Волна 4. Primary cutovers и эксплуатационная устойчивость

**Оценка:** 8–12 недель плюс observation.<br>
**Порядок:** данные и маршруты переключаются независимо, но по строгим гейтам.

### 4.1. Storage primary

- S3 ADR принят;
- new writes: local → S3 shadow → S3 canary → S3 primary;
- historical backfill/journal/checksum parity;
- materialize/Range/cache;
- backup/restore и controlled local cleanup.

### 4.2. Metadata primary

- JSON → PostgreSQL shadow-write;
- backfill и semantic parity;
- canary read/write по объекту;
- PostgreSQL primary;
- JSON projection только для rollback/legacy consumers;
- writer inventory подтверждает отсутствие обходов.

### 4.3. Next primary

- это массовое переключение оставшихся основных routes, а не первый запуск Next:
  внутренний pilot начинается в W1, independent canary routes — в W2/W3;
- routing canary по пользователю/объекту;
- performance/accessibility/error/cost budgets из §5.1;
- primary routes с быстрым route-level rollback;
- старый frontend становится read-only fallback на период observation.

### 4.4. Job primary

- durable queue/lease/heartbeat;
- restart/retry/cancel/drain tests;
- legacy engine вызывается только через package protocol;
- WebSocket/SSE является projection durable state.

### Gate G4

- production прошёл ≥14 суток и требуемое число runs из §5.1 без сброса окна;
- RPO/RTO подтверждены restore drill;
- SLO/alerts имеют владельцев;
- скрытых fallback и прямых writers нет;
- reconciliation backlog равен нулю либо имеет утверждённые exceptions;
- rollback drill выполнен после появления новых production-данных.

## 11. Волна 5. Pipeline ports и отключение наследия

**Оценка:** инкрементально после G4; 12+ недель, не блокирует пользу control plane.

### 5.1. Сначала единый stage contract

- stage registry вместо нескольких списков порядка;
- typed StageInput/StageOutput;
- artifact manifest и schema versions;
- deterministic resume rules;
- stage telemetry и error taxonomy.

### 5.2. Параллельный перенос stages

После freeze stage contract разные stage directories можно переносить
параллельно:

| Группа | Условие независимости |
| --- | --- |
| preparation/document graph | пишет только собственный output contract |
| crop/block context | получает blob/materialized path через port |
| block analysis | LLM/provider скрыт adapter contract |
| text analysis | не читает глобальный project path |
| findings merge/review | использует UID и immutable run inputs |
| norms | общий registry доступен через versioned read port |
| optimization | не меняет findings/decision history |
| export | читает опубликованные artifacts через Storage API |

Одна интеграционная задача обновляет registry/composition после завершения
группы. Несколько исполнителей не правят общий pipeline manager одновременно.

### 5.3. Retirement backlog

- legacy frontend routes;
- legacy API endpoints;
- direct filesystem/JSON writers;
- JSON canonical readers;
- `latest` как обязательный read source;
- compatibility aliases с нулевым usage;
- feature flags после observation;
- локальная rollback-replica после финального restore drill.

Именованные позиции backlog (пополняется по мере обнаружения):

| Позиция | Найдено | Состояние |
| --- | --- | --- |
| `/api/discussions` — роутер и JS-функции обсуждений | `aeb0b2f2` (2026-07-06) удалил вкладку «Проработка замечаний» из интерфейса, оставив бэкенд и JS как мёртвый код с пометкой «вычистить отдельно». 13 эндпоинтов живут без пользовательского входа | Полностью снять нельзя: `/resolve` ещё вызывается экспертной оценкой. Требуется сначала развязать эту зависимость, затем снимать остальное |

### Gate G5

- legacy consumer inventory равен нулю;
- production не зависит от старого application process для control plane;
- оставшиеся Python stages соответствуют новому engine contract;
- PostgreSQL/S3 полностью восстанавливаются;
- документация, runbooks и on-call описывают только целевую систему;
- старый код архивируется/удаляется отдельными recoverable changes.

## 12. Соответствие плану хранения 1→5

| Существующий этап | Где выполняется в roadmap |
| --- | --- |
| Этап 1: identity/integrity | W0 contracts, W1 domain, W2/W3 consumers |
| Этап 1Б: `projects_v2_primary` | обязательный gate до W2-INT-03; не ждёт всего UI/backfill |
| Этап 2: ingest/Storage/S3 | W1-STO, W2 first slice, W4 storage primary |
| Этап 3: PostgreSQL | W1-META, W2/W3 vertical schemas, W4 metadata primary |
| Этап 4: индексация | W3 query profiles, W4 measured indexes/read models |
| Этап 5: legacy off | W5 retirement |

Capability work может идти параллельно раньше своего production cutover.
Например, PostgreSQL schema и Next mock UI разрабатываются одновременно со
Storage local adapter, но новая production-публикация включается только после
соответствующего гейта.

## 13. Командная модель и WIP

Подробная развилка зафиксирована в
[ADR-0015](adr/ADR-0015-program-execution-model.md). Roadmap не предполагает
несуществующий найм молча.

### Сценарий A: staffed team

- backend/data engineer: META + часть API;
- storage/platform engineer: STO + OPS;
- backend/pipeline/analysis engineer: JOB + ENG + AI; AI является явной зоной
  ответственности, а задачи трёх lanes не считаются параллельными для этого
  человека;
- frontend engineer: WEB + generated client;
- функции architecture/integration/QA распределяются явно, а не считаются
  «общей ответственностью».

WIP:

- максимум 4 implementation tasks одновременно;
- максимум одна implementation task на фактического владельца; отдельные
  логические lanes сами по себе не создают дополнительную capacity;
- максимум 1 shared contract review-slot; только `CB-W0-01/02` могут включать
  по две заранее подготовленные ADR-задачи, все остальные slots — ровно одну;
- максимум 1 integration task;
- один migration head и один root lockfile owner на волну;
- не более одного production cutover одновременно.

Planning range: 11–19 календарных месяцев, 44–76 human engineer-months до
калибровки W0/W1.

### Сценарий B: один human integrator + agents

- максимум 1 shared contract review-slot; только `CB-W0-01/02` могут включать
  по две заранее подготовленные ADR-задачи, все остальные slots — ровно одну;
- максимум 1–2 implementation tasks одновременно и только в разных ownership
  zones;
- максимум 1 integration task; новый contract не открывается, пока integration
  slot занят;
- один human integrator утверждает contract, migration head, acceptance evidence
  и production cutover;
- агенты готовят provider/consumer/tests/docs, но не увеличивают integration
  capacity автоматически.

Planning range: 15–34 календарных месяца до калибровки. Если выделенные четыре
инженера не подтверждены, для capacity и обещаний используется сценарий B.
Добавление агентов без новой ownership zone увеличивает очередь интеграции, а не
скорость программы.

Оба сценария проходят одинаковые quality gates. Снижать scope волны разрешено;
ослаблять data/security/rollback gate из-за меньшей команды запрещено.

## 14. Метрики программы

### Скорость и качество

- lead time task/vertical slice;
- доля задач, реально завершённых без cross-owner правок;
- число contract changes внутри волны;
- merge/file ownership conflicts;
- escaped defects по slice;
- flaky tests и время CI;
- доля test lanes, завершившихся с пригодным JUnit, число timeout/hang и возраст
  каждой записи known-failure baseline;
- integration wait как доля lead time;
- rework после human review;
- human hours и agent/LLM/CI cost на завершённый slice.

### Миграция

- coverage нового read/write path;
- legacy fallback calls;
- semantic parity mismatches;
- reconciliation backlog;
- данные без UID/manifest/blob/FK;
- время rollback/restore;
- до G1: число legacy capability slots (`≤1`) и отдельно отчётная доля human
  integration capacity с явными numerator/denominator и целью 20%; после G1:
  новые legacy endpoints/capabilities = 0;
- legacy contract-hardening changes учитываются отдельно и должны иметь golden
  compatibility evidence;
- открытые legacy exceptions и просроченные expiry.

### Пользовательский результат

- P50/P95 открытия проекта, findings и PDF;
- upload success/retry;
- job queue/run duration и failure rate;
- потерянные/непривязанные решения;
- error rate нового и старого маршрута;
- число ручных операций на один аудит.

### Стоимость

- фактическая и estimated стоимость одного аудита, P50/P95;
- стоимость одного замечания, принятого экспертом;
- стоимость в валюте бюджета программы (включая ₽/аудит и ₽/принятое замечание,
  если бюджет ведётся в ₽) рядом с исходной валютой provider invoice и FX source;
- tokens/requests/storage/egress/compute по stage/provider;
- отклонение estimate от billing и доля вызовов без cost attribution;
- стоимость повторов, failed runs и replay/live eval отдельно.

## 15. Stop conditions

Волна или cutover останавливается, если:

- обнаружена потеря или неоднозначная привязка пользовательских данных;
- неизвестна версия contract/manifest/package;
- checksum/FK/semantic parity расходятся без объяснения;
- rollback или restore не воспроизводится;
- regression-gate не завершается за runtime/quality budget, не создаёт свежий
  JUnit либо minimal dependency/TestClient probe зависает;
- новая система требует прямого legacy path/DB/S3 обхода;
- error budget canary превышен;
- owner или on-call для новой критической зависимости отсутствует;
- до G1 legacy capability WIP превышает `1 slot`, либо после G1 появляется
  новая legacy capability без действующего исключения; отклонение отчётной
  метрики 20% само по себе до появления baseline не является stop condition;
- contract меняется быстрее, чем независимые tasks успевают интегрироваться.

## 16. Ближайшие следующие решения

До W1 implementation соответствующей области закрываются ADR-0006–0013,
ADR-0017 и ADR-0018 через явно назначенные W0 tasks из
[реестра ADR](ADR_INDEX.md).
ADR-0014 получает owner/deadline в W0 и обязан стать accepted до первого canary
на production data. ADR-0015/0016 закрывают capacity и workspace process на W0,
не подменяя product architecture. Первые поставки — walking skeleton W1-INT-01
и read-only Next pilot W1-INT-02, а не массовая генерация CRUD, экранов или
migrations.

## 17. Связанные документы

- [ADR Bible](ADR_BIBLE.md)
- [Реестр ADR](ADR_INDEX.md)
- [Разбор архитектурного ревью](REVIEW_DISPOSITION_2026-08-27.md)
- [Разбор архитектурного ревью R2](REVIEW_DISPOSITION_2026-08-27_R2.md)
- [Разбор архитектурного ревью R3](REVIEW_DISPOSITION_2026-08-27_R3.md)
- [План развития хранения](../data_storage_modernization/00_global_plan.md)
- [Кодовый план identity](../data_storage_modernization/01_storage_and_identity_code_plan.md)
- [Потоковый ingest](../data_storage_modernization/02_01_streaming_ingest.md)
- [Архитектурный аудит workers](../distributed_audit_workers/01_current_architecture_audit.md)
