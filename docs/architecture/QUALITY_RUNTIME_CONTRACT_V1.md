# Quality/runtime contract v1

**Contract ID:** `quality-runtime/v1`<br>
**Версия:** `1.0.0`<br>
**Статус:** frozen implementation input<br>
**Owning task:** `W0-ARC-03`<br>
**Владельцы:** ARC — семантика контракта; OPS — materialization и CI receipt<br>
**Дата фиксации:** 2026-08-28<br>
**Базовый commit:** `de2ccea1fc1fa4fd81f6dbace61593735cf46379`

Этот документ является shared contract для `W0-ENG-02`, `W0-WEB-02`,
`W0-OPS-03` и интеграции `W0-INT-01`. Он фиксирует воспроизводимый профиль
окружения, классификацию тестов, обязательные capabilities, timeouts, отчёты и
правила known-failure baseline. Менять эти правила «по пути» в потребляющей
задаче нельзя.

Контракт следует P-04, P-10, P-13 и §5.7 ADR Bible и принятому
[ADR-0005](adr/ADR-0005-parallel-delivery.md). Исторический аудит
[CI environment matrix](ci_environment_matrix.md) остаётся evidence; при
расхождении по числу baseline, версиям или причинам зависания действует этот
контракт и более свежий receipt ниже.

## 1. Граница решения

В scope входят:

- один Linux clean-room профиль Python/Node для локального и CI-прогона;
- совместимый reference dependency receipt и правило его materialization;
- профили `unit`, `contract`, `integration`, `network`, `chaos`;
- обязательные capability probes до запуска тестов;
- per-test и wall-clock timeouts, свежий JUnit и machine-readable receipt;
- правила skip, optional data и known-failure baseline.

Не входят:

- выбор новой backend/frontend архитектуры или release topology;
- исправление тестов, lifecycle-кода и frontend-контрактов;
- изменение root dependencies, `pytest.ini`, workflow или baseline;
- объявление текущего G0 пройденным;
- provider E2E с реальными ключами и клиентские production-данные.

Эти изменения принадлежат соответственно задачам-потребителям и
`W0-INT-01`.

## 2. Frozen input receipt

SHA-256 вычислен по байтам файлов текущего worktree. Базовый commit фиксирует
provenance исходного кода. Любое изменение входа требует нового receipt до
интеграции.

**Переиздание от 2026-09-01 (`W0-INT-01`).** Прошлый receipt разошёлся по шести
входам, и это не дрейф, а результат принятых работ: `requirements.txt` дополнен
недостающими рантайм-зависимостями (CR-1/CR-2), `pytest.ini` получил регистрацию
lane-маркеров §5, `ci.yml` переписан под пять полос, `ci_regression_gate.py` —
под wall budget и cleanup группы процессов, `ci_known_failures.txt` — под
владельцев и даты пересмотра, `tsconfig.distributed.json` — под `strict: true`.
Добавлены два входа детерминированной среды: `requirements-dev.txt` и
`constraints-qr-v1.txt` (materialized lock §4.1; имя — по глобу `constraints*.txt`
из ADR-0006).

| Вход | SHA-256 |
| --- | --- |
| `requirements.txt` | `e517f305175010e974f5dcdb288135dd3ad59f5a8fd7b16f069f898ee9262df4` |
| `requirements-proto.txt` | `037a6d4a3402c1ae756a1cd8143be63e2d3a5fb2daf32d01040a79145794f92a` |
| `requirements-dev.txt` | `935ce563a390983e2ce1d140010ea6446606098faf4c7adc0ca05f59a7614d5f` |
| `constraints-qr-v1.txt` | `e701df30ffc0a942e08c77fc4458442d7f4fb3b4379560e47c437d4d4ab2dcbe` |
| `pytest.ini` | `9978cc8e08dbc4f35602ee011a291171aaba2421ef2a6ab883c672e98c681d9e` |
| `frontend/package-lock.json` | `c679604b25329bdbcf89f80017011a0c51c07e770e326865b093f63633097040` |
| `frontend/package.json` | `65749f5180ea6fd1e2d99f35c103365f9188f7e2cabaef3db53e8f051eef2075` |
| `frontend/tsconfig.distributed.json` | `a3d3fb949642421af5563073f04658160534b04e78c3ebad895d4454eb487863` |
| `.github/workflows/ci.yml` | `c835121d7feeb8ed14bab714309239a4b019f66bf6417976f066e45afb680ab3` |
| `scripts/ci_regression_gate.py` | `42fc15209950558781481aaa25d84d6f11a1333acb78eb22644b3a8b50f6f529` |
| `scripts/ci_known_failures.txt` | `4a69decf38d4f1a65c9b2d7cbca6468512b7d4ce46fcd4a07db24c47147e2fb2` |
| `tests/conftest.py` | `395646bd3f738f1da345bb75f2627844f8e27d447991c04ce305b97d13594706` |
| `backend/tests/conftest.py` | `8df70ba9cc4b1070574148b1b8cbd44cabe98c8316039c9f67f360858aac67e8` |

Таблица и константы `scripts/ci_runtime_probe.py` — один и тот же факт в двух
местах; их согласованность проверяет
`tests/test_ci_runtime_probe.py::test_frozen_receipt_matches_document`.

Baseline receipt: заголовок и фактический список согласованы, **35 entries**.
Это legacy debt inventory, а не разрешение добавлять новые падения.

## 3. Clean-room profile `qr-v1`

### 3.1. Platform

| Свойство | Нормативное значение |
| --- | --- |
| CI image | `ubuntu-24.04`, Linux `x86_64`; floating `ubuntu-latest` перед enforce заменяется фиксированным image label |
| Python | CPython `3.12.3`; переход на другую patch/minor требует нового dependency receipt и полного gate |
| User | непривилегированный, `uid != 0` |
| Node/npm | Node `22.23.1`, npm `10.9.8`, lockfile v3 |
| Temporary storage | отдельный записываемый каталог, свободно не менее 2 GiB |
| Locale/time | `TZ=UTC`, `LC_ALL=C.UTF-8`, `PYTHONHASHSEED=0` |
| Network during tests | outbound deny; loopback разрешён только профилям, которым он нужен |
| Secrets | provider/API keys отсутствуют; `PAID_API_ENABLED=false` |

Пакеты устанавливаются до test phase. Ошибка установки не проглатывается.
Wheel/cache receipt не заменяет `pip check` и runtime probes.

### 3.2. Isolated runtime state

Для каждого job создаётся новый временный root. Обязательные значения:

```text
AUDIT_DISABLE_DOTENV=1
PAID_API_ENABLED=false
PORTAL_AUTH_ENABLED=false
AUDIT_APP_DATA_DIR=<run-root>/app_data
AUDIT_PROJECTS_DIR=<run-root>/projects
AUDIT_OBJECTS_FILE=<run-root>/objects.json
AUDIT_ACTION_LOG_DIR=<run-root>/action_log
AUDITMANAGER_DEPLOY_LOCK_DIR=<run-root>/locks
```

`AUDITMANAGER_DEPLOY_LOCK_DIR` добавлена по итогам clean-room репетиции
`W0-OPS-03` (находка CR-3). Без неё `scripts/deploy_lock.py` уходит в жёстко
зашитый машинный путь `/home/coder/auditmanager/locks`, лежащий ВНЕ
репозитория и вне run-root. Под root он на машине разработчика доступен, и
падений не видно; непривилегированный пользователь получает `PermissionError`,
а на чистом раннере каталога не существует вовсе. Измерено: с этой
переменной те же 59 тестов проходят целиком.

Правило шире одного случая: изоляция обязана покрывать КАЖДЫЙ путь, который
код берёт по умолчанию вне run-root. Умолчание, указывающее на машину, — не
конфигурация, а скрытая зависимость от неё.

`app_data` не является просто пустым каталогом: provision копирует туда
allowlist tracked read-only assets из `backend/app/data`, но не машинные
`stage_models.json`, `prepare_queue.json`, `usage_data.json` и
`hidden_projects.json`. Один и тот же рецепт используют оба test root; локальный
`.env` и состояние машины не участвуют.

Боевой `projects/**`, provider CLI и пользовательские аудиты в clean-room не
копируются. `experiments/**` также не является обязательным входом.

### 3.3. Norm corpus

В enforce CI `norms/vault/**` и производный `norms/tools/status_index.json`
обязательны. Provision получает versioned artifact, проверяет SHA-256 и затем
детерминированно строит индекс. Нет artifact/checksum — setup failure, не skip.

Локально norm-набор может быть не выбран. Тогда допускается только явный skip
тестов, доказывающих именно наличие внешнего corpus, с reason code
`OPTIONAL_NORM_CORPUS_ABSENT`. Тесты поведения работают на synthetic fixture.
Такой локальный прогон не может создавать baseline и не считается G0 receipt.

## 4. Reference dependency set

### 4.1. Совместимый Python receipt

Единственный проверенный при фиксации tuple имеет SHA-256
`557e95885700a44013febcc6559fa8ee278923507b71df8adba761e1e247f99c` от
полного вывода `python -m pip freeze` с завершающим переводом строки.

Критическое compatibility nucleus:

| Package | Version |
| --- | --- |
| `fastapi` | `0.141.1` |
| `starlette` | `1.6.0` |
| `httpx` / `httpx2` | `0.28.1` / `2.12.0` |
| `anyio` | `4.14.2` |
| `pydantic` | `2.13.4` |
| `openai` / `google-genai` | `3.3.1` / `2.19.0` |
| `pytest` / `pytest-asyncio` | `9.1.1` / `1.4.0` |
| `grpcio` / `grpcio-tools` / `protobuf` | `1.82.1` / `1.82.1` / `7.35.1` |

Полный reference freeze:

```text
aiofiles==25.1.0
annotated-doc==0.0.5
annotated-types==0.8.0
anyio==4.14.2
certifi==2026.7.22
cffi==2.1.1
charset-normalizer==3.5.1
click==8.4.2
cryptography==46.0.7
distro==1.9.0
et_xmlfile==2.0.0
fastapi==0.141.1
google-auth==2.57.0
google-genai==2.19.0
grpcio==1.82.1
grpcio-health-checking==1.82.1
grpcio-tools==1.82.1
h11==0.16.0
httpcore==1.0.9
httpcore2==2.12.0
httptools==0.8.0
httpx==0.28.1
httpx2==2.12.0
idna==3.19
iniconfig==2.3.0
jiter==0.16.0
numpy==2.5.2
openai==3.3.1
opencv-python-headless==5.0.0.93
openpyxl==3.1.5
packaging==26.3
passlib==1.7.4
pillow==12.3.0
pluggy==1.6.0
protobuf==7.35.1
psutil==7.2.2
pyasn1==0.6.4
pyasn1_modules==0.4.2
pycparser==3.0
pydantic==2.13.4
pydantic_core==2.46.4
Pygments==2.21.0
PyMuPDF==1.27.2.2
pytest==9.1.1
pytest-asyncio==1.4.0
python-dotenv==1.2.3
python-multipart==0.0.32
PyYAML==6.0.3
requests==2.34.2
setuptools==84.0.0
sniffio==1.3.1
starlette==1.6.0
tenacity==9.1.4
truststore==0.10.4
typing-inspection==0.4.4
typing_extensions==4.16.0
urllib3==2.7.0
uvicorn==0.52.4
uvloop==0.22.1
watchfiles==1.2.0
websockets==16.1.1
wheel==0.48.0
```

Это reference input для materialization, не разрешение навсегда хранить
ручной `pip freeze`. `W0-INT-01` создаёт проверяемый CI/test lock или constraints
file из этого списка и устраняет manifest gaps. Сейчас clean install только из
`requirements.txt` + `requirements-proto.txt` неполон как минимум на
`passlib`, `pytest-asyncio`, `PyMuPDF`, `Pillow`, `openpyxl` и
`grpcio-health-checking`; `pip check` такие отсутствующие import-зависимости не
обнаруживает.

Worker/gateway manifests не складываются слепо с center requirements: там есть
осознанно другие pins и deployment scopes. Test lock включает нужные пакеты в
версиях `qr-v1`, не меняя worker production profile.

### 4.2. Проверка compatibility nucleus

До принятия любого нового dependency receipt обязательны:

1. clean install из materialized lock и `python -m pip check`;
2. collection полного inventory без import/collection errors;
3. AnyIO `to_thread` probe с bounded timeout;
4. минимальный FastAPI `TestClient` GET с sync endpoint и timeout 10 s;
5. полный набор `test_action_log_api.py`,
   `test_distributed_workers_flag_off.py` и
   `test_projects_v2_shadow_http_smoke.py`;
6. domain/contract lanes и затем полный regression gate.

Receipt 2026-08-28:

- `7039/7041 tests collected`, два `chaos` deselected действующим default;
- `pip check`: no broken requirements;
- `tests/test_domain_contract_v1.py`: `86 passed`;
- три критичных TestClient/route/socket файла: `30 passed`;
- минимальный `TestClient`: HTTP 200;
- full freeze совпал с рабочим venv и дал SHA-256 выше.

Проверки с thread/loopback выполнялись вне restricted sandbox, но под root.
Поэтому они доказывают совместимость tuple, а не соответствие всему clean-room
profile и не прохождение G0.

### 4.3. Frontend receipt

`npm ci` обязан использовать только `frontend/package-lock.json`. На receipt:

| Package | Resolved version |
| --- | --- |
| `eslint` | `8.57.1` |
| `typescript` | `5.9.3` |
| `vite` | `5.4.21` |
| `vitest` | `1.6.1` |

Изменение lockfile без `npm ci`, full Vitest, lint, strict typecheck и build не
принимается.

## 5. Test lanes

Каждый Python test node получает ровно один primary lane marker. `slow` —
ортогональный атрибут, не lane. Provider/live и corpus requirements также
являются атрибутами. Непомеченный или одновременно отнесённый к двум primary
lanes тест после `W0-OPS-03` является inventory failure.

| Lane | Что доказывает | Разрешённые side effects | Обязательные capabilities |
| --- | --- | --- | --- |
| `unit` | чистые domain/invariant/algorithm rules | только память; часы/random через fake | base Python |
| `contract` | schema/version/provider-consumer compatibility | temp files и bounded local compiler process; без service/network | base Python, process spawn если test явно компилирует contract |
| `integration` | совместную работу adapters/components и target PostgreSQL/S3 adapters | изолированный FS, threads, provisioned local services | thread wake-up; loopback для service-backed tests |
| `network` | реальный HTTP/gRPC/socket/process lifecycle | loopback, child processes, свободные ports | thread wake-up, loopback, process spawn/cleanup |
| `chaos` | recovery после SIGTERM/SIGKILL и restart | те же ресурсы плюс сигналы/kill | все capabilities, ≥2 GiB temp, отдельный runner/job |

Реальный PostgreSQL/S3 integration из §5.7 Bible не заменяется mock в target
contour. In-process legacy integration может оставаться characterization test,
но это явно отражается в node inventory.

### 5.1. Canonical commands

После marker materialization задачей `W0-OPS-03` локальные команды одинаковы с
CI-командами:

```bash
python -m pytest tests backend/tests -m unit --junitxml=.ci/reports/unit.xml
python -m pytest tests backend/tests -m contract --junitxml=.ci/reports/contract.xml
python -m pytest tests backend/tests -m integration --junitxml=.ci/reports/integration.xml
python -m pytest tests backend/tests -m network --junitxml=.ci/reports/network.xml
python -m pytest tests backend/tests -m chaos --junitxml=.ci/reports/chaos.xml
```

До появления этих markers действующие compatibility-команды:

```bash
python scripts/ci_regression_gate.py
python -m pytest tests/test_domain_contract_v1.py -q -p no:cacheprovider
python -m pytest tests/test_process_chaos_12e.py -m chaos -q -p no:cacheprovider
cd frontend && npm ci && npm test && npm run lint && npm run typecheck && npm run build
```

Первая команда остаётся legacy aggregate и использует baseline; она не
подменяет lane receipts. Chaos запускается только после успешного capability
probe. Provider E2E не входит ни в одну default/PR команду.

## 6. Capability preflight и skip policy

`W0-OPS-03` предоставляет один versioned probe с target interface
`python scripts/ci_runtime_probe.py --profile <lane>`. Имя допускается изменить
только в том же integration change с обновлением этого документа и workflow.

Probe выполняется до pytest и проверяет:

- `uid != 0`, Python/OS/architecture и минимум свободного temp;
- запись/rename/delete в изолированном temp;
- AnyIO worker-thread roundtrip с timeout;
- bind/connect/accept на loopback без обращения наружу;
- spawn/wait/terminate child process, а для chaos — SIGTERM и SIGKILL;
- отсутствие provider secrets и запрет платных вызовов;
- наличие и checksum norm artifact для enforce profile;
- совпадение dependency/lock и frontend lock receipts.

Правила результата:

1. В явном lane job отсутствие обязательной capability — **setup failure** до
   тестов. Skip запрещён.
2. Локальный `unit`/`contract` разрешён на restricted машине, если их собственный
   preflight зелёный. Не выбранные `network`/`chaos` считаются `NOT_RUN`, а не
   `passed` или `skipped`.
3. Test-level skip допустим только для именованного optional input или
   неподдерживаемой OS-specific ветки; reason code и текст обязательны.
4. `norms/vault` в enforce CI не optional. Боевой `projects/**` всегда optional
   и никогда не provisioned.
5. Provider E2E запускается только отдельным явно авторизованным job с budget и
   test credentials; его отсутствие в PR receipt ожидаемо.

Restricted sandbox 2026-08-28 разрешал обычные Python threads, но зависал на
AnyIO worker-thread wake-up и запрещал socket creation. Тот же exact tuple вне
sandbox прошёл probes и 30 сфокусированных тестов. Поэтому sandbox hang нельзя
классифицировать как dependency regression или добавлять в baseline.

## 7. Timeouts и завершение

| Lane | Hard per-test timeout | Lane wall-clock budget |
| --- | ---: | ---: |
| `unit` | 30 s | 10 min |
| `contract` | 60 s | 10 min |
| `integration` | 120 s | 30 min |
| `network` | 180 s | 20 min |
| `chaos` | 300 s | 20 min |

Исключение требует node ID, измеренный p95, нового hard limit, owner и expiry.
Бессрочное исключение запрещено. Увеличение timeout для сокрытия deadlock не
принимается.

При per-test timeout harness обязан:

1. напечатать полный pytest node ID и lane;
2. снять Python thread/task dump и child-process inventory;
3. завершить дочерние процессы bounded cleanup;
4. записать testcase failure типа `timeout` в свежий JUnit;
5. завершить lane ненулевым кодом.

При исчерпании wall budget действуют те же правила для активного node. Если
JUnit нельзя корректно завершить, receipt получает `report_status=missing` и job
падает. Hang никогда не превращается в молчаливый cancel или skip.

## 8. JUnit и run receipt

Перед каждым lane старый report удаляется. После процесса проверяются existence,
mtime не старше start time и parseability. Stale/missing/unparseable report —
infrastructure failure, даже если process exit code равен нулю.

JUnit должен содержать node ID, duration, failure/skip reason и counts. Рядом
публикуется JSON receipt минимум с полями:

```text
contract_id, contract_version, source_commit, lane, command
started_at, completed_at, duration_seconds, exit_code
selected, passed, failed, errors, skipped, deselected, timed_out_node
os_image, architecture, uid, python_version, node_version, npm_version
python_lock_sha256, pip_freeze_sha256, frontend_lock_sha256
capabilities, norm_artifact_sha256, report_status
```

Обязательные CI metrics: completion ratio, lane duration, timeout count,
missing/stale report count и skip count по reason code. Node ID не используется
как high-cardinality production metric label; он остаётся в artifact/log.

## 9. Known-failure baseline

Baseline применяется только к legacy aggregate `tests + backend/tests`. Новый
target-contour test, contract lane и frontend gate не могут быть добавлены в
baseline: они либо зелёные, либо блокируют merge.

Действующий список из 35 entries сохраняется как debt inventory до
`W0-INT-01`, но не считается clean-room baseline, потому что был получен до
полного materialization профиля. Правила пересъёмки:

1. только non-root `qr-v1`, все обязательные capabilities и norm corpus зелёные;
2. collection завершена полностью; timeout, interruption и pytest exit 2–5
   запрещают запись;
3. `--record` выполняется один раз integration owner после review полного
   failure list;
4. изменение baseline коммитится отдельно с причиной, owner и ссылкой на
   receipt;
5. новая запись не принимается автоматически: сначала defect disposition;
6. удаление различает `passed`, `skipped` и `vanished`; долг закрывает только
   доказанный `passed` либо отдельно утверждённое удаление test contract.

Локальное отсутствие optional data исправляется explicit skip в тесте, а не
новым baseline. Sandbox capability failure в baseline также запрещён.

## 10. Frontend gate

Frontend является отдельным обязательным receipt и не маскируется Python
baseline. Порядок:

1. `npm ci`;
2. `npm test` — полный Vitest;
3. `npm run lint`;
4. `npm run typecheck` — strict действующего distributed profile;
5. `npm run build`.

Любой ненулевой exit блокирует enforce. На входе W0-WEB-02 известны семь
Vitest failures и один `TS2339`; они требуют disposition/fix, но не frontend
baseline и не ослабление команд.

## 11. Acceptance для задач-потребителей

### W0-ENG-02

- перечисленные lifecycle nodes заканчиваются в `integration`/`network` budget;
- после теста нет orphan executor/thread/process;
- error/cancel/shutdown имеют characterization evidence.

### W0-WEB-02

- Vitest, lint, strict typecheck и build зелёные;
- каждое из семи прежних падений имеет route/journey disposition;
- удалённый test contract явно обоснован, а не скрыт.

### W0-OPS-03

- materialized markers, capability probe, timeout harness и receipts;
- norm artifact provision с checksum;
- shared workflow/defaults ещё не переводятся в enforce.

### W0-INT-01 / G0

- lock/constraints материализует dependency receipt и закрывает manifest gaps;
- все пять lanes и frontend gate завершились на non-root clean-room runner;
- fresh JUnit/JSON receipts пригодны для разбора;
- baseline переснят по §9, новых failure нет;
- `continue-on-error` удалён только после успешного полного rehearsal.

## 12. Versioning, изменения и rollback

Совместимое изменение (`1.y.z`) сохраняет значения lane, fail/skip policy,
required capabilities и строгость gates. Оно может обновить patch versions,
команду или timeout на основании полного нового receipt; изменение выполняет
integration owner одним change с этим документом, lock и CI wiring.

Несовместимое изменение создаёт `quality-runtime/v2`. К нему относятся:

- ослабление обязательного lane/capability или перевод failure в skip;
- изменение смысла baseline либо разрешение baseline для target/frontend;
- смена test framework, package/dependency manager или release topology;
- удаление JUnit/timeout/clean-room proof.

Новый долгоживущий cross-context tool/topology требует ADR до реализации.
Обновление совместимых версий существующего toolchain с полным receipt отдельного
ADR не требует.

Rollback W0-ARC-03 — только возврат документационных ссылок. После потребления
контракта rollback implementation выполняется целиком через `W0-INT-01`; частично
возвращать старые pins, markers или workflow запрещено, потому что это создаёт
несогласованный профиль.
