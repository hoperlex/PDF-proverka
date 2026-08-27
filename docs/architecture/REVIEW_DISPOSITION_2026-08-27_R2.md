# Разбор архитектурного ревью R2 от 2026-08-27

Раунд R2 проверяет дефекты, появившиеся после первого ужесточения Bible и
roadmap. Источником правил остаются ADR Bible, ADR и roadmap.

> Уточнение R3: лимит одного capability slot остаётся жёстким pre-G1 gate, а
> 20% human integration capacity до появления baseline является отчётной
> метрикой. Актуальная формулировка — в
> [разборе R3](REVIEW_DISPOSITION_2026-08-27_R3.md).

| № | Решение | Исправление |
| --- | --- | --- |
| N1 | Принято; измеримость уточнена R3 | Полный capability freeze перенесён с W0 на G1. До G1 жёстко разрешён один активный product slot на волну, а цель 20% human integration capacity до baseline является отчётной; после G1 — ноль новых legacy endpoints/capabilities |
| N2 | Принято | P-17 явно разрешает неповеденческое contract-hardening существующего legacy API: characterization, response models, schemas, snapshots, telemetry и backward-compatible validation |
| N3 | Принято | Добавлены `W0-ADR-06`→ADR-0010, `W0-ADR-07`→ADR-0011, `W0-ADR-08`→ADR-0012 и `W0-ADR-09`→ADR-0017; W1 dependencies переназначены |
| N4 | Принято и усилено | Добавлен `W0-SEC-03`, который реально закрывает EXC-0001 включением/fail-closed проверкой legacy portal auth; object-level AuthZ нового API больше не является ложным условием закрытия этого исключения |
| N5 | Принято | В сценарии A AI назначен backend/pipeline/analysis engineer; JOB/ENG/AI у одного владельца последовательны и не создают фиктивную capacity |
| N6 | Принято с фактическим уточнением | Пилот ограничен ровно 8 GET и тремя distributed frontend-файлами; `audit-workers.js` и mutations исключены. Lint покрывает три файла, но текущий tsconfig — только два и `strict: false`; W1-WEB-02 закрывает legacy coverage gap, а новый boundary проверяется отдельным strict TS config |

## Legacy budget до и после G1

```text
W0 ───────────── W1 ───────────── G1 ───────────── W2+
  ≤1 slot/wave     ≤1 slot/wave     freeze: 0 new legacy capability
  20% reported     20% reported     contract-hardening still allowed
```

Слот не разрешает новую файловую канонику, writer или storage format. Срочная
работа после G1 требует временного исключения и доказательства, почему новый
контур не способен дать результат в согласованный срок.

## Точная граница frontend pilot

Включены только:

- 8 `GET /api/workers/distributed/{snapshot,overview,workers,queue,tasks,limits,diagnostics,recommendation}`;
- `distributed-service.js`, `distributed-feature.js`, `distributed-page.js` как
  исходная behavior surface;
- существующие mock scenarios и ручные guards как fixtures для generated
  client/runtime schemas.

Исключены `audit-workers.js`, общий `/api/workers/*`, worker/provider/job admin и
все mutations. Расширение scope требует новой contract task.
