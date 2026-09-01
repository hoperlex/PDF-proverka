// @ts-check
/**
 * Vue composition controller and reusable view components for the distributed UI.
 */

/**
 * Глобальный объект страницы вместе со свойствами, которых нет в стандартном
 * `globalThis`: модули подключаются тегами <script> и общаются между собой
 * через window. Без такого объявления `root.Vue` для проверки типов —
 * индексация объекта без index signature.
 *
 * Тип объявлен на верхнем уровне файла намеренно: аннотация параметра
 * разрешается во внешней области видимости, а не внутри тела функции.
 * Значения объявлены как unknown: их кладут туда вендорный Vue и соседние
 * скрипты, у которых объявлений типов нет вовсе. Форму каждого задаёт одно
 * приведение в месте использования, а не догадка в каждой строке.
 *
 * @typedef {typeof globalThis & {
 *     Vue?: unknown,
 *     DistributedData?: unknown,
 *     DistributedPage?: unknown,
 *     DistributedFeature?: unknown,
 * }} DistributedFeatureRoot
 */

(function initDistributedFeature(/** @type {DistributedFeatureRoot} */ root) {
    'use strict';

    /**
     * Формы данных, которые контроллер получает от адаптера — реального или
     * демонстрационного — и показывает на экране.
     *
     * Это не копия внутренних типов distributed-service.js: объявления JSDoc
     * не переносятся между скриптами, подключёнными тегами <script>, да и
     * зависеть от всей формы ответа экрану незачем — только от полей, которые
     * он читает. Необязательное поле означает ровно то, что написано: сервер
     * вправе его не прислать, и код это учитывает.
     */

    /** @typedef {'claude'|'codex'} ProviderKey */

    /**
     * @typedef {Object} QuotaWindowView
     * @property {string} [windowId]
     * @property {string} [label]
     * @property {number|null} [remainingPercent]
     * @property {string|null} [resetIn]
     */

    /**
     * @typedef {Object} QuotaView
     * @property {number|null} [percentageRemaining]
     * @property {string} [status]
     * @property {string} [reason]
     * @property {number|null} [ageSec]
     * @property {QuotaWindowView[]} [windows]
     * @property {string} [sourceStability]
     * @property {string|null} [resetAt]
     * @property {string|null} [resetIn]
     * @property {boolean} [isEstimated]
     * @property {boolean} [stale]
     */

    /**
     * @typedef {Object} EventOutboxView
     * @property {string} [status]
     * @property {number} [lastWrittenSeq]
     * @property {number} [lastAckedSeq]
     * @property {number} [pending]
     * @property {number} [attempts]
     * @property {string|null} [lastAckAt]
     */

    /**
     * @typedef {Object} ReleasesView
     * @property {string|null} [centerRelease]
     * @property {string|null} [gatewayRelease]
     * @property {string} [status]
     * @property {string|null} [reason]
     */

    /**
     * @typedef {Object} DiagnosticView
     * @property {string} workerId
     * @property {string|null} [instanceId]
     * @property {string|null} [transport]
     * @property {string|null} [grpcStream]
     * @property {string|null} [connectionId]
     * @property {string|null} [mtls]
     * @property {string|null} [heartbeat]
     * @property {string|null} [gatewayTarget]
     * @property {string|null} [gatewayTargetNote]
     * @property {string|null} [sourceHost]
     * @property {string|null} [resultHost]
     * @property {string|null} [nginx]
     * @property {string|null} [agentStatus]
     * @property {string|null} [executorStatus]
     * @property {EventOutboxView} [eventOutbox]
     * @property {string|null} [resultAck]
     * @property {string|null} [workerVersion]
     * @property {string|null} [workerRelease]
     * @property {ReleasesView} [releases]
     * @property {string|null} [runtimeVersion]
     * @property {string|null} [uptime]
     * @property {string|null} [certExpiry]
     */

    /**
     * @typedef {Object} DiagnosticRowView
     * @property {string} [workerName]
     * @property {boolean} [online]
     * @property {DiagnosticView} diagnostic
     */

    /**
     * @typedef {Object} TaskView
     * @property {string} id
     * @property {string} stage
     * @property {string|null} [workerId]
     * @property {string} [project]
     * @property {string} [packageName]
     * @property {string} [mode]
     * @property {string} [status]
     * @property {number|null} [progress]
     * @property {number|null} [progressPercent]
     * @property {string} [progressKind]
     * @property {string} [duration]
     * @property {string} [lastActivity]
     * @property {string|null} [completedAtIso]
     * @property {string|null} [errorMessage]
     * @property {string|null} [technicalCode]
     * @property {{at: string, text: string}[]} [events]
     * @property {Record<string, string>} [modelUsage]
     */

    /**
     * @typedef {Object} WorkerView
     * @property {string} id
     * @property {string} name
     * @property {string} status
     * @property {{claude: QuotaView, codex: QuotaView}} quotas
     * @property {{used: number, total: number, occupiedSlots?: number, totalSlots?: number, physicalFreeSlots?: number}} slots
     * @property {{cpu?: number|null, ram?: number|null, gpu?: number|null, vramUsedGb?: number|null, vramTotalGb?: number|null, disk?: number|null}} resources
     * @property {DiagnosticView} diagnostic
     * @property {TaskView[]} [currentTasks]
     * @property {boolean} [acceptsNewTasks]
     * @property {boolean} [quotaDataStale]
     * @property {boolean} [readOnly]
     * @property {string|null} [lastHeartbeat]
     */

    /**
     * @typedef {Object} QueueItemView
     * @property {string} id
     * @property {string|null} priority
     * @property {number} [position]
     * @property {string} [project]
     * @property {string} [packageName]
     * @property {string} [mode]
     * @property {string|null} [suggestedWorkerId]
     * @property {string|null} [expectedStart]
     * @property {string} [status]
     * @property {number|null} [pageCount]
     * @property {number|null} [blockCount]
     */

    /**
     * @typedef {Object} ProjectView
     * @property {string} id
     * @property {string} [project]
     * @property {string} [packageName]
     * @property {string} [mode]
     * @property {string|null} [assignment]
     * @property {string} [status]
     * @property {string|null} [priority]
     * @property {number|null} [pageCount]
     * @property {number|null} [blockCount]
     * @property {number|null} [packageSizeBytes]
     */

    /**
     * Рекомендация «что запустить следующим». Проект и узел объявлены
     * обнуляемыми не для страховки: реальный бэкенд отдаёт `projectId: null`
     * и `workerId: null`, пока планировщик выключен.
     *
     * @typedef {Object} RecommendationView
     * @property {string|null} projectId
     * @property {string|null} workerId
     * @property {string[]} [reasons]
     * @property {number} [freeSlots]
     * @property {number|null} [gpu]
     * @property {number|null} [claude]
     * @property {number|null} [codex]
     */

    /**
     * @typedef {Object} AttentionView
     * @property {string} [id]
     * @property {string|null} [workerId]
     * @property {string} [taskId]
     * @property {string} [title]
     * @property {string} [description]
     * @property {string} [severity]
     */

    /**
     * @typedef {Object} LimitRowView
     * @property {string} workerName
     * @property {QuotaView} claude
     * @property {QuotaView} codex
     * @property {string} [workerId]
     * @property {boolean} [online]
     * @property {boolean} [stale]
     */

    /** @typedef {{active: TaskView[], completed: TaskView[], errors: TaskView[]}} TasksView */

    /**
     * @typedef {Object} OverviewView
     * @property {WorkerView[]} workers
     * @property {ProjectView[]} projects
     * @property {RecommendationView|null} recommendation
     * @property {QueueItemView[]} queuePreview
     * @property {AttentionView[]} attention
     * @property {Record<string, number>} [kpis]
     */

    /**
     * @typedef {Object} SnapshotView
     * @property {OverviewView} overview
     * @property {WorkerView[]} workers
     * @property {QueueItemView[]} queue
     * @property {TasksView} tasks
     * @property {LimitRowView[]} limits
     * @property {DiagnosticRowView[]} diagnostics
     */

    /**
     * Контракт адаптера данных: что экран вправе у него спросить. Реализаций
     * две — реальная и демонстрационная, — и обе живут в
     * distributed-service.js.
     *
     * @typedef {Object} DistributedService
     * @property {string} mode
     * @property {boolean} [readOnly]
     * @property {() => Promise<SnapshotView>} [getSnapshot]
     * @property {() => Promise<OverviewView>} getOverview
     * @property {() => Promise<WorkerView[]>} getWorkers
     * @property {() => Promise<QueueItemView[]>} getQueue
     * @property {() => Promise<TasksView>} getTasks
     * @property {() => Promise<LimitRowView[]>} getProviderLimits
     * @property {() => Promise<DiagnosticRowView[]>} getDiagnostics
     * @property {(projectId: string, workerId: string) => Promise<ProjectView>} assignTask
     * @property {(projectId: string, workerId: string|null) => Promise<ProjectView>} sendTask
     * @property {(queueItemId: string, priority: string) => Promise<unknown>} changePriority
     * @property {(queueItemId: string, direction: 'first'|'up'|'down'|'last') => Promise<QueueItemView[]>} moveQueueItem
     * @property {(workerId: string, acceptsNewTasks: boolean) => Promise<WorkerView>} setWorkerIntake
     * @property {(taskId: string) => Promise<TaskView>} retryTask
     * @property {(taskId: string, workerId: string) => Promise<TaskView>} transferTask
     * @property {() => string} getSafeDiagnosticsText
     */

    /**
     * Ровно та часть window.DistributedData, которой пользуется контроллер:
     * фабрика адаптера по умолчанию. Полный контракт объявлен в
     * distributed-service.js.
     *
     * @typedef {{createDefaultService: () => DistributedService}} DistributedDataFactory
     */

    /**
     * Vue приходит вендорным глобальным скриптом (vue.global.prod.js), пакета
     * с объявлениями типов в зависимостях нет. Описана та часть API, которой
     * пользуется контроллер, — этого достаточно, чтобы значения внутри ref
     * оставались типизированными.
     *
     * @template T
     * @typedef {{value: T}} VueRef
     */

    /**
     * @typedef {Object} VueRuntimeApi
     * @property {<T>(value: T) => VueRef<T>} ref
     * @property {<T>(getter: () => T) => {readonly value: T}} computed
     * @property {<T extends object>(target: T) => T} reactive
     */

    /**
     * Состояние модального окна — размеченное объединение по полю `type`:
     * каждый обработчик проверяет тип и дальше видит ровно свой набор полей.
     *
     * @typedef {{type: 'send', project: ProjectView, workerId: string|null}
     *     | {type: 'why', recommendation?: RecommendationView|null}
     *     | {type: 'alternative', project?: ProjectView|null, workerId?: string|null}
     *     | {type: 'queue-why', item: QueueItemView, worker: WorkerView|null}
     *     | {type: 'transfer', task: TaskView}} ModalState
     */

    /** @typedef {{message: string, tone: 'success'|'warning'|'error'}} ToastState */

    /**
     * Область видимости геттеров карточки квоты: props, которые Vue кладёт в
     * `this` во время выполнения.
     *
     * @typedef {{label?: string, quota: QuotaView|null|undefined, stale?: boolean}} QuotaBarScope
     */

    const TAB_DEFINITIONS = Object.freeze([
        { key: 'overview', label: 'Обзор', path: '/distributed' },
        { key: 'queue', label: 'Очередь', path: '/distributed/queue' },
        { key: 'tasks', label: 'Задачи', path: '/distributed/tasks' },
        { key: 'workers', label: 'Воркеры', path: '/distributed/workers' },
        { key: 'limits', label: 'Лимиты', path: '/distributed/limits' },
        { key: 'diagnostics', label: 'Диагностика', path: '/distributed/diagnostics' },
    ]);

    const MODE_LABELS = Object.freeze({ full_codex: 'Full Codex', hybrid: 'Гибрид Claude + Codex', distributed_audit: 'Распределённый аудит' });
    const PRIORITY_LABELS = Object.freeze({ critical: 'Критический', high: 'Высокий', normal: 'Обычный', low: 'Низкий' });
    const STAGE_LABELS = Object.freeze({ queued: 'В очереди', transfer: 'Передача', preparing: 'Подготовка', auditing: 'Проверка', collecting: 'Сбор результата', returning: 'Возврат результата', importing: 'Импорт', done: 'Готово', error: 'Ошибка' });
    const TASK_STAGE_ORDER = Object.freeze(['queued', 'transfer', 'preparing', 'auditing', 'collecting', 'returning', 'importing', 'done']);

    /**
     * Почему остаток такой, какой есть, — словами.
     *
     * Воркер присылает КОД, а не текст: свободная строка с полу-доверенной
     * стороны, показанная в браузере, — это чужой текст на нашем экране.
     * Разворачивание кода в предложение живёт здесь, и здесь же видно, что
     * недокументированный источник не выдаётся за официальный.
     */
    const QUOTA_REASON_TEXT = Object.freeze({
        organization_subscription_access_disabled: 'Вход выполнен, но владелец организации запретил доступ Claude Code для этой учётной записи. Повторный вход не поможет: нужен доступ от администратора организации либо другая учётная запись.',
        local_cache_available: 'Локальные данные Claude Code. Официального машиночитаемого остатка у Claude Code нет — показано то, что CLI сохранил у себя.',
        local_cache_stale: 'Локальные данные Claude Code, уже неактуальные: показано последнее известное значение, а не текущее.',
        local_cache_missing: 'Локальные данные об использовании Claude пока не появились — они возникают после обращений к модели на этом воркере.',
        local_cache_schema_unsupported: 'Формат локальных данных Claude Code не распознан: источник недокументирован и мог измениться с обновлением CLI.',
        no_safe_supported_source: 'Claude Code не сообщает остаток лимита без обращения к модели, а локальных данных об использовании на воркере пока нет.',
    });

    /**
     * Ярлык по коду. Отдельная функция нужна потому, что коды приходят
     * снаружи: для проверки типов это произвольная строка, а не заранее
     * известный ключ словаря. Неизвестный код даёт undefined — чем его
     * заменить, решает вызывающий.
     *
     * @param {Readonly<Record<string, string>>} labels
     * @param {string|null|undefined} code
     * @returns {string|undefined}
     */
    function labelFor(labels, code) {
        return code == null ? undefined : labels[code];
    }

    /**
     * Проверка «это число, с которым можно считать». Отдельная функция нужна
     * проверке типов: `Number.isFinite` делает ровно это, но тип не сужает, и
     * сравнение после неё считается сравнением с null.
     *
     * @param {unknown} value
     * @returns {value is number}
     */
    function isFiniteNumber(value) {
        return typeof value === 'number' && Number.isFinite(value);
    }

    /**
     * Текст ошибки действия для показа пользователю. В catch тип по-настоящему
     * неизвестен: туда попадает и Error, и что угодно ещё, брошенное
     * адаптером, — поэтому поле message читается приведением к форме «объект с
     * message», а не утверждением о классе исключения. Поведение сохранено
     * дословно, включая крайний случай `throw null`.
     *
     * @param {unknown} error
     * @returns {string}
     */
    function errorText(error) {
        const carrier = /** @type {{message?: unknown}} */ (error);
        return String(carrier.message || error);
    }

    /**
     * Остаток провайдера числом. Приведение здесь одно и объяснимо: строки уже
     * отобраны по `Number.isFinite`, но для проверки типов фильтр
     * доказательством не является. Во время выполнения не меняет ничего.
     *
     * @param {LimitRowView} row
     * @param {ProviderKey} provider
     * @returns {number}
     */
    function remainingPercent(row, provider) {
        return /** @type {number} */ (row[provider].percentageRemaining);
    }

    /** @param {QuotaView|null|undefined} quota */
    function quotaReasonText(quota) {
        const code = quota && quota.reason;
        return (code && labelFor(QUOTA_REASON_TEXT, code)) || '';
    }

    /** Возраст НАБЛЮДЕНИЯ. Не «когда мы посмотрели», а «когда это было верно».
     * @param {QuotaView|null|undefined} quota */
    function quotaAgeText(quota) {
        const age = quota && quota.ageSec;
        if (!isFiniteNumber(age)) return '';
        if (age < 90) return 'данные только что';
        if (age < 5400) return `данные ${Math.round(age / 60)} мин назад`;
        if (age < 172800) return `данные ${Math.round(age / 3600)} ч назад`;
        return `данные ${Math.round(age / 86400)} сут назад`;
    }

    /** @param {QuotaView|null|undefined} quota @returns {QuotaWindowView[]} */
    function quotaWindows(quota) {
        return (quota && Array.isArray(quota.windows)) ? quota.windows : [];
    }

    /** @param {string} path */
    function routeToTab(path) {
        const clean = String(path || '').replace(/\/+$/, '') || '/';
        if (clean === '/distributed') return 'overview';
        const match = clean.match(/^\/distributed\/(queue|tasks|workers|limits|diagnostics)$/);
        return match ? match[1] : null;
    }

    /** @param {number|null|undefined} value */
    function usageTone(value) {
        if (!isFiniteNumber(value)) return 'unavailable';
        if (value >= 90) return 'danger';
        if (value >= 70) return 'warning';
        return 'normal';
    }

    /** @param {number} bytes */
    function formatBytes(bytes) {
        if (!Number.isFinite(bytes) || bytes <= 0) return '—';
        return `${(bytes / 1024 / 1024).toFixed(bytes >= 104857600 ? 0 : 1)} МБ`;
    }

    /** @param {Date} date */
    function localDate(date) {
        const year = date.getFullYear();
        const month = String(date.getMonth() + 1).padStart(2, '0');
        const day = String(date.getDate()).padStart(2, '0');
        return `${year}-${month}-${day}`;
    }

    /** @param {TaskView[]|null|undefined} rows @param {string} period @param {string=} customFrom @param {string=} customTo @param {Date=} anchor */
    function filterCompletedTasks(rows, period, customFrom, customTo, anchor = new Date()) {
        const toDate = new Date(anchor.getTime());
        const fromDate = new Date(anchor.getTime());
        if (period === '7d') fromDate.setDate(fromDate.getDate() - 6);
        if (period === '30d') fromDate.setDate(fromDate.getDate() - 29);
        let from = localDate(fromDate);
        let to = localDate(toDate);
        if (period === 'custom') {
            from = customFrom || '0000-01-01';
            to = customTo || '9999-12-31';
        }
        return (rows || []).filter((task) => {
            const raw = String(task.completedAtIso || '');
            const parsed = raw ? new Date(raw) : null;
            const date = parsed && Number.isFinite(parsed.getTime()) ? localDate(parsed) : raw.slice(0, 10);
            return date && date >= from && date <= to;
        });
    }

    /** @param {{service?: DistributedService}=} options */
    function createManager(options = {}) {
        const VueRuntime = /** @type {VueRuntimeApi} */ (root.Vue);
        const { ref, computed, reactive } = VueRuntime;
        // Адаптер данных лежит на window: distributed-service.js подключён к
        // странице раньше. Приведение стоит здесь, чтобы дальше работать с
        // объявленным контрактом, а не с unknown.
        const service = options.service || /** @type {DistributedDataFactory} */ (root.DistributedData).createDefaultService();
        const isDemo = service.mode === 'mock';
        const readOnly = Boolean(service.readOnly);
        const today = new Date();

        const activeTab = ref('overview');
        const taskSubtab = ref('active');
        const historyPeriod = ref('today');
        const historyFrom = ref(localDate(new Date(today.getFullYear(), today.getMonth(), 1)));
        const historyTo = ref(localDate(today));
        const loading = ref(false);
        const loaded = ref(false);
        const error = ref('');
        /** @type {VueRef<OverviewView|null>} */
        const overview = ref(null);
        /** @type {VueRef<WorkerView[]>} */
        const workers = ref([]);
        /** @type {VueRef<QueueItemView[]>} */
        const queue = ref([]);
        /** @type {VueRef<TasksView>} */
        const tasks = ref({ active: [], completed: [], errors: [] });
        /** @type {VueRef<LimitRowView[]>} */
        const limits = ref([]);
        /** @type {VueRef<DiagnosticRowView[]>} */
        const diagnostics = ref([]);
        /** @type {VueRef<Record<string, string>>} */
        const assignmentByProject = ref({});
        /** @type {VueRef<TaskView|null>} */
        const selectedTask = ref(null);
        /** @type {VueRef<WorkerView|null>} */
        const selectedWorker = ref(null);
        /** @type {VueRef<DiagnosticRowView|null>} */
        const selectedDiagnostic = ref(null);
        /** @type {VueRef<ModalState|null>} */
        const modal = ref(null);
        const transferWorkerId = ref('worker-mow-03');
        /** @type {VueRef<ToastState|null>} */
        const toast = ref(null);
        let toastTimer = 0;

        // Обзор читается в локальную переменную не ради краткости: тогда из
        // непустой рекомендации видно, что и сам обзор непуст, — иначе это
        // знание остаётся только в голове у читателя.
        const recommendationProject = computed(() => {
            const current = overview.value;
            const recommendation = current && current.recommendation;
            return recommendation && current.projects.find((project) => project.id === recommendation.projectId);
        });
        const recommendationWorker = computed(() => {
            const current = overview.value;
            const recommendation = current && current.recommendation;
            return recommendation && current.workers.find((worker) => worker.id === recommendation.workerId);
        });
        const limitsSummary = computed(() => {
            const online = limits.value.filter((item) => item.online);
            /** @param {ProviderKey} provider */
            const withValue = (provider) => online.filter((item) => Number.isFinite(item[provider] && item[provider].percentageRemaining));
            /** @param {ProviderKey} provider */
            const average = (provider) => {
                const rows = withValue(provider);
                return rows.length ? Math.round(rows.reduce((sum, item) => sum + remainingPercent(item, provider), 0) / rows.length) : null;
            };
            /** @param {ProviderKey} provider */
            const best = (provider) => [...withValue(provider)].sort((a, b) => remainingPercent(b, provider) - remainingPercent(a, provider))[0] || null;
            const resetEntries = online.flatMap((item) => [
                { provider: 'Claude', resetAt: item.claude.resetAt, resetIn: item.claude.resetIn, workerName: item.workerName },
                { provider: 'Codex', resetAt: item.codex.resetAt, resetIn: item.codex.resetIn, workerName: item.workerName },
            ]).filter((item) => item.resetAt).sort((a, b) => String(a.resetAt).localeCompare(String(b.resetAt)));
            const next = resetEntries[0];
            return { claude: average('claude'), codex: average('codex'), nextReset: next ? `${next.resetIn || 'время недоступно'} · ${next.provider}, ${next.workerName}` : 'Недоступно', bestClaude: best('claude')?.workerName || 'Недоступно', bestCodex: best('codex')?.workerName || 'Недоступно' };
        });
        const visibleCompletedTasks = computed(() => {
            return filterCompletedTasks(tasks.value.completed, historyPeriod.value, historyFrom.value, historyTo.value, new Date());
        });

        async function load(force = false) {
            if (loaded.value && !force) return;
            loading.value = true;
            error.value = '';
            try {
                let overviewData, workersData, queueData, tasksData, limitsData, diagnosticsData;
                if (typeof service.getSnapshot === 'function') {
                    const snapshot = await service.getSnapshot();
                    overviewData = snapshot.overview;
                    workersData = snapshot.workers;
                    queueData = snapshot.queue;
                    tasksData = snapshot.tasks;
                    limitsData = snapshot.limits;
                    diagnosticsData = snapshot.diagnostics;
                } else {
                    [overviewData, workersData, queueData, tasksData, limitsData, diagnosticsData] = await Promise.all([
                        service.getOverview(), service.getWorkers(), service.getQueue(), service.getTasks(), service.getProviderLimits(), service.getDiagnostics(),
                    ]);
                }
                overview.value = overviewData;
                workers.value = workersData;
                queue.value = queueData;
                tasks.value = tasksData;
                limits.value = limitsData;
                diagnostics.value = diagnosticsData;
                /** @type {Record<string, string>} */
                const assignments = {};
                for (const project of overviewData.projects || []) assignments[project.id] = project.assignment || 'auto';
                assignmentByProject.value = assignments;
                loaded.value = true;
            } catch (loadError) {
                // Загрузка терпимее действий: falsy-значение исключения здесь
                // превращается в текст, а не роняет обработчик. Сохранено как
                // было — этим ветка и отличается от errorText().
                const carrier = /** @type {{message?: unknown}|null|undefined} */ (loadError);
                error.value = String(carrier && carrier.message ? carrier.message : loadError);
            } finally {
                loading.value = false;
            }
        }

        async function refresh() { await load(true); }

        /** @param {string} tab */
        function setTab(tab) {
            if (TAB_DEFINITIONS.some((item) => item.key === tab)) activeTab.value = tab;
        }

        /** @param {string} tab */
        function goToTab(tab) {
            const definition = TAB_DEFINITIONS.find((item) => item.key === tab) || TAB_DEFINITIONS[0];
            root.location.hash = definition.path;
        }

        /** @param {string} message @param {'success'|'warning'|'error'=} tone */
        function notify(message, tone = 'success') {
            root.clearTimeout(toastTimer);
            toast.value = { message, tone };
            toastTimer = root.setTimeout(() => { toast.value = null; }, 3600);
        }

        /** @param {string|null|undefined} workerId @returns {WorkerView|null} */
        function workerById(workerId) { return workers.value.find((worker) => worker.id === workerId) || null; }
        /** @param {string|null|undefined} workerId */
        function workerName(workerId) { const worker = workerById(workerId); return worker ? worker.name : 'Автоматически'; }
        /** @param {string|null|undefined} mode */
        function modeLabel(mode) { return labelFor(MODE_LABELS, mode) || mode; }
        /** @param {string|null|undefined} priority */
        function priorityLabel(priority) { return labelFor(PRIORITY_LABELS, priority) || priority; }
        /** @param {string|null|undefined} stage */
        function stageLabel(stage) { return labelFor(STAGE_LABELS, stage) || stage; }
        /** @param {number|null|undefined} value */
        function progressStyle(value) { return { width: `${Number.isFinite(value) ? Math.min(100, Math.max(0, Number(value))) : 0}%` }; }
        /** @param {TaskView|null|undefined} task */
        function progressText(task) {
            if (!task || !Number.isFinite(task.progressPercent)) return 'Прогресс недоступен';
            return `${task.progressKind === 'estimated' ? '≈ ' : ''}${task.progressPercent}%`;
        }
        /** @param {number|null|undefined} value @param {string=} suffix */
        function metricText(value, suffix = '%') { return Number.isFinite(value) ? `${value}${suffix}` : 'Нет телеметрии'; }
        /** «Ещё не опрашивали» — это не «недоступен» и не «нет лимита».
         *  @param {QuotaView|null|undefined} quota */
        function quotaText(quota) {
            if (quota && quota.status === 'not_observed') return 'Ещё не опрошен';
            return quota && Number.isFinite(quota.percentageRemaining) ? `${quota.percentageRemaining}%` : 'Остаток недоступен';
        }
        const OUTBOX_STATUS_LABELS = {
            synced: 'Синхронизировано', pending: 'Ожидается синхронизация',
            stale: 'Данные устарели', unavailable: 'Нет данных',
        };
        /** Состояние журнала событий словом. `null` пользователю не показываем:
         *  он читается либо как ноль, либо как поломка.
         *  @param {DiagnosticView|null|undefined} diagnostic */
        function outboxStatusText(diagnostic) {
            /** @type {EventOutboxView} */
            const outbox = diagnostic && diagnostic.eventOutbox || {};
            return labelFor(OUTBOX_STATUS_LABELS, outbox.status) || OUTBOX_STATUS_LABELS.unavailable;
        }
        /** @param {DiagnosticView|null|undefined} diagnostic */
        function outboxAvailable(diagnostic) {
            /** @type {EventOutboxView} */
            const outbox = diagnostic && diagnostic.eventOutbox || {};
            return [outbox.lastAckedSeq, outbox.lastWrittenSeq, outbox.pending].every(Number.isFinite);
        }
        /** @param {DiagnosticView|null|undefined} diagnostic */
        function outboxText(diagnostic) {
            /** @type {EventOutboxView} */
            const outbox = diagnostic && diagnostic.eventOutbox || {};
            return outboxAvailable(diagnostic)
                ? `${outboxStatusText(diagnostic)} · последняя попытка ${outbox.lastAckedSeq}/${outbox.lastWrittenSeq}, ожидает всего ${outbox.pending}`
                : OUTBOX_STATUS_LABELS.unavailable;
        }
        /** @param {string} projectId @param {string} workerId */
        async function setAssignment(projectId, workerId) {
            try {
                const project = await service.assignTask(projectId, workerId);
                assignmentByProject.value = { ...assignmentByProject.value, [projectId]: workerId };
                const target = workerId === 'auto' ? 'автоматическое распределение' : `VPS ${workerName(workerId)}`;
                notify(`${project.project} → ${project.packageName}: выбрано ${target}`);
                return true;
            } catch (actionError) {
                notify(errorText(actionError), 'error');
                return false;
            }
        }

        /** @param {ProjectView} project @param {string=} explicitWorkerId */
        function openSend(project, explicitWorkerId) {
            const selected = explicitWorkerId || assignmentByProject.value[project.id] || project.assignment || 'auto';
            const resolved = selected === 'auto' && overview.value && overview.value.recommendation && overview.value.recommendation.projectId === project.id
                ? overview.value.recommendation.workerId : selected;
            modal.value = { type: 'send', project, workerId: resolved };
        }

        async function confirmSend() {
            if (!modal.value || modal.value.type !== 'send') return;
            const { project, workerId } = modal.value;
            try {
                const result = await service.sendTask(project.id, workerId);
                modal.value = null;
                const target = workerId === 'auto' ? 'с автоматическим назначением' : `на VPS ${workerName(workerId)}`;
                notify(`${result.project} → ${result.packageName} добавлен ${isDemo ? 'в демо-очередь' : 'в очередь'} ${target}`);
                await refresh();
            } catch (actionError) { notify(errorText(actionError), 'error'); }
        }

        function openWhy() { modal.value = { type: 'why', recommendation: overview.value && overview.value.recommendation }; }
        function openAlternative() { modal.value = { type: 'alternative', project: recommendationProject.value, workerId: recommendationWorker.value && recommendationWorker.value.id }; }
        async function applyAlternative() {
            if (!modal.value || modal.value.type !== 'alternative') return;
            // Модалку «другой узел» открывает только карточка рекомендации:
            // к этому моменту и проект, и узел уже выбраны. Приведение это
            // фиксирует и сохраняет прежнее поведение — без узла код падал и
            // раньше, молчаливой заглушки здесь не появляется.
            const chosenWorkerId = /** @type {string} */ (modal.value.workerId);
            const project = /** @type {ProjectView} */ (modal.value.project);
            const changed = await setAssignment(project.id, chosenWorkerId);
            if (!changed) return;
            if (overview.value && overview.value.recommendation) {
                const chosenWorker = workerById(chosenWorkerId);
                overview.value.recommendation.workerId = chosenWorkerId;
                if (chosenWorker) {
                    overview.value.recommendation.freeSlots = chosenWorker.slots.total - chosenWorker.slots.used;
                    overview.value.recommendation.gpu = chosenWorker.resources.gpu;
                    overview.value.recommendation.claude = chosenWorker.quotas.claude.percentageRemaining;
                    overview.value.recommendation.codex = chosenWorker.quotas.codex.percentageRemaining;
                    overview.value.recommendation.reasons = [
                        `свободно ${chosenWorker.slots.total - chosenWorker.slots.used} из ${chosenWorker.slots.total} слотов`,
                        `GPU загружен на ${chosenWorker.resources.gpu}%`,
                        `Claude: осталось примерно ${chosenWorker.quotas.claude.percentageRemaining}%`,
                        `Codex: осталось примерно ${chosenWorker.quotas.codex.percentageRemaining}%`,
                        `сброс Claude через ${chosenWorker.quotas.claude.resetIn}`,
                        `узел подходит под режим ${modeLabel(project.mode)}`,
                    ];
                }
            }
            modal.value = null;
        }

        /** @param {QueueItemView} item */
        function openQueueWhy(item) {
            const worker = workerById(item.suggestedWorkerId);
            modal.value = { type: 'queue-why', item, worker };
        }

        /** @param {QueueItemView} item @param {'first'|'up'|'down'|'last'} direction */
        async function moveQueue(item, direction) {
            try {
                queue.value = await service.moveQueueItem(item.id, direction);
                notify(`${item.project} → ${item.packageName}: позиция в очереди изменена`);
                if (overview.value) overview.value.queuePreview = queue.value.slice(0, 5);
            } catch (actionError) { notify(errorText(actionError), 'error'); }
        }

        /** @param {QueueItemView} item @param {string} priority */
        async function changePriority(item, priority) {
            try {
                await service.changePriority(item.id, priority);
                item.priority = priority;
                notify(`${item.project} → ${item.packageName}: приоритет — ${priorityLabel(priority)}`);
            } catch (actionError) { notify(errorText(actionError), 'error'); }
        }

        /** @param {TaskView|null|undefined} task */
        function openTask(task) {
            if (!task) return;
            const fullTask = [...tasks.value.active, ...tasks.value.completed, ...tasks.value.errors].find((item) => item.id === task.id);
            selectedTask.value = fullTask || task;
        }
        /** @param {string} taskId @returns {TaskView|null} */
        function taskById(taskId) { return [...tasks.value.active, ...tasks.value.completed, ...tasks.value.errors].find((item) => item.id === taskId) || null; }
        /** @param {string} taskId */
        function openAttentionTask(taskId) { openTask(taskById(taskId)); }
        /** @param {string} taskId */
        function retryAttentionTask(taskId) { const task = taskById(taskId); if (task) retryTask(task); }
        /** @param {string} taskId */
        function transferAttentionTask(taskId) { const task = taskById(taskId); if (task) openTransfer(task); }
        /** @param {WorkerView|null} worker */
        function openWorker(worker) { selectedWorker.value = worker; }
        /** @param {DiagnosticRowView|null} row */
        function openDiagnostic(row) { selectedDiagnostic.value = row; }
        function openWorkerDiagnostic() {
            if (!selectedWorker.value) return;
            const workerId = selectedWorker.value.diagnostic.workerId;
            const row = diagnostics.value.find((item) => item.diagnostic.workerId === workerId);
            selectedWorker.value = null;
            if (row) selectedDiagnostic.value = row;
        }

        /** @param {WorkerView} worker @param {boolean} accepts */
        async function toggleWorkerIntake(worker, accepts) {
            try {
                const updated = await service.setWorkerIntake(worker.id, accepts);
                worker.acceptsNewTasks = updated.acceptsNewTasks;
                notify(`VPS ${worker.name}: ${accepts ? 'приём новых задач включён' : 'новые назначения приостановлены'}`, accepts ? 'success' : 'warning');
            } catch (actionError) { notify(errorText(actionError), 'error'); }
        }

        /** @param {TaskView} task */
        async function retryTask(task) {
            try {
                const updated = await service.retryTask(task.id);
                notify(`${updated.project} → ${updated.packageName}: повтор запущен${isDemo ? ' в демо-режиме' : ''}`);
                selectedTask.value = null;
                await refresh();
            } catch (actionError) { notify(errorText(actionError), 'error'); }
        }

        /** @param {TaskView} task */
        function openTransfer(task) {
            // Запасной вариант — узел самой задачи, а он может быть не
            // назначен: бэкенд шлёт workerId: null для задач в очереди.
            // Приведение сохраняет прежнее поведение, крайний случай описан
            // в отчёте по W0-INT-01.
            transferWorkerId.value = /** @type {string} */ (workers.value.find((worker) => worker.status !== 'offline' && worker.id !== task.workerId)?.id || task.workerId);
            modal.value = { type: 'transfer', task };
        }

        async function confirmTransfer() {
            if (!modal.value || modal.value.type !== 'transfer') return;
            try {
                const updated = await service.transferTask(modal.value.task.id, transferWorkerId.value);
                modal.value = null;
                selectedTask.value = null;
                notify(`${updated.project} → ${updated.packageName} переносится на VPS ${workerName(transferWorkerId.value)}${isDemo ? ' (демо)' : ''}`);
                await refresh();
            } catch (actionError) { notify(errorText(actionError), 'error'); }
        }

        /** @param {TaskView} task @param {string} stage */
        function taskStageState(task, stage) {
            if (task.stage === 'error') return stage === 'auditing' ? 'error' : 'pending';
            const currentIndex = TASK_STAGE_ORDER.indexOf(task.stage);
            const stageIndex = TASK_STAGE_ORDER.indexOf(stage);
            if (stageIndex < currentIndex || task.stage === 'done') return 'done';
            if (stageIndex === currentIndex) return 'current';
            return 'pending';
        }

        /** @param {TaskView} task @param {string} stage */
        function taskStageText(task, stage) {
            const state = taskStageState(task, stage);
            if (state === 'done') return '✓';
            if (state === 'current') return stage === 'auditing' ? progressText(task) : 'сейчас';
            if (state === 'error') return '!';
            return '';
        }

        async function copyDiagnostics() {
            const text = service.getSafeDiagnosticsText();
            try {
                if (root.navigator && root.navigator.clipboard) await root.navigator.clipboard.writeText(text);
                else {
                    const area = root.document.createElement('textarea');
                    area.value = text;
                    root.document.body.appendChild(area);
                    area.select();
                    root.document.execCommand('copy');
                    area.remove();
                }
                notify('Безопасная диагностика скопирована');
            } catch (_) { notify('Не удалось скопировать диагностику', 'error'); }
        }

        /** @param {DiagnosticView|null|undefined} diagnostic */
        function diagnosticRows(diagnostic) {
            if (!diagnostic) return [];
            /** @type {EventOutboxView} */
            const outbox = diagnostic.eventOutbox || {};
            /** @type {ReleasesView} */
            const releases = diagnostic.releases || {};
            /** @param {unknown} value */
            const show = (value) => value === null || value === undefined || value === '' ? 'Нет данных' : value;
            return [
                ['worker_id', show(diagnostic.workerId)], ['instance_id', show(diagnostic.instanceId)], ['transport', show(diagnostic.transport)], ['grpc_stream', show(diagnostic.grpcStream)], ['connection_id', show(diagnostic.connectionId)], ['mTLS', show(diagnostic.mtls)], ['heartbeat', show(diagnostic.heartbeat)],
                ['Gateway target', show(diagnostic.gatewayTarget) === 'Нет данных' && diagnostic.gatewayTargetNote ? diagnostic.gatewayTargetNote : show(diagnostic.gatewayTarget)],
                ['source host', show(diagnostic.sourceHost)], ['result host', show(diagnostic.resultHost)], ['nginx', show(diagnostic.nginx)], ['Agent status', show(diagnostic.agentStatus)], ['Executor status', show(diagnostic.executorStatus)],
                ['EventOutbox', outboxStatusText(diagnostic)],
                ['EventOutbox · записано (последняя попытка)', outboxAvailable(diagnostic) ? outbox.lastWrittenSeq : 'Нет данных'],
                ['EventOutbox · подтверждено (последняя попытка)', outboxAvailable(diagnostic) ? outbox.lastAckedSeq : 'Нет данных'],
                ['EventOutbox · ожидает (всего по попыткам)', outboxAvailable(diagnostic) ? outbox.pending : 'Нет данных'],
                ['EventOutbox · попыток учтено', Number.isFinite(outbox.attempts) ? outbox.attempts : 'Нет данных'],
                ['EventOutbox · последнее подтверждение', show(outbox.lastAckAt)],
                ['ResultAck', show(diagnostic.resultAck)], ['worker version', show(diagnostic.workerVersion)],
                ['Релиз центра', show(releases.centerRelease)], ['Релиз шлюза', show(releases.gatewayRelease)], ['Релиз воркера', show(diagnostic.workerRelease)],
                ['Совместимость релизов', releases.status === 'ok' ? `OK — ${releases.reason}` : show(releases.reason)],
                ['runtime version', show(diagnostic.runtimeVersion)], ['uptime', show(diagnostic.uptime)], ['cert expiry', show(diagnostic.certExpiry)],
            ];
        }

        return reactive({
            tabs: TAB_DEFINITIONS, activeTab, taskSubtab, historyPeriod, historyFrom, historyTo,
            loading, loaded, error, overview, workers, queue, tasks, limits, diagnostics, isDemo, readOnly,
            assignmentByProject, selectedTask, selectedWorker, selectedDiagnostic, modal, transferWorkerId, toast,
            recommendationProject, recommendationWorker, limitsSummary, visibleCompletedTasks,
            load, refresh, setTab, goToTab, notify, workerById, workerName,
            modeLabel, priorityLabel, stageLabel, progressStyle, progressText, metricText, quotaText, outboxText, usageTone, formatBytes,
            quotaReasonText, quotaAgeText, quotaWindows,
            setAssignment, openSend, confirmSend, openWhy, openAlternative, applyAlternative,
            openQueueWhy, moveQueue, changePriority, openTask, taskById,
            openAttentionTask, retryAttentionTask, transferAttentionTask,
            openWorker, openDiagnostic, openWorkerDiagnostic,
            toggleWorkerIntake, retryTask, openTransfer, confirmTransfer,
            taskStageState, taskStageText, copyDiagnostics, diagnosticRows,
            closeModal: () => { modal.value = null; },
            closeTask: () => { selectedTask.value = null; },
            closeWorker: () => { selectedWorker.value = null; },
            closeDiagnostic: () => { selectedDiagnostic.value = null; },
        });
    }

    /** @param {{component: (name: string, definition: unknown) => unknown}} app */
    function registerComponents(app) {
        app.component('distributed-dispatcher-page', root.DistributedPage);
        app.component('distributed-quota-bar', {
            props: { label: String, quota: Object, stale: Boolean },
            computed: {
                // Окна лимита приходят отсортированными «самое ограничивающее
                // первым», и главное число карточки относится именно к нему.
                //
                // `@this` в каждом геттере — не украшение: внутри литерала
                // опций `this` для типизатора равен самому литералу, где
                // никакого `quota` нет. Vue подставляет туда props в рантайме,
                // и тип области видимости назван здесь ровно поэтому.
                //
                // Соседние computed читают `quotaWindows(this.quota)` заново, а
                // не `this.windows`: внутри литерала опций `this` — обычный
                // объект, и `this.windows` для типизатора равно самой функции,
                // а не её результату (`Property 'slice' does not exist on type
                // '() => any'`). Vue-обёртка над геттерами существует только в
                // рантайме, tsc её не видит. Повторный вызов дешёв — это
                // проверка типа и чтение поля.
                /** @this {QuotaBarScope} */
                windows() { return quotaWindows(this.quota); },
                /** @this {QuotaBarScope} */
                primaryWindow() { return quotaWindows(this.quota)[0] || null; },
                /** @this {QuotaBarScope} */
                otherWindows() { return quotaWindows(this.quota).slice(1); },
                /** @this {QuotaBarScope} */
                reasonText() { return quotaReasonText(this.quota); },
                /** @this {QuotaBarScope} */
                ageText() { return quotaAgeText(this.quota); },
                /** @this {QuotaBarScope} */
                undocumented() { return this.quota && this.quota.sourceStability === 'undocumented'; },
                // Доказанный отказ провайдера: авторизация исправна, работать
                // нельзя. Показывается вместо процента — числа тут нет и быть
                // не может, а «Остаток недоступен» увело бы к поиску квоты.
                /** @this {QuotaBarScope} */
                entitlementBlocked() { return this.quota && this.quota.status === 'entitlement_blocked'; },
            },
            template: `
                <div class="distributed-quota" :class="'distributed-quota--' + (quota.status || 'unknown')">
                    <div class="distributed-quota__top">
                        <span class="distributed-quota__name">{{ label }}</span>
                        <strong v-if="entitlementBlocked" class="distributed-quota__blocked">Доступ запрещён организацией</strong>
                        <strong v-else-if="Number.isFinite(quota.percentageRemaining)">{{ quota.percentageRemaining }}% <small>осталось</small></strong>
                        <strong v-else>Остаток недоступен</strong>
                    </div>
                    <div v-if="entitlementBlocked" class="distributed-quota__window">Вход выполнен · работа запрещена</div>
                    <div v-else-if="primaryWindow" class="distributed-quota__window">{{ primaryWindow.label }}</div>
                    <div v-if="entitlementBlocked" class="distributed-progress distributed-progress--unavailable" aria-label="Доступ запрещён организацией"><span></span></div>
                    <div v-else-if="Number.isFinite(quota.percentageRemaining)" class="distributed-progress distributed-progress--quota" role="progressbar" :aria-label="label + ': осталось ' + quota.percentageRemaining + '%'" :aria-valuenow="quota.percentageRemaining" aria-valuemin="0" aria-valuemax="100">
                        <span :style="{width: quota.percentageRemaining + '%'}"></span>
                    </div>
                    <div v-else class="distributed-progress distributed-progress--unavailable" aria-label="Остаток недоступен"><span></span></div>
                    <div class="distributed-quota__reset">
                        <span>{{ entitlementBlocked ? 'Задания этому провайдеру не назначаются' : stale ? 'Последние известные данные' : quota.resetIn ? 'Сброс через ' + quota.resetIn : 'Дата сброса недоступна' }}</span>
                        <span v-if="quota.isEstimated" title="Провайдер передаёт приблизительное значение">≈ оценка</span>
                    </div>
                    <ul v-if="otherWindows.length" class="distributed-quota__windows">
                        <li v-for="window in otherWindows" :key="window.windowId">
                            <span>{{ window.label }}</span>
                            <span>{{ Number.isFinite(window.remainingPercent) ? window.remainingPercent + '% осталось' : 'остаток недоступен' }}<template v-if="window.resetIn"> · сброс через {{ window.resetIn }}</template></span>
                        </li>
                    </ul>
                    <div v-if="stale && ageText" class="distributed-quota__age distributed-quota__age--stale">⚠ {{ ageText }}</div>
                    <div v-else-if="ageText" class="distributed-quota__age">{{ ageText }}</div>
                    <div v-if="reasonText" class="distributed-quota__note" :class="{'distributed-quota__note--undocumented': undocumented}">{{ reasonText }}</div>
                </div>`,
        });

        app.component('distributed-worker-card', {
            props: { worker: Object, detailed: Boolean },
            emits: ['detail', 'toggle-intake', 'task'],
            methods: {
                /** @param {string|null|undefined} mode */
                modeLabel(mode) { return labelFor(MODE_LABELS, mode) || mode; },
                /** @param {string|null|undefined} stage */
                stageLabel(stage) { return labelFor(STAGE_LABELS, stage) || stage; },
                usageTone,
                /** @param {number|null|undefined} value @param {string=} suffix */
                metricText(value, suffix = '%') { return Number.isFinite(value) ? value + suffix : 'Нет телеметрии'; },
                /** @param {TaskView} task */
                progressText(task) { return !Number.isFinite(task.progressPercent) ? 'Прогресс недоступен' : (task.progressKind === 'estimated' ? '≈ ' : '') + task.progressPercent + '%'; },
            },
            template: `
                <article class="distributed-worker-card" :class="['distributed-worker-card--' + worker.status, {'distributed-worker-card--detailed': detailed}]">
                    <header class="distributed-worker-card__header">
                        <div>
                            <h3>VPS {{ worker.name }}</h3>
                            <span class="distributed-worker-card__heartbeat">{{ worker.status === 'offline' ? 'Последняя связь ' : 'Heartbeat ' }}{{ worker.lastHeartbeat }}</span>
                        </div>
                        <span class="distributed-status" :class="'distributed-status--' + worker.status"><i></i>{{ worker.status === 'offline' ? 'Offline' : worker.status === 'busy' ? 'Занят' : 'Online' }}</span>
                    </header>
                    <div class="distributed-resources">
                        <div v-for="metric in [{key:'cpu',label:'CPU',value:worker.resources.cpu},{key:'ram',label:'RAM',value:worker.resources.ram},{key:'gpu',label:'GPU',value:worker.resources.gpu}]" :key="metric.key" class="distributed-resource">
                            <div><span>{{ metric.label }}</span><strong>{{ worker.status === 'offline' ? '—' : metricText(metric.value) }}</strong></div>
                            <div class="distributed-progress" :class="'distributed-progress--' + usageTone(metric.value)"><span :style="{width: (worker.status === 'offline' ? 0 : metric.value) + '%'}"></span></div>
                        </div>
                        <div class="distributed-resource">
                            <div><span>VRAM</span><strong>{{ worker.status === 'offline' ? '—' : Number.isFinite(worker.resources.vramUsedGb) && Number.isFinite(worker.resources.vramTotalGb) ? worker.resources.vramUsedGb + ' / ' + worker.resources.vramTotalGb + ' ГБ' : 'Нет телеметрии' }}</strong></div>
                            <div class="distributed-progress" :class="'distributed-progress--' + usageTone(worker.resources.vramUsedGb / worker.resources.vramTotalGb * 100)"><span :style="{width: (worker.status === 'offline' || !Number.isFinite(worker.resources.vramUsedGb) || !Number.isFinite(worker.resources.vramTotalGb) ? 0 : worker.resources.vramUsedGb / worker.resources.vramTotalGb * 100) + '%'}"></span></div>
                        </div>
                    </div>
                    <div class="distributed-worker-card__slots">
                        <span>Слоты <b>{{ worker.slots.occupiedSlots ?? worker.slots.used }} / {{ worker.slots.totalSlots ?? worker.slots.total }}</b></span>
                        <span :class="{'is-free': (worker.slots.physicalFreeSlots ?? (worker.slots.total - worker.slots.used)) > 0}">{{ worker.status === 'offline' ? 'недоступен' : (worker.slots.physicalFreeSlots ?? (worker.slots.total - worker.slots.used)) + ' физически свободно' }}</span>
                    </div>
                    <div class="distributed-quota-grid">
                        <distributed-quota-bar label="Claude" :quota="worker.quotas.claude" :stale="worker.quotas.claude.stale"></distributed-quota-bar>
                        <distributed-quota-bar label="Codex" :quota="worker.quotas.codex" :stale="worker.quotas.codex.stale"></distributed-quota-bar>
                    </div>
                    <div class="distributed-worker-tasks" v-if="worker.currentTasks.length">
                        <div class="distributed-worker-tasks__title">Сейчас</div>
                        <button v-for="task in worker.currentTasks.slice(0, detailed ? 4 : 2)" :key="task.id" class="distributed-worker-task" @click="$emit('task', task)">
                            <span><strong>{{ task.project }}</strong> → {{ task.packageName }}</span>
                            <span>{{ modeLabel(task.mode) }} · {{ task.duration }}</span>
                            <div class="distributed-worker-task__progress"><i :style="{width: (Number.isFinite(task.progressPercent) ? task.progressPercent : 0) + '%'}"></i></div>
                            <b>{{ progressText(task) }}</b>
                        </button>
                    </div>
                    <div v-else class="distributed-worker-card__idle">{{ worker.status === 'offline' ? 'Текущих задач нет' : 'Свободен для новой задачи' }}</div>
                    <footer v-if="detailed" class="distributed-worker-card__footer">
                        <label class="distributed-switch" :class="{'is-disabled': worker.status === 'offline' || worker.readOnly}">
                            <input type="checkbox" :checked="worker.acceptsNewTasks" :disabled="worker.status === 'offline' || worker.readOnly" @change="$emit('toggle-intake', $event.target.checked)">
                            <span></span>Принимать новые задачи
                        </label>
                        <button class="btn btn-outline btn-sm" @click="$emit('detail', worker)">Подробнее</button>
                    </footer>
                </article>`,
        });
    }

    root.DistributedFeature = Object.freeze({ createManager, registerComponents, routeToTab, filterCompletedTasks, quotaReasonText, quotaAgeText, quotaWindows, constants: { TAB_DEFINITIONS, MODE_LABELS, PRIORITY_LABELS, STAGE_LABELS, QUOTA_REASON_TEXT } });
})(typeof window !== 'undefined' ? window : globalThis);
