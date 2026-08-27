# ADR-0004. Новый frontend на Next.js, React и TypeScript

**Статус:** accepted<br>
**Дата:** 2026-08-27<br>
**Владельцы:** frontend architecture<br>
**Утверждено:** заказчик, 2026-08-27; явно заданная платформа Next.js/React/TypeScript<br>
**Supersedes:** нет<br>
**Затронутые принципы:** P-04, P-13–P-15

## Контекст

Действующий frontend содержит крупный общий `app.js`, смешивает server state,
UI state и сетевые вызовы и затрудняет независимую разработку экранов. Новый
frontend должен мигрировать маршруты постепенно, а не ждать полного backend
rewrite.

## Решение

Новый frontend использует Next.js App Router, React и TypeScript strict.

- OpenAPI-generated client является единственным базовым HTTP client;
- BFF/read endpoints предоставляют формы, удобные экрану, но не бизнес-решения;
- server-first используется для shell, auth и простых read routes;
- PDF, таблицы, progress и сравнение являются ограниченными client features;
- структура кода строится по feature/vertical slice;
- runtime validation выполняется на API boundary;
- новый route можно включать независимо через routing/feature gate;
- старый и новый UI не редактируют одну сущность одновременно без утверждённой
  ownership/cutover policy.

## Последствия

- frontend-разработку можно вести по маршрутам после заморозки OpenAPI;
- нужен design system и generated-client pipeline до массовой миграции страниц;
- Server Components не должны использоваться как скрытый второй backend;
- для browser-heavy workspace остаётся существенный client bundle, который
  нужно измерять и делить по маршрутам.

## Критерий завершения миграции маршрута

Route имеет loading/empty/error/permission states, telemetry, accessibility,
contract tests и canary. Старый route выключается только после периода
наблюдения и проверки сохранённых ссылок.

## Ссылки

- [ADR Bible](../ADR_BIBLE.md)
- [Roadmap](../HYBRID_REWRITE_ROADMAP.md)
- [ADR-0017: route strangler, typed boundary и FSD](ADR-0017-frontend-route-strangler-and-fsd.md)
