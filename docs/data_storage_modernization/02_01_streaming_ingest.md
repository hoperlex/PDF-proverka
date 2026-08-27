# Сегмент 2.1. Потоковый файловый ingest

**Статус:** обязательный ранний срез этапа 2; может разрабатываться параллельно
с этапом 1, но production-публикация через новый контур требует завершённого
этапа 1Б.

## 1. Результат

Все способы получения комплекта — browser upload, локальный админ-импорт и
будущие source adapters — передают данные в один потоковый ingest. Большие PDF
и ZIP не удерживаются целиком в памяти, распаковка выполняется на диске,
классификация и precheck не дублируются.

Сегмент не включает S3 cutover и внешнюю интеграцию. Он создаёт общий вход,
который одинаково работает с локальным Storage Adapter и будущим S3 Adapter.

## 2. Целевой поток

```text
HTTP multipart / локальный Path / source stream
        │
        ▼
лимиты до и во время чтения
        │
        ▼
staging/<ingest_id>/*.part
        │ size + SHA-256 + fsync + atomic rename
        ▼
безопасная распаковка ZIP
        │
        ▼
единый classify_bundle()
        │
        ▼
precheck → план публикации → Storage Service
```

## 3. Staging

Staging задаётся отдельной конфигурацией и не размещается неявно в корне
проекта. Для каждой операции создаётся непрозрачный `ingest_id`.

Минимальные настройки:

```text
AUDIT_INGEST_STAGING_DIR
AUDIT_INGEST_MAX_FILE_BYTES
AUDIT_INGEST_MAX_ARCHIVE_BYTES
AUDIT_INGEST_MAX_EXPANDED_BYTES
AUDIT_INGEST_MAX_FILES
AUDIT_INGEST_MIN_FREE_BYTES
AUDIT_INGEST_RETENTION_HOURS
```

Запись выполняется в `.part`; готовым считается только файл после проверки
размера/checksum и атомарного rename. Cleanup не удаляет активные операции и
использует lock/lease.

## 4. Внутренний контракт

```python
@dataclass(frozen=True)
class IngestedFile:
    logical_name: str
    role: str
    staged_path: Path
    size: int
    sha256: str
    media_type: str | None

@dataclass(frozen=True)
class IngestBundle:
    ingest_id: str
    files: tuple[IngestedFile, ...]
    provenance: ProvenanceRecord
```

Контракт передаёт владение staged-файлом следующему слою явно. Общий API не
принимает `dict[str, bytes]` для крупных комплектов.

`ProvenanceRecord` не определяется повторно в этом документе: это канонический
тип этапа 1, §6.5. Он передаётся без преобразования и один раз записывается в
`input_manifest.json` на уровне всего комплекта; у файлов нет альтернативного
`source_ref`.

## 5. Потоковая browser upload

- request body читается чанками;
- одновременно считаются размер и SHA-256;
- actual-byte limit проверяется во время чтения, а не только по заголовку;
- при обрыве `.part` остаётся недоступным публикации;
- frontend получает `ingest_id`, стадии и безопасный retry;
- несколько проектов из одной родительской папки обрабатываются
  последовательно либо с ограниченным concurrency.

## 6. Безопасная распаковка ZIP

Общий unpacker обязан отклонять:

- абсолютные пути и `..`;
- symlink, hardlink, device и FIFO;
- коллизии имён после нормализации;
- превышение количества файлов;
- превышение размера одного файла и общего expanded size;
- подозрительный compression ratio;
- вложенные архивы, если они не разрешены явной политикой;
- дубли обязательных ролей, включая несколько PDF одного проекта.

Сначала строится план распаковки и проверяются лимиты; только затем создаются
обычные файлы в каталоге операции.

## 7. Единая классификация

`classify_bundle()` получает список имён, размеров и media type и возвращает:

- один source PDF;
- опциональные `*_document.md`, `*_result.json`, `*_ocr.html`, `_blocks.json`;
- неизвестные вложения с явной политикой;
- ошибки и предупреждения;
- предложение `new_document | new_version | duplicate`.

Precheck и save используют один результат классификации. Повторное чтение или
повторная распаковка ради публикации запрещены.

## 8. Интеграция со Storage Service

До сегмента 2.2 ingest может завершаться локальным adapter. После появления
Storage Service публикация выглядит так:

1. каждый файл передаётся в `put_stream`/`put_path`;
2. Storage Service возвращает `blob_id`, размер и подтверждённый SHA-256;
3. строится полный `input_manifest.json` с известным `schema_version`;
4. версия публикуется атомарно последней операцией;
5. staging очищается только после успешной публикации или retention.

Source adapter сегмента 2.5 не меняет эту последовательность.

## 9. Большие внутренние маршруты

Тот же принцип применяется к:

- пакетам распределённого воркера;
- merge/candidate комплектам;
- ZIP-пакетам аудита;
- импорту решений из Excel;
- загрузке версий и stage comparison;
- historical backfill.

TAR/ZIP builder получает `Path` или stream и не собирает общий payload в RAM.

## 10. Атомарность и идемпотентность

- `ingest_id` идентифицирует попытку, но не документ;
- дубликат определяется по составу, ролям и checksum;
- публикация версии выполняется под document lock;
- повтор после сбоя либо продолжает тот же валидный staged object, либо создаёт
  новую попытку без двойной версии;
- provenance соответствует единственному `ProvenanceRecord` этапа 1 и не
  содержит секретов.

## 11. Производительность

Baseline и acceptance фиксируют:

- peak RSS для P50/P95/MAX комплектов;
- скорость upload и unpack;
- максимальное заполнение staging;
- число копирований каждого большого файла;
- время precheck и publish;
- поведение при заполненном диске и обрыве клиента.

Критерий: peak RSS не растёт линейно с размером ZIP/PDF; один крупный файл не
должен одновременно существовать в нескольких `bytes`-копиях процесса.

## 12. Наблюдаемость

Для каждой операции логируются `ingest_id`, источник, стадия, байты, время,
результат checksum, число файлов, предупреждения и причина остановки. Полные
локальные пути, подписанные URL и credentials в обычные логи не попадают.

## 13. Критерии завершения

1. Browser upload не читает крупный комплект целиком в память.
2. ZIP unpacker общий для всех входных каналов и покрыт adversarial tests.
3. Precheck и save используют один `IngestBundle`.
4. Все actual-byte и expanded-size лимиты проверяются.
5. Публикация не видит `.part` и неполные каталоги.
6. Worker package и export не собирают общий `dict[str, bytes]`.
7. Retry не создаёт двойную версию.
8. Browser upload остаётся рабочим rollback независимо от сегмента 2.5.
9. Peak RSS и staging profile измерены на реальных размерах.

## 14. Не входит

- выбор конкретного S3-провайдера;
- выдача S3 credentials;
- historical S3 backfill;
- внешний каталог документов и webhook;
- PostgreSQL metadata cutover.

## 15. Связанные документы

- [глобальный план](00_global_plan.md)
- [этап 2](02_unified_file_storage_and_ingest.md)
- [ADR внешних источников](ADR_external_sources_are_optional.md)
- [этап 1Б](01b_projects_v2_write_cutover.md)
