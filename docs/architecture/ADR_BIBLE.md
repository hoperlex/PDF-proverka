# ADR Bible: архитектурная конституция AuditManager

**Статус:** proposed — базовая политика для явного утверждения задачей
`W0-DEC-01`; discovery, inventory и обратимые эксперименты разрешены, но
необратимый production-код, зависящий именно от этой политики, до утверждения не
стартует.<br>
**Редакция:** 2026-08-27.<br>
**Область:** backend, frontend, PostgreSQL, S3, pipeline, миграции,
инфраструктура и эксплуатация.

Этот документ фиксирует не конкретную реализацию каждой функции, а правила,
по которым принимаются архитектурные решения. После утверждения, если задача
предлагает отступить от обязательного правила, до кода нужен отдельный ADR с
причиной, альтернативами, рисками, сроком пересмотра и владельцем.

## 1. Архитектурная позиция

Проект развивается гибридно по модели Strangler:

1. действующее приложение остаётся рабочим продуктом и эталоном фактического
   поведения;
2. новый control plane пишется рядом и постепенно принимает владение данными,
   API и пользовательскими сценариями;
3. существующий pipeline временно работает как изолированный execution engine;
4. миграция выполняется вертикальными сценариями через shadow, parity, canary и
   обратимый cutover;
5. legacy отключается по потребителям, а не одной операцией «переписать всё».

Исходный код разрешено переиспользовать, если у модуля есть понятный контракт,
характеризационные тесты и отсутствует зависимость от legacy-пути как от
идентичности. Копирование больших сервисов в новый контур без изменения границ
не считается миграцией.

```text
Next.js / React / TypeScript
        │
        ▼
API/BFF нового control plane
        │
        ├── Metadata modules ── PostgreSQL
        ├── Storage module ──── private S3
        ├── Job orchestration ─ durable state/outbox
        └── Analysis port ───── legacy engine → новые stage runners
```

## 2. Что является источником истины

| Данные | Целевая каноника | Не является каноникой |
| --- | --- | --- |
| Документы, версии, запуски, findings, решения | PostgreSQL через Metadata API | JSON, путь, frontend state |
| Долговечные байты | private S3 через Storage API | локальный рабочий каталог, внешний URL |
| Входной комплект и результат run | versioned immutable manifest | содержимое `latest`, имя папки |
| Статус фоновой операции | durable job state | WebSocket, память процесса |
| Пользовательская сессия и полномочия | auth/session service | параметры UI, скрытая кнопка |
| Представления и индексы | перестраиваемые projections | второй независимый write model |
| Действующая бизнес-семантика миграции | утверждённый контракт + golden tests | предположение разработчика |
| Конфигурация анализа | immutable `AnalysisProfile`: routing, provider/model, параметры и ссылки на версии prompt/norm bundles | текущий `.env`, выбранная в UI модель, имя файла промпта |
| Промпты анализа | content-addressed versioned `PromptBundle` | редактируемая папка промптов без hash/version |
| Нормативная база | versioned `NormsSnapshot` с provenance, датой и checksum | изменяемый `norms_db.json` без снимка run |
| Доказательство LLM-вызова | immutable `ModelCallRecord` + приватный payload/artifact с checksum | логи, счётчик токенов в памяти, ожидание повторяемого ответа |

Одна сущность имеет одного владельца записи. Несколько read-представлений
разрешены; несколько независимых авторитетных writers запрещены.

## 3. Базовые понятия

### 3.1. Control plane

Новый модульный backend, который владеет пользователями, документами, версиями,
файлами, заданиями, статусами, результатами и API. Он не обязан сам выполнять
тяжёлый анализ.

### 3.2. Execution engine

Исполнитель pipeline с входом в виде versioned job package и выходом в виде
проверяемого result package. Engine не переключает current version, не пишет в
PostgreSQL напрямую и не решает, какой результат публиковать.

### 3.3. Bounded context

Модуль с собственным словарём, бизнес-правилами и владельцем данных. Начальный
набор контекстов:

- Identity and Access;
- Projects and Documents;
- Versions and Ingest;
- Storage and Blobs;
- Audit Jobs and Runs;
- Findings and Reviews;
- Expert Decisions and Knowledge Base;
- Comparison;
- Export;
- Worker Control;
- Operations and Audit Trail.

Контексты не импортируют внутренние repository/model соседнего контекста.
Взаимодействие идёт через публичный application port, контрактное событие или
явно утверждённый read model.

### 3.4. Вертикальный сценарий

Минимальная законченная пользовательская цепочка: UI → API → бизнес-правило →
данные → наблюдаемость → тест. Миграция только таблицы или только экрана без
работающего сценария является компонентной работой, но не завершённой поставкой.

### 3.5. Contract и schema version

Любая граница между независимо изменяемыми компонентами имеет версионированный
машинно проверяемый контракт: OpenAPI, JSON Schema, protobuf или SQL migration.
Неизвестная версия отклоняется явно. Неизвестные необязательные поля известной
версии могут игнорироваться.

## 4. Обязательные архитектурные принципы

### P-01. Идентичность непрозрачна

Системные ID генерируются один раз, не содержат пути или бизнес-атрибуты и не
парсятся для восстановления связей. `document_uid`, `finding_uid`, `run_id` и
`blob_id` связываются явными FK. Человекочитаемые номера — только display fields.

### P-02. Путь не является идентичностью

Путь, bucket key, имя файла, URL и название документа — адрес или отображение.
Их изменение не создаёт новую личность и не разрывает ссылки.

### P-03. Immutable history, explicit mutable state

Входные версии, complete run, manifests и события решений неизменяемы.
Исправление создаёт новую версию, run или редакцию. Mutable current pointer и
статус имеют одного владельца и меняются транзакционно.

### P-04. Сначала контракт, затем параллельная реализация

Параллельные задачи стартуют только от замороженной версии контракта. Потребители
не меняют общий контракт «по пути». Следующая несовместимая версия планируется
отдельной интеграционной задачей.

### P-05. Модульный монолит по умолчанию

Новый control plane начинается как один развёртываемый backend с жёсткими
модульными границами. Отдельный сервис создаётся только при доказанной
необходимости независимого масштабирования, безопасности, отказоустойчивости или
релизного цикла. Сеть не используется как способ скрыть плохую модульность.

### P-06. Side effects находятся на краях

Domain logic не читает environment, filesystem, HTTP, часы и случайность
напрямую. Эти зависимости передаются через ports. Adapter отвечает за I/O,
retry и преобразование внешней ошибки в типизированную внутреннюю ошибку.

### P-07. Транзакция заканчивается outbox

Изменение PostgreSQL и намерение вызвать внешний side effect фиксируются в одной
транзакции через transactional outbox. Прямой dual-write `DB → S3/event/legacy`
без журнала восстановления запрещён.

### P-08. Повтор является нормальным событием

Все команды, jobs, imports и callbacks имеют idempotency key или естественный
уникальный ключ. Повтор после timeout не создаёт вторую версию, второй run или
двойное решение.

### P-09. Состояние — явная state machine

Набор конфликтующих boolean-полей не заменяет состояние. Допустимые переходы,
terminal states, retry и компенсация определяются в одном месте и тестируются.

### P-10. Нет молчаливого fallback

Fallback разрешён только как именованный compatibility/canary mode с метрикой,
логом, владельцем и датой удаления. «Не нашли в новом — незаметно прочитали
старое» запрещено.

### P-11. Миграция обратима до observation gate

Каждый cutover проходит `baseline → shadow → parity → canary → primary →
observation → cleanup`. До cleanup существует проверенный rollback. Удаление
старой копии начинается только после restore drill.

### P-12. Производные данные перестраиваемы

Индекс, read model, thumbnail, page image, cache и `latest` не являются
единственной копией. У каждого производного объекта есть source, recipe/version
и процедура rebuild.

### P-13. Наблюдаемость является частью контракта

Каждая команда и фоновая операция имеет correlation ID, структурированный лог,
метрику результата и trace через границы. Ошибка без диагностируемого entity ID
и stage не считается нормально обработанной.

### P-14. Безопасность fail-closed

Авторизация проверяется на сервере для каждого объекта. S3 private, доступ
короткоживущий и минимальный. Секреты не пишутся в manifest, logs, browser state
или job package. Неизвестный auth state означает отказ.

### P-15. Простота важнее универсального framework

Абстракция вводится после двух реальных независимых применений либо из-за
обязательной архитектурной границы. Generic repository, base service и глобальный
`utils` без подтверждённой семантики запрещены.

### P-16. Повторяемость LLM доказывается артефактами

LLM-ответ не считается детерминированным. Каждый опубликованный run фиксирует
версии input, prompt bundle, norms snapshot, routing/model/parameters, checksum
ответа, usage и измеренную стоимость. В тестах analysis parity проверяется на
записанных синтетических или обезличенных ответах; live-ответы сравниваются по
утверждённой quality policy, а не побайтно.

### P-17. Бюджет legacy явно уменьшается до нуля

До Gate G1 legacy может получать не более одного активного product-capability
слота на волну и не более 20% human integration capacity — применяется более
строгий предел. Слот имеет пользовательский результат, владельца, срок и парную
задачу нового контура. После G1 бюджет новых legacy-capabilities равен нулю;
исключение требует владельца, expiry и доказательства, что новый контур не может
закрыть срочную потребность в согласованный срок.

Security/data-loss/production bugfix и неповеденческое усиление **существующего**
legacy-контракта не расходуют capability slot: разрешены characterization tests,
response models, JSON Schema, snapshots, telemetry и backward-compatible
validation. Такая работа не создаёт endpoint/writer/storage format, не меняет
бизнес-семантику ответа и подтверждает совместимость golden test.

### P-18. Стоимость является эксплуатационным ограничением

Для LLM-, storage- и compute-сценариев измеряются стоимость одного аудита и
стоимость одного принятого экспертом замечания. Рост за утверждённый budget
останавливает canary так же, как превышение latency/error budget. Оценка по
токенам без сверки с фактическим billing помечается как estimate.

## 5. Предпочтительные паттерны

### 5.1. Backend

Для каждого bounded context используется направленная зависимость:

```text
api/consumer
    → application commands/queries
        → domain rules
            ← ports
                ← adapters (PostgreSQL, S3, legacy, external API)
```

Предпочтения:

- use case/command handler вместо толстого router;
- типизированные value objects для ID, checksum, version и money/limits;
- unit of work на один бизнес-переход;
- repository только для aggregate boundary, не универсальный CRUD;
- optimistic concurrency или row lock там, где возможна потеря обновления;
- typed error/result с единым HTTP mapping;
- dependency injection на composition root, без service locator;
- orchestration saga для длинной операции; choreography только для простых
  информационных событий.

### 5.2. PostgreSQL

- нормализованная write model с FK, UNIQUE, CHECK и NOT NULL;
- timestamps в UTC и явный actor/source для изменяемых данных;
- schema migration только вперёд; rollback данных — отдельная безопасная
  процедура, а не надежда на down migration;
- expand → backfill → switch → contract для несовместимых изменений;
- индекс создаётся под зафиксированный query profile и проверяется `EXPLAIN`;
- JSONB допустим для versioned opaque payload или редких extension fields, но не
  вместо основных отношений;
- пагинация cursor-based для растущих списков;
- delete по retention/state transition; cascade delete для пользовательской
  истории по умолчанию запрещён;
- transactional outbox и migration journal — append-only.

### 5.3. S3 и файловый контур

- private bucket и deny-public policy;
- business code знает `blob_id`, role, size, SHA-256 и media type, но не bucket
  layout;
- object key непрозрачен и строится только storage adapter;
- upload идёт через temporary/multipart state, verify и publish;
- complete object и manifest неизменяемы;
- Range и materialize cache являются частью read contract;
- lifecycle, versioning, backup, RPO/RTO и egress утверждаются ADR до
  `s3_shadow_write`;
- удалённые workers не получают постоянные S3 credentials.

### 5.4. Фоновые задания и pipeline

- durable job record до запуска side effect;
- lease/heartbeat с fencing token, а не только память процесса;
- `job_id`, `attempt_id` и `run_id` имеют разную семантику;
- retry policy зависит от типа ошибки и имеет предел;
- poison job уходит в диагностируемый terminal state/DLQ;
- progress — projection, а не источник статуса;
- публикация result package выполняется после checksum/schema validation;
- stage registry и state transitions определены один раз;
- один stage читает только контрактные входы и пишет только собственные выходы.

### 5.5. API и интеграции

- OpenAPI является контрактом frontend/backend;
- TypeScript client генерируется и не переписывается вручную;
- команды поддерживают idempotency key;
- ошибки используют стабильный `error_code`, безопасное сообщение и correlation
  ID;
- breaking change создаёт новую major contract version или совместимый период;
- webhook/event содержит ID и версию, но не пытается быть полной копией aggregate;
- BFF агрегирует UI-read модели, но не владеет бизнес-правилами;
- внешний adapter заканчивается общим ingest и не публикует version напрямую.

### 5.6. Frontend Next.js / React / TypeScript

- TypeScript strict; `any` требует локального обоснования;
- App Router и server-first загрузка используются для shell, auth и простых
  read-сценариев;
- Next-каталог `app/` остаётся тонким router-adapter; FSD-слои называются
  `_app`, `_pages`, `widgets`, `features`, `entities`, `shared`, чтобы не
  конфликтовать с зарезервированными Next-каталогами и работать с архитектурным
  линтером;
- `page.tsx` только связывает Next route с публичным API `_pages` и не содержит
  доменной логики;
- PDF viewer, таблицы, live progress и тяжёлая интерактивность оформляются как
  ограниченные client islands;
- server state живёт в query/cache layer, UI state — локально или в узком
  feature store; единый глобальный store всего приложения запрещён;
- импорты идут только вниз по слоям; slice публикует `index.ts`/`index.server.ts`,
  deep imports и cross-imports между slices одного слоя запрещены;
- raw HTTP знает только generated transport в `shared/api`; `entities/*/api`
  может содержать узкие query/mutation hooks, но не собственный HTTP client;
- структура — по feature/vertical slice, а не общие папки `components` и
  `services` без владельца;
- runtime-валидация выполняется на внешней границе схемой, выведенной из того же
  OpenAPI; вручную дублировать response schema в Zod и backend запрещено;
- route/component не собирает URL строками и не знает внутренний S3 key;
- дизайн-система отделяет primitive, domain component и page composition;
- accessibility, loading, empty, error, retry и permission states обязательны;
- большие списки имеют server pagination/virtualization; polling ограничен и
  заменяется resumable event stream там, где это оправдано.

### 5.7. Тестирование

Используется не пирамида ради количества тестов, а набор доказательств:

1. characterization/golden tests фиксируют существующую бизнес-семантику;
2. domain unit tests проверяют инварианты без I/O;
3. contract tests проверяют providers и consumers одной schema version;
4. integration tests запускают реальный PostgreSQL/S3-compatible adapter;
5. migration tests проверяют old → new и повторный запуск;
6. end-to-end tests покрывают критические пользовательские маршруты;
7. parity tests сравнивают старый и новый результат семантически, а не по
   случайному порядку JSON;
8. restore/rollback drills являются эксплуатационными тестами.

Для LLM-сценариев слово `parity` всегда квалифицируется:

- **contour parity** — совпадают schema/checksum, явные identity mappings,
  связи version/run/finding, решения эксперта и опубликованные artifacts;
- **analysis replay parity** — legacy engine получает тот же package и
  записанные provider responses, поэтому проверяется детерминированная логика до
  и после LLM-вызова;
- **live quality parity** — новые live-ответы оцениваются на размеченной выборке
  по quality/cost/latency policy, но от них не требуется текстовое совпадение.

Кассеты в репозитории содержат только синтетические или обезличенные данные.
Production payload с персональными/проектными данными хранится приватно по
retention policy и не копируется в fixtures.

Новый код не понижает baseline. Flaky test получает владельца и срок; молчаливое
добавление его в вечный allowlist запрещено.

## 6. Правила параллельной вайб-разработки

Параллелизм строится по стабильным границам, а не по количеству агентов.

### 6.1. Контрактный гейт волны

Перед началом волны один владелец фиксирует версии общих контрактов. После
старта волны потребители работают только с этими версиями. Изменение контракта
идёт в следующую волну либо в отдельную блокирующую integration-задачу.

### 6.2. Один файл и один контракт — один владелец

В одной волне два исполнителя не редактируют один файл, migration или schema.
Общие hotspots (`OpenAPI`, root dependency files, application composition,
global styles, migration head) принадлежат интегратору волны.

### 6.3. Форма задачи

Каждая задача обязана содержать:

- `task_id` и измеримый пользовательский/технический результат;
- frozen inputs и contract version;
- разрешённые каталоги и список общих файлов, которых касаться нельзя;
- явные non-goals;
- артефакт выхода: код, migration, schema, test, report или runbook;
- локальную команду проверки;
- integration contract и критерий готовности;
- rollback/feature flag для изменения поведения;
- зависимость только от завершённых task IDs, а не от «почти готовой ветки».

Предпочтительный размер — 0,5–3 инженерных дня и один bounded context. Если
задача одновременно меняет shared contract, backend, frontend и migration, её
нужно разделить на contract-task, независимые implementation-tasks и
integration-task.

### 6.4. Порядок интеграции

```text
contract task
    → параллельные provider / consumer / tests / ops tasks
        → integration task
            → canary evidence
                → следующий contract version
```

Режим изоляции checkout/worktree выбирается отдельным ADR. Пока
[ADR-0016](adr/ADR-0016-workspace-isolation.md) не принят и `CLAUDE.md` не
изменён одним согласованным change, действует текущий режим одного checkout:
задачи дополнительно разводятся по файлам, а незавершённая задача не оставляет
общий контракт в полусостоянии. Worktree устраняет конфликт dirty state, но не
отменяет одного владельца contract, migration head и integration slot.

### 6.5. Что можно выполнять параллельно

- PostgreSQL module после фиксации domain/schema contract;
- Storage adapter после фиксации Blob/Manifest contract;
- generated client и frontend mock после фиксации OpenAPI;
- legacy analysis adapter после фиксации Job/Result package;
- observability dashboards после фиксации event/metric names;
- миграционный scanner после фиксации mapping schema;
- contract tests независимо от provider implementation.

Не параллелятся внутри одной версии:

- проектирование и реализация одного и того же shared contract;
- две migrations от одного head без назначенного интегратора;
- два изменения composition root или root dependency lock;
- два рефакторинга одного legacy hotspot;
- cutover и изменение semantic parity rules.

## 7. Запрещённые антипаттерны

- big-bang rewrite и один общий финальный cutover;
- новый проект как бесконечно догоняющая функциональная копия legacy;
- direct SQL/S3/filesystem из router или React component;
- бизнес-логика в ORM model, transport schema или UI;
- parsing ID, path или display name для восстановления FK;
- boolean soup вместо state machine;
- dual-write без outbox/reconciliation;
- catch-all exception с успешным ответом или silent fallback;
- shared mutable singleton для durable state;
- `latest`/cache/index как единственная копия;
- неограниченный retry, polling, concurrency или in-memory payload;
- универсальный `utils`, `BaseService`, `GenericRepository` без семантики;
- permanent feature flag без владельца и даты удаления;
- frontend mega-component и общий store всей предметной области;
- миграция без dry-run, journal, parity и rollback;
- microservice только ради организационного разделения файлов.

## 8. Архитектурный Definition of Done

Изменение считается завершённым, только если:

1. контракт и владелец данных названы;
2. инварианты закреплены DB constraints или domain tests;
3. success, validation, conflict, retry и terminal failure протестированы;
4. schema/API совместимы либо есть versioned migration;
5. лог, metric и correlation ID позволяют диагностировать операцию;
6. security boundary и отсутствие секретов проверены;
7. migration/cutover имеет dry-run и rollback, если затрагивает данные;
8. frontend показывает loading/empty/error/permission states;
9. документация и ADR обновлены, если изменилось архитектурное решение;
10. feature flag имеет default, владельца, критерий включения и дату удаления;
11. CI и локальная проверка воспроизводимы;
12. нет нового прямого обхода Metadata/Storage/Application ports.

## 9. Процесс ADR

ADR обязателен, если решение:

- меняет источник истины или владельца данных;
- вводит новый сервис, database, queue, storage или внешний provider;
- создаёт новый публичный API/contract major version;
- меняет идентичность, retention, security boundary, consistency или RPO/RTO;
- добавляет долгоживущий framework/pattern, затрагивающий несколько контекстов;
- отклоняется от этой Bible.

Статусы:

- `proposed` — обсуждается; необратимая production-реализация, существующая
  только при выборе этого решения, не стартует, но discovery/fixtures/spike
  разрешены;
- `accepted` — решение обязательно для новых изменений;
- `superseded` — заменено другим ADR, история сохраняется;
- `rejected` — рассмотрено и отклонено;
- `deprecated` — действует только для legacy/перехода с датой удаления.

Эти статусы относятся к ADR, а не создают новые статусы для roadmap или plan
contract. Accepted ADR самодостаточен: ссылка на `P-XX` объясняет связь, но не
делает proposed Bible скрытой нормативной зависимостью. Bible становится
обязательной только после отдельной записи утверждения с датой и субъектом;
перевод Bible и ADR-0002 в `accepted` выполняется задачей `W0-DEC-01`, а не
подразумевается началом разработки.

Принятый ADR не переписывается задним числом. Допускаются исправления ссылок и
опечаток; изменение решения оформляется новым ADR со ссылкой `supersedes`.
Шаблон находится в [ADR_TEMPLATE.md](ADR_TEMPLATE.md), реестр — в
[ADR_INDEX.md](ADR_INDEX.md).

## 10. Управление исключениями

Временное исключение содержит:

- нарушаемый принцип `P-XX`;
- конкретную область кода/данных;
- причину и рассмотренные альтернативы;
- риск и компенсирующий контроль;
- владельца;
- дату истечения;
- задачу удаления.

Исключение без даты истечения считается новой архитектурой и требует ADR.
Действующие исключения регистрируются в [EXCEPTIONS.md](EXCEPTIONS.md).

## 11. Связанные документы

- [Реестр ADR](ADR_INDEX.md)
- [Шаблон ADR](ADR_TEMPLATE.md)
- [Реестр исключений](EXCEPTIONS.md)
- [Roadmap гибридной миграции](HYBRID_REWRITE_ROADMAP.md)
- [План развития хранения](../data_storage_modernization/00_global_plan.md)
- [Правила идентичности](../data_storage_modernization/01_storage_and_identity_rules.md)
- [Единый файловый контур](../data_storage_modernization/02_unified_file_storage_and_ingest.md)
- [PostgreSQL для метаданных](../data_storage_modernization/03_postgresql_metadata.md)
- [Архитектура распределённых workers](../distributed_audit_workers/01_current_architecture_audit.md)
