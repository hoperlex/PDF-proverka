# ADR-0013. Версионирование LLM-анализа, повторяемость и стоимость

**Статус:** proposed<br>
**Дата:** 2026-08-27<br>
**Владельцы:** analysis architecture, domain owner, operations<br>
**Утверждено:** не утверждено<br>
**Decision deadline:** до Gate G0<br>
**Supersedes:** нет<br>
**Связанные task IDs:** W0-LLM-01, W0-LLM-02, W0-ADR-04, W2-C-05<br>
**Затронутые принципы Bible:** P-03, P-04, P-13, P-16, P-18

## 1. Контекст

Результат анализа зависит не только от кода и схем данных. Его меняют текст
промпта, нормативный snapshot, routing по stages, provider/model, параметры,
tools и ответ недетерминированной модели. Текущие mutable prompts, env routing и
несколько LLM transports нельзя считать воспроизводимым контрактом.

Текстовое совпадение двух live-прогонов недостижимо как надёжный gate. При этом
без точных версий входов невозможно объяснить регрессию, повторить post-LLM
логику или сопоставить качество со стоимостью.

## 2. Варианты

### A. Best-effort live parity

Хранить только имя модели и сравнивать live results семантически. Дёшево в
реализации, но тесты flaky, prompt/norm drift не диагностируется. Не
рекомендуется.

### B. Immutable analysis profile + call ledger + replay

Версионировать все детерминирующие входы, записывать evidence каждого вызова и
тестировать на replay responses. Live качество измерять отдельно. Рекомендуемый
вариант.

### C. Только локальная детерминированная модель

Упрощает повтор, но меняет качество продукта и не устраняет versioning prompt и
нормативной базы. Не является текущей целью.

## 3. Предлагаемое решение

Для каждого опубликованного run обязателен `analysis_profile_id`. Immutable
`AnalysisProfile` содержит:

- `prompt_bundle_id` и SHA-256 каждого template;
- `norms_snapshot_id`, provenance и checksum;
- routing по stage: provider, model identifier и model revision, если provider
  её раскрывает;
- sampling/tool/timeout/retry параметры;
- версии parser/post-processing и feature flags, влияющих на result;
- cost policy и currency/source расчёта.

Каждый вызов создаёт immutable `ModelCallRecord`: request checksum, response
checksum/blob reference, provider request ID, usage, latency, status, retry и
estimate/actual cost. Payload хранится приватно, не попадает в обычные logs и
подчиняется ADR-0014.

Различаются три доказательства:

1. contour parity для identity/schema/relations/artifact checksums;
2. analysis replay parity на записанных synthetic/sanitized responses;
3. live quality parity на утверждённой экспертной выборке с cost/latency budget.

Неизвестная версия profile/prompt/norm блокирует публикацию run. Если provider
не раскрывает точную revision модели, записываются объявленный model ID, дата,
provider и request fingerprint; ограничение явно отражается в evidence.

## 4. Последствия

- правка промпта или routing становится новой версией, а не скрытым изменением;
- регрессии до и после LLM-вызова воспроизводятся без платного live-запроса;
- production payload нельзя автоматически превращать в git fixture;
- появляется storage/retention стоимость call ledger и response artifacts;
- побайтное совпадение live findings исключается из release gates.

## 5. Внедрение и гейты

```text
inventory → schemas → sanitized cassette harness → baseline replay
→ shadow call ledger → cost reconciliation → canary policy
```

ADR должен быть `accepted` до production analysis writer нового контура. Gate G0
требует inventory и хотя бы один воспроизводимый critical journey. Gate G2
требует contour parity и replay parity; live canary проходит по числовой quality
и cost policy.

## 6. Пересмотр

После 100 production runs нового контура или при добавлении нового provider,
transport либо автоматического prompt optimizer — что наступит раньше.

## 7. Ссылки

- [ADR Bible](../ADR_BIBLE.md)
- [Roadmap](../HYBRID_REWRITE_ROADMAP.md)
- [Behavior freeze](../../data_storage_modernization/00a_behaviour_freeze.md)
