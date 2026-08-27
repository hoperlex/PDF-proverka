# ADR-0017. Route Strangler, typed boundary и FSD для Next frontend

**Статус:** proposed<br>
**Дата:** 2026-08-27<br>
**Владельцы:** frontend architecture, API contract owner<br>
**Утверждено:** не утверждено<br>
**Decision deadline:** до W1-WEB-04<br>
**Supersedes:** нет; детализирует ADR-0004<br>
**Связанные task IDs:** W0-ADR-09, W1-API-02, W1-WEB-02, W1-WEB-04, W1-INT-02<br>
**Затронутые принципы Bible:** P-04, P-10, P-13–P-15

## 1. Контекст

Behavior baseline фиксирует отсутствие типизированных response schemas у
основного legacy API snapshot. Генерация TypeScript client до response models
создаст `unknown` и не даст фактической границы TypeScript strict. Одновременно
ожидание полного backend rewrite позволит legacy mega-files продолжать расти.

Фактическая read-only поверхность выбранного пилота ограничена восемью `GET`
под `/api/workers/distributed/*`. Его текущий frontend расположен ровно в
`distributed-service.js`, `distributed-feature.js`, `distributed-page.js`.
`npm run lint` покрывает эти три файла, а `tsconfig.distributed.json` на момент
решения покрывает только service/feature и использует `strict: false` — это
известный baseline gap. Пилот добавляет page в legacy check coverage, но новый
Next-код и generated boundary компилируются отдельным `strict: true` config.
Существующий service уже содержит mock scenarios и ручные runtime guards; они
являются входным behavior fixture, а не вторым постоянным API-клиентом.

Next использует специальный каталог `app`, а FSD — слои App/Pages. Для
совместимости с официальным FSD linter конфликт должен решаться явно.

## 2. Решение

Каждый frontend route мигрируется в строгом порядке:

```text
golden master response формы пилотного slice
  → backend response_model только этого slice
    → OpenAPI-generated client + contract-derived runtime schemas
      → FSD route на mock
        → read-only internal route
          → mutation contracts/AuthZ → canary → primary
```

Все legacy endpoints заранее не типизируются. Типизируется ровно срез текущего
маршрута. Runtime schema генерируется из того же OpenAPI, что client; ручная
копия Zod schema запрещена.

### 2.1. Раскладка

```text
src/
  app/        # Next App Router: route/layout/loading/error, тонкие re-exports
  _app/       # FSD App: providers и frontend infrastructure
  _pages/     # FSD Pages: композиция полного экрана
  widgets/
  features/
  entities/
  shared/     # ui-kit, generated API, runtime schemas, lib/config
```

`page.tsx` экспортирует публичный API `_pages` и не реализует domain/use-case.
Импорты идут вниз; каждый slice экспортирует `index.ts`, при смешении server и
client API — `index.server.ts`. Deep imports и cross-imports slices одного слоя
запрещены и проверяются Steiger/ESLint boundaries.

Raw HTTP доступен только generated transport в `shared/api`. Slice `api`
содержит query/mutation hooks над этим transport. Server state хранится в query
cache (default candidate — TanStack Query), UI state — локально/в feature store;
глобальный domain store запрещён.

Рабочие экраны преимущественно client-first: RSC используется для shell, auth,
простых списков и первичной загрузки, но не становится вторым backend и не
дублирует business rules/API control plane.

Ориентир декомпозиции текущего UI:

| Текущая область | Целевая зона |
| --- | --- |
| `currentView`/`navigate()` | исчезает; Next routes в `app/` |
| дерево объект → раздел → проекты | `widgets/project-sidebar`, `entities/object`, `entities/discipline` |
| карточки/фильтры/батч-выбор проектов | `_pages/projects`, `entities/project`, узкие features |
| плитки stages и retry | `widgets/stage-tiles`, `features/retry-stage` |
| WS/polling/resync live status | `entities/job/model`, `shared/api/realtime` |
| findings и фильтры | `_pages/findings`, `entities/finding` |
| expert verdict | `features/expert-verdict` |
| discussion/SSE | `features/discuss-finding` |
| upload/precheck wizard | `features/upload-project` |
| batch queue/pause | `features/batch-audit`, `widgets/queue-panel` |
| blocks/crops/vector graph | `_pages/blocks`, `entities/block` |
| stage comparison/PDF panes | `_pages/stage-comparison`, `widgets/pdf-pane` |
| distributed overview (пилот) | `_pages/distributed-overview`, `entities/distributed-snapshot` |
| worker admin из `audit-workers.js` | будущие `_pages/worker-admin`, `entities/worker`; вне pilot scope |
| `version_api.js` | `entities/version/api` поверх generated transport |

### 2.2. Первый route

Пилот — read-only overview «Распределённые вычисления» по
`/next/distributed`. Он использует существующее изолированное UI-разбиение и не
затрагивает основной аудит. Retry/transfer/intake и другие mutations остаются в
legacy до типизированных mutation contracts и object-level AuthZ.

Его backend contract содержит ровно восемь операций:

1. `GET /api/workers/distributed/snapshot`;
2. `GET /api/workers/distributed/overview`;
3. `GET /api/workers/distributed/workers`;
4. `GET /api/workers/distributed/queue`;
5. `GET /api/workers/distributed/tasks`;
6. `GET /api/workers/distributed/limits`;
7. `GET /api/workers/distributed/diagnostics`;
8. `GET /api/workers/distributed/recommendation`.

В scope входят response models/OpenAPI/runtime schemas этих восьми GET, текущие
mock scenarios и отображение одного overview route. Не входят
`audit-workers.js`, `/api/workers/{worker_id}`, providers/jobs/admin endpoints и
любые `POST/PATCH/PUT/DELETE`. Расширение списка — новая contract task, а не
«уточнение» W1-WEB-02.

`/next/*` является временным internal/role-gated prefix. После canary route
получает канонический URL через reverse-proxy routing по user/object; старый
route остаётся быстрым rollback target. W4 означает массовый primary cutover, а
не первый production Next route.

## 3. Последствия

- пользователь получает первый Next route в W1/W2, не через год;
- generated client имеет реальные response types;
- пилот проверяет routing, auth shell, telemetry и CSS isolation с низким
  бизнес-риском;
- временно поддерживается proxy split и два route implementations;
- FSD naming использует `_pages`, а не неофициальный `views`, чтобы не ломать
  стандартный linter.

## 4. Gate

W1-WEB-02 не стартует до W1-API-02. Он переиспользует семантику существующего
mock provider как fixture, заменяет ручные guards contract-derived schemas и
добавляет `distributed-page` в legacy typecheck coverage; новый client/route
проходит отдельный strict TypeScript check. W1-WEB-04 не стартует до generated
client и runtime schemas. `W1-INT-02` закрывается только при ровно 8 GET/0
mutations, zero critical accessibility violations, contract tests, route
telemetry и rollback check.

## 5. Ссылки

- [ADR-0004](ADR-0004-nextjs-frontend.md)
- [Behavior freeze](../../data_storage_modernization/00a_behaviour_freeze.md)
- [Feature-Sliced Design: Next.js](https://fsd.how/docs/guides/tech/with-nextjs/)
- [Next.js project structure](https://nextjs.org/docs/app/getting-started/project-structure)
