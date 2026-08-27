# ADR-0003. Contract-first и единый владелец данных

**Статус:** accepted<br>
**Дата:** 2026-08-27<br>
**Владельцы:** architecture, data, API<br>
**Утверждено:** заказчик, 2026-08-27; ранее согласованные identity/storage/PostgreSQL plan contracts<br>
**Supersedes:** нет<br>
**Затронутые принципы:** P-01–P-04, P-07–P-10

## Контекст

Текущие связи часто определяются путями и JSON-формами, а одно состояние может
иметь несколько writers. Для безопасной параллельной разработки нужны стабильные
машинно проверяемые границы.

## Решение

- PostgreSQL через Metadata module владеет изменяемыми метаданными;
- private S3 через Storage module владеет долговечными байтами;
- OpenAPI владеет HTTP-контрактом нового frontend;
- versioned JSON Schema владеет manifest/job/result packages;
- каждый shared contract имеет одного владельца версии;
- consumer не меняет provider schema в своей implementation-задаче;
- несовместимое изменение использует expand/backfill/switch/contract;
- DB + event/side effect используют transactional outbox;
- повтор команды защищён idempotency key.

Чтение legacy допустимо только через anti-corruption adapter с метрикой. Новая
domain logic не читает legacy JSON или filesystem напрямую.

## Последствия

- backend, frontend, storage и migration tools можно писать параллельно;
- contract-task становится обязательным предшественником implementation-tasks;
- появляется стоимость schema registry, generated clients и compatibility tests;
- прямой dual-write без reconciliation считается архитектурным нарушением.

## Ссылки

- [Правила идентичности](../../data_storage_modernization/01_storage_and_identity_rules.md)
- [Storage и S3](../../data_storage_modernization/02_unified_file_storage_and_ingest.md)
- [PostgreSQL](../../data_storage_modernization/03_postgresql_metadata.md)
- [ADR Bible](../ADR_BIBLE.md)
