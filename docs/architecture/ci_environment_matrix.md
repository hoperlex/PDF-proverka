# Матрица CI-окружения: группы B (critic_v2) и C (инфраструктура)

Исследование причин «новых» падений регресс-гейта (`python scripts/ci_regression_gate.py`)
в чистом чекауте. Документ **ничего не чинит**: он фиксирует фактическую причину
каждого падения и предлагает решение, чтобы владелец мог принять его осознанно.

- Объём: 13 модулей, **47 падающих тестов** (45 «новых» относительно
  `scripts/ci_known_failures.txt`, 2 уже были в baseline).
- Вне объёма: группа A (геометрия, 33 шт., чинится отдельно) и
  `backend/tests/test_action_log.py` (задача W0-LOG-01).
- Метод: каждый тест **запущен**, причина взята из фактического сообщения об
  ошибке, а не из предположения. Ни один тест и ни один файл кода не изменялся.

## Как читать колонку «класс»

| Класс | Смысл |
|---|---|
| `hermetic` | Обязан проходить на любой машине с чекаутом и объявленными зависимостями. Падение = дефект кода/теста/пина, а не окружения. |
| `service integration` | Поднимает реальные процессы/порты; зависит от таймингов и ОС. |
| `external corpus` | Нужен тяжёлый набор данных вне git. |
| `provider E2E` | Нужен реальный провайдерский CLI/сеть/ключ. |
| `production-only` | Нужны боевые данные заказчика; в CI их быть НЕ должно. |

**В группах B и C нет ни одного теста класса `provider E2E`.** Все LLM-пути в них
идут через `--llm-provider mock` или monkeypatch. Отсутствие провайдерских CLI на
раннере ни одного из этих 47 падений не объясняет.

---

## Сквозная матрица

| # | Модуль / тест | Класс | Обязательная зависимость | Кто предоставляет | Поведение сейчас | Решение |
|---|---|---|---|---|---|---|
| **B-1** | `backend/tests/test_batch_critic_v2.py::TestCLIBatch` — `test_cli_section_eom_limit_3`, `test_cli_summary_structure`, `test_cli_per_project_artifacts`, `test_cli_with_llm_gate_mock`, `test_cli_compare_legacy`, `test_cli_with_blocks`, `test_cli_no_accept_in_zero_evidence_batch` (7) | `production-only` | Боевые проекты в `<repo>/projects/**/_output/03_findings.json` секции EOM. Путь захардкожен: `backend/scripts/batch_critic_v2.py:72` `PROJECTS_ROOT = _PROJECT_ROOT / "projects"`; флага `--projects-root` у скрипта НЕТ | Никто. `/projects/` в `.gitignore:217`; это данные заказчика, в CI их быть не должно | FAILED: скрипт выходит с rc=1 (`No 03_findings.json found under .../projects`), артефакт `batch_summary.json` не создан → `FileNotFoundError` | `исправление теста` + `fixture`: добавить скрипту `--projects-root` и направить CLI на синтетический корень, который уже умеет строить хелпер `_make_project` в том же файле. Контракт CLI (схема summary, набор артефактов, rc) проверяется без боевых данных |
| **B-2** | `backend/tests/test_benchmark_critic_v2_against_human.py` — `TestCLI` (6), `TestProviderUnavailableSafeguard::test_cli_with_max_candidates` (1), `TestTriageIntegration` (4) — итого 11 | `production-only` | Боевые проекты секций AR/КЖ с ПАРОЙ `03_findings.json` + `expert_review.json` (решения живого эксперта) | Никто. Те же данные заказчика | FAILED: `ERROR: No projects found with both 03_findings.json and expert_review.json` → rc=1 → отсутствие ожидаемых артефактов | `исправление теста`: направить CLI на синтетический корень из `_make_project`. **Уточнено при реализации (2026-08-28):** флаг `--projects-root` у скрипта был объявлен, но не работал — код делал `import backend.scripts.benchmark_critic_v2_against_human as _self; _self.PROJECTS_ROOT = ...`, а скрипт запускается как `__main__`, то есть патчился ДРУГОЙ объект модуля, и `discover_projects_with_human_decisions` продолжала читать прежний глобал. Первоначальная запись «тесты его просто не передают» неверна: передать было можно, эффекта бы не было. Исправлено в `b3a56a3c` явным параметром |
| **B-3** | `test_batch_critic_v2.py::TestDiscoverProjects::test_discovers_real_projects`, `::test_section_filter`; `test_benchmark_critic_v2_against_human.py::TestDiscoverProjects::test_discovers_real_projects`, `::test_section_filter_ar` (4) | `production-only` | Сам факт наличия боевых проектов: `assert len(projects) > 0` / `>= 1` | Никто и никогда в CI | FAILED: `assert 0 > 0` | **`skip как optional`** — единственные тесты в объёме, где skip честен: они проверяют не поведение кода, а присутствие данных заказчика, которых на раннере быть не должно. Skip обязан нести причину («боевой корпус `projects/` отсутствует»). Альтернатива — удалить как утратившие смысл; **требует решения владельца** |
| **B-4** | `backend/tests/test_pipeline_critic_v2_post_review_hook.py` — все 6 тестов | `hermetic` | Нет | — | FAILED: `TypeError: manager_instance.<locals>._log() got an unexpected keyword argument 'stage_override'` (`backend/app/pipeline/manager.py:4648`) | `исправление теста`: заглушка `_log(job, msg, level="info")` в фикстуре `manager_instance` (строка 108 теста) отстала от сигнатуры production. Комментарий в фикстуре прямо декларирует «точная сигнатура production» — для `_update_pipeline_log` это сделано, для `_log` нет |
| **B-5** | `backend/tests/test_critic_v2_project_scoped_view.py` — `test_frontend_has_per_project_critic_v2_button`*, `test_frontend_has_critic_v2_button_after_discussions`*, `test_frontend_view_block_has_no_file_input`, `test_frontend_project_view_has_no_file_input_even_in_disagreements_mode` (4; * — уже в baseline) | `hermetic` | Ничего, кроме `frontend/index.html` (в git, 512 КБ) | Репозиторий | FAILED: якоря `Проработка замечаний` в `frontend/index.html` и `frontend/static/js/app.js` нет вообще (0 вхождений, в т.ч. никаких вариантов подстроки «Проработк*») → `assert 0 < -1`. У двух других тестов ломается эвристика вырезания блока: маркер конца `</div><!-- /main-area -->` встречается в файле ОДИН раз, на 113 425 символов ниже начала блока, поэтому в «блок» затягивается чужая секция stage-comparison со своим `<input type="file">` | `исправление теста` (и/или UI): либо вернуть якорь в вёрстку, либо перевести проверки на устойчивые маркеры (`project-tab--experimental`, `cv2-sub-tabs`) и на границу блока по парности тегов. **Требует решения владельца**: это UI-контракт, а не окружение — надо решить, вкладка потеряна намеренно или регрессия |
| **C-1** | `tests/test_distributed_workers_flag_off.py` — `test_real_main_registers_nothing_when_flag_off`, `test_real_main_registers_both_contours_when_flag_on`, `test_admin_contour_not_exposed_without_portal_auth`, `test_admin_contour_available_with_explicit_dev_optin` (4)<br>`tests/test_projects_v2_shadow_http_smoke.py::test_build_smoke_app_has_routes` (1) | `hermetic` | Зафиксированная версия FastAPI/Starlette. `requirements.txt:1` объявляет `fastapi>=0.115.0` без верхней границы; установлено **fastapi 0.141.1 / starlette 1.6.0** | Репозиторий (пины) + CI (установка) | FAILED. В FastAPI ≥0.141 `include_router` кладёт в `app.routes` объекты `fastapi.routing._IncludedRouter`, а не плоские маршруты. `test_projects_v2_shadow_http_smoke` падает явно: `AttributeError: '_IncludedRouter' object has no attribute 'path'`. `test_distributed_workers_flag_off` падает молча: `getattr(r, "path", "")` возвращает `""` для ВСЕХ включённых роутеров, `routes["admin_api"] == []`, `routes["total"] == 12` вместо `> 100`. Приложение при этом рабочее: TestClient-тесты в тех же файлах проходят | `provision в CI` (запинить `fastapi`/`starlette` в `requirements.txt` и ставить пины в workflow) **+** `исправление теста` (интроспекция маршрутов через общий хелпер, устойчивый к `_IncludedRouter`). **Skip запрещён**: это проверки контура безопасности — какие ручки воркеров подняты при каком флаге. **ОТДЕЛЬНАЯ ОПАСНОСТЬ**: под новой FastAPI проверки вида «маршрута НЕТ» (`"/api/workers/jobs" not in routes["admin_api"]`) становятся вакуумно-истинными и пройдут, даже если ручка реально поднята |
| **C-2** | `tests/test_norms_index_unification.py::test_inrepo_index_exists_and_has_consistent_total`, `::test_sanpin_official_copy_has_unambiguous_paragraphs` (2) | `external corpus` | `norms/tools/status_index.json` (`.gitignore:108` — `norms/tools/*.json`). Собирается `norms/tools/build_status_index.py` из `norms/vault/*.md` + `norms/tools/status_overrides.yaml`. `norms/vault/` в `.gitignore:105`, в чекауте отсутствует | Развилка (см. ниже) | FAILED: `assert ep._DEFAULT_STATUS_INDEX.exists()` → False; во втором `FileNotFoundError: status_index.json не найден … Запустите build_status_index.py` | **Требует решения владельца.** В git УЖЕ лежат `paragraphs.jsonl` (56 МиБ), `embeddings.npz` (2 МБ) и `status_overrides.yaml` (219 overrides). Не хватает только `vault/`, а тест требует `meta.total >= 565` — одними overrides порог не берётся. Развилка: **(а) `provision в CI`** — норм-база это production source of truth (без неё нормативные стадии падают закрыто, см. C-3), значит CI, который претендует проверять нормативный контур, обязан её подвозить артефактом; **(б) `skip как optional`** с явной причиной, если владелец сознательно объявляет норм-корпус необязательным для базового прогона. Вариант «закоммитить `status_index.json`» отдельно запрещён README норм: индекс — производный артефакт |
| **C-3** | `tests/test_classic_codex_exec_runner.py::test_codex_runner_configures_required_norms_mcp_and_disables_web`, `::test_codex_json_mode_wires_norms_mcp_when_stage_declares_tools` (2) | `hermetic` | Файл `norms/tools/venv/bin/python` (`.gitignore:106`). `codex_runner.assert_norms_mcp_available()` (строка 300) требует именно `is_file()` | Разработчик (шаг «Setup после clone» в `norms/tools/README.md:306`) | FAILED: `NormsMcpUnavailableError: Сервер норм недоступен: не найден интерпретатор …/norms/tools/venv/bin/python` | `fixture`: оба теста проверяют СБОРКУ argv для codex (`-c mcp_servers.norms.required=true`, `web_search="disabled"`), а не работоспособность сервера норм. Достаточно monkeypatch `codex_runner._NORMS_MCP_PYTHON` на существующий файл в `tmp_path`. Альтернатива `provision в CI` (создавать venv) дороже и ничего не добавляет к предмету теста. Fail-closed поведение самого `assert_norms_mcp_available` менять НЕЛЬЗЯ |
| **C-4** | `tests/test_release_staging_cleanup_12i2.py::test_sealed_tree_is_not_removable_without_relaxing_modes` (1) | `hermetic` | Непривилегированный пользователь (uid != 0) | CI (конфигурация раннера) | FAILED: `assert staging.exists(), "запечатанное дерево обязано пережить наивный rm -rf"`. Под root права `0o555` не действуют, `shutil.rmtree(ignore_errors=True)` сносит дерево. Проверено отдельным экспериментом: uid=0 → дерево удалено | `provision в CI` (гонять набор от непривилегированного пользователя — это и так требование гигиены) **+** `исправление теста` (при `os.getuid() == 0` тест обязан дать `skip` с причиной «доказательство держится на правах доступа», а не молча падать). Оба варианта законны; **требует решения владельца**, но `provision` предпочтительнее: остальные три теста файла проверяют саму уборку и под root проходят вырожденно |
| **C-5** | `tests/test_process_chaos_12e.py::test_12e_gateway_graceful_stop_recovery_is_persistence_only`, `::test_12e_gateway_sigkill_recovery_is_persistence_only` (2) | `service integration` | Поднимает отдельный процесс gRPC-gateway, свободные TCP-порты, посылает SIGTERM/SIGKILL, ждёт сходимости по таймаутам | CI (ресурсы раннера) | **FAILED недетерминированно.** Четыре прогона подряд: `1 failed`, `2 failed`, `2 passed`, `1 failed` — падает то один тест, то другой, то ни одного. Ошибка: `executor_after = agent.db.process_row(...)` → `None` → `TypeError: 'NoneType' object is not subscriptable` (строка 98). То есть строка процесса исчезает до наблюдения | `исправление теста` (устранить гонку: ждать появления строки предикатом, как это уже делается для остальных состояний) **+** `отдельный job` (chaos-набор с ретраями и собственным бюджетом времени). **Skip запрещён**: это контракт долговечности задания при падении шлюза. **Требует решения владельца** в части «отдельный job или маркер `slow`» |
| **C-6** | `tests/test_agent_stream_protocol_v1.py::test_a_proto_files_compile_and_descriptor_is_reproducible` (1) | `hermetic` | Пакет `grpcio-tools` (модуль `grpc_tools.protoc`). Объявлен в `requirements-proto.txt` как dev-toolchain; в окружении стоят `grpcio` 1.82.1 и `protobuf` 7.35.1, а `grpcio-tools` — нет | CI (шаг установки) | FAILED: `CalledProcessError` от `python -m grpc_tools.protoc` → `ModuleNotFoundError: No module named 'grpc_tools'` | `provision в CI`: ставить `requirements-proto.txt`. **Skip не годится**: тест доказывает воспроизводимость дескриптора контракта `contracts/agent_stream/v1` — ровно то, ради чего он написан. Если владелец не хочет тянуть toolchain в основной job — `отдельный job` «contracts», но не молчаливый skip |
| **C-7** | `tests/test_distributed_workers_network_e2e_11g.py::test_d_backend_passes_the_requirement_into_create_audit_job` (1) | `hermetic` | Детерминированная конфигурация моделей. Читается из `backend/app/data/stage_models.json` (`.gitignore:178` — машинный runtime-стейт) | Репозиторий/CI обязаны обеспечить изоляцию; сейчас не обеспечивают | FAILED: `ExecutionError: воркер не объявляет способность 'strong_audit' для провайдера 'openrouter'`. Локальный файл на этой машине маршрутизирует ВСЕ стадии на `openai/gpt-5.4`, а `_REAL_WORKER_CAPS` в тесте объявляет у `openrouter` только `block_detector`. **Доказано**: с `AUDIT_APP_DATA_DIR=<пустой tmp>` тест проходит (конфиг берётся из `_STAGE_MODEL_DEFAULTS` в коде) | `fixture`: `tests/conftest.py` уже уводит в песочницу `AUDIT_PROJECTS_DIR`, `AUDIT_OBJECTS_FILE`, `AUDIT_ACTION_LOG_DIR` — `AUDIT_APP_DATA_DIR` в этом списке отсутствует, хотя `backend/app/data/` тоже живой runtime-стейт. Плюс `provision в CI`: гейт обязан выставлять `AUDIT_APP_DATA_DIR` в чистый каталог. Skip категорически запрещён: тест закрывает дефект 11G (задание уезжало на воркер без требования к провайдеру) |
| **C-8** | `tests/test_stage01_dual_review.py::test_stage01_dual_runner_persists_review_contract` (1) | `hermetic` | Ничего. Падает ТОЛЬКО в полном прогоне; в одиночку модуль даёт `7 passed` | — | FAILED в полном прогоне: `counts` даёт `{'new': 2}` вместо `{'new': 1}`. **Причина найдена бисекцией**: `tests/test_openrouter_worker_provider_11j.py::test_rev6_feature_flags_cannot_inject_provider_env` вызывает production-функцию `remote_audit_runner.apply_routing_flags(plan)`, которая по контракту пишет разрешённые флаги В `os.environ` процесса и в атрибуты импортированных модулей — и не откатывает их. В окружении остаётся `STAGE01_THIRD_LEG_ENABLED=true`, третья нога детектора добавляет лишнее «новое» замечание. Проверено прямо: `STAGE01_THIRD_LEG_ENABLED=true pytest tests/test_stage01_dual_review.py` воспроизводит падение один в один | `исправление теста`: `test_rev6` обязан изолировать `os.environ` и атрибуты модулей (снимок/restore вокруг вызова `apply_routing_flags`). Правится тест-загрязнитель, а не жертва. Skip запрещён: жертва проверяет контракт stage01 dual review |

### Итог по решениям

Одна строка = одно ОСНОВНОЕ решение; сумма по столбцу равна 47.

| Основное решение | Тестов | Где |
|---|---|---|
| `исправление теста` | 29 | B-1 (7), B-2 (11), B-4 (6), B-5 (4), C-8 (1) |
| `provision в CI` | 9 | C-1 (5), C-2 (2, при выборе ветки «а»), C-4 (1), C-6 (1) |
| `fixture` | 3 | C-3 (2), C-7 (1) |
| `отдельный job` | 2 | C-5 (2) |
| **`skip как optional`** | **4** | B-3 (4) |

Сопутствующие (не суммируются повторно): B-1 и B-2 (18 тестов) вдобавок требуют
`fixture` — синтетический корень проектов; C-1 и C-4 вдобавок требуют
`исправление теста`; C-7 вдобавок требует `provision`; C-5 вдобавок требует
`исправление теста`; C-6 может быть вынесен в `отдельный job`. При выборе ветки
«б» по C-2 два теста уходят из `provision` в `skip как optional` — итого skip
станет 6 из 47.

Отношение «skip» к «provision/fixture/починка» — **4 : 43**. Массового skip нет и
быть не должно: 43 из 47 падений — это либо дефект теста, либо незакрытый пункт
контракта CI, и любой из них при заглушении спрячет настоящую регрессию.

---

## Что НЕ является причиной

Три ходовые гипотезы проверены и не подтвердились для групп B и C:

1. **Внешний корпус `experiments/`.** Ни один из 13 модулей на него не ссылается
   (`grep` по `experiments/` — пусто). В чекауте каталог есть и весит 6 МБ.
2. **Провайдерские CLI (`claude`, `codex`, `openrouter`).** Ни одного падения по
   причине «CLI не найден». Все LLM-ветки в объёме — mock/monkeypatch: например,
   `test_classic_codex_exec_runner.py` единственный трогает `find_codex_cli` — и
   подменяет его через `monkeypatch.setattr(..., lambda: "/usr/bin/codex")`.
3. **`.env` в корне.** Он есть, `backend/app/core/config.py:21` грузит его через
   `load_dotenv()`, и это реальная угроза воспроизводимости — но контрольный
   прогон с `AUDIT_DISABLE_DOTENV=1` набор падений НЕ изменил. Это пункт гигиены
   контракта, а не текущая причина.

Что причиной **является** (и в baseline не отражено, потому что baseline снимали
на машине с другим состоянием): дрейф версии FastAPI, дрейф теста относительно
кода (`_log`, вёрстка), боевые данные заказчика в `projects/`, машинный
`stage_models.json`, отсутствие `norms/` артефактов, прогон под root, утечка
переменной окружения между тестами и одна недетерминированная chaos-проверка.

---

## Позиции, требующие решения владельца

Решения приняты 2026-08-28. Развилка сохраняется в тексте: принятое решение
без отклонённой альтернативы нельзя пересмотреть осознанно.

| Позиция | Развилка | Решение |
|---|---|---|
| **B-3** (4 теста «есть ли боевые проекты») | `skip как optional` с причиной **или** удалить как утратившие смысл. В CI боевых данных не будет никогда, третьего варианта нет | **Удалить.** Skip лишь законсервировал бы пустую проверку |
| **B-5** (вёрстка `Проработка замечаний`) | Якорь исчез из `frontend/index.html`. Это регрессия UI (вернуть вёрстку) **или** намеренное изменение (переписать тест на устойчивые маркеры)? Тест сам ответить не может | **Открыта.** Требует установления факта: была ли вёрстка удалена намеренно |
| **C-2** (норм-корпус) | `provision в CI` артефактом `norms/vault/` + сборка `status_index.json` **или** честный `skip как optional`. Ставка: во втором случае нормативный контур в CI не проверяется вовсе | **Provision артефактом.** Нормативный контур — сам предмет продукта, оставлять его без проверки нельзя. Отсюда семантика «обязательно в CI, необязательно локально»: локально skip, в CI отсутствие артефакта ломает прогон |
| **C-1** (пин FastAPI) | Откат к `fastapi<0.120` (сохранит плоский `app.routes`) **или** пин на 0.141.x + переписывание интроспекции маршрутов | **Переписать интроспекцию** — сделано в `2a60c367`. Откат законсервировал бы старую зависимость и оставил тесты хрупкими к внутреннему представлению |
| **C-4** (root) | Чинить раннер (непривилегированный пользователь) **или** учить тест давать skip при uid=0 | **Непривилегированный пользователь** в контракте CI. Чинит весь класс проверок прав, а не один тест |
| **C-5** (chaos 12e) | Отдельный job с ретраями **или** починка гонки в основном наборе | **Отдельный job** по маркеру. Из основного набора исключается, запускается явно |

Общий принцип, проступивший в решениях C-1, C-2 и C-4: **тест, не способный
доказать своё утверждение в текущем окружении, обязан об этом сказать, а не быть
зелёным.** Молчаливо проходящая проверка хуже отсутствующей — она создаёт
ложную уверенность. Отсюда и требование «локально skip, в CI ошибка»: skip
допустим как признание неполноты окружения, но не как способ убрать красноту.

---

## Проект контракта CI-окружения

Baseline имеет смысл только если прогон воспроизводим. Ниже — минимум, при
котором два прогона на разных машинах дают одинаковый список падений.

### 1. Пины зависимостей (репозиторий)

- `requirements.txt`: убрать открытые верхние границы у **`fastapi`** и
  **`starlette`**. Сегодня `fastapi>=0.115.0` означает, что раннер ставит любую
  будущую мажорную версию, и набор падений меняется сам собой (ровно это дало
  5 падений C-1). Пин — обязательное условие воспроизводимости.
- Шаг установки в `.github/workflows/ci.yml` сейчас `pip install … || true`
  плюс ручной список пакетов и **проглатывает ошибку установки**. Это надо
  снять: неустановленная зависимость обязана валить job, а не тихо менять
  результат.
- `requirements-proto.txt` ставится, если основной job содержит проверку
  контракта `contracts/agent_stream/v1` (иначе — выносится в отдельный job).

### 2. Переменные окружения (раннер обязан выставлять)

| Переменная | Значение | Зачем |
|---|---|---|
| `AUDIT_DISABLE_DOTENV` | `1` | Никакой локальный `.env` не участвует в прогоне. Иначе результат зависит от секретов машины разработчика |
| `AUDIT_APP_DATA_DIR` | пустой временный каталог | Изолирует `backend/app/data/` — `stage_models.json`, `prepare_queue.json`, `usage_data.json`, `hidden_projects.json`. Без этого код берёт машинную маршрутизацию моделей (причина C-7) |
| `AUDIT_PROJECTS_DIR`, `AUDIT_OBJECTS_FILE`, `AUDIT_ACTION_LOG_DIR` | временные каталоги | Уже делает `tests/conftest.py`; должно дублироваться на уровне job, потому что `backend/tests/conftest.py` этого НЕ делает |
| `PORTAL_AUTH_ENABLED` | `false` | Уже выставляет `tests/conftest.py` |
| `PAID_API_ENABLED` | `false` | Явный запрет платных вызовов на раннере |

Пункты 2 и 3 (`AUDIT_APP_DATA_DIR`) стоит продублировать в `tests/conftest.py` и
`backend/tests/conftest.py` — тогда контракт держится и при локальном запуске.

### 3. Пользователь и ФС

- Прогон **от непривилегированного пользователя** (uid != 0). Под root проверки,
  опирающиеся на права доступа, вырождаются: `test_release_staging_cleanup_12i2`
  падает, а его соседи проходят вырожденно и ничего не доказывают.
- Записываемый `TMPDIR` с запасом ≥ 2 ГБ (release-staging и chaos-тесты).

### 4. Данные и бинари

| Ресурс | Статус | Кто предоставляет |
|---|---|---|
| `frontend/index.html`, `frontend/static/js/app.js` | **обязательно**, в git | репозиторий |
| `norms/tools/paragraphs.jsonl`, `embeddings.npz`, `status_overrides.yaml` | **обязательно**, уже в git | репозиторий |
| `norms/vault/` + собранный `norms/tools/status_index.json` | **развилка C-2** | CI (артефакт) либо объявляется optional |
| `norms/tools/venv/bin/python` | **не требуется** после fixture в C-3 | — |
| `grpcio-tools` | **обязательно**, если job включает contracts-проверку | CI |
| `projects/**` (боевые аудиты заказчика) | **никогда** | — |
| Провайдерские CLI `claude` / `codex`, сетевые ключи | **не требуются** ни одним тестом групп B и C | — |

### 5. Честно объявляется optional

- **Боевой корпус `projects/`** — данные заказчика. Тесты, которые проверяют сам
  факт его наличия (B-3), обязаны давать `skip` с причиной. Тесты, которые
  проверяют поведение кода, обязаны работать на синтетическом корне.
- **`experiments/`** — исследовательский корпус, кандидат на удаление. В группах
  B и C от него не зависит ничего; фиксируется здесь только чтобы это было
  видно явно.
- **Норм-вольт `norms/vault/`** — optional ТОЛЬКО если владелец примет ветку «б»
  по C-2, и тогда в квитанции прогона обязана быть строка «нормативный контур не
  проверялся».

Всё остальное в объёме B/C — **не optional**. Это либо контракт CI (пины,
переменные, пользователь, toolchain), либо дефект теста.

### 6. Порядок перезаписи baseline

Baseline снимается **только** на окружении, удовлетворяющем пунктам 1–4, и
коммитится вместе с обоснованием. Расхождение из-за отсутствующего optional-набора
чинится skip'ом в самом тесте (с причиной), а не перезаписью baseline — иначе
локальное состояние машины закрепляется как норма, и гейт перестаёт ловить
регрессии. Это уже записано в шапке `scripts/ci_regression_gate.py`; текущий
baseline (44 записи) этому правилу не удовлетворяет и подлежит пересъёмке
ПОСЛЕ выполнения контракта, а не до.
