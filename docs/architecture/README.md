# Архитектура новой платформы AuditManager

Этот каталог является точкой входа в программу гибридной миграции.

## Порядок чтения

1. [ADR Bible](ADR_BIBLE.md) — обязательные принципы, предпочтительные паттерны,
   антипаттерны, quality gates и правила параллельной разработки.
2. [Реестр ADR](ADR_INDEX.md) — принятые решения и ADR, которые блокируют
   следующие production-шаги.
3. [Roadmap](HYBRID_REWRITE_ROADMAP.md) — волны, capability lanes, независимые
   task IDs, зависимости и cutover gates.
4. [Quality/runtime contract v1](QUALITY_RUNTIME_CONTRACT_V1.md) — clean-room
   профиль, test lanes, capabilities, timeout/JUnit и baseline policy.
5. [Глоссарий](GLOSSARY.md) — канонические имена сущностей и разбор
   конфликтов действующего словаря.
6. [Domain contract v1](DOMAIN_CONTRACT_V1.md) — идентификаторы, состояния
   и ошибки нового контура.
7. [Route/feature inventory UI v1](WEB_ROUTE_INVENTORY_V1.md) — адресуемые
   маршруты действующего интерфейса, deeplink-параметры и дефекты адресуемости.
8. [Каталог критических journeys v1](CRITICAL_JOURNEYS_V1.md) — 30 сквозных
   пользовательских сценариев с обоснованием критичности и фактическим
   покрытием: где есть детерминированный тест, где только часть шагов и
   почему условие Gate G0 №5 ещё не закрыто
   ([расписка](receipts/W0-BEH-01.json)).
9. [Disposition падений UI](WEB_FRONTEND_DISPOSITION_W0-WEB-02.md) —
   классификация падений Vitest действующего интерфейса с коммитом-причиной.
10. [Шаблон ADR](ADR_TEMPLATE.md) — форма нового архитектурного решения.
11. [Реестр исключений](EXCEPTIONS.md) — временные нарушения принципов с owner и
   expiry.
12. [Разбор ревью 2026-08-27](REVIEW_DISPOSITION_2026-08-27.md) — принятые,
   оспоренные и оставленные развилкой замечания.
13. [Разбор ревью R2](REVIEW_DISPOSITION_2026-08-27_R2.md) — исправления дефектов,
   внесённых первым ужесточением.
14. [Разбор ревью R3](REVIEW_DISPOSITION_2026-08-27_R3.md) — пересчёт W0,
   contract review-batch и уточнение измеримости/security provisioning.
15. [План version-среза 0.0.03](WAVE_0_0_03_PLAN.md) — закрытие двух оставшихся
   blocker'ов `W0-INT-01`, порядок перехода observe-first → enforce и граница
   между закрытием integration task и общим Gate G0.
16. [G0-readiness delta](G0_READINESS_DELTA.md) — состояние каждого условия
   Gate G0 на текущий срез: что проверено, чего нет и что принадлежит
   владельцам других задач. Закрытие `W0-INT-01` — не главное, чего не хватает.
17. [Инвентарь категорий данных v1](DATA_INVENTORY_V1.md) — 55 категорий: где
   продукт хранит данные, кто пишет и читает, есть ли срок хранения, что
   останется на диске после erasure-запроса и какие категории нельзя
   классифицировать без владельца данных. Frozen input для ADR-0014
   (`W0-ADR-05`) и `W0-SEC-02`
   ([расписка](receipts/W0-DATA-01.json)).
18. [Applicability matrix стандарта v3.1](STANDARD_APPLICABILITY_W0-STD-01.md) —
   `W0-STD-01`: 51 положение корпоративного стандарта с решением
   принять/адаптировать/отложить/отклонить/требует подтверждения, где найден
   сам текст (только в истории git) и почему условие Gate G0 №10 ещё не
   закрыто, хотя ни один ADR не считает неподтверждённое положение стандарта
   обязательным ([расписка](receipts/W0-STD-01.json)).
19. [Legacy sustainment register](LEGACY_SUSTAINMENT_W0-LEG-01.md) —
   `W0-LEG-01`: сколько активных capability slot по факту (ноль при пределе
   один), 11 sustainment-обязательств с владельцем, сроком и целевой задачей и
   форма еженедельного отчёта по человеко-часам, которую нечем заполнить
   ([расписка](receipts/W0-LEG-01.json)).
20. [Инвентарь LLM-контура v1](LLM_INVENTORY_V1.md) — промпты, нормативный
   вход, маршрутизация, транспорты, параметры модели и 58 mutable sources с
   пометкой «фиксируемо / нефиксируемо»: что нужно записать, чтобы повторный
   прогон дал тот же ответ, и что непреодолимо — с разбором пятнадцати
   непреодолимых позиций на четыре класса. Frozen input
   для `ADR-0013` (`W0-ADR-04`) и `W0-LLM-02`
   ([расписка](receipts/W0-LLM-01.json)).
21. [План version-среза 0.0.04 и пути к CP1](WAVE_0_0_04_PLAN.md) — граница
   приёмки evidence-фазы 1, честно оставшиеся условия G0 и порядок параллельной
   подготовки redaction, auth и watchdog с последовательным production rollout.

## Презентации

- [Основной пользовательский маршрут](presentations/AUDITMANAGER_USER_WORKFLOW_RU.pdf)
  — объект → проект → версия → аудит → экспертное решение → экспорт;
  [редактируемый ODP](presentations/AUDITMANAGER_USER_WORKFLOW_RU.odp).
- [ADR Bible и roadmap простыми словами](presentations/ADR_BIBLE_ROADMAP_PLAIN_RU.pdf)
  — правила, безопасный переход, волны, gates и текущее состояние;
  [редактируемый ODP](presentations/ADR_BIBLE_ROADMAP_PLAIN_RU.odp).

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

## Эксплуатационные runbook'и

- [Clean-room репетиция W0-OPS-03](receipts/W0-OPS-03-cleanroom-rehearsal.json)
  — non-root прогон по профилю `qr-v1`: что уже работает и что блокирует
  приёмку `W0-INT-01`.
- [Диагностируемый test harness](../ops/TEST_HARNESS_RUNBOOK.md) — прогон lanes
  под бюджетами §7, разбор таймаута и непригодного отчёта, provisioning norm
  corpus и границы observe-first до `W0-INT-01`.
- [Baseline эксплуатации v1](OPS_BASELINE_V1.md) — `W0-OPS-01`: что измерено на
  этом дереве (латентность, RSS, диск, артефакты, длительности этапов) и почему
  `B_p95`, `B_error`, `B_cost` и `B_runs_7d` остаются пустыми до боевого
  развёртывания; форма из 24 величин для §5.1 roadmap и ADR-0011.
- [Диспозиция ветки `dev`](DEV_BRANCH_DISPOSITION.md) — куда назначен каждый из
  двенадцати уникальных коммитов `dev`, какой из них оказался дублем уже
  опубликованного и почему ветку нельзя сливать целиком: она отстала по
  `WAVE_0_0_03_PLAN.md` и откатила бы фиксацию выпуска `0.0.03`.
- [Пилот изоляции рабочих деревьев](WORKTREE_PILOT_W0-WS-01.md) — `W0-WS-01`:
  измеренное сравнение общего чекаута и четырёх изолированных worktree, пять
  выполненных условий `ADR-0016` §3 из шести и находка по шестому — изоляция
  разводит прогоны, но не права на общий файл
  ([расписка](receipts/W0-WS-01.json)).

## Связанные программы

- [Хранение и движение данных](../data_storage_modernization/00_global_plan.md)
- [Распределённые audit-worker](../distributed_audit_workers/01_current_architecture_audit.md)
- [Стабильный finding ID](../stable_finding_id.md)
