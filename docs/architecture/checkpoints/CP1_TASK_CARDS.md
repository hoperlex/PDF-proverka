# CP1 task cards — L / S / O / E

**BASE_SHA:** `c8475ed72a13a98566ddd9c7e6297ff232d40f62`<br>
**Форма:** [acceptance-rework/v1](../ACCEPTANCE_REWORK_POLICY_V1.md) §7<br>
**Матрица состояний:** [CP1_STATE_MATRIX.md](CP1_STATE_MATRIX.md)<br>
**Интегратор:** единственный владелец `backend/app/main.py`,
`backend/app/core/config.py`, `.github/workflows/ci.yml`, `conftest.py`,
`docs/architecture/EXCEPTIONS.md`, `contracts/**`, `*_CONTRACT_V1.md`,
`checkpoints/CP1.json` и этих двух файлов.

Общее для всех карточек: `candidate_frozen` выставляется **после** зелёного
preflight, не раньше. Полный гейт (`python scripts/ci_regression_gate.py`,
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
                  docs/architecture/README.md,
                  docs/architecture/WAVE_0_0_04_PLAN.md,
                  docs/architecture/checkpoints/README.md,
                  docs/architecture/policies/acceptance-rework-v1.json,
                  tests/test_acceptance_rework_policy.py]
  non_goals: [перенос W0-SEC-03 на новую базу, сведение EXC-0003,
              любые правки redaction/auth/watchdog]
preflight:
  - $QR_PY -m pytest tests/test_acceptance_rework_policy.py -q
  - $QR_PY -m pytest tests/ -k "document_contract or receipt" -q
attempts: []
remediation_commit: null
terminal_status: null
next_task_ids: [CP1-L-01, CP1-S-01, CP1-O-01, CP1-E-01]
```

**Важно:** `c8475ed7` изменил `.github/workflows/ci.yml` и добавил
исполняемый тест — по §6 политики это **не** receipt-only, поэтому полный гейт
перед merge обязателен. Гейт в этой сессии не запускался: бюджет окна нетронут
(0 из 2).

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
preflight:
  - $QR_PY -m pytest backend/tests/test_action_log.py tests/test_action_log_api.py tests/test_ci_redaction.py -q
  - $QR_PY -m pytest tests/ -k document_contract -q
attempts: []
terminal_status: null
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
              любые секреты в репозитории или журналах]
  shared_files_by_request: [backend/app/main.py, backend/app/core/config.py,
                            conftest.py, .github/workflows/ci.yml,
                            docs/architecture/QUALITY_RUNTIME_CONTRACT_V1.md]
preflight:
  - $QR_PY -m pytest tests/test_portal_auth.py tests/test_portal_startup_policy.py -q
  - $QR_PY -m pytest tests/ -k "startup or config" -q
attempts: []
terminal_status: null
```

**Первый шаг — не код, а перенос.** `2d624433` стоит на базе behind 16;
переносится на BASE отдельным review (план P0 шаг 4). Наличие кода не выдаётся
за выполненный rollout.

**Outcome S1:** перенесённый fail-closed кандидат + provisioning receipt:
список 3–4 сотрудников, уникальные hashes, сгенерированные **вне репозитория и
журналов**, защищённая выдача, подтверждение входа, owner/rotation/revocation,
проведённая rollback rehearsal. Общий пароль или передача секрета через git /
task tracker исключение не закрывают.

**Блокирующая связка:** `/api/info` открыт без auth ради cron-watchdog
(`portal_auth.py:40,48`). Изменение этого allowlist согласуется с потоком O;
в одиночку S его не трогает.

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
              включение auth]
preflight:
  - $QR_PY -m pytest tests/test_health_probes.py -q
  - $QR_PY -m pytest tests/ -k "action_log_api or info" -q
attempts: []
terminal_status: null
```

**Шаг 1 — идентификация, а не написание.** Обязательный первый результат:
подтвердить, какая ревизия watchdog реально работает на production, и совпадает
ли она со staged-копией
`docs/distributed_audit_workers/12f1_phaseb/staged/webapp-watchdog.sh`. Без
этого у O2 нет проверяемого отката и он не может стартовать.

**Outcome O1:** kill-семантика вынесена в документ (сейчас источник истины —
комментарии в пяти модулях); liveness/readiness endpoint'ы добавлены (на BASE
их нет); shadow-прогон выполнен, расхождения измерены, shadow receipt выпущен.
Старый watchdog остаётся активен.

**Календарное ограничение:** шаг 4 не выполняется в одну неделю с S2
(`ADR-0010:419`, план §3).

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
                  docs/architecture/checkpoints/CP1_TASK_CARDS.md,
                  docs/architecture/EXCEPTIONS.md]
  non_goals: [преждевременный verdict,
              authorizes_next_cutover=true без отдельного gate,
              заполнение production-полей догадкой]
preflight:
  - $QR_PY -m pytest tests/ -k "document_contract or receipt or checkpoint" -q
  - проверка разрешимости относительных ссылок и валидности JSON
attempts: []
terminal_status: null
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
