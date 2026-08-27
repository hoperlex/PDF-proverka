# Разбор архитектурного ревью R3 от 2026-08-27

Раунд R3 закрывает календарный дефект W0 и три уточнения, обнаруженные после R2.
Нормативными источниками остаются ADR Bible, ADR-0015, roadmap и EXCEPTIONS.

| № | Решение | Исправление |
| --- | --- | --- |
| R1 | Принято; выбран ограниченный batching с пересчётом | 13 owner-only решений сведены к 11 contract slots двумя review-batch: `W0-ADR-01/02` и `W0-ADR-06/07`. ADR не сливаются и сохраняют отдельные acceptance/dependencies. W0: 7–9 недель в A, 9–12 в B; fallback 10–14. Горизонт A пересчитан до 11–19 месяцев/44–76 human engineer-months из-за последовательных JOB/ENG/AI |
| M1 | Принято | До baseline жёстким pre-G1 gate является только `≤1 active capability slot`; 20% human integration capacity считается еженедельно с явным denominator, но остаётся отчётной целью |
| M2 | Принято | Таблица default canary budgets переименована в черновик для `W0-ADR-07`/ADR-0011. G2/G4 используют только значения accepted ADR-0011 |
| M3 | Принято | `W0-SEC-03` включает staff provisioning, безопасную выдачу уникальных credentials, подтверждение входа, rotation/revocation и запрет общего пароля. Lead-time включён, expiry EXC-0001 синхронизирован на 2026-10-15 |

## Правило review-batch

```text
13 owner-only decisions
  - 4 individual slots: ADR-0007/0008/0010/0011
  + 2 batch slots: CB-W0-01 и CB-W0-02
  = 13 - 4 + 2 = 11 serialized contract slots
```

Review-batch означает одну подготовленную decision session на общей evidence
base, но не один документ и не групповое «всё или ничего». Если один ADR не
готов или возвращён, его повторное рассмотрение занимает новый slot. W1-задача
может стартовать только после acceptance именно своего ADR.

Review-slot открывается только после готовности обоих проектов ADR; во время
него третья contract task запрещена. Для расчёта взяты 2–3 owner-days на slot:
11 slots дают 22–33 последовательных owner-days, а inventory, provisioning и G0
reconciliation частично перекрываются с этой очередью.

## Измеримый legacy budget

До G1 реестр содержит одновременно не более одного активного product-capability
slot. Дополнительно раз в неделю публикуются:

- часы human integrator на legacy capability;
- доступные integration hours того же периода, зафиксированные в начале недели
  за вычетом отпуска/on-call/обязательного support;
- вычисленная доля и отклонение от reporting target 20%;
- contract-hardening hours отдельно от capability work.

До observed baseline отклонение 20% не останавливает волну. На G1 бюджет новых
legacy capabilities становится равен нулю, поэтому невалидированный процент не
используется как фиктивный gate.

## Provisioning для W0-SEC-03

Закрытие EXC-0001 требует не только включить feature flag. Нужны подтверждённый
список пользователей, уникальные credentials/hashes, защищённый канал первичной
выдачи, успешный вход каждого пользователя, а также owner и процедуры
rotation/revocation. Секреты не фиксируются в git, task tracker, manifests или
logs; общий пароль не считается выполнением задачи.
