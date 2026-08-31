# Route/feature inventory действующего UI — v1

**Задача:** `W0-WEB-01` (lane WEB).<br>
**Редакция:** 2026-08-31.<br>
**Источник истины:** рабочее дерево на коммите, указанном в §8; ничего не
предполагается по документации — каждая строка ниже прочитана из кода.<br>
**Изменений кода задача не вносит.** Это frozen input для `W0-WEB-02`
(disposition падений) и для `W0-ADR-09` (ADR-0017 route strangler).

## 1. Граница инвентаризации

Инвентаризируется то, что определяет **адресуемость** UI: какие документы
отдаёт сервер, какие маршруты понимает SPA, какие из них можно открыть по
ссылке и что именно маршрут запускает. Внутренние вкладки, модальные окна и
состояние компонентов сюда не входят — они не адресуемы и не могут быть
целью strangler-переноса.

Инвентарь фиксирует **фактическое** поведение, в том числе дефектное. Строка
«дефект» не означает разрешения его чинить: правки принадлежат `W0-WEB-02` и
последующим задачам.

## 2. Документы, которые отдаёт сервер

Три HTML-документа и один статический mount. Все — в `backend/app/main.py`.

| Path | Handler | Что отдаёт | Auth | Кэш |
| --- | --- | --- | --- | --- |
| `/` | `serve_spa` | `frontend/index.html`, подстановка `{{css_version}}`/`{{js_version}}` из mtime | наследует portal auth | `no-cache, must-revalidate` |
| `/login` | `serve_login` | `frontend/login.html`; при выключенном auth или активной сессии — 302 на `/` | публичный по определению | по умолчанию |
| `/audit-workers` | `serve_audit_workers` | `frontend/audit-workers.html` | наследует portal auth | `no-cache, must-revalidate` |
| `/static/**` | `StaticFiles` | `frontend/static/**` (js, css) | наследует portal auth | по умолчанию (версионирование через `?v=mtime`) |

Следствие для strangler: **точек входа три, а не одна.** `/audit-workers` —
отдельное приложение на своём JS (`static/js/audit-workers.js`, 82 КБ), оно не
разделяет ни роутер, ни состояние с SPA. Перенос `/` не переносит его.

`js_version` для `/` считается как максимум mtime по четырём файлам —
`app.js`, `version_api.js`, `portal_auth.js`,
`stage-comparison-differences.js`. `distributed-*.js` в этот расчёт **не
входят**: правка только их не инвалидирует кеш браузера. Это дефект
cache-busting, а не маршрутизации; зафиксирован здесь, потому что влияет на
проверяемость любого frontend-изменения (`W0-INT-01`).

## 3. Маршрутизация SPA

Механизм — `window.location.hash`, без History API. Единственная запись хеша
— `navigate(path)` (`app.js:2555`), единственный разбор — `handleRoute()`
(`app.js:2559`), подписка на `hashchange` и первый вызов — в `onMounted`
(`app.js:11738`, `11745`).

Диспетчер — цепочка `if/else if` по регулярным выражениям. Порядок ветвей
значим и разобран в §6.

### 3.1. Глобальные маршруты

| Hash | `currentView` | Что запускает | WS |
| --- | --- | --- | --- |
| `#/` (и пустой хеш) | `dashboard` | `refreshProjects()`; сбрасывает `sidebarFilterSection` | global |
| `#/queue` | `queue` | `refreshBatchQueue()`, `fetchPrepareQueue()`, `refreshProjects()` | global |
| `#/schedule` | `schedule` | `loadUsers()` (admin-гейт), `schedLoad()` | global |
| `#/knowledge-base` | `knowledge-base` | `loadKnowledgeBase()`, `loadKBStats()`; фильтр по текущему объекту | global |
| `#/stage-comparison` | `stage-comparison` | `scLoadObjects()` | global |
| `#/critic-v2-ui` | `critic-v2-ui` | ничего не грузит | global |
| `#/section/{code}` | `dashboard` | `refreshProjects()`; ставит `sidebarFilterSection = code` | global |
| `#/section/{code}/optimization` | `section-optimization` | `refreshProjects()`, `loadSectionOptimization(code, tab)` | global |

`#/section/__all__` — не отдельный маршрут, а зарезервированное значение
`{code}`: только оно не раскрывает подменю разделов (`app.js:2648`).
Навигация на него — `app.js:5896`.

`#/critic-v2-ui` виден в навигации только под `cv2DebugVisible`
(`index.html:130`), но маршрут открыт всем: прямая ссылка работает независимо
от флага. Это debug-видимость, а не ограничение доступа.

### 3.2. Проектные маршруты

Все — вида `#/project/{id}/…`, `{id}` проходит `decodeURIComponent`.

| Hash | `currentView` | Что запускает | WS |
| --- | --- | --- | --- |
| `#/project/{id}` | `project` | `loadProject(id)` | global |
| `#/project/{id}/findings` | `findings` | `loadProject`, `loadFindings`, `loadExpertDecisions` | global |
| `#/project/{id}/blocks` | `blocks` | `loadProject`, `loadBlocks` | global |
| `#/project/{id}/optimization` | `optimization` | `loadProject`, `loadOptimization`, `loadExpertDecisions` | global |
| `#/project/{id}/document` | `document` | `loadProject`, `loadDocument` | global |
| `#/project/{id}/critic-v2` | `critic-v2-project` | `loadProject`, `cv2LoadProject(id)` | global |
| `#/project/{id}/critic-v2-disagreements` | `critic-v2-project` | `loadProject`, `cv2LoadProject(id, {disagreementsMode:true})` | global |
| `#/project/{id}/log` | `log` | `loadProject`, `loadProjectLog` | **project WS**, не global |

`#/project/{id}/log` — единственный маршрут, переключающий соединение с
global WS на project WS. Любая навигация с него возвращает global WS. Для
strangler это означает: маршрут нельзя вынести, не перенеся вместе с ним
владение WS-соединением.

Два `critic-v2` маршрута дают **один** `currentView` и различаются только
начальным фильтром. `index.html:472` называет их «старыми hash-routes» —
внутри вида есть свой sub-tab strip, который переписывает хеш обратно
(`app.js:523`, `531`). Тем самым маршрут `…/critic-v2-disagreements` —
адресуемый alias состояния, а не отдельный экран.

### 3.3. Маршруты распределённых вычислений

Определены в `distributed-feature.js:8` (`TAB_DEFINITIONS`), разбираются
`routeToTab()` (`distributed-feature.js:62`) — то есть **вне** `app.js`, и
проверяются в диспетчере первыми.

| Hash | Вкладка |
| --- | --- |
| `#/distributed` | `overview` |
| `#/distributed/queue` | `queue` |
| `#/distributed/tasks` | `tasks` |
| `#/distributed/workers` | `workers` |
| `#/distributed/limits` | `limits` |
| `#/distributed/diagnostics` | `diagnostics` |

Все шесть дают `currentView = 'distributed'`. Хвостовые слэши нормализуются
(`replace(/\/+$/, '')`). Это единственная группа маршрутов с собственным
модулем, тайпчеком (`tsconfig.distributed.json`) и линтом — то есть
единственный участок UI, уже пригодный к типизированному переносу.

## 4. Deeplink-параметры

Query живёт **внутри** хеша: `#/path?key=value`. Разделение — по первому `?`
(`app.js:2561`).

| Параметр | Где читается | Действие | Область |
| --- | --- | --- | --- |
| `version_id` | `VersionAPI.parseVersionFromHash` (`version_api.js:44`) | перебивает `activeVersionId`, инвалидирует кеши `project`/`findings`/`optimization`/`blocks` | любой маршрут |
| `tab` | `handleRoute`, ветка section-optimization | начальная вкладка; допустимы `specifications`, `accepted`, `signals`, иначе — `specifications` | только `#/section/{code}/optimization` |

Сборка ссылки с версией — `VersionAPI.buildHashRoute(route, versionId)`
(`version_api.js:61`); она отбрасывает существующий query, поэтому
`?version_id` и `?tab` **не сочетаются**: переключение версии на странице
оптимизации раздела теряет выбранную вкладку. Дефект зафиксирован в §6.

Сброс версии: если query нет и маршрут не начинается с `/project`,
`activeVersionId` обнуляется (`app.js:2584`). Дашборд и разделы намеренно не
наследуют версию предыдущего проекта.

## 5. Возвратные точки, не являющиеся маршрутами

Две функции сохраняют «откуда пришли» в памяти, а не в URL:

- `navigateToBlock()` (`app.js:7513`) пишет `blockBackRoute = {hash, expandedFinding, expandedOpt}`
  и уходит на `…/blocks`; `goBackFromBlock()` (`app.js:7545`) восстанавливает хеш.
- `loadSectionOptimization` использует `window.location.hash` как точку
  возврата (`app.js:5624`).

Обе точки возврата **не переживают перезагрузку страницы**: раскрытый finding
и вкладка восстанавливаются из ref-состояния. Для strangler это скрытая
связность: маршрут `…/blocks` не самодостаточен, его пользовательский сценарий
зависит от состояния, которого нет в URL.

`navigateToBlock` дополнительно ждёт загрузку блоков через
`setTimeout(300)` — то есть корректность deeplink на блок зависит от времени
ответа API, а не от готовности данных.

## 6. Дефекты адресуемости, найденные инвентаризацией

Найденное фиксируется, не чинится. Владелец каждой строки указан.

### RI-1. `#/project/{id}/discussions` — маршрут удалён, навигация осталась

`closeDiscussion()` (`app.js:9130`) выполняет
`navigate('/project/' + currentProjectId.value + '/discussions')`. Ветви для
`discussions` в диспетчере нет: маршрут удалён вместе с разделом «Проработка
замечаний» в `aeb0b2f2` (2026-07-06). Сообщение того коммита утверждает
«0 остаточных ссылок на discussions» — утверждение неверно, эта ссылка
пережила удаление.

Фактическое поведение: хеш попадает в замыкающую ветвь
`/^\/project\/(.+)$/`, и `currentProjectId` становится строкой
`"{id}/discussions"`, после чего `loadProject` запрашивает несуществующий
проект. Пользователь получает пустую карточку вместо возврата к списку.

Достижимость на сегодня: `closeDiscussion` экспортирована в шаблон
(`app.js:15972`), но **ни одна разметка её не вызывает** (0 вхождений в
`index.html`); единственный живой вызов — из `resolveDiscussion`
(`app.js:9459`), который сам достижим только через удалённый UI. То есть
дефект реален, но в текущей сборке не воспроизводится действиями
пользователя.

**Владелец:** `W0-WEB-02` — восстановление уже утверждённого поведения
(удалить осиротевшую навигацию либо вернуть ей корректную цель). Legacy slot
не расходуется: новой пользовательской семантики нет.

### RI-2. Неизвестный маршрут не даёт ни ошибки, ни редиректа

Цепочка `if/else if` не имеет ветви `else`. При хеше, не совпавшем ни с одним
шаблоном (например `#/bogus`), `handleRoute` не меняет `currentView` и ничего
не загружает. При первом открытии по такой ссылке пользователь видит
`dashboard` **без данных**: `refreshProjects()` вызывается только из ветви
`#/`. При навигации внутри сессии остаётся предыдущий экран, а адресная
строка ему уже не соответствует.

**Владелец:** `W0-ADR-09`/ADR-0017 — поведение неизвестного маршрута
(404-экран либо редирект) является решением контура, а не правкой legacy.

### RI-3. `version_id` и `tab` взаимно исключаются

`buildHashRoute` (`version_api.js:63`) отбрасывает весь существующий query
(`route.split('?')[0]`) и приписывает только `version_id`. Переключение
версии на `#/section/{code}/optimization?tab=signals` возвращает на вкладку
`specifications`.

Строго говоря, `version_id` на маршруте раздела и не должен применяться:
раздел агрегирует проекты, а не версию одного. Но фактическая потеря вкладки
происходит, потому что диспетчер разрешает query на любом маршруте.

**Владелец:** `W0-ADR-09` — контракт query-параметров относится к дизайну
маршрутизации.

### RI-4. Cache-busting не покрывает `distributed-*.js`

`serve_spa` считает `js_version` по четырём файлам; три модуля
распределённых вычислений (`distributed-feature.js`, `distributed-page.js`,
`distributed-service.js`) в расчёт не входят, хотя подключаются из
`index.html`. Правка только этих файлов не инвалидирует кеш браузера.

**Владелец:** `W0-INT-01` — `backend/app/main.py` относится к composition
root и в WEB-задачах запрещён.

### RI-5. Точка возврата не адресуема

См. §5. `#/project/{id}/blocks`, открытый по прямой ссылке, не имеет кнопки
возврата: `blockBackRoute` пуст, `goBackFromBlock()` не делает ничего.

**Владелец:** `W0-ADR-09` — это ограничение дизайна маршрутов, а не дефект
реализации.

## 7. Сводка для strangler

| Группа | Маршрутов | Владелец кода | Пригодность к переносу |
| --- | ---: | --- | --- |
| `#/distributed/*` | 6 | `distributed-*.js` (модули, typecheck + lint) | высокая: изолированы, типизированы, без общего состояния с `app.js` |
| `#/section/*` | 2 | `app.js` | средняя: зависят от `sidebarFilterSection` и текущего объекта |
| `#/project/{id}/*` | 8 | `app.js` | низкая: общий кеш, общий WS, непубличные точки возврата |
| глобальные экраны | 6 | `app.js` | средняя: `#/critic-v2-ui` не грузит данных и переносится первым |
| `/audit-workers` | 1 документ | `audit-workers.js` | высокая: отдельная страница, отдельный JS |

Итого адресуемых hash-маршрутов: **22** (6 распределённых + 2 раздельных +
8 проектных + 6 глобальных), плюс 3 серверных документа.

## 8. Воспроизводимость

Инвентарь снят чтением следующих файлов:

| Файл | Роль |
| --- | --- |
| `backend/app/main.py` | серверные документы, static mount, cache-busting |
| `frontend/static/js/app.js` | `navigate`, `handleRoute`, все проектные и глобальные ветви |
| `frontend/static/js/distributed-feature.js` | `TAB_DEFINITIONS`, `routeToTab` |
| `frontend/static/js/version_api.js` | `parseVersionFromHash`, `buildHashRoute` |
| `frontend/index.html` | точки навигации в разметке |
| `frontend/audit-workers.html` | вторая точка входа |

Проверка полноты. Числа сверены на дату редакции и обязаны совпадать с §7;
расхождение означает, что маршрут добавлен или удалён без правки инвентаря.

```bash
# 16 маршрутных ветвей диспетчера (17-я строка — сброс версии, не маршрут)
awk '/^        function handleRoute\(\)/,/^        }$/' frontend/static/js/app.js \
  | grep -cE '^            \} else if \('        # ожидается 17

# 6 вкладок распределённых вычислений, свёрнутых в одну ветвь диспетчера
grep -c "path: '/distributed" frontend/static/js/distributed-feature.js  # 6

# 3 серверных документа
grep -cE '^@app\.get\("/(login|audit-workers)?"\)' backend/app/main.py  # 3
```

16 маршрутных ветвей + 6 вкладок распределённых вычислений = 22 адресуемых
hash-маршрута.

## 9. Что этот документ не делает

- не меняет ни строки кода и ни одного маршрута;
- не назначает целевую архитектуру маршрутизации — это ADR-0017 (`W0-ADR-09`);
- не описывает REST API (`/api/**`): предмет `W0-ARC-02`/ADR-0003;
- не заменяет каталог user journeys `W0-BEH-01`: маршрут — адрес, а не сценарий.
