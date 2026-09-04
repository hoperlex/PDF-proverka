# Инвентарь категорий данных продукта — v1

**Задача:** `W0-DATA-01` (lane MIG).<br>
**Редакция:** 2026-09-04.<br>
**Источник истины:** рабочее дерево на каноническом коммите `6dc3aadf`
(`origin/main`). Каждая строка ниже прочитана из кода или измерена командой;
чего измерить нельзя — помечено явно (§2).<br>
**Перепроверка среза.** Инвентарь снимался на `53d85e99` (ветка `dev`), которая
не содержит 1613 файлов, добавленных в `origin/main` позже. Тридцать девять
ссылок с номерами строк сверены пословно, четыре перенесены на канон, одна
уточнена путём (`blocks.py` в дереве три штуки, документ не говорил какой).
Классы данных, появившиеся в каноне и отсутствовавшие в первой редакции,
вынесены отдельным разделом и не смешаны с перепроверенными.<br>
**Изменений кода задача не вносит.** Это frozen input для `ADR-0014`
(`W0-ADR-05`), `W0-SEC-02` (классификация и draft retention matrix), а также для
`ADR-0007`/`ADR-0008` (объёмы) и `W1-MIG-01` (перенос).

**Условия Gate G0, которые закрывает документ:**

- №6 «inventory не содержит неразобранной категории данных» — §3–§12: 55
  категории, у каждой назван писатель, читатель, класс и срок либо его
  отсутствие;
- №14 «неизвестные/неоднозначные данные имеют статус, владельца и решение» —
  §15: 24 развилки и 7 позиций со статусом «назначение из кода не установлено»,
  у каждой причина, варианты и тот, кто решает.

Документ не объявляет G0 пройденным и не принимает ни одного решения по
retention: он даёт факты, на которых решение можно принять.

## 1. Граница инвентаризации

Инвентаризируется **всё, где продукт хранит данные**: именованное место на
диске (каталог, файл, таблица), в которое продукт пишет или из которого читает,
и которое отличается от соседних владельцем, классом чувствительности или
сроком хранения.

Внутрь границы попадают и места, которые обычно инвентарём не считают, но
которые фактически удерживают данные: история git и её удалённая копия, рабочие
деревья, резервные копии, создаваемые операцией удаления, и каталоги вне
репозитория (`/var/lib/**`, `/etc/**`, `~/.claude/**`).

Вне границы: исходный код приложения, зависимости, документация самой программы
миграции, сгенерированные отчёты CI.

Инвентарь фиксирует **фактическое** состояние, в том числе дефектное. Строка
«ретеншна нет» не означает разрешения его добавить: правки принадлежат
`ADR-0014`, `W0-SEC-02` и задачам волны 1.

**Именованного владельца данных в документах программы нет.** `ADR-0014`
называет роли («product/data owner, security/privacy, storage operations») и в
матрице пишет «назначить». Пока роль не занята конкретным человеком, ни один
класс из §15 закрыть нельзя — это, а не отсутствие цифр, главный блокер
`ADR-0014`.

## 2. Что удалось измерить и что нет

Этот чекаут — **не production**. `CLAUDE.md` и `AGENTS.md` прямо говорят, что
живой портал работает из `/home/coder/auditmanager/current`, а данные прибиты к
рабочему дереву разработки через `AUDIT_DATA_DIR`. В песочнице этого дерева нет.

Что измерено сегодня (команды — §17):

| Место | Размер | Файлов |
| --- | ---: | ---: |
| `projects_v2/` | 28 МБ (28 007 009 байт) | 116 |
| `norms/` | 60 МБ | 41 |
| `backend/app/data/` | 3.0 МБ | 42 |
| `prompts/` | 1.1 МБ | 152 |
| `deliverables/` | 3.3 МБ | 8 |
| `experiments/` | 6.0 МБ | 154 |
| `logs/` | 48 КБ | 2 |
| `.git/` | 550 МБ | — |
| worktrees `../wt/` | 1.4 ГБ | 4 дерева |

Чего в этом чекауте физически нет, хотя код это адресует: `projects/` (пуст),
`knowledge_base/` , `cache/block_crops/`, `отчет/`, `comparison_sources/`,
`norms/vault/`, `critic v2 test/`, `backend/app/data/users.json`,
`/var/lib/auditmanager/distributed_workers`, `/var/lib/audit-worker`,
`/etc/auditmanager/pki`.

Следствие: **все объёмы ниже — нижняя граница, а не production baseline.**
Числа production можно взять только на живом дереве, и это работа `W0-OPS-01`,
не этой задачи. Что известно из документов программы и НЕ перепроверено сегодня:

| Число | Источник | Дата |
| --- | --- | --- |
| legacy `projects/` = 11 ГБ, диск заполнен на 92% | `docs/projects_v2_legacy_quarantine_plan.md` | 2026-07-10 |
| кропы блоков 12.2 ГБ / 64 764 файла при заполнении 98% | `docs/block_crop_lifecycle.md` | 2026-08-03 |
| 440 версий в `projects_v2`, у 183 index блоков только в `runs/` | `docs/block_crop_lifecycle.md`, `projects_v2_adapter.py:425` | 2026-08-03 |
| 20 433 записи в `decisions_log.json` на 117 проектах | `knowledge_base_service.py:29-30` | 2026-08-06 |
| дедуп кропов освободил 3.6 ГБ, 16564/16564 файла байт-идентичны | `docs/block_crop_lifecycle.md` | 2026-08-03 |

Эти пять чисел — единственная имеющаяся эмпирика production-масштаба. Они
собраны для других задач, не для инвентаря, и их пересъём на дату решения
остаётся за владельцем.

**Сверка с `W0-OPS-01`.** Выпущенный в тот же день
[`OPS_BASELINE_V1.md`](OPS_BASELINE_V1.md) §3.6 измерил ту же единственную
версию независимо и даёт `du -sb` = 28 000 785 байт против 28 007 009 у
инвентаря (разница — `_system/old_to_new_map.json` и `object.json`, которые
инвентарь считает, а baseline нет). Оттуда же — **амплификация хранения 3.07×
от входного PDF** и доля растровых кропов в `03_analysis/` — 77 %. Два
независимых измерения сошлись; ни одно из них не является production-объёмом
(§2, первый абзац).

## 3. Сводная таблица категорий

Класс — по матрице `ADR-0014` §3: `source` (source documents/versions),
`findings` (findings/expert decisions/audit trail), `derived` (derived
artifacts/cache/index), `llm` (LLM request/response evidence), `logs`
(logs/traces/action journal), `exports` (exports/temp uploads). Прочерк в
колонке класса означает, что **категория не попадает ни в один класс матрицы** —
разбор в §16.

«Лейн» — техническое владение по таблице capability lanes роадмапа §3.2. Оно не
заменяет владельца данных (§1).

| ID | Категория | Где | Лейн | Класс | ПДн / тайна | Ретеншн | Erasure |
| --- | --- | --- | --- | --- | --- | --- | --- |
| D-01 | Входной комплект версии | `projects_v2/**/versions/vNNN/01_input/` | STO | source | тайна заказчика | нет | удаляется с документом, но уезжает в backup |
| D-02 | Нормализованные рабочие копии | `.../02_work/` | STO | source | тайна заказчика | нет | то же |
| D-03 | Legacy-дерево проектов | `projects/**` | MIG | source | тайна заказчика | нет | best-effort rmtree |
| D-04 | Реестры identity | `objects.json`, `object.json`, `document.json`, `version.json`, `version_group.json`, `_system/old_to_new_map.json` | MIG | — | название и адрес объекта заказчика | нет | частично |
| D-05 | JSON-этапы конвейера | `.../03_analysis/latest/`, `.../03_analysis/runs/<run_id>/` | ENG | derived | производное от документа заказчика | нет | с документом |
| D-06 | Кропы блоков (PNG) + `index.json` | `.../blocks_stage02_100/`, `blocks_gemma_100/`, `blocks/` | ENG | derived | фрагменты чертежей заказчика | вытеснение выключено по умолчанию | с документом |
| D-07 | Векторные графы блоков и shadow-профили | `.../block_vector_graphs/**` | AI | derived | производное от чертежей | нет | с документом |
| D-08 | LRU-кэш кропов | `cache/block_crops/` | ENG | derived | фрагменты чертежей | LRU: 1.5 ГБ, min age 900 с | **не чистится при удалении проекта** |
| D-09 | Кэш платных ответов Stage 02 | `.../_output/_stage02_paid_response_cache/<key>.json` | AI | llm | сырой ответ модели по блоку заказчика | нет | с каталогом `_output` |
| D-10 | Audit trail вызовов моделей | `.../_output/audit_trail/<stage>_<ts>.json` | AI | llm | полный результат модели | нет | с каталогом `_output` |
| D-11 | Экспертные решения версии | `.../04_review/expert_review.json` (+ legacy пути) | META | findings | **ФИО эксперта**, тайна заказчика | нет | с документом |
| D-12 | Сквозной журнал решений | `knowledge_base/decisions_log.json` | META | findings | **ФИО эксперта**, ответы заказчика | нет | **остаётся** |
| D-13 | Паттерны замечаний | `knowledge_base/patterns.json` | META | findings | имя принявшего решение | нет | остаётся |
| D-14 | Планы и закрытия смен | `knowledge_base/work_plans.json`, `schedule_completion.json` | META | findings | **ФИО инженера**, выработка | нет | остаётся |
| D-15 | Обсуждения замечаний с моделью | `.../_output/discussions/<item_id>.json` | AI | llm | свободный текст инженера + контент заказчика | нет | с каталогом `_output`; есть точечный DELETE |
| D-16 | Реестры замечаний заказчика | `backend/app/data/external_registers/<obj>__<reg>.json` | META | findings | **переписка заказчика**, `user_confirmed_by` | нет | **удаления в коде нет** |
| D-17 | Durable audit journal | `logs/actions/actions-YYYY-MM-DD.jsonl` | OPS | logs | **логин сотрудника** в `actor` | 180 дней, удаление работает | остаётся до TTL |
| D-18 | Diagnostic journal | `logs/actions/diag-YYYY-MM-DD.jsonl` | OPS | logs | усечённый IP, пути с `project_id` | 14 дней, удаление работает | остаётся до TTL |
| D-19 | Журнал конвейера версии | `pipeline_log.json`, `audit_log.jsonl`, `audit_log_<ts>.jsonl` | ENG | logs | пути и ошибки с именами проектов | архивация при новом прогоне | с каталогом |
| D-20 | Логи процесса сервера | `logs/server.log`, `server.err.log`, ротированные `server.<ts>.log` | OPS | logs | не установлено | 10 последних, ротация при старте | остаётся |
| D-21 | Журналы заданий центра | `<DISTRIBUTED_WORKERS_DATA_DIR>/job_logs/<job>/<attempt>.jsonl` | JOB | logs | события выполнения после redaction | **нет** | остаётся |
| D-22 | Учёт токенов и длительностей | `backend/app/data/usage_data.json`, `usage_offsets.json` | OPS | logs | `project_id`, модель, стоимость | **30 дней, работает** | остаётся до TTL |
| D-23 | Forensic-журналы платных вызовов | `paid_cost_events.jsonl`, `paid_api_blocked_events.jsonl`, `paid_cost.json` | OPS | — | `project_id`, `object_id`, стоимость | **нет по дизайну** | остаётся навсегда |
| D-24 | Транскрипты Claude Code | `~/.claude/projects/**` (чужие файлы) | AI | — | сессии инженеров, папка→имя | не наш файл | недостижимо |
| D-25 | Очереди выполнения | `batch_queue.json`, `prepare_queue.json` | JOB | — | `project_id`, абсолютные пути в `error` | нет; есть ручной `clear_queue_history` | остаётся |
| D-26 | Конфигурация из интерфейса | `stage_models.json`, `stage_batch_modes.json`, `hidden_projects.json`, `project_groups.json`, `stage_comparison_saved_config.json` | API | — | нет | нет | частично |
| D-27 | Оптимизация раздела | `backend/app/data/section_optimization/<obj>/<SEC>/`, `section_optimization_pipeline/<obj>__<SEC>.json` | ENG | derived | **спецификации оборудования заказчика** | нет; `history/` копится | остаётся |
| D-28 | Reverse-файлы переименований | `project_rename.reverse.json`, `rename_project.reverse.json`, `cleanup_containers.reverse.json` | MIG | — | старые/новые имена проектов | нет | остаётся |
| D-29 | Учётные записи сотрудников | `backend/app/data/users.json` | API | — | **ФИО, инициалы, логин, роль** | нет | ручной DELETE, следы в D-12 остаются |
| D-30 | Пароли и сессии портала | env `PORTAL_AUTH_USERS`; подписанный cookie | API | — | **логин + pbkdf2-хэш пароля** | сессия 24 ч; отзыва нет | смена секрета |
| D-31 | Секреты приложения | `.env` (0600, вне git) | OPS | — | ключ OpenRouter и прокси | нет | ручное |
| D-32 | Состояние распределённого контура | `<data_dir>/workers.db` (36 таблиц, SCHEMA_VERSION 13) | JOB | — | `project_display_name`, хэши токенов, `source_ip` оператора | `retention_until` = метка; **строки не удаляются** | остаётся |
| D-33 | Пакеты заданий и результатов центра | `<data_dir>/{source_packages,incoming,result_staging,validated_results,rejected_results,superseded_results}/` | JOB | source+derived | **весь каталог версии заказчика в архиве** | нет | остаётся |
| D-34 | Локальное состояние воркера | `/var/lib/audit-worker/**` (`worker.db`, `jobs/`, `token`, `claim_secret`, `providers/`, `trash/`, `runtime/tombstones/`) | JOB | source+llm | документы заказчика на чужом VPS; **токен в открытом виде** | 30 дней, **удаление по умолчанию выключено** | не покрывается erasure центра |
| D-35 | Криптографический материал | `/etc/auditmanager/pki/**`, `AUDIT_WORKER_GRPC_KEY_STORE_DIR/client-key.pem` | OPS | — | приватные ключи issuing CA и воркеров | сертификат 30 дней, ротация есть | не относится |
| D-36 | Нормативный индекс | `norms/norms_db.json`, `norms_paragraphs.json`, `tools/paragraphs.jsonl` (57 МБ), `tools/embeddings.npz`, `tools/status_index.json` | AI | — | тексты стандартов | нет | не относится |
| D-37 | Корпус текстов норм | `norms/vault/**` (в дереве отсутствует) | AI | — | тексты стандартов, правовой статус не установлен | нет | не относится |
| D-38 | Промпты и профили дисциплин | `prompts/pipeline/**`, `prompts/disciplines/**`, `_registry.json` | AI | — | нет | нет | не относится |
| D-39 | Очередь недостающих норм | `missing_norms_vault.json`, `missing_norms_queue.json`, `missing_norms_report.json` | AI | — | по дизайну только обозначения норм | нет | не относится |
| D-40 | Сессии сравнения стадий | `comparison/sessions/<id>/pairs/<pair>/*.json` | WEB | derived | производное от документов заказчика | **нет; удаления в коде не найдено** | остаётся |
| D-41 | Исходники сравнения стадий | `comparison_sources/**` | WEB | source | документы заказчика | нет | остаётся |
| D-42 | Excel-отчёты | `отчет/audit_report_*.xlsx` и др. | STO | exports | замечания + решения + ФИО | **нет, копятся бессрочно** | остаётся |
| D-43 | ZIP-пакет аудита | собирается в памяти, отдаётся потоком | STO | exports | весь комплект версии | на диск не ложится; временный xlsx удаляется | не применимо |
| D-44 | Резервные копии удаления | `projects_v2/_system/destructive_backups/<backup_id>/` | STO | source | полная копия всех версий документа | **явно «никакого auto-cleanup»** | **erasure сюда не доходит** |
| D-45 | Pre-Codex снимки каталога вывода | `<COMPARISON_ROOT>/classic_codex_ab/backups/<project>/<vid>_<action>_<ts>/` | ENG | derived | копия всех JSON/MD/XLSX проекта и `audit_trail/` | нет | **вне каталога проекта, erasure не доходит** |
| D-46 | Сырые ответы модели по блокам | `_output/_stage01_findings_only_runs/<ts>__<model>_<effort>/block_<ID>.json`, `summary.json` | AI | llm | полный ответ модели по каждому блоку заказчика | нет | с каталогом `_output` |
| D-47 | Снимки ансамбля оптимизации | `_output/_optimization_ensemble/<run_id>/**`, `optimization_{claude,codex}.json` | AI | llm | выход каждой ноги ансамбля + входные артефакты | нет | с каталогом `_output` |
| D-48 | Артефакты повторного триажа | `_output/critic_v2/critic_v2_*.json` (имя из `CRITIC_V2_OUTPUT_SUBDIR`) | AI | derived | ре-триаж findings, метрики, inline-карта | нет | с каталогом `_output` |
| D-49 | Слепок вердиктов между прогонами | `_output/verdict_preservation_snapshot.json`, `verdict_preservation_report.json` | META | findings | вердикты + фингерпринты замечаний; наличие ФИО не установлено | нет; **переживает «Очистить»** | остаётся при очистке проекта |
| D-50 | Кэш вектор-кропов портала | `<версия>/01_input/crops/<block_id>.pdf`, `crops_manifest.json` | STO | derived | одностраничные PDF-кропы чертежей заказчика | потолки 64 МБ/файл и 2 ГБ/документ; TTL нет | с документом |
| D-51 | Переопределения промптов проекта | `_output/prompt_overrides.json` | AI | — | `{stage: текст промпта}`; содержит ли данные заказчика — не установлено | нет | с каталогом `_output` |
| D-52 | Диагностические копии findings | `03_findings_pre_{restart,merge,dedup,norm,review}.json`, `03_findings.json.broken`, `*.classic.bak.json`, `03_findings_codex_base.json`, `03_findings_targeted_*.json` | ENG | derived | промежуточные состояния мастер-файла замечаний | **очистки нет ни у одной** | с каталогом `_output` |
| D-53 | Ledger графических изменений пары | `comparison/sessions/<id>/pairs/<pair>/graphic_change_ledger.json` | WEB | derived | текст из PDF заказчика в `address_hints[].text`, до 160 символов на подсказку | **нет; удаления в коде не найдено** | остаётся |
| D-54 | Верхнеуровневые изменения проекта П↔РД | `comparison/sessions/<id>/pairs/<pair>/high_level_project_changes.json` | WEB | llm | `summary`/`before`/`after`/заголовки из документов заказчика **и решения модели** | **нет; удаления в коде не найдено** | остаётся |
| D-55 | Текстовые сущности пары | `comparison/sessions/<id>/pairs/<pair>/text_entities.json` | WEB | derived | проектные обозначения заказчика (`display_names`, например `ЩРа-5`) | **нет; удаления в коде не найдено** | остаётся |

Итого: **55 категорий**: 52 от сплошного прохода первой редакции и три
(D-53…D-55), добавленные перепроверкой на каноническом срезе — §11.

- **Содержимое документов заказчика либо прямые производные** — 32: D-01, D-02,
  D-03, D-05…D-12, D-15, D-16, D-19, D-27, D-33, D-34, D-40…D-50, D-52,
  D-53…D-55.
- **Идентификаторы заказчика без содержимого** (название объекта, `object_id`,
  `project_id`, имя документа) — ещё 10: D-04, D-13, D-17, D-18, D-21, D-22,
  D-23, D-25, D-28, D-32.
- **Персональные данные сотрудников** — 11: D-11 (ФИО эксперта), D-12, D-13,
  D-14, D-16 (`user_confirmed_by`), D-17 (`actor` = логин), D-24, D-29, D-30,
  D-32 (`source_ip`, `user_agent` оператора), D-18 (усечённый IP).
- **Секреты и криптографический материал** — 3: D-30, D-31, D-35.
- **Не имеют класса в матрице `ADR-0014` вовсе** — 16 (§16).

К этим 55 добавляются четыре места, которые продукт не «хранит» в смысле
записи, но которые удерживают ровно те же данные и потому обязаны попасть в
любую политику удаления, — они разобраны в §12 и в таблице выше отсутствуют
намеренно, чтобы не смешивать хранилище с его копиями.

**Оговорка о раскладке.** Категории с маской `_output/…` физически лежат в
одном из трёх мест в зависимости от режима хранилища: `<проект>/_output/`
(legacy), `<версия>/_output/` (контейнер версий) или
`<версия>/03_analysis/{latest,runs/<run_id>}/` (`projects_v2`). Резолвер —
`gemma_enrichment_contract.gemma_output_root` (ContextVar → env
`AUDIT_OUTPUT_DIR` → `03_analysis/latest` → `_output`) и
`manager._output_dir_for_project`. Это одна категория данных в трёх адресах, а
не три категории. Исключение: `discussions/`, `expert_review.json` и
shadow-артефакты в `projects_v2` намеренно остаются в стабильном `_output/`,
потому что `03_analysis/latest` пересоздаётся.

## 4. Документы заказчика и их версии (D-01…D-04)

Раскладка `projects_v2` описана нормативно в `docs/projects_v2_storage_standard.md`
и на диске выглядит так (единственный документ в этом чекауте):

```text
projects_v2/objects/<объект>/disciplines/<Д>/documents/<код>/versions/v001/
  01_input/   9.5 МБ  — <base>.pdf, <base>_results.md, <base>_results.html,
                        <base>_blocks.json, project_info.json, input_manifest.json
  02_work/     10 МБ  — document.pdf, document.md, ocr.html, result.json, blocks.json
  03_analysis/7.6 МБ  — latest/ (+ runs/<run_id>/ на живом дереве)
  04_review/    пусто — expert_review.json
  05_export/    пусто
  99_service/   пусто
```

Три факта, важные для объёмов и для `ADR-0008`:

1. **Входной PDF хранится дважды.** `01_input/<base>.pdf` и
   `02_work/document.pdf` — 9 133 138 байт каждый, разные inode (`1837231` и
   `1837236`), жёсткой ссылки нет. На один документ это 18.3 МБ вместо 9.1 МБ.
   Дублирование — по стандарту (`01_input` объявлен неизменяемым), но цена его
   до сих пор не была посчитана.
2. **`03_analysis` умеет держать две копии одного и того же.** `runs/<run_id>/`
   объявлен «VERBATIM копией legacy `_output`», `latest/` — выжимкой. На живом
   дереве у 183 из 440 версий index блоков лежит **только** в `runs/`, то есть
   run-папка обслуживает интерфейс и «историей» не является. Считать `runs/`
   удаляемым мусором нельзя.
3. **Уровень «объект» — это заказчик.** `objects.json` хранит имя вида
   `213. Мосфильмовская 31А "King&Sons"` — номер стройки, адрес и название
   организации в одном поле. То же значение зашито в код:
   `backend/app/core/config.py:127` `OBJECT_NAME`, откуда
   `object_service._ensure_default_object` создаёт объект по умолчанию.
   Это не тестовая строка — она совпадает с объектом на диске.

Ещё два свойства входного комплекта:

- `input_manifest.json` хранит `pdf_sha256`, `bundle_fingerprint` и по каждому
  файлу `role`/`name`/`sha256`/`size`. Это готовый инструмент проверки после
  удаления («доказательство purge» из `ADR-0014` §4), который сегодня для этой
  цели не используется;
- **исходники защищены от очистки на уровне кода.** `clear_project_data`
  (`project_service.py:3810`, предикат `is_source_file`) явно исключает `.pdf`
  и `.md`: операция «Очистить» их не трогает. Это правильно для рабочего
  сценария и неверно для erasure — путь удаления должен быть другим, и его нет.

`D-03` (`projects/**`) в этом окружении пуст: `.env` содержит
`AUDIT_PROJECTS_V2_WRITE_MODE=projects_v2_primary`, cutover был 2026-06-23.
Legacy-дерево при этом ещё не выведено: `docs/projects_v2_legacy_deletion_checklist.md`
говорит «НЕ выполнен», а `docs/projects_v2_legacy_quarantine_plan.md` фиксирует
11 ГБ и правило «`projects/` НЕЛЬЗЯ удалять напрямую, сначала только
quarantine archive». Судьба этих 11 ГБ — открытый вопрос §15.

## 5. Производные артефакты анализа (D-05…D-10, D-46…D-52)

Конвейер — 17 stage-каталогов (`backend/app/pipeline/stages/`). Каждый этап
пишет JSON, следующий читает его. Файлы, которые встречаются в коде конвейера
чаще всего, и их писатели:

| Файл | Пишет | Читает |
| --- | --- | --- |
| `document_graph.json` | `stages/prepare/process_project.py` | почти все этапы, `findings_service._enrich_sheet_page` |
| `block_batches.json`, `block_batches.runtime.json` | `stages/crop_blocks/blocks.py::generate_block_batches`, `stages/block_analysis/runner.py::write_single_block_runtime_plan` | `manager.py`, `merge_block_results`, `resume_detector.py` |
| `block_batch_NNN.json` — **ответы модели по пакету** | `services/llm/claude_runner.py::run_block_batch`, `gemini_direct_runner.py` | `blocks.py::merge_block_results` |
| `01_blocks_analysis.json` | `stages/block_analysis/**` | `stages/findings_merge/**` |
| `02_text_analysis.json` | `stages/text_analysis/**` | `stages/findings_merge/**` |
| `03_findings.json` | `stages/findings_merge/**`, `stages/findings_verify/runner.py` | интерфейс, экспорт, база знаний |
| `03_findings_review.json` | `stages/findings_review/**` | интерфейс |
| `norm_checks.json`, `03a_norms_verified.json` | `stages/norms/**` | `norms/_core.py update` |
| `optimization.json`, `optimization_review.json` | `stages/optimization/runner.py` | интерфейс, экспорт |
| `pipeline_log.json` | `services/common/audit_logger.py:162` | `usage_service` |
| `block_context_summary.json`, `step1_locality_debug.json` | `stages/block_context/**` | диагностика |

Фактически на диске в единственной версии этого чекаута: `audit_log.jsonl`
(16 КБ), `block_context_summary.json` (116 КБ), `document_graph.json` (476 КБ),
`pipeline_log.json` (4 КБ), `step1_locality_debug.json` (60 КБ),
`blocks_stage02_100/` (5.8 МБ, 47 PNG), `block_vector_graphs/` (1.2 МБ). Прогон
до findings не дошёл, поэтому `03_findings.json` отсутствует — это состояние
дерева, а не отсутствие категории.

**D-06/D-08, кропы.** Это исторически крупнейшая статья на диске: 12.2 ГБ /
64 764 файла (`docs/block_crop_lifecycle.md`, 2026-08-03). Механизмы управления
жизненным циклом написаны, но **выключены по умолчанию**:
`BLOCK_CROP_RESTORE_ENABLED=False`, `BLOCK_CROP_EVICTION_ENABLED=False`,
`BLOCK_CROP_EVICTION_DRY_RUN=True` (`config.py:1253`, `1287`, `1288`). Работает
только LRU самого кэша: `BLOCK_CROP_CACHE_MAX_BYTES` 1.5 ГБ,
`MAX_FILE_BYTES` 64 МБ, `MIN_FREE_BYTES` 2 ГБ, `MIN_AGE_S` 900,
`SWEEP_EVERY` 50. То есть в production сегодня кропы не эвакуируются, а кэш —
единственное место с реальным потолком.

**D-09, кэш платных ответов.** `backend/app/pipeline/stages/block_analysis/stage02_paid_cache.py`
кладёт в `<project>/_output/_stage02_paid_response_cache/<sha256>.json` сырой
ответ модели по блоку вместе с `parsed`, токенами и `elapsed_ms`. Ключ —
хэш от модели, `block_id`, системного промпта, пользовательского текста,
обогащения, текста страницы и идентичности изображения. TTL нет. Каталог
исключён из пакета воркера (`project_package.py:113`), то есть на воркер
не уезжает, но на центре живёт вечно вместе с `_output`.

**D-10, audit trail.** `services/llm/claude_runner.py:95-137` пишет
`<project>/_output/audit_trail/<stage>_<ts>.json` с полями `stage`, `model`,
`timestamp`, токены, `duration_ms` и **полным результатом модели**. Семь точек
вызова. Ретеншна нет; `manager.py:2884-2887` копирует каталог в бэкапы.

**Мест хранения ответов моделей внутри каталога проекта не два, а пять.**
Кроме D-09 и D-10 это:

- **D-46** `_output/_stage01_findings_only_runs/<UTC ts>__<model>_<effort>/block_<ID>.json`
  (`stages/block_analysis/gemma_findings_only.py:2357`, `:3020`) — полный ответ
  модели по каждому блоку плюс `summary.json` с биллинговыми токенами. Пишется
  как страховка при обрыве прогона; очистки нет;
- **D-47** `_output/_optimization_ensemble/<run_id>/` (`stages/optimization/ensemble.py:483-499`)
  — снимок входных артефактов и выход каждой ноги ансамбля. Предыдущие
  `optimization_claude.json` / `optimization_codex.json` переносятся сюда и
  только потом удаляются из `_output`; сам каталог не чистится;
- **D-48** `_output/critic_v2/critic_v2_{triage,triage_ui,inline_map,metrics,stage_summary}.json`
  (`stages/critic_v2_triage/runner.py:387-439`) — read-only повторный триаж
  замечаний; `03_findings_review.json` не меняет, TTL не имеет.

Шестое место — `_output/block_batch_NNN.json`, распарсенные ответы модели по
пакету блоков (`claude_runner.py::run_block_batch`, `gemini_direct_runner.py`).
Оно единственное из шести имеет уборку: `blocks.py merge --cleanup`
(`stages/crop_blocks/blocks.py:2098-2100`), `unlink` перед retry (`manager.py:5224`) и маска
`block_batch_*.json` в `_clean_stage_files`.

`ADR-0014` называет класс «LLM request/response evidence» одним классом с
одним TTL. Сегодня у него **шесть адресов, из которых пять не имеют ни TTL, ни
уборки, и ни один не имеет границы объекта**: всё лежит внутри каталога проекта
и наследует его судьбу.

**D-49, слепок вердиктов.** `verdict_preservation_snapshot.json` хранит вердикты
и фингерпринты замечаний (лист, категория, severity, нормализованный текст,
«значимые числа»), чтобы переаудит не терял решения при перенумерации `F-NNN`.
В `projects_v2` файл живёт в `04_review/` и **переживает операцию «Очистить»** —
то есть после очистки проекта его findings-производные всё ещё на диске.
Удаления у файла нет.

**D-50, вектор-кропы.** `services/common/crop_cache.py` кладёт в
`<версия>/01_input/crops/<block_id>.pdf` одностраничные PDF-кропы, полученные
от портала, с манифестом (`schema_version`, `crop_source_mode`, `counts`,
`entries[]` со `status` и `source`). Потолки заданы: 64 МБ на файл, 2 ГБ на
документ; TTL нет. Это ещё одна копия графики заказчика рядом с PNG-кропами.

**D-52, диагностические копии findings.** Мастер-файл `03_findings.json`
сохраняется под другими именами в шести точках: `03_findings_pre_restart.json`
(`manager.py:2748`), `_pre_merge`, `_pre_dedup`, `_pre_norm`, `_pre_review`,
плюс `03_findings.json.broken` (сырой невалидный JSON до ремонта кавычек),
`01_blocks_analysis.classic.bak.json` и целевые `03_findings_targeted_*.json`.
`_clean_stage_files` удаляет из них только `03_findings_pre_review.json`.
Остальные остаются до `rmtree` всего каталога. Для инвентаря это значит, что
findings существуют на диске в 3–8 экземплярах на версию.

**Уточнение к `CLAUDE.md`.** Документация называет каталогом кропов
`blocks_gemma_100`; фактический production-каталог, который создаёт
`stages/crop_blocks/runner.py::build_crop_args`, — **`blocks_stage02_100`**.
`blocks_gemma_100` и `blocks_gemma_300` создаются только явной командой и
остаются legacy-профилями. Плюс алиас `_output/blocks/` — жёсткие ссылки на
`blocks_stage02_100`, пересоздаётся для совместимости. Для инвентаря это три
имени одной категории D-06, а не три категории.

## 6. Экспертные знания и решения (D-11…D-16)

Это самая чувствительная группа: она соединяет данные заказчика с
персональными данными сотрудников.

**D-11.** `expert_review.json` пишется в `<version>/04_review/` (канон v2), с
чтением из трёх legacy-путей. Поля решения: `item_id`, `item_type`, `decision`,
`rejection_reason` (свободный текст эксперта), **`reviewer`** (ФИО),
`timestamp`, поля переноса между версиями.

**D-12.** `knowledge_base/decisions_log.json` — сквозной append-журнал тех же
решений по всем объектам. Поля записи (`backend/app/models/expert_review.py`):
`id` (`DEC-NNNN`), `object_id`, `source_project`, `section`, `item_id`,
`severity`, `category`, `summary`, `norm_refs[]`, `sheet`, `page`,
`grounding_level`, `primary_block_ids[]`, **`expert_decision`**,
**`expert_reason`**, **`expert_reviewer`** (ФИО), `expert_date`,
`customer_response`, `customer_confirmed`, `customer_date`, `customer_note`.
Атрибуция при включённой auth серверная: логин сессии →
`user_service.get_user_by_login` → `user["name"]`
(`api/routers/knowledge_base.py:25-54`). Ротации нет; на 2026-08-06 в журнале
20 433 записи по 117 проектам. Есть точечный `revoke_decision`; массового
удаления и TTL нет.

**D-14.** `work_plans.json` хранит `engineer_id`, **`engineer_name`**, плановую
выработку, период; `schedule_completion.json` — `reviewer` и дату закрытия. Это
данные о труде конкретных работников, и они живут бессрочно.

**D-16, реестры замечаний заказчика.** `backend/app/data/external_registers/<object_id>__<register_id>.json`
хранит разбор письма заказчика: `source_md` (путь к исходному письму),
`entries[]` с `problem`, `description`, `proposed_solution`, `risk`,
`customer_response_raw`, `customer_comment` и — отдельно — **`user_confirmed_by`**
и `user_confirmed_at`. Это переписка третьей стороны, попавшая в наше
хранилище. **Удаления реестров в сервисе нет вовсе**: повторный импорт
перезаписывает `entries`, сохраняя подтверждения.

**D-15, обсуждения.** `<version>/_output/discussions/<item_id>.json` — диалог
инженера с моделью по конкретному замечанию: `messages[]` с `role`
(`user`/`assistant`), свободным `content`, токенами и стоимостью. Имени автора
там нет — только `role: "user"`; кто это был, восстанавливается лишь косвенно
через `actor` в D-17. Содержимое сообщений уходит во внешние LLM, изображения
передаются base64. Есть `DELETE /api/discussions/{project_id}/{item_id}` и
`truncate`; TTL нет. В ZIP-экспорт обсуждения попадают целиком.

## 7. Журналы и телеметрия (D-17…D-24)

`W0-LOG-01` разделила журнал на три канала, и это единственное место в
продукте, где ретеншн реализован и работает.

**D-17, durable audit.** `logs/actions/actions-YYYY-MM-DD.jsonl`. Фактический
allowlist — `backend/app/core/action_log.py:168-193`, 16 полей с пределами
длины: `actor` 200, `project_id` 300, `method` 10, `route` 300, `status`,
`stage` 100, `event` 200, `level` 20, `logger` 200, `duration_sec`, `severity`
40, `required_permission` 100, `reason` 200, `role` 60, `auth_enabled`,
`max_bytes`. Плюс служебные `ts`, `kind`, `eid`. Расширяется только через
`ACTION_LOG_AUDIT_EXTRA_FIELDS`.

`actor` — **логин сотрудника из cookie** (`action_log.py:774-780`). То есть
вечный журнал на 180 дней поимённо фиксирует, кто какой маршрут вызвал. Это
осознанное свойство («кто из инженеров что сделал» — комментарий в
`config.py:1166`), но его правовое основание и срок не подтверждены никем (§15).

**D-18, diagnostic.** `diag-YYYY-MM-DD.jsonl`, лимиты `action_log.py:200-209`:
`path` 500, `query` 500, `message` 2000, `error` 500, `exc` 3000, `traceback`
3000, `ip` 60, `dur_ms`. Любое неизвестное поле сохраняется с усечением до 300
символов, при «секретном» имени — `[redacted]`. `ip` усекается
(`_redact_ip`: IPv4 → `a.b.c.x`, IPv6 → /64), `query` пишет значение только для
allowlist-параметров.

**Ретеншн реален, но триггер у него нетипичный.** `_cleanup_prefix`
(`action_log.py:96-108`) удаляет файлы старше cutoff по обоим префиксам,
каждый со своим сроком (180 и 14 дней). Планировщика нет: чистка вызывается из
`_write_record` при первой записи в новый день, новый каталог или после
рестарта процесса. Следствие: **если сервер молчит, старые файлы не удаляются
никогда.** `logrotate`/cron в репозитории нет.

Потолок `ACTION_LOG_MAX_DAY_BYTES` = 256 МБ **общий на оба канала**; при
превышении события дропаются, в каждый файл однократно пишется маркер
`day_cap_reached`. На границе бюджета выигрывает durable audit.

Флагов `ACTION_LOG_*` — 13 плюс `AUDIT_ACTION_LOG_DIR`; `.env.example`
описывает только 9 из них (нет `REDACTION`, `DIAG_ENABLED`,
`DIAG_RETENTION_DAYS`, `AUDIT_EXTRA_FIELDS`, `QUERY_ALLOW_EXTRA`).

**Журнал на диске сегодня — дораздельного формата.** Единственный содержательный
файл `logs/actions/actions-2026-08-25.jsonl` (189 строк) написан до разделения:
в нём в одном канале лежат `path`, `query`, `ip` и текст исключения, например
`"error": "crop subprocess failed: exit code 1: [ERROR] *_result.json не найден в /root/.../projects/AR/13АВ-РД-АР-ТП1-ТП2_V1"`.
Это не дефект текущего кода, но это данные, которые уже лежат на диске в
непредусмотренной новым контрактом форме, и их судьба — вопрос §15.

**D-22.** `usage_data.json` — единственный сторедж с внятным TTL по времени:
`MAX_RECORD_AGE_DAYS = 30`, отсечка при каждом `_save()`.

**D-23.** `paid_cost_events.jsonl` и `paid_api_blocked_events.jsonl` —
append-only и **намеренно без ротации**: докстринг
`services/llm/paid_api_events.py` называет их forensic-источником истины и
запрещает truncate даже при `clear_project_usage`. Поля включают `project_id`,
`object_id`, `version_id`, `stage`, `cost_usd`, `response_id`, `pid`.

**D-24 — самая неожиданная строка инвентаря.**
`services/common/usage_service.py:42` объявляет
`CLAUDE_SESSIONS_DIR = Path.home()/".claude"/"projects"`, и `GlobalUsageScanner`
разбирает **все JSONL-транскрипты Claude Code** в домашнем каталоге, включая
сопоставление имени папки с именем проекта. Продукт читает файлы, которые ему
не принадлежат, которые он не создавал и содержимое которых он не
контролирует. Что в этих транскриптах — из нашего кода не следует.

## 8. Состояние приложения (D-25…D-28)

`APP_DATA_DIR` = `backend/app/data/` (override `AUDIT_APP_DATA_DIR`).
Канонический перечень «живого рантайм-стейта» кодифицирован в
`backend/tests/conftest.py:26-45`.

Отдельно стоит **D-27**. `section_optimization_pipeline/<object_id>__<SECTION>.json`
и `.snapshot.json` — результат сквозной оптимизации раздела по всем проектам
объекта. В снапшоте, лежащем в этом чекауте, — `meta.project_count` 18,
`specification_rows` 1952, `shared_specification_groups` 257, и строки вида

```json
{"row_id":"SPEC-432f0e5eaca0d7","project_id":"13АВ-РД-МЗ","page":23,
 "sheet_name":"Спецификация оборудования, изделий и материалов",
 "name":"Провод установочный медный, сечением 1x25",
 "type_mark":"ПугПнг(A)-HF 1x25 ж/з"}
```

Это спецификация оборудования реального объекта. Файл **отслеживается git**
(§12), размер 2 484 215 байт.

Очереди D-25 персистятся: `batch_queue.json` атомарно (`manager.py:510-527`),
`prepare_queue.json` — нет. В `prepare_queue.json` поле `error` содержит
абсолютные пути файловой системы.

## 9. Учётные записи, сессии и секреты (D-29…D-31)

**Источник истины по паролям — не файл, а окружение.** `PORTAL_AUTH_USERS`
хранит `логин:pbkdf2-хеш` через запятую. Сессия — **stateless подписанный
cookie**: payload `{"u": username, "exp": epoch}`, base64url + HMAC-SHA256 на
`PORTAL_SESSION_SECRET`; при отсутствии секрета — эфемерный per-process
секрет. TTL по умолчанию 24 часа. Серверного хранилища сессий нет, и **отозвать
отдельный токен нельзя**: массовая инвалидация — только сменой секрета или
удалением логина.

`users.json` (в этом чекауте отсутствует) содержит `id` (слаг фамилии), `login`,
`surname`, `initials`, `name` («Фамилия И. О.»), `role`, `created_at`. Ни
e-mail, ни телефона, ни хэша пароля в нём нет. При удалении пользователя его
записи в `decisions_log.json` **сохраняются** — имя эксперта остаётся в базе
знаний.

`.env` в корне (0600, вне git) содержит `OPENROUTER_API_KEY`, адрес и версию
прокси LLM, лимиты платного API и режим хранилища. Значения здесь не
приводятся; для инвентаря важно, что это отдельная категория с отдельным
владельцем и что она физически лежит рядом с данными.

**Реальные логины сотрудников лежат в отслеживаемых git файлах.**
`.env.example:209-211` и `deploy/systemd/backend.env.example` содержат
`DISTRIBUTED_WORKERS_VIEWER_SUBJECTS=igor,alexey,filipp,marina,alexandra` и
`DISTRIBUTED_WORKERS_ADMIN_SUBJECTS=andrey`. Там же
`AGENT_GATEWAY_SERVER_IDENTITY=176.12.77.128`; этот адрес встречается ещё в
двух десятках документов `docs/distributed_audit_workers/**` и в
`audit_worker/providers/claude_adapter.py`.

## 10. Распределённый контур (D-32…D-35)

Корень состояния центра — `DISTRIBUTED_WORKERS_DATA_DIR`, по умолчанию
`/var/lib/auditmanager/distributed_workers` (**вне репозитория и вне любого
релиза**). В этом окружении каталога нет: `DISTRIBUTED_WORKERS_ENABLED` по
шаблону `backend.env.example` равен `false`.

**D-32, `workers.db`.** Одна SQLite-база (WAL, `SCHEMA_VERSION = 13`), 36
таблиц. Gateway своей базы не имеет — пишет в эту же. Что в ней есть с точки
зрения классификации:

- имя документа заказчика: `logical_jobs.project_display_name`,
  `project_external_id`, `project_version_id`;
- секреты — **только хэшами**: `worker_tokens.token_sha256`,
  `job_attempts.execution_token_hash`, `workers.claim_secret_sha256`,
  `worker_bootstrap_registration_tokens.token_hash`,
  `worker_identity_reenrollment_authorizations.token_sha256`. В схеме есть
  явные комментарии, что колонок самих токенов нет намеренно;
- `worker_certificates.certificate_pem` — публичный лист, приватного ключа нет;
- **`worker_admin_actions`** — append-only журнал действий операторов с
  `actor_id`, `role`, `source_ip`, `user_agent`, `reason`. Это персональные
  данные, и удаления у таблицы нет по проекту;
- `idempotency_keys.response_json` хранит **целиком** ответ на запрос;
- `registration_rate_limit` ключует по хэшу, а не по IP — сознательно.

**Ретеншна как удаления в центре нет.** `RETENTION_DAYS = 30`
(`job_service.py:72`) проставляет `job_attempts.retention_until` только после
подтверждённого приёма результата — и это всё: строки завершённых заданий,
попыток и событий не удаляются никогда. `DELETE` в подсистеме встречается лишь
трижды: обрезка `resource_snapshots` до 200 на воркера, `_prune_history` для
`provider_quota_snapshots` (120 дней / 5000 строк) и чистка окон
`registration_rate_limit`. `VACUUM` есть только как `VACUUM INTO` для бэкапа
перед миграцией. `job_logs/*.jsonl` (D-21) не ротируются вовсе.

**D-33, что уезжает на воркер.** Управляющая часть задания данных заказчика не
содержит: `AuditPipelineParams` объявлен `extra="forbid"` и состоит из профилей,
действий и хэшей; `PackageTransferDescriptor` несёт только размеры и хэши.
Данные едут отдельным каналом — **source package**. `project_package.scan_version_tree`
обходит **весь каталог версии** и берёт все файлы, кроме явных списков
запрещённых имён/суффиксов (`.env`, `.pem`, `token`, `claim_secret`,
`workers.db`, `expert_review.json`, нормативные артефакты) и двух
регенерируемых каталогов. То есть **PDF заказчика, PNG-кропы чертежей и все
JSON-артефакты этапов физически копируются на удалённый воркер.**
Обратно возвращаются только `03_analysis/`, `99_service/`, логи (обрезка до
8 МБ), `usage/` и `result/`; исходный PDF назад не едет.

**D-34, воркер.** Корень `/var/lib/audit-worker` (`AUDIT_WORKER_ROOT`). Там
лежат `worker.db` (6 таблиц, лизы `lease_expires_at`, LEASE_SEC 120),
`worker_state.json`, **`token` и `claim_secret` в открытом виде (0600)**,
`jobs/<job>/<attempt>/` с `metadata.json` (0600, внутри `execution_token`),
`source/`, `work/`, `result/`, `events/`, `logs/`, `uploads/`,
`inference/<key>.result.json` (**сырые ответы провайдера**, в результат-пакет не
включаются и остаются на воркере), `providers/<p>/{home,runtime,metadata}`
(0700, авторизация LLM-CLI), `trash/`, `runtime/tombstones/<attempt>.json`.

Ретеншн у воркера — единственный в продукте, написанный как отдельный
компонент (`audit_worker/retention.py`): 30 дней, порядок «tombstone → перенос в
`trash/` → стирание», запрет удаления при `retention_until IS NULL` даже при
нехватке диска, отчёт в `runtime/retention_report.json`. Но
**`AUDIT_WORKER_RETENTION_DELETE_ENABLED` по умолчанию `false`**, и в
systemd-юните исполнителя тоже `false` — то есть сегодня это сухой прогон.
Tombstone остаётся навсегда. Из `worker.db` строки не удаляются вовсе.

**D-35, PKI.** `/etc/auditmanager/pki/issuer/issuing-ca-key.pem` (приватный
ключ выдающего CA), `/etc/auditmanager/pki/gateway/server-key.pem`,
`worker-trust/worker-ca-bundle.pem`; на воркере —
`<AUDIT_WORKER_GRPC_KEY_STORE_DIR>/client-key.pem` (на Linux защищён правами
ОС, на Windows DPAPI; через argv/env/API не принимается). Срок сертификата
воркера 30 дней, ротация автоматическая с jitter.

## 11. Нормы, промпты, сравнение стадий и экспорт (D-36…D-43, D-53…D-55)

**D-36/D-37.** `norms/norms_db.json` больше не авторитетен; истина по статусам —
`norms/tools/status_index.json`, по текстам — корпус `norms/vault/**`, которого
в дереве нет. Самый крупный файл продукта вне git — `norms/tools/paragraphs.jsonl`,
57 МБ (58 932 351 байт в истории). Сеть используется в одном месте:
`scripts/ci_provision_norms.py --acquire` тянет versioned artifact по адресу из
env, сверяет SHA-256 и распаковывает в `norms/vault`. Верификация цитат идёт
через MCP-сервер норм; `WebSearch`/`WebFetch` в нормативном контуре запрещены
концептуально и помечены в коде.

**D-38.** Профили дисциплин (`role.md`, `checklist.md`, `norms_reference.md`,
`config.json` и др.) для 14 дисциплин. Писателей у самих `.md` в коде нет —
они правятся вручную и через git; из кода пишется только `_registry.json`.

**D-40/D-41, сравнение стадий.** `COMPARISON_ROOT` (по умолчанию
`<repo>/comparison`) хранит `sessions/<id>/session.json` и
`sessions/<id>/pairs/<pair>/{pair.json, sheet_match_suggestions.json,
sheet_links.json, ...}`. `.gitignore` описывает содержимое как «сессии,
рендеренные страницы PDF, crop'ы блоков, alignment-карты, diff'ы».
`comparison_sources/**` — «реальные документы сравниваемых стадий».
**Ни удаления, ни TTL, ни владельца у этой пары в коде не найдено**;
`docs/DOCUMENT_COMPARISON_CURRENT_STATE.md` описывает фичу как минимальный
каркас без аналитического конвейера. В этом чекауте оба каталога пусты или
отсутствуют.

**D-53/D-54/D-55, дельта канона.** Первая редакция снималась на срезе, где этих
трёх артефактов не существовало. На каноне каталог пары пополнился ими, и
описание «минимальный каркас без аналитического конвейера» для него больше не
верно.

| Файл | Схема | Кто пишет | Что внутри от заказчика |
| --- | --- | --- | --- |
| `graphic_change_ledger.json` (`paths.py:92-93`) | `graphic-change-ledger.v1`, файл `graphic_comparison/graphic_change_ledger.schema.json` | `POST …/graphic-comparison` (`store.py:1831`) | `address_hints[].text` — сырые текстовые спаны из PDF, обрезанные до 160 символов (`graphic_comparison/mode1.py:172`), плюс `pdf_sha256` и имя `blocks.json` |
| `high_level_project_changes.json` (`paths.py:88-89`) | `kind=stage_comparison_high_level_project_changes`; **отдельного `*.schema.json` нет** | `POST …/high-level-project-changes` (`store.py:1271-1273`) | `summary`, `before`, `after`, заголовки и подписи листов (`high_level_project_changes.py:673-680`) — те же тексты уходят во внешнюю модель |
| `text_entities.json` (`paths.py:96-97`) | `text-entities.v1`, файл `unified_entity_bridge/text_entities.schema.json` | тот же POST high-level (`store.py:1274-1276`), GET `text-entities` не пишет ничего | проектные обозначения заказчика в `display_names` |

Четыре свойства этих трёх категорий важны для `ADR-0014`.

1. **Ретеншна нет ни у одной**, как и у D-40/D-41: `@router.delete` у
   `/api/stage-comparison` нет ни одного, TTL и фонового удаления в
   `store.py`/`paths.py` не найдено. Единственный механизм — пометка `stale` по
   подписи источника (`store.py:1776-1785`), которая ничего не удаляет.
2. **`D-54` — первая категория класса `llm` за пределами конвейера аудита.**
   Артефакт хранит решения модели вместе с `usage`, `model_calls` и
   `fresh_model_calls` (`high_level_project_changes.py:853-856`), поэтому его
   удаление означает не пересчёт, а новый платный недетерминированный прогон.
3. **`D-55` производен полностью** — детерминированная функция от `D-54` без
   PDF, OCR и модели (`unified_entity_bridge/text_entity_producer.py:1-7`),
   и это единственная из трёх категория, которую можно удалять свободно.
4. **Схемы у двух из трёх есть, у `D-54` — нет.** В коде объявлена только
   `RESPONSE_SCHEMA` для ответа модели (`high_level_project_changes.py:129`);
   формат самого артефакта проверяется рантайм-валидатором, файла json-schema
   под него в дереве не найдено.

Отдельно: `paths.py:100-105` объявляет ещё два пути — `graph_entities.json` и
`entity_links.json`, — под которые в дереве лежат схемы, но продюсеров в коде
нет. Это объявленные, но ненаполняемые категории; в инвентарь как данные они не
попадают, а в §15 как неоднозначность — да.

**D-42/D-43, экспорт.** Excel пишется в `REPORTS_DIR` = `<repo>/отчет/` с
именами `audit_report_YYYYMMDD_HHMM.xlsx`; содержит замечания, оптимизации и
колонки «РЕШЕНИЕ»/«ПРИЧИНА ОТКЛОНЕНИЯ» из `expert_review.json`. **Ротации и
удаления нет** — файлы копятся бессрочно; скачивание через
`GET /api/export/download/{filename}` с проверкой префикса. ZIP-пакет аудита
собирается в памяти и на диске не остаётся; временный xlsx удаляется в
`finally`; временный файл Excel-импорта решений — тоже.

## 12. Копии, тени и архивы: где данные остаются после удаления

Эти четыре места не являются самостоятельными хранилищами — они хранят копии
уже перечисленных категорий. Именно поэтому их нельзя пропустить: любая
политика удаления, которая их не называет, не работает.

### 12.1. История git и её копия на GitHub

Измерено сегодня: в объектной базе **17 048 блобов на 1889.6 МБ**, из них

- `projects/**` — **6218 блобов, 845.2 МБ**;
- `experiments/**` — 2676 блобов, 285.8 МБ;
- `knowledge_base/**` — 21 блоб, 34.6 МБ (максимальная версия
  `decisions_log.json` — 5 369 334 байта).

Расширения блобов `projects/**`: 3171 `.json`, **2380 `.png`**, 449 `.md`,
158 `.html`, 35 `.csv`, 24 `.jsonl`, 1 `.xlsx`. PDF в истории нет — `*.pdf`
исключён `.gitignore` с самого начала. PNG — это кропы чертежей заказчика,
`.md` — OCR-текст его документов.

Из `origin/main` достижимо **6886** объектов пути `projects/**`. Remote —
`https://github.com/hoperlex/PDF-proverka.git`. То есть данные объектов уже
находятся у стороннего хостера; приватность репозитория из рабочего дерева не
проверяется и остаётся вопросом владельца (§15, A-05).

Каталоги `projects/` и `knowledge_base/` сейчас в `.gitignore` — но
`.gitignore` действует вперёд, а не назад. Удаление файла из рабочего дерева не
удаляет его из истории.

### 12.2. Данные заказчика, отслеживаемые git сегодня

Не только история — рабочее дерево тоже. Отслеживаются:

- `backend/app/data/section_optimization_pipeline/73a0e59a__EOM.snapshot.json`
  (2.4 МБ, 1952 строки спецификаций 18 проектов объекта `73a0e59a`) и парный
  `73a0e59a__EOM.json`. Внесены коммитом с сообщением
  «wip: снапшот незакоммиченных правок перед слиянием origin/main»;
- `deliverables/audit_trackers/**`, `deliverables/sds_chat_history/**`,
  `deliverables/sds_manual/**` — разборы замечаний реальных проектов
  (`ПД-00542664-АИТ.ГСВ_V1`, `ПД-00542664-СКД`, `СТ26_01-14-ОВ1-3-РД_V1`) с
  названием объекта заказчика в заголовке;
- `docs/graphic_anchors/пробы/corpus_results.jsonl` — 1187 строк по полному
  корпусу блоков с именами файлов чертежей и геометрией.

### 12.3. Рабочие деревья

`../wt/` — 1.4 ГБ, четыре worktree. Каждое содержит полную копию
отслеживаемых файлов, поэтому снапшот `73a0e59a__EOM.snapshot.json` существует
на диске в **5 экземплярах** (проверено `find … | wc -l`). Пилот изоляции
worktree (`W0-WS-01`) увеличивает число копий данных заказчика линейно по числу
деревьев — это следствие, которое ни в одном документе программы не отмечено.

### 12.4. Резервные копии, создаваемые удалением (D-44)

В режиме `projects_v2_primary` (а он включён) `delete_project` идёт через
`_delete_project_v2_primary` (`services/common/project_service.py:663`), который
**перед удалением делает backup ВСЕХ версий** документа в
`projects_v2/_system/destructive_backups/<backup_id>` и пишет подтверждение в
`_system/destructive_confirmations.jsonl`. В `services/storage/v2_primary_wiring.py:298`
это зафиксировано дословно:

> «Никакого auto-cleanup: восстановление и retention остаются явными действиями.»

То есть **сегодня удаление проекта не удаляет данные, а перемещает их в
каталог без срока хранения и без владельца.**

К этому добавляются архивы, объявленные планами вывода legacy:
`projects_legacy_archive_<date>` (правило «сначала только quarantine archive») и
`~/archives/legacy-rescue-20260710/` (спасённые вендор-листы и реестр СУ-10).
Ни того, ни другого в этой песочнице нет; существуют ли они на живом сервере —
подтверждает владелец.

### 12.5. Снимки каталога вывода в чужом корне (D-45)

`manager._snapshot_output_before_codex_run` (`manager.py:2833-2900`) перед
Codex-прогоном копирует **все** `*.json`, `*.jsonl`, `*.md`, `*.xlsx` каталога
вывода и весь `audit_trail/` в
`<COMPARISON_ROOT>/classic_codex_ab/backups/<project>/<vid>_<action>_<ts>/`
вместе с `_snapshot_meta.json`.

Это копия findings, анализа блоков, текста и полных ответов моделей **вне
каталога проекта, в корне другой подсистемы** (`COMPARISON_ROOT`, по умолчанию
`<repo>/comparison`). Ни TTL, ни очистки, ни связи с удалением проекта у неё
нет. Ни один путь удаления из §14 её не затрагивает.

## 13. Ретеншн: фактическая картина

Сроки, которые реально реализованы кодом и срабатывают:

| Где | Срок | Механизм | Оговорка |
| --- | --- | --- | --- |
| `logs/actions/actions-*.jsonl` | 180 дней | `_cleanup_prefix`, `unlink` | триггер — запись, а не таймер: при простое не чистится |
| `logs/actions/diag-*.jsonl` | 14 дней | то же | то же |
| `usage_data.json` | 30 дней | отсечка в `_save()` | срабатывает только при записи |
| `cache/block_crops/` | по объёму | LRU 1.5 ГБ, min age 900 с | это кэш, а не хранилище |
| `provider_quota_snapshots` | 120 дней / 5000 строк | `_prune_history` | только квоты |
| `resource_snapshots` | последние 200 на воркера | обрезка при вставке | телеметрия |
| `logs/server*.log` | 10 последних | ротация в `start_server.sh` при старте | не Python |
| `<worker>/jobs/**` | 30 дней | `audit_worker/retention.py` | **удаление выключено по умолчанию** |
| сертификаты воркеров | 30 дней | автоматическая ротация | не данные заказчика |

Отдельно стоит единственная автоматическая чистка «осиротевших» артефактов во
всём конвейере: `stages/block_context/builder.py:315-321` удаляет из
`block_vector_graphs/` все `*.json`, которых нет в текущем `index.json`. Это
образец того, чего нет больше нигде, — и одновременно источник дефекта:
shadow-пакеты профилей она тоже задевает (`docs/ar_ceiling_lighting_profile.md`).

Остальное — этапные файлы, которые сносит `_clean_stage_files` при перезапуске
этапа (списки: `manager.py:3821-3826`, `3842-3847`, `3905-3908`, `3955-3957`,
`4058-4062`, `5412-5422`), и разовые ручные операции: `blocks.py merge --cleanup`
(`unlink` всех `block_batch_*.json`), «Очистить проект» (`rmtree(_output)` или
`rmtree(03_analysis)` с обязательным backup), `clear_queue_history`,
`revoke_decision`, `DELETE /api/discussions/...`. Это не ретеншн: это
инвалидация результата этапа, привязанная к запуску, а не ко времени и не к
классу данных.

Всё остальное растёт бессрочно. Явно и намеренно бессрочны: forensic-журналы
платных вызовов (D-23), `worker_admin_actions`, tombstone'ы воркера,
`destructive_backups` (D-44). Без объявленного намерения, просто потому что
уборщика не написали: `audit_trail/` (D-10), `_stage01_findings_only_runs/`
(D-46), `_optimization_ensemble/` (D-47), `critic_v2/` (D-48),
`verdict_preservation_snapshot.json` (D-49), `01_input/crops/` (D-50),
диагностические копии findings (D-52), `audit_log_*.jsonl` (D-19), pre-Codex
снимки (D-45), сессии сравнения (D-40), Excel-отчёты (D-42),
`job_logs/*.jsonl` (D-21), строки `workers.db` (D-32).

Ни одна из этих политик не выражена как retention **класса данных**: они
привязаны к файлу или таблице. Матрица `ADR-0014` требует обратного — политики
по классу с наследованием класса производными артефактами.

## 14. Что произойдёт при erasure-запросе сегодня

Сценарий: заказчик требует удалить всё, относящееся к объекту
`d9dee80b` («213. Мосфильмовская 31А "King&Sons"»).

Что продукт умеет:

| Действие | Что делает | Ссылка |
| --- | --- | --- |
| `DELETE /api/projects/{project_id}` | v2-primary: backup всех версий → `rmtree` каталога документа → чистка `old_to_new_map` → best-effort удаление legacy-папки. Legacy-режим: удаление v2-документа по карте → `rmtree` legacy → `unhide_project` → инвалидация кэша | `project_service.py:663`, `:784` |
| `DELETE /api/projects/{id}/versions/{vid}` | удаление одной версии (тоже с backup) | `api/routers/projects.py:592` |
| `DELETE /api/projects/{id}/clean` | очистка данных проекта | `api/routers/projects.py:936` |
| `DELETE /api/objects/{object_id}` | удаляет **только запись объекта**; докстринг прямо говорит «файлы проектов не удаляются» | `api/routers/objects.py:66` |
| `DELETE /api/discussions/{pid}/{item}` | удаляет один файл обсуждения | `api/routers/discussions.py:339` |
| `POST /api/knowledge-base/revoke` | удаляет одну запись решения | `knowledge_base_service` |
| `DELETE /api/users/{user_id}` | удаляет учётную запись; записи в журнале решений сохраняются | `api/routers/users.py:96` |

Чего не произойдёт ни при одном из этих вызовов — то есть что останется на
диске после «полного удаления объекта»:

1. **Резервная копия всех версий** в `_system/destructive_backups` — без срока
   и без уборщика (§12.4);
2. `knowledge_base/decisions_log.json` — все решения по удалённым проектам,
   с ФИО экспертов и ответами заказчика (D-12);
3. `knowledge_base/patterns.json`, `work_plans.json`, `schedule_completion.json`
   (D-13, D-14);
4. `external_registers/<object_id>__*.json` — переписка заказчика; удаления
   в коде нет вовсе (D-16);
5. `section_optimization/<object_id>/**` и
   `section_optimization_pipeline/<object_id>__*.json` — спецификации
   оборудования объекта (D-27);
6. `paid_cost_events.jsonl`, `paid_api_blocked_events.jsonl`, `paid_cost.json` —
   с `object_id`, `project_id`, `version_id` (D-23);
7. `usage_data.json` — до истечения 30 дней (D-22);
8. `logs/actions/actions-*.jsonl` — `project_id` в durable-канале до 180 дней;
   `diag-*` — пути до 14 дней (D-17, D-18);
9. `cache/block_crops/**` — кропы чертежей; связи с проектом у кэша нет
   (D-08);
10. `workers.db` — `logical_jobs.project_display_name` и все попытки; строки не
    удаляются никогда (D-32);
11. `<data_dir>/{source_packages,validated_results,...}` — архивы с полным
    каталогом версии (D-33);
12. `/var/lib/audit-worker/jobs/**` на каждом воркере, где задание выполнялось,
    — включая `source/` с PDF; удаление по умолчанию выключено (D-34);
13. `comparison/sessions/**` (D-40) и `comparison_sources/**` (D-41);
14. `<COMPARISON_ROOT>/classic_codex_ab/backups/**` — снимки каталога вывода
    вместе с `audit_trail/` (D-45, §12.5): удаление проекта их не видит, потому
    что они лежат в корне другой подсистемы;
15. `отчет/*.xlsx` — все ранее выгруженные отчёты (D-42);
16. **история git и её копия на GitHub** — 845 МБ артефактов `projects/**`,
    достижимых из `origin/main`, плюс отслеживаемые сегодня файлы §12.2, плюс
    их копии в четырёх worktree.

Отдельно про операцию «Очистить проект». В `projects_v2` она делает
`rmtree(03_analysis)` с пересозданием `latest` и обязательным
`backup_version_before_destructive`. То есть очистка тоже оставляет полную
копию версии в `destructive_backups`, а `verdict_preservation_snapshot.json`
(D-49) и `_output/discussions/**` (D-15) она вообще не трогает — они лежат вне
`03_analysis` намеренно.

Вывод для `ADR-0014`: **у продукта нет операции erasure.** Есть удаление
каталога документа, которое к тому же оставляет полную резервную копию.
Требования §4 ADR-0014 — object/tenant scope, инвалидация производных, dry-run,
count/size preview, idempotency, post-delete reconciliation, метрики overdue
retention — не реализованы ни одним из перечисленных путей. Это не оценка
качества, а перечень того, чего в коде нет.

## 15. Неоднозначные и неизвестные категории (условие G0 №14)

Ниже — то, по чему решение принять **нельзя без владельца данных**. Формулировка
«вероятно, ПДн нет» здесь не годится и не используется: если основания нет,
записано «требует решения».

| ID | Категория | Почему неоднозначна | Варианты | Кто решает |
| --- | --- | --- | --- | --- |
| A-01 | Название и адрес объекта (D-04, `OBJECT_NAME` в коде) | `213. Мосфильмовская 31А "King&Sons"` — номер стройки, адрес и организация. Является ли это охраняемой договором информацией, определяется договором, а не архитектурой. От ответа зависит класс всей цепочки D-01…D-12 | (а) тайна заказчика → минимальный класс для всей цепочки; (б) открытая справочная информация; (в) псевдонимизировать `object_id` и убрать имя из кода | владелец данных + юрист по договору |
| A-02 | ФИО экспертов в D-11…D-14 | Работник идентифицируется поимённо в бессрочном журнале решений. Основание обработки и срок хранения из кода не выводятся | (а) трудовые отношения, срок = срок хранения проектной документации; (б) псевдонимизация после закрытия объекта; (в) хранить только `user_id` | владелец данных + кадры |
| A-03 | `actor` = логин в durable audit 180 дней (D-17) | Поимённая фиксация действий сотрудника на полгода. Срок выбран технически, не юридически | (а) подтвердить 180 дней; (б) сократить; (в) хранить хэш логина, а расшифровку — отдельно и короче | владелец данных + OPS (`W0-LOG-01`) |
| A-04 | Усечённый IP в diag-канале (D-18) | `a.b.c.x` — обезличенные данные или всё ещё ПДн, зависит от толкования и от того, сеть внутренняя или нет | (а) считать обезличенным, оставить 14 дней; (б) убрать IP полностью; (в) 7 дней | security/privacy |
| A-05 | 845 МБ артефактов заказчика в истории git, достижимых из `origin/main` (§12.1) | Данные уже у стороннего хостера. Приватность репозитория, юрисдикция и допустимость по договору из дерева не проверяются. Удалить файл нельзя — только переписать историю | (а) подтвердить, что приватный репозиторий у этого провайдера допустим договором; (б) переписать историю и форсировать push; (в) завести новый репозиторий без истории; (г) перенести на собственный хостинг | владелец программы + владелец данных + юрист |
| A-06 | Снапшот спецификаций объекта, отслеживаемый git (§12.2, D-27) | 2.4 МБ реальных спецификаций 18 проектов лежат в git и размножены по 5 деревьям. Попали коммитом «wip». Нужны ли они как fixture — не установлено | (а) удалить из индекса и истории; (б) заменить синтетикой и оставить как fixture; (в) оставить как есть, признав репозиторий носителем данных заказчика | владелец данных + ARC |
| A-07 | Разборы замечаний в `deliverables/**` (§12.2) | Полные аудиты реальных проектов с названием объекта, отслеживаются git. Это поставочный документ или данные заказчика в репозитории кода — из содержимого не следует | (а) вынести в отдельное хранилище с доступом; (б) обезличить; (в) оставить, зафиксировав как осознанное исключение | владелец данных |
| A-08 | Реальные логины сотрудников и IP в отслеживаемых `.env.example` / `deploy/**` (§9) | Шесть логинов и адрес шлюза в файлах, которые копируются в каждый клон | (а) заменить на placeholders; (б) признать служебной информацией без ограничений | владелец данных + OPS |
| A-09 | `destructive_backups` без срока (D-44) | Механизм сознательно отказывается от auto-cleanup. Пока срок не назначен, удаление не является удалением | (а) TTL + уборщик; (б) перенос в отдельное хранилище с контролем доступа; (в) отказ от backup при явном erasure-запросе (отдельный путь) | владелец данных + STO |
| A-10 | Чтение `~/.claude/projects/**` (D-24) | Продукт разбирает транскрипты сессий Claude Code, включая сопоставление папки с именем. Что в них содержится и чьи это данные — из нашего кода не следует. Назначение (подсчёт лимитов подписки) известно, правовой статус — нет | (а) признать служебной телеметрией и ограничить чтение только счётчиками; (б) отказаться от источника; (в) явно уведомить инженеров и зафиксировать основание | владелец данных + AI |
| A-11 | Сырые ответы провайдера на воркере (`inference/*.result.json`, D-34) | Остаются на удалённом VPS, в результат-пакет не включаются, в erasure центра не входят. Срок и класс не назначены | (а) класс `llm`, TTL как у попытки; (б) не хранить вовсе; (в) хранить только на центре | AI + JOB |
| A-12 | `job_logs/*.jsonl` на центре (D-21) | Ротации нет вообще, объём не ограничен | (а) TTL как у durable audit; (б) объёмный потолок; (в) перенос в общий журнал | JOB + OPS |
| A-13 | Бессрочные строки `workers.db` (D-32) | `retention_until` — метка, а не удаление. Задания, попытки, события и `worker_admin_actions` копятся навсегда | (а) удаление по `retention_until` + отдельный срок для admin-журнала; (б) архивирование; (в) признать audit trail вечным осознанно | JOB + владелец данных |
| A-14 | Forensic-журналы платных вызовов (D-23) | Бессрочность объявлена в коде как свойство. Но записи содержат `object_id`/`project_id` удалённых объектов | (а) подтвердить бессрочность, обезличив идентификаторы; (б) TTL; (в) разделить на финансовую (вечную, обезличенную) и проектную (со сроком) части | владелец данных + OPS |
| A-15 | Реестры замечаний заказчика (D-16) | Переписка третьей стороны, `user_confirmed_by`, удаления в коде нет вовсе. Класс не определён: это и findings, и входящий документ | (а) класс `findings` со сроком проектной документации; (б) отдельный класс «входящие документы третьих лиц»; (в) не хранить исходный текст, только сопоставление | владелец данных |
| A-16 | Сессии и исходники сравнения стадий (D-40, D-41) | Фича описана как минимальный каркас; ни удаления, ни TTL, ни владельца-лейна в коде нет. Назначение хранения после закрытия сессии не установлено | (а) TTL сессии; (б) привязать к версии документа и удалять вместе с ней; (в) признать временным рабочим пространством и чистить при рестарте | владелец фичи (WEB/ENG) + владелец данных |
| A-17 | `critic v2 test/` — рабочее пространство ручного фидбека | Каталог по умолчанию для `CRITIC_V2_FEEDBACK_DIR` и `CRITIC_V2_UI_EXPORT_PATH`; читается эндпоинтами, писателя в продуктовом коде нет. **Назначение и происхождение содержимого из кода не установлены** | (а) объявить временным и исключить из хранения; (б) перенести в `APP_DATA_DIR` с классом; (в) удалить фичу | AI |
| A-18 | `experiments/**` — 285.8 МБ в истории git (замер первой редакции), 1668 отслеживаемых файлов и 225 МБ в рабочем дереве на каноне `6dc3aadf` | Содержит `vector_block.json` из реальных документов (12+ МБ на файл). На срезе первой редакции отслеживаемых файлов было **154**; канон добавил сюда основную часть волны — это самый быстрорастущий каталог продукта, и растёт он материалом реальных проектов. Ценность как эталона против стоимости и риска не оценена | (а) вынести из репозитория; (б) сократить до минимального набора; (в) оставить и признать | AI + ARC |
| A-19 | Корпус текстов норм `norms/vault` (D-37) | Тексты стандартов получаются versioned artifact'ом по внешнему адресу. Условия распространения и хранения текстов из кода не следуют | (а) подтвердить лицензионную чистоту и зафиксировать источник; (б) хранить только индекс и цитаты; (в) перейти на официальный источник по подписке | владелец данных + юрист |
| A-20 | Экспортные Excel в `отчет/` (D-42) | Копятся бессрочно, содержат замечания, решения и ФИО. Кому принадлежит выгрузка после скачивания — не определено | (а) TTL и удаление после скачивания; (б) не хранить на сервере, отдавать потоком (как ZIP); (в) хранить как поставочный артефакт со сроком договора | STO + владелец данных |
| A-21 | Судьба «сирот» при удалении объекта и проекта (§14) | `DELETE /api/objects` не трогает файлы вовсе; `delete_project` не трогает шестнадцать позиций из §14, включая собственную резервную копию. `ADR-0014` §3 запрещает cascade delete истории по умолчанию — значит, нужно правило псевдонимизации, а его нет | (а) каскад с сохранением обезличенного audit trail; (б) псевдонимизация `object_id`/`project_id` во всех вторичных хранилищах; (в) tenant-scope и удаление по scope | владелец данных + META + STO |
| A-22 | Шесть мест хранения ответов моделей на центре (D-09, D-10, D-46, D-47, D-48 и `block_batch_NNN.json`) | Класс `llm` в `ADR-0014` один, а адресов шесть, и уборка есть только у одного. Часть создана как страховка при обрыве прогона, часть — как A/B-эвиденс; нужны ли они после закрытия версии, из кода не следует | (а) один TTL на класс и одно место хранения; (б) не хранить сырые ответы после успешного merge; (в) выносить в отдельный evidence-стор с собственным сроком (связано с `ADR-0013`) | AI + владелец данных |
| A-23 | Pre-Codex снимки в `COMPARISON_ROOT` (D-45, §12.5) | Копия findings и `audit_trail/` пишется в корень другой подсистемы. Ни один путь удаления её не видит; была ли эта раскладка намеренной, из кода не следует | (а) перенести снимки внутрь версии и удалять вместе с ней; (б) TTL; (в) отключить снимки, если A/B-контур больше не нужен | ENG + владелец данных |
| A-24 | Объявленные, но ненаполняемые пути `graph_entities.json` и `entity_links.json` (`paths.py:100-105`) | Схемы под них в дереве есть (`unified_entity_bridge/graph_entities.schema.json`, `entity_links.schema.json`, `entity_links_v2.schema.json`), продюсеров в коде нет. Неизвестно, это задел, брошенный контур или пропущенная реализация; пока не известно — неизвестно и какие данные там окажутся | (а) реализовать продюсера и завести категории данных заранее; (б) удалить пути и схемы как незавершённый задел; (в) оставить, зафиксировав как объявленный, но не действующий контракт | владелец contracts + WEB |

**Отдельно — неизвестные, а не спорные.** По этим позициям из кода не
устанавливается назначение, и любая классификация была бы догадкой:

- `critic v2 test/` (A-17) — писателя нет, происхождение содержимого неизвестно;
- `_output/_experiments/gemma_enrichment/<ts>/block_<id>.json` — читается
  (`stages/block_analysis/gemma_findings_only.py::latest_gemma_enrichment`), но
  **писателя в текущем коде нет**. Кто и когда эти файлы создаёт, из дерева не
  следует; чистки у них тоже нет;
- `_output/tiles/page_*/*.png` — считаются (`resume_detector.py:78`,
  `manager.py:4207`) и влияют на решение о возобновлении, но **писателя в
  текущем коде нет**. Тайловый путь legacy, однако его артефакты остаются
  входом логики resume;
- `_output/prompt_overrides.json` (D-51) — назначение известно (кастомный промпт
  на этап), но содержит ли текст данные заказчика, зависит от того, что туда
  ввёл оператор; из кода это не устанавливается;
- `_output/text_analysis_provider_run.json`,
  `findings_merge_provider_run.json`, `01_text_prescan.json` — диагностические
  журналы провайдерских запусков; срок и назначение после закрытия версии не
  определены;
- `logs/actions/actions-2026-08-25.jsonl` дораздельного формата (§7) — данные
  уже на диске в форме, которую текущий контракт не описывает; чистить их,
  конвертировать или оставить до истечения 180 дней, не решено;
- `projects_v2/_system/schema.json` и `migration_inventory.json` — объявлены
  стандартом, на диске отсутствуют; является ли это незавершённой миграцией или
  отказом от части стандарта, из кода не следует;
- `deliverables/sds_chat_history/` — по имени это история переписки; кто её
  участники и на каком основании она в репозитории, не установлено;
- существование `~/archives/legacy-rescue-20260710/` и
  `projects_legacy_archive_<date>` на живом сервере (§12.4) — проверяется только
  доступом к production, которого у этой задачи нет.

## 16. Пробелы матрицы ADR-0014

Матрица `ADR-0014` §3 содержит шесть классов. Шестнадцать категорий инвентаря не
попадают ни в один из них, и ещё четыре (D-16, D-21, D-44, D-45) формально
отнесены к классу, но их поведением класс не описывается. Это не упрёк
классификации: эти данные при написании ADR просто не были видны.

| Что не покрыто | Категории | Почему это отдельный класс |
| --- | --- | --- |
| Идентичность и реестры | D-04, D-28 | переживают удаление содержимого; хранят имена объектов и карты миграции |
| Учётные записи и сессии | D-29, D-30 | ПДн работников, отдельное основание и срок, отдельная процедура отзыва |
| Секреты и криптографический материал | D-31, D-35 | не «данные» в смысле retention, но требуют ротации и уничтожения |
| Состояние распределённого исполнения | D-32, D-33, D-34, D-21 | живёт вне контура центра, на чужих машинах; собственный ретеншн, выключенный по умолчанию |
| Нормативный корпус и промпты | D-36, D-37, D-38, D-39 | сторонний контент с собственным правовым режимом |
| Финансовый и ресурсный учёт | D-22, D-23 | объявлен forensic и бессрочным, но содержит идентификаторы заказчика |
| Внешняя телеметрия | D-24 | продукт читает чужие файлы вне своего хранилища |
| Входящие документы третьих лиц | D-16 | не source и не findings: это переписка, попавшая внутрь |
| Переопределения промптов | D-51 | конфигурация с потенциально пользовательским текстом внутри каталога данных |
| Резервные копии удаления и снимки | D-44, D-45 | создаются самим удалением и самим прогоном; без них матрица не работает |

Рекомендация инвентаря к `ADR-0014` (решение — за владельцем): матрица должна
покрывать не только «что мы храним», но и «где это дублируется» — иначе
retention класса `source` не имеет силы, пока существуют §12.1, §12.3 и §12.4.

## 17. Воспроизводимость

Инвентарь снят чтением следующих файлов (полные пути — от корня репозитория):

| Файл | Что дал |
| --- | --- |
| `backend/app/core/config.py` | все корневые пути, env-переопределения, флаги ретеншна и redaction |
| `backend/app/core/action_log.py` | allowlist durable-канала, лимиты diag, механизм чистки и суточного потолка |
| `backend/app/services/common/project_service.py` | семантика удаления проекта в двух режимах хранилища |
| `backend/app/services/storage/v2_primary_wiring.py` | `destructive_backups` и отсутствие auto-cleanup |
| `backend/app/services/common/usage_service.py` | 30-дневный TTL учёта и чтение `~/.claude/projects` |
| `backend/app/services/llm/paid_api_events.py` | бессрочность forensic-журналов |
| `backend/app/services/knowledge_base/knowledge_base_service.py`, `backend/app/models/expert_review.py` | поля решений и ФИО эксперта |
| `backend/app/services/external_register/{service,models}.py` | реестры заказчика и `user_confirmed_by` |
| `backend/app/services/distributed_workers/{schema,settings,job_service,project_package}.py` | 36 таблиц, каталоги центра, состав source package |
| `audit_worker/{config,local_store,local_db,retention,package_io}.py` | раскладка воркера, лизы, ретеншн и его выключенность |
| `backend/app/services/stage_comparison/paths.py` | раскладка сессий сравнения |
| `backend/app/pipeline/stages/block_analysis/stage02_paid_cache.py`, `backend/app/services/llm/claude_runner.py`, `stages/block_analysis/gemma_findings_only.py`, `stages/optimization/ensemble.py`, `stages/critic_v2_triage/runner.py` | пять мест хранения ответов моделей |
| `backend/app/pipeline/manager.py` (`_clean_stage_files`, `_backup_findings_before_restart`, `_snapshot_output_before_codex_run`, `_maybe_evict_block_crops`) | что и когда сносится, и где появляются копии |
| `backend/app/pipeline/stages/crop_blocks/{blocks.py,runner.py}`, `services/common/{block_crop_store,block_crop_lru,crop_cache}.py` | каталоги кропов, sidecar `crops_evicted.json`, LRU и вектор-кропы |
| `backend/app/pipeline/stages/block_context/builder.py` | единственная автоматическая чистка осиротевших артефактов |
| `backend/app/pipeline/stages/prepare/{process_project,graph_builder,task_builder}.py`, `services/common/version_service.py` | состав входного комплекта, `document_graph.json`, `prompt_overrides.json`, контейнеры версий |
| `backend/app/services/findings/verdict_preservation.py` | слепок вердиктов, переживающий очистку |
| `backend/app/pipeline/stages/gemma_enrichment/gemma_enrichment_contract.py` | резолвер `output_dir` для трёх раскладок |
| `.gitignore`, `.env.example`, `deploy/systemd/*.env.example` | что объявлено runtime-данными и где заданы production-пути |
| `docs/projects_v2_storage_standard.md` | нормативная раскладка версий |
| `docs/block_crop_lifecycle.md`, `docs/projects_v2_legacy_quarantine_plan.md` | эмпирика production-объёмов |
| `docs/architecture/OPS_BASELINE_V1.md` §3.6 | независимая сверка объёма версии и амплификации хранения |

Измерения повторяются скриптом (он не входит в репозиторий; текст приведён
целиком, чтобы результат можно было воспроизвести без него):

```bash
cd "$(git rev-parse --show-toplevel)"
git rev-parse --short HEAD                       # ожидается 6dc3aadf

# объёмы категорий
for p in projects projects_v2 comparison backend/app/data logs norms prompts \
         knowledge_base cache отчет; do
  if [ -e "$p" ]; then
    printf "%-22s %8s  файлов %s\n" "$p" "$(du -sh "$p"|cut -f1)" "$(find "$p" -type f|wc -l)"
  else printf "%-22s ОТСУТСТВУЕТ\n" "$p"; fi
done

# данные заказчика в истории git
git rev-list --objects --all \
 | git cat-file --batch-check='%(objecttype) %(objectname) %(objectsize) %(rest)' \
 | awk '$1=="blob"{n++;s+=$3;p=$4;
        if(p~/^projects\//){pn++;ps+=$3}
        else if(p~/^knowledge_base\//){kn++;ks+=$3}
        else if(p~/^experiments\//){en++;es+=$3}}
   END{printf "blob %d / %.1f МБ; projects/** %d / %.1f МБ; kb %d / %.1f МБ; exp %d / %.1f МБ\n",
       n,s/1048576,pn,ps/1048576,kn,ks/1048576,en,es/1048576}'

# сколько из них уже у стороннего хостера
git rev-list --objects origin/main | awk '$2 ~ /^projects\//' | wc -l   # ожидается 6886

# дублирование входного PDF: разные inode = копия, а не жёсткая ссылка
# на чистом чекауте боевых данных нет, и обе маски ниже не раскроются — это ожидаемо
stat -c '%i %h %s %n' projects_v2/objects/*/disciplines/*/documents/*/versions/*/01_input/*.pdf \
                      projects_v2/objects/*/disciplines/*/documents/*/versions/*/02_work/document.pdf

# сколько копий снапшота заказчика на диске (основное дерево + worktrees)
find "$(dirname "$(git rev-parse --show-toplevel)")" -name '73a0e59a__EOM.snapshot.json' | wc -l
```

Проверка полноты. Число категорий в §3 обязано совпадать с числом разобранных в
§4–§12; расхождение означает, что появилось хранилище, не внесённое в инвентарь.
Быстрая проверка на новые места хранения — перечень env-переменных, задающих
пути:

```bash
grep -rhoE 'os\.environ(\.get\(|\[)"[A-Z_0-9]*(DIR|ROOT|PATH|FILE|STORE|CACHE)"' \
  --include=*.py backend/ audit_worker/ norms/ scripts/ *.py \
  | grep -oE '"[A-Z_0-9]+"' | tr -d '"' | sort -u
```

На дату редакции список даёт 40 имён. Из них тестовые и смоук-скриптовые
(`AUDIT_11F_*`, `E2E_*`, `STUB_DIR`, `POLICY_PATH`, `SECRET_PATH`,
`*_FAKE_*`), системные (`PATH`, `TMPDIR`) и не-пути (`CRITIC_V2_PROFILE`)
исключаются; остальные разобраны выше.

Этот grep — эвристика, а не доказательство полноты: он не поймает имя,
не оканчивающееся на `DIR/ROOT/PATH/FILE/STORE/CACHE`. Пример из этого дерева —
`AUDIT_STAGE_COMPARISON_ROOTS` (`services/stage_comparison/store.py:2334`).
Полнота инвентаря держится на чтении кода (таблица выше), а не на этой команде.

## 18. Что этот документ не делает

- не меняет ни строки кода, ни одного файла данных и ни одной политики;
- не назначает TTL и не заполняет retention matrix — это `ADR-0014`
  (`W0-ADR-05`) и решение владельца данных;
- не даёт классификацию по уровням доступа — это `W0-SEC-02` поверх
  `W0-SEC-01`;
- не измеряет production: объёмы §2 — нижняя граница этого чекаута, baseline
  принадлежит `W0-OPS-01`;
- не объявляет условия G0 №6 и №14 выполненными: он даёт материал, на котором
  владелец может их закрыть, и явно перечисляет 21 развилку, без которых
  закрыть их нельзя;
- не заменяет `W0-DATA-02` (маппинг legacy identity → UID): здесь описано, где
  идентификаторы лежат, а не как их сводить.
