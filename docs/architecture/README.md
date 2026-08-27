# Архитектура новой платформы AuditManager

Этот каталог является точкой входа в программу гибридной миграции.

## Порядок чтения

1. [ADR Bible](ADR_BIBLE.md) — обязательные принципы, предпочтительные паттерны,
   антипаттерны, quality gates и правила параллельной разработки.
2. [Реестр ADR](ADR_INDEX.md) — принятые решения и ADR, которые блокируют
   следующие production-шаги.
3. [Roadmap](HYBRID_REWRITE_ROADMAP.md) — волны, capability lanes, независимые
   task IDs, зависимости и cutover gates.
4. [Шаблон ADR](ADR_TEMPLATE.md) — форма нового архитектурного решения.
5. [Реестр исключений](EXCEPTIONS.md) — временные нарушения принципов с owner и
   expiry.
6. [Разбор ревью 2026-08-27](REVIEW_DISPOSITION_2026-08-27.md) — принятые,
   оспоренные и оставленные развилкой замечания.
7. [Разбор ревью R2](REVIEW_DISPOSITION_2026-08-27_R2.md) — исправления дефектов,
   внесённых первым ужесточением.

## Иерархия решений

При противоречии используется следующий порядок:

1. явное требование безопасности/сохранности пользовательских данных;
2. новый accepted ADR, который явно supersedes старое решение;
3. ADR Bible после перевода в статус `accepted`;
4. специализированный accepted ADR/contract;
5. roadmap и implementation plan;
6. локальная задача или комментарий в коде.

Противоречие не разрешается молчаливым выбором удобного документа. Оно
фиксируется отдельным ADR или правкой ошибочной ссылки.

## Короткая архитектурная формула

```text
новый control plane: modular monolith + PostgreSQL + private S3
новый UI: Next.js + React + TypeScript
действующий pipeline: временный execution engine за versioned adapter
переход: vertical slices + shadow + parity + canary + rollback
разработка: frozen contracts + независимые ownership zones + integration tasks
LLM: versioned prompts/norms/routing + replay evidence + live quality/cost gate
```

## Связанные программы

- [Хранение и движение данных](../data_storage_modernization/00_global_plan.md)
- [Распределённые audit-worker](../distributed_audit_workers/01_current_architecture_audit.md)
- [Стабильный finding ID](../stable_finding_id.md)
