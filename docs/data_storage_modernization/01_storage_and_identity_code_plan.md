# Этап 1 — план изменений в коде волнами субагентов

> Рабочий спутник документа
> [Этап 1. Доведение `projects_v2` до единой идентичности](01_storage_and_identity_rules.md).
> Тот документ отвечает на вопрос «какие правила», этот — «какой код, в каком
> порядке и кто пишет параллельно».

**Статус:** план работ, редакция от 2026-08-27 (вторая, после переработки
дорожной карты и упразднения самостоятельного этапа внешней доставки).

**Область:** только этап 1. Подэтап 1Б (`01b`), единый файловый контур и
собственный S3 (этап 2), PostgreSQL (этап 3), индексация (этап 4) и отключение
наследия (этап 5) сюда не входят.

---

## 0. Принятые решения, влияющие на код этапа 1

Два решения закрыты **до первой записи**. Они являются частью контракта волны 0
и не могут переоткрываться отдельным агентом после появления append-only данных.

### 0.1. `finding_uid`: непрозрачный `fnd_<ULID>`

Принят непрозрачный `finding_uid` (`fnd_<ULID>`), при котором:

- `document_uid` и `version_id` — обязательные соседние поля в записи реестра,
  в самом finding и в снимке решения;
- человекочитаемая форма `<document_code>/<version_id>:U-0006` остаётся
  производным `display_ref` для отчётов и не является идентичностью;
- этап 3 получает чистый FK без парсинга строки в SQL и без дублирования ключа.

Формат задаётся ровно одной функцией `identity/ids.py:new_finding_uid()`.
Составной ID запрещён: версия определяется по явным полям и FK, а не парсингом.

### 0.2. Версия схемы manifest

Этап 1 (§8.2, Работа 7) начинает писать `run_manifest.json`, а сегмент 2.2
добавляет обязательный `blob_id`. Единое правило эволюции обоих manifest теперь
закреплено в §8.3 правил и реализуется волной 0.

Этап 1 с первой записи пишет **`schema_version: 1`** в оба manifest. Читатели
игнорируют неизвестные необязательные поля известной схемы, но отклоняют
неизвестную версию. Обязательный `blob_id` сегмента 2.2 повышает manifest до
`schema_version: 2`; переход выполняется явно, а не вслепую.

---

## 1. Что ограничивает параллелизм именно в этом репозитории

### 1.1. Одно рабочее дерево, без веток и worktree

`AGENTS.md` фиксирует: разработка идёт прямо в рабочем дереве на `main`, малыми
изолированными коммитами, без per-task веток и без per-task worktree. Этот же
checkout является источником релиза, поэтому долгоживущее грязное дерево
блокирует `scripts/production_source_guard.py`.

Из этого следуют три жёстких правила параллельной работы:

1. **Один файл — один владелец внутри волны.** Два агента одной волны никогда не
   редактируют один и тот же файл. Разделение — по файлам, а не по «темам».
2. **Коммитит только оркестратор.** Субагенты пишут изменения, но не выполняют
   `git commit`. Оркестратор после схождения волны коммитит результат каждого
   агента отдельным коммитом, добавляя только его файлы (никогда `git add -A`).
3. **Волна закрывается чистым деревом.** Следующая волна не стартует, пока
   `git status` не пуст и `python scripts/ci_regression_gate.py` не зелёный.

### 1.2. Горячие файлы, которые нельзя делить внутри волны

| Файл | Строк | Почему горячий |
| --- | --- | --- |
| `backend/app/services/storage/projects_v2_adapter.py` | 750 | `current_version_id`, `_fallback_run_dir`, `_runs_file`, `blocks_dir` — Работы 3, 7, 8 |
| `backend/app/services/storage/storage_write_facade.py` | 760 | scaffold документа, `current_version.txt`, публикация артефактов — Работы 3, 6, 7 |
| `backend/app/services/common/version_service.py` | 2748 | создание версии, указатели, v2-контекст, merge-сборка источников — Работы 3, 7 |
| `backend/app/services/common/project_service.py` | 4127 | резолв документа/версии, `register_external_project` — Работы 3, 7 |
| `backend/app/pipeline/manager.py` | 7541 | публикация run, выбор `runs/<run_id>` — Работы 6, 7 |
| `backend/app/services/knowledge_base/knowledge_base_service.py` | 1246 | хайдрейтинг, `decisions_log`, ключ `item_id` — Работы 3, 4, 5 |
| `backend/app/services/findings/findings_service.py` | 1573 | чтение/сборка findings для API — Работы 4, 6 |
| `backend/app/pipeline/stages/findings_merge/runner.py` | — | три точки перенумерации `F-NNN` — Работа 4 |
| `frontend/static/js/app.js` | 16149 | весь SPA одним файлом; параллельная правка невозможна |
| `scripts/ci_known_failures.txt` | — | baseline регресс-гейта, общий на репозиторий |

`frontend/static/js/app.js` и `scripts/ci_known_failures.txt` **всегда**
принадлежат оркестратору либо ровно одному выделенному агенту волны.

### 1.3. Поверхность, которую нельзя переписывать целиком

- `03_findings.json` упоминается в **66 файлах** `backend/app` (259 вхождений),
  из них 29 сервисов и 7 роутеров. Этап 1 **не** заводит фасад для всех
  читателей. Он закрывает только границу «завершённый run неизменяем» —
  писателей, а не читателей.
- `current_version.txt` пишут 6 мест: `version_service.py:899`,
  `version_service.py:2656`, `stage_comparison/stage_storage.py:325`,
  `scripts/projects_v2/v2lib.py:929`,
  `backend/scripts/build_vector_graph_gallery.py:903`,
  `scripts/projects_v2/migrate_legacy_findings_preserve.py:343`
  (+ упаковка в пакет воркера `distributed_workers/project_package.py:632`).

### 1.4. Что этап 1 не делает и что нужно проверить до старта

Этап 1 не переключает production и не трогает флаги записи. Но перед волной 1
нужно подтвердить фактический режим: в этом checkout `.env` содержит
`AUDIT_PROJECTS_V2_WRITE_MODE=projects_v2_primary` и
`AUDIT_PROJECTS_V2_READ_DEFAULT_ENABLED=true`, тогда как `01b` описывает
production как `dual_write_shadow`. Baseline обязан зафиксировать реальные
значения боевого контура, иначе все измерения окажутся про другой контур.

### 1.5. Что уже есть в коде и не переписывается

| Уже в коде | Где | Как используется этапом 1 |
| --- | --- | --- |
| Фингерпринт замечания по дрейф-устойчивым якорям | `findings/verdict_preservation.py:151` `build_fingerprint` | база для `finding_uid`, а не новый алгоритм |
| Двухфазный матч exact → fuzzy | `verdict_preservation.py:184` `match_snapshot_to_items` | база трекинга UID |
| Fuzzy-дедуп | `findings/dedup/fuzzy_dedup.py` | кандидаты для fuzzy-ветки трекинга |
| Кросс-версионные связи | `findings/migrated_findings_service.py` (`origin_finding_id`, `_stable_migrated_id`, `linked_finding_id`) | отдельная ось, UID её не заменяет |
| Перенос вердиктов между версиями | `findings/decision_carryover_service.py` | потребитель `finding_uid`, не конкурент |
| Фасады чтения/записи | `storage/storage_read_facade.py`, `storage_write_facade.py` | точки внедрения новых правил |

---

## 2. Карта: Работа документа → волна

| Работа этапа 1 | Волна | Агенты |
| --- | --- | --- |
| 2. Реестр идентификаторов (схема) | 0 | W0 |
| 1. Повторный read-only-аудит | 1 | W1-1 |
| 3. `document_uid` — карта (dry-run) | 1 | W1-2 |
| 7. Классификация `run_id` (наблюдение) | 1 | W1-3 |
| 5. Орфаны решений (наблюдение) | 1 | W1-4 |
| 9. Каркас identity/integrity-отчёта | 1 | W1-5 |
| Вход в 1Б: реестр версий без manifest | 1 | W1-6 |
| 3. `document_uid` — запись | 2 | W2-1 |
| 4. `finding_uid` — теневой режим | 2 | W2-2 |
| 6. Слой ручной проверки (писатели) | 2 | W2-3 |
| 7. Канонические указатели | 3 | W3-1 |
| 7 + 8.2. Модель run, manifest и неизменяемость | 3 | W3-2 |
| 5. Самодостаточные решения | 3 | W3-3 |
| 6. Слияние в API | 3 | W3-4 |
| 3 + 4. Переключение потребителей | 4 | W4-1…W4-5 |
| 5. Бэкфилл исторических решений | 4 | W4-6 |
| 9. Полный набор проверок + CI | 5 | W5-1 |
| Фаза E. Строгие ограничения | 5 | W5-2 |
| UI: `ordinal` vs UID | 5 | W5-3 |
| 2. Документация разработчика | 5 | W5-4 |

---

## 3. Волна 0 — фундамент (последовательно, 1 агент)

Эта волна **не параллелится**. Всё, что делают следующие волны, импортирует её
результат; параллельная работа здесь означала бы согласование контракта на лету.

### W0. Пакет идентичности и контракты

**Владение:** только новые файлы.

```
backend/app/services/identity/__init__.py
backend/app/services/identity/ids.py
backend/app/services/identity/registry.py
backend/app/services/identity/provenance.py
backend/app/services/identity/manifest_schema.py
backend/app/services/identity/flags.py
backend/app/services/identity/errors.py
contracts/identity/v1/identity_registry.json
contracts/identity/v1/README.md
backend/tests/fixtures/identity/__init__.py
backend/tests/fixtures/identity/build_tree.py
backend/tests/test_identity_ids.py
backend/tests/test_identity_registry_contract.py
backend/tests/test_manifest_schema_contract.py
```

**`ids.py`** — генерация и валидация, без ввода-вывода:

```python
def new_document_uid() -> str                     # непрозрачный, не производный от пути
def new_finding_uid() -> str                      # непрозрачный; см. §0.1
def finding_display_ref(document_code, version_id, seq) -> str   # только отображение
def new_import_id() -> str
def new_decision_id() -> str
def classify_run_id(run_id: str) -> RunIdKind     # live | migration | refresh | legacy_preserve | unknown
def normalize_version_id(value: str) -> str       # vNNN
def legacy_document_key(object_id, discipline_code, document_code) -> str
```

Инварианты, закреплённые тестами: UID не выводится из пути и не пересчитывается
при чтении; `parse_*` отвергает форму, которую `new_*` не мог породить;
`finding_display_ref` нигде не используется как ключ.

**Именование run.** `run_id` — единственное каноническое имя в новых JSON, API,
каталоге `03_analysis/runs/<run_id>` и PostgreSQL. Существующее поле
`version.json.analysis_run_id` читается и сверяется как legacy-алиас на период
миграции, но не является вторым полем нового контракта.

**`provenance.py`** — реализация единственной формы записи происхождения из
§6.5 правил. `IngestBundle` использует тип `ProvenanceRecord`, а
`input_manifest.json` хранит его один раз на уровне комплекта. Файловые записи
не создают альтернативный вложенный `source`. Секретный ключ и подписанный URL
в структуру не попадают — это проверяется тестом.

**`manifest_schema.py`** — `schema_version = 1`, валидатор обязательных полей
`input_manifest.json` и `run_manifest.json`, правило «неизвестные необязательные
поля известной схемы игнорируются; неизвестная версия отклоняется». См. §0.2.

**`registry.py` + `contracts/identity/v1/identity_registry.json`** — раздел 5
правил в машиночитаемом виде. Для каждой из 15 сущностей: область уникальности,
формат (regex), место создания, запрет переиспользования, поля-алиасы. Алиас
документа описывается как **список**, а не одно поле: документ мог
переименовываться несколько раз, и этап 3 §6.2 заводит под это таблицу
`document_aliases`.

**`flags.py`** — по одному флагу отката на подсистему, все по умолчанию
выключены (§11). Значения читаются на каждый вызов — как в уже работающем
`verdict_preservation.is_enabled()`.

**`errors.py`** — `PointerMismatchError`, `AmbiguousIdentityError`,
`ImmutableRunViolation`, `ManifestMissingError`. Нужны заранее: волны 3 и 5
требуют диагностируемой ошибки вместо молчаливого выбора.

**Фикстуры** — `build_tree.py` собирает синтетическое дерево `projects_v2`
(2 объекта × 2 дисциплины × 2 документа × 2 версии × 2 run, из них одна версия
без manifest) во временном каталоге. Все последующие агенты тестируются против
него, а не против реальных данных. Это снимает главный источник конфликтов в
`tests/`.

**Гейт волны 0:** решения §0.1 и §0.2 закреплены тестами; тесты
идентичности зелёные; `contracts/identity/v1/` закоммичен; ни один
production-путь ещё не импортирует новый пакет.

---

## 4. Волна 1 — только наблюдение (Фаза A)

Шесть агентов, все создают **только новые файлы** — конфликтов нет по построению.
Ни один агент этой волны не меняет поведение приложения и не имеет флага
`--execute`.

### W1-1. Baseline-аудит (Работа 1)

**Файлы:** `scripts/projects_v2/audit_identity_baseline.py`,
`tests/test_audit_identity_baseline.py`.

Read-only обход корня данных. Отчёт JSON + Markdown фиксирует дату, корень
данных, фактические значения `AUDIT_PROJECTS_V2_WRITE_MODE` и
`AUDIT_PROJECTS_V2_READ_DEFAULT_ENABLED`, количество объектов, дисциплин,
документов, версий, run, findings, решений, сессий сравнения и записей
`workers.db`.

Отдельными счётчиками — семь пунктов Работы 1: расхождения двух указателей
версии; результаты без известного run; таксономия форматов `run_id`; решения без
найденного исходного замечания; документы, определённые только путём или
`document_code`; изменения завершённого run после первой записи; внешние
crop-ссылки как единственная копия.

### W1-2. Карта `document_uid` без записи (Работа 3, шаг 1)

**Файлы:** `scripts/projects_v2/plan_document_uid.py`,
`tests/test_plan_document_uid.py`.

Таблица `object_id + discipline_code + document_code → document_uid` и карта
влияния: какие записи `knowledge_base/decisions_log.json`, обсуждений,
`external_register`, сравнений и заданий ссылаются на каждый документ. Выход —
`document_uid_plan.json` в отдельном каталоге отчётов, **вне мигрируемого
дерева**, со статусами `ok | ambiguous | conflict`.

`conflict` — один `document_code` в одной дисциплине объекта. `ambiguous` —
legacy-ссылка, разрешающаяся более чем в один документ. Оба статуса блокируют
волну 2 для затронутых документов: UID им не присваивается автоматически.

Отдельная секция отчёта — **все известные алиасы каждого документа** (прежние
имена папок, legacy `obj_<id>`, переименования), в форме списка. Из неё этап 3
строит `document_aliases`.

### W1-3. Таксономия `run_id` (Работа 7, наблюдение)

**Файлы:** `scripts/projects_v2/scan_run_id_taxonomy.py`,
`tests/test_scan_run_id_taxonomy.py`.

Классифицирует все каталоги `03_analysis/runs/<run_id>` через
`identity.ids.classify_run_id`. Отдельно отмечает: run без указывающего на него
`run_id`; `run_id`, указывающий в пустоту; версии, где `latest`
не совпадает по составу ни с одним run; complete-run без `run_manifest.json`.
Каталоги **не переименовываются**.

### W1-4. Орфаны решений (Работа 5, наблюдение)

**Файлы:** `scripts/projects_v2/scan_decision_orphans.py`,
`tests/test_scan_decision_orphans.py`.

Повторяет измерение «447 из 6440» на текущих данных. Для каждого решения ищет
исходный finding **с учётом версии**, а не через `latest`; разница между
«нашлось по версии» и «нашлось по latest» — это ровно масштаб корневого бага.
Классификация орфанов: нет версии; версия есть, но `F-NNN` отсутствует; `F-NNN`
есть, но текст разошёлся; несколько кандидатов. Результат калибрует порог fuzzy
в волне 2.

### W1-5. Каркас identity/integrity-отчёта (Работа 9)

**Файлы:** `scripts/projects_v2/check_identity_integrity.py`,
`backend/app/services/identity/checks.py`,
`tests/test_check_identity_integrity.py`.

Каркас с уровнями `critical | error | warning | info` и реестром правил. В волне
1 включены только исполнимые до появления UID: дубли `document_code` в
дисциплине, версия без документа, расхождение двух указателей, указатель на
отсутствующую версию, `run_id` в пустоту, сравнение по путям,
block-ссылка без поколения, код в обход фасадов.

Одновременно включаются manifest-проверки §13 правил и подэтапа 1Б (§10.5):

- версия без `input_manifest.json`;
- current указывает на версию без manifest;
- complete-run без `run_manifest.json`.

Остальные правила регистрируются со статусом `not_applicable_yet` — волна 5 их
только включает, а не изобретает.

### W1-6. Реестр версий без manifest (вход в подэтап 1Б)

**Файлы:** `scripts/projects_v2/scan_versions_without_manifest.py`,
`tests/test_scan_versions_without_manifest.py`.

Подэтап 1Б (§6.1) требует отдельного read-only аудита существующих версий без
`input_manifest.json` и фиксирует ориентир аудита 2026-08-07: 527 manifest на
559 версий, то есть около 32 версий без manifest. Этот агент повторяет замер на
текущих данных и классифицирует каждую дыру:

- состав и происхождение восстанавливаются однозначно → кандидат на repair;
- восстановление неоднозначно → `manual_unresolved`, владелец решения;
- версия является current → **critical**, потому что 1Б запрещает current без
  manifest.

Отдельно проверяется, что `project_info.json.pdf_sha256` и `bundle_fingerprint`
не расходятся с фактическими файлами: после подключения общего writer manifest
станет главным носителем состава, а эти поля — проверяемым зеркалом.

Агент ничего не чинит. Сам repair и подключение общего manifest writer к
`POST /api/projects/register-external` — работа подэтапа 1Б, разблокированная
волной 2 (см. §8).

**Гейт волны 1:** шесть отчётов сняты на реальных данных; `document_uid_plan.json`
без `conflict` либо конфликты имеют владельца и решение; таксономия `run_id`
покрывает 100% каталогов; счётчик версий без manifest зафиксирован как база
сравнения для 1Б; проверка целостности проходит на фикстурах.

---

## 5. Волна 2 — аддитивная запись ядра (Фаза B)

Три агента, разведённые по трём непересекающимся поддеревьям кода: storage,
pipeline findings, внешняя регистрация. Каждый пишет новые поля **рядом** со
старыми; ни один существующий ответ API не меняется.

### W2-1. `document_uid` в хранилище (Работа 3, шаги 2–4)

**Владение:**
`backend/app/services/identity/document_uid_store.py` (новый),
`backend/app/services/storage/projects_v2_adapter.py`,
`backend/app/services/storage/storage_write_facade.py`,
`scripts/projects_v2/v2lib.py`,
`tests/test_document_uid_store.py`, `tests/test_v2_document_uid_write.py`.

- `document_uid_store.py` — единственное место присвоения и чтения UID:
  `ensure_document_uid(doc_dir)` (идемпотентно, генерация один раз),
  `resolve_by_uid(uid)`, `resolve_by_legacy_key(...)`, `alias_table()`.
- `storage_write_facade._ensure_document_scaffold` при создании документа сразу
  пишет `document.json.document_uid` и `document.json.aliases` — **список**
  записей `{kind, value, valid_from, valid_to}`, а не одно поле. При каждом
  переименовании прежнее значение остаётся в истории.
- В `ProjectsV2Adapter` добавляются `document_uid(doc_dir)` и
  `find_document_by_uid(uid)`. Существующий трёхступенчатый резолв поведения не
  меняет, но логирует, каким путём разрешился документ (читаемое имя,
  `object_id`, legacy `obj_<id>`) — требование §6.1 правил.
- Бэкфилл — команда `v2lib.py backfill-document-uid` строго по утверждённому
  `document_uid_plan.json`. `ambiguous` и `conflict` пропускаются и попадают в
  отчёт.

Чего **не** делает: не переименовывает каталоги, не меняет ни одного API-ответа,
не трогает потребителей UID.

### W2-2. `finding_uid` в теневом режиме (Работа 4)

**Владение:**
`backend/app/services/identity/finding_identity.py` (новый),
`backend/app/pipeline/stages/findings_merge/runner.py`,
`backend/app/services/findings/dedup/fuzzy_dedup.py`,
`tests/test_finding_identity_registry.py`,
`tests/test_findings_merge_uid_shadow.py`.

- `finding_identity.py` — append-only реестр `finding_identity.json` рядом с
  версией: `fp_algo`, `entries[]` с `finding_uid`, `document_uid`,
  `version_id`, `display_ref`, `fingerprint`, `fingerprints[]`,
  `first_seen_run`, `last_seen_run`, `alive`, `anchors`. UID непрозрачен (§0.1);
  принадлежность версии выражается полями, а не разбором строки.
- Фингерпринт **переиспользует** `verdict_preservation.build_fingerprint`,
  дополняя его `document_uid` и `version_id`. Новый алгоритм не пишется.
- Трекинг exact → fuzzy → mint; fuzzy опирается на существующий `fuzzy_dedup`.
  При двух равных кандидатах UID не переиспользуется: минтуется новый и случай
  уходит в `finding_identity_report.json`. Это правило «система не угадывает».
- В `findings_merge/runner.py` три места перенумерации (`:283`, `:380–391`,
  `:476–482`) остаются, но после финальной перенумерации добавляется
  `ordinal = item["id"]` и `item["finding_uid"]`. `F-NNN` продолжает жить в поле `id` —
  ни один из 66 читателей не ломается.
- **Теневой режим:** при `IDENTITY_FINDING_UID_MODE=shadow` (по умолчанию)
  реестр ведётся и отчёт пишется, но привязки решений не меняются.

Порог fuzzy калибруется на реальных парах повторных аудитов из отчёта W1-4 —
отдельный подшаг с числом в отчёте, а не константа «на глаз».

### W2-3. Слой ручной проверки — писатели (Работа 6, первая половина)

**Владение:**
`backend/app/services/findings/review_layer.py` (новый),
`backend/app/services/external_register/apply_verdicts.py`,
`backend/app/services/external_register/service.py`,
`tests/test_review_layer_writes.py`,
`tests/test_external_register_run_immutability.py`.

- `review_layer.py` — артефакт `04_review/manual_review.json`: вердикты
  заказчика и созданные человеком `REG-*` с собственными UID, ключуемые на
  `finding_uid`.
- `apply_verdicts.py` перестаёт мутировать `03_findings.json` и создавать `.bak`
  (`apply_verdicts.py:317–331`). То же для
  `service._write_finding_external_register` и `_clear_finding_external_register`
  (`service.py:301–396`).
- Ключевой тест: полный сценарий регистрации, SHA-256 всех файлов завершённого
  run до и после — ни один байт не изменился. Критерий завершения №9.

Поведение старого API сохраняется через флаг: пока
`IDENTITY_REVIEW_LAYER_READS=0`, ответ не меняется — слияние появится в W3-4.

**Гейт волны 2:** три агента сошлись без пересечений по файлам; UID пишутся, но
никем не читаются; тест неизменяемости run зелёный; в проверке целостности
включены правила «finding без `finding_uid`» и «повторное использование UID».

---

## 6. Волна 3 — указатели, модель run, самодостаточные решения

Четыре агента. Одна внутриволновая зависимость: **W3-2 стартует после коммита
W3-1**, потому что оба логически касаются адаптера. Владеет файлом W3-1; W3-2
работает поверх его интерфейса.

### W3-1. Канонические указатели (Работа 7, первая половина)

**Владение:**
`backend/app/services/identity/pointers.py` (новый),
`backend/app/services/storage/projects_v2_adapter.py`,
`backend/app/services/common/version_service.py`,
`scripts/projects_v2/repair_version_pointers.py` (новый),
`tests/test_version_pointer_canonical.py`.

- `pointers.write_current_version(doc_dir, vid)` — одна операция, атомарно
  обновляющая `current_version.txt` и зеркало `document.json.current_version` с
  немедленной проверкой равенства. Все шесть писателей (§1.3) переводятся на неё;
  правки в чужих файлах (`stage_storage.py`, `v2lib.py`,
  `build_vector_graph_gallery.py`) выполняет **оркестратор** одним коммитом после
  волны.
- `ProjectsV2Adapter.current_version_id` (`:220`) перестаёт молча возвращать
  `versions[-1]`: при расхождении — `PointerMismatchError`.
- Указатель не переключается на версию без `input_manifest.json` —
  `ManifestMissingError`. Это инвариант подэтапа 1Б §10.5, и закрыть его должен
  этап 1, потому что именно он владеет операцией записи указателя.
- `repair_version_pointers.py` — dry-run по умолчанию, восстанавливает зеркало из
  канонического файла.

Риск, снимаемый здесь же: `distributed_workers/project_package.py:632` кладёт
`current_version.txt` в пакет воркера, а `result_import.py:56` считает его
метаданным. Тест подтверждает, что импорт результата не переоткрывает указатель
мимо `pointers.write_current_version`.

### W3-2. Модель run, manifest и неизменяемость (Работы 7, 8.2)

**Владение:**
`backend/app/services/identity/runs.py` (новый),
`backend/app/pipeline/manager.py`,
`backend/app/services/storage/v2_primary_wiring.py`,
`tests/test_run_manifest_immutability.py`,
`tests/test_run_index_contract.py`.

- `runs.py` — контракт `job_id → attempt_id → run_id` и состояния
  `running | complete | failed | cancelled`. Для нового живого аудита
  `run_id = job_id`, если задание опубликовало ровно один набор;
  повторная попытка с другим набором обязана получить новый ID.
- При публикации run пишется `run_manifest.json` с `schema_version: 1`
  (§0.2), списком артефактов, размерами, SHA-256, `job_id`, `attempt_id`,
  временем и ссылкой `input_import_id` на канонический provenance входа. После
  публикации run получает `complete`, и любая
  последующая запись в его каталог — `ImmutableRunViolation`.
- `version.json.run_id` переводится на новый run только после успешного
  завершения.
- Индекс исторических run — `03_analysis/runs_index.json`: тип, время,
  `input_import_id`, связь с версией. Каталоги не переименовываются.
- `latest` строится атомарно: новое представление собирается рядом и заменяется
  одним переключением. Тест: удалить `latest` в копии дерева и полностью
  восстановить из выбранного run (критерий №10).
- `_fallback_run_dir` и `_runs_file` (`:325`, `:334`) выбирают run по
  `max(mtime)`. Остаются как явный legacy-путь под флагом
  `IDENTITY_ALLOW_RUN_MTIME_FALLBACK=1`, логируют warning и попадают в отчёт
  целостности. Выключаются в волне 5.

### W3-3. Самодостаточные экспертные решения (Работа 5)

**Владение:**
`backend/app/models/expert_review.py`,
`backend/app/services/knowledge_base/knowledge_base_service.py`,
`tests/test_decision_snapshot_selfsufficient.py`.

При создании решения сохраняется полный снимок §6.9 правил: `decision_id`,
`document_uid`, `version_id`, `finding_uid` + текущий `ordinal`, суть, категория,
критичность, страница/лист/блоки, нормативные ссылки, решение, автор, дата,
`run_id`.

Наличие `document_uid` и `version_id` в снимке — это и есть выполнение требования
R4 из `stable_finding_id.md` без составного UID (§0.1).

Хайдрейтинг (`knowledge_base_service.py:442–455`, `_load_source_item_maps` около
`:353`) остаётся, но переходит в роль дополнительного отображения: обязательные
поля берутся из снимка, а не восстанавливаются из `latest`. Тест: удалить
`latest`, подменить `03_findings.json` — решение всё равно отображается полностью.

Исправление решения создаёт новую редакцию; предыдущая остаётся в истории
(§8.6 правил). Удаление в UI = отзыв, не физическое исчезновение.

### W3-4. Слияние результата и ручной проверки в API (Работа 6, вторая половина)

**Владение:**
`backend/app/services/findings/findings_service.py`,
`backend/app/api/routers/findings.py`,
`backend/app/api/routers/external_register.py`,
`tests/test_findings_api_review_merge.py`.

API объединяет неизменяемый `03_findings.json` выбранного run и слой
`manual_review.json`. Пользователь видит итоговую картину — вердикты заказчика и
`REG-*`, — но исходный результат run воспроизводим. Флаг
`IDENTITY_REVIEW_LAYER_READS` переводится в `1` здесь.

Проверка эквивалентности: на данных, где `apply_verdicts` уже отработал по старой
схеме, результат слияния должен совпадать с текущим ответом API. Разница — в
отчёт, а не в тихое расхождение.

**Гейт волны 3:** расхождений двух указателей — 0 (критерий №4); каждый актуальный
run существует и завершён (№5); `latest` восстанавливается из run (№10); ни один
current не указывает на версию без manifest; тест самодостаточности решений
зелёный; ответ API до и после слияния эквивалентен на контрольной выборке.

---

## 7. Волна 4 — теневое чтение и переключение потребителей (Фазы C и D)

Шесть агентов, разведённых по подсистемам-потребителям. У каждой подсистемы свой
флаг отката. Порядок внутри волны свободный — файлы не пересекаются.

### W4-1. База знаний

**Владение:** `backend/app/services/knowledge_base/knowledge_base_service.py`,
`backend/app/api/routers/knowledge_base.py`, `tests/test_kb_uid_keys.py`.

Ключ решения — `(source_project, finding_uid)` вместо `(source_project, item_id)`.
`decisions_log` пишет оба ключа; чтение сперва по UID, затем по `F-NNN` как
алиасу, и каждое срабатывание алиаса считается. Хайдрейтинг резолвит источник по
`version_id` из снимка решения, а не по `latest` — это устраняет корневой баг
эталонного кейса DEC-5453.

### W4-2. Обсуждения

**Владение:** `backend/app/services/discussions/discussion_service.py`,
`backend/app/api/routers/discussions.py`, `tests/test_discussions_uid_keys.py`.

`_discussion_path` (`:90`) формирует имя файла из `item_id`. Новые обсуждения
адресуются по UID; старые файлы `F-NNN.json` читаются через таблицу алиасов и не
переименовываются.

### W4-3. Внешняя регистрация

**Владение:** `backend/app/services/external_register/matcher.py`, `models.py`,
`parser.py`, `section_map.py`, `tests/test_external_register_uid.py`.

Записи реестра ссылаются на `document_uid + version_id + finding_uid`. `REG-*` из
волны 2 получают собственные постоянные UID.

### W4-4. Сравнения (Работа 8, первая половина)

**Владение:** `backend/app/services/stage_comparison/*`,
`backend/app/api/routers/stage_comparison.py`,
`tests/test_comparison_version_refs.py`.

`session_id` и `pair_id` сохраняются. Каждая сторона пары получает
`document_uid + version_id`; путь к PDF остаётся адресом чтения, а не
идентичностью. Здесь же `stage_storage.py:320,365` перестаёт читать и писать
`document.json.current_version` напрямую и переходит на `identity.pointers`.

### W4-5. Страницы и блоки (Работа 8, вторая половина)

**Владение:** `backend/app/services/identity/block_refs.py` (новый),
`backend/app/pipeline/stages/crop_blocks/blocks.py`,
`backend/app/services/findings/block_captions.py`,
`tests/test_block_ref_generation.py`.

Ссылка на страницу — `pdf_page` внутри версии; `sheet` из штампа остаётся
подписью и никогда не ключом. Ссылка на блок включает версию **и поколение**
`_blocks.json`, чтобы новый ingest сегмента 2.1 не подменял геометрию старого
результата. Затрагивает `blocks_dir` / `resolved_blocks_dirs` в адаптере
(`:376`, `:416`) — их правит оркестратор после волны.

### W4-6. Бэкфилл исторических решений (Работа 5, вторая половина)

**Владение:** `scripts/backfill_decision_snapshots.py` (новый),
`tests/test_backfill_decision_snapshots.py`.

Dry-run по умолчанию. Для каждого старого решения подбирает версию по сохранённым
данным и дате; при однозначном ответе заполняет снимок, при неоднозначном ставит
`manual_unresolved` с причиной и **не** прикрепляет решение к похожему замечанию.
Автоматически угаданных связей — ноль (критерий №8).

**Этот агент не является входом в подэтап 1Б** (см. §8) — он может завершаться
после cutover.

**Гейт волны 4:** по каждой подсистеме снят отчёт теневого чтения с точными ID;
покрытие UID измерено по каждому семейству ссылок; ни одна подсистема не
переключена без своего флага; счётчик срабатываний legacy-алиасов ведётся и виден.

---

## 8. Что этап 1 разблокирует для подэтапа 1Б и сегмента 2.1

Подэтап 1Б (§5) задаёт storage-facing минимум Работ 3, 6, 7 и 9. Он покрывается
волнами 0–3, но **не требует завершения всего этапа 1**. Бэкфилл 6440
исторических решений (W4-6), переключение остальных finding-потребителей,
правка SPA (W5-3) и строгий режим Фазы E (W5-2) продолжаются параллельно и не
блокируют файловый cutover.

| Предусловие 1Б (§5) | Закрывает |
| --- | --- |
| постоянная идентичность документа и версии | W2-1 |
| единая функция обновления канонического current и зеркала | W3-1 |
| запрет изменения завершённого run | W2-3 + W3-2 |
| связь `job_id → attempt_id → run_id` | W3-2 |
| известная версия схемы manifest; current/complete только с manifest | W0 + W3-1 + W3-2 |
| отчёт целостности без необъяснённых critical/error | W1-5 + гейты волн 2–3 |
| карта legacy → v2 без неоднозначных документов | W1-2 |

Дополнительно 1Б §6.1 требует, чтобы merge создавал у target-версии новый
`input_manifest.json` с полем `derived_from_version.source_document_uid`. Этот
writer — работа 1Б, а не этапа 1, но он **не может быть написан раньше W2-1**,
потому что `document_uid` появляется именно там. То же для подключения общего
manifest writer к `POST /api/projects/register-external`
(`project_service.register_external_project`) — седьмой блокер 1Б.

Для сегмента 2.1 этап 1 передаёт три стабильных контракта:
`identity.provenance` (канонический `ProvenanceRecord`, который передаёт
`IngestBundle`), `schema_version` и правило «версия публикуется только
после полного manifest». Разработка 2.1 может идти параллельно волнам 1–3, но её
production-публикация ждёт 1Б.

---

## 9. Волна 5 — строгие ограничения, целостность, UI, документация

Четыре агента. `app.js` наконец получает единственного владельца.

### W5-1. Полный отчёт целостности и CI (Работа 9)

**Владение:** `scripts/projects_v2/check_identity_integrity.py`,
`backend/app/services/identity/checks.py`, `.github/workflows/*` (identity-job),
`tests/test_identity_integrity_full.py`.

Включаются все правила §13, включая manifest-проверки волны 1. Режимы: в
CI — на фикстурах при каждом релизе; по расписанию — read-only по рабочим данным;
полный пересчёт SHA-256 больших файлов — отдельный режим `--deep`.

Правило «новый код обходит фасады хранения» — статическая проверка: запись в
`projects_v2/**` мимо `storage_write_facade` и `identity.pointers` вне
разрешённого списка модулей.

### W5-2. Строгие ограничения (Фаза E)

**Владение:** `backend/app/services/identity/flags.py`,
`document_uid_store.py`, `finding_identity.py`,
`tests/test_identity_strict_mode.py`.

После подтверждённого 100% покрытия: новая запись без обязательного UID
отклоняется; `IDENTITY_ALLOW_RUN_MTIME_FALLBACK` выключается по умолчанию;
`IDENTITY_FINDING_UID_MODE` переводится в `enforce`. Старые алиасы остаются
только для чтения исторических ссылок. Физическое удаление старых полей на этапе
1 **не выполняется** (§17 правил).

### W5-3. Интерфейс: `ordinal` против UID

**Владение:** `frontend/static/js/app.js`, `frontend/tests/*`.

Единственный агент, касающийся SPA. Пользователь продолжает видеть `F-001`,
`F-002` — `ordinal` остаётся отображаемым номером. UID уходит в deeplink, в тело
запроса решения и в обсуждение. Отдельно — честное поведение при неоднозначности:
карточка просит проверить связь, а не показывает угаданную (§15 правил).

### W5-4. Документация разработчика (Работа 2)

**Владение:** `CLAUDE.md`, `docs/project_structure.md`,
`docs/projects_v2_storage_standard.md`, `docs/stable_finding_id.md`.

`CLAUDE.md` описывает `projects/<КОД>/<имя>/_output/` как основную структуру
приложения (строки 16 и 21, инструкция на строке 214) — это прямо противоречит
критерию завершения №14. Раздел переписывается на `projects_v2`, legacy-раскладка
уходит в подраздел «историческая структура, новый код туда не пишет».

`stable_finding_id.md` получает статус «реализовано в
`backend/app/services/identity/finding_identity.py`» и **правку §6**: ключ решения
— непрозрачный `finding_uid` плюс явные `document_uid`/`version_id`, а не разбор
составной строки (§0.1).

Граница Storage/source adapters уже зафиксирована принятым ADR и правилами
этапов 1–2. Агент лишь проверяет, что
документация не возвращает упразднённый самостоятельный этап внешней доставки.

**Гейт волны 5 = завершение этапа 1:** проверка целостности проходит без
`critical`/`error` либо имеет утверждённый список исключений с владельцем и
сроком (№12); manifest-инварианты выполнены (№13); документация не направляет
новый код в legacy (№14).

---

## 10. Карта владения файлами по волнам

| Файл | В0 | В1 | В2 | В3 | В4 | В5 |
| --- | --- | --- | --- | --- | --- | --- |
| `services/identity/*` | W0 | W1-5 (checks) | W2-1/W2-2 | W3-1/W3-2 | W4-5 | W5-2 |
| `storage/projects_v2_adapter.py` | — | — | W2-1 | W3-1 | оркестратор | — |
| `storage/storage_write_facade.py` | — | — | W2-1 | — | — | — |
| `common/version_service.py` | — | — | — | W3-1 | — | — |
| `pipeline/manager.py` | — | — | — | W3-2 | — | — |
| `stages/findings_merge/runner.py` | — | — | W2-2 | — | — | — |
| `findings/findings_service.py` | — | — | — | W3-4 | — | — |
| `findings/review_layer.py` | — | — | W2-3 | — | — | — |
| `knowledge_base/knowledge_base_service.py` | — | — | — | W3-3 | W4-1 | — |
| `external_register/*` | — | — | W2-3 | — | W4-3 | — |
| `discussions/*` | — | — | — | — | W4-2 | — |
| `stage_comparison/*` | — | — | — | — | W4-4 | — |
| `scripts/projects_v2/*` | — | W1-1…W1-6 | W2-1 (v2lib) | W3-1 (repair) | — | W5-1 |
| `frontend/static/js/app.js` | — | — | — | — | — | W5-3 |
| `CLAUDE.md`, `docs/*` | — | — | — | — | — | W5-4 |
| `scripts/ci_known_failures.txt` | оркестратор | оркестратор | оркестратор | оркестратор | оркестратор | оркестратор |

Клетки «оркестратор» — правки в файле, которым в этой волне владел другой агент,
или общий ресурс. Выполняются между волнами отдельным коммитом.

---

## 11. Контракты, которые волна 0 фиксирует один раз

**`document.json` (аддитивно):**

```jsonc
{
  "document_uid": "doc_01J...",
  "aliases": [
    {"kind": "legacy_compound_key", "value": "<object_id>+<discipline_code>+<document_code>",
     "valid_from": null, "valid_to": "2026-08-27T00:00:00Z"}
  ],
  "current_version": "v002"
}
```

**`finding_identity.json`** — формат `stable_finding_id.md` §5 с непрозрачным
`finding_uid` и явными `document_uid` / `version_id` / `display_ref` (§0.1).

**`run_manifest.json`:**

```jsonc
{
  "schema_version": 1,
  "run_id": "run_01J...",
  "job_id": "...", "attempt_id": "...",
  "input_import_id": "imp_01J...",
  "state": "complete", "run_kind": "live",
  "published_at": "...",
  "artifacts": [{"name": "03_findings.json", "size": 12345, "sha256": "..."}]
}
```

**`input_manifest.json`** — сохраняет `schema_version: 1`; поле
`derived_from_version` подэтапа 1Б добавляется аддитивно в ту же схему 1.

**`manual_review.json`** — вердикты заказчика и `REG-*` с UID, ключ на
`finding_uid`.

**Снимок решения** — 12 полей §6.9 правил.

**Запись происхождения** — канонический тип §6.5 правил в `identity/provenance.py`.
`IngestBundle` передаёт готовый `ProvenanceRecord`, а input manifest хранит его
один раз на уровне комплекта. Секреты и подписанные URL в него не попадают.

---

## 12. Флаги отката

| Флаг | По умолчанию | Что закрывает | Снимается |
| --- | --- | --- | --- |
| `IDENTITY_DOCUMENT_UID_WRITES` | `0` → `1` в В2 | запись `document_uid` | — |
| `IDENTITY_DOCUMENT_UID_READS` | `0` | резолв по UID | В4, по подсистемам |
| `IDENTITY_FINDING_UID_MODE` | `shadow` | трекинг UID без изменения привязок | `enforce` в В5 |
| `IDENTITY_REVIEW_LAYER_WRITES` | `0` → `1` в В2 | вердикты в отдельный артефакт | — |
| `IDENTITY_REVIEW_LAYER_READS` | `0` → `1` в В3 | слияние в API | — |
| `IDENTITY_STRICT_POINTERS` | `0` → `1` в В3 | ошибка вместо молчаливого max | — |
| `IDENTITY_REQUIRE_MANIFEST_FOR_CURRENT` | `0` → `1` в В3 | current только на версию с manifest | — |
| `IDENTITY_ALLOW_RUN_MTIME_FALLBACK` | `1` | legacy-выбор run по mtime | `0` в В5 |
| `IDENTITY_KB_UID_KEYS` | `0` | база знаний на UID | В4 |
| `IDENTITY_DISCUSSIONS_UID_KEYS` | `0` | обсуждения на UID | В4 |
| `IDENTITY_EXTREG_UID_KEYS` | `0` | внешняя регистрация на UID | В4 |
| `IDENTITY_COMPARISON_UID_REFS` | `0` | сравнения на UID | В4 |

Каждый флаг регистрируется в `scripts/audit_env_flags.py`, иначе он не виден
эксплуатации. Ни один агент не меняет `AUDIT_PROJECTS_V2_WRITE_MODE` — это
подэтап 1Б.

---

## 13. Тесты при параллельной работе

- Два корня: `pytest.ini` → `testpaths = tests backend/tests`.
- **Один агент — свои файлы тестов.** Дописывать в чужой существующий тест-файл
  внутри волны запрещено.
- Все тесты волн 1–5 идут против фикстуры
  `backend/tests/fixtures/identity/build_tree.py` из волны 0, а не против
  реальных данных и не против `projects_v2/` в checkout (там 1 документ и 1
  версия — это не корпус).
- `scripts/ci_known_failures.txt` правит только оркестратор между волнами через
  `python scripts/ci_regression_gate.py --record`.
- Гейт каждой волны: `python -m pytest tests backend/tests` и
  `python scripts/ci_regression_gate.py` без новых падений.

---

## 14. Риски параллельности

| Риск | Проявление | Снятие |
| --- | --- | --- |
| Два агента правят один горячий файл | конфликт правок в общем дереве | карта владения §10; чужие файлы — оркестратором между волнами |
| Агент коммитит сам | грязная история, блок `production_source_guard` | коммитит только оркестратор |
| Агенты договариваются о схеме на лету | разошедшиеся JSON-формы | §11 зафиксирован волной 0 |
| Формат `finding_uid` меняется после первой записи | миграция всех экспертных решений | §0.1 решается в волне 0, до записи |
| `run_manifest` меняется в 2.2 без версии схемы | слепая миграция | §0.2, `schema_version` с первой записи; `blob_id` повышает схему до v2 |
| Тесты пишутся в один файл | конфликт в `tests/` | один агент — свои тест-файлы |
| Агент трогает реальные данные | необратимая правка корпуса | волна 1 read-only без `--execute`; далее dry-run по умолчанию |
| Волна ушла вперёд по флагам | преждевременное переключение production | флаги переключает оператор по гейту |
| `document_uid` пересчитан заново | два UID у одного документа | генерация только в `ensure_document_uid` |
| Fuzzy-матч «угадал» | старое решение уехало на новое замечание | два равных кандидата → новый UID и отчёт |
| Этап 1 съехал в cutover | смешение с 1Б | §8 явно называет вход в 1Б; флаги записи не трогаются |

---

## 15. Соответствие критериям завершения этапа 1

| Критерий | Где закрывается |
| --- | --- |
| 1. Актуальный baseline | W1-1 |
| 2. 100% документов имеют один `document_uid` | W1-2 + W2-1 |
| 3. Новые ссылки содержат UID, старые — через алиасы | W4-1…W4-4 |
| 4. Расхождений указателей версии — 0 | W3-1 |
| 5. Актуальный run существует и завершён; форматы классифицированы | W1-3 + W3-2 |
| 6. 100% новых findings с UID, коллизий 0 | W2-2 + W5-2 |
| 7. Новые решения на `finding_uid` со снимком | W3-3 |
| 8. Исторические решения без неучтённых орфанов | W1-4 + W4-6 |
| 9. Вердикты и `REG-*` не меняют байты run | W2-3 |
| 10. `latest` восстанавливается из run | W3-2 |
| 11. Сравнения и блоки со ссылками на версию и поколение | W4-4 + W4-5 |
| 12. Проверка целостности без critical/error | W1-5 + W5-1 |
| 13. Manifest имеет известную схему; current/complete без manifest запрещены | W1-5 + W3-1 + W3-2 + W5-1 |
| 14. Документация не направляет в legacy | W5-4 |

---

## Связанные документы

- [Этап 1. Правила идентичности и целостности](01_storage_and_identity_rules.md)
- [Глобальный план развития хранения](00_global_plan.md)
- [Подэтап 1Б. Write-cutover на `projects_v2`](01b_projects_v2_write_cutover.md)
- [ADR опциональных внешних источников](ADR_external_sources_are_optional.md)
- [Сегмент 2.1. Потоковый ingest](02_01_streaming_ingest.md)
- [Этап 2. Единый файловый контур](02_unified_file_storage_and_ingest.md)
- [Этап 3. PostgreSQL для метаданных](03_postgresql_metadata.md)
- [Стабильный идентификатор замечания](../stable_finding_id.md)
- [`projects_v2` — стандарт структуры](../projects_v2_storage_standard.md)
