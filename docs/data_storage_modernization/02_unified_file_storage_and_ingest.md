# Этап 2. Единый файловый контур, собственный S3 и импорт

**Редакция:** 2026-08-27.<br>
**Происхождение:** прежний этап 3 перенумерован в этап 2 и расширен общим
ingest; прежний самостоятельный этап внешней доставки упразднён.

## 1. Коротко о результате

После этапа 2 приложение управляет всеми долговечными байтами через один
Storage Service. Собственный private S3 является источником истины для
оригиналов и неизменяемых результатов, локальный диск — staging, рабочей
областью и восстанавливаемым кэшем.

Все входные каналы используют один ingest. Browser upload обязателен. Внешний
S3, HTTPS pull и push-inbox подключаются только как опциональные adapters и не
входят в критический путь.

## 2. Почему этап объединён

Отдельная внешняя доставка и собственный S3 требовали бы дважды реализовать:

- потоковое чтение и resume;
- staging и лимиты;
- распаковку и классификацию;
- checksum и provenance;
- идемпотентность;
- manifests и публикацию версии;
- retry, наблюдаемость и cleanup.

Объединение оставляет одну реализацию и позволяет получить пользу от
собственного S3 даже при полном отсутствии внешнего connector.

## 3. Граница этапа

Входит:

- безопасность файловой выдачи;
- потоковый ingest;
- `blob_id` и manifest-контракты;
- Storage Service и adapters local/S3;
- новые записи, historical backfill и S3-primary cutover;
- материализация для существующего pipeline;
- производные файлы, кэш и retention;
- опциональные source adapters;
- backup, restore и эксплуатация.

Не входит:

- перенос документных метаданных в PostgreSQL — этап 3;
- SQL-индексы — этап 4;
- окончательное удаление legacy/JSON — этап 5;
- выдача S3 credentials удалённым воркерам;
- обязательный внешний каталог или webhook.

## 4. Зависимости

| Работа | Зависимость |
| --- | --- |
| 2.0–2.2: baseline, ingest, контракт | можно вести параллельно этапу 1 |
| production-запись новых версий | завершённый этап 1Б (`projects_v2_primary`) |
| historical backfill | storage contract, inventory, место на staging и restore plan |
| S3-primary | shadow parity, canary и rollback drill |
| source adapter 2.5 | не является гейтом; нужен отдельный подтверждённый контракт |
| PostgreSQL этапа 3 | стабильные `blob_id` и manifests этапа 2 |

## 5. Сквозная схема

```text
browser / local admin / optional source adapter
        │
        ▼
2.1 ingest: stream → staging → unpack → classify → precheck
        │
        ▼
2.2 Storage Service: blob_id + checksum + manifest
        │
        ├─ local adapter (до cutover)
        └─ own S3 adapter
                 │
                 ▼
         immutable source/run blobs
                 │
                 ▼
         materialize cache → audit pipeline
```

## 6. Сегмент 2.0. Безопасность и baseline

До S3 shadow-write выполняются независимые обязательные работы.

### 6.1. Export download

`GET /api/export/download/{filename}` не должен искать произвольное имя в
корне проекта. Допустим только зарегистрированный непрозрачный `export_id` с:

- portal-auth в fail-closed режиме;
- проверкой владельца/объекта;
- allowlisted логической ролью;
- коротким сроком жизни;
- audit event;
- проверкой фактической доступности через production nginx.

### 6.2. Baseline

На production-копии измеряются:

- общий объём и число файлов;
- hardlink-группы и orphan;
- P50/P95/MAX PDF, ZIP и run;
- peak RSS upload/unpack/package/export;
- peak local disk при migration;
- частота чтений PDF, страниц, кропов и exports;
- стоимость хранения, PUT/GET/egress;
- реальное время восстановления производных данных.

### 6.3. S3 ADR

До инфраструктуры фиксируются провайдер/регион, bucket layout, encryption,
versioning, object lock при необходимости, lifecycle, backup, RPO/RTO,
credentials, rotation, audit, egress и область C-07.

Это гейт сегмента 2.0: без утверждённого S3 ADR и явной границы C-07 запрещено
начинать `s3_shadow_write` сегмента 2.3. Этап 1 за этот артефакт не отвечает.

## 7. Сегмент 2.1. Потоковый ingest

Сегмент подробно описан в [отдельном документе](02_01_streaming_ingest.md).
Ключевые гарантии:

- большие файлы не собираются целиком в RAM;
- `.part` не виден публикации;
- ZIP проверяется до и во время распаковки;
- classify/precheck выполняются один раз;
- browser upload использует тот же контракт, что будущий adapter;
- версия публикуется только после полного manifest.

## 8. Сегмент 2.2. Storage Core

### 8.1. `blob_id`

`blob_id` — непрозрачный случайный идентификатор управляемого файла. Он не
равен пути, имени, SHA-256 или S3 key. SHA-256 является свойством целостности,
но не публичной идентичностью.

Сокращённый пример manifest schema 2:

```json
{
  "schema_version": 2,
  "files": [
    {
      "role": "source_pdf",
      "blob_id": "blb_01J...",
      "size": 15324891,
      "sha256": "...",
      "media_type": "application/pdf",
      "storage_class": "durable"
    }
  ]
}
```

Object key строит только storage adapter. Бизнес-смысл и пользовательское имя
в key не кодируются. Provenance не дублируется в файловой записи: input manifest
хранит один `ProvenanceRecord` точной формы из этапа 1 §6.5.

### 8.2. Storage Service API

Минимальный интерфейс:

```python
put_path(path, *, role, expected_sha256=None) -> BlobRef
put_stream(stream, *, role, size_limit, expected_sha256=None) -> BlobRef
open_stream(blob_id, *, byte_range=None) -> BinaryIO
materialize(blob_id, *, expected_sha256) -> Path
stat(blob_id) -> BlobStat
delete(blob_id, *, reason, retention_token) -> DeleteReceipt
ensure_derived(recipe, source_blob_ids) -> DerivativeRef
```

Все вызовы идемпотентны в рамках operation key. Частичный PUT не публикуется в
manifest. Неизвестная роль считается долговечной до явной классификации.

### 8.3. Local adapter

До подключения S3 тот же интерфейс работает поверх локального durable root.
Это позволяет перевести producers/readers на контракт отдельно от
инфраструктурного cutover.

### 8.4. Manifests

- `input_manifest.json` фиксирует полный комплект версии;
- `run_manifest.json` фиксирует полный завершённый run;
- каждый manifest содержит обязательный `schema_version`;
- schema 1 этапа 1 остаётся читаемой; обязательный `blob_id` означает schema 2;
- миграция v1 → v2 выполняется через shadow/backfill, а не добавлением
  обязательного поля под прежним номером;
- manifest публикуется последним;
- опубликованный manifest неизменяем;
- исправление создаёт новый manifest/run, а не правит историю;
- указатель current переключается только на полностью доступный набор blobs.

## 9. Классы хранения

### 9.1. Класс A — долговечные

- исходные PDF и невоспроизводимые вложения;
- OCR/result/HTML/blocks, если их нельзя гарантированно восстановить;
- input/run manifests;
- итоговые findings, norm checks, optimization и expert exports;
- пользовательские вложения и импортированные решения;
- migration journal и доказательства целостности.

### 9.2. Класс B — производные

- изображения страниц;
- миниатюры;
- восстанавливаемые кропы;
- временные Excel/ZIP exports;
- materialized копии.

Для них manifest хранит recipe, версию алгоритма и исходные `blob_id`.
Постоянное хранение определяется измеренной стоимостью восстановления.

### 9.3. Класс C — временные

- `.part`;
- staging unpack;
- промежуточные файлы незавершённого run;
- локальные lock/lease;
- ephemeral package worker.

Потеря класса C не должна приводить к потере опубликованной версии или run.

## 10. Запись нового файла

```text
ingest precheck
  → put_path/put_stream
  → checksum + verified BlobRef
  → полный manifest во временном состоянии
  → document lock
  → publish manifest
  → switch current pointer
  → release staging по retention
```

Если legacy mirror временно сохраняется после 1Б, ошибка зеркала не откатывает
каноническую S3/v2-запись. Она ставится на отдельный reconciliation retry.

## 11. Чтение

### 11.1. UI

- PDF поддерживает Range;
- `content_url` короткоживущий и авторизованный;
- чувствительные объекты можно проксировать через backend;
- список файлов не раскрывает bucket/key;
- cold derivative возвращает `pending + recipe_id`, UI делает fetch+poll и
  показывает placeholder.

### 11.2. Существующий pipeline

```text
resolve blob_id
  → cache hit с верным size/SHA? → Path
  → cache miss → GET в .part → verify → atomic rename → Path
```

Один `blob_id` материализует один процесс; остальные ждут lock. В рамках run
source PDF скачивается один раз. Pipeline продолжает работать с проверенным
локальным `Path`, поэтому не требует одномоментного переписывания.

## 12. Сегмент 2.3. Собственный S3 для новых записей

Порядок включения:

1. создать private bucket и policy;
2. реализовать S3 Adapter за Storage Service;
3. проверить multipart, abort, retry и checksum;
4. включить `s3_shadow_write` для тестового объекта;
5. сравнивать local/S3 размер и SHA-256;
6. перевести новые input manifests и complete run manifests на dual reference;
7. включить canary read;
8. только затем использовать S3 для новых production-записей.

Feature modes должны быть явными, например:

```text
local_primary
s3_shadow_write
s3_shadow_read
s3_canary_primary
s3_primary
```

Конкретное имя env фиксирует S3 ADR; бизнес-код не проверяет env напрямую.

## 13. Сегмент 2.4. Historical backfill и cutover

### 13.1. Inventory

Read-only инвентаризация охватывает всё `projects_v2`, `_system`, hardlink,
legacy rollback-replica, stage comparison, knowledge base и exports. Для
каждого файла определяется владелец, роль, размер, checksum, retention и
воспроизводимость.

### 13.2. План миграции

- заранее резервируются `blob_id`;
- append-only journal хранится и резервируется вне мигрируемого дерева;
- партии ограничиваются по байтам и local free space;
- повтор не создаёт второй PUT;
- orphan S3 object определяется и убирается только по retention;
- неизвестный файл не удаляется автоматически.

### 13.3. Cutover

```text
dry-run inventory
→ shadow upload
→ full checksum parity
→ shadow read
→ canary-primary по объекту
→ S3-primary
→ observation
→ restore drill
→ controlled local cleanup
```

При высоком заполнении диска нужен отдельный staging volume. Расчёт места
выполняется до первой партии, а не после заполнения.

## 14. Сегмент 2.5. Source adapters

Политика описана в [ADR](ADR_external_sources_are_optional.md).

Обязательный adapter:

- browser upload.

Допустимые опциональные adapters:

- authenticated HTTPS pull;
- read-only внешний S3;
- push во входной quarantine prefix собственного S3.

MVP adapter допускается только для одного источника и точного locator. Внешний
каталог, webhook, polling и multi-source routing не являются критериями этапа
2. Отсутствие adapter не блокирует завершение этапа.

Любой adapter заканчивается одной последовательностью:

```text
resolve exact generation → stream → common ingest → own blob → manifest
```

После публикации внешний locator хранится только как provenance.

## 15. Сегмент 2.6. Производные данные и быстродействие

`ensure_derived(recipe)` является единственной точкой получения страницы,
миниатюры, кропа или export:

1. вычисляется стабильный recipe key;
2. готовый derivative возвращается сразу;
3. при miss создаётся одна background job;
4. API возвращает `pending`;
5. результат проверяется, получает `blob_id` или cache reference;
6. UI подставляет `content_url` без полного reload.

Heavy render не выполняется внутри request process. Кэш имеет лимит байтов,
LRU/retention, pin активного run и защиту от stampede.

Метрики:

- P50/P95/P99 Range и full GET;
- cache hit ratio;
- materialize bytes/time;
- derivative queue time;
- PUT/GET/egress cost;
- peak RSS и local disk;
- время открытия project/findings/PDF.

## 16. Сегмент 2.7. Эксплуатация

### 16.1. Security

- private bucket, deny public access;
- TLS и encryption at rest;
- отдельные роли runtime/migration/backup;
- минимальный bucket/prefix access;
- короткоживущие credentials и rotation;
- signed URL не попадает в логи;
- удаление требует retention policy и audit event.

### 16.2. Backup и DR

- bucket versioning/lifecycle;
- backup manifests и migration journal отдельно от blobs;
- регулярная выборочная и полная проверка restore;
- документированные RPO/RTO;
- защита от ошибочного массового удаления;
- восстановление проверяется без внешнего источника.

### 16.3. Reconciliation

Регулярно проверяются:

- manifest без blob;
- blob без manifest;
- размер/checksum mismatch;
- незавершённый multipart;
- stale `.part` и staging;
- cache corruption;
- неполный mirror;
- превышение quota/retention.

## 17. Удалённые воркеры

Воркеры не получают S3 credentials. Центр:

1. резолвит manifests;
2. материализует либо потоково собирает защищённый package;
3. передаёт package штатным каналом;
4. принимает result package;
5. публикует complete run через Storage Service.

Worker package не собирается как общий `dict[str, bytes]`. При offline-работе
воркер опирается только на выданный пакет и локальную очередь.

## 18. Ошибки и rollback

| Сбой | Поведение |
| --- | --- |
| staging full | остановить ingest до публикации, показать точную квоту |
| checksum mismatch | карантин, версия не публикуется |
| S3 PUT timeout | идемпотентный retry/abort multipart |
| manifest publish failed | blobs остаются orphan-candidates до retention |
| cache corruption | удалить cache entry и materialize заново |
| S3 read outage | ограниченный local fallback только в утверждённом режиме |
| external adapter failed | browser upload остаётся доступным |
| canary mismatch | вернуть чтение на local primary, не удалять S3 blobs |

Rollback переключает facade mode, а не переписывает пути в бизнес-коде.

## 19. Фазы реализации

| Фаза | Содержание | Выходной гейт |
| --- | --- | --- |
| A | 2.0 security + baseline | auth закрыт, capacity и ADR утверждены |
| B | 2.1 streaming ingest | browser upload и packages не линейны по RAM |
| C | 2.2 Storage Core + local adapter | producers/readers работают через facade |
| D | 2.3 S3 shadow для новых записей | checksum parity и canary PASS |
| E | 2.4 historical backfill | полный inventory/journal/parity |
| F | S3-primary | restore drill и observation PASS |
| G | 2.6 derivatives/cache | пользовательские P95 и cost budget достигнуты |
| H | 2.5 adapter при наличии контракта | независимый пилот; не блокирует этап |
| I | 2.7 operations handoff | runbooks, alerts, ownership и rollback готовы |

Фаза H намеренно расположена после формирования общего контура и может быть
пропущена без изменения статуса остальных фаз.

## 20. Владельцы до начала production-работ

Нужно назначить владельцев:

- этапа 2 и cutover;
- security hotfix;
- S3 infrastructure/finops;
- Storage Service;
- ingest/frontend;
- migration/reconciliation;
- backup/DR;
- optional source adapter, если он одобрен.

Неназначенный optional adapter не блокирует основной этап. Неназначенные
storage, security и DR владельцы блокируют S3-primary.

## 21. Измеримые критерии завершения этапа 2

Этап считается завершённым, когда:

1. старый внешний этап отсутствует в active roadmap;
2. browser upload проходит единый потоковый ingest;
3. Storage Service является единственной точкой работы с долговечными файлами;
4. все source и complete run файлы имеют `blob_id`, размер и SHA-256;
5. input/run manifests имеют известный `schema_version`, schema 2 содержит
   обязательные `blob_id`; публикация атомарна и неизменяема;
6. собственный private S3 является primary для управляемых байтов;
7. historical backfill имеет полный journal и checksum parity;
8. local disk можно очистить без потери опубликованных данных;
9. pipeline получает проверенный `Path` через `materialize`;
10. PDF Range и derivative fetch+poll работают в UI;
11. remote workers не имеют S3 credentials;
12. export download закрыт по auth и opaque ID;
13. backup/restore drill проходит в пределах RPO/RTO;
14. canary и rollback проверены на production-подобном контуре;
15. P95, peak RSS, disk и cost соответствуют утверждённым бюджетам;
16. S3 ADR и граница C-07 утверждены до первого `s3_shadow_write`;
17. optional adapter, если отсутствует, не влияет на критерии 1–16.

## 22. Что изменится для пользователя

- большие загрузки перестанут зависеть от объёма RAM backend;
- документ и результаты сохранятся независимо от локального диска и внешних
  ссылок;
- PDF сможет открываться диапазонами;
- при cold miss UI покажет подготовку миниатюры/кропа, а не зависнет;
- ручная загрузка останется доступной;
- внешний импорт появится только как дополнительный удобный канал.

## 23. Связанные документы

- [глобальный план](00_global_plan.md)
- [сегмент 2.1](02_01_streaming_ingest.md)
- [ADR внешних источников](ADR_external_sources_are_optional.md)
- [этап 1 — идентичность](01_storage_and_identity_rules.md)
- [этап 1Б — `projects_v2_primary`](01b_projects_v2_write_cutover.md)
- [этап 3 — PostgreSQL](03_postgresql_metadata.md)
