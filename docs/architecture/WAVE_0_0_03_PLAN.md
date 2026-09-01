# План version-среза 0.0.03 — закрытие `W0-INT-01`

**Статус:** proposed<br>
**Дата:** 2026-09-01<br>
**Базовый срез:** `version/0.0.02` → `654d276a7911d8ed3e485f9eab50ea95d2276a1e`<br>
**Исходный режим:** clean-room rehearsal W0, observe-first; не G0<br>
**Интегратор:** `W0-INT-01`

## 1. Результат волны

Закрыть два оставшихся blocker'а `W0-INT-01`:

1. подключить versioned `norms/vault` с проверяемым SHA-256;
2. устранить недетерминизм трёх тестов настоящих процессов в полосе `network`;
3. после обоих результатов одним integration change перевести CI из `--ci`
   в `--enforce`, снять маскировку падений и выпустить пригодную clean-room
   расписку.

Закрытие `W0-INT-01` само по себе **не означает прохождение G0**. Общий Gate G0
проверяется отдельно по всем условиям §6 roadmap. До такой проверки массовая
генерация W1-кода, новый `pyproject.toml` и skeleton `src/auditmanager/**` не
начинаются.

## 2. Замороженные входы и ограничения

- runtime/quality contract `quality-runtime/v1`, версия `1.1.0`;
- receipt `docs/architecture/receipts/W0-INT-01.json`, revision 4;
- порядок включения в конце `.github/workflows/ci.yml`;
- baseline из `scripts/ci_known_failures.txt` меняется только после успешного
  provisioning корпуса в точном enforce-профиле;
- `chaos` остаётся отдельной неблокирующей наблюдаемой полосой;
- падение `network` нельзя скрывать новой записью baseline, `skip`, `xfail`,
  quarantine или расширением 90-секундного ожидания без доказанной причины;
- `version/0.0.02` — неизменяемая точка возврата. Работа 0.0.03 идёт на `dev`.

## 3. Пакет A — versioned norm artifact

**Владелец результата:** владелец источника норм совместно с release/OPS.<br>
**Потребитель:** интегратор `W0-INT-01`.<br>
**Можно выполнять параллельно:** с пакетом B.

### Outcome

CI получает `norms/vault/**` из именованного внешнего источника, знает версию
артефакта и ожидаемый SHA-256, а `ci_provision_norms.py` строит производный
`status_index.json` и отказывает при отсутствии либо несовпадении входа.

### Deliverables

- идентификатор и владелец источника, версия/дата сборки, checksum и политика
  доступа без публикации credentials в git или logs;
- wiring шага `Provisioning norm corpus` к этому источнику;
- receipt `ci_provision_norms.py --build-index --enforce` с фактическим SHA-256;
- сверка 33 текущих corpus-зависимых ошибок/записей baseline по реальному JUnit:
  ожидается их исчезновение, любое расхождение разбирается по node ID.

### Verification и stop conditions

Fresh non-root runner обязан получить один и тот же checksum и детерминированно
построить индекс. `NORM_ARTIFACT_MISSING`, отсутствие manifest/checksum,
несовпадение SHA-256, неоднозначное происхождение или необходимость собрать
vault из `norms_db.json` останавливают пакет. До зелёного результата baseline не
перезаписывается.

## 4. Пакет B — детерминизм `network`

**Владелец результата:** владелец распределённого контура.<br>
**Потребитель:** интегратор `W0-INT-01`.<br>
**Можно выполнять параллельно:** с пакетом A; shared workflow не редактируется.

### Обязательный набор

- `tests/test_agent_grpc_client_12c.py::test_agent_restart_adopts_live_executor_higher_epoch_no_duplicate`;
- `tests/test_distributed_workers_executor.py::test_two_executors_never_start_two_processes`;
- `tests/test_distributed_workers_prepipeline_gate.py::test_two_real_processes_overlap_and_third_waits`.

До правки владелец ограничивает allowed paths этими тестами, их fixtures и
минимальным production-кодом распределённого контура, где воспроизведена
причина. Root dependencies, `pytest.ini`, baseline и workflow остаются за
интегратором.

### Evidence matrix

1. Каждый тест — не менее 20 повторов изолированно.
2. Три теста — не менее 20 прогонов с записанными seed и порядком.
3. После исправления — пять полных последовательных прогонов полосы `network`
   в профиле `--ci` на тихом non-root runner.
4. До и после каждого прогона — inventory дочерних процессов, портов и run-root;
   после cleanup остаток равен нулю.

Acceptance требует ноль падений, таймаутов и осиротевших процессов во всей
матрице. Один зелёный прогон не считается снятием недетерминизма. Исправление
обязано назвать root cause: identity/epoch, общий путь/порт, порядок cleanup,
наследование процесса или другой измеренный механизм.

## 5. Пакет C — integration и enforce

**Владелец:** только интегратор `W0-INT-01`.<br>
**Зависимости:** пакеты A и B приняты; выполняется после них последовательно.

1. Подключить norm artifact и выполнить `--build-index --enforce`.
2. Прогнать тесты норм; по JUnit подтвердить судьбу каждой corpus-зависимой
   записи baseline.
3. Пересобрать baseline ровно один раз через
   `scripts/ci_regression_gate.py --record` в том же enforce-окружении и
   закоммитить обоснованный diff. Инструмент обязан сам отказать без корпуса.
4. Заменить `--ci` на `--enforce` у Lane и Chaos.
5. Убрать ветку, гасящую exit code 1 у Lane, и `continue-on-error` у
   regression gate. Коды непригодного прогона 2/3/4/5 продолжают пробрасываться.
6. Выполнить fresh non-root clean-room прогон всех пяти полос, frontend gate и
   aggregate regression gate с provenance исходного commit.
7. Обновить receipt `W0-INT-01`: закрыть задачу только по фактическим
   артефактам; отдельно выпустить G0-readiness delta без заявления о прохождении
   общего Gate G0.

## 6. Приёмка среза 0.0.03

- все пять lane receipt имеют `probe_mode: enforce`, валидные `source_commit` и
  `source_commit_origin`, полный обязательный состав §8 и пригодный JUnit;
- setup завершён во всех полосах; `norm_artifact` — PASS с ожидаемым checksum;
- aggregate gate: новых падений, vanished baseline и baseline-in-skip — 0;
- `network` выполняет evidence matrix §4 без разброса и утечек процессов;
- frontend test/lint/typecheck/build зелёные;
- regression и lane failures блокируют CI; `chaos` остаётся observe-only;
- tracked-дерево чистое, source commit достижим из опубликованной ветки;
- receipt `W0-INT-01` помечает задачу закрытой, но не подменяет отдельный
  verdict Gate G0.

## 7. Rollback и порядок публикации

Integration change остаётся одним revertable commit/change set. При любой
непригодной расписке, новой регрессии, нестабильности `network` или проблеме
provenance CI возвращается в observe-first откатом integration commit; baseline
и внешний norm artifact не подгоняются под красный прогон. Точка возврата к
проверенному состоянию — ветка `version/0.0.02`.

Публикация 0.0.03 выполняется только после приёмки §6: сначала commit evidence и
receipt на `dev`, затем отдельная неизменяемая ветка `version/0.0.03`. До этого
имя версии не создаётся как будто волна уже завершена.
