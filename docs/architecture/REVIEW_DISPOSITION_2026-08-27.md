# Разбор архитектурного ревью от 2026-08-27

Этот документ сохраняет решение по каждому замечанию: что исправлено, что
оставлено архитектурной развилкой и что оспорено. Источником правил остаются
Bible, ADR и roadmap; этот файл является журналом разбора, а не новой
архитектурой.

| № | Решение | Что изменено |
| --- | --- | --- |
| 1 | Принято как развилка | Создан proposed ADR-0015 с двумя плановыми сценариями: staffed team и один human integrator + agents; roadmap больше не выдаёт оценку четырёх человек за текущую фактическую модель |
| 2 | Частично принято, тезис о зависимости оспорен | ADR-0001/0003/0004/0005 самодостаточны и не зависят от deploy topology ADR-0002; ссылка на `P-XX` не является скрытой зависимостью. Добавлена явная ратификация Bible и ADR-0002 задачей `W0-DEC-01` |
| 3 | Принято | Создан ADR-0013; в источники истины добавлены `AnalysisProfile`, `PromptBundle`, `NormsSnapshot`, `ModelCallRecord`; в волну 0 добавлены inventory и replay cassettes |
| 4 | Принято | Parity разделена на contour, analysis replay и live quality; G2 больше не требует совпадения двух live LLM-ответов |
| 5 | Принято | В граф добавлено явное ребро от storage-facing gate этапа 1Б к `W2-INT-03` |
| 6 | Принято, затем уточнено R2 | До G1 разрешён один bounded legacy capability slot/волна и ≤20% human integration capacity; после G1 бюджет новых endpoint/capability равен нулю; contract-hardening разрешён всегда |
| 7 | Принято | Добавлены стоимость аудита, принятого замечания и расхождение estimate/billing |
| 8 | Принято | Canary/observation gates получили формулы latency/error/cost и минимальные дни/runs от baseline волны 0 |
| 9 | Принято | `accepted plan contract` удалён как несуществующий ADR-статус; тип документа и статус теперь отдельные поля |
| 10 | Принято | Создан `EXC-0001` для выключенной по умолчанию legacy portal auth с owner role, expiry и обязательными контролями |
| 11 | Принято как бизнес/правовая развилка | Создан ADR-0014: рекомендуется retention по классам данных, но сроки нельзя выдумывать без владельца данных и применимых требований |
| 12 | Принято как процессная развилка | Создан ADR-0016: shared checkout остаётся действующим до пилота и явного решения; рекомендуемый кандидат — worktrees для implementation и чистый integration/deploy checkout |

## Frontend/FSD

| Замечание | Решение | Что изменено |
| --- | --- | --- |
| Response models → client → FSD | принято | `W1-API-02 → W1-WEB-02 → W1-WEB-04`; типизируется только read-only pilot slice, а не все legacy endpoints |
| Не ждать W4 | принято | в W1 появляется внутренний `/next/distributed`, затем routes переключаются независимо; W4 остаётся массовым primary cutover, а не первым запуском Next |
| Пилот «Распределённые вычисления» | принято с ограничением | пилот сначала только read-only overview; retry/transfer/intake остаются legacy до AuthZ и mutation contracts |
| `views/` как якобы канонический FSD alias | оспорено | актуальный гайд FSD рекомендует `_app` и `_pages`; выбран совместимый с официальным линтером вариант `app/ + _app/ + _pages/` |
| Слои, public API, границы сети/state | принято с уточнением | raw HTTP только в generated `shared/api`; runtime schemas выводятся из OpenAPI, а не дублируются вручную; query hooks могут жить в slice API |

## Открытые акты утверждения

Документы намеренно не выдают proposed-решения за принятые. На `W0-DEC-01` владелец
программы должен явно:

1. принять или отклонить Bible и ADR-0002;
2. выбрать сценарий исполнения ADR-0015 в `W0-DEC-01`;
3. выбрать режим workspace ADR-0016 после короткого пилота в `W0-DEC-02`;
4. назначить владельцев и сроки retention matrix ADR-0014;
5. принять ADR-0006–0013 и ADR-0017 через назначенные W0-задачи до
   соответствующих W1 implementation tasks.

Новые дефекты, найденные после первого ужесточения, закрыты в
[разборе R2](REVIEW_DISPOSITION_2026-08-27_R2.md).

## Первичные справочные материалы по frontend-развилке

- [Feature-Sliced Design: Usage with Next.js](https://fsd.how/docs/guides/tech/with-nextjs/)
- [Next.js: Project structure and organization](https://nextjs.org/docs/app/getting-started/project-structure)
