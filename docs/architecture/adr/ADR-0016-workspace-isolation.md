# ADR-0016. Изоляция agent tasks: shared checkout или worktrees

**Статус:** proposed<br>
**Дата:** 2026-08-27<br>
**Владельцы:** technical lead, release/integration owner<br>
**Утверждено:** не утверждено<br>
**Decision deadline:** W0-DEC-02 после пилота<br>
**Supersedes:** нет<br>
**Связанные task IDs:** W0-WS-01, W0-DEC-02<br>
**Затронутые принципы Bible:** P-04, P-11, P-13

## 1. Контекст

Текущий `CLAUDE.md` предписывает один checkout на `main`, который должен
оставаться пригодным к релизу. Это упрощает production provenance, но dirty
state одного исполнителя блокирует другого и искусственно связывает независимые
ownership zones. Worktree изолирует filesystem/index, но не решает логические
конфликты OpenAPI, migrations и composition root.

## 2. Варианты

### A. Один shared checkout

Минимум release-процесса, максимум ограничений на параллельный WIP. Подходит для
одного последовательного интегратора.

### B. Worktree на каждую task

Хорошая изоляция, но много веток/cleanup и риск обойти canonical main/release
guard без строгого integration workflow.

### C. Гибрид

Canonical checkout используется только для integration/test/push/deploy;
parallel-safe implementation tasks живут в короткоживущих worktrees/branches.
Contracts, migration head и cutover остаются последовательными. Рекомендуемый
кандидат.

## 3. Пилот и критерий решения

До принятия ADR действует вариант A и текущий `CLAUDE.md`. `W0-WS-01` проверяет
вариант C на двух non-production задачах с непересекающимися allowed paths в
disposable clone либо по отдельному time-boxed исключению; production checkout
и deploy процесс пилот не затрагивает.

Вариант C принимается, если:

- canonical checkout остаётся clean и releasable;
- production source guard подтверждает commit, достижимый из `origin/main`;
- integration выполняется отдельным человеком/change, а не deploy из worktree;
- task card фиксирует worktree, branch, base commit и allowed paths;
- нет потери незакоммиченных изменений и скрытого изменения shared contract;
- cleanup worktree выполняется только после интеграции/явного отклонения.

Если хотя бы одно условие не выполняется, остаётся вариант A. Принятие варианта
C требует одним change обновить `CLAUDE.md`, task template и release runbook.

## 4. Неизменные ограничения

Независимо от варианта один владелец остаётся у frozen contract, migration head,
root lockfile, composition root и production cutover. Worktree не даёт права
параллельно менять эти hotspots.

## 5. Ссылки

- [ADR-0005](ADR-0005-parallel-delivery.md)
- [Production source guard](../../production_source_guard.md)
- [ADR Bible §6](../ADR_BIBLE.md)
