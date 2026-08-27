# ADR-0015. Модель исполнения программы и integration capacity

**Статус:** proposed<br>
**Дата:** 2026-08-27<br>
**Владельцы:** program owner, technical lead<br>
**Утверждено:** не утверждено<br>
**Decision deadline:** W0-DEC-01<br>
**Supersedes:** нет<br>
**Связанные task IDs:** W0-DEC-01, W0-OPS-01<br>
**Затронутые принципы Bible:** P-04, P-11, P-15, P-18

## 1. Контекст

Contract и integration tasks имеют одного ответственного и образуют
последовательное узкое место. Агенты ускоряют независимые implementation tasks,
но не создают дополнительные права принятия архитектурного контракта, migration
head или production cutover. Поэтому календарная оценка команды из четырёх
людей неприменима к одному human integrator без отдельного коэффициента.

## 2. Плановые сценарии

| Сценарий | Capacity | WIP | Предварительный горизонт до G5 | Основной риск |
| --- | --- | --- | --- | --- |
| A. Staffed team | 4 опытных инженера, integration/QA назначены | 1 contract + до 4 implementation + 1 integration | 10–17 месяцев; 40–68 human engineer-months | найм и coordination cost |
| B. Human integrator + agents | 1 человек принимает contracts/integration/cutover, агенты работают по ownership zones | 1 contract + 1–2 implementation + 1 integration | planning range 15–34 месяца до калибровки W0/W1 | очередь ревью, integration и rework |

Диапазоны не являются обещанием. После W0 и W1 они пересчитываются по observed
lead time, integration wait, rework и escaped defects. Стоимость agents/LLM/CI
считается отдельно от human engineer-months.

В сценарии A lane AI принадлежит backend/pipeline/analysis engineer вместе с
JOB и ENG. Это один фактический owner: задачи JOB/ENG/AI для него
последовательны и не считаются тремя параллельными capacity slots. Отдельный
пятый специалист не подразумевается молча; если требуется параллельный AI WIP,
он явно добавляется в staffing и forecast пересчитывается.

## 3. Предлагаемое решение

До явного решения roadmap показывает оба сценария и не смешивает их оценки.
Фактическим default считается сценарий B, если staffing не подтверждён
выделенными людьми. При нём:

- human integrator единолично принимает frozen contract и integration result;
- одновременно активны не более двух implementation tasks в разных zones;
- новый contract не открывается, пока предыдущий integration slot занят;
- агент не меняет accepted ADR, migration head, OpenAPI root или production
  defaults без отдельной integration task;
- wave scope уменьшается, но quality/cutover gates не ослабляются.

Смена A↔B меняет capacity/WIP и календарный forecast, но не архитектурные гейты.

## 4. Доказательства и пересмотр

После W0 и первого vertical slice измеряются:

- доля времени integrator на contract/review/integration;
- очередь готовых agent tasks до integration;
- rework после review и cross-owner conflicts;
- escaped defects и rollback events;
- human hours и agent/LLM/CI cost на завершённый slice.

ADR пересматривается после G1, при найме второго интегратора или если integration
wait превышает 30% lead time двух последовательных волн.

## 5. Ссылки

- [Roadmap §13](../HYBRID_REWRITE_ROADMAP.md)
- [ADR-0005](ADR-0005-parallel-delivery.md)
