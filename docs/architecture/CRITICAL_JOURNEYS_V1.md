# Каталог критических user journeys — v1

**Задача:** `W0-BEH-01` (lane ENG).<br>
**Редакция:** 2026-09-04.<br>
**Срез кода:** канонический коммит `6dc3aadf` (`origin/main`).<br>
**Перепроверка среза.** Каталог снимался на `53d85e99` — коммите ветки `dev`,
которая отпочковалась 2026-09-03 от `370b6ee8` и не содержит 1613 файлов,
добавленных в `origin/main` позже. На каноне пересчитано заново: **246 путей и
270 операций** против 265 операций первой редакции. Разница — три пути и пять
операций, все в `stage-comparison` (§4.7); ни один из трёх не образует нового
journey, поэтому каталог остаётся на 30. Двадцать шесть ссылок с номерами строк
сверены пословно, две перенесены, одно утверждение о транспорте J-07 переписано
по существу.<br>
**Источник истины:** рабочее дерево на этом коммите. Каждая строка колонки
«покрытие» получена чтением конкретного тестового файла; «вероятно покрыто»
в таблицу не попадает.<br>
**Изменений кода задача не вносит.** Это frozen input для `W0-BEH-02`
(golden fixtures), `W0-LLM-02` (кассеты и replay), `W0-ADR-03`, `W0-ADR-08` и
`W0-ADR-09`.

## 1. Граница инвентаризации

Инвентаризируется **сценарий**, а не функция и не маршрут.
[Route/feature inventory](WEB_ROUTE_INVENTORY_V1.md) отвечает на вопрос «куда
можно перейти» (22 hash-маршрута + 3 серверных документа); этот документ
отвечает на вопрос «что пользователь доводит до конца и по чему видно, что оно
получилось». Один journey может проходить через несколько маршрутов и
несколько из 270 операций HTTP API, а может не иметь адресуемого маршрута
вовсе (стадии конвейера).

Journey попадает в каталог, только если у него есть все три вещи:

| Свойство | Что это значит |
| --- | --- |
| **Вход** | конкретный артефакт или действие, которое можно воспроизвести (папка файлов, версия документа, вердикт эксперта) |
| **Наблюдаемый результат** | файл, запись или ответ API, который можно предъявить: `03_findings.json`, `expert_review.json`, `.xlsx`, HTTP-ответ, строка журнала |
| **Способ проверки** | утверждение, которое может быть ложным: не «стадия отработала», а «в артефакте столько-то замечаний с такими-то полями» |

Сценарий без наблюдаемого результата (например «оператор посмотрел дашборд»)
в каталог не входит: его нельзя ни закрепить fixture'ой, ни проверить в CI.

## 2. Критерий критичности и приоритеты

Journey критичен не потому, что он существует, а потому что его поломка стоит
продукту ценности или данных. Использованы три класса, и класс назначается по
**последствию поломки**, а не по частоте использования.

| Приоритет | Критерий | Последствие поломки |
| --- | --- | --- |
| **P0** | ломается основная продуктовая цепочка «комплект → аудит → замечания → решение эксперта → отчёт», либо теряются пользовательские данные | продукт не выполняет свою работу либо теряет результат чужого труда |
| **P1** | ломается вспомогательный, но самостоятельно оплачиваемый результат (сравнение версий, реестр заказчика, распределённое исполнение, учёт денег) | пользователь теряет функцию, ради которой отдельно приходит; данные не теряются |
| **P2** | ломается удобство; результат восстанавливается вручную | раздражение, ручная работа |

P2-сценарии в каталог не включены сознательно: 30 позиций — это верх диапазона
Gate G0, и занимать их удобством, когда часть P0 покрыта неполно, было бы
подменой предмета. Список отклонённых — §7.

Отдельно отмечена **сохранность решений эксперта**. Замечание, порождённое
моделью, воспроизводимо повторным прогоном; вердикт человека — нет. Поэтому
любой journey, который может молча потерять `expert_review.json` или
`decisions_log.json`, получает P0 независимо от того, насколько редко он
запускается (J-12, J-13, J-20, J-27).

## 3. Как измерялось покрытие

Три шкалы, потому что «есть тест» и «есть deterministic fixture» — разные
утверждения, и G0 требует второе.

### 3.1. Ось «есть ли сквозной детерминированный тест»

| Метка | Определение |
| --- | --- |
| **Д** | существует тест, который проходит journey до его наблюдаемого результата и утверждает про этот результат; данные создаёт сам тест; без сети, без боевых `projects/**`, без живой модели |
| **Ч** | покрыты только отдельные шаги, только негативные ветки, либо только сервисный слой без наблюдаемого результата journey |
| **Н** | теста на journey нет |

Подмена модели синтетикой (`fake_providers`, monkeypatch на
`call_gpt_for_block`) **не лишает** journey метки Д, но такой journey помечен
`модель синтетическая` и не годится как доказательство LLM-replay по G0 —
синтетический ответ проверяет код вокруг модели, а не воспроизводимость
прогона.

### 3.2. Ось «есть ли переиспользуемая golden fixture»

Отдельная колонка, потому что она и есть предмет формулировки G0. Считается
именованный, версионированный набор входных данных, живущий вне тела
конкретного теста и переиспользуемый несколькими тестами.

### 3.3. Ось «зависимость от боевых данных, сети и модели»

Проверено фактически:

* `projects/` в этом чекауте **пуст** и закрыт `.gitignore:226`; корпус живёт
  в `AUDIT_DATA_DIR` вне репозитория;
* оба корня тестов уводят хранилище в песочницу процесса на импорте conftest
  (`tests/conftest.py`, `backend/tests/conftest.py`): `AUDIT_PROJECTS_DIR`,
  `AUDIT_OBJECTS_FILE`, `AUDIT_ACTION_LOG_DIR`, копия `backend/app/data` без
  живого runtime-стейта. Поэтому дефолтный прогон боевые данные не читает;
* тесты, которым боевой корпус всё же нужен, объявляют это `skipif`, а не
  падают: `tests/test_low_voltage_geometry.py`, `test_singleline_graph_etalon.py`,
  `test_singleline_graph_red_sheets.py`, `test_singleline_rich_prompt.py`,
  `test_blocks_analysis_endpoint.py:215`, `test_protection_table_check.py:179`,
  `test_eval_harness.py:135`, `backend/tests/test_critic_v2_assisted_round1.py`
  (класс `TestRealReviewPackage`), плюс 12 файлов геометрии, зависящих от
  корпуса `experiments/блоки разных дисциплин/`;
* обращений к реальным провайдерам моделей в тестах нет ни одного. Подделан
  «последний метр»: `backend/app/pipeline/execution/fake_providers.py` (CLI
  `claude`/`codex` подстановкой в `PATH`),
  `backend/app/pipeline/execution/provider_bridge_stub.py`,
  `tests/distributed_audit_e2e/openrouter_stub.py` (настоящий сокет, поддельный
  собеседник). Стенд воркеров дополнительно держит сетевой guard и вычистку
  секретов — `tests/distributed_audit_e2e/isolation.py`;
* **глобальной защиты «тест не сходит в модель» нет.** Ни один из трёх
  conftest (`conftest.py`, `tests/conftest.py`, `backend/tests/conftest.py`) не
  ставит autouse-блокировку LLM и не поднимает сетевой guard. От живого вызова
  сегодня защищает только пустой `OPENROUTER_API_KEY` и `PAID_API_ENABLED=false`.
  Это дефект харнесса, а не свойство тестов; владелец — `W0-LLM-02`.

Lane-маркеры по §5 [quality/runtime contract](QUALITY_RUNTIME_CONTRACT_V1.md)
проставлены: `unit` 816, `integration` 959, `network` 212, `contract` 29,
`chaos` 8 узлов; `chaos` исключён из прогона по умолчанию
(`pytest.ini: addopts = -m "not chaos"`).

## 4. Каталог journeys

30 позиций. Колонка «Fixture» отвечает на вопрос §3.2 и почти везде отвечает
«нет» — это главный результат инвентаризации, см. §6.

### 4.1. Приём документа и идентичность версии

| ID | Journey | P | Вход → наблюдаемый результат | Покрытие | Fixture |
| --- | --- | --- | --- | --- | --- |
| J-01 | Загрузка комплекта проекта из папки | P0 | папка с PDF+MD(+result,+ocr) → каталог проекта на диске и карточка в списке | **Д** | нет |
| J-02 | Предпроверка комплекта до записи: дубль, дисциплина, предложение версии | P0 | тот же комплект → вердикт precheck (ready / warning / hard block) | **Д** | нет |
| J-03 | Новая версия документа и её файлы | P0 | существующий проект + новый комплект → `version_group.json`, папка версии, `can_run_audit` | **Д** | нет |
| J-04 | Подготовка: резолв Markdown и `document_graph.json` | P0 | версия с PDF и MD → `document_graph.json` со страницами и `sheet_no` | **Ч** | нет |

**J-01.** `tests/test_upload_folder.py` (23 теста, `integration`+`network`) —
сервис `save_uploaded_project_folder` и HTTP `POST /api/projects/upload-folder`
на кодах 200/422/409: полный комплект, отсутствие PDF, несколько PDF, дубль в
legacy и в `projects_v2`, path-traversal и `webkitRelativePath`,
fail-soft shadow-записи. Критичность: это единственная дверь, через которую
документация заказчика попадает в систему; ошибка здесь либо не пускает работу,
либо создаёт второй экземпляр одного документа с расходящимися замечаниями.
**Пробел:** новый 3-файловый комплект портала (`*_results.md` / `*_results.html`
/ `*_blocks.json`, ZIP) покрыт только на сервисном уровне —
`backend/tests/test_new_results_bundle_ingest.py` (32 теста: `TestClassifyUploadFiles`,
`TestZipExpansion`, `TestFindInputQuad`), `test_results_md_parser.py`,
`test_parse_md_text_results_format.py`, `test_blocks_json_result.py`; последние три
читают реальные ZIP из `experiments/новая структура.`, а HTTP-конца у этого
варианта нет.

**J-02.** `tests/test_upload_folder_precheck.py` (11 тестов: дубль по имени, по
sha256 PDF, по отпечатку комплекта, похожее имя, повторная проверка при
сохранении) и `tests/test_upload_folder_autodetect.py` (14 тестов: определение
дисциплины по имени папки/PDF/тексту, предложение версии при совпадении имени).
Критичность: precheck — единственное место, где система отличает «новая версия»
от «второй раз тот же документ»; ошибка порождает расщепление истории решений.

**J-03.** `tests/test_version_file_upload.py` (22), `test_project_version_from_candidate.py`
(9), `test_merge_project_as_version.py` (20), `test_version_service.py`,
`test_migrate_versions_to_container.py`. Критичность: `project_id` = basename
папки версии; поломка раскладки контейнера `(main)/` отвязывает от проекта
решения, обсуждения и учёт стоимости (`docs/project_versions.md`).

**J-04.** Покрыты части: `tests/test_md_resolver.py` (12) — выбор Markdown и
запрет фолбэка на `extracted_text`; `tests/test_graph_builder_multi_pdf.py` (3) —
ремап коллизий `page_number` в мультиPDF-проекте;
`tests/test_prepare_service_v2_primary.py` (3),
`tests/test_process_project_v2_primary_prepare.py` (1) — резолв путей;
`backend/tests/test_prepare_results_md_branch.py`, `backend/tests/test_md_mirror_reconcile.py`.
**Чего нет:** теста, который из версии с PDF и MD получает `document_graph.json`
и утверждает про его содержимое целиком. Граф — вход для sheet/page во всех
последующих замечаниях, поэтому пробел стоит дорого.

### 4.2. Детерминированная предобработка блоков

| ID | Journey | P | Вход → наблюдаемый результат | Покрытие | Fixture |
| --- | --- | --- | --- | --- | --- |
| J-05 | Блоки: кроп, частичный отказ, восстановление кропа, вектор-контекст | P0 | версия с PDF → `blocks_stage02_100/index.json` + PNG + `block_vector_graphs/*.json` | **Д** | нет |

`tests/test_crop_blocks_partial_success.py` (6) — стадия не объявляет успех при
частично скачанных кропах; `tests/test_crop_rehydration_gate.py` (9) и
`tests/test_block_crop_store.py` (26) — лестница восстановления «локальный файл →
LRU → ре-рендер из PDF → crop_url» и защита от «index есть, PNG нет»;
`tests/test_block_context.py` (7), `tests/test_block_context_stage_skip.py`,
`tests/test_block_context_source_kinds_contract.py`; `backend/tests/test_pdf_crop.py`,
`backend/tests/test_crop_cache.py`, `backend/tests/test_block_vector_availability.py`.
Критичность: по `docs/blocks_and_stage02.md` визуальный анализ даёт ~60 %
замечаний; молча пустой набор блоков превращает аудит в анализ одного текста,
и по итоговому отчёту это неотличимо от «на чертежах всё чисто».

### 4.3. Анализ

| ID | Journey | P | Вход → наблюдаемый результат | Покрытие | Fixture |
| --- | --- | --- | --- | --- | --- |
| J-06 | Stage 01: анализ текста MD | P0 | MD версии → `02_text_analysis.json` | **Ч** | нет |
| J-07 | Stage 02: анализ блоков | P0 | кропы + `block_context` → `01_blocks_analysis.json` | **Ч** | нет |
| J-08 | Свод замечаний (текст + блоки → F) | P0 | `02_text_analysis.json` + `01_blocks_analysis.json` → `03_findings.json` | **Ч** | нет |
| J-09 | Критик → корректор замечаний | P0 | `03_findings.json` → `03_findings_review.json` + правленый `03_findings.json` | **Д** | **есть, частично** |
| J-10 | Верификация норм | P0 | `03_findings.json` → `norm_checks.json`, `missing_norms_queue.json` | **Ч** | нет |
| J-11 | Оптимизация + критик/корректор | P1 | MD + `03_findings.json` → `optimization.json`, `optimization_review.json` | **Ч** | нет |
| J-12 | Долги: согласованные замечания прошлой версии не теряются | P0 | findings и `expert_review.json` версии N-1 → MIG-замечания в `03_findings.json` | **Д** | нет |
| J-13 | Автоперенос вердиктов эксперта на новую версию | P0 | вердикты версии N-1 → `expert_review.json` версии N + отчёт | **Д** (модель синтетическая) | нет |

**J-06.** Покрыто окружение стадии, не стадия: `tests/text_analysis/` (13 файлов —
загрузка чек-листов, детектор стадии, детектор типа документа, нормативный
статус, правила по блокам, синхронизация шаблона промпта),
`tests/test_text_analysis_md_chunker.py`, `test_text_analysis_md_prescan.py`,
`test_text_analysis_rate_limit_retry.py`, `test_stage01_abort_on_leg_failure.py`
(19 — отказ одной ноги ансамбля останавливает проверку),
`test_stage01_dual_review.py` (7, модель подменена на уровне
`call_gpt_for_block`/`call_codex_for_block`), `test_stage01_evidence_context.py` (9),
`test_11d1_text_analysis_semantic_equivalence.py` (сверка промпта после переезда
на ProviderAdapter), `backend/tests/test_absence_guard.py`.
**Чего нет:** прогона стадии от MD до `02_text_analysis.json`.

**J-07.** Аналогично: `tests/test_stage02_smoke_controls.py` (22),
`test_stage02_finding_provenance.py` (10), `test_stage02_paid_cache_and_adapt.py`
(8), `backend/tests/test_stage02_paid_cache.py`, `test_block_grounding.py`,
`test_neighbor_block_dedup.py`, `tests/test_blocks_before_text_reorder.py`,
`tests/test_legacy_block_batch_removed.py`, `tests/test_resume_block_analysis_reconciliation.py` (3).
Детерминированные подпроверки стадии покрыты отдельно —
`tests/test_protection_table_check.py` (частично на боевом корпусе, `skipif`).
**Чего нет:** прогона стадии до `01_blocks_analysis.json`.

**J-08.** Покрыт весь детерминированный пост-проход:
`tests/findings/dedup/test_phase0_integration.py` (11 — интеграция дедупа в
`findings_merge/runner.py`), `test_class_dedup.py`, `test_fuzzy_dedup.py`,
`test_dedup_safety.py`, `tests/test_block_captions.py` (25 — замена `block_id` на
человеческие подписи), `test_findings_schema_normalization.py` (6),
`test_findings_sheet_and_numbering.py` (14 — `sheet` против `page`),
`test_finding_symbol_evidence.py`, `backend/tests/test_ground_highlights_textlayer.py`.
**Чего нет:** прогона `run_findings_merge` до `03_findings.json`.

**J-09 — единственный анализ-journey с меткой Д.** Детерминированный контур
покрыт целиком: `tests/test_findings_deterministic_critic.py` (11),
`tests/test_findings_deterministic_corrector.py` (13, включая
`test_critic_then_corrector_roundtrip` — две стадии подряд),
`backend/tests/test_findings_verify_stage.py` (6),
`backend/tests/test_findings_review_critic_v2_offline.py` (107) и
`backend/tests/test_findings_review_quality_fixtures.py` (59).
**Fixture есть:** `backend/tests/fixtures/findings_review/` — `good_findings.json`,
`bad_findings.json`, `borderline_findings.json`, `duplicate_findings.json`,
`no_evidence_findings.json` с ожидаемыми вердиктами и README формата. Это
**единственный** в репозитории набор данных, отвечающий определению §3.2, и он
покрывает один шаг одного journey. Семантические проверки 3/5 (bounded LLM)
воспроизводимо не проверяются — они fail-soft, и тест видит только ветку «LLM
промолчал». Критичность journey: инвариант «ни одно замечание не удаляется»
(`docs/critic_corrector.md`) — единственная защита от тихой потери результата
аудита.

**J-10.** `tests/test_norms_status_index_fallback.py` (46),
`test_norms_core_classification.py` (22), `test_norm_clause_binding.py` (13),
`test_norms_index_unification.py` (10), `test_native_verify_numeric_sensitivity.py`,
`test_norm_quote_backfill.py`, `test_norms_from_optimization.py`,
`test_norms_verification_metrics.py` (3), `test_missing_norms_kb.py` (10).
**Чего нет:** прогона стадии до `norm_checks.json` на фиксированном срезе норм.
`tests/test_ci_provision_norms.py` показывает, что корпус норм в чистой комнате
провижнится отдельным шагом (§3.3 quality contract), то есть fixture нормативной
базы — самостоятельная работа, а не побочный эффект.

**J-11.** `tests/test_optimization_deterministic_critic.py` (11),
`test_optimization_deterministic_corrector.py` (9),
`test_optimization_prescan.py`, `test_optimization_ensemble.py`,
`test_optimization_norm_status_enrich.py`, `test_optimization_norm_fix_guard.py`,
`test_optimization_visual_context.py`, `test_optimization_prompt_policy.py`;
раздел целиком — `backend/tests/test_section_optimization_*.py` (5 файлов).
Генерация предложений (LLM) не прогоняется.

**J-12.** `tests/test_debt_control_stage.py` (6) и
`tests/test_migrated_findings_service.py` (59) — сквозной сценарий «замечание,
согласованное в версии N-1, обязано появиться в версии N». P0 по критерию
сохранности: молчаливая потеря выглядит как «в новой редакции исправлено».

**J-13.** `tests/test_decision_carryover_service.py` (21): перенос accepted и
rejected, неперезапись решения человека, идемпотентность повторного прогона,
пропуск для первой версии, fail-soft при исключении воркера, отсутствие записи
при неподтверждённом переносе. Sonnet замокан (сказано в шапке файла) — ответ
модели **синтетический, а не записанный**, поэтому journey не годится как
LLM-replay доказательство G0. Смежное: `tests/test_verdict_preservation.py` (17) —
перепривязка вердиктов при перенумерации `F-NNN`.

### 4.4. Управление прогоном

| ID | Journey | P | Вход → наблюдаемый результат | Покрытие | Fixture |
| --- | --- | --- | --- | --- | --- |
| J-14 | Запуск аудита версии и наблюдаемость прогресса | P0 | версия → `pipeline_log.json`, статусы стадий, WS-события | **Ч** | нет |
| J-15 | Resume после обрыва | P0 | версия с прерванным прогоном → возобновление с правильной стадии | **Ч** | нет |
| J-16 | Retry стадии и `start-from` без обхода обязательных | P0 | запрос повтора стадии → отказ либо корректный перезапуск | **Ч** | нет |
| J-17 | Пакетная очередь: постановка, пауза, отмена, восстановление после рестарта | P0 | список проектов → порядок исполнения и переживание рестарта | **Д** | нет |

**J-14.** Покрыты write-path и наблюдаемость по отдельности:
`tests/test_pipeline_write_path_versioned.py` (21 — прогон версии V2 пишет только
в свой `_output`, не трогает V1; `job_key`; `audit_logger`),
`tests/test_ws_status_pipeline_summary.py` (5 — `pipeline_summary` в WS-сообщении),
`tests/test_pipeline_summary_status_normalization.py` (включая
`test_legacy_ar_project_v4_full_pipeline`), `tests/test_audit_coverage_honesty.py`
(6 — честность покрытия блоков в отчёте).
**Чего нет:** HTTP-запуск покрыт только отрицательными ветками —
`POST /api/audit/{id}/full-audit` и `POST /api/optimization/{id}/run` проверены
на неизвестной версии (404: `test_pipeline_write_path_versioned.py:169,431,437`)
и на версии без исходных файлов (409: `test_version_file_upload.py:307,316`).
Положительного прогона нет ни одного: `PipelineManager` конструируется в 12
файлах тестов, но оркестратор `_run_ocr_pipeline` не вызывается ни разу —
все четыре его упоминания в тестах находятся в комментариях
(`test_backend_main_v2_audit_md_resolution.py:5,258`,
`test_distributed_workers_execution_backend.py:2400`,
`test_legacy_block_batch_removed.py:47`).

**J-15.** `tests/test_resume_detector.py` (5 — контракт ответа, невалидная версия
не resumable, пустой проект резюмится с prepare, следующая стадия после импорта
результата воркера), `tests/test_recover_stale_version_aware.py` (2 — обход
братских папок версий), `tests/test_seed_prepared_inputs_from_latest.py`,
`tests/test_catch_up_source_ready.py`. Исполнение `_run_resumed_pipeline` не
покрыто.

**J-16.** `tests/test_validate_start_stage_vector_gate.py` (6 — пустой проект
блокирован, отсутствующий MD никогда не обходится, `block_context` без артефакта
блокирован) и `tests/test_standalone_stage_run_dir_seed.py` (7 — сидирование
run-каталога из `latest` без перезаписи существующего). HTTP
`POST /api/audit/{id}/retry/{stage}` и его таблица соответствий стадий не покрыты
ни одним тестом.

**J-17.** `tests/test_batch_queue_hardening.py` (7),
`test_batch_queue_resilience.py` (11), `test_batch_queue_parallel.py`,
`test_batch_queue_reconcile.py`, `test_batch_queue_selection_fixes.py`,
`test_batch_queue_hide_finished.py`, `test_parallel_hardening.py`. Файл очереди
изолирован autouse-фикстурой `_isolate_batch_queue_file`.

### 4.5. Просмотр и экспертное решение

| ID | Journey | P | Вход → наблюдаемый результат | Покрытие | Fixture |
| --- | --- | --- | --- | --- | --- |
| J-18 | Просмотр замечаний версии: список, фильтры, лист против страницы | P0 | версия с `03_findings.json` → ответ `GET /api/findings/{id}` | **Д** | нет |
| J-19 | Просмотр исходника и блоков, привязка замечания к блоку | P1 | версия → страницы документа, кропы, `block-map` | **Ч** | нет |
| J-20 | Экспертное решение по замечанию и его сохранность | P0 | вердикты → `expert_review.json` + `decisions_log.json` | **Д** | нет |
| J-21 | Excel round-trip решений: отчёт → правка → импорт | P1 | `.xlsx` с решениями → обновлённый `expert_review.json` | **Ч** | нет |
| J-22 | Внешний реестр заказчика: импорт → сопоставление → вердикт | P1 | реестр заказчика → сопоставленные записи и применённые вердикты | **Ч** | нет |

**J-18.** `tests/test_version_aware_endpoints.py` (20 — findings/optimization/blocks/
document по версиям, включая 404 на неизвестной версии и поведение legacy-эндпоинта
без `version_id`), `tests/test_findings_sheet_and_numbering.py` (14),
`tests/test_finding_block_map_strict.py` (5),
`tests/test_sidebar_review_pending_counter.py` (11).

**J-19.** `tests/test_blocks_analysis_endpoint.py` (6, часть скипается без боевых
данных: `:215` — «реальные данные проекта недоступны в этом окружении»),
`tests/test_block_llm_text_shadow_markdown.py`, `test_block_profile_full_markdown`
на фронте, `test_version_aware_endpoints.py::test_document_v2_isolated`,
`backend/tests/test_block_vector_availability.py`,
`backend/tests/test_textlayer_highlights_shadow_api.py` (1 TestClient-тест).
Наблюдаемого сквозного теста «открыл замечание → перешёл на блок → увидел кроп»
нет; на фронте он невозможен в принципе, см. §5.

**J-20.** `tests/test_expert_review_v2_primary_canonical.py` (7 — канонический
`04_review/expert_review.json`, приоритет над фолбэками, отсутствие обратного
затирания shadow-зеркалом), `tests/test_atomic_json_decisions_log_lock.py` (9 —
конкурентная запись `decisions_log.json` не теряет решений),
`tests/test_verdict_preservation.py` (17), `tests/test_schedule_completion_stamp.py`,
`tests/test_knowledge_base_attribution.py` (4),
`backend/tests/test_kb_id_and_revoke.py`, `backend/tests/test_project_review_status_split.py`,
`tests/test_resolve_project_dir_pdf_orphan_fix.py` (защита от создания orphan
`_output` при сохранении решений). **Пробел:** HTTP
`POST/GET /api/knowledge-base/expert-review/{project_id}` не покрыт ни одним
тестом — наблюдаемый результат проверяется на слое сервиса.

**J-21.** Обе половины покрыты порознь, замкнутого round-trip нет:
`tests/test_excel_report_sheets.py` (9 — в том числе скрытая ячейка `project_id`,
которая и существует ради обратного импорта), `tests/test_import_decisions_excel.py`
(6), `tests/test_export_rejected_findings_excel.py` (2),
`tests/test_excel_report_version_aware.py` (2).

**J-22.** `tests/test_external_register_kingsons.py` (7 — применение вердиктов
реестра, dry-run не пишет). Цепочка `POST /import` → `POST /{object}/match` →
`confirm|reject` → `export.xlsx` через HTTP не покрыта; `matcher.py` зовёт
`claude` CLI.

### 4.6. Выгрузка результата

| ID | Journey | P | Вход → наблюдаемый результат | Покрытие | Fixture |
| --- | --- | --- | --- | --- | --- |
| J-23 | Excel-отчёт по проекту и по разделу | P0 | артефакты версии + решения → `.xlsx` | **Ч** | нет |
| J-24 | Пакет аудита (ZIP) | P1 | версия → архив с PDF, MD, всеми JSON и отчётом | **Ч** | нет |

**J-23.** `tests/test_excel_report_sheets.py` (9, `unit`) строит отдельные листы и
проверяет нормализацию severity EN→RU и устойчивость к пустым данным;
`tests/test_excel_report_version_aware.py` (2) — одна primary-версия на контейнер.
Стадия `excel` целиком (subprocess-запуск генератора, запись в `05_export/`) и
HTTP `POST /api/export/excel`, `POST /api/export/excel/section`,
`GET /api/export/download/{filename}` не покрыты. Отчёт — единственный
результат, который заказчик видит; P0 назначен по этому основанию.
Форматов генерации ровно один: `.xlsx` (openpyxl); Word/PDF в коде нет.

**J-24.** `tests/test_export_v2_primary.py` (2): состав ZIP (PDF, `latest`,
README, сгенерированный на лету отчёт) и 404 на пустом `latest`. Вызывается
функция обработчика напрямую, не через HTTP; legacy-ветка `export.py:252` не
покрыта.

### 4.7. Сравнение редакций документации

| ID | Journey | P | Вход → наблюдаемый результат | Покрытие | Fixture |
| --- | --- | --- | --- | --- | --- |
| J-25 | Сессия сравнения стадий: загрузка → пары → сопоставление листов → текстовые различия | P1 | два комплекта стадий → сессия, пары, связи листов, ledger различий | **Д** | нет |

12 файлов, ~186 тестов: `tests/test_stage_comparison_shell.py` (17,
HTTP-уровень сессий и пар), `test_stage_comparison_document_matching.py` (4),
`test_stage_comparison_sheet_matching.py` (23),
`test_stage_comparison_sheet_link_repair.py` (18) и `..._store.py` (5),
`test_stage_comparison_text_comparison.py` (23),
`test_stage_comparison_text_differences.py` (22),
`test_stage_comparison_project_change_summary.py` (25),
`test_stage_comparison_text_ai_reviewer.py` (40),
`test_stage_comparison_stage_upload*.py` (3 файла). Шаг AI-review внутри journey
— LLM, см. §5.3.

**Дельта канона.** На каноническом срезе в этом разделе появились три пути,
которых не было в первой редакции: `graphic-comparison` (GET+POST),
`high-level-project-changes` (GET+POST) и `text-entities` (GET). Это весь прирост
API между срезами — 265 операций стали 270, больше нигде не изменилось ничего.

**Ни один из трёх путей не становится journey, и число journeys не меняется.**
Критерий §2 требует сценария, который пользователь доводит до конца и у которого
есть собственный наблюдаемый результат.

- `high-level-project-changes` — **шаг внутри J-25**, наравне с AI-review.
  Отдельного пользовательского действия у него нет: SPA вызывает его в том же
  обработчике, что и `project_change_summary`
  (`frontend/static/js/app.js:13483`), под тем же флагом загрузки
  `scProjectChangeSummaryLoading` и с тем же каналом ошибки. Пользователь не
  может запустить его сам и не видит его завершения отдельно.
- `graphic-comparison` и `text-entities` из интерфейса не вызываются вовсе —
  функции без сценария (§7).

Покрытие шага — **частичное**, и это измерено: 24 теста
`tests/test_stage_comparison_high_level_project_changes.py` проверяют модуль
(детерминированная маршрутизация групп, валидация ответа модели, fail-closed при
непрошедшей валидации), 2 теста `tests/test_stage_comparison_high_level_store.py`
— слой store с подменёнными загрузчиками сессии и пары. Ни один тест не проходит
через HTTP-маршрут и ни один не подменяет транспорт модели. Оценка J-25
остаётся **Д**: сквозной тест у самого journey есть, недостаёт покрытия у его
нового шага — и это записано в §5.3 вместе с остальными пробелами replay.

Два оставшихся пути покрыты алгоритмически и тоже мимо HTTP:
`graphic-comparison` — 26 тестов
(`tests/test_stage_comparison_graphic_comparison.py`), `text-entities` — 19
(`tests/test_stage_comparison_entity_producers_context.py`).

**Оговорка о первой редакции этой правки.** Черновик кандидата заводил под
`high-level-project-changes` отдельный journey `J-31` и доводил каталог до 31 —
за верхнюю границу диапазона 20–30 из roadmap §6. Владелец программы отклонил
это, и справедливо: сценария там нет, а диапазон критерия не подлежит вольной
трактовке. Классификация исправлена по коду, а не подогнана под число.

### 4.8. Доступ, сохранность данных, учёт

| ID | Journey | P | Вход → наблюдаемый результат | Покрытие | Fixture |
| --- | --- | --- | --- | --- | --- |
| J-26 | Вход в портал и разграничение ролей | P0 | логин/пароль → session-cookie и допуск к API | **Д** | нет |
| J-27 | Обслуживание проекта: очистка, удаление, восстановление, переименование без потери решений | P0 | команда обслуживания → состояние диска и сохранённые вердикты | **Д** | нет |
| J-28 | Журнал действий: durable audit отдельно от диагностики, redaction | P1 | запросы → `logs/actions/actions-*.jsonl` и `diag-*.jsonl` | **Д** | нет |
| J-29 | Учёт стоимости платных вызовов и защита от перерасхода | P1 | вызовы модели → счётчики, дневной/месячный лимит, блокировка | **Д** | нет |

**J-26.** `tests/test_portal_auth.py` (24), `tests/test_portal_startup_policy.py`
(fail-closed вне local-режима; ради него и появился корневой `conftest.py` с
`PORTAL_RUNTIME_MODE=local_dev`), `tests/test_users.py` (10),
`tests/test_permission_boundary_12f.py`, `tests/test_current_object_per_request.py` (5).
Связано с `EXC-0001` и `W0-SEC-03`.

**J-27.** `tests/test_project_delete.py` (9), `tests/test_clean_projects_v2.py`
(включая `test_clean_project_data_end_to_end_v2_not_noop`),
`tests/test_restore_clean_endpoint.py` (2), `tests/test_project_rename.py` (27),
`tests/test_ui_project_rename.py`, `tests/test_destructive_backup_contract.py`,
`tests/test_clean_project_data_v2_primary.py`. P0: это единственная группа
операций, которая по определению уничтожает данные.

**J-28.** `tests/test_action_log_api.py` (8, полное приложение),
`backend/tests/test_action_log.py` (55, включая
`test_secret_in_query_reaches_neither_channel` и
`test_presigned_url_in_query_loses_its_signature`),
`tests/test_ci_redaction.py`. Владелец контракта — `W0-LOG-01`.

**J-29.** `tests/test_paid_api_reservation.py` (10),
`backend/tests/test_paid_api_guard.py` (20),
`backend/tests/test_gemini_direct_paid_guard.py`,
`backend/tests/test_paid_cost_dashboard.py` (9),
`backend/tests/test_paid_cost_daily_breakdown.py`,
`backend/tests/test_paid_event_invariant.py`,
`tests/test_usage_projects_summary_contract.py` (2),
`tests/test_usage_cleared_project_zeroed.py` (3),
`tests/test_llm_runner_model_prices.py`.

### 4.9. Распределённое исполнение

| ID | Journey | P | Вход → наблюдаемый результат | Покрытие | Fixture |
| --- | --- | --- | --- | --- | --- |
| J-30 | Выдача задания воркеру и приём результата в центр | P1 | задание → пакет, прогон, чанкованная загрузка, импорт результата | **Д** (модель синтетическая) | частично: программная фабрика проекта |

`tests/test_distributed_workers_e2e.py` (3, `network`): полный цикл
«регистрация → одобрение → heartbeat → выдача задания → скачивание пакета →
сверка sha256 и манифеста → распаковка → прогон → события → сборка результата →
чанкованная загрузка → скачивание» плюс отложенная доставка и отказ без токена.
`tests/test_12h_result_import_finalization.py` (4),
`tests/test_distributed_workers_central_handoff.py` (70+ узлов: снимок профиля
дисциплины и его подделка, переносимость путей, ось центрального хвоста после
рестарта, откат и идемпотентность импорта, конфликт, resume настоящим детектором,
семантическая эквивалентность).
`tests/distributed_audit_e2e/fixture.py::build_project_fixture` — **единственная
переиспользуемая фабрика проекта в репозитории**, но она строит проект
программно, а не воспроизводит зафиксированный корпус, поэтому в §3.2 засчитана
как «частично».

## 5. LLM-journeys и готовность к replay

### 5.1. Какие journeys зависят от модели

| Journey | Транспорт | Точка вызова |
| --- | --- | --- |
| J-06 Stage 01 | `claude -p` (subprocess), ProviderAdapter | `backend/app/services/llm/claude_runner.py`, `stages/text_analysis/provider_transport.py`, `stages/text_analysis/absence_guard.py:314` (мимо `_run_cli`) |
| J-07 Stage 02 | HTTP OpenRouter, отдельно Gemini Direct | `stages/block_analysis/gemma_findings_only.py:1556` — вызов идёт через обёртку повторов `_post_openrouter_with_transient_retry` (`:161`), а не прямым `client.post`, как в первой редакции; URL захардкожен на `:96`. Отдельно `services/llm/gemini_direct_runner.py` |
| J-08 Свод замечаний | `claude -p` | `stages/findings_merge/provider_transport.py` |
| J-09 Критик (проверки 3/5) | `claude -p --max-turns 1`, bounded | `stages/findings_review/deterministic_critic.py`; `critic_v2/llm_gate.py:1584` (`requests`, URL захардкожен), `critic_v2/kb_gate.py:174` (`subprocess.run` мимо `_run_cli`) |
| J-10 Верификация норм | `claude`/MCP | `stages/norms/runner.py`, `external_provider.py` |
| J-11 Оптимизация и её критик | `claude` + `codex exec` (ансамбль) | `stages/optimization/ensemble.py`, `services/llm/codex_runner.py` |
| J-13 Автоперенос вердиктов | `claude -p` | `services/findings/decision_carryover_service.py:335` (`subprocess.run` мимо `_run_cli`) |
| J-22 (шаг) сопоставление реестра | `claude` | `services/external_register/matcher.py:176` |
| J-25 (шаг) AI-review различий | `claude` / `codex` | `services/stage_comparison/text_ai_reviewer.py` |
| J-25 (шаг) верхнеуровневые изменения | `codex exec` (subprocess, JSON-режим) | `services/stage_comparison/store.py:1200` → `services/llm/codex_runner.py:709`; модель — литерал `gpt-5.6-luna` в `services/stage_comparison/project_change_summary.py:21` |

Итого 7 journeys, целиком построенных вокруг модели, и 2 с LLM-подшагом. У
J-25 таких подшагов теперь два — AI-review различий и верхнеуровневый синтез.
Второй устроен как гибрид: детерминированная маршрутизация решает, какие группы
вообще уходят в модель (`high_level_project_changes.py:418-449`), остальные
закрываются без неё (`store.py:1187`).

### 5.2. Что для replay уже есть

* **Подмена CLI подстановкой в `PATH`** — `backend/app/pipeline/execution/fake_providers.py`:
  `materialize()`, разбор `argv`, воспроизведение *фактического* контракта обоих
  CLI (`claude` пишет JSON-конверт на stdout, `codex exec` — финальный ответ в
  файл из `-o` и JSONL на stdout), поведения `ok|rate_limit|auth_error|timeout|broken_json`,
  журнал вызовов. Механизм подстановки готов; отдаёт **синтетику**.
* **Поддельный HTTP-шлюз OpenRouter** — `tests/distributed_audit_e2e/openrouter_stub.py`:
  настоящий сокет, настоящий `Authorization`, настоящий разбор ответа адаптером,
  фиксированный `usage` ради детерминизма, журнал с sha256-отпечатками вместо
  содержимого.
* **Легальный HTTP-шов на стороне воркера** —
  `AUDIT_WORKER_PROVIDER_OPENROUTER_BASE_URL` + `AUDIT_WORKER_PROVIDER_ENDPOINTS_STUBBED`
  (`audit_worker/providers/openrouter_adapter.py:109,115`): неофициальный хост
  принимается только при явном объявлении, и объявление уезжает в heartbeat.
* **Готовые ключи нормализованного запроса** —
  `audit_worker/providers/inference_ledger.py::call_key()` (sha256 от
  provider/purpose/prompt/attachments/action, есть состояние `STATE_REPLAY`,
  возвращающее сохранённый `ProviderInferenceResult` без обращения к модели) и
  `stages/block_analysis/stage02_paid_cache.py::compute_cache_key()`
  (sha256 от `model | block_id | prompt_text | image_identity`, schema v2 с
  нормализацией идентичности картинки вместо байтов).
* **Фабрика провайдеров** — `critic_v2/llm_gate.py::_make_provider()`
  (`mock|noop|claude_runner|openrouter`): место, куда `ReplayProvider` вставляется
  одной строкой. Но `run_llm_gate` вызывается только из скриптов и тестов, в
  production-конвейер не заведён.
* **Фактически записанные ответы моделей в git** —
  `experiments/stage_comparison_text_ai_reviewer/artifacts/runs/*.json`, 12
  файлов под контролем версий: `provider`, `requested_model`, `dataset_sha256`,
  `batches[].usage`, `batches[].answer` — дословный текст ответа. Ни один
  модуль их не читает; это evidence эксперимента, а не кассеты.
* **Ключ-значение ответов в рантайме** —
  `<project>/_output/_stage02_paid_response_cache/<key>.json` и
  `<project>/_output/audit_trail/<stage>_<ts>.json` (`claude_runner.py:95`,
  сохраняет `raw_text`, `json_data`, `finish_reason`, `response_id`). Оба
  каталога закрыты `.gitignore` и в CI недоступны.

### 5.3. Чего не хватает

1. **Кассет и формата кассеты нет.** Слово `cassette` не встречается в коде
   ни разу; `vcrpy`, `pytest-recording`, `respx`, `responses` отсутствуют в
   `requirements*.txt`, `pyproject.toml` и `constraints-qr-v1.txt`. Записанные
   ответы в `experiments/**` не имеют ключа запроса и не сопоставимы с вызовом.
2. **Нет шва у центрального OpenRouter.** Три независимых захардкоженных URL и
   три разных клиента: `openai.AsyncOpenAI` (`services/llm/llm_runner.py`,
   `OPENROUTER_BASE_URL` — литерал `config.py:784` без env-override), `httpx`
   (`gemma_findings_only.py:96`), `requests` (`critic_v2/llm_gate.py:1584`).
   Перенаправить центральный конвейер на replay-прокси сегодня нечем. Это ровно
   то, что зафиксировано в `docs/data_storage_modernization/00a_behaviour_freeze.md`
   §4.3 строкой «шва нет, нужен».
3. **Нет единой точки перехвата `claude -p`.** Шесть модулей зовут
   `subprocess.run` мимо `claude_runner._run_cli`: `absence_guard.py:314`,
   `critic_v2/kb_gate.py:174`, `critic_v2/llm_gate.py:1465`,
   `decision_carryover_service.py:335`, `migrated_findings_service.py:1233`,
   `discussions/discussion_service.py:435,656`. Подстановка бинаря в `PATH`
   их накрывает, а программная подмена — нет.
4. **Нет режима `record`** и нет правила «промах кассеты — ошибка, а не тихий
   фолбэк на живую модель». Действующий `stage02_paid_cache` при промахе идёт
   в сеть — для экономии денег это правильно, для детерминизма недопустимо.
5. **Нет глобального guard'а**, запрещающего живой вызов в прогоне тестов
   (§3.3). Сетевой guard существует только внутри стенда воркеров
   (`tests/distributed_audit_e2e/isolation.py`).
6. **Не сделаны предшествующие задачи.** Расписок `W0-LLM-01` и `W0-LLM-02` в
   `docs/architecture/receipts/` нет; ADR-0013 в статусе `proposed`. Без
   инвентаря промптов/норм/маршрутизации ключ кассеты не определён: неизвестно,
   какие входы обязаны в него входить.
7. **Санитизация не решена.** ADR-0013 §4 прямо запрещает автоматически
   превращать production payload в git fixture: промпт — это документация
   заказчика. Записанные ответы в `experiments/**` попали в git до появления
   этого правила и требуют отдельной проверки владельцем, прежде чем стать
   основой кассет.

### 5.4. Кандидат на первый LLM-journey с replay

**J-25, шаг AI-review текстовых различий.** Основания: настоящие ответы шести
моделей уже записаны и лежат в git (12 файлов, с `dataset_sha256` входа);
валидатор вокруг модели детерминирован и покрыт 40 unit-тестами
(`tests/test_stage_comparison_text_ai_reviewer.py`); journey не трогает
`03_findings.json` и потому дёшев в откате. Требуется: формат кассеты, ключ
запроса, шов на транспорте `claude`/`codex` для этого сервиса и проверка
санитизации записей.

**Запасной вариант — J-07 Stage 02.** У него уже есть нормализованный ключ
(`stage02_paid_cache.compute_cache_key`) и фактические ответы в `_output`, но
их нужно вынести из боевых данных, санитизировать и превратить промах в ошибку.
Цена выше, зато закрывается P0-journey основной цепочки.

## 6. Сводка покрытия

| Показатель | Значение |
| --- | --- |
| Journeys в каталоге | **30** (P0 — 21, P1 — 9) |
| Есть сквозной детерминированный тест (**Д**) | **16** |
| Покрыто частично (**Ч**) | **14** |
| Не покрыто вовсе (**Н**) | **0** |
| Из числа Д — с синтетической подменой модели | 2 (J-13, J-30) |
| Опираются на переиспользуемую golden fixture | **0 полностью; 1 частично (J-09), 1 через программную фабрику (J-30)** |
| LLM-journeys | 7 целиком + 2 с LLM-подшагом (у J-25 подшагов два) |
| LLM-journeys, проходящих replay на записанных ответах | **0** |

**Дотягивает ли перечень до 20–30.** Да: 30 journeys — верхняя граница
диапазона G0, и это не растяжка. При необходимости каталог сокращается до 24 без
потери P0: J-19, J-21, J-22, J-24, J-28, J-29 — приоритета P1.

**Но условие G0 №5 этим не закрыто, и вторая половина формулировки важнее
первой.** «Deterministic fixtures» в G0 означает именованный переиспользуемый
корпус, а не «тест не ходит в сеть». Такого корпуса нет: единственные каталоги
фикстур — `tests/fixtures/` (`agent_stream_v1_golden.json`, протокол
воркер↔центр, не journey; и появившийся на каноне
`g2_4_5_policy_cases_v2.json`, корпус случаев политики графического сравнения —
тоже не journey, потому что `graphic-comparison` в каталог не входит, §4.7) и
`backend/tests/fixtures/findings_review/` (5 файлов синтетических замечаний,
один шаг J-09). Данные каждого теста создаются его собственным
хелпером: локальные `_make_project` / `_make_v2_doc` / `_write_project`
обнаружены примерно в 35 файлах `tests/` и в 11 файлах `backend/tests/`, общей
фабрики в conftest нет. Поэтому честная формулировка состояния:

> Из 30 критических journeys 16 имеют сквозной детерминированный тест, 14 —
> частичный, ни один не опирается на версионированный golden-корпус, и ни один
> LLM-journey не воспроизводится на записанных ответах.

Разрыв до G0 — это ровно объём `W0-BEH-02` (fixtures) и `W0-LLM-02` (кассеты и
replay); `W0-BEH-01` его измеряет, а не закрывает.

### 6.1. Что чинить первым (вход для W0-BEH-02)

Порядок по отношению «стоимость журнала риска / стоимость fixture»:

1. **Корпус версии-образца.** Одна версия документа со всеми артефактами
   `_output/` в нормализованном виде, из которой строятся J-04, J-06…J-11,
   J-14…J-16, J-18, J-23, J-24. Без неё все Ч из §4.3 и §4.4 остаются Ч.
2. **Фикстура комплекта нового формата** (ZIP `pdf` + `*_results.md` +
   `*_results.html` + `*_blocks.json`) — закрывает пробел J-01 и снимает
   зависимость `backend/tests/test_results_md_parser.py` и соседей от
   `experiments/новая структура.`.
3. **Фикстура «версия N-1 с вердиктами эксперта»** — общий вход для J-12, J-13,
   J-20, J-21 и единственный способ проверять сохранность решений не по частям.
4. **Срез нормативной базы** для J-10; связано с §3.3 quality contract и
   `scripts/ci_provision_norms.py`.
5. **HTTP-концы**, не покрытые ни одним тестом при существующих сервисных
   тестах: `POST/GET /api/knowledge-base/expert-review/{project_id}` (J-20),
   `POST /api/audit/{id}/retry/{stage}` (J-16), `POST /api/export/excel` и
   `/api/export/excel/section` (J-23). Здесь fixture почти не нужна — нужен тест.

## 7. Что в каталог не вошло и почему

| Кандидат | Решение | Причина |
| --- | --- | --- |
| Обсуждение замечания (`/api/discussions/**`, 12 операций) | не journey сегодня | маршрут `#/project/{id}/discussions` удалён из UI коммитом `aeb0b2f2`; см. RI-1 в [route inventory](WEB_ROUTE_INVENTORY_V1.md). Тестов ноль — но и достижимости пользователем нет. Владелец решения о судьбе API — `W0-ADR-09` |
| План-график проверки | P2 | `tests/test_schedule.py` (64), `test_schedule_plans.py` (24), `test_schedule_completion_stamp.py` покрывают его; результат восстанавливается вручную |
| `critic-v2` UI и triage | не самостоятельный journey | экспериментальный контур, `CRITIC_V2_ENABLED` по умолчанию выключен, LLM в стадии принудительно отключён. Покрыт плотно (30 из 68 файлов `backend/tests/`), учтён внутри J-09 |
| Администрирование воркеров (одобрение, drain, ротация токена) | P1, но эксплуатационный | не пользовательский результат; покрыт `tests/test_distributed_workers_hardening.py`, `..._prepipeline_gate.py`, `..._center.py` |
| Реестр объектов и переключение текущего объекта | P2 | `tests/test_object_service_v2_creation.py`, `test_current_object_per_request.py` |
| Миграция `projects_v2` (45 файлов тестов) | не journey | это перенос хранилища, у него собственная программа `docs/data_storage_modernization/` |
| Геометрические профили и Вектограф | шаг внутри J-05 | 19 файлов тестов, но результат не наблюдается пользователем отдельно; большая часть требует боевого корпуса и скипается |

## 8. Чего этот документ не делает

* не изготавливает fixtures — это `W0-BEH-02`, и он же назначает формат корпуса;
* не пишет кассеты и не выбирает формат записи — это `W0-LLM-02` после
  `W0-LLM-01`;
* не правит ни одного теста и ни одной строки кода;
* не объявляет условие Gate G0 №5 выполненным: §6 фиксирует разрыв числом;
* не заменяет [route inventory](WEB_ROUTE_INVENTORY_V1.md) — маршрут есть адрес,
  journey есть сценарий, и одно не выводится из другого;
* не оценивает качество аудита. Precision/acceptance против решений эксперта
  меряет `scripts/eval_harness.py` (тест `tests/test_eval_harness.py`, 11), и это
  слой 3 из `docs/data_storage_modernization/00a_behaviour_freeze.md`, а не
  предмет `W0-BEH-01`.

## 9. Воспроизводимость

Числа §6 и §3.3 проверяются на срезе `6dc3aadf`:

```bash
F=docs/architecture/CRITICAL_JOURNEYS_V1.md

# 30 строк каталога; шаблон строки — "| J-NN |", он не совпадает
# со ссылками вида "| J-06 Stage 01 |" в таблице §5.1
grep -cE '^\| J-[0-9]{2} \|' $F                          # 30
grep -E  '^\| J-[0-9]{2} \|' $F | grep -c '\*\*Д\*\*'    # 16
grep -E  '^\| J-[0-9]{2} \|' $F | grep -c '\*\*Ч\*\*'    # 14
grep -E  '^\| J-[0-9]{2} \|' $F | grep -c '| P0 |'       # 21
grep -E  '^\| J-[0-9]{2} \|' $F | grep -c '| P1 |'       #  9

# каталоги фикстур: два, суммарно 7 файлов данных
find tests/fixtures backend/tests/fixtures -type f | grep -v README | wc -l   # 7

# кассет нет: ни одного вхождения в коде
grep -rli 'cassette' --include='*.py' . | wc -l                     # 0

# поверхность API, к которой относятся journeys
python3 -c "import json;d=json.load(open('contracts/http/v1/openapi.snapshot.json'));\
p=d['paths'];print(len(p),sum(1 for v in p.values() for m in v if m in ('get','post','put','patch','delete')))"
# 246 270 — снимок контракта пересобран на каноне; на срезе первой редакции было 243 265

# боевые данные в чекауте отсутствуют
grep -nx 'projects/' .gitignore                                     # 177:projects/
ls projects 2>/dev/null | wc -l                                     # 0 (каталога нет)
```

## 10. Ссылки

* [Roadmap](HYBRID_REWRITE_ROADMAP.md) — `W0-BEH-01`/`W0-BEH-02`, `W0-LLM-01`/`W0-LLM-02`, Gate G0
* [G0-readiness delta](G0_READINESS_DELTA.md) — строка 5 условий гейта
* [Quality/runtime contract v1](QUALITY_RUNTIME_CONTRACT_V1.md) — §5 test lanes, §3.3 norm corpus
* [Domain contract v1](DOMAIN_CONTRACT_V1.md) — идентификаторы, `analysis_status`, `run_state`, `import_state`, `decision_verdict`
* [Route/feature inventory UI v1](WEB_ROUTE_INVENTORY_V1.md) — адресуемость интерфейса
* [ADR-0012](adr/ADR-0012-legacy-analysis-package-protocol.md) §1.3, §10 — зависимость от этого каталога
* [ADR-0013](adr/ADR-0013-llm-reproducibility-and-cost.md) — `AnalysisProfile`, `ModelCallRecord`, три вида доказательства
* [Закрепление текущего поведения](../data_storage_modernization/00a_behaviour_freeze.md) — слои 1/2/3, шов записи кассет
* [Critic → Corrector](../critic_corrector.md), [Блоки и Stage 02](../blocks_and_stage02.md) — предметное описание J-05…J-11
