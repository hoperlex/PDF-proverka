# Реестр архитектурных решений

**Редакция:** 2026-09-01.<br>
**Владелец нумерации:** technical lead/architecture owner.

Номер ADR не переиспользуется. Принятое решение сохраняется в истории; замена
создаёт новый ADR и помечает старый как `superseded`.

## Базовые ADR новой платформы

| ADR | Статус | Решение | Пересмотр |
| --- | --- | --- | --- |
| [ADR-0001](adr/ADR-0001-hybrid-strangler-migration.md) | accepted | гибридная миграция Strangler, legacy как execution engine | после первого primary vertical slice |
| [ADR-0002](adr/ADR-0002-modular-monolith-control-plane.md) | proposed | модульный монолит control plane; сервисы только по доказанной границе | `W0-DEC-01`, до ADR target layout |
| [ADR-0003](adr/ADR-0003-contracts-and-data-ownership.md) | accepted | contract-first, PostgreSQL/S3 ownership, outbox | при contract major v2 или смене source of truth |
| [ADR-0004](adr/ADR-0004-nextjs-frontend.md) | accepted | Next.js/React/TypeScript и поэтапная миграция маршрутов | после первого сложного PDF/findings route |
| [ADR-0005](adr/ADR-0005-parallel-delivery.md) | accepted | контрактные волны и file ownership для параллельной разработки | после двух волн, по lead time/conflicts |
| [ADR-0006](adr/ADR-0006-target-repository-layout.md) | accepted | целевая раскладка репозитория, зоны владения и правила импортов | после первого перенесённого модуля или при смене composition root |
| [ADR-0007](adr/ADR-0007-postgresql-topology-and-migrations.md) | proposed | топология PostgreSQL, владение миграциями, HA/backup/pooling, RPO/RTO | `W0-ADR-01`, до metadata shadow-write |
| [ADR-0008](adr/ADR-0008-s3-provider-and-bucket-policy.md) | proposed | провайдер S3, ключи, шифрование, versioning, lifecycle, стоимость | `W0-ADR-02`, до `s3_shadow_write` |
| [ADR-0009](adr/ADR-0009-durable-jobs-and-outbox.md) | proposed | durable jobs: state machine, leases, retries, outbox, recovery | `W0-ADR-03`, до нового production job writer |
| [ADR-0010](adr/ADR-0010-authn-authz-and-tenant-object-scope.md) | proposed | session, roles, object checks, service identity, audit | `W0-ADR-06`, до нового write API и Next route |
| [ADR-0011](adr/ADR-0011-observability-and-slo.md) | proposed | logs/traces/metrics, retention, alerts, ownership, SLO | `W0-ADR-07`, до production canary |
| [ADR-0012](adr/ADR-0012-legacy-analysis-package-protocol.md) | proposed | схема пакета анализа, checksum, версия, отмена, повтор | `W0-ADR-08`, до вызова legacy engine из control plane |
| [ADR-0013](adr/ADR-0013-llm-reproducibility-and-cost.md) | proposed | prompt/norm/model routing versioning, replay и cost policy | `W0-ADR-04`, до analysis writer |
| [ADR-0014](adr/ADR-0014-data-classification-retention-and-erasure.md) | proposed | data classes, retention matrix и erasure workflow | `W0-ADR-05`, до storage canary |
| [ADR-0015](adr/ADR-0015-program-execution-model.md) | proposed | staffed team или human integrator + agents; WIP/forecast | `W0-DEC-01` |
| [ADR-0016](adr/ADR-0016-workspace-isolation.md) | proposed | shared checkout или hybrid worktrees | `W0-DEC-02` после `W0-WS-01` |
| [ADR-0017](adr/ADR-0017-frontend-route-strangler-and-fsd.md) | proposed | typed slice → generated client → FSD route strangler | `W0-ADR-09`, до W1-WEB-04 |
| [ADR-0018](adr/ADR-0018-domain-contract-v1.md) | accepted | domain contract v1: идентификаторы, состояния и ошибки | при contract major v2 или смене source of truth |

Нормативные приложения ADR-0018 — [глоссарий](GLOSSARY.md) и
[domain contract v1](DOMAIN_CONTRACT_V1.md) вместе с машиночитаемой формой
`contracts/domain/v1/**`. Собственного ADR-статуса они не имеют: их
нормативная сила следует статусу ADR-0018.

## Ранее принятые решения программы

Эти документы считаются действующими специализированными ADR/decision records и
не дублируются новой нумерацией:

| Документ | Тип | Статус | Область |
| --- | --- | --- | --- |
| [Внешние источники — опциональные adapters](../data_storage_modernization/ADR_external_sources_are_optional.md) | ADR | accepted | source adapters и C-07 |
| [Правила идентичности](../data_storage_modernization/01_storage_and_identity_rules.md) | plan contract | accepted | UID, run, manifest, immutability |
| [Storage/S3 plan](../data_storage_modernization/02_unified_file_storage_and_ingest.md) | plan contract | accepted | blobs, S3, ingest, migration |
| [PostgreSQL plan](../data_storage_modernization/03_postgresql_metadata.md) | plan contract | accepted | metadata ownership и cutover |

`plan contract` — тип документа, а не отдельный ADR-статус. Для ADR допустимы
только статусы из §9 Bible.

## Записи приёмки

Статус ADR и готовность файлов задачи — разные вещи: до явной записи здесь
готовый документ остаётся `proposed` и не разрешает необратимый шаг. Поэтому
приёмка фиксируется отдельной строкой с датой и тем, кто её принял.

| Дата | ADR | Из | В | Кто принял | Основание |
| --- | --- | --- | --- | --- | --- |
| 2026-09-01 | ADR-0006 | proposed | accepted | владелец программы (Древний), в задании на волну `W0-INT-01` | `W0-ARC-01` выполнена; target layout и зоны владения нужны как frozen input интеграции |
| 2026-09-01 | ADR-0018 | proposed | accepted | владелец программы (Древний), в задании на волну `W0-INT-01` | `W0-ARC-02` выполнена; domain contract v1 вместе с глоссарием и `contracts/domain/v1/**` получает нормативную силу |

Поправка об ограниченном pre-G1 владении `W0-INT-01` внесена в ADR-0006 ДО
перевода в `accepted`: после принятия такое изменение оформлялось бы новым
ADR, а не правкой задним числом (§9 Bible).

Приёмка этих двух ADR **не** снимает `proposed` с остальных: ADR-0002, 0013,
0014, 0015, 0016 и 0017 остаются в прежнем статусе, и ограничения, которые из
них следуют, продолжают действовать.

## Внешние нормативные входы

Документы, которые влияют на решения, но не являются решениями этой программы и
не получают ADR-номер.

| Вход | Статус | Роль | Владелец проверки |
| --- | --- | --- | --- |
| Корпоративный стандарт v3.1 (single-VPS baseline) | рекомендательный; актуальность не подтверждена, новой редакции нет | operational checklist и evidence для ADR-0007/0008/0009/0010/0011 | `W0-STD-01` |

Правила обращения с такими входами:

1. вход не создаёт ADR и не занимает contract slot;
2. применимость фиксируется матрицей `W0-STD-01` в разрезе
   принять / адаптировать / отложить / отклонить / требует подтверждения;
3. неподтверждённое положение после истечения decision timeout остаётся
   справочным evidence и не имеет нормативной силы;
4. поздний ответ владельца входа не переоткрывает принятые ADR автоматически;
5. ADR, опирающийся на внешний вход, фиксирует **дату проверки и версию
   документации**, а не только ссылку.

Требования Bible не понижаются до уровня внешнего входа: там, где стандарт даёт
минимум, а Bible — более строгое требование (manifest, lease, fencing token,
outbox, immutable result package), действует Bible.

## ADR, обязательные до production-кода соответствующей области

| Кандидат | Owning task | Блокирует | Минимальное решение |
| --- | --- | --- | --- |
| [ADR-0006](adr/ADR-0006-target-repository-layout.md) Target repository/package layout | `W0-ARC-01` | массовое создание нового skeleton | ownership zones, imports, dependency rules, composition root |
| ADR-0007 PostgreSQL topology and migrations | `W0-ADR-01` | metadata shadow-write | driver/ORM, migration ownership, HA, backup, pooling, RPO/RTO |
| ADR-0008 S3 provider and bucket policy | `W0-ADR-02` | `s3_shadow_write` | provider/region, keys, encryption, versioning, lifecycle, cost, C-07 |
| ADR-0009 Durable jobs and outbox | `W0-ADR-03` | новый production job writer | state machine, leases, retries, outbox dispatcher, recovery |
| ADR-0010 AuthN/AuthZ and tenant/object scope | `W0-ADR-06` | новый write API и Next route | session, roles, object checks, service identity, audit |
| ADR-0011 Observability and SLO | `W0-ADR-07` | production canary | logs, traces, metrics, retention, alerts, ownership |
| ADR-0012 Legacy analysis package protocol | `W0-ADR-08` | вызов legacy engine из control plane | input/result schema, checksum, version, cancellation, retry |

Номера 0006–0012 зарезервированы этим блокирующим backlog и не переиспользуются,
даже если более поздний ADR создан раньше. Резерв номера не означает принятия:
нормативным решение становится только после создания файла и статуса
`accepted`.

Для календаря W0 разрешены два review-batch: `W0-ADR-01/02` (`CB-W0-01`) и
`W0-ADR-06/07` (`CB-W0-02`). Batch занимает один shared contract review-slot,
но owning task, ADR-файл, статус и downstream acceptance каждого решения
остаются отдельными.

## Как добавить ADR

1. Скопировать [ADR_TEMPLATE.md](ADR_TEMPLATE.md) в `adr/ADR-NNNN-slug.md`.
2. Взять номер после максимального файла **и зарезервированного backlog ID** из
   этого реестра; пропуски 0006–0012 не занимать другой темой.
3. Добавить строку в этот реестр одним логическим изменением.
4. До статуса `accepted` не запускать необратимую implementation-задачу.
5. После реализации добавить ссылки на contract, migration, tests и runbook.

## Связанные документы

- [ADR Bible](ADR_BIBLE.md)
- [Roadmap](HYBRID_REWRITE_ROADMAP.md)
- [Глоссарий](GLOSSARY.md)
- [Domain contract v1](DOMAIN_CONTRACT_V1.md)
- [Реестр исключений](EXCEPTIONS.md)
- [Разбор ревью 2026-08-27](REVIEW_DISPOSITION_2026-08-27.md)
- [Разбор ревью R2](REVIEW_DISPOSITION_2026-08-27_R2.md)
- [Разбор ревью R3](REVIEW_DISPOSITION_2026-08-27_R3.md)
