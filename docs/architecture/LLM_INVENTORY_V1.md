# Инвентарь LLM-контура — v1

**Задача:** `W0-LLM-01` (lane AI).<br>
**Редакция:** 2026-09-04.<br>
**Источник истины:** рабочее дерево на каноническом коммите `6dc3aadf`
(`origin/main`). Каждая строка ниже прочитана из кода, из конфигурационного
файла или измерена командой. Чего измерить нельзя — названо явно и разнесено по
четырём классам в §10.<br>
**Перепроверка среза.** Инвентарь снимался на `bff35d7d` (ветка `dev`), которая
не содержит 1613 файлов, добавленных в `origin/main` позже. Из файлов, на
которые ссылается документ, между срезами изменились четыре:
`gemma_findings_only.py` (добавлена политика повторов OpenRouter, §6.8),
`core/config.py`, `routers/stage_comparison.py`, `routers/blocks.py`. Каталоги
`prompts/**`, `norms/**`, `services/llm/**` и `audit_worker/**` между срезами не
менялись — `git diff --name-only bff35d7d 6dc3aadf -- prompts norms
backend/app/services/llm audit_worker` даёт пустой вывод, поэтому все числа §3,
§4 и §5 перенесены без правки. Сто восемьдесят девять ссылок с номерами строк
сверены пословно, семнадцать перенесены на канон.<br>
**Изменений кода задача не вносит.** Это frozen input для `ADR-0013`
(`W0-ADR-04`) и для `W0-LLM-02` (санитизированные кассеты и replay), а также
вход для `W0-ADR-08` (ADR-0012).

**Что документ отвечает.** По каждому из шести предметов инвентаря —
промпты, нормы как вход модели, маршрутизация, транспорты, параметры модели,
mutable sources — сформулирован один и тот же вопрос: **что нужно зафиксировать,
чтобы повторный прогон дал тот же ответ**, и что зафиксировать невозможно в
принципе. Второе не пробел инвентаря, а свойство предметной области, и названо
отдельно (§10).

**Чего документ не делает.** Не изготавливает кассеты и не выбирает их формат —
это `W0-LLM-02`; не правит ни строки кода, ни одного теста, ни одного промпта;
не объявляет условие Gate G0 №5 выполненным; не принимает ADR-0013 и не
переписывает его §3.

## 1. Граница инвентаризации

Инвентаризируется **всё, что определяет ответ модели**: текст, ушедший в
запрос; выбор адресата запроса; параметры вызова; канал доставки; и любое
состояние, способное измениться между двумя прогонами без явного действия
инженера.

Внутрь границы попадают вещи, которые обычно не считают частью LLM-контура, но
которые фактически меняют ответ: рукописный нормативный справочник дисциплины,
подмешиваемый в system-промпт целиком; таблица моделей, лежащая вне git;
редактирование промпта из веб-интерфейса; кэш платных ответов; порядок
разрешения модели, у которого пять конкурирующих источников.

Вне границы: качество аудита (слой 3 по
[behaviour freeze](../data_storage_modernization/00a_behaviour_freeze.md),
меряется `scripts/eval_harness.py`), устройство самого конвейера вне
LLM-вызовов, хранение и retention артефактов (это
[инвентарь данных](DATA_INVENTORY_V1.md), `W0-DATA-01`).

## 2. Метод и правило доказательства

Утверждение попадает в документ, только если у него есть либо путь с номером
строки, либо команда с её выводом. Отрицательные утверждения («механизма нет»)
доказываются так же — командой, чей вывод пуст или равен нулю. Числа §12
воспроизводятся на срезе `6dc3aadf`.

Три состояния, которыми размечены все источники:

| Метка | Значение |
| --- | --- |
| **фиксируемо** | состояние можно записать нашими силами и предъявить при повторе; отсутствие записи — наш недоделанный механизм, а не свойство мира |
| **нефиксируемо** | состояние принадлежит внешней стороне и меняется без нашего ведома; максимум, что доступно, — записать наблюдение и его дату |
| **фиксируемо частично** | записать можно объявленное значение, но не то, что за ним стоит |

## 3. Промпты

### 3.1. Файловый корпус: 152 файла

```
$ find prompts -type f | wc -l
152
```

| Каталог | Файлов | Состав |
| --- | ---: | --- |
| `prompts/pipeline/ru` | 11 | этапные шаблоны, редактируются из UI |
| `prompts/pipeline/ru/phase1` | 6 | 5 промптов + `README.md`; **не подключены** |
| `prompts/pipeline/en` | 9 | 8 шаблонов + `_sync.json`; **именно они уходят в модель** |
| `prompts/disciplines` | 126 | `_registry.json` + 14 профилей |

Объём: 724 374 байта. Дисциплин четырнадцать — `AI, AR, EOM, GP, ITP, KJ, KM, OV, POS,
PS, PT, SS, TX, VK`; в каждой 8 `.md` (`role`, `checklist`, `triage_table`,
`project_params`, `drawing_types`, `finding_categories`, `norms_reference`,
`compact_strategy`) плюс `config.json`. Отклонение одно: у `EOM` нет
`compact_strategy.md`, а `backend/app/services/common/discipline_service.py:189`
его читает и молча получает пустую строку.

`prompts/disciplines/*/config.json` — чистый маппинг «логическая роль → имя
файла»: десять ключей, ни модели, ни параметров, ни версии. Профили дисциплин —
**больше половины объёма корпуса (788 КБ)** и правились за всю историю
репозитория 6 раз, последний раз 2026-07-04 и уборкой, а не по существу.

**Русский шаблон в модель не уходит.** Выбор языка —
`backend/app/pipeline/stages/prepare/task_builder.py:187-197`:

```python
def load_template_for_llm(ru_path: Path) -> str:
    """Приоритет: английская версия (prompts/pipeline/en/) → русская."""
    en_path = _en_path_for(ru_path)
    if en_path.exists():
        return en_path.read_text(encoding="utf-8")
    return load_template(ru_path)
```

Решение принимается **по факту существования файла**, и больше ни по чему.
Три шаблона английской пары не имеют (`norm_requote_task.md`,
`optimization_norm_fix_task.md`, `rejected_finding_expert_audit.md`) — они
уходят в модель по-русски.

Кэширования этапных шаблонов в памяти процесса нет: файл открывается заново на
каждый вызов. Профили дисциплин, наоборот, кэшируются
(`discipline_service.py:45` `_profile_cache`, сброс — `:446`), поэтому правка
профиля на диске подхватывается не сразу.

### 3.2. Промпты, зашитые в код

`"role": "system"` встречается в Python-коде 31 раз; 8 из них берут содержимое
из файла через `prompt_builder._load_and_clean_template`. Остальные **23 — текст
в коде**. Литералов длиной ≥250 символов, уходящих в модель, около 36 суммарным
объёмом ≈34 000 символов; из них 13 — самостоятельные роли. Тридцать шестой
найден перепроверкой на каноне и в первую редакцию не входил — Stage 5.3,
1002 символа, §5.7.

Крупнейшие:

| Файл:строка | Константа | Симв. | Назначение |
| --- | --- | ---: | --- |
| `backend/app/pipeline/stages/block_analysis/gemma_findings_only.py:349` | `SYSTEM_PROMPT_BASE` | 3562 | Stage 01/02 графический анализ блоков |
| `backend/app/services/stage_comparison/project_change_summary.py:177` | `SYSTEM_PROMPT` | 2455 | агрегатор изменений П↔РД |
| `backend/app/services/stage_comparison/text_ai_reviewer.py:94` | `SYSTEM_PROMPT` | 2125 | семантический ревьюер различий (J-25) |
| `backend/app/pipeline/stages/block_analysis/dual_review.py:41` | `REVIEW_SYSTEM_PROMPT` | 1799 | арбитр двух детекторов |
| `backend/app/services/section_optimization_agent_service.py:71` | `_SYSTEM_PROMPT` | 1630 | агент тиражирования оптимизаций |
| `backend/app/pipeline/stages/norms/clause_binding.py:43` | `SYSTEM_PROMPT` | 1107 | привязка пункта норматива |
| `backend/app/pipeline/stages/findings_review/critic_v2/llm_gate.py:167` | `_FALLBACK_PROMPT` | 925 | аварийный критик |
| `backend/app/services/stage_comparison/high_level_project_changes.py:153` | `SYSTEM_PROMPT` | 1002 | верхнеуровневый синтез изменений П↔РД (Stage 5.3) |

Отдельно `backend/app/pipeline/stages/prepare/codex_targeted_findings.py` держит
**шесть** inline-ролей (строки 473, 503, 535, 570, 604, 649; 1103–1791 символов)
— параллельную дисциплинарную логику, никак не связанную с
`prompts/disciplines/`.

Ещё два боевых промпта лежат вне `prompts/`:
`backend/app/pipeline/stages/findings_review/critic_v2/prompts/llm_gate_human_taxonomy.ru.md`
(21 513 Б) и `kb_augmented.ru.md` (2047 Б).

**Следствие.** Конфигурация промптов расщеплена на две несопоставимые половины:
152 файла под `prompts/` покрывают восемь этапов конвейера, а Stage 01-графика,
dual-review, clause-binding, targeted-findings, агенты оптимизации,
stage-comparison и обсуждения живут в Python и версионируются только историей
кода. Любой «prompt bundle», собранный из `prompts/**`, покрывает меньше
половины того, что реально уходит в модель.

### 3.3. Текст промпта зависит не только от шаблона

Между шаблоном и байтами запроса стоят четыре преобразования, и каждое —
самостоятельный вход:

1. **Инъекция профиля дисциплины** — `discipline_service.py:312`
   `inject_discipline()` подставляет `{DISCIPLINE_ROLE}`,
   `{DISCIPLINE_CHECKLIST}`, `{DISCIPLINE_NORMS_FILE}` и др.
2. **Зачистка под транспорт** — `prompt_builder.py:105`
   `_clean_template_for_api()` удаляет строки с CLI-инструкциями, а
   `stages/*/provider_transport.py` дочищает абсолютные пути. Один и тот же
   шаблон даёт **разный текст** для агентного CLI, для provider-адаптера и для
   HTTP-пути. Причина зафиксирована в самом коде
   (`stages/text_analysis/provider_transport.py:19-27`): у provider-режима нет
   инструментов `Read`/`Write`, и инструкция «прочитай файл» ломает ответ.
3. **Обязательные хвосты в коде** — `TRANSPORT_CONTRACT`, `INPUT_DATA_NOTE`,
   `SEVERITY_SEMANTICS`, `_OUTPUT_CONTRACT`, `_ABSENCE_GUARD_TEXT`
   (`task_builder.py:54`, включается флагом `PIPELINE_ABSENCE_GUARD_ENABLED`).
4. **Per-project override** — см. §3.6.
5. **Ambient-контекст Claude Code** — см. §3.4. Это преобразование не видно в
   коде сборки промпта вовсе, и оно самое крупное по объёму.

Плейсхолдеры английских шаблонов включают `{BASE_DIR}`, `{PROJECT_PATH}`,
`{MD_FILE_PATH}`, `{OUTPUT_PATH}`, `{BLOCKS_ANALYSIS_PATH}`: **в промпт уезжают
абсолютные пути**. Плейсхолдера текущей даты нет ни одного — это хорошая
новость для нормализации ключа кассеты (`behaviour freeze` §4.4 требует снимать
пути, `run_id` и даты; даты снимать не придётся, пути придётся).

### 3.4. Самый крупный вход промпта не лежит в `prompts/`

`claude -p` запускается как процесс, и Claude Code сам подтягивает в контекст
проектный `CLAUDE.md`, `.claude/settings.json`, хуки, memory и skills рабочего
каталога. Отключается это чистой cwd, и механизм написан
(`claude_runner.py:233-291` `_clean_cwd_root` / `_ensure_clean_cwd`), а мотив
измерен и записан прямо в коде (`claude_runner.py:226-229`):

> Чистая cwd для запуска `claude -p` без подгрузки project CLAUDE.md / hooks /
> memory / skills. Эмпирически (КЖ5.1, 25 блоков) даёт −42% input/блок и −36%
> cli_cost при +35% findings.

**Но по умолчанию он выключен.** `claude_runner.py:318` — `clean_cwd: bool = False`;
`:393-401` — при `False` `cwd_arg = None`, то есть рабочий каталог наследуется
от процесса бэкенда, а это корень репозитория. Из пятнадцати вызовов `_run_cli`
параметр передаёт **один** (`:2558`, `clean_cwd=CLAUDE_BLOCK_BATCH_CLEAN_CWD`).

Что из этого следует: для четырнадцати из пятнадцати CLI-этапов в контекст
модели фактически входят

* `CLAUDE.md` корня репозитория — **29 108 байт** (на срезе первой редакции
  было 27 548; файл растёт), то есть больше любого
  этапного шаблона;
* `AGENTS.md` (895 байт);
* `.claude/settings.json`, включая объявленный там `SessionStart`-хук
  `python .claude/hooks/load_context.py`, который сканирует `projects/` и
  печатает **живой статус всех проектов** — данные, меняющиеся каждый прогон;
* `.claude/settings.local.json` — закрыт `.gitignore:49`;
* пользовательские `~/.claude/CLAUDE.md`, настройки, memory и skills: `HOME`
  сохраняется даже в чистом режиме (`claude_runner.py:236` `_CLEAN_ENV_KEEP`).

Три первых пункта в git и потому фиксируемы; два последних — вне репозитория и
принадлежат учётной записи машины. Ни один из пяти не входит ни в
`prompt_bundle_hash`, ни в `prompt_sha256`: последний считается по тексту,
который **мы** собрали, а ambient-контекст добавляет CLI уже после нас.

Отдельная развилка того же рода: `config.py:65`

```python
PROMPTS_DIR = Path(os.environ["AUDIT_PROMPTS_DIR"]).resolve() if os.environ.get("AUDIT_PROMPTS_DIR") else DATA_DIR / "prompts"
```

— одной переменной окружения весь корпус промптов подменяется на внешний
каталог. Для воркера это правильно и осознанно (там лежит снимок из пакета,
чей хеш сверяет центр, `task_builder.py:130-137`), но означает, что «промпты
этого прогона» нельзя установить по чекауту — только по окружению процесса.

### 3.5. Версионирование промптов: что есть

Четыре механизма, ни один из которых не решает задачу целиком.

**(а) `prompt_sha256` — отпечаток собранного текста.** Считается только на
provider-adapter транспорте: `claude_runner.py:1053`, `:1434`, `:1915`,
`provider_json_stage.py:291,304`, `gemma_findings_only.py:1416`. Пишется в
`_output/<stage>_provider_run.json` (`claude_runner.py:1079`, `:1464`, `:1718`,
`:1912`) вместе с `prompt_build` — картой состава промпта
(`instructions_chars`, `payload_chars`, `prompt_chars`, `images_attached`).
Ограничение честно объявлено в самом коде (`provider_json_stage.py:310-313`):
промпт и ответ в отчёт не кладутся, потому что это документ заказчика;
остаются только отпечатки — `prompt_sha256` для запроса и
`provider_result.raw_sha256` для ответа. Это **ближайший существующий аналог
`ModelCallRecord`** из ADR-0013 §3.

Но `prompt_sha256` — отпечаток *конкретного вызова по конкретному проекту*, а
не идентификатор редакции шаблона: два прогона одного шаблона по разным
документам дадут разные значения, и по нему нельзя узнать, какая редакция
`.md` применялась.

**(б) `prompt_bundle_hash` — sha256 набора файлов.** Существует только на пути
распределённого аудита. Считает центр
(`services/distributed_workers/audit_job_service.py:249`
`project_package.hash_files(prompts)`), везёт в задании (`:565`), воркер
пересчитывает и **падает** при расхождении
(`backend/app/pipeline/remote_audit_runner.py:711-721`:
`SystemExit("Снимок конфигурации не совпадает с заявленным: …")`).

Два ограничения. Первое: снимок **исключает профили дисциплин** —
`project_package.py:490` `PROMPT_SNAPSHOT_EXCLUDED_TOP_DIRS = frozenset({"disciplines"})`,
и это осознанное решение (иначе хеш менялся бы от правки чужого раздела);
применённый профиль едет отдельно со своим `discipline_profile_hash`. Второе: в
манифест **результата** `prompt_bundle_hash` не выгружается — он живёт в
`run_spec.json` на воркере.

**(в) `_sync.json` — MD5 русских шаблонов.** Единственный хеш содержимого
файла промпта в репозитории: `prompts/pipeline/en/_sync.json`, поле `ru_hash`,
считается `hashlib.md5` (`task_builder.py:159-161`). Это трекер рассинхрона
RU→EN, а не версия.

**И он устарел целиком.** Сверка записанных хешей с фактическими; каталог
`prompts/**` между срезами не менялся, поэтому результат тот же и на `6dc3aadf`:

| Шаблон | `ru_hash` в `_sync.json` | фактический MD5 | совпадение |
| --- | --- | --- | --- |
| `text_analysis_task.md` | `f70dddca…` | `c2c0c159…` | **нет** |
| `block_analysis_task.md` | `73d8e880…` | `03648636…` | **нет** |
| `findings_merge_task.md` | `67e9e530…` | `031240a8…` | **нет** |
| `optimization_task.md` | `a3b2c9aa…` | `3c5d02e7…` | **нет** |
| `optimization_critic_task.md` | `ef578d22…` | `29e997f5…` | **нет** |
| `optimization_corrector_task.md` | `d03385d1…` | `a2442ecf…` | **нет** |
| `norm_verify_task.md` | `018f9b9e…` | `227b742e…` | **нет** |
| `norm_fix_task.md` | `db923316…` | `6a84a53d…` | **нет** |

Восемь из восьми. При этом у всех записей стоит `"synced": true`, а
`check_template_sync()` (`task_builder.py:228-250`) сравнивает хеш и вернёт
`synced: false` — то есть **английский текст, реально уходящий в модель, есть
перевод русского оригинала, которого больше не существует**. Никакого гейта на
этом нет: результат `check_template_sync` отдаётся в UI
(`GET /api/audit/templates/sync`, `backend/app/api/routers/audit.py:643`) и
ничего не блокирует.

**(г) Ручные строки `prompt_version`.** Четыре штуки, инкрементируются руками и
с содержимым файла не связаны:
`block_analysis/provenance.py:23` `STAGE01_PROMPT_VERSION = "stage01-findings-evidence-v3"`
(и алиас `STAGE02_PROMPT_VERSION` на `:25`),
`stage_comparison/project_change_summary.py:19`,
`stage_comparison/text_ai_reviewer.py:21`,
`findings/rejected_audit_service.py:106` `AUDIT_CONTRACT_VERSION`.
`STAGE01_PROMPT_VERSION` доезжает до `03_findings.json` — в
`provenance.detections[].prompt_version` (`provenance.py:92`).

### 3.6. Промпт — изменяемое рантайм-состояние

Пять HTTP-эндпоинтов правят промпты на живой машине:

| Эндпоинт | Обработчик | Что пишет на диск |
| --- | --- | --- |
| `PUT /api/audit/templates/{stage}` | `audit.py:615-625` → `task_builder.py:383` | `prompts/pipeline/ru/{stage}_task.md` + `synced:false` |
| `PUT /api/audit/templates/{stage}/en` | `audit.py:629-639` → `task_builder.py:207` | `prompts/pipeline/en/{stage}_task.md` + перезапись `_sync.json` |
| `GET /api/audit/templates/sync` | `audit.py:643-656` | — (чтение статуса) |
| `PUT /api/audit/{project_id}/prompts/{stage}` | `audit.py:837-847` → `task_builder.py:281` | `<version>/_output/prompt_overrides.json` |
| `DELETE /api/audit/{project_id}/prompts/{stage}` | `audit.py:850-857` | сброс override |

Разрешённые к правке этапы — `text_analysis`, `block_analysis`,
`findings_merge`, `optimization` (`audit.py:618`). Override применяется в
`task_builder.py:579, 1259, 1330, 1519` и `claude_runner.py:924, 1318`.
Реестр дисциплин тоже правится из API — четыре эндпоинта в
`backend/app/api/routers/projects.py:54,69,83,90` пишут
`prompts/disciplines/_registry.json`.

Итог: **правка через API переписывает версионируемый файл в рабочей копии без
коммита, без автора, без метки времени и без хеша до/после.** Старое значение
`ru_hash` затирается, история правок из UI не восстанавливается ни из
репозитория, ни из артефактов. В распределённом режиме `prompt_bundle_hash`
считается от текущего состояния каталога на момент сборки пакета
(`audit_job_service.py:232`) — то есть правка из UI молча меняет хеш задания.

Обратная сторона: файл `prompt_overrides.json` лежит в `_output/`, который
закрыт `.gitignore:25`. Промпт, которым реально сделан аудит проекта, может
физически отсутствовать где-либо, кроме боевого диска.

### 3.7. Промпты: что фиксировать

| Что | Метка | Как фиксировать |
| --- | --- | --- |
| Содержимое `prompts/**` | фиксируемо | `hash_files()` уже написан (`project_package.py:569`); эталон корпуса на срезе — `445584a0b8d28b52355d8717dd90c0863af6e4d7441354f610fd65c3275de966` (`find prompts -type f -print0 \| sort -z \| xargs -0 sha256sum \| sha256sum`) |
| Профиль применённой дисциплины | фиксируемо | `discipline_profile.tree_hash` существует, но только в распределённом контуре |
| Inline-промпты в коде | фиксируемо | сегодня — только git-ревизией кода; отдельного отпечатка нет |
| Собранный текст запроса | фиксируемо | `prompt_sha256` существует на provider-пути; на трёх остальных транспортах не считается |
| Per-project override | фиксируемо | файл есть, отпечатка нет, в git не попадает |
| Ambient-контекст CLI: `CLAUDE.md`, `AGENTS.md`, `.claude/settings.json` | фиксируемо | в git; но не входит ни в один отпечаток, и загружается по умолчанию (§3.4) |
| Вывод `SessionStart`-хука со статусом проектов | **нефиксируемо** | живые данные, меняются каждый прогон |
| `~/.claude/**` учётной записи машины | **нефиксируемо** | вне репозитория, принадлежит окружению |
| Каталог промптов, выбранный `AUDIT_PROMPTS_DIR` | фиксируемо | нужно записывать значение, а не только содержимое чекаута |
| `_sync.json` как признак актуальности | **не работает** | 8/8 записей устарели; механизм ничего не гарантирует |

## 4. Нормы как вход модели

### 4.1. Два независимых нормативных источника

Продукт держит **два не связанных между собой корпуса**, и рассинхрон между
ними ничем не ловится:

1. **Рукописный справочник дисциплины** — `prompts/disciplines/<КОД>/norms_reference.md`,
   14 файлов по 8–28 КБ, с таблицами «документ / название / статус / редакция»
   (пример: `EOM/norms_reference.md:16` — «СП 256.1325800.2016 … ред. 29.01.2024,
   с изм. 1-6»). **Уходит в system-промпт Stage 01 целиком и дословно.**
2. **Машинный корпус** — `norms/**`: `norms_db.json` (1252 нормы + 181 замена),
   `norms_paragraphs.json` (122 подтверждённые цитаты), `vault/*.md` (тексты),
   `status_index.json` (индекс статусов), `paragraphs.jsonl`, `embeddings.npz`.
   Используется детерминированной верификацией и MCP-инструментами.

### 4.2. Что уходит в промпт

| Что именно | Откуда | Куда | Точка кода |
| --- | --- | --- | --- |
| Полный текст `norms_reference.md` дисциплины (8–28 КБ) | `prompts/disciplines/<КОД>/` | Stage 01 system | `prompt_builder.py:529-531` |
| Полный текст `checklist.md` дисциплины | там же | Stage 01 и Stage 02 system | `discipline_service.py:331` |
| `role.md` дисциплины | там же | Stage 01/02/merge/optimization | `discipline_service.py:330` |
| `status`, `replacement_doc`, `notes[:500]`, `last_verified` по каждой найденной норме | `norms/norms_db.json` | targeted-проход `alia_docnorm_audit`, блок «LOCAL VERIFIED NORM STATUS» | `codex_targeted_findings.py:319-347, 632-638` |
| Перечень позиций для сверки цитат | резолв по `status_index.json` | Stage 04 system+user | `norms/_core.py:1022-1079`, `prompt_builder.py:820-827` |
| Буквальные тексты пунктов и таблиц (`norm_context`) | `norms/vault/*.md` через `norms_api` | повторный аудит отклонённых | `rejected_audit_service.py:980-1252, 4868` |
| Прошлые вердикты эксперта | `knowledge_base/decisions_log.json` | KB-gate (ручной запуск из API) | `critic_v2/kb_gate.py:92-107, 126-146` |
| **Норм не уходит** | — | Stage 02 block_analysis, findings_merge, optimization | `prompt_builder.py:656-735, 742-797, 869-937` |

Отдельная развилка: `prompts/pipeline/en/findings_merge_task.md:26` сообщает
модели, что нормативный справочник «provided in system context», а код его туда
не кладёт. Шаблон и код расходятся.

Ключевой факт для воспроизводимости: `_read_norms_reference`
(`prompt_builder.py:290`) читает файл **на каждой сборке промпта**, содержимое
не кэшируется. Правка одной строки в справочнике меняет байты system-промпта
Stage 01 при следующем же прогоне.

### 4.3. Состояние корпуса и его фиксация

Что в git: `norms_db.json`, `norms_paragraphs.json`, `paragraphs.jsonl` (56 МБ),
`embeddings.npz`, `status_overrides.yaml`. Что вне git и **в этом чекауте
физически отсутствует**: `norms/vault/` (`.gitignore:109`),
`norms/tools/status_index.json` (`.gitignore:117`), `norms/tools/venv/`
(`.gitignore:115`). То есть authoritative-часть корпуса здесь не выбрана;
`ci_provision_norms.corpus_state()` отвечает
`{"provisioned": false, "reason_code": "OPTIONAL_NORM_CORPUS_ABSENT"}`.

Внутри пакета `norms/` версионирования корпуса как целого нет: ни
`corpus_version`, ни `norms_version`, ни `revision`. Есть только `meta`:

```json
"last_updated": "2026-05-06T14:33:25", "total_norms": 1252,
"stale_after_days": 180, "update_history": [ … 7 записей … ]
```

`update_history` показывает происхождение записей — импорты из PDF-библиотек,
ручные правки по карточкам Росстандарта и **`"source": "websearch:2026-05-06"`,
99 обновлённых норм**. Хеша содержимого в истории нет, дифф не сохраняется,
откат возможен только через git.

Механизм фиксации существует, но **вне** пакета `norms/`:
`scripts/ci_runtime_probe.py:1138-1146` `_norm_artifact_digest(vault)` считает
детерминированный SHA-256 всего дерева vault, эталон берётся из
`QR_NORM_ARTIFACT_SHA256` либо `norms/vault.sha256`;
`scripts/ci_provision_norms.py` раскладывает vault **только** после совпадения
контрольной суммы, требует именованную версию артефакта (безымянный «latest»
отвергается) и пишет `norm_artifact_sha256` и `status_index_sha256` в отчёт.
`scripts/ci_regression_gate.py:279-306` отказывает в `--record` без
provisioned-корпуса.

Чего нет: **отпечатка корпуса в артефакте прогона.** `norm_checks.json → meta`
несёт `index_state` (`ok|absent|broken`), `check_date`, счётчики — но ни хеша,
ни числа записей индекса. Прогон на индексе из 565 норм и на индексе из 600 даёт
байт-идентичное `index_state: "ok"`.

### 4.4. Стадия верификации норм не ходит в интернет

Это важно и это подтверждено в четырёх местах: `norms/external_provider.py:7`
(«WebSearch / WebFetch / интернет здесь запрещены концептуально»),
`stages/norms/runner.py:522` (лог «WebSearch запрещён»),
`prompts/pipeline/ru/norm_verify_task.md:11-15` (раздел «Запрещено»),
`norms/_core.py:1091,1108-1109` (значение `websearch` в `verified_via` считается
нарушением политики). Fast path — чистый Python offline
(`norms/_native_verify.py`, word-Jaccard 0.30 + числовая сверка); fallback при
исключении — `claude` с MCP-сервером норм, не с веб-поиском.

Оговорка: `update_history` в `norms_db.json` показывает, что **корпус
пополнялся через WebSearch руками** (`websearch:2026-05-06`, 99 норм). Стадия
не ходит в сеть; человек с корпусом — ходил.

### 4.5. Нормы: что фиксировать

| Что | Метка | Комментарий |
| --- | --- | --- |
| `norms_db.json`, `norms_paragraphs.json` | фиксируемо | в git; отпечаток можно взять git-blob или sha256 |
| `norms/vault/**` | фиксируемо | механизм готов (`_norm_artifact_digest` + версионированный артефакт); в этом чекауте не применён |
| `status_index.json` | фиксируемо | детерминированно собирается из vault; `status_index_sha256` считается |
| `norms_reference.md` дисциплины — **главный вход промпта** | фиксируемо | но сегодня не покрыт **ничем**, кроме git-истории и `discipline_profile.tree_hash` в распределённом контуре |
| Состояние корпуса в артефакте прогона | фиксируемо | поля в `norm_checks.json.meta` нет; добавить — работа `W1-AI-01` |
| Фактический статус нормы в реальном мире | **нефиксируемо** | норму отменяют вне нас; наш снимок стареет, `stale_after_days: 180` это признаёт |
| `decisions_log.json` (вердикты эксперта в KB-gate) | фиксируемо | не версионируется, растёт от прогона к прогону |

## 5. Маршрутизация

### 5.1. Провайдеры

Канонический реестр — `backend/app/services/audit_routing/registry.py:31-43`:
`claude`, `codex`, `openrouter`. Фактически вызываются пять адресатов:

| Провайдер | Транспорт | Где |
| --- | --- | --- |
| OpenRouter | `openai.AsyncOpenAI` | `services/llm/llm_runner.py:90-98` |
| OpenRouter (Stage 01/02) | `httpx` | `stages/block_analysis/gemma_findings_only.py:96,1556` |
| Claude Code CLI (подписка) | `subprocess` | `services/llm/claude_runner.py:206-224` |
| Codex exec CLI (подписка) | `subprocess` | `services/llm/codex_runner.py:638-660, 763-790` |
| Gemini Direct | `google-genai` | `services/llm/gemini_direct_runner.py`, вход `claude_runner.py:2573` |

Gemini Direct в реестре маршрутизации отсутствует и достижим только по прямому
условию `is_gemini_direct_model(model) and GEMINI_DIRECT_API_KEY`; ни одного
`gemini-*` идентификатора нет в `AVAILABLE_MODELS` (`config.py:561-568`) —
ветка практически мертва, но код жив.

### 5.2. Таблица моделей лежит вне git и расходится с кодом

Живой файл `backend/app/data/stage_models.json` — **`.gitignore:187`**, и его
комментарий в коде честен: «Файл вне git, и без него прогон пойдёт не на тех»
(`project_package.py:515`). Содержимое на срезе:

```json
{"text_analysis":"openai/gpt-5.4","block_batch":"openai/gpt-5.4",
 "findings_merge":"openai/gpt-5.4","findings_critic":"openai/gpt-5.4",
 "findings_corrector":"openai/gpt-5.4","norm_verify":"openai/gpt-5.4",
 "norm_fix":"openai/gpt-5.4","norm_requote":"openai/gpt-5.4",
 "optimization":"openai/gpt-5.4","optimization_critic":"openai/gpt-5.4",
 "optimization_corrector":"openai/gpt-5.4"}
```

Дефолты кода (`config.py:276-288`) говорят другое: `text_analysis`,
`findings_merge`, `findings_critic`, `findings_corrector`, `norm_*` —
`claude-opus-5`; `block_batch` — `ensemble/gpt-codex`; `optimization` —
`ensemble/claude-codex-opt`; `optimization_critic/corrector` —
`claude-sonnet-5`. **Расхождение по всем одиннадцати стадиям.**

Из этого следует прямое требование к воспроизводимости: `stage_models.json`
обязан входить в снимок прогона. Он туда и входит — но только на пути
распределённого аудита (`collect_model_config_snapshot`, `model_config_hash`).
Для локального прогона таблица не фиксируется нигде.

Отдельно: `docs/blocks_and_stage02.md:20` объявляет Stage 02 модель
`openai/gpt-5.4` — совпадает с живым файлом и расходится с дефолтом кода
(`ensemble/gpt-codex`).

### 5.3. Пять конкурирующих источников решения

`backend/app/core/config.py:642-672`:

```python
def get_stage_model(stage: str) -> str:
    stage_key = "block_batch" if stage.startswith("block_batch") else stage
    try:
        from backend.app.services.audit_routing import center_models
        planned = center_models.stage_model_from_plan(stage_key)
    except Exception:                      # fail-soft НАМЕРЕННО
        planned = ""
    if planned:
        return planned
    return STAGE_MODEL_CONFIG.get(stage_key, "openai/gpt-5.4")
```

Пятый источник в этот код не заходит вовсе и разобран отдельно в §5.7: стадия
может задать модель литералом и не спросить `get_stage_model` ни разу. Первая
редакция считала источников четыре, потому что не знала о нём.

Приоритет остальных четырёх: **замороженный план прогона** (11J,
`services/audit_routing/`, 3029 строк — `plan`, `compiler`, `presets`,
`registry`, `validator`, `budget`, `active_plan`) → **глобальный мутабельный
словарь процесса** `STAGE_MODEL_CONFIG` (грузится один раз на импорте,
`config.py:359-385`) → **файл** → **дефолт-литерал `"openai/gpt-5.4"`**.
Плюс UI-ручка `POST /api/audit/model/stages` (`audit.py:155-186`), пишущая
сразу в три места и сохраняющая файл. `project_info.json` в выборе **не
участвует**.

Замороженный план — единственный настоящий механизм воспроизводимости
маршрута. Он же несёт собственное ограничение, объявленное машинно:
**план по контракту не имеет права содержать точный идентификатор модели.**
`registry.py:325-340` держит `_EXACT_MODEL_PATTERNS` — regexp'ы
`claude-(opus|sonnet|haiku)`, `gpt-\d`, `codex/`, `openai/`, `gemini-\d`,
`gemma` — и проверяет ими **все** значения плана. План несёт пару «провайдер +
способность» (`strong_audit` / `cheap_review`), точную модель разрешает
принимающая сторона: центр — `center_models.model_for()`, воркер —
`audit_worker/providers/model_policy.py` по локальной политике с
`AUDIT_WORKER_PROVIDER_POLICY_SHA256` и `AUDIT_WORKER_PROVIDER_POLICY_VERSION`.

Практический вывод: **по замороженному плану нельзя восстановить, какая модель
отвечала**. Нужно записывать ещё и политику исполнителя.

### 5.4. Fallback: маршрут недетерминирован

Двенадцать переключений, из них два молчаливых и оба ведут в платный
OpenRouter:

| # | Где | Условие | Куда | Молча? |
| --- | --- | --- | --- | --- |
| F1 | `stages/block_analysis/runner.py:645-651` | модель не в белом списке | `openai/gpt-5.4` | лог `warn` |
| F2 | `config.py:672` | ключа стадии нет в таблице | `openai/gpt-5.4` | **да** |
| F3 | `config.py:668` | `except Exception` при чтении плана | глобальная таблица | **да** |
| F4 | `config.py:520-541`, `gemma_findings_only.py:2762-2776` | нога ансамбля упала | блок засчитан успешным, если ответила хоть одна; останов только при `STAGE01_ABORT_ON_LEG_FAILURE_ENABLED` (**default off**) | да |
| F5 | `codex_runner.py:149-215` | транзиентная ошибка | 2 повтора, та же модель | нет |
| F6 | `llm_runner.py:362-391` | rate limit / timeout | 3 повтора с backoff | нет |
| F7 | `claude_runner.py:575-597` | сломанный JSON от codex | повтор разбора | нет |
| F8 | `stages/text_analysis/runner.py:171-225` | rate limit Claude | ожидание сброса + backoff | нет |
| F9 | `stages/block_analysis/dual_review.py:453-468` | сбой семантического review | детерминированная аннотация, `status="fallback"` | пишется в артефакт |
| F10 | `services/discussions/discussion_service.py:581,760` | модель `claude-cli` | компрессия уходит на `google/gemini-2.5-pro` | да |
| F11 | `gemini_direct_runner.py:586-600` | 429/503/timeout | повтор с backoff | нет |
| F12 | `stages/block_analysis/runner.py:637-643` | активен provider bridge | модель `provider/worker-policy`, `stage_models.json` игнорируется | лог `info` |

**Fallback между провайдерами при исчерпании лимита отсутствует** — это хорошо
для детерминизма: `codex_runner.py:62-73` относит `usage limit reached`,
`quota`, `billing` к неповторяемым, стадия падает, а не мигрирует на другого
поставщика.

### 5.5. Где записан фактический выбор

| Артефакт | Что о модели | Ревизия |
| --- | --- | --- |
| `_output/audit_trail/<stage>_<ts>.json` | `stage`, `model`, `timestamp`, токены, `duration_ms`, `result` (`claude_runner.py:121-129`) | нет |
| — payload OpenRouter | плюс `finish_reason`, `response_id`, `reasoning_tokens`, `cost_source` (`claude_runner.py:137-148`) | нет |
| `01_blocks_analysis.json → stage01_meta` | `model`, `run_id`, `prompt_version`, `detectors[]`, `reasoning_effort` (`gemma_findings_only.py:3279-3296`) | нет |
| `03_findings.json` | провенанс по `detector`, не по строке модели (`provenance.py:76+`) | нет |
| `pipeline_log.json` | `model`, токены (`manager.py:1162`) | нет |
| `backend/app/data/usage_data.json` | `model`, токены, `cost_usd`, `cache_*_tokens` | нет |
| `backend/app/data/paid_cost_events.jsonl` | `model`, `stage`, `response_id`, токены, `cost_usd` | нет |
| `<stage>_provider_run.json` | `provider_result` (`provider`, `model`, `status`, `usage`, `raw_sha256`), `prompt_sha256` | нет |

**Дефект, который надо знать до проектирования `ModelCallRecord`.** `CLIResult`
(`backend/app/models/usage.py:121-134`) **не имеет поля `model`**. Поэтому в
`manager.py:1055`:

```python
model = getattr(cli_result, "model", "") or get_model_for_stage(stage)
```

для CLI-стадий всегда срабатывает правая ветка, а `get_model_for_stage`
(`config.py:707-713`) читает **legacy-словарь** `_stage_models`
(`config.py:262-274`), который UI-ручка синхронизирует только для `claude-*`.
То есть в `usage_data.json` и `pipeline_log.json` для CLI-стадий записывается
не та модель, что реально исполняла запрос.

Единственное место, где отчитанная провайдером модель сверяется с ожидаемой, —
воркер: `audit_worker/providers/claude_adapter.py:1032-1065` разбирает
`modelUsage` из `--output-format json` и сверяет с `accepted_reported_models`
(`model_policy.py:146-163`).

### 5.6. Что провайдер о себе сообщает: замер по записанным ответам

В git лежат 12 записанных прогонов шести моделей
(`experiments/stage_comparison_text_ai_reviewer/artifacts/runs/*.json`).
Они дают прямой ответ на вопрос ADR-0013 §3 «раскрывает ли provider точную
revision»:

| Провайдер | `requested_model` | `reported_model` в ответе |
| --- | --- | --- |
| `claude` (3 модели × 2 режима) | `claude-opus-5`, `claude-sonnet-5`, `claude-fable-5` | тот же алиас, дословно |
| `codex` (3 модели × 2 режима) | `gpt-5.6-sol`, `gpt-5.6-luna`, `gpt-5.6-terra` | **поле пустое** |

Никакой ревизии ни один провайдер не отдаёт. Максимум — эхо запрошенного
алиаса, и то не всегда. **Это факт, а не пробел инвентаря.**


### 5.7. Новая точка вызова модели, найденная перепроверкой: Stage 5.3

Первая редакция снималась на срезе, где файла
`backend/app/services/stage_comparison/high_level_project_changes.py` ещё не
существовало. На каноне это **восьмая** точка вызова модели, и ни одно из
правил §5.1–§5.3 её не описывает.

| Что | Значение | Где |
| --- | --- | --- |
| Транспорт | `codex exec` через `subprocess`, JSON-режим | `store.py:1200` → `codex_runner.py:709` |
| Модель | литерал `gpt-5.6-luna` | `project_change_summary.py:21` |
| `reasoning_effort` | литерал `medium` | `project_change_summary.py:22` |
| Структурированный вывод | `--output-schema` из `RESPONSE_SCHEMA` | `high_level_project_changes.py:129`, передача `store.py:1207` |
| Инструменты | запрещены явно (`allowed_tools=""`) | `store.py:1208` |
| Таймаут | 240 с | `store.py:1202` |
| Идентификатор стадии | `stage_comparison_high_level_project_changes` | `store.py:1203` |

Три следствия, каждое противоречит уже записанному в этом документе.

1. **Модель задана литералом мимо всех четырёх источников решения из §5.3.**
   `stage_models.json` для этой стадии не спрашивается вовсе, `AUDIT_CODEX_MODEL`
   (`config.py:479`) на этом пути не применяется: `resolve_codex_model`
   (`config.py:690-695`) получает непустую строку и возвращает её как есть.
   Источников решения о модели, таким образом, не четыре, а пять — пятый
   заключается в том, чтобы не спрашивать никого. Приём не новый: тот же литерал
   `gpt-5.6-luna` зашит в `text_ai_reviewer.py:25` (шаг AI-review внутри J-25) —
   первая редакция описала промпт этого модуля (§3.2), но не его модель.
2. **Промпт — литерал в коде**, `prompts/**` его не содержит:
   `high_level_project_changes.py:153`, 1002 символа, плюс преамбула транспорта
   `codex_runner.py:526-534`. То есть §3.2 недосчитывает один боевой промпт.
3. **Стадия не описана в конфиге моделей**, но её идентификатор уходит в текст
   запроса (`codex_runner.py:527`) и в guard норм (`codex_runner.py:330-350`).

Детерминированная часть здесь существенна и её нельзя опускать: в модель уходят
только группы с маршрутом `AI_REVIEW` (`high_level_project_changes.py:418-449`),
ответ жёстко валидируется (`:521-575`), при провале валидации решение
заменяется fail-closed заглушкой (`:656-663`), а заголовки перезаписываются
бэкендом (`:607-636`). Это ближе к «модель как один из источников», чем к
«модель решает».

## 6. Транспорты

### 6.1. Сводка

Обнаружено 35 точек обращения наружу, из них **22 боевых**.

| Категория | Всего | Есть шов | Шва нет |
| --- | ---: | ---: | ---: |
| HTTP/SDK к LLM, центр (`llm_runner`, `gemma_findings_only`, Gemini Direct) | 3 | 0 | **3** |
| HTTP к LLM, воркер (`openrouter_adapter`) | 1 | 1 | 0 |
| HTTP к локальной модели (`local_vision_provider`, вне прода) | 1 | 1 | 0 |
| CLI-транспорты боевого конвейера | 11 | 11 по бинарю (PATH), **8 без программной точки перехвата** | — |
| Мост и `process_runner` | 2 | 2 | 0 |
| CLI-провайдеры воркера | 3 | 3 | 0 |
| MCP | 3 | 2 | 1 |
| gRPC / data plane воркера | 1 | 1 | 0 |
| Скрипты и эксперименты | 10 | 6 | 4 |
| **Итого** | **35** | **27** | **8** |

**Шва для подмены целевого URL нет у пяти боевых транспортов:** `llm_runner`
(`AsyncOpenAI`), `gemma_findings_only` (`httpx`), Gemini Direct (base URL внутри
SDK), ambient MCP по `.mcp.json`, и, как следствие первых двух, весь
центральный OpenRouter-контур.

### 6.2. Четыре независимых литерала одного и того же адреса

| Файл:строка | Клиент | Значение |
| --- | --- | --- |
| `backend/app/core/config.py:784` | `openai.AsyncOpenAI` | `"https://openrouter.ai/api/v1"` |
| `backend/app/pipeline/stages/block_analysis/gemma_findings_only.py:96` | `httpx` | `"https://openrouter.ai/api/v1/chat/completions"` |
| `backend/app/pipeline/stages/findings_review/critic_v2/llm_gate.py:1584` | `requests` | тот же адрес |
| `audit_worker/providers/openrouter_adapter.py:102` | `httpx` | `OFFICIAL_BASE_URL`, **и он переопределяем** |

Только четвёртый сделан правильно: `resolve_base_url()`
(`openrouter_adapter.py:155-201`) читает
`AUDIT_WORKER_PROVIDER_OPENROUTER_BASE_URL`, принимает неофициальный хост
**только** при явном `AUDIT_WORKER_PROVIDER_ENDPOINTS_STUBBED=true`, и это
объявление уезжает в heartbeat центру. Это готовый образец шва для остальных
трёх.

### 6.3. Расхождение конфигурации и кода: прокси, которого нет

`.env` этого чекаута объявляет `AI_PROVIDER_MODE=proxy`,
`PROXY_LLM_BASE_URL=…`, `OPENROUTER_BASE_URL=…`, `PROXY_LLM_IDEMPOTENCY_VERSION=v1`.

```
$ grep -rn "PROXY_LLM\|AI_PROVIDER_MODE" --include='*.py' backend/ audit_worker/ scripts/
(пусто)
```

`OPENROUTER_BASE_URL` в коде — литерал (`config.py:784`), env не читается.
Оператор считает, что трафик идёт через прокси; трафик идёт прямо в OpenRouter.
Для инвентаря важно двоякое: во-первых, это дефект наблюдаемости; во-вторых,
это доказательство, что **env-override базового URL в центре не существует даже
там, где его пытались задать**.

### 6.4. `claude -p` мимо централизованного хелпера

`claude_runner._run_cli` (`claude_runner.py:310`) — заявленная единая точка. Мимо
неё в боевом коде идут:

| Модуль:строка | Механизм | Боевой? |
| --- | --- | --- |
| `stages/text_analysis/absence_guard.py:314` | `subprocess.run` | да (страж отсутствия Stage 01) |
| `stages/findings_review/critic_v2/kb_gate.py:174` | `subprocess.run` | **да** — достижим из `POST /api/findings/…` через `kb_validation_service.py:79` |
| `stages/findings_review/critic_v2/llm_gate.py:1465` | `subprocess.run` | нет (скрипты/тесты) |
| `services/findings/decision_carryover_service.py:335` | `subprocess.run` | да (J-13) |
| `services/findings/migrated_findings_service.py:1233` | `subprocess.run` | да |
| `services/discussions/discussion_service.py:435,656` | `process_runner.run_command` / `run_command_stream` | да |
| **`stages/block_analysis/gemma_findings_only.py:1842`** | `asyncio.create_subprocess_exec`, бинарь из `CLAUDE_CLI_BIN` (`:268`) | **да**, в §5.3 каталога journeys не назван |
| **`services/external_register/matcher.py:187`** | `run_command` | **да** (J-22), не назван |
| **`api/routers/audit.py:230,269,281`** | `claude auth status/logout/login` | да, управляющий канал, не назван |

То есть обходов не шесть, а девять, и три из них — боевые. Подстановка бинаря в
`PATH` (`backend/app/pipeline/execution/fake_providers.py::materialize`) накрывает
все; программной подмены нет ни у одного.

### 6.5. MCP

`.mcp.json` в корне описывает два stdio-сервера: `playwright` (инструмент
разработки) и `norms`, и путь последнего — `/home/coder/projects/PDF-proverka/…`,
то есть **абсолютный путь чужого чекаута**; в этом дереве он нерабочий.
`claude -p` подхватывает сервер ambient — по рабочему каталогу, `--mcp-config`
не передаётся никогда (`claude_runner.py:201-224`); `--strict-mcp-config`
добавляется только когда в наборе инструментов нет `mcp__`. `codex exec`,
наоборот, инъектирует сервер явно (`codex_runner.py:388-396`) и имеет
объявленную точку подмены для тестов (`_norms_mcp_python()`, `:290-301`).

### 6.6. Какой именно бинарь исполняет запрос

Центр разрешает путь к CLI один раз на импорте — `config.py:204`
`CLAUDE_CLI = _find_claude_cli()`. Лестница поиска (`config.py:175-203`):
`which("claude")` → `PATH` + `~/.local/bin` → **скан расширений VSCode** →
`~/.local/bin/claude`, `/usr/local/bin/claude` → npm-пути → строка `"claude"`.

Третья ступень заслуживает отдельного внимания. `_scan_vscode_claude()`
(`config.py:150-172`) собирает все `anthropic.claude-code-*` из
`~/.vscode-server/extensions` и `~/.vscode/extensions` и берёт **самый свежий
по mtime каталога**:

```python
        candidates.append((mtime, str(binary)))
    ...
    candidates.sort(reverse=True)
    return candidates[0][1]
```

То есть автообновление расширения редактора молча меняет бинарь, которым
исполняются LLM-этапы, а ни версия, ни отпечаток этого бинаря в артефакты
локального прогона не попадают.

Контрпример из того же дерева показывает, что делать правильно умеют:
`backend/app/services/worker_bootstrap/remote.py:611,666` держит
`pins = {"claude": "2.1.220", "codex": "0.147.0"}`, проверяет SHA-256 артефакта
и отказывает кодом `cli_version_unpinned`; в комментарии рядом сказано, что
bootstrap «не исполняет `curl | sh` и не знает слова `latest`». Механизм
существует, но применяется только на пути установки воркера.

### 6.7. Транспорты: что фиксировать

| Что | Метка | Комментарий |
| --- | --- | --- |
| Адрес, куда ушёл запрос | фиксируемо | сегодня не записывается ни в один артефакт |
| Путь и отпечаток бинаря CLI | фиксируемо | центр выбирает по mtime расширения VSCode (§6.6) и ничего не записывает |
| Версия CLI (`claude`, `codex`) | фиксируемо | `cli_version` собирается воркером (`providers/identity.py:178`, `quota.py:244`) и уезжает в снимок провайдера; на пути bootstrap версии даже пиннуются; **в артефакт прогона не попадает**, у центра не собирается вовсе |
| Версия SDK (`openai`, `httpx`, `google-genai`) | фиксируемо | `requirements.txt` держит `>=` (`openai>=1.60.0`), `constraints-qr-v1.txt` пинует точные (`openai==3.3.1`) — два разных ответа в одном дереве |
| Поведение CLI при самообновлении | **нефиксируемо** | `claude`/`codex` обновляются вне нашего контроля; фиксируется только наблюдённая версия |
| Доступность MCP-сервера норм | фиксируемо | fail-closed уже есть (`assert_norms_mcp_available`) |


### 6.8. Политика повторов OpenRouter

На каноническом срезе Stage 01/02 больше не вызывает шлюз напрямую. Вызов
обёрнут в `_post_openrouter_with_transient_retry`
(`gemma_findings_only.py:161`), точка вызова — `:1556`. Первая редакция описывала
прямой `client.post`, и это утверждение устарело.

| Параметр | Значение | Где |
| --- | --- | --- |
| Число дополнительных попыток | по умолчанию 2, env `STAGE01_OPENROUTER_TRANSIENT_RETRIES`, зажато в 0…5 | `gemma_findings_only.py:109,112,118-126` |
| Базовая пауза | по умолчанию 2.0 с, env `STAGE01_OPENROUTER_RETRY_BASE_DELAY_S`, зажата в 0…60 | `:110,113,128-136` |
| Что считается временным отказом | статусы 408, 409, 429 и любой ≥500, плюс транспортные исключения | `:114,148-149` |
| Пауза | `base * 2^(n-1)` плюс джиттер `random.uniform(0, delay*0.5)` | `:232-233` |
| `Retry-After` | числовой заголовок **заменяет** вычисленную паузу, зажат в 0…60 с | `:150-158,235` |
| Полный транспортный таймаут | повторяется не больше одного раза | `:226` |

Для инвентаря важны три вещи, и ни одна не про производительность.

- **Джиттер берётся из незасеянного `random`** (`:37,233`). На ответ модели это
  не влияет, на длительность и на порядок параллельных вызовов — влияет.
- **Число фактических обращений к платному шлюзу перестало быть равным единице**
  и записывается в метаданные вызова (`attempts`, `retry_count`,
  `retry_errors`, `:219-224`). Это прямо касается `B_cost` из roadmap §5.1:
  один логический вызов теперь может стоить как три.
- **Аналогичная политика у Codex-транспорта существовала и раньше** —
  `CODEX_TRANSIENT_RETRIES` и `CODEX_TRANSIENT_RETRY_BASE_DELAY_S`
  (`codex_runner.py:53-56,102-115`, джиттер `:208,215`). Первая редакция её не
  назвала; это пропуск инвентаря, а не изменение кода: между срезами
  `codex_runner.py` не менялся ни на строку
  (`git diff --name-only bff35d7d 6dc3aadf -- backend/app/services/llm` пуст).

## 7. Параметры модели

### 7.1. Таблица

| Параметр | Где | Значение | Детерминирован |
| --- | --- | --- | --- |
| `temperature` (OpenRouter, все текстовые стадии) | `config.py:1026` `DEFAULT_TEMPERATURE = 0.2`, применение `llm_runner.py:262,350` | `0.2` | **да** — ни один вызов конвейера его не переопределяет |
| `temperature` (Stage 01/02 нога) | `gemma_findings_only.py:1529` | `0.2` литерал | да |
| `temperature` (воркер) | `audit_worker/providers/openrouter_adapter.py:620` | `0.2` литерал | да |
| `temperature` (Claude CLI, Codex CLI) | — | **не передаётся, флага нет** | **нет** — дефолт провайдера |
| `top_p` | — | **нигде** | нет — дефолт провайдера |
| `seed` | — | **нигде** | **нет** — сэмплинг стохастический |
| `max_tokens` (общий OpenRouter) | `llm_runner.py:255-261`, `config.py:1024-1025` | `128000`, для gemini `65536`; выбор по подстроке `"gemini" in model` | частично |
| `max_tokens` (Stage 01/02) | `gemma_findings_only.py:99` | `16000` | да |
| `max_tokens` (воркер) | `openrouter_adapter.py:139` | `16000` | да |
| `max_tokens` (CLI) | — | не передаётся | нет |
| `reasoning_effort` (Stage 01/02, все ноги) | `gemma_findings_only.py:98`, жёстко `stages/block_analysis/runner.py:653` | `"low"`, переопределить нечем | да |
| `reasoning_effort` (Codex-нога оптимизации) | `config.py:493-496`, `stages/optimization/ensemble.py:514` | `"xhigh"`, env | частично |
| `reasoning_effort` (Claude CLI) | `claude_runner.py:320,385` принимает, `_build_cmd:213-224` **игнорирует** | параметр теряется | нет |
| `response_format` / json schema (OpenRouter) | `llm_runner.py:264-278,357` | `json_schema` strict либо `json_object` | да |
| `response_format` (Stage 01/02) | `gemma_findings_only.py:1531` | `json_schema` | да |
| `response_format` (воркер) | `openrouter_adapter.py:632` | `json_object` — **слабее центрального** | частично |
| `--output-schema` (Codex JSON-режим) | `codex_runner.py:755-763,781` | схема во временный файл | да |
| structured output (Claude CLI) | — | **нет вовсе**, только текстовый контракт в промпте | нет |
| `--max-turns` | `audit_worker/providers/claude_adapter.py:166`, `kb_gate.py:158` | `1` | да у воркера; **у центра флага нет** — число ходов не ограничено |
| `timeout` | `config.py:121-124,216-232`; `claude_runner.py:1219,2036,…` | 600 / 1800 / 3600 c по стадиям | да (литералы) |
| `max_retries` | `llm_runner.py:217` = 3, `codex_runner.py:56` = 2 | | частично (env) |
| stop-последовательности | — | нигде | — |

### 7.2. Доказательство отсутствия `seed`

```
$ grep -rn --include='*.py' -w "seed" backend/app audit_worker | grep -v __pycache__ | wc -l
17
```

Все 17 — не про LLM: seed-ячейка flood-fill геометрии
(`block_grounding/ar_ceiling_lighting/spatial.py:171-182`, `rooms.py:103-104`),
seed-строка для `sha1` идентификатора кластера
(`section_optimization_service.py:567-569,715-717`), seed-словарь
`project_info.json` новой версии (`version_service.py:985-1000`), сообщение об
ошибке копирования входов (`manager.py:2361`). Полные списки параметров
запроса — `llm_runner.py:346-360`, `gemma_findings_only.py:1525-1534`,
`openrouter_adapter.py:616-635`, `gemini_direct_runner.py:556-572` — `seed` не
содержат.

### 7.3. Что из параметров попадает в запись прогона

Только `reasoning_effort` — в `01_blocks_analysis.json → stage01_meta`
(`gemma_findings_only.py:3291`), в `summary` (`:3420`) и в имя каталога прогона
`_stage01_findings_only_runs/<ts>__<model>_<effort>` (`:2357`).
`temperature`, `max_tokens`, `response_format`, `timeout`, `top_p`, `seed`
не записываются нигде. По готовому артефакту нельзя восстановить параметры
вызова даже задним числом.

### 7.4. Параметры: что фиксировать

| Что | Метка |
| --- | --- |
| `temperature`, `max_tokens`, `response_format`, `timeout`, `reasoning_effort` | **фиксируемо** — значения уже жёсткие в коде, надо лишь записывать их в `ModelCallRecord` |
| `seed` на HTTP-транспортах | **фиксируемо** — параметр поддерживается провайдерами, у нас просто не задаётся |
| Параметры CLI-транспортов (`claude -p`, `codex exec`) | **нефиксируемо** — интерфейс CLI их не принимает; исключение `model_reasoning_effort` у codex |
| Сам факт детерминизма при фиксированных параметрах | **нефиксируемо** — `temperature=0` и `seed` не гарантируют побайтовое совпадение у облачного провайдера |

## 8. Mutable sources — сводный реестр

Полный перечень того, что меняет ответ и способно измениться между прогонами
незаметно. Колонка «метка» — по правилу §2, уточнённому для непреодолимых
позиций четырьмя классами §10.1. **Пятьдесят восемь позиций в восьми группах:**
пятьдесят одна от сплошного прохода первой редакции и семь, добавленных
перепроверкой на каноне (§8.8). Две из первых (№45 и №48) — явные отрицания:
там, где источник недетерминизма ожидался, его нет, и это тоже результат
инвентаря. Метку с корнем «нефиксируем» несут пятнадцать строк, все — из
первой полусотни.

### 8.1. Модель и провайдер

| # | Источник | Где | Метка | Комментарий |
| ---: | --- | --- | --- | --- |
| 1 | Версия модели за неизменным алиасом | вне нас | **нефиксируемо** (класс A, §10.1) | замер §5.6: `reported_model` — эхо алиаса либо пусто |
| 2 | Недетерминизм сэмплинга | вне нас | **нефиксируемо** (класс D, §10.1) | `temperature=0.2` без `seed` |
| 3 | Строка модели, которую воркер считает соответствующей способности | `audit_worker/providers/model_policy.py` | **нефиксируемо центром** (класс C, §10.1) | комментарий `:1-56`: центр назвал `claude-opus-5`, ответила `claude-opus-4-8[1m]`; «решает администратор VPS файлом». Допускается и суффикс `[1m]` — другое эффективное окно |
| 4 | Entitlement провайдера (HTTP 403 «organization has disabled…») | вне нас | **нефиксируемо** (класс B, §10.1) | защёлки намеренно нет; набор доступных профилей меняется сам |
| 5 | Остаток лимита подписки | `~/.claude.json → cachedUsageUtilization` | **нефиксируемо** (класс B, §10.1) | `stability=undocumented`, задержка кэша, формат может смениться с CLI |

### 8.2. Текст, ушедший в модель

| # | Источник | Где | Метка | Комментарий |
| ---: | --- | --- | --- | --- |
| 6 | `prompts/pipeline/**` | 26 файлов | фиксируемо | `hash_files()`; только в распределённом контуре |
| 7 | `prompts/disciplines/**` | 126 файлов | фиксируемо | **исключены** из `prompt_bundle_hash`; есть `discipline_profile.tree_hash` |
| 8 | Inline-промпты в коде | ~35 литералов, ≈33 000 симв. | фиксируемо | только git-ревизией кода |
| 9 | Правка промпта из UI | `PUT /api/audit/templates/*` | фиксируемо | переписывает git-файл без коммита и без истории |
| 10 | Per-project override | `_output/prompt_overrides.json` | фиксируемо | вне git (`.gitignore:25`), отпечатка нет |
| 11 | Подмена корпуса промптов | `AUDIT_PROMPTS_DIR` (`config.py:65`) | фиксируемо | значение переменной нигде не записывается |
| 12 | `CLAUDE.md` (29 108 Б), `AGENTS.md`, `.claude/settings.json` | ambient-контекст CLI, §3.4 | фиксируемо | в git, но вне всех отпечатков; грузится по умолчанию |
| 13 | Вывод `SessionStart`-хука `load_context.py` | статус всех проектов | **нефиксируемо** (класс B, §10.1) | живые данные, меняются каждый прогон |
| 14 | `.claude/settings.local.json`, `~/.claude/**` | окружение машины | **нефиксируемо** (класс C, §10.1) | `HOME` сохраняется даже в чистом режиме |
| 15 | `_sync.json` как признак актуальности EN-шаблона | `prompts/pipeline/en/` | **не работает** | 8/8 записей устарели, гейта нет |
| 16 | Флаги, меняющие текст промпта | `STAGE01_PAGE_CONTEXT_ENABLED` (on), `NEIGHBOR_TEXT_BLOCKS_ENABLED` (on), `FINDINGS_BLOCK_CAPTIONS_ENABLED` (on), `PIPELINE_ABSENCE_GUARD_ENABLED` (off), `SINGLELINE_RICH_PROMPT_ENABLED` (off), `BLOCK_VALUE_GROUNDING_ENABLED` (off) | фиксируемо | `feature_flags_hash` есть только для воркеров |

### 8.3. Нормативный вход

| # | Источник | Где | Метка | Комментарий |
| ---: | --- | --- | --- | --- |
| 17 | `norms_reference.md` дисциплины | вход Stage 01, 8–28 КБ дословно | фиксируемо | локально не покрыт ничем |
| 18 | `norms_db.json` / `norms_paragraphs.json` | 1252 + 122 записи | фиксируемо | в git; отпечаток в артефакт прогона не пишется |
| 19 | `norms/vault/**`, `status_index.json` | вне git, здесь отсутствуют | фиксируемо | `_norm_artifact_digest`, `status_index_sha256` |
| 20 | Подмена источника статусов норм | `NORMS_STATUS_INDEX_PATH` (`norms/external_provider.py:88-91`) | фиксируемо | одной переменной база статусов меняется |
| 21 | Реальный статус нормы в мире | вне нас | **нефиксируемо** (класс A, §10.1) | `stale_after_days: 180` это признаёт |
| 22 | `knowledge_base/decisions_log.json` | KB-gate | фиксируемо | не версионируется, растёт от прогона к прогону |
| 23 | `missing_norms_online_*.json` | восстанавливаются `scripts/audit_missing_norms_online.py` из интернета | **нефиксируемо** (класс B, §10.1) | вне git |

### 8.4. Маршрут и параметры

| # | Источник | Где | Метка | Комментарий |
| ---: | --- | --- | --- | --- |
| 24 | `stage_models.json` | `.gitignore:187` | фиксируемо | `model_config_hash` только для воркеров. Комментарий в `.gitignore:183-188` сам объясняет причину: пока файл был в истории, «любой checkout тихо уводил конвейер на другие модели при следующем рестарте» |
| 25 | Глобальный `STAGE_MODEL_CONFIG` в памяти | `config.py:359-406` | фиксируемо | правится ручкой API на лету, `reload` мутирует существующий словарь |
| 26 | Замороженный план маршрутизации | `audit_routing/active_plan.py` | фиксируемо | `plan_hash()` считается (`:102-104`), **в артефакты не пишется** |
| 27 | Политика моделей воркера | `AUDIT_WORKER_PROVIDER_POLICY*` | фиксируемо | `_SHA256` и `_VERSION` уже есть |
| 28 | Молчаливые fallback F2, F3, F10, F12 | §5.4 | фиксируемо | следа в артефакте не оставляют |
| 29 | Параметры вызова | §7 | фиксируемо | в запись попадает только `reasoning_effort` |
| 30 | Флаги, меняющие сам факт и адресата вызова | `PAID_API_ENABLED` (off), `STAGE02_PAID_CACHE_ENABLED` (on), `AUDIT_WORKER_PIPELINE_PROVIDER_ENABLED` (off), `STAGE01_DUAL_REVIEW_ENABLED` (on), `OPTIMIZATION_CRITIC_DETERMINISTIC` (off), `CRITIC_V2_LLM_ENABLED` (off), `AUDIT_STRICT_MCP_FOR_NON_NORM_STAGES` (on) | фиксируемо | 21 LLM-значимая переменная из 90 `_env_*` в `config.py`; в `.env.example` объявлено 22 переменные всего |

### 8.5. Транспорт и среда исполнения

| # | Источник | Где | Метка | Комментарий |
| ---: | --- | --- | --- | --- |
| 31 | Путь к бинарю CLI | `config.py:150-172,175-203` | **нефиксируемо на практике** (класс B, §10.1) | выбор по mtime расширения VSCode; §6.6 |
| 32 | Версии CLI `claude` / `codex` | самообновляются | фиксируемо частично | `cli_version` только в снимке воркера; пины есть только в bootstrap |
| 33 | Версии SDK `openai` / `httpx` / `google-genai` | манифесты | фиксируемо | `openai>=1.60.0` в `requirements.txt`, `openai==3.3.1` в `constraints-qr-v1.txt`, `openai==2.31.0` в `requirements-worker-pipeline.txt` — **мажорное расхождение SDK, формирующего запрос** |
| 34 | Базовый URL провайдера | три литерала в центре | фиксируемо | env-override нет; §6.2 |
| 35 | MCP-сервер норм | ambient по `.mcp.json` с чужим абсолютным путём | фиксируемо | §6.5 |
| 36 | Пауза по rate limit | `usage_service.py:42,1011,1035` читает `~/.claude/projects/**/*.jsonl` | **нефиксируемо** (класс B, §10.1) | посторонняя интерактивная сессия того же пользователя поднимает утилизацию и ставит конвейер в паузу до 5 часов |
| 37 | Распознавание rate limit по тексту ответа | `cli_utils.py:13-24`, 10 регекспов | **нефиксируемо** (класс A, §10.1) | формулировки провайдера меняются между версиями CLI, что признано в `codex_runner.py:96` |
| 38 | Дневной денежный лимит | `paid_api_guard.py:120-135` сверяется с календарным днём | фиксируемо | вызов не состоится в зависимости от даты; 75 записей в `paid_api_blocked_events.jsonl` |

### 8.6. Кэши и вход из предыдущих стадий

| # | Источник | Где | Метка | Комментарий |
| ---: | --- | --- | --- | --- |
| 39 | Кэш платных ответов Stage 02 | `_output/_stage02_paid_response_cache/<key>.json` | фиксируемо | `compute_cache_key` (`stage02_paid_cache.py:112-135`), `CACHE_SCHEMA_VERSION = 2`. **TTL отсутствует**, инвалидация только по схеме и ключу; **при промахе идёт в сеть** |
| 40 | Идентичность картинки в ключе кэша | `build_image_identity()` (`stage02_paid_cache.py:80-109`) | фиксируемо | ключ по метаданным, модель получает **байты**; ре-рендер кропа даёт другие байты при том же ключе (замер в комментарии `:7-20`: 1818 КБ против 1770 КБ). Worker-путь ключует по sha256 байтов (`pipeline_bridge.attachments_digest`) — **два пути кэширования используют разные определения идентичности** |
| 41 | Журнал вызовов воркера | `inference_ledger.call_key()` | фиксируемо | готовая заготовка replay (`STATE_REPLAY`), но **модель в ключ не входит** — смена политики моделей при том же промпте вернёт из журнала ответ другой модели |
| 42 | `audit_trail/<stage>_<ts>.json` | ответ без запроса | фиксируемо | пишет `model`, токены, `result`, для HTTP-пути `response_id`/`finish_reason`; **промпта и его отпечатка нет → как кассета не годится** |
| 43 | Восстановление кропа по `crop_url` | `BLOCK_CROP_RESTORE_ALLOW_NETWORK` (default **on**) | **нефиксируемо** (класс D, §10.1) | байты картинки приходят из внешнего портала, 15% ссылок мертвы |
| 44 | Артефакты предыдущих стадий и MD от Chandra | `_output/**`, вне git | фиксируемо | предмет golden-корпуса `W0-BEH-02`, `behaviour freeze` §4.5 |

### 8.7. Порядок, время и стоимость

| # | Источник | Где | Метка | Комментарий |
| ---: | --- | --- | --- | --- |
| 45 | Дата и время **в промпте** | — | — | **не попадают**: плейсхолдера даты нет, `datetime.now` в сборщиках промпта отсутствует; даты живут в артефактах и именах каталогов |
| 46 | Выбор MD-файла проекта | `gemma_findings_only.py:595-596` — `for p in project_dir.glob("*_document.md"): return p` | фиксируемо | `glob` не отсортирован: при двух подходящих файлах выбор зависит от файловой системы |
| 47 | Выбор «последнего» прогона enrichment | `gemma_findings_only.py:519` — лексикографически; `blocks_dir()` — по mtime | фиксируемо | mtime меняется от `touch` и `rsync` |
| 48 | Порядок блоков в результате | `gemma_findings_only.py:3113-3117` — сборка по `plan`, а не по порядку завершения | — | **детерминирован**, конкурентность на порядок не влияет |
| 49 | Прайс моделей | `backend/app/data/model_prices.json` | фиксируемо | **в git**, 9 моделей; читается один раз на импорте (`llm_runner.py:163`), есть встроенный fallback, который может расходиться с файлом; неизвестная модель даёт `cost=0.0` + один warning |
| 50 | Фактическая цена от провайдера | `usage.cost`, `cost_source = actual\|estimated` (`llm_runner.py:429-436`) | **нефиксируемо** (класс B, §10.1) | цена меняется у провайдера; расхождение видно только по `cost_source` |
| 51 | Кэш промпта у провайдера | `cache_creation_input_tokens` / `cache_read_input_tokens` | **нефиксируемо** (класс D, §10.1) | те же входы дают разную раскладку → **стоимость невоспроизводима даже при воспроизводимом ответе** |


### 8.8. Позиции, добавленные перепроверкой на каноне

Первые пятьдесят одна позиция получены сплошным проходом по срезу `bff35d7d`.
Семь ниже найдены delta-аудитом на каноне и вынесены отдельно намеренно:
сквозной нумерации они не ломают, а происхождение у них другое — они не были
пропущены при чтении, их (кроме №58) в том срезе не существовало.

| # | Источник | Где | Метка | Комментарий |
| ---: | --- | --- | --- | --- |
| 52 | Инлайн-промпт Stage 5.3 | `high_level_project_changes.py:153` | фиксируемо | 1002 символа, в `prompts/**` отсутствует; §5.7 |
| 53 | Литерал модели верхнеуровневого синтеза | `project_change_summary.py:21` | фиксируемо | `gpt-5.6-luna` мимо `stage_models.json` и мимо `AUDIT_CODEX_MODEL` |
| 54 | `PROMPT_VERSION` и `VALIDATOR_VERSION` Stage 5.3 | `project_change_summary.py:19-20` | фиксируемо | входят в `source_signature` артефакта и управляют его инвалидацией |
| 55 | Политика нарезки запросов к модели | `store.py:1129-1143` | фиксируемо | не более 4 групп и 32 evidence на запрос — меняет состав каждого вызова |
| 56 | Флаг `allow_ai` прогона | `store.py:1147`, ветка `:1191-1193` | фиксируемо | при `false` решения заменяются `fallback_decision("disabled_for_run")`; переключатель обхода модели |
| 57 | Политика повторов OpenRouter | `gemma_findings_only.py:109-136,232-235` | фиксируемо частично | два env-параметра записываемы, джиттер берётся из незасеянного `random`; §6.8 |
| 58 | Политика повторов Codex | `codex_runner.py:53-56,208,215` | фиксируемо частично | то же устройство; существовала и в первом срезе — **пропуск первой редакции**, а не изменение кода |

Ни одна из семи не относится к классам §10: шесть фиксируемы полностью, две
(№57 и №58) — частично, и частичность у обеих в одном и том же месте, в
незасеянном джиттере. На счёт пятнадцати непреодолимых позиций эти строки не
влияют.

## 9. Что нужно зафиксировать, чтобы повторный прогон дал тот же ответ

Сводка §3–§8 в форме, пригодной как вход для ключа кассеты `W0-LLM-02` и как
состав `AnalysisProfile` из ADR-0013 §3. Разделено на три уровня.

**Уровень 1 — идентичность запроса (ключ кассеты).** Минимум, без которого
кассета не адресуется:

1. sha256 **собранного** текста запроса после нормализации (снять абсолютные
   пути `{BASE_DIR}`, `{PROJECT_PATH}`, `{OUTPUT_PATH}`, `run_id`, `job_id`,
   имена временных каталогов);
2. идентичность вложений — `attachments_sha256` для файлов,
   `image_identity` для кропов (обе функции уже написаны:
   `inference_ledger.call_key()`, `stage02_paid_cache.compute_cache_key()`);
3. провайдер и стадия (`purpose`), потому что один и тот же текст на разных
   стадиях — два разных оплачиваемых вызова;
4. объявленный идентификатор модели;
5. параметры вызова: `temperature`, `max_tokens`, `response_format`/схема,
   `reasoning_effort`, `top_p`, `seed` — сегодня в ключ не входят, и это
   безопасно ровно до первой их правки.

**Уровень 2 — профиль анализа (что объясняет расхождение).** Не входит в ключ
вызова, но обязано быть записано на прогон:

6. `prompt_bundle_hash` над `prompts/pipeline/**` **плюс** отпечаток профиля
   применённой дисциплины (`discipline_profile.tree_hash`) — сегодня второе
   считается только в распределённом контуре, первое исключает профили;
7. отпечаток inline-промптов — сегодня его нет вовсе; минимальный суррогат —
   ревизия кода;
8. состояние ambient-контекста CLI: отпечатки `CLAUDE.md`, `AGENTS.md`,
   `.claude/settings.json` и флаг «этап шёл с чистой cwd или нет» — без этого
   для четырнадцати из пятнадцати CLI-этапов неизвестен самый крупный кусок
   входа (§3.4);
9. `norms_snapshot`: sha256 `norms/vault/**`, `status_index_sha256`, отпечатки
   `norms_db.json` и `norms_paragraphs.json`, **и отдельно** отпечаток
   `norms_reference.md` применённой дисциплины — он идёт в промпт целиком;
10. `model_config_hash` над `stage_models.json` и `plan_hash` замороженного
   плана; для распределённого прогона — политика воркера
   (`AUDIT_WORKER_PROVIDER_POLICY_SHA256`);
11. `feature_flags_hash` над 21 LLM-значимым флагом;
12. версии транспорта: путь и отпечаток бинаря CLI плюс его `cli_version`
    (сегодня бинарь выбирается по mtime расширения VSCode, §6.6), версия SDK
    у HTTP-пути и адрес, на который ушёл запрос;
13. факт и причина каждого fallback (F1–F12) — сегодня F2, F3, F10 и F12 не
    оставляют следа.

**Уровень 3 — стоимость.** `model_prices.json` (в git), фактический `usage`
включая `cache_creation_input_tokens` и `cache_read_input_tokens`, и явная
пометка, что стоимость воспроизводима хуже ответа (см. §10, п. 5).

## 10. Четыре класса непреодолимости

Первая редакция этого раздела называлась «Что зафиксировать невозможно в
принципе» и перечисляла шесть позиций. Реестр §8 при этом помечал
**нефиксируемо** пятнадцать строк. Расхождение 15 против 6 — не описка и не
округление: одна метка склеивала четыре разных препятствия, а раздел
перечислял произвольную выборку из них, ничем не обосновав, почему остальные
девять не названы. Расписка первой редакции называла число 14 — она объединила
строки №50 и №51 в одну запись «цена и раскладка prompt cache»; здесь они
разделены, потому что классы у них разные. Метка §2 отвечает на грубый вопрос «это наш недочёт или
нет» и для инвентаря этого мало. Ниже она разложена на четыре класса; сумма
классов равна числу помеченных строк реестра, и это равенство проверяется
командой из §12.

| Класс | Что именно недоступно | Что всё-таки можно записать |
| --- | --- | --- |
| **A. Нефиксируемое состояние** | внешняя сторона не предъявляет состояние ни по какому каналу | только собственное наблюдение и его дату; само состояние не восстановимо |
| **B. Фиксируемое наблюдение внешнего состояния** | состояние чужое и меняется без нашего ведома, но снимок предъявим и осмыслен | снимок с отпечатком и датой — этого достаточно, чтобы объяснить расхождение постфактум |
| **C. Фиксируемое только оператором** | запись возможна, механизм есть, но источник лежит вне периметра центра и репозитория | значение и отпечаток, если оператор их сообщит |
| **D. Принципиально невоспроизводимое** | запись может быть полной, а повтор всё равно не даст того же | сам результат и условия прогона; равенство проверяется не побайтово |

Классы **A** и **D** — про разное, и именно их смешение породило ошибку счёта.
A отвечает «мы не знаем, что было». D отвечает «мы знаем, что было, и это не
повторится». Позиция может быть в D, будучи при этом полностью фиксируемой, —
и наоборот, позиция класса A не мешает повтору, если состояние не влияет на
ответ.

### 10.1. Разнесение пятнадцати помеченных строк реестра

| № §8 | Источник | Класс | Обоснование класса |
| ---: | --- | :---: | --- |
| 1 | Версия модели за неизменным алиасом | **A** | замер §5.6: обратного канала нет — `claude` возвращает эхо запрошенного алиаса, `codex` не возвращает ничего. Комментарий `config.py:254-256` фиксирует, что подмена уже случалась: «замер 2026-08-03: opus→4.8, sonnet→5». Записать можно объявленный ID и дату, но не то, что за ним стояло |
| 21 | Реальный статус нормы в мире | **A** | документ считается действующим, пока не доказано обратное; `stale_after_days: 180` это прямо признаёт. Реестра, который выдал бы состояние на дату прогона, у нас нет |
| 37 | Формулировка, по которой распознаётся rate limit | **A** | `cli_utils.py:13-24` — десять регекспов по тексту ответа. Провайдер не публикует ни перечень формулировок, ни машинный признак; наблюдение фиксирует одну формулировку, а для повтора нужен полный набор, которого не существует в предъявимом виде |
| 4 | Entitlement провайдера | **B** | «вход выполнен, работать нельзя» (HTTP 403, «organization has disabled Claude subscription access»). Состояние чужой организации, защёлки намеренно нет, потому что запрет могут снять в любой момент, — но факт, код и дата записываются полностью |
| 5 | Остаток лимита подписки | **B** | `~/.claude.json → cachedUsageUtilization`; `docs/claude_local_quota.md` объявляет `stability=undocumented`, `confidence=medium` и возраст кэша. Спросить остаток «честно» можно только ценой запроса к модели, что запрещено, — но наблюдённое значение и его возраст пишутся |
| 13 | Вывод `SessionStart`-хука `load_context.py` | **B** | самая слабая из пятнадцати меток: хук наш, его вывод детерминирован состоянием проектов, и ничто не мешает записать отпечаток того, что ушло в контекст. «Меняется каждый прогон» — довод за фиксацию, а не против неё |
| 23 | `missing_norms_online_*.json` | **B** | файлы лежат вне git и восстанавливаются `scripts/audit_missing_norms_online.py` из интернета. Интернет мы не контролируем, отпечаток полученного файла — контролируем |
| 31 | Путь к бинарю CLI | **B** | `config.py:150-172,175-203`: выбор по mtime расширения VSCode (§6.6). Раздел §9 п. 12 уже требует записывать путь и отпечаток бинаря — то есть документ сам считает это фиксируемым. Метка «нефиксируемо на практике» описывала не невозможность, а отсутствие записи |
| 36 | Пауза по rate limit, поднятая посторонней сессией | **B** | `usage_service.py:42,1011,1035` разбирает `~/.claude/projects/**/*.jsonl` — журналы всех сессий Claude Code этого пользователя. Интерактивная работа человека на той же машине уводит конвейер в паузу до пяти часов (`RATE_LIMIT_MAX_WAIT`, `config.py:759`) без единого изменения в репозитории. Причину зафиксировать нельзя, наблюдённое значение и факт паузы — можно |
| 50 | Фактическая цена от провайдера | **B** | `llm_runner.py:429-436`: прейскурант меняется на стороне провайдера, расхождение видно только по `cost_source`. Но когда провайдер называет цену сам, она приходит в `usage.cost` и записывается; когда не называет, записывается признак `estimated`. Наблюдение предъявимо — недоступен только будущий прейскурант |
| 3 | Строка модели, которую воркер сопоставляет способности | **C** | `audit_worker/providers/model_policy.py:1-56`: центр назвал `claude-opus-5`, ответила `claude-opus-4-8[1m]`; «решает администратор VPS файлом». Механизм записи существует — `AUDIT_WORKER_PROVIDER_POLICY_SHA256`; отсутствует не возможность, а обязанность оператора сообщить отпечаток |
| 14 | `.claude/settings.local.json`, `~/.claude/**` | **C** | `HOME` сохраняется даже в чистом режиме, файлы принадлежат машине оператора. Отпечатки снимаются тривиально — но снимать их должен тот, у кого эта машина |
| 2 | Недетерминизм сэмплинга | **D** | даже при `temperature=0` и заданном `seed` облачный провайдер не обещает побайтового совпадения. Отсюда прямо следует вывод ADR-0013 §4: побайтовое совпадение live-результатов не может быть release gate. Сам ответ фиксируется полностью |
| 43 | Восстановление кропа по `crop_url` | **D** | `BLOCK_CROP_RESTORE_ALLOW_NETWORK` (default **on**): байты приходят из внешнего портала, 15% ссылок мертвы. Отпечаток полученной картинки записывается; повторно получить те же байты по мёртвой ссылке нельзя ничем |
| 51 | Раскладка prompt cache и стоимость при идентичном ответе | **D** | записанные прогоны показывают `cache_creation_input_tokens` и `cache_read_input_tokens` в каждом `usage`. Раскладка зависит от того, что провайдер держит в кэше в этот момент: **два прогона с идентичным запросом и идентичным ответом стоят по-разному**. `B_cost` из roadmap §5.1 обязан это учитывать — воспроизводима сумма токенов, а не сумма денег |

Итог по классам: **A — 3, B — 7, C — 2, D — 3; всего 15**, ровно столько строк
реестра §8 несут метку с корнем «нефиксируем».

### 10.2. Что из этого следует для W0-LLM-02 и ADR-0013

Классы не равнозначны, и обращаться с ними надо по-разному.

- **B и C закрываются работой**, а не решением о невозможности: девять позиций
  из пятнадцати требуют не признания непреодолимости, а механизма записи. Для
  C механизм есть и упирается в обязанность оператора; для B его надо дописать.
  Считать эти восемь «свойством внешнего мира» — значит списать собственный
  долг на мир.
- **D не закрывается никогда и не должен**: три позиции определяют форму
  приёмки. Кассета `W0-LLM-02` не может проверять побайтовое равенство ответа,
  а `B_cost` не может проверять равенство суммы денег.
- **A — три позиции — единственное, что честно называется «невозможно в
  принципе»**, и именно они ограничивают потолок воспроизводимости LLM-контура.

Отдельно, не в списке, но рядом: **CLI-транспорты не принимают `temperature`,
`max_tokens` и (у Claude) `reasoning_effort`.** Это ограничение интерфейса, а не
мира: оно снимается сменой транспорта на HTTP ценой отказа от подписочной
тарификации. В пятнадцать строк реестра оно не входит и ни в один из четырёх
классов не попадает.

## 11. Что из этого блокирует ADR-0013

ADR-0013 §3 перечисляет состав `AnalysisProfile` и `ModelCallRecord`. Сверка
построчно:

| Требование ADR-0013 §3 | Состояние | Блокер |
| --- | --- | --- |
| `prompt_bundle_id` и SHA-256 каждого template | `prompt_bundle_id` объявлен в `contracts/domain/v1/identifiers.json:280-289` (`pmt_<ULID>`), реализации ноль (`grep prompt_bundle_id` по коду — пусто). `prompt_bundle_hash` есть, но исключает 126 файлов профилей и покрывает 0 из ~35 inline-промптов | **да** |
| `norms_snapshot_id`, provenance, checksum | `norms_snapshot_id` объявлен в контракте, не реализован. Механизм checksum vault есть, но корпус в чекауте не выбран; `norms_reference.md` — главный вход промпта — не покрыт ничем | **да** |
| routing по стадиям: provider, model identifier, model revision | provider и model разрешаются в пяти конкурирующих источниках, таблица вне git, два молчаливых fallback. Revision провайдером не раскрывается (§5.6) | **да** для identifier; **нет** для revision — это ограничение, а не пробел |
| sampling/tool/timeout/retry параметры | значения жёсткие, но в запись прогона попадает только `reasoning_effort` | **да** |
| версии parser/post-processing и feature flags | `feature_flags_hash` существует только для воркеров; версии парсеров не выделены | частично |
| cost policy, currency, источник расчёта | `model_prices.json` в git, `paid_cost_events.jsonl` пишется — но **только для платного HTTP-пути**; подписочные CLI-вызовы в него не попадают | **да** |
| `ModelCallRecord`: request checksum, response checksum, provider request ID, usage, latency, status, retry, cost | Собрано, но **порознь и на разных путях**: `prompt_sha256` + `raw_sha256` только в provider-режиме; `response_id` только у OpenRouter; `model` в `usage_data.json` для CLI-стадий **неверен** (§5.5); единого объекта нет | **да** |
| Payload хранится приватно, не в обычных логах | **уже соблюдается** и объявлено в коде (`provider_json_stage.py:310-313`) | нет |
| Неизвестная версия profile/prompt/norm блокирует публикацию run | гейтов нет ни одного; `check_template_sync` возвращает `synced:false` и ничего не блокирует | **да** |
| Replay parity на записанных ответах | кассет нет: `grep -rli cassette --include='*.py' . \| wc -l` → `0`; `vcrpy`/`respx`/`responses`/`pytest-recording` отсутствуют во всех манифестах | **да**, владелец — `W0-LLM-02` |
| Профиль полон, то есть покрывает весь вход | не покрывает: ambient-контекст CLI (§3.4) добавляет к промпту `CLAUDE.md` и вывод хука уже после того, как мы посчитали `prompt_sha256` | **да** |

Все три идентификатора, на которых стоит ADR-0013, объявлены в контракте и не
реализованы ни разу: `analysis_profile_id` (`prf`), `prompt_bundle_id` (`pmt`),
`norms_snapshot_id` (`nrm`) — `contracts/domain/v1/identifiers.json:269`, `:280`, `:291`,
`owner_module: analysis`; поиск по коду, фронтенду и скриптам даёт ноль
вхождений всех трёх.

Итого блокеров ADR-0013 — **девять**. Три из них снимаются написанием кода
(`AnalysisProfile`, `ModelCallRecord`, гейты), пять требуют предварительного
решения владельца:

* **Р-1. Границы prompt bundle.** Включать ли 126 файлов профилей дисциплин и
  ~35 inline-промптов. Сегодня хеш считается по 26 файлам из ~187 источников
  текста. Решает владелец analysis architecture.
* **Р-2. Судьба правки промптов из UI.** Либо запретить (промпт становится
  артефактом релиза), либо ввести версионирование правок с автором и временем.
  Сегодня — третий вариант: правка молча меняет версионируемый файл. Решает
  владелец продукта.
* **Р-3. Место таблицы моделей.** `stage_models.json` вне git и расходится с
  дефолтами кода по всем 11 стадиям. Либо в git, либо в БД с историей. Решает
  владелец operations.
* **Р-4. Санитизация записей.** ADR-0013 §4 запрещает автоматически превращать
  production payload в git fixture. 12 записанных ответов уже лежат в
  `experiments/**` и попали туда до появления правила. Решает владелец данных
  (см. `W0-DATA-01`).
* **Р-5. Ambient-контекст CLI.** Либо `clean_cwd` становится значением по
  умолчанию для всех CLI-этапов (замер в коде утверждает, что это ещё и
  дешевле и точнее: −42% input, −36% cost, +35% findings), либо `CLAUDE.md`,
  `.claude/**` и вывод `SessionStart`-хука объявляются частью
  `AnalysisProfile` и хешируются. Третьего варианта — «оставить как есть» —
  профиль анализа не переживёт: он будет заведомо неполон. Решает владелец
  analysis architecture совместно с operations.

## 12. Воспроизводимость

Числа документа проверяются на срезе `6dc3aadf` (`origin/main`):

```bash
git rev-parse --short HEAD            # 6dc3aadf

# счёт непреодолимых позиций: 14 строк реестра §8, разложенных на четыре класса
awk '/^### 8\./,/^## 9\./' docs/architecture/LLM_INVENTORY_V1.md \
  | grep -cE '^\| [0-9]+ \|.*нефиксируем'                        # 15
grep -oE '\(класс [ABCD], §10\.1\)' docs/architecture/LLM_INVENTORY_V1.md \
  | sort | uniq -c                                              # A 3, B 7, C 2, D 3

# новая точка вызова модели и её литералы (§5.7)
grep -rn 'PRODUCTION_MODEL = ' backend/app/services/stage_comparison/
# 3 совпадения: два литерала (text_ai_reviewer.py:25, project_change_summary.py:21)
# и один реэкспорт (high_level_project_changes.py:26)

# политика повторов OpenRouter (§6.8)
grep -n 'STAGE01_OPENROUTER_TRANSIENT_RETRIES\|STAGE01_OPENROUTER_RETRY_BASE_DELAY_S' \
  backend/app/pipeline/stages/block_analysis/gemma_findings_only.py

# каталоги, не менявшиеся между первым срезом и каноном
git diff --name-only bff35d7d 6dc3aadf -- prompts norms \
  backend/app/services/llm audit_worker                        # пусто

# промпты: 152 файла, разбивка
find prompts -type f | wc -l                                   # 152
find prompts/pipeline/ru -type f | wc -l                       # 17 (11 + phase1/6)
find prompts/pipeline/en -type f | wc -l                       # 9
find prompts/disciplines -type f | wc -l                       # 126
ls prompts/disciplines | grep -v _registry | wc -l             # 14 дисциплин

# эталон корпуса промптов (как МОГ БЫ выглядеть prompt_bundle_id)
find prompts -type f -print0 | sort -z | xargs -0 sha256sum | sha256sum
# 445584a0b8d28b52355d8717dd90c0863af6e4d7441354f610fd65c3275de966

# _sync.json устарел целиком: 8 из 8
python3 - <<'PY'
import json, hashlib, pathlib
s = json.load(open('prompts/pipeline/en/_sync.json'))
bad = sum(1 for n, m in s['templates'].items()
          if hashlib.md5((pathlib.Path('prompts/pipeline/ru')/n).read_bytes()).hexdigest() != m['ru_hash'])
print(bad, 'из', len(s['templates']))          # 8 из 8
PY

# промпты правились 30 раз, последний — 2026-08-07
git log --oneline -- prompts/ | wc -l                          # 30
git log -1 --format='%h %ad' --date=short -- prompts/          # b4afae5f 2026-08-07
git log --oneline -- prompts/disciplines | wc -l               # 6

# таблица моделей вне git и расходится с кодом
git check-ignore -v backend/app/data/stage_models.json         # .gitignore:187
# на чистом чекауте таблицы моделей НЕТ — она вне git; строка ниже это показывает
test -f backend/app/data/stage_models.json \
  && python3 -c "import json;print(sorted(set(json.load(open('backend/app/data/stage_models.json')).values())))" \
  || echo "stage_models.json отсутствует: значения §5.2 сняты с диска рабочей машины"
# ['openai/gpt-5.4']

# seed не задан нигде
grep -rn --include='*.py' -w seed backend/app audit_worker | grep -v __pycache__ | wc -l   # 17, ни один не про LLM
grep -rn --include='*.py' -w top_p backend/app audit_worker | wc -l                        # 0

# нормы
python3 -c "import json;d=json.load(open('norms/norms_db.json'));print(len(d['norms']),len(d['replacements']),d['meta']['last_updated'])"
# 1252 181 2026-05-06T14:33:25.818089
python3 -c "import json;print(len(json.load(open('norms/norms_paragraphs.json'))['paragraphs']))"   # 122
ls norms/vault norms/tools/status_index.json 2>&1 | head -2    # отсутствуют

# три идентификатора ADR-0013 объявлены в контракте и не реализованы
python3 -c "import json;d=json.load(open('contracts/domain/v1/identifiers.json'));\
print([ (i['field'], i.get('prefix')) for i in d['identifiers'] \
if i.get('field') in ('analysis_profile_id','prompt_bundle_id','norms_snapshot_id')])"
grep -rn "prompt_bundle_id\|norms_snapshot_id\|analysis_profile_id" \
  --include='*.py' --include='*.ts' --include='*.vue' backend audit_worker scripts frontend | wc -l   # 0

# промпты в коде: 31 вхождение role:system, 8 из файла, 23 в коде
grep -rn '"role": *"system"' --include='*.py' backend audit_worker scripts tools | wc -l            # 31
grep -c '"role": *"system"' backend/app/pipeline/stages/prepare/prompt_builder.py                   # 8

# кассет нет (подтверждение §5.3 каталога journeys)
grep -rli cassette --include='*.py' . | wc -l                                      # 0
grep -rniE 'vcrpy|respx|pytest-recording' requirements*.txt constraints-qr-v1.txt | wc -l   # 0

# провайдер не раскрывает ревизию модели
python3 - <<'PY'
import json, glob
for f in sorted(glob.glob('experiments/stage_comparison_text_ai_reviewer/artifacts/runs/*.json')):
    d = json.load(open(f))
    rep = {b.get('reported_model') for b in d['batches']}
    print(d['provider'], d['requested_model'], '->', sorted(x for x in rep if x) or 'ПУСТО')
PY

# ambient-контекст CLI включён по умолчанию: 1 вызов из 15 просит чистую cwd
grep -n "_run_cli(" backend/app/services/llm/claude_runner.py | grep -vc "def _run_cli"   # 15 вызовов
grep -c "clean_cwd=CLAUDE" backend/app/services/llm/claude_runner.py                # 1 из 15
grep -n "clean_cwd: bool = False" backend/app/services/llm/claude_runner.py         # :318
wc -c CLAUDE.md AGENTS.md                                                           # 29108, 895

# бинарь CLI выбирается по mtime расширения VSCode
grep -n "candidates.sort(reverse=True)" backend/app/core/config.py                  # :171

# ключ журнала вызовов не содержит модель
sed -n '74,82p' audit_worker/providers/inference_ledger.py

# у кэша платных ответов нет TTL
grep -c "expire\|ttl\|max_age" backend/app/pipeline/stages/block_analysis/stage02_paid_cache.py   # 0

# env-поверхность конфигурации: 90 читаемых переменных против 22 объявленных
grep -cE '_env_(bool|int|str|json_dict|float)\(' backend/app/core/config.py        # 90
grep -cE '^[A-Z][A-Z0-9_]*=' .env.example                                          # 22

# три литеральных URL OpenRouter в центре
grep -n 'openrouter.ai' backend/app/core/config.py \
  backend/app/pipeline/stages/block_analysis/gemma_findings_only.py \
  backend/app/pipeline/stages/findings_review/critic_v2/llm_gate.py
```

## 13. Границы документа

* не изготавливает кассеты, не выбирает их формат и не пишет ключ — это
  `W0-LLM-02`; §9 даёт только состав, который в ключ обязан войти;
* не правит ни одного промпта, ни одной строки кода, ни одного теста;
* не принимает решения Р-1…Р-5 из §11 — называет их и владельцев;
* не объявляет ADR-0013 готовым к переводу в `accepted`: §11 фиксирует девять
  блокеров;
* не повторяет каталог journeys — §5.2 и §5.3
  [CRITICAL_JOURNEYS_V1](CRITICAL_JOURNEYS_V1.md) остаются источником по тому,
  что для replay уже есть и чего не хватает. Настоящий документ уточняет их в
  трёх местах, не отменяя ни одного вывода: (1) обходов `_run_cli` не шесть, а
  девять, и три неучтённых — боевые (`gemma_findings_only.py:1842`,
  `external_register/matcher.py:187`, `api/routers/audit.py:230,269,281`);
  (2) `discussions/discussion_service.py:435,656` идёт не через
  `subprocess.run`, а через `process_runner.run_command`/`run_command_stream`;
  (3) `critic_v2/kb_gate.py:174` достижим из боевого API
  (`api/routers/findings.py:123` → `kb_validation_service.py:79`), а не только
  из скриптов;
* не оценивает качество аудита — это слой 3 behaviour freeze.

## 14. Ссылки

* [ADR-0013](adr/ADR-0013-llm-reproducibility-and-cost.md) — `AnalysisProfile`,
  `ModelCallRecord`, три вида доказательства; §11 сверяет инвентарь с его §3
* [Каталог критических journeys v1](CRITICAL_JOURNEYS_V1.md) §5 — LLM-journeys
  и готовность к replay, заготовки и блокеры
* [Инвентарь категорий данных v1](DATA_INVENTORY_V1.md) — где живут артефакты
  прогона, что закрыто `.gitignore`, чей это класс данных
* [Roadmap](HYBRID_REWRITE_ROADMAP.md) — `W0-LLM-01`/`W0-LLM-02`,
  `W0-ADR-04`, `W1-AI-01`/`W1-AI-02`, `W2-C-05`, `B_cost`/`B_quality` §5.1
* [Quality/runtime contract v1](QUALITY_RUNTIME_CONTRACT_V1.md) §3.3 —
  provisioning нормативного корпуса
* [Закрепление текущего поведения](../data_storage_modernization/00a_behaviour_freeze.md)
  §4.2–4.7 — шов записи, ключ кассеты, что нормализуется
* [Блоки и Stage 02](../blocks_and_stage02.md), [Critic → Corrector](../critic_corrector.md)
  — предметное описание стадий, вокруг которых построены LLM-journeys
* [Остаток лимита Claude](../claude_local_quota.md) — почему квота относится к
  нефиксируемым источникам
