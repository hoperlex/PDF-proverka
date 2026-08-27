# ADR-0015. Модель исполнения программы и integration capacity

**Статус:** proposed<br>
**Дата:** 2026-08-27<br>
**Владельцы:** program owner, technical lead<br>
**Утверждено:** не утверждено<br>
**Decision deadline:** W0-DEC-01<br>
**Supersedes:** нет<br>
**Связанные task IDs:** W0-DEC-01, W0-OPS-01<br>
**Затронутые принципы Bible:** P-04, P-11, P-15, P-17, P-18

## 1. Контекст

Contract и integration tasks имеют одного ответственного и образуют
последовательное узкое место. Агенты ускоряют независимые implementation tasks,
но не создают дополнительные права принятия архитектурного контракта, migration
head или production cutover. Поэтому календарная оценка команды из четырёх
людей неприменима к одному human integrator без отдельного коэффициента.

## 2. Плановые сценарии

| Сценарий | Capacity | WIP | Предварительный горизонт до G5 | Основной риск |
| --- | --- | --- | --- | --- |
| A. Staffed team | 4 опытных инженера, integration/QA назначены | 1 contract review-slot + до 4 implementation + 1 integration | 11–19 месяцев; 44–76 human engineer-months | найм, coordination cost и последовательная очередь JOB/ENG/AI |
| B. Human integrator + agents | 1 человек принимает contracts/integration/cutover, агенты работают по ownership zones | 1 contract review-slot + 1–2 implementation + 1 integration | planning range 15–34 месяца до калибровки W0/W1 | очередь ревью, integration и rework |

Диапазоны не являются обещанием. После W0 и W1 они пересчитываются по observed
lead time, integration wait, rework и escaped defects. Стоимость agents/LLM/CI
считается отдельно от human engineer-months.

В сценарии A lane AI принадлежит backend/pipeline/analysis engineer вместе с
JOB и ENG. Это один фактический owner: задачи JOB/ENG/AI для него
последовательны и не считаются тремя параллельными capacity slots. Отдельный
пятый специалист не подразумевается молча; если требуется параллельный AI WIP,
он явно добавляется в staffing и forecast пересчитывается.

### 2.1. Калибровка волны 0

В W0 находятся 13 решений единственного принимающего владельца: `W0-DEC-01/02`,
`W0-ARC-01/02` и `W0-ADR-01…09`. При WIP=1 они являются критическим путём,
даже если inventory и подготовка проектов ADR выполняются параллельно.

Разрешены ровно два review-batch:

- `CB-W0-01`: `W0-ADR-01` + `W0-ADR-02` — PostgreSQL/S3 topology, RPO/RTO и
  граница владения данными на общем `W0-DATA-01`/`W0-OPS-01` evidence;
- `CB-W0-02`: `W0-ADR-06` + `W0-ADR-07` — AuthN/AuthZ и observability/SLO на
  общей production boundary и threat/baseline evidence.

Batch занимает один shared contract slot, но не сливает документы: у каждого
ADR остаются собственные статус, решение, acceptance и downstream dependency.
Один ADR пары можно отклонить или вернуть на доработку независимо; в этом случае
повторное рассмотрение занимает новый contract slot. Остальные решения не
пакетируются без пересмотра этого ADR.

`Contract review-slot` — единица WIP принимающего владельца, а не переименование
двух активных задач в одну. До открытия batch оба проекта ADR и общая evidence
base должны быть готовы; во время review-slot никакая третья contract task не
активна. Вне двух перечисленных batch один slot содержит ровно одну task.

Таким образом, базовая очередь W0 равна 11 contract slots. Planning range W0:

| Сценарий | Диапазон W0 | Допущение |
| --- | --- | --- |
| A. Staffed team | 7–9 недель | inventories готовятся четырьмя владельцами, решения принимает один contract owner |
| B. Human integrator + agents | 9–12 недель | integrator последовательно принимает 11 slots и отдельно закрывает integration/security evidence |
| Fallback | 10–14 недель | хотя бы один batch распался либо provisioning/external decision имеет дополнительный lead time |

Расчёт использует allowance 2–3 рабочих дня принимающего владельца на один
review-slot: 11 slots дают 22–33 owner-days. Evidence/inventory занимает 2–4
календарные недели и перекрывается с ранними решениями; provisioning и финальная
сверка G0 добавляют 1–2 недели, частично перекрывая конец очереди. В сценарии B
тот же человек также интегрирует evidence, поэтому диапазон шире сценария A.

Это прогноз всей W0, а не сумма длительностей задач: inventory, подготовка ADR и
security provisioning перекрываются, но принятие shared contracts остаётся
последовательным.

## 3. Предлагаемое решение

До явного решения roadmap показывает оба сценария и не смешивает их оценки.
Фактическим default считается сценарий B, если staffing не подтверждён
выделенными людьми. При нём:

- human integrator единолично принимает frozen contract и integration result;
- одновременно активны не более двух implementation tasks в разных zones;
- одновременно открыт не более один contract review-slot; только `CB-W0-01/02`
  могут содержать по две заранее подготовленные ADR-задачи;
- новый contract review-slot не открывается, пока предыдущий integration slot занят;
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

С W0 также еженедельно измеряется `legacy integration hours / available human
integration hours`. Denominator — утверждённые в начале недели рабочие часы
назначенного integrator за вычетом отпуска/on-call/обязательного support; numerator
берётся из task/time log только для product-capability slot. До появления
observed baseline и первого завершённого slice
значение 20% является отчётной целью, а не stop gate; жёстким pre-G1
ограничением остаётся один активный legacy capability slot. После G1 бюджет
новых legacy capabilities равен нулю независимо от измеренной доли.

ADR пересматривается после G1, при найме второго интегратора или если integration
wait превышает 30% lead time двух последовательных волн.

## 5. Ссылки

- [Roadmap §13](../HYBRID_REWRITE_ROADMAP.md)
- [ADR-0005](ADR-0005-parallel-delivery.md)
