# Этап 3. PostgreSQL для метаданных и связей

**Редакция:** 2026-08-27.<br>
**Происхождение:** прежний этап 4 перенумерован в этап 3 после упразднения
самостоятельного этапа внешней доставки.

## 1. Результат

PostgreSQL становится источником истины для изменяемых документных
метаданных: объектов, дисциплин, документов, версий, запусков, файловых ролей,
замечаний, экспертных решений, обсуждений и сравнений. Собственный S3 этапа 2
хранит байты, PostgreSQL — связи с `blob_id`.

JSON и файловые указатели временно остаются compatibility projections, но
после cutover не считаются канонической записью.

## 2. Что этап не делает

- не переносит сами PDF/кропы/results в базу;
- не повторяет S3 backfill этапа 2;
- не подключает внешний источник;
- не заменяет автономный `workers.db` без отдельного ADR;
- не вводит все индексы заранее — это этап 4;
- не удаляет legacy/JSON — это этап 5.

## 3. Входные условия

Production-cutover блокируется, пока не выполнены:

1. этап 1: стабильные `document_uid`, `finding_uid`, version/run identity;
2. этап 1Б: `projects_v2_primary` и один write contract;
3. этап 2.2: стабильные `blob_id` и manifests;
4. этап 2.3–2.4: S3 storage mode и правила current pointer;
5. свежий inventory всех metadata readers/writers;
6. отдельный PostgreSQL ADR: topology, HA, backup, pooling, RPO/RTO;
7. назначенные schema, migration и operations owners.

Source adapter 2.5 не является входным условием.

## 4. Источники истины после этапа

| Данные | Источник истины |
| --- | --- |
| объекты, дисциплины, документы, версии | PostgreSQL |
| current version/current run | PostgreSQL в одной транзакции |
| роли и ссылки на файлы | PostgreSQL → `blob_id` |
| байты | собственный S3 этапа 2 |
| input/run manifest | immutable blob + зарегистрированная запись в PostgreSQL |
| замечания и решения | PostgreSQL |
| локальный диск | staging/cache/workspace |
| JSON projections | временная совместимость, не каноника |
| `workers.db` | отдельный автономный управляющий контур |

## 5. Metadata Service

Бизнес-код не пишет SQL и JSON параллельно. Вводится единый Metadata Service:

```python
create_document(...)
create_version(...)
publish_version(version_id, input_manifest_blob_id)
create_run(...)
complete_run(run_id, run_manifest_blob_id)
set_current_version(...)
upsert_finding(...)
record_expert_decision(...)
attach_blob(role, blob_id, ...)
resolve_document(...)
list_versions(...)
get_project_summary(...)
```

Service отвечает за транзакции, ограничения, outbox, audit trail и временную
JSON projection. Роутеры и pipeline не переключают backend самостоятельно.

## 6. Основная модель

### 6.1. Идентичность и структура

```text
objects
  └─ disciplines
       └─ documents(document_uid)
            └─ document_versions(version_id)
                 ├─ version_files(blob_id, role)
                 ├─ analysis_runs(run_id)
                 │    ├─ run_artifacts(blob_id, role)
                 │    └─ findings(finding_uid, ordinal)
                 ├─ expert_decisions
                 └─ discussions
```

### 6.2. Таблицы

Минимальный набор:

- `objects`;
- `disciplines`;
- `documents`;
- `document_aliases` — история из нескольких алиасов документа с типом и
  периодом действия, а не одно перезаписываемое поле;
- `document_versions`;
- `version_files`;
- `analysis_runs`;
- `run_artifacts`;
- `findings`;
- `finding_occurrences`;
- `expert_reviews` и `expert_decisions`;
- `discussions` и `discussion_events`;
- `version_comparisons`;
- `imports`;
- `derivatives`;
- `metadata_outbox`;
- `migration_journal`;
- `integrity_events`.

## 7. Ключевые ограничения

- `document_uid`, `finding_uid`, `run_id`, `blob_id` — непрозрачные ID;
- новый `finding_uid` имеет вид `fnd_<ULID>`; `document_uid` и `version_id`
  хранятся отдельными FK и не извлекаются парсингом строки;
- `(document_uid, version_id)` уникально;
- один current version на документ;
- один current complete run на версию;
- current run может ссылаться только на `complete` run с manifest;
- finding принадлежит run/version/document через FK;
- expert decision ссылается на стабильный `finding_uid`, а не `F-NNN`;
- `ordinal` уникален только внутри run и используется для отображения;
- version/run manifest после публикации не заменяется;
- manifest содержит известный `schema_version`; schema 2 требует `blob_id` для
  каждой управляемой файловой записи;
- удаление сущности с зависимостями запрещено либо выполняется через
  документированный state transition;
- `blob_id` регистрируется только после подтверждения Storage Service.

## 8. Транзакционные сценарии

### 8.1. Публикация версии

1. Storage Service создаёт все blobs и input manifest.
2. Metadata Service открывает транзакцию.
3. Создаёт version/files/import records.
4. Проверяет известный `schema_version`, отсутствие конфликта и полноту manifest.
5. Публикует version.
6. Переключает current pointer.
7. Пишет outbox/audit event.
8. Commit.

Неполная версия не видна обычному чтению.

### 8.2. Завершение run

1. Pipeline пишет artifacts через Storage Service.
2. Публикует run manifest.
3. Metadata Service проверяет обязательные роли.
4. Переводит run `running → complete`.
5. Переключает current run.
6. Создаёт outbox для projections/UI.

### 8.3. Решение эксперта

Решение, причина, автор, timestamp и версия сохраняются в одной транзакции.
Синхронизация discussion status выполняется через тот же service/outbox, а не
отдельными best-effort HTTP-вызовами.

## 9. Immutable и mutable данные

Immutable:

- опубликованный input manifest;
- complete run manifest;
- finding occurrence конкретного run;
- история decisions/events.

Mutable через контролируемые переходы:

- current pointers;
- display name и группировка;
- статусы незавершённого run;
- текущая экспертная оценка как проекция истории;
- visibility/retention state.

Изменение immutable факта создаёт новую запись или corrective event.

## 10. Outbox и projections

До этапа 5 части приложения продолжают читать JSON. Поэтому транзакция пишет
`metadata_outbox`, а отдельный projector строит:

- `document.json`;
- `version.json`;
- `runs.json`;
- `latest` compatibility view;
- summaries для старых endpoint;
- knowledge-base projections.

Ошибка projection не откатывает каноническую DB-транзакцию. Она видна в
очереди и исправляется retry/rebuild. Прямое редактирование projection
запрещено после write-cutover.

## 11. Режимы миграции

```text
json_primary
postgres_shadow_write
postgres_shadow_read
postgres_canary_primary
postgres_primary
```

Режим выбирает Metadata Facade. Один request не должен смешивать источники без
явного dual-read comparator.

## 12. Inventory перед миграцией

Нужно классифицировать все readers/writers:

- projects/versions API;
- pipeline manager и stage storage;
- findings/optimization/norms;
- expert review, discussions, knowledge base;
- stage comparison;
- schedule и dashboards;
- exports и audit packages;
- distributed worker dispatcher;
- scripts/backfill/migration;
- `latest`, current pointers и `_system`;
- тестовые и синтетические producers.

Для каждого фиксируются owner, logical operation, authority, consistency и
план переключения.

## 13. Backfill

Backfill идёт по `document_uid` стабильными партиями:

1. read-only inventory;
2. dry-run преобразования;
3. резервирование ID;
4. запись parent entities;
5. версии и blob references;
6. run/findings/decisions;
7. checksums/counts/semantic parity;
8. запись append-only journal.

Повтор безопасен. Timestamp и порядок событий сохраняются. Неоднозначные
данные уходят в quarantine report и не угадываются по имени.

## 14. Semantic parity

Сравнивается не сырой JSON, а пользовательский смысл:

- тот же документ и current version;
- тот же complete run;
- одинаковые counts и severity;
- одинаковые решения эксперта и причины;
- те же version files и roles;
- те же discussions/comparisons;
- одинаковая доступность PDF/blocks/findings/export.

Допустимые различия — порядок ключей, служебные timestamps projection и новые
непрозрачные ID при сохранённой связи.

## 15. Cutover

```text
fresh baseline
→ schema + constraints
→ idempotent backfill
→ shadow write
→ outbox/projector
→ full semantic parity
→ shadow read
→ canary-primary по объекту
→ postgres-primary
→ observation
→ rollback drill
```

Этап 5, а не этап 3, удаляет JSON readers и legacy replicas.

## 16. Concurrency

- document/version publication использует row/advisory lock;
- current pointer меняется compare-and-set либо под lock;
- run completion идемпотентен по `run_id`;
- decision updates используют revision/optimistic lock;
- outbox публикуется at-least-once, consumers идемпотентны;
- connection pool имеет отдельные лимиты API, pipeline и workers;
- долгие backfill не держат транзакцию на весь объект.

## 17. Backup и DR

- PITR и регулярные base backup;
- restore drill связывает PostgreSQL snapshot с доступностью S3 blobs и
  manifests;
- RPO/RTO фиксируются в ADR;
- migration journal и schema migrations резервируются;
- восстановление проверяет current pointers, FK и выборочные пользовательские
  сценарии;
- DB backup без согласованного S3 состояния не считается полным restore.

## 18. Безопасность

- отдельные DB roles для API, migration, projector и read-only diagnostics;
- TLS, secret rotation и запрет credentials в репозитории;
- parameterized SQL/ORM;
- audit trail критических изменений;
- персональные данные и комментарии получают retention/access policy;
- admin endpoints требуют auth и явный scope;
- destructive migration требует maintenance gate и backup proof.

## 19. Производительность

До этапа 4 создаются только индексы, обязательные для PK/FK/uniqueness и
критических current lookups. Остальные решения принимаются по `EXPLAIN` и
метрикам.

Baseline:

- project list P50/P95;
- open document/version;
- findings and expert decisions;
- dashboard aggregation;
- publish version/run;
- concurrent review updates;
- backfill rows/sec и WAL;
- pool saturation и lock waits.

## 20. Наблюдаемость

- query latency/error rate;
- pool usage;
- lock/deadlock;
- replication/backup lag;
- outbox lag и retry;
- projection freshness;
- parity mismatches;
- orphan/FK/integrity events;
- canary source and fallback;
- связь request/import/job/run через correlation IDs.

## 21. Rollback

До этапа 5 rollback переключает Metadata Facade на предыдущий подтверждённый
режим. Новые DB-записи не уничтожаются. Outbox/projector догоняется после
восстановления. Rollback не меняет S3 storage mode этапа 2 автоматически — два
cutover управляются независимо.

## 22. Фазы

| Фаза | Работа | Гейт |
| --- | --- | --- |
| A | ADR, inventory, baseline | owners/RPO/RTO/schema authority назначены |
| B | schema + Metadata Service | contract tests PASS |
| C | dry-run/backfill | quarantine объяснён, повтор идемпотентен |
| D | shadow write + outbox | без потерь и неконтролируемого lag |
| E | semantic parity | все пользовательские проекции совпадают |
| F | shadow read/canary | P95 и correctness PASS |
| G | postgres-primary | observation и rollback drill PASS |
| H | передача этапу 4 | реальные query profiles собраны |

## 23. Критерии завершения

1. PostgreSQL является primary для всех документных метаданных.
2. Все writers проходят через Metadata Service.
3. UID/FK/uniqueness/current constraints действуют.
4. Version и run публикуются транзакционно после manifest.
5. Expert decisions связаны со стабильным `finding_uid`.
6. JSON являются только projections.
7. Backfill идемпотентен и имеет полный journal.
8. Semantic parity пройдена для всех объектов и основных endpoint.
9. Outbox/projector восстанавливаются после сбоя.
10. Backup + совместный DB/S3 restore drill PASS.
11. Canary, observation и rollback drill PASS.
12. P95, pool и lock budgets соблюдены.
13. `workers.db` не объявлен перенесённым без отдельного решения.
14. Документы и UI не называют этот этап этапом 4.

## 24. Пользовательский эффект

- одна и та же версия и история видны во всех экранах;
- решения не пропадают после повторного аудита;
- параллельная работа не создаёт дубли и потерянные связи;
- списки и статусы перестают зависеть от обхода каталогов;
- последующий этап 4 может ускорять реальные SQL-запросы.

## 25. Связанные документы

- [глобальный план](00_global_plan.md)
- [этап 1](01_storage_and_identity_rules.md)
- [этап 1Б](01b_projects_v2_write_cutover.md)
- [этап 2](02_unified_file_storage_and_ingest.md)
- [ADR внешних источников](ADR_external_sources_are_optional.md)
