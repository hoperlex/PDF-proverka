# Глоссарий предметной области AuditManager

**Статус:** проект словаря; нормативная сила — после принятия ADR-0018<br>
**Редакция:** 2026-08-28<br>
**Владельцы:** lane ARC — словарь и идентичность<br>
**Связанные task IDs:** W0-ARC-02, W0-ARC-01, W0-DATA-02, W1-META-01, W1-STO-01, W1-API-01<br>
**Парный документ:** [Domain contract v1](DOMAIN_CONTRACT_V1.md)

Словарь задаёт одно имя на понятие и фиксирует, какие слова действующего
кода означают разное. Машиночитаемая часть контракта — реестр
идентификаторов, таблицы состояний и каталог ошибок — живёт в
[Domain contract v1](DOMAIN_CONTRACT_V1.md) и здесь не дублируется.
Глоссарий на неё ссылается.

Область применения — новый контур. Действующий код словарь не
переименовывает: замена имени в legacy является изменением поведения и
расходует capability slot (Bible P-17).

## 1. Как пользоваться словарём

- одно понятие имеет одно имя во всех слоях: domain-код, HTTP API,
  gRPC-контракты, журналы, схема PostgreSQL и интерфейс;
- русское слово — подпись для человека, машинное значение — латиница
  `snake_case`; подпись живёт в отдельном display-поле и не участвует в
  сравнении, сортировке, ключах и путях;
- запрещённый синоним не употребляется в новом контуре: он читается
  adapter-ом из действующего контура и в новые контракты не попадает.
  Список запрещённых синонимов — §2 контракта;
- термин без записи в словаре не вводится: новое понятие добавляется
  сюда одним изменением вместе с контрактом и машиночитаемой формой в
  `contracts/domain/v1`;
- слово из §4 не употребляется без квалификатора: конфликт разрешается
  ссылкой на строку таблицы, а не выбором удобного значения;
- запись словаря называет владельца данных; несколько читателей
  разрешены, второй авторитетный writer запрещён (Bible §2).

## 2. Основные сущности

Реестр идентификаторов §3.2 контракта является источником истины.
Колонки «Термин (RU)», «Идентификатор» и «Владелец записи» §2.1 совпадают
с ним дословно; расхождение правится в глоссарии, а не в контракте.

### 2.1. Сущности реестра идентификаторов

| Термин (RU) | Каноническое имя (EN) | Определение | Идентификатор | Владелец записи |
| --- | --- | --- | --- | --- |
| Объект строительства | `object` | Стройка или комплекс, объединяющий документы разных дисциплин | `object_id` | documents |
| Дисциплина | `discipline` | Раздел проектирования: АР, ЭОМ, ОВ и другие; код реестра — латиница | `discipline_code` | documents |
| Документ | `document` | Логический комплект одной дисциплины со своей историей версий | `document_uid` | documents |
| Версия документа | `document version` | Одна принятая загрузка документа; после публикации неизменяема | `version_id` | documents |
| Импорт | `import` | Факт приёма входного комплекта с фиксацией происхождения и checksum | `import_id` | ingest |
| Входной файл | `input file` | Один файл принятой версии в известной роли; байты адресует `blob_id` | роль файла + `blob_id` | ingest |
| Объект хранения | `blob` | Долговечная последовательность байтов с размером и SHA-256 | `blob_id` | storage |
| Страница PDF | `pdf page` | Физическая страница версии; нумерация с единицы | `(version_id, pdf_page)` | documents |
| Блок | `block` | Область страницы, пришедшая из выгрузки портала | `block_id` | documents |
| Логическое задание | `job` | Запрос пользователя выполнить аудит | `job_id` | jobs |
| Попытка исполнения | `attempt` | Одно исполнение задания конкретным воркером | `attempt_id` | jobs |
| Запуск анализа | `run` | Неизменяемый набор результатов одной обработки версии | `run_id` | jobs |
| Артефакт запуска | `artifact` | Файл, созданный запуском; роль берётся из закрытого реестра | `(run_id, artifact_role)` | storage |
| Замечание | `finding` | Одна найденная проблема; внутри своего запуска неизменяемо | `finding_uid` | findings |
| Экспертное решение | `expert decision` | Append-only событие вердикта человека по замечанию | `decision_id` | decisions |
| Сессия сравнения | `comparison session` | Операция сравнения двух наборов документов | `session_id` | comparison |
| Пара сравнения | `comparison pair` | Связка двух листов внутри сессии | `pair_id` | comparison |
| Профиль анализа | `analysis profile` | Immutable конфигурация запуска: routing, модель, параметры, ссылки на версии | `analysis_profile_id` | analysis |
| Комплект промптов | `prompt bundle` | Content-addressed версия набора шаблонов с SHA-256 каждого | `prompt_bundle_id` | analysis |
| Снимок норм | `norms snapshot` | Неизменяемый срез нормативной базы, закреплённый за запуском | `norms_snapshot_id` | analysis |
| Запись вызова модели | `model call record` | Immutable доказательство одного вызова LLM: checksum, usage, стоимость | `model_call_id` | analysis |
| Запрос на удаление | `erasure request` | Заявка на удаление данных субъекта; workflow задаёт ADR-0014 | `erasure_request_id` | operations |
| Корреляция операции | `correlation` | Сквозной идентификатор одной операции в журналах и трассах | `correlation_id` | operations |
| Воркер | `worker` | Машина, исполняющая попытку задания | `worker_id` | workers |
| Экземпляр воркера | `worker instance` | Один запуск процесса агента на машине | `instance_id` | workers |
| Пользователь | `user` | Субъект доступа; значение поля `actor` в экспертном решении | `user_id` | access |

Форматы идентификаторов и области уникальности — §3.1 и §3.2 контракта,
разрешённые составные ключи — §3.3, legacy-алиасы — §3.4, состояния
версии, запуска, импорта, объекта хранения и решения — §4.

### 2.2. Понятия без собственного идентификатора

Словарь называет эти понятия, а реестр §3.2 идентификатора им не выдаёт.
Колонка «Чем идентифицируется» показывает, через что понятие адресуется.

| Термин (RU) | Каноническое имя (EN) | Определение | Чем идентифицируется | Владелец записи |
| --- | --- | --- | --- | --- |
| Входной комплект | `ingest bundle` | Набор файлов одной загрузки, принимаемый и проверяемый как целое | версия документа и роли её файлов (§3.3 контракта); факт приёма — `import_id` | ingest |
| Лист | `sheet` | Подпись из штампа; повторяется и ключом не является | атрибут страницы версии | documents |
| Кроп | `crop` | Растровое изображение блока | производное представление блока; перестраивается (P-12) | storage |
| Критичность | `severity` | Класс последствий замечания | значение поля замечания из закрытого списка §4.7 контракта | findings |
| Доказательство | `evidence` | Привязка замечания к блоку, странице и цитате нормы | поля самого замечания | findings |
| База решений | `decision knowledge base` | Поиск и повторное применение решений эксперта | перестраиваемая проекция журнала решений (P-12) | decisions |
| Норма | `norm` | Нормативный документ или его пункт, на который ссылается замечание | код нормы внутри `norms_snapshot_id` | analysis |
| Манифест | `manifest` | Версионированное описание состава комплекта, запуска или пакета | принадлежит своему предмету | владелец предмета |
| Пакет задания | `job package` | Переносимый вход движка анализа с фиксированной схемой | `run_id` и checksum содержимого | jobs |
| Пакет результата | `result package` | Переносимый выход движка, проверяемый до публикации | `run_id` и checksum содержимого | jobs |
| Стадия конвейера | `stage` | Шаг обработки с контрактными входом и выходом | идентификатора v1 не вводит | не определён в v1 |

Идентификатор стадии конвейера v1 не вводит намеренно: имена и реестр
этапов принадлежат единому stage contract волны 5 (roadmap §11 п. 5.1), а
статусы этапов `pipeline_log.json` в v1 не переносятся (§6 контракта).
Префикс для стадии в §3.2 не зарезервирован, поэтому имя `stage_id` в
новом контуре не употребляется.

## 3. Роли контура и слова программы миграции

| Термин | Определение | Источник определения |
| --- | --- | --- |
| control plane | Новый модульный backend, который владеет пользователями, документами, версиями, файлами, заданиями, статусами, результатами и API; тяжёлый анализ он выполнять не обязан | ADR Bible §3.1 |
| execution engine | Исполнитель pipeline с входом в виде versioned job package и выходом в виде проверяемого result package; current version не переключает, в PostgreSQL напрямую не пишет и не решает, какой результат публиковать | ADR Bible §3.2 |
| bounded context | Модуль с собственным словарём, бизнес-правилами и владельцем данных; внутренние repository и model соседнего контекста не импортируются | ADR Bible §3.3 |
| вертикальный сценарий | Минимальная законченная пользовательская цепочка: UI, API, бизнес-правило, данные, наблюдаемость, тест | ADR Bible §3.4 |
| contract и schema version | Версионированный машинно проверяемый контракт на границе независимо изменяемых компонентов; неизвестная версия отклоняется явно | ADR Bible §3.5 |
| волна | Набор задач, работающих от frozen contract versions; внутри волны общие контракты не меняются, волна заканчивается integration gate | roadmap §3.1 |
| capability lane | Долгоживущая область владения с непересекающимися по умолчанию файлами | roadmap §3.2 |
| integration task | Единственная задача, которой разрешено соединять несколько lanes, менять composition root, root lockfile или общий deployment manifest | roadmap §3.3 |
| ownership zone | Каталог, который редактирует одна task; shared files принадлежат интегратору | roadmap §4 п. 2, ADR-0006 |
| shadow | Режим, в котором новый компонент выполняет работу параллельно с действующим и авторитетным writer не является | roadmap §8, W2-INT-02 |
| parity | Семантическое совпадение результатов двух контуров, проверяемое тестами, а не побайтным сравнением; для LLM слово квалифицируется как contour parity, analysis replay parity или live quality parity | roadmap §6, §8 |
| canary | Включение нового маршрута для ограниченного списка объектов и пользователей под error budget | roadmap §8, W2-INT-03 |
| cutover | Переключение primary для данных или маршрута; обратимо до observation gate | ADR Bible P-11 |
| observation | Непрерывный период наблюдения после переключения с минимальной длительностью и минимальным числом runs | roadmap §5.1 |
| retirement | Отключение legacy по потребителям и удаление старого writer или route после observation и restore drill | roadmap §2, §11 |

Порядок обязателен и сокращению не подлежит:
`baseline → shadow → parity → canary → primary → observation → cleanup`
(Bible P-11). До cleanup существует проверенный rollback.

## 4. Конфликты действующего кода

Таблица разбирает слова, которые в действующем коде означают разное.
Каждое значение подтверждено ссылкой на файл и строку.

| Слово | Значение A | Значение B | Значение C | Как разводятся в новом контуре |
| --- | --- | --- | --- | --- |
| `stage` | Этап конвейера анализа: `backend/app/models/audit.py:8`, `backend/app/services/common/project_service.py:1864` | Стадия проектирования ПД, РД, КМД: `backend/app/services/text_analysis/stage_gates.py:33` | Каталоги `stage_1` и `stage_2` сравнения стадий П и РД: `backend/app/services/stage_comparison/stage_upload.py:27`, `backend/app/services/stage_comparison/text_comparison.py:912` | `stage_id` — только шаг конвейера; стадия проектирования — `document_stage`; сторона сравнения — `comparison_side` |
| `status` | Статус этапа конвейера `pending`, `running`, `done`, `error`, `partial`, `skipped`: `backend/app/models/project.py:16`, `backend/app/services/common/audit_logger.py:94` | Статус задания `queued`, `running`, `completed`, `failed`, `cancelled`: `backend/app/models/audit.py:30` | Статус версии `active` рядом с `analysis_status` в одном файле: `backend/app/services/common/version_service.py:460` | Поле состояния квалифицировано владельцем: `analysis_status`, `run_state`, `import_state`, `blob_state`; голое `status` запрещено |
| `severity` | Критичность замечания русскими строками: `backend/app/core/config.py:775` | Уровень события воркера `warn` и `error`, во фронтенде `warning`: `audit_worker/agent.py:861`, `backend/app/services/distributed_workers/distributed_ui.py:1214` | Класс события безопасности `security` в durable audit: `backend/app/services/distributed_workers/authorization.py:346` | `severity` — только критичность замечания латиницей (§4.7 контракта); уровень журнала — `log_level`; класс события журнала — `audit_event_class` |
| `audit` | Аудит проектной документации как бизнес-процесс: `backend/app/api/routers/audit.py:27` | Durable audit — журнал действий и решений: `backend/app/core/action_log.py:24` | Перепроверка отклонённых замечаний: `backend/app/services/findings/rejected_audit_service.py:1` | Бизнес-процесс — `analysis run`; журнал — `audit_trail`; перепроверка — `finding_recheck` |
| `run` | Каталог результатов `runs/<run_id>`: `backend/app/services/storage/v2_primary_wiring.py:203` | `run_id`, равный `job_id` живого аудита: `backend/app/pipeline/manager.py:2045` | Локальный идентификатор прогона стадии на метке времени: `backend/app/pipeline/stages/optimization/ensemble.py:482` | `run_id` — только опубликованный неизменяемый набор результатов; задание — `job_id`; внутренний прогон стадии собственного идентификатора не получает |
| `job` | Задание backend-очереди `AuditJob` с `job_id` из `uuid4`: `backend/app/models/audit.py:38` | Логическое задание распределённого контура с отдельной попыткой: `backend/app/services/distributed_workers/schema.py:244`, `:265` | Задание оптимизации разделов с собственным форматом идентификатора: `backend/app/services/section_optimization_pipeline_service.py:164` | Один `job_id` на запрос пользователя, `attempt_id` на исполнение, `run_id` на результат (§3.2 контракта) |
| `decision` | Вердикт эксперта `accepted` и `rejected`: `backend/app/models/expert_review.py:13` | Решение critic v2 `accept`, `reject`, `borderline`, `merge`, `low_priority`: `backend/app/pipeline/stages/findings_review/critic_v2/models.py:46` | Ответ заказчика, отображаемый в решение: `backend/app/services/external_register/apply_verdicts.py:199` | `decision_verdict` — только решение человека; машинный вердикт — `review_verdict`; ответ заказчика — `customer_response` |
| `verifier` | Этап findings_verify с UI-подписью «Верификатор»: `backend/app/pipeline/stages/findings_verify/runner.py:4` | Верификация норм norm_verify: `backend/app/pipeline/stages/norms/runner.py:4` | Проверка целостности пакета и сертификата воркера: `audit_worker/package_io.py:203`, `backend/app/security/certificate_profiles.py:110` | Этап называется по предмету проверки; сверка байтов — `checksum_verification`; проверка личности — `identity_verification` |
| `grounding` | Привязка замечания к блоку: `backend/app/services/findings/grounding_service.py:2` | Извлечение значений из вектор-графики: `backend/app/pipeline/stages/block_grounding/__init__.py:1` | Заземление как предметная категория дисциплины ЭОМ: `prompts/disciplines/EOM/finding_categories.md:7` | Привязка — `evidence_binding`; извлечение значений — `value_extraction`; предметная категория остаётся значением поля `category` |
| `manifest` | Манифест входного комплекта `input_manifest.json`: `backend/app/services/common/project_service.py:3204` | Манифест архива пакета `package_manifest.json`: `audit_worker/package_io.py:26`, `backend/app/services/distributed_workers/package_service.py:34` | Манифест результата анализа `audit_manifest.json`: `backend/app/pipeline/remote_audit_runner.py:727` | Имя манифеста называет предмет: `input_manifest`, `run_manifest`, `package_manifest`; слово `manifest` без квалификатора не употребляется |
| `profile` | Профиль дисциплины — каталог с ролью и чек-листом: `backend/app/services/common/discipline_service.py:87` | Профиль исполнения удалённого аудита: `backend/app/pipeline/execution/contracts.py:110` | Графический профиль блока `profile_id`: `backend/app/services/common/graphic_profile_classifier.py:13` | `analysis_profile_id` — конфигурация анализа; профиль дисциплины — `discipline_profile`; профиль графики — `graphic_profile` |
| `package` | Пакет задания и результата воркера: `backend/app/services/distributed_workers/package_service.py:34` | Пакет контекста блока Stage 01: `backend/app/pipeline/stages/block_grounding/block_source_router.py:673` | Python-пакет и npm-пакет: `norms/__init__.py:1`, `frontend/package.json:2` | `job_package` и `result_package` — только контракт движка; контекст блока — `block_context_bundle`; единица дистрибутива словарём не описывается |
| `provenance` | Происхождение замечания: детектор и модель: `backend/app/pipeline/stages/block_analysis/provenance.py:1` | Происхождение отрезка вектор-графа: `backend/app/pipeline/stages/block_grounding/vector_path_graph.py:78` | Происхождение релиза по commit: `scripts/deploy_center_release.py:207` | `ProvenanceRecord` — только происхождение импортированного комплекта; атрибуция замечания — `detector_attribution`; источник геометрии — `geometry_source` |
| `version` | Версия документа `vNNN`: `backend/app/services/common/version_service.py:16` | Версия схемы файла `schema_version`: `backend/app/services/common/version_service.py:49` | Версия промпта и алгоритма: `backend/app/pipeline/stages/block_analysis/provenance.py:23`, `backend/app/services/stage_comparison/text_ai_reviewer.py:21` | `version_id` — только версия документа; схема — `schema_version`; контракт — `contract_version`; промпт — `prompt_bundle_id` |
| `latest` | Каталог продвинутых артефактов `03_analysis/latest`: `backend/app/services/storage/projects_v2_adapter.py:297` | Указатель актуальной версии `latest_version_id`: `backend/app/services/common/version_service.py:18` | Самая свежая строка таблицы: `audit_worker/local_db.py:306` | Актуальность версии хранит `current_version_id` с одним владельцем; каталог `latest` — перестраиваемое представление (P-12); свежая запись именуется по предмету |
| `project` | Раздел документации: папка с одним PDF: `backend/app/services/common/project_service.py:309` | Стройка как объект: `backend/app/services/common/object_service.py:2` | Переносимый корень `projects_v2` внутри пакета воркера: `audit_worker/package_io.py:47` | Раздел документации — `document`; стройка — `object`; корень переноса — `package_root` |
| `block_id` | Человекочитаемый код вида `A64J-JJPV-A7Y`: `backend/app/services/findings/findings_service.py:551` | Портальный `blk_` и 32 hex-символа: `backend/app/services/common/results_md.py:48` | Старые формы `block_007_1` и `page_12_text`: `backend/app/pipeline/stages/findings_review/deterministic_critic.py:66` | Оба поколения сохраняются в mapping как legacy-алиасы; новые блоки получают `blk_<ULID>` (§3.4 контракта) |

### 4.1. Расхождение о том, какое поколение `block_id` считается новым

Документация и код называют новым разные поколения формата.

| Источник | Что назван новым | Что назван старым |
| --- | --- | --- |
| `backend/app/pipeline/stages/crop_blocks/block_markdown.py:5` и `:7` | `blk_` и hex — формат портала vibe 2026-07 | дефисный код из Chandra-разметки |
| `backend/app/pipeline/stages/block_grounding/md_mirror_reconcile.py:16` | `blk_` и hex | дефисный код |
| `docs/new_upload_format.md:31` | `blk_` и 32 hex-символа | комплект прежнего метода |
| `backend/app/services/findings/rejected_audit_service.py:111` | дефисный код, константа `_MODERN_BLOCK_ID_RE` | `blk_`, константа `_LEGACY_BLOCK_ID_RE` |
| `backend/app/services/findings/block_captions.py:45` | дефисный код назван портальным | `block_007_1` |

Два модуля применяют к формам противоположную нормализацию регистра:
`backend/app/services/findings/rejected_audit_service.py:188` приводит
дефисную форму к верхнему регистру, `:190` приводит `blk_` к нижнему.
Контракт v1 снимает спор: оба поколения являются legacy-алиасами, а
канон — `blk_<ULID>`. Генератора ULID в действующем коде нет; форма
зафиксирована только в `contracts/domain/v1/identifiers.json`.

### 4.2. Значения, не поместившиеся в таблицу

- `stage` — шаг подтверждения отмены `CANCEL_ACK_STAGE_*`
  (`contracts/agent_stream/v1/agent_stream.proto:66`); порядковый номер
  уровня анализа, где имена артефактов и документированный порядок
  этапов нумеруются встречно: `01_blocks_analysis.json` против этапа 02
  и `02_text_analysis.json` против этапа 01
  (`backend/app/services/storage/stage_artifacts.py:29`, `CLAUDE.md:111`);
  шаги 1–5 конвейера сравнения
  (`backend/app/services/stage_comparison/project_change_summary.py:177`).
- `status` — статус нормы `active`, `replaced`, `cancelled`, `unknown`
  (`norms/external_provider.py:162`); нормативный статус пункта чек-листа
  (`backend/app/services/text_analysis/normative_status.py:35`); статус
  регистрации воркера и статус сертификата
  (`backend/app/models/distributed_workers.py:161`,
  `backend/app/services/distributed_workers/certificate_registry.py:22`);
  строковый признак успеха ответа
  (`backend/app/api/routers/audit.py:820`).
- `audit` — лог прогона конвейера `audit_log.jsonl`
  (`backend/app/services/common/audit_logger.py:399`) и каталог копий
  ответов модели `audit_trail`
  (`backend/app/services/llm/claude_runner.py:106`); ни то, ни другое не
  является durable audit из `backend/app/core/action_log.py:24`.
- `grounding` — в одном файле интерфейса слово означает и привязку, и
  заземление: `frontend/static/js/app.js:9508` против
  `frontend/static/js/app.js:9612`.
- `manifest` — манифест снимка профиля дисциплины
  (`backend/app/services/distributed_workers/discipline_profile.py:43`),
  манифест версий проекта
  (`backend/app/services/common/version_service.py:47`), манифесты
  релизов (`scripts/deploy_audit_worker.py:429`,
  `scripts/build_center_release.py:458`).
- `project_id` — в одном модуле собираются две несовместимые формы:
  `<дисциплина>/<имя>` (`backend/app/services/common/project_service.py:2870`)
  и голое имя папки
  (`backend/app/services/common/project_service.py:3362`).
- `correlation_id` — приравнен к `job_id`
  (`backend/app/pipeline/execution/registry.py:158`), поэтому операции
  внутри одного задания не различает.

## 5. Одна сущность — разные слова

| Сущность | Синонимы в действующем коде | Канон v1 |
| --- | --- | --- |
| Замечание | `findings` и `items` в одном выражении: `backend/app/services/findings/findings_service.py:128`; `problem`, `finding`, `description` как поле сути: `backend/app/models/findings.py:25`; `issue`, `remarks`, `corrective` во внешнем реестре: `backend/app/services/external_register/parser.py:379`; третья цепочка с `remarks`: `backend/scripts/compare_classic_findings_outputs.py:65`; подписи «Проблема» и «Замечания»: `backend/app/pipeline/stages/report/generate_excel_report.py:136` | `finding` с ключом `finding_uid` |
| Критичность | `severity` русскими строками: `backend/app/core/config.py:775`; `criticality` как запасной источник текста: `backend/app/services/external_register/parser.py:394`; форма с подчёркиванием `ПРОВЕРИТЬ_ПО_СМЕЖНЫМ`: `backend/app/data/discipline_checklists/VK.md:7`; значения `СУЩЕСТВЕННОЕ` и `СНЯТО` только в Excel: `backend/app/pipeline/stages/report/generate_excel_report.py:51`, `:86`; подстановка `НЕИЗВЕСТНО` вместо отсутствующего значения в восьми местах, среди них `backend/app/services/findings/findings_service.py:150`, `backend/app/pipeline/stages/findings_merge/runner.py:303`, `backend/app/services/common/project_service.py:984` | `severity` из закрытого списка §4.7 контракта; `НЕИЗВЕСТНО` и пустое значение отображаются в `unknown` |
| Версия документа | `version_id`, `logical_version_id`, `physical_version_id` в одной записи: `backend/app/services/common/version_service.py:455`; `label` вида `V1` рядом с `version_id` вида `v001`: `backend/app/services/common/version_service.py:458` | `version_id` вида `vNNN` внутри `document_uid` |
| Текущая версия | `latest_version_id` в манифесте: `backend/app/services/common/version_service.py:18`; `document.json.current_version` и `current_version.txt`: `backend/app/services/common/version_service.py:896`, `:899`; `None` как неявная актуальная версия: `backend/app/pipeline/context.py:95` | `current_version_id` — один указатель с одним владельцем |
| Запуск | `analysis_run_id` в `version.json`: `backend/app/services/storage/projects_v2_adapter.py:274`; `run_id`, равный `job_id`: `backend/app/pipeline/manager.py:2045`; исторические `run_refresh_*`: `scripts/projects_v2/refresh_migrated_snapshot.py:296` | `run_id` |
| Воркер | `worker_id` и `instance_id` в реестре центра: `backend/app/services/distributed_workers/schema.py:40`, `:42`; `executor_instance_id` на самом воркере: `audit_worker/local_db.py:58`; `worker_instance_id` в gRPC-контракте: `contracts/agent_stream/v1/agent_stream.proto:96` | `worker_id` и `instance_id` |
| Этап контекста блоков | Один раннер пишет оба ключа: `backend/app/pipeline/stages/block_context/runner.py:33`, `:34`; в нормализаторе канон — `gemma_enrichment`: `backend/app/pipeline/manager.py:3246`; в порядке этапов — `block_context`: `backend/app/services/common/project_service.py:1865`; в enum задания `gemma_enrichment` помечен как legacy alias: `backend/app/models/audit.py:23` | Имена этапов фиксирует единый stage contract волны 5 (roadmap §11 п. 5.1); v1 их не переносит, третье имя не вводится |
| Этап анализа блоков | Ключ `block_analysis`: `backend/app/models/audit.py:25`; поле `blocks_analysis`: `backend/app/models/project.py:19`; алиас `tile_audit`: `backend/app/pipeline/manager.py:3248`; файл `01_blocks_analysis.json` и legacy `02_blocks_analysis.json`: `backend/app/services/storage/stage_artifacts.py:29`, `:45`; два корневых ключа внутри одного файла: `backend/app/services/findings/findings_service.py:607` | То же: имя принадлежит stage contract волны 5 |
| Решение эксперта | `decision`: `backend/app/models/expert_review.py:13`; `origin_expert_status`: `backend/app/services/findings/decision_carryover_service.py:625`; расширенные множества `ACCEPTED_DECISIONS` и `REJECTED_DECISIONS`: `backend/app/services/findings/migrated_findings_service.py:121`, `:127`; `customer_response`: `backend/app/models/expert_review.py:66`; резолюция обсуждения: `backend/app/api/routers/discussions.py:267` | `decision_verdict` со значениями `accepted`, `rejected`, `revoked` |
| Дисциплина | `section` и `discipline` в одном выражении: `backend/app/services/common/project_service.py:1003`; латинский и кириллический коды в одном словаре: `backend/app/pipeline/stages/block_grounding/block_source_router.py:92` | `discipline_code` латиницей |

## 6. Русско-английские соответствия

Кириллица допустима в двух местах: в display-подписи (`display_name`,
`label`, заголовок интерфейса, подпись этапа, колонка отчёта) и в
содержимом документа (текст замечания, цитата нормы, наименование
листа). Ключ словаря, значение перечисления, имя поля, сегмент пути,
имя файла, метка метрики и элемент URL — латиница.

Правило уже реализовано в распределённом контуре:
`backend/app/services/distributed_workers/schema.py:246` объявляет
пользовательский код проекта метаданными и запрещает делать его
компонентом файлового пути.

| Где кириллица попадает в ключ или путь | Подтверждение | Канон v1 |
| --- | --- | --- |
| Значения `severity` русскими строками, включая enum JSON Schema | `backend/app/core/config.py:775`, `backend/app/schemas/text_analysis.json:62` | Латинские значения §4.7 контракта; русская формулировка — display-подпись |
| Кириллица в имени CSS-класса рядом с латинским дублем | `frontend/static/css/styles.css:2105` | Класс строится по машинному значению |
| Русские коды дисциплин как ключи словарей и как каноническое значение | `backend/app/pipeline/stages/block_grounding/block_source_router.py:92`, `backend/app/pipeline/stages/block_context/reference_catalog/build_catalog.py:21` | `discipline_code` латиницей; русское название — подпись реестра |
| Кириллические `folder_patterns` участвуют в резолве дисциплины по имени папки | `prompts/disciplines/_registry.json:8`, `backend/app/services/common/discipline_service.py:214` | Дисциплина хранится полем документа, а не выводится из пути (P-02) |
| Кириллица в идентификаторе проекта и в сегменте пути | `CLAUDE.md:219`, `backend/app/services/common/project_service.py:2870` | `document_uid` — ключ; код документа — display-поле |
| Русские метки ответа модели работают как ключи разбора | `backend/app/pipeline/stages/block_analysis/gemma_findings_only.py:405` | Метки отображаются в машинные ключи на границе adapter |
| Кириллические ключи гистограмм телеметрии | `backend/app/data/stage01_telemetry_examples/filled_per_project.json:9` | Метки метрик латиницей и низкой кардинальности (P-13) |
| Русские значения по умолчанию `НЕИЗВЕСТНО` и `РЕКОМЕНДАТЕЛЬНОЕ` | `backend/app/services/findings/findings_service.py:150`, `backend/app/pipeline/stages/text_analysis/md_prescan.py:62` | `НЕИЗВЕСТНО` и пустое значение отображаются в `unknown` (§4.7 контракта); подстановка `РЕКОМЕНДАТЕЛЬНОЕ` вместо отсутствующего значения — молчаливый fallback, запрещённый P-10 |
| Кириллица в имени листа Excel как ключе поиска | `backend/app/pipeline/stages/report/generate_excel_report.py:540` | Имя листа — подпись; поиск идёт по машинному ключу |

## 7. Термины, которых нет в коде

Проверка выполнена поиском по всему дереву репозитория без каталогов
зависимостей. Перечисленные имена встречаются только в документах и в
машиночитаемой форме контракта.

| Термин | Владеющий документ | Состояние |
| --- | --- | --- |
| `document_uid` | `docs/data_storage_modernization/01_storage_and_identity_rules.md:141`, `docs/stable_finding_id.md` | спроектировано, кода нет |
| `finding_uid` | `docs/stable_finding_id.md` | спроектировано, кода нет |
| `blob_id` | `docs/data_storage_modernization/02_unified_file_storage_and_ingest.md:39` | спроектировано, кода нет |
| `import_id` | `docs/data_storage_modernization/01_storage_and_identity_rules.md:238` | спроектировано; одноимённое поле в модуле сравнения означает другое — метку времени загрузки (`backend/app/services/stage_comparison/stage_storage.py:335`) |
| `run_manifest.json` | `docs/data_storage_modernization/01_storage_and_identity_rules.md:401` | спроектировано, кода нет |
| `AnalysisProfile` | `docs/architecture/adr/ADR-0013-llm-reproducibility-and-cost.md:44` | спроектировано, кода нет |
| `PromptBundle` | `docs/architecture/ADR_BIBLE.md:58`; поле `prompt_bundle_id` — ADR-0013 | спроектировано, кода нет |
| `NormsSnapshot` | `docs/architecture/ADR_BIBLE.md:59` | спроектировано, кода нет; действующая база `norms/norms_db.json` изменяема и снимка запуска не имеет |
| `ProvenanceRecord` | `docs/data_storage_modernization/01_storage_and_identity_rules.md:235` | спроектировано, кода нет; слово `provenance` в коде занято другими значениями (§4) |
| `ModelCallRecord` | `docs/architecture/adr/ADR-0013-llm-reproducibility-and-cost.md:55` | спроектировано, кода нет; ближайший действующий аналог — счётчик потребления `backend/app/services/common/usage_service.py:1` |

Строка словаря переносится из этой таблицы в §2 только вместе с кодом,
контрактом и тестом. До этого момента термин остаётся проектным.

## 8. Ссылки

- [Domain contract v1](DOMAIN_CONTRACT_V1.md) — идентификаторы, состояния
  и ошибки
- [ADR-0018](adr/ADR-0018-domain-contract-v1.md) — решение, дающее
  словарю и контракту нормативную силу
- [ADR-0006](adr/ADR-0006-target-repository-layout.md) — раскладка и
  зоны владения
- [ADR Bible](ADR_BIBLE.md) — §2 источники истины, §3 базовые понятия,
  P-01…P-18
- [Roadmap](HYBRID_REWRITE_ROADMAP.md) — §3 единицы планирования, волны
  и gates
- [Правила идентичности](../data_storage_modernization/01_storage_and_identity_rules.md)
- [Стабильный finding ID](../stable_finding_id.md)
