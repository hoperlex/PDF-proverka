# CP1 task cards — L / S / O / E

**P0_SOURCE_SHA:** `c8475ed72a13a98566ddd9c7e6297ff232d40f62`<br>
**P0_PLANNING_SHA:** `7d9ddc65dbd2ef64a8e472299d7748254e2b566e`<br>
**CP1_BASE_SHA:** не определён до публикации P0<br>
**Форма:** [acceptance-rework/v1](../ACCEPTANCE_REWORK_POLICY_V1.md) §7<br>
**Матрица состояний:** [CP1_STATE_MATRIX.md](CP1_STATE_MATRIX.md)<br>
**Интегратор:** единственный владелец `backend/app/main.py`,
`backend/app/core/config.py`, `.github/workflows/ci.yml`, `conftest.py`,
`docs/architecture/EXCEPTIONS.md`, `contracts/**`, `*_CONTRACT_V1.md`,
`checkpoints/CP1.json` и этих двух файлов.

Общее для всех карточек: `candidate_frozen` выставляется **после** зелёного
preflight, не раньше; до этого он явно `false`. Полный гейт (`python scripts/ci_regression_gate.py`,
исполняется в CI — `ci.yml:270`) — максимум 2 запуска на окно, 1 remediation
между ними, 0 автоповторов, 1800 с на прогон. Любой старт считается попыткой,
включая timeout и отменённый прогон.

**Окружение preflight.** Команды ниже записаны через `$QR_PY` — интерпретатор
**материализованного** профиля `qr-v1`. Голого `python` предполагать нельзя: на
чистом PATH такой команды нет (`command -v python` → 127), а `python3`
разрешается в системный интерпретатор без набора зависимостей профиля.
Материализация — той же командой, что в CI (`ci.yml:102-105`):

```bash
python3 -m venv <venv>
<venv>/bin/python -m pip install --upgrade pip
<venv>/bin/python -m pip install -c constraints-qr-v1.txt -r requirements-dev.txt
export QR_PY=<venv>/bin/python
```

Материализованный venv не обязан лежать в рабочем дереве и в worktree-чекаутах
там его нет — путь берётся из переменной, а не собирается относительно корня.

Правило параллельности из плана §3: **каждый поток сдаёт один reviewable commit
и собственную первичку.** Серия мелких коммитов внутри окна формой сдачи не
является; единственное допустимое добавление — один remediation commit по §4.

---

## P0 — публикация BASE (владелец: интегратор)

```text
policy_id: acceptance-rework/v1
acceptance_window_id: CP1-P0-01
owner: интегратор
P0_SOURCE_SHA:   c8475ed72a13a98566ddd9c7e6297ff232d40f62
  # source candidate: ci.yml + исполняемый тест; по §6 не receipt-only,
  # именно его проверяет полный гейт
P0_PLANNING_SHA: 7d9ddc65dbd2ef64a8e472299d7748254e2b566e
  # planning-docs CP1; non_executable_documentation_only. Отдельного гейта не
  # требует и от гейта source candidate не освобождает: исключение §6 работает
  # только ПОСЛЕ зелёного source candidate, а его ещё не было
CP1_BASE_SHA:    <не определён — присваивается после публикации P0>
  # опубликованный origin/main, на который встают L/S/O. Пустое поле не
  # выдаётся за ноль (правило 4 checkpoints/README)
frozen_scope:
  allowed_paths: [AGENTS.md, .github/workflows/ci.yml,
                  docs/architecture/ACCEPTANCE_REWORK_POLICY_V1.md,
                  docs/architecture/HYBRID_REWRITE_ROADMAP.md,
                  docs/architecture/QUALITY_RUNTIME_CONTRACT_V1.md,
                  docs/architecture/README.md,
                  docs/architecture/WAVE_0_0_04_PLAN.md,
                  docs/architecture/checkpoints/README.md,
                  docs/architecture/policies/acceptance-rework-v1.json,
                  tests/test_acceptance_rework_policy.py,
                  docs/architecture/checkpoints/CP1_STATE_MATRIX.md,
                  docs/architecture/checkpoints/CP1_TASK_CARDS.md]
  non_goals: [перенос W0-SEC-03 на новую базу,
              любые правки redaction/auth/watchdog,
              создание CP1.json в любом виде,
              реализация или переразбиение scope по O-DEC-01..04,
              # четыре долга интегратора — остаются вне окна P0:
              сведение EXC-0003 с review/0.0.04-debts@b0b79211,
              снятие устаревшей записи redaction из CP0.json,
              исправление пути чекаута в AGENTS.md,
              вынесение противоречия про worktrees владельцу W0-DEC-02]
  contracts: [policies/acceptance-rework-v1.json (frozen, enforced 2026-09-07),
              checkpoints/README.md — обязательный минимум полей квитанции]
  fixtures: не затронуты
candidate_frozen: false
preflight:
  - command: $QR_PY -m pytest tests/test_acceptance_rework_policy.py -q
    result: pass на 7d9ddc65 — перепроверить на tip перед заморозкой
    evidence: сверка текста политики с policies/acceptance-rework-v1.json
  - command: $QR_PY -m pytest tests/test_architecture_docs_integrity.py -q
    result: pass на 7d9ddc65 — перепроверить на tip перед заморозкой
    evidence: валидность JSON в docs/architecture/** и разрешимость локальных
      md-ссылок; единственное автоматическое покрытие обоих CP1-файлов
  - command: $QR_PY scripts/ci_runtime_probe.py --profile unit
    result: pass на 7d9ddc65, exit 0 — перепроверить на tip перед заморозкой
    evidence: обязательный capability probe §2 п.3, тот же шаг, что ci.yml:252
  - command: $QR_PY -m pytest
      tests/test_ci_runtime_probe.py::test_frozen_receipt_matches_document -q
    result: red на 933bce78 (§2 отставала от ci.yml с c8475ed7) — зелёный после
      переиздания пина
    evidence: единственная проверка, сверяющая §2 QUALITY_RUNTIME_CONTRACT_V1.md
      и с worktree, и с константами probe; окно P0 изменяет ci.yml через
      c8475ed7, поэтому без неё receipt устаревает молча
attempts:
  - n: 1
    run_id: 34216177648
    run_attempt: 1
    head_sha: f228c08f68b10c81db4d88b48e171c1da3cdba3b   # == candidate
    review_ref: refs/heads/review/cp1-p0-01
    url: https://github.com/hoperlex/PDF-proverka/actions/runs/34216177648
    ci_conclusion: success        # прогон зелёный, но evidence неполон
    jobs: 7/7 success (lanes unit/contract/integration/network,
      regression-gate, frontend, chaos)
    gate: 7682 passed, 233 skipped, 6 deselected; все шесть счётчиков 0
    artifacts: 5/6 — отсутствует regression-gate-report
    result: unsuccessful_incomplete_evidence
findings:
  - id: P0-01-F1
    class: pre_existing_or_flaky
    summary: шаг «Выгрузить отчёт гейта» терял JUnit молча — .ci_last_report.xml
      это дотфайл, а upload-artifact@v4 по умолчанию исключает скрытые файлы;
      if-no-files-found=warn оставлял шаг зелёным
    evidence: дефект присутствует на origin/main@16414088 и НЕ внесён
      диапазоном кандидата 16414088..f228c08f; в логе job'а —
      "No files were found with the provided path: .ci_last_report.xml"
    disposition: отдельное окно (CP1-P0-02); в этом окне не чинится
remediation_commit: null           # ремедиация в этом окне НЕ использовалась
                                   # и НЕ переносится: окно закрыто
terminal_status: split             # окно закрыто терминально; работа
                                   # продолжается в CP1-P0-02
next_task_ids: [CP1-P0-02]
```

**Окно `CP1-P0-01` закрыто терминально со статусом `split`.** Попытка `1/2`
израсходована и неуспешна: прогон был зелёным, но комплект JUnit/artifacts
неполон, а по правилу окна это неуспех. Оставшаяся попытка `2/2` и неиспользо‑
ванная ремедиация **не считаются доступными**: они принадлежали закрытому
окну и на новое не переносятся. `CP1_BASE_SHA` этим окном не получен,
`origin/main` не двигался, merge не создавался.

Находка `P0-01-F1` отнесена к классу `pre_existing_or_flaky`: тот же
`if-no-files-found: warn` и то же умолчание `include-hidden-files: false`
стоят на `origin/main@16414088`, поэтому диапазон кандидата дефект не вносил —
он лишь впервые его проявил. Чинить его внутри закрытого окна нельзя, отсюда
`disposition: отдельное окно`.

---

## P0-02 — публикация BASE с починкой evidence (владелец: интегратор)

```text
policy_id: acceptance-rework/v1
acceptance_window_id: CP1-P0-02
owner: интегратор
predecessor: CP1-P0-01 (terminal_status: split)
outcome: публикация исходного P0-кандидата вместе с исправлением
  обязательной evidence-инфраструктуры
P0_SOURCE_SHA:   c8475ed72a13a98566ddd9c7e6297ff232d40f62
  # неизменен: источник тот же, окно новое
P0_PLANNING_SHA: 7d9ddc65dbd2ef64a8e472299d7748254e2b566e
CP1_BASE_SHA:    <не определён — присваивается после публикации P0-02>
frozen_scope:
  allowed_paths: [.github/workflows/ci.yml,
                  docs/architecture/QUALITY_RUNTIME_CONTRACT_V1.md,
                  docs/architecture/checkpoints/CP1_TASK_CARDS.md,
                  tests/test_acceptance_rework_policy.py]
  non_goals: [публикация в main без санкции freeze,
              полный regression gate до заморозки кандидата,
              правка шагов выгрузки полос и chaos,
              смена пути .ci_last_report.xml,
              перенос попыток или ремедиации из CP1-P0-01,
              # долги интегратора — по-прежнему вне окна P0:
              сведение EXC-0003 с review/0.0.04-debts@b0b79211,
              снятие устаревшей записи redaction из CP0.json,
              исправление пути чекаута в AGENTS.md,
              вынесение противоречия про worktrees владельцу W0-DEC-02]
  contracts: [policies/acceptance-rework-v1.json (frozen, enforced 2026-09-07),
              checkpoints/README.md — обязательный минимум полей квитанции]
  fixtures: не затронуты
candidate_frozen: false
review_ref_after_freeze: refs/heads/review/cp1-p0-02
preflight:
  - command: $QR_PY -m pytest tests/test_acceptance_rework_policy.py -q
    evidence: политика окна плюс новый сторож шага выгрузки отчёта гейта
  - command: $QR_PY -m pytest
      tests/test_ci_runtime_probe.py::test_frozen_receipt_matches_document -q
    evidence: окно снова меняет ci.yml — §2 обязана быть переиздана в том же
      коммите, иначе receipt отстаёт от worktree
  - command: $QR_PY -m pytest tests/test_architecture_docs_integrity.py -q
    evidence: JSON и локальные ссылки изменённых архитектурных документов
  - command: $QR_PY scripts/ci_runtime_probe.py --profile unit
    evidence: обязательный capability probe §2 п.3, тот же шаг, что ci.yml:252
  - command: git diff --check
    evidence: пробелы и конфликтные маркеры в изменённых файлах
attempts:
  - n: 1
    run_id: 34220971371
    head_sha: eb3429845a7aaf288961d8f5efd5ef6a8c967396
    stage: review
    full_gate: success
    workflow: success
    artifacts: 6/6
    result: successful_review
  - n: 2
    run_id: 34221844259
    head_sha: eb3429845a7aaf288961d8f5efd5ef6a8c967396
    stage: post_merge_main
    full_gate: success
    workflow: failure
    artifacts: 6/6
    failed_node: tests/test_parallel_hardening.py::test_rate_limit_deadline_cleared_by_last_waiter
    result: unsuccessful_post_merge_ci
findings:
  - id: P0-02-F1
    class: pre_existing_or_flaky
    evidence:
      - review того же SHA: pass
      - post-merge unit lane: fail
      - regression-gate того же post-merge run: pass
      - 374 diagnostic_only повторов: 0 failures
      - диапазон P0-02 не менял test или manager
    disposition: отдельное уменьшенное окно CP1-P0-03
remediation_commit: null
terminal_status: split
next_task_ids: [CP1-P0-03]
```

**Окно `CP1-P0-02` закрыто терминально со статусом `split`, бюджет `2/2`.**
Попытка 1 — review-прогон на `eb342984`: полный гейт зелёный, workflow
`success`, artifacts `6/6`; она подтвердила, что починка evidence-инфраструктуры
работает. Попытка 2 — post-merge main CI на том же SHA: полный гейт снова
зелёный и artifacts снова `6/6`, но workflow `failure` из-за одного узла в
полосе `unit`. Обе попытки израсходованы, ремедиация не использовалась.

`CP1_BASE_SHA` **не ратифицирован**: регламент требует зелёного post-merge main
CI. При этом `origin/main` фактически опубликован на `eb342984` — это состояние
зафиксировано как есть и не выдаётся за ратификацию.

Находка `P0-02-F1` отнесена к классу `pre_existing_or_flaky` (класса `flaky` в
реестре нет и он не используется): дефект существовал до окна, диапазон
`16414088..eb342984` не менял ни `tests/test_parallel_hardening.py`, ни
`backend/app/pipeline/manager.py`. Чинить его внутри закрытого окна нельзя —
отсюда `disposition: отдельное уменьшенное окно CP1-P0-03`.

---

## P0-03 — cancellation-safe waiter accounting (владелец: интегратор)

```text
policy_id: acceptance-rework/v1
acceptance_window_id: CP1-P0-03
owner: интегратор
predecessor: CP1-P0-02 (terminal_status: split, бюджет 2/2)
base_sha: eb3429845a7aaf288961d8f5efd5ef6a8c967396
outcome: cancellation-safe accounting rate-limit waiters и детерминированное
  доказательство shared-deadline contract
frozen_scope:
  allowed_paths: [backend/app/pipeline/manager.py,
                  tests/test_parallel_hardening.py,
                  docs/architecture/checkpoints/CP1_TASK_CARDS.md]
  non_goals: [изменение бизнес-семантики rate-limit,
              retry/skip/xfail/baseline,
              sleep для стабилизации теста,
              правка ci.yml или любого §2 frozen input,
              общий refactoring PipelineManager,
              self._sleep или другой production seam только ради теста,
              rerun run 34221844259,
              долги / L / S / O / production]
  contracts: [policies/acceptance-rework-v1.json (frozen, enforced 2026-09-07)]
  fixtures: не затронуты
candidate_frozen: false
attempts: []
findings: []
remediation_commit: null
terminal_status: null
review_ref_after_freeze: refs/heads/review/cp1-p0-03
preflight:
  - command: $QR_PY -m pytest tests/test_parallel_hardening.py -q
  - command: $QR_PY -m pytest tests/test_paid_api_reservation.py
      tests/test_parallel_hardening.py -m unit -q
  - command: $QR_PY -m pytest -m unit -q
  - command: $QR_PY -m pytest tests/test_acceptance_rework_policy.py -q
  - command: $QR_PY -m pytest tests/test_architecture_docs_integrity.py -q
  - command: $QR_PY -m pytest
      tests/test_ci_runtime_probe.py::test_frozen_receipt_matches_document -q
  - command: git diff --check
next_task_ids: [CP1-L-01, CP1-S-01, CP1-O-01, CP1-E-01]
```

**Продуктовый инвариант.** После `self._rate_limit_waiters += 1` любой выход —
`return`, исключение или `CancelledError` — проходит через один `finally`,
который возвращает счётчик и снимает общий дедлайн, только когда ушёл
последний ждущий. `try` открывается непосредственно после регистрации, до
первого следующего `await`; вычисление `effective_wait` тоже внутри
защищённой области, чтобы синхронный отказ после регистрации не оставлял
состояние. Happy-path, разбежка, `RATE_LIMIT_MAX_WAIT`, scanner fallback и
формат логов не менялись.

**Достижимость дефекта.** Между регистрацией и прежней границей `try` стоял
единственный `await` — лог разбежки. Он выполняется при `stagger > 0`, то есть
ровно когда в ожидании уже есть сосед. Отмена там навсегда оставляла лишнего
ждущего: счётчик не возвращался к нулю, последний реальный waiter не мог снять
общий дедлайн, и следующий эпизод наследовал протухшее время сброса.

**Оракул теста.** Прежний узел утверждал только «вернулось `True`» и потому был
зелёным на двух разных ветках сразу — по известному времени сброса и через
scanner fallback. Новый контракт наблюдает число пробуждений и опубликованный
дедлайн, поэтому ветка фиксируется, а не угадывается: `I2` — пока `W>0`,
дедлайн не снимается; `I3` — последний вышедший даёт `W=0` и `D=0.0`; `I4` —
следующий непересекающийся эпизод не наследует дальний дедлайн; `I5` — после
отмены `W` возвращается к значению до входа.

**Изоляция.** Подмены ставятся на ССЫЛКИ в namespace менеджера
(`manager.asyncio`, `manager.claude_runner`, `manager.global_scanner`,
`manager.ws_manager`), а не на методы процессных singleton'ов и не на общий
модуль `asyncio`. `RATE_LIMIT_CHECK_INTERVAL` и `RATE_LIMIT_STAGGER_SEC`
пинятся явно. Настоящий `asyncio.sleep` захватывается до подмены и
используется как `sleep(0)`: точка уступки циклу сохраняется, ожидания по
стенным часам нет.

Бюджет окна `CP1-P0-03`: попыток `0/2`, ремедиаций `0/1`; полный гейт не
запускался. `ci.yml` не затронут, §2 pin не менялся.

**Что чинит окно CP1-P0-02.** Шаг «Выгрузить отчёт гейта» получает
`include-hidden-files: true` (отчёт — дотфайл) и `if-no-files-found: error`
(пропажа обязательного evidence обязана красить прогон). Путь
`.ci_last_report.xml` сохранён точно: он совпадает с `JUNIT` в
`scripts/ci_regression_gate.py`, и расхождение дало бы ту же тихую потерю по
другой причине. Шаги полос и `chaos` не трогались — они грузят каталог
`.ci/reports/` и дефекту не подвержены.

Правка `ci.yml` снова меняет зафиксированный §2 вход, поэтому тем же
логическим коммитом переиздан пин (`c89bea9d70a4…` → `2805d8da7038…`) и
добавлен сторож
`test_gate_report_upload_preserves_evidence`: таблица §2 ловит факт изменения
файла, но не сказала бы, какой именно параметр съехал. Сторож проверен
мутациями — краснеет на `include-hidden-files: false`, на
`if-no-files-found: warn` и на расхождении пути с `JUNIT`.

Бюджет окна `CP1-P0-02`: попыток `0/2`, ремедиаций `0/1`; полный гейт не
запускался.

**Важно:** `c8475ed7` изменил `.github/workflows/ci.yml` и добавил
исполняемый тест — по §6 политики это **не** receipt-only, поэтому полный гейт
перед merge обязателен. Planning-docs поверх него гейта не требуют, но и не
освобождают от него: исключение §6 действует только **после** зелёного source
candidate, а его ещё не было. Окно одно, гейт один, покрывает весь диапазон.
В окне `CP1-P0-01` гейт был запущен один раз (run `34216177648`) и израсходовал
попытку `1/2`; окно закрыто со статусом `split`, счётчик на `CP1-P0-02` не
переносится.

**Почему preflight не использует селектор.** `-k "document_contract or receipt"`
собирает 26 тестов из шести файлов (`test_ci_evidence_bundle`,
`test_ci_runtime_probe`, `test_ci_test_lane`, `test_ci_timeout_plugin`,
`test_permission_boundary_12f`, `test_stage01_evidence_context`) и **не
включает** `test_architecture_docs_integrity.py` — единственную автоматическую
проверку изменённых архитектурных документов, обоих CP1-файлов и нового
`policies/acceptance-rework-v1.json`. По §2 п.1 и п.4 preflight обязан покрывать
изменённые файлы, ссылки и JSON, поэтому тесты названы путями.

**Цена этого выбора, обнаруженная 2026-09-08.** Отказ от селектора стоил одной
проверки: `test_frozen_receipt_matches_document` содержит «receipt» в имени и
`-k` его бы собрал, а перечисление путями — нет. Окно P0 при этом меняет
`ci.yml` (через `c8475ed7`), то есть ровно тот вход, который этот тест и
сторожит, и §2 контракта молча отставала от worktree. Узел добавлен в preflight
явным путём — четвёртым пунктом выше; из этого не следует возврат к селектору,
следует лишь правило: если окно трогает зафиксированный §2 вход, проверка
receipt обязана быть в preflight поимённо.

Последовательность (план §3, P0): опубликовать review-кандидат → зелёный
GitHub CI → сверить source SHA → merge только проверенного SHA в актуальный
`origin/main` → повторный CI на merge commit. Stop condition: divergence,
красный/отменённый CI, неполный JUnit, несовпадение SHA.

**Вне маршрута P0:** повторная release receipt и создание либо перемещение
ветки `version/0.0.04`. Срез `0.0.04` уже закрыт: расписка выпущена
(`receipts/0.0.04-release.json`), ветка `version/0.0.04` существует и на
`origin`, и локально на одном и том же `772f8523`, а план §2 п.4 объявляет её
**неизменяемой**. Выпускать вторую расписку на тот же срез и двигать
неизменяемое имя маршрут CP1 не должен — P0 публикует planning-документы и
source candidate, а не переоформляет уже закрытый срез.

---

## L — redaction, `W0-LOG-01` (владелец: OPS/logging)

```text
policy_id: acceptance-rework/v1
acceptance_window_id: CP1-L-01
owner: OPS/logging
candidate_sha: <CP1_BASE_SHA + коммит потока L>
  # база — актуальный опубликованный origin/main ПОСЛЕ публикации planning-docs,
  # а не P0_SOURCE_SHA и не P0_PLANNING_SHA
frozen_scope:
  allowed_paths: [backend/app/core/action_log.py,
                  backend/tests/test_action_log.py,
                  tests/test_action_log_api.py,
                  tests/test_ci_redaction.py,
                  docs/action_log.md,
                  docs/architecture/REDACTION_CONTRACT_V1.md,
                  docs/ops/REDACTION_RUNBOOK.md]
  non_goals: [production-включение (это L2),
              изменение ретеншна, правка EXC-0002,
              startup-проверка флага в config.py — заявка интегратору]
  contracts: [DATA_INVENTORY_V1.md D-17..D-24]
  fixtures: не затронуты; негативные проверки строят данные внутри теста
candidate_frozen: false
preflight:
  - command: $QR_PY -m pytest backend/tests/test_action_log.py tests/test_action_log_api.py tests/test_ci_redaction.py -q
    result: не запускался
    evidence: —
  - command: $QR_PY -m pytest tests/test_architecture_docs_integrity.py -q
    result: не запускался
    evidence: REDACTION_CONTRACT_V1.md — новый файл в docs/architecture/**
attempts: []
findings: []
remediation_commit: null
terminal_status: null
next_task_ids: [CP1-E-01]
```

**Outcome L1:** контракт redaction вынесен из комментариев кода в документ;
deny-by-default доказан негативными тестами (секрет / presigned URL / ПДн /
traceback не попадают **ни в один** канал по умолчанию); runbook и rollback
готовы. Production не переключается.

**Обязательный побочный результат:** заявка интегратору на компенсирующий
контроль №4 `EXC-0002` — startup-проверка, отклоняющая старт при
`ACTION_LOG_REDACTION=0` вне явно обозначенного разбора инцидента. Сейчас
контроль не реализован; по преамбуле `EXCEPTIONS.md` это fail-closed-состояние.

**Rollback:** репозиторный — BASE. Runtime `ACTION_LOG_REDACTION=0` — аварийный
режим EXC-0002, не штатный откат. Production rollback target отсутствует.

---

## S — auth, `W0-SEC-03` (владелец: OPS/API + владелец доступа)

```text
policy_id: acceptance-rework/v1
acceptance_window_id: CP1-S-01
owner: OPS/API + владелец доступа
candidate_sha: <перенос review/g0-sec03-code@2d624433 на CP1_BASE_SHA — новый SHA>
  # база — актуальный опубликованный origin/main ПОСЛЕ публикации planning-docs
frozen_scope:
  allowed_paths: [backend/app/core/portal_auth.py,
                  tests/test_portal_auth.py,
                  tests/test_portal_startup_policy.py,
                  docs/portal_auth.md,
                  .env.example]
  non_goals: [включение auth на production (это S2),
              object-level AuthZ (ADR-0010, Gate G2),
              миграция watchdog (поток O),
              изменение EXEMPT_PATHS в одиночку,
              любые секреты в репозитории или журналах]
  contracts: [QUALITY_RUNTIME_CONTRACT_V1.md — правится только интегратором,
              EXC-0001 в EXCEPTIONS.md]
  fixtures: не затронуты
  shared_files_by_request: [backend/app/main.py, backend/app/core/config.py,
                            conftest.py, .github/workflows/ci.yml,
                            docs/architecture/QUALITY_RUNTIME_CONTRACT_V1.md]
candidate_frozen: false
preflight:
  - command: $QR_PY -m pytest tests/test_portal_auth.py tests/test_portal_startup_policy.py -q
    result: не запускался
    evidence: —
  - command: $QR_PY -m pytest tests/ -k "startup or config" -q
    result: не запускался
    evidence: —
attempts: []
findings: []
remediation_commit: null
terminal_status: null
next_task_ids: [CP1-E-01]
```

**Первый шаг — не код, а перенос.** `2d624433` стоит на базе behind 16;
переносится на BASE отдельным review (план P0 шаг 4). Наличие кода не выдаётся
за выполненный rollout.

**Outcome S1:** перенесённый fail-closed кандидат + provisioning receipt:
список 3–4 сотрудников, уникальные hashes, сгенерированные **вне репозитория и
журналов**, защищённая выдача, подтверждение входа, owner/rotation/revocation,
проведённая rollback rehearsal. Общий пароль или передача секрета через git /
task tracker исключение не закрывают.

**Блокирующая связка.** `/api/info` открыт без auth ради cron-watchdog
(`portal_auth.py:40,48`). Изменение этого allowlist согласуется с потоком O;
в одиночку S его не трогает. Оговорка о первичке: связку подтверждают
комментарий `portal_auth.py:40` и наблюдавшиеся инциденты, но **не**
версионированный `staged/webapp-watchdog.sh` — он `/api/info` не запрашивает.
Связка принимается как действующая по fail-closed; снять её может только
идентификация рабочей ревизии watchdog (поток O, шаг 1).

**Rollback:** репозиторный — BASE. `PORTAL_AUTH_ENABLED=false` восстанавливает
EXC-0001 — только аварийно и с записью. Production rollback target отсутствует.

---

## O — watchdog, `W0-OPS-02` шаги 1–3 (владелец: OPS)

```text
policy_id: acceptance-rework/v1
acceptance_window_id: CP1-O-01
owner: OPS
candidate_sha: <CP1_BASE_SHA + коммит потока O>
  # база — актуальный опубликованный origin/main ПОСЛЕ публикации planning-docs
frozen_scope:
  allowed_paths: [docs/ops/WATCHDOG_CONTRACT_V1.md,
                  backend/app/api/routers/health.py,
                  tests/test_health_probes.py,
                  docs/supervision_oom.md,
                  deploy/watchdog/webapp-watchdog.sh]
  non_goals: [шаг 4 — атомарное переключение watchdog (это O2),
              закрытие /api/info,
              включение auth,
              правка комментариев о kill-семантике в backend/app/** до
                идентификации рабочей ревизии watchdog]
  contracts: [ADR-0010 §7 — календарное разведение S2 и шага 4]
  fixtures: не затронуты
candidate_frozen: false
preflight:
  - command: $QR_PY -m pytest tests/test_health_probes.py -q
    result: не запускался
    evidence: —
  - command: $QR_PY -m pytest tests/ -k "action_log_api or info" -q
    result: не запускался
    evidence: —
attempts: []
findings: []
remediation_commit: null
terminal_status: null
next_task_ids: [CP1-E-01]
```

**Шаг 1 — идентификация, а не написание.** Обязательный первый результат:
подтвердить, какая ревизия watchdog реально работает на production, и совпадает
ли она со staged-копией
`docs/distributed_audit_workers/12f1_phaseb/staged/webapp-watchdog.sh`. Без
этого у O2 нет проверяемого отката и он не может стартовать.

**Что шаг 1 обязан разрешить в первую очередь.** Комментарии шести модулей
описывают watchdog, убивающий бэкенд при неответе `/api/info` > 5 с, и двое
ссылаются на наблюдавшиеся инциденты (`audit.py:252` — «инциденты 03.07»;
`main.py:117`). Версионированная staged-копия не делает ни того, ни другого:
`API_URL` присвоен и не использован, `curl` отсутствует, живость меряется
`ss -ltn` по порту 8081, бэкенд не убивается вовсе. Значит staged-копия — не
рабочая ревизия, и контракт пишется по скрипту, снятому с хоста, а не по ней.

**Outcome O1:** kill-семантика вынесена в документ (сейчас источник истины —
комментарии шести модулей, противоречащие версионированному скрипту); liveness/readiness endpoint'ы добавлены (на BASE
их нет); shadow-прогон выполнен, расхождения измерены, shadow receipt выпущен.
Старый watchdog остаётся активен.

**Календарное ограничение:** шаг 4 не выполняется в одну неделю с S2
(`ADR-0010:419`, план §3).

**Решения владельца:** O-DEC-01…04 в [матрице](CP1_STATE_MATRIX.md) — safe stop
до probes; bounded operational probes не расходуют capability slot; liveness
обслуживается вне event loop; шесть chaos tests требуют отдельного non-root job.
`allowed_paths` выше решению O-DEC-03 ещё не удовлетворяет и переразбивается
отдельными окнами.

**Rollback:** для шагов 1–3 откат — сохранённый активный старый watchdog.
Для O2 — обратное переключение на прежнюю ревизию, идентификатор которой пока
неизвестен. Production rollback target отсутствует.

---

## E — интеграция, CP1 receipt (владелец: интегратор)

```text
policy_id: acceptance-rework/v1
acceptance_window_id: CP1-E-01
owner: интегратор
candidate_sha: <коммит CP1.json; отдельный и следующий за проверенным source commit>
frozen_scope:
  allowed_paths: [docs/architecture/checkpoints/CP1.json,
                  docs/architecture/checkpoints/CP1_STATE_MATRIX.md,
                  docs/architecture/checkpoints/CP1_TASK_CARDS.md]
  non_goals: [преждевременный verdict,
              authorizes_next_cutover=true без отдельного gate,
              заполнение production-полей догадкой,
              правка EXCEPTIONS.md — отдельный долг интегратора вне окна,
              удаление rollback-копий, старых blob'ов, JSON-проекций и
                compatibility-флагов до observation (правило 5 README, P-11)]
  contracts: [checkpoints/README.md — обязательный минимум полей квитанции,
              acceptance-rework/v1 §7]
  fixtures: не затронуты
candidate_frozen: false
preflight:
  - command: $QR_PY -m pytest tests/test_architecture_docs_integrity.py -q
    result: не запускался
    evidence: валидность CP1.json и разрешимость ссылок обоих CP1-файлов
  - command: $QR_PY -m pytest tests/ -k "document_contract or receipt or checkpoint" -q
    result: не запускался
    evidence: —
attempts: []
findings: []
remediation_commit: null
terminal_status: null
next_task_ids: []
```

**Выполнено в этом окне:** матрица состояний, границы allowed_paths, shared
files, rollback targets, команды проверки, граница наблюдаемости production.

**Не выполнено и не может быть выполнено здесь:** все три `production_state`.
CP1 собирается только после L2, S2 и O2 (план §4); до этого `CP1.json` не
выпускается даже как черновик с verdict.

**Долг интегратора вне окон L/S/O:**
1. свести `EXC-0003` с `review/0.0.04-debts@b0b79211` в `EXCEPTIONS.md`;
2. снять устаревшую запись про redaction из `CP0.json.known_defects`;
3. исправить путь чекаута в `AGENTS.md`;
4. вынести противоречие «AGENTS.md запрещает worktrees / в программе их шесть»
   владельцу `W0-DEC-02`.
