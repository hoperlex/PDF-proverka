# ADR-0014. Классификация данных, retention и контролируемое удаление

**Статус:** proposed<br>
**Дата:** 2026-08-27<br>
**Владельцы:** product/data owner, security/privacy, storage operations<br>
**Утверждено:** не утверждено<br>
**Decision deadline:** до первого production canary с новым хранилищем<br>
**Supersedes:** нет<br>
**Связанные task IDs:** W0-SEC-01, W0-SEC-02, W0-ADR-05<br>
**Затронутые принципы Bible:** P-03, P-11, P-12, P-14

## 1. Контекст

Проектные PDF, штампы, названия организаций и объектов, findings, экспертные
решения, LLM payload, логи и backups имеют разную ценность и чувствительность.
AuthN/AuthZ отвечает, кто читает данные, но не отвечает, сколько они хранятся,
что удаляется по запросу и когда исчезает последняя backup-копия.

Конкретные сроки нельзя выводить только из архитектуры: нужны применимые
договорные/правовые требования и назначенный владелец данных.

## 2. Варианты

### A. Один TTL для всего

Просто, но либо преждевременно удаляет решения/audit evidence, либо бессрочно
держит тяжёлые и чувствительные artifacts.

### B. Retention по классам данных

Отдельная политика для source documents, derived artifacts, findings/decisions,
model calls, operational logs, exports и backups. Рекомендуемый вариант.

### C. Бессрочное хранение до ручной команды

Минимум кода сейчас, максимум стоимости и privacy/legal риска. Отклоняется как
production default.

## 3. Предлагаемое решение и незакрытая развилка

Принимается структура варианта B, но значения TTL остаются блокирующей бизнес-
и правовой развилкой до заполнения retention matrix:

| Класс | Purpose/legal basis | Active TTL | Archive TTL | Delete trigger | Hold | Owner | Backup expiry |
| --- | --- | --- | --- | --- | --- | --- | --- |
| source documents/versions | решить | решить | решить | решить | да/нет | назначить | решить |
| findings/expert decisions/audit trail | решить | решить | решить | решить | да/нет | назначить | решить |
| derived artifacts/cache/index | operational | решить | не обязателен | source deletion/rebuild | нет | platform | решить |
| LLM request/response evidence | quality/debug | решить | решить | TTL/request | да/нет | analysis owner | решить |
| logs/traces/action journal | operations/security | решить | решить | TTL | да/нет | operations | решить |
| exports/temp uploads | delivery | решить | не обязателен | expiry/abort | нет | storage owner | решить |

До заполнения матрицы новый storage может работать на synthetic/production-copy
данных, но не проходит production canary.

Удаление является durable workflow с `erasure_request_id`, scope, actor,
основанием, legal hold check, journal и доказательством purge. Оно охватывает
PostgreSQL, S3 current/versioned objects, caches, search/read models и backup
expiry. Прямой cascade delete истории по умолчанию запрещён. Если audit evidence
нужно сохранить, PII минимизируется или псевдонимизируется по отдельному правилу.

## 4. Обязательные свойства

- классификация при ingest и наследование класса производными artifacts;
- object/tenant scope для export и erasure;
- legal/contractual hold блокирует purge явно, а не молча;
- удаление source инвалидирует derivatives и presigned URLs;
- backup не обещает немедленный физический purge: фиксируется максимальный срок
  вытеснения и запрет обычного восстановления удалённых данных;
- dry-run, count/size preview, idempotency и post-delete reconciliation;
- отдельные метрики overdue retention и failed purge.

## 5. Пересмотр

При смене юрисдикции/договора, появлении multi-tenant доступа, нового класса
данных или изменении backup topology.

## 6. Ссылки

- [ADR Bible](../ADR_BIBLE.md)
- [S3/storage plan](../../data_storage_modernization/02_unified_file_storage_and_ingest.md)
- [PostgreSQL plan](../../data_storage_modernization/03_postgresql_metadata.md)
