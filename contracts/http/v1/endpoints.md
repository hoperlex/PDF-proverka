# HTTP-контракт: индекс операций

Сгенерировано `scripts/contract/dump_openapi.py`. Не редактировать вручную.

Ни одна операция не имеет типизированной схемы ответа — все обработчики
возвращают голый `dict`. Формы ответов закрепляются отдельно, слоем 1б
(см. `docs/data_storage_modernization/00a_behaviour_freeze.md`).

Всего операций: **270**.

| Метод | Путь | Параметры | Теги |
| --- | --- | --- | --- |
| `GET` | `/` | — | — |
| `GET` | `/api/action-log` | query:actor?, query:date_from?, query:date_to?, query:errors_only?, query:kind?, query:limit?, query:offset?, query:q? | action-log |
| `GET` | `/api/action-log/stats` | query:days? | action-log |
| `GET` | `/api/audit/account` | — | audit |
| `POST` | `/api/audit/account/switch` | — | audit |
| `GET` | `/api/audit/account/switch/status` | — | audit |
| `POST` | `/api/audit/all/full` | — | audit |
| `POST` | `/api/audit/batch` | body! | audit |
| `POST` | `/api/audit/batch/add` | body! | audit |
| `POST` | `/api/audit/batch/add-resume` | body! | audit |
| `POST` | `/api/audit/batch/add-retry` | body! | audit |
| `DELETE` | `/api/audit/batch/cancel` | — | audit |
| `POST` | `/api/audit/batch/hide-finished` | body? | audit |
| `DELETE` | `/api/audit/batch/history` | — | audit |
| `POST` | `/api/audit/batch/remove` | body! | audit |
| `POST` | `/api/audit/batch/reorder` | body! | audit |
| `POST` | `/api/audit/batch/resume` | — | audit |
| `GET` | `/api/audit/batch/status` | — | audit |
| `POST` | `/api/audit/batch/update-action` | body! | audit |
| `GET` | `/api/audit/disciplines` | — | audit |
| `GET` | `/api/audit/live-status` | — | audit |
| `GET` | `/api/audit/model` | — | audit |
| `POST` | `/api/audit/model` | query:model! | audit |
| `GET` | `/api/audit/model/batch-modes` | — | audit |
| `POST` | `/api/audit/model/batch-modes` | body! | audit |
| `GET` | `/api/audit/model/stages` | — | audit |
| `POST` | `/api/audit/model/stages` | body! | audit |
| `POST` | `/api/audit/pause` | body? | audit |
| `GET` | `/api/audit/pause/status` | — | audit |
| `GET` | `/api/audit/prepare-data/queue` | — | audit |
| `POST` | `/api/audit/prepare-data/queue/cancel` | — | audit |
| `POST` | `/api/audit/prepare-data/queue/clear` | — | audit |
| `POST` | `/api/audit/prepare-data/queue/pause` | — | audit |
| `POST` | `/api/audit/prepare-data/queue/resume` | — | audit |
| `POST` | `/api/audit/prepare-data/{project_id}/retry-failed` | path:project_id!, query:version_id? | audit |
| `POST` | `/api/audit/resume` | — | audit |
| `GET` | `/api/audit/templates` | query:discipline? | audit |
| `GET` | `/api/audit/templates/sync` | — | audit |
| `PUT` | `/api/audit/templates/{stage}` | body!, path:stage! | audit |
| `PUT` | `/api/audit/templates/{stage}/en` | body!, path:stage! | audit |
| `DELETE` | `/api/audit/{project_id}/cancel` | path:project_id! | audit |
| `POST` | `/api/audit/{project_id}/crop-blocks-only` | path:project_id!, query:force? | audit |
| `POST` | `/api/audit/{project_id}/full-audit` | path:project_id!, query:version_id? | audit |
| `DELETE` | `/api/audit/{project_id}/log` | path:project_id!, query:version_id? | audit |
| `GET` | `/api/audit/{project_id}/log` | path:project_id!, query:limit?, query:offset?, query:version_id? | audit |
| `POST` | `/api/audit/{project_id}/main-audit` | path:project_id!, query:version_id? | audit |
| `POST` | `/api/audit/{project_id}/prepare` | path:project_id!, query:version_id? | audit |
| `POST` | `/api/audit/{project_id}/prepare-data` | path:project_id!, query:force?, query:model?, query:parallelism?, query:timeout?, query:version_id? | audit |
| `GET` | `/api/audit/{project_id}/prepare-data/status` | path:project_id! | audit |
| `POST` | `/api/audit/{project_id}/pro-audit` | path:project_id!, query:version_id? | audit |
| `GET` | `/api/audit/{project_id}/prompts` | path:project_id!, query:discipline? | audit |
| `DELETE` | `/api/audit/{project_id}/prompts/{stage}` | path:project_id!, path:stage! | audit |
| `PUT` | `/api/audit/{project_id}/prompts/{stage}` | body!, path:project_id!, path:stage! | audit |
| `POST` | `/api/audit/{project_id}/resume` | path:project_id!, query:version_id? | audit |
| `GET` | `/api/audit/{project_id}/resume-info` | path:project_id!, query:version_id? | audit |
| `POST` | `/api/audit/{project_id}/retry/{stage}` | path:project_id!, path:stage!, query:version_id? | audit |
| `POST` | `/api/audit/{project_id}/skip/{stage}` | path:project_id!, path:stage! | audit |
| `POST` | `/api/audit/{project_id}/standard-audit` | path:project_id!, query:version_id? | audit |
| `POST` | `/api/audit/{project_id}/start-from` | path:project_id!, query:stage!, query:version_id? | audit |
| `GET` | `/api/audit/{project_id}/status` | path:project_id! | audit |
| `POST` | `/api/audit/{project_id}/tile-audit` | path:project_id!, query:start_from?, query:version_id? | audit |
| `POST` | `/api/audit/{project_id}/verify-norms` | path:project_id!, query:version_id? | audit |
| `POST` | `/api/auth/login` | body! | auth |
| `POST` | `/api/auth/logout` | — | auth |
| `GET` | `/api/auth/me` | — | auth |
| `GET` | `/api/critic-v2/artifact-info` | — | critic-v2-ui |
| `GET` | `/api/critic-v2/assisted-round1/files` | — | critic-v2-assisted-round1 |
| `GET` | `/api/critic-v2/assisted-round1/items` | query:group?, query:project_id? | critic-v2-assisted-round1 |
| `GET` | `/api/critic-v2/feedback-files` | query:project_id? | critic-v2-ui |
| `GET` | `/api/critic-v2/feedback-files/{name}` | path:name! | critic-v2-ui |
| `GET` | `/api/critic-v2/projects/{project_id}/triage-ui` | path:project_id! | critic-v2-ui |
| `GET` | `/api/discussions/models` | — | discussions |
| `GET` | `/api/discussions/{project_id}/list` | path:project_id!, query:type?, query:version_id? | discussions |
| `GET` | `/api/discussions/{project_id}/resolved/excel` | path:project_id!, query:type?, query:version_id? | discussions |
| `DELETE` | `/api/discussions/{project_id}/{item_id}` | path:item_id!, path:project_id!, query:version_id? | discussions |
| `GET` | `/api/discussions/{project_id}/{item_id}` | path:item_id!, path:project_id!, query:version_id? | discussions |
| `POST` | `/api/discussions/{project_id}/{item_id}/apply-revision` | body!, path:item_id!, path:project_id!, query:type?, query:version_id? | discussions |
| `POST` | `/api/discussions/{project_id}/{item_id}/chat` | body!, path:item_id!, path:project_id!, query:type?, query:version_id? | discussions |
| `POST` | `/api/discussions/{project_id}/{item_id}/chat/stream` | body!, path:item_id!, path:project_id!, query:type?, query:version_id? | discussions |
| `GET` | `/api/discussions/{project_id}/{item_id}/estimate-tokens` | path:item_id!, path:project_id!, query:type?, query:version_id? | discussions |
| `POST` | `/api/discussions/{project_id}/{item_id}/resolve` | body!, path:item_id!, path:project_id!, query:type?, query:version_id? | discussions |
| `POST` | `/api/discussions/{project_id}/{item_id}/revise` | body!, path:item_id!, path:project_id!, query:type?, query:version_id? | discussions |
| `POST` | `/api/discussions/{project_id}/{item_id}/truncate` | body!, path:item_id!, path:project_id!, query:version_id? | discussions |
| `GET` | `/api/document/{project_id}/page/{page_num}` | path:page_num!, path:project_id!, query:version_id? | document |
| `GET` | `/api/document/{project_id}/pages` | path:project_id!, query:version_id? | document |
| `GET` | `/api/document/{project_id}/pdf` | path:project_id!, query:version_id? | document |
| `GET` | `/api/export/audit-package/{project_id}` | path:project_id!, query:version_id? | export |
| `GET` | `/api/export/download/{filename}` | path:filename! | export |
| `POST` | `/api/export/excel` | query:report_type? | export |
| `POST` | `/api/export/excel/section` | body! | export |
| `GET` | `/api/external-register/_/section-map` | — | external-register |
| `POST` | `/api/external-register/import` | body! | external-register |
| `GET` | `/api/external-register/{object_id}` | path:object_id!, query:register_id? | external-register |
| `GET` | `/api/external-register/{object_id}/coverage` | path:object_id!, query:register_id? | external-register |
| `POST` | `/api/external-register/{object_id}/entry/{entry_key}/confirm` | body!, path:entry_key!, path:object_id!, query:register_id? | external-register |
| `POST` | `/api/external-register/{object_id}/entry/{entry_key}/reject` | body!, path:entry_key!, path:object_id!, query:register_id? | external-register |
| `GET` | `/api/external-register/{object_id}/export.xlsx` | path:object_id!, query:register_id? | external-register |
| `POST` | `/api/external-register/{object_id}/match` | body!, path:object_id!, query:register_id? | external-register |
| `GET` | `/api/external-register/{object_id}/registers` | path:object_id! | external-register |
| `GET` | `/api/findings/summary` | — | findings |
| `GET` | `/api/findings/{project_id}` | path:project_id!, query:category?, query:group?, query:limit?, query:offset?, query:search?, query:severity?, query:sheet?, query:version_id? | findings |
| `GET` | `/api/findings/{project_id}/block-map` | path:project_id!, query:version_id? | findings |
| `GET` | `/api/findings/{project_id}/finding/{finding_id}` | path:finding_id!, path:project_id!, query:version_id? | findings |
| `GET` | `/api/findings/{project_id}/kb-validation` | path:project_id!, query:version_id? | findings |
| `POST` | `/api/findings/{project_id}/kb-validation/run` | path:project_id!, query:model?, query:section?, query:version_id? | findings |
| `GET` | `/api/findings/{project_id}/textlayer-highlights-shadow` | path:project_id!, query:version_id? | findings |
| `GET` | `/api/info` | — | — |
| `POST` | `/api/knowledge-base/customer-confirm` | body! | knowledge-base |
| `POST` | `/api/knowledge-base/customer-unconfirm` | body! | knowledge-base |
| `GET` | `/api/knowledge-base/entries` | query:item_type?, query:limit?, query:object_id?, query:offset?, query:search?, query:section?, query:status? | knowledge-base |
| `GET` | `/api/knowledge-base/expert-review/{project_id}` | path:project_id!, query:version_id? | knowledge-base |
| `POST` | `/api/knowledge-base/expert-review/{project_id}` | body!, path:project_id!, query:version_id? | knowledge-base |
| `GET` | `/api/knowledge-base/missing-norms` | query:status? | knowledge-base |
| `POST` | `/api/knowledge-base/missing-norms/backfill` | — | knowledge-base |
| `POST` | `/api/knowledge-base/missing-norms/{doc_number}/dismiss` | path:doc_number! | knowledge-base |
| `POST` | `/api/knowledge-base/missing-norms/{doc_number}/mark-added` | path:doc_number! | knowledge-base |
| `POST` | `/api/knowledge-base/missing-norms/{doc_number}/restore` | path:doc_number! | knowledge-base |
| `GET` | `/api/knowledge-base/patterns` | — | knowledge-base |
| `POST` | `/api/knowledge-base/patterns/detect` | query:min_frequency? | knowledge-base |
| `POST` | `/api/knowledge-base/patterns/{pattern_id}/approve` | path:pattern_id! | knowledge-base |
| `POST` | `/api/knowledge-base/patterns/{pattern_id}/dismiss` | path:pattern_id! | knowledge-base |
| `POST` | `/api/knowledge-base/patterns/{pattern_id}/edit` | body!, path:pattern_id! | knowledge-base |
| `POST` | `/api/knowledge-base/revoke` | body! | knowledge-base |
| `GET` | `/api/knowledge-base/stats` | query:object_id? | knowledge-base |
| `POST` | `/api/knowledge-base/upload-excel` | body!, query:project_id?, query:version_id? | knowledge-base |
| `GET` | `/api/objects` | — | objects |
| `POST` | `/api/objects` | body! | objects |
| `POST` | `/api/objects/switch` | body! | objects |
| `DELETE` | `/api/objects/{object_id}` | path:object_id! | objects |
| `PUT` | `/api/objects/{object_id}` | body!, path:object_id! | objects |
| `GET` | `/api/optimization/section/{section_code}` | path:section_code!, query:object_id? | optimization |
| `POST` | `/api/optimization/section/{section_code}/pipeline/graphics-plan` | path:section_code!, query:object_id? | optimization |
| `POST` | `/api/optimization/section/{section_code}/pipeline/run` | path:section_code!, query:object_id? | optimization |
| `GET` | `/api/optimization/section/{section_code}/pipeline/status` | path:section_code!, query:object_id? | optimization |
| `GET` | `/api/optimization/section/{section_code}/replications` | path:section_code!, query:object_id? | optimization |
| `POST` | `/api/optimization/section/{section_code}/replications/start` | body!, path:section_code!, query:object_id? | optimization |
| `POST` | `/api/optimization/section/{section_code}/replications/start-all` | path:section_code!, query:object_id? | optimization |
| `GET` | `/api/optimization/section/{section_code}/replications/{replication_id}` | path:replication_id!, path:section_code!, query:include_dossier?, query:object_id? | optimization |
| `POST` | `/api/optimization/section/{section_code}/replications/{replication_id}/graphics/retry` | path:replication_id!, path:section_code!, query:object_id? | optimization |
| `GET` | `/api/optimization/summary/all` | — | optimization |
| `GET` | `/api/optimization/{project_id}` | path:project_id!, query:version_id? | optimization |
| `GET` | `/api/optimization/{project_id}/block-map` | path:project_id!, query:version_id? | optimization |
| `DELETE` | `/api/optimization/{project_id}/cancel` | path:project_id! | optimization |
| `POST` | `/api/optimization/{project_id}/run` | path:project_id!, query:version_id? | optimization |
| `GET` | `/api/optimization/{project_id}/status` | path:project_id!, query:version_id? | optimization |
| `GET` | `/api/project-groups` | query:object_id? | groups |
| `PUT` | `/api/project-groups/{section}` | body!, path:section! | groups |
| `DELETE` | `/api/project-groups/{section}/{group_id}` | path:group_id!, path:section!, query:object_id? | groups |
| `GET` | `/api/projects` | — | projects |
| `GET` | `/api/projects-v2-shadow/cutover-readiness` | query:per_type? | projects-v2-shadow |
| `GET` | `/api/projects-v2-shadow/documents` | query:analysis_status?, query:discipline?, query:limit?, query:object_folder? | projects-v2-shadow |
| `GET` | `/api/projects-v2-shadow/documents/{document_id_or_code}` | path:document_id_or_code!, query:discipline?, query:object_folder? | projects-v2-shadow |
| `GET` | `/api/projects-v2-shadow/documents/{document_id_or_code}/snapshot` | path:document_id_or_code!, query:discipline?, query:object_folder? | projects-v2-shadow |
| `GET` | `/api/projects-v2-shadow/documents/{document_id_or_code}/versions` | path:document_id_or_code!, query:discipline?, query:object_folder? | projects-v2-shadow |
| `GET` | `/api/projects-v2-shadow/dual-read/document/{document_code}` | path:document_code!, query:object_id? | projects-v2-shadow |
| `GET` | `/api/projects-v2-shadow/dual-read/sample` | query:per_type? | projects-v2-shadow |
| `GET` | `/api/projects-v2-shadow/health` | — | projects-v2-shadow |
| `GET` | `/api/projects-v2-shadow/objects` | — | projects-v2-shadow |
| `GET` | `/api/projects-v2-shadow/parity/sample` | — | projects-v2-shadow |
| `GET` | `/api/projects-v2-shadow/ui-contract/sample` | query:per_type? | projects-v2-shadow |
| `POST` | `/api/projects/detect-discipline` | body! | projects |
| `GET` | `/api/projects/disciplines` | — | projects |
| `POST` | `/api/projects/disciplines` | body! | projects |
| `POST` | `/api/projects/disciplines/reorder` | body! | projects |
| `DELETE` | `/api/projects/disciplines/{code}` | path:code! | projects |
| `PUT` | `/api/projects/disciplines/{code}` | body!, path:code! | projects |
| `POST` | `/api/projects/register` | body! | projects |
| `POST` | `/api/projects/register-external` | body! | projects |
| `GET` | `/api/projects/scan` | — | projects |
| `POST` | `/api/projects/scan-external` | body! | projects |
| `POST` | `/api/projects/upload-folder` | body! | projects |
| `POST` | `/api/projects/upload-folder/precheck` | body! | projects |
| `POST` | `/api/projects/versions/from-candidate` | body! | projects |
| `POST` | `/api/projects/versions/from-project` | body! | projects |
| `DELETE` | `/api/projects/{project_id}` | path:project_id! | projects |
| `GET` | `/api/projects/{project_id}` | path:project_id!, query:version_id? | projects |
| `DELETE` | `/api/projects/{project_id}/clean` | path:project_id!, query:_confirmed?, query:version_id? | projects |
| `GET` | `/api/projects/{project_id}/config` | path:project_id! | projects |
| `POST` | `/api/projects/{project_id}/hide` | path:project_id! | projects |
| `PUT` | `/api/projects/{project_id}/pipeline-version` | body!, path:project_id! | projects |
| `PATCH` | `/api/projects/{project_id}/rename` | body!, path:project_id! | projects |
| `POST` | `/api/projects/{project_id}/restore-clean` | body!, path:project_id! | projects |
| `PUT` | `/api/projects/{project_id}/section` | body!, path:project_id! | projects |
| `POST` | `/api/projects/{project_id}/unhide` | path:project_id! | projects |
| `GET` | `/api/projects/{project_id}/versions` | path:project_id! | projects |
| `POST` | `/api/projects/{project_id}/versions` | body!, path:project_id! | projects |
| `POST` | `/api/projects/{project_id}/versions/ensure-manifest` | path:project_id! | projects |
| `DELETE` | `/api/projects/{project_id}/versions/{version_id}` | path:project_id!, path:version_id! | projects |
| `GET` | `/api/projects/{project_id}/versions/{version_id}/files` | path:project_id!, path:version_id! | projects |
| `POST` | `/api/projects/{project_id}/versions/{version_id}/files` | body!, path:project_id!, path:version_id! | projects |
| `POST` | `/api/projects/{project_id}/versions/{version_id}/migrated-findings/check` | path:project_id!, path:version_id! | migrated_findings |
| `GET` | `/api/projects/{project_id}/versions/{version_id}/migrated-findings/report` | path:project_id!, path:version_id! | migrated_findings |
| `POST` | `/api/projects/{target_project_id}/versions/from-candidate` | body!, path:target_project_id! | projects |
| `POST` | `/api/projects/{target_project_id}/versions/from-project` | body!, path:target_project_id! | projects |
| `GET` | `/api/schedule` | query:from?, query:object_id?, query:to? | schedule |
| `GET` | `/api/schedule/plan` | query:from?, query:object_id?, query:period_type?, query:to? | schedule |
| `PUT` | `/api/schedule/plan` | body! | schedule |
| `GET` | `/api/stage-comparison/objects` | — | stage-comparison |
| `POST` | `/api/stage-comparison/objects/{object_id}/stages/{stage_name}/upload` | body!, path:object_id!, path:stage_name! | stage-comparison |
| `POST` | `/api/stage-comparison/objects/{object_id}/stages/{stage_name}/upload-folder` | body!, path:object_id!, path:stage_name! | stage-comparison |
| `GET` | `/api/stage-comparison/sessions` | — | stage-comparison |
| `POST` | `/api/stage-comparison/sessions` | body! | stage-comparison |
| `GET` | `/api/stage-comparison/sessions/{session_id}` | path:session_id! | stage-comparison |
| `PUT` | `/api/stage-comparison/sessions/{session_id}/document-pairing` | body!, path:session_id! | stage-comparison |
| `POST` | `/api/stage-comparison/sessions/{session_id}/document-pairing/suggest` | path:session_id! | stage-comparison |
| `POST` | `/api/stage-comparison/sessions/{session_id}/pairs` | body!, path:session_id! | stage-comparison |
| `GET` | `/api/stage-comparison/sessions/{session_id}/pairs/{pair_id}` | path:pair_id!, path:session_id! | stage-comparison |
| `GET` | `/api/stage-comparison/sessions/{session_id}/pairs/{pair_id}/graphic-comparison` | path:pair_id!, path:session_id! | stage-comparison |
| `POST` | `/api/stage-comparison/sessions/{session_id}/pairs/{pair_id}/graphic-comparison` | body!, path:pair_id!, path:session_id! | stage-comparison |
| `GET` | `/api/stage-comparison/sessions/{session_id}/pairs/{pair_id}/high-level-project-changes` | path:pair_id!, path:session_id! | stage-comparison |
| `POST` | `/api/stage-comparison/sessions/{session_id}/pairs/{pair_id}/high-level-project-changes` | path:pair_id!, path:session_id! | stage-comparison |
| `GET` | `/api/stage-comparison/sessions/{session_id}/pairs/{pair_id}/page-info` | path:pair_id!, path:session_id!, query:page?, query:side! | stage-comparison |
| `GET` | `/api/stage-comparison/sessions/{session_id}/pairs/{pair_id}/page-preview` | path:pair_id!, path:session_id!, query:page?, query:side!, query:width? | stage-comparison |
| `GET` | `/api/stage-comparison/sessions/{session_id}/pairs/{pair_id}/page-svg` | path:pair_id!, path:session_id!, query:page?, query:side! | stage-comparison |
| `GET` | `/api/stage-comparison/sessions/{session_id}/pairs/{pair_id}/page-thumb` | path:pair_id!, path:session_id!, query:page?, query:side!, query:width? | stage-comparison |
| `GET` | `/api/stage-comparison/sessions/{session_id}/pairs/{pair_id}/page-tile` | path:pair_id!, path:session_id!, query:level?, query:page?, query:side!, query:x?, query:y? | stage-comparison |
| `GET` | `/api/stage-comparison/sessions/{session_id}/pairs/{pair_id}/sheet-link-repairs` | path:pair_id!, path:session_id! | stage-comparison |
| `POST` | `/api/stage-comparison/sessions/{session_id}/pairs/{pair_id}/sheet-link-repairs/{repair_id}/undo` | path:pair_id!, path:repair_id!, path:session_id! | stage-comparison |
| `PUT` | `/api/stage-comparison/sessions/{session_id}/pairs/{pair_id}/sheet-links` | body!, path:pair_id!, path:session_id! | stage-comparison |
| `POST` | `/api/stage-comparison/sessions/{session_id}/pairs/{pair_id}/sheet-match-suggestions` | path:pair_id!, path:session_id! | stage-comparison |
| `GET` | `/api/stage-comparison/sessions/{session_id}/pairs/{pair_id}/sheet-matches` | path:pair_id!, path:session_id! | stage-comparison |
| `GET` | `/api/stage-comparison/sessions/{session_id}/pairs/{pair_id}/text-ai-review` | path:pair_id!, path:session_id! | stage-comparison |
| `POST` | `/api/stage-comparison/sessions/{session_id}/pairs/{pair_id}/text-ai-review` | path:pair_id!, path:session_id! | stage-comparison |
| `GET` | `/api/stage-comparison/sessions/{session_id}/pairs/{pair_id}/text-change-summary` | path:pair_id!, path:session_id! | stage-comparison |
| `POST` | `/api/stage-comparison/sessions/{session_id}/pairs/{pair_id}/text-change-summary` | path:pair_id!, path:session_id! | stage-comparison |
| `GET` | `/api/stage-comparison/sessions/{session_id}/pairs/{pair_id}/text-comparison` | path:pair_id!, path:session_id! | stage-comparison |
| `POST` | `/api/stage-comparison/sessions/{session_id}/pairs/{pair_id}/text-comparison` | path:pair_id!, path:session_id! | stage-comparison |
| `GET` | `/api/stage-comparison/sessions/{session_id}/pairs/{pair_id}/text-differences` | path:pair_id!, path:session_id! | stage-comparison |
| `POST` | `/api/stage-comparison/sessions/{session_id}/pairs/{pair_id}/text-differences` | path:pair_id!, path:session_id! | stage-comparison |
| `GET` | `/api/stage-comparison/sessions/{session_id}/pairs/{pair_id}/text-entities` | path:pair_id!, path:session_id! | stage-comparison |
| `GET` | `/api/stage-comparison/sessions/{session_id}/pairs/{pair_id}/text-exclusions` | path:pair_id!, path:session_id! | stage-comparison |
| `GET` | `/api/stage-comparison/sessions/{session_id}/pairs/{pair_id}/text-final-comparison` | path:pair_id!, path:session_id! | stage-comparison |
| `GET` | `/api/stage-comparison/sessions/{session_id}/pairs/{pair_id}/text-search` | path:pair_id!, path:session_id!, query:query!, query:side! | stage-comparison |
| `GET` | `/api/tiles/{project_id}/blocks` | path:project_id!, query:version_id? | blocks |
| `GET` | `/api/tiles/{project_id}/blocks/analysis` | path:project_id!, query:version_id? | blocks |
| `GET` | `/api/tiles/{project_id}/blocks/image/{block_id}` | path:block_id!, path:project_id!, query:version_id? | blocks |
| `GET` | `/api/tiles/{project_id}/blocks/llm-text/{block_id}` | path:block_id!, path:project_id!, query:page?, query:version_id? | blocks |
| `GET` | `/api/tiles/{project_id}/blocks/region-image/{block_id}` | path:block_id!, path:project_id!, query:version_id? | blocks |
| `POST` | `/api/usage/clear-all` | — | usage |
| `GET` | `/api/usage/config` | — | usage |
| `GET` | `/api/usage/counters` | — | usage |
| `GET` | `/api/usage/global` | — | usage |
| `POST` | `/api/usage/global/clear-display` | — | usage |
| `POST` | `/api/usage/global/limits` | query:session_5h?, query:weekly_all? | usage |
| `POST` | `/api/usage/global/refresh` | — | usage |
| `POST` | `/api/usage/global/reset-offsets` | — | usage |
| `POST` | `/api/usage/global/set-percent` | body! | usage |
| `POST` | `/api/usage/global/weekly-reset` | query:hour_utc?, query:weekday? | usage |
| `GET` | `/api/usage/history` | query:limit? | usage |
| `GET` | `/api/usage/paid-api/status` | — | usage |
| `GET` | `/api/usage/paid-cost` | — | usage |
| `GET` | `/api/usage/paid-cost/blocked-events` | query:limit? | usage |
| `GET` | `/api/usage/paid-cost/daily` | query:days? | usage |
| `GET` | `/api/usage/paid-cost/events` | query:limit? | usage |
| `POST` | `/api/usage/paid-cost/monthly/calibrate` | body! | usage |
| `POST` | `/api/usage/paid-cost/reset` | — | usage |
| `GET` | `/api/usage/project/{project_id}` | path:project_id! | usage |
| `GET` | `/api/usage/projects-summary` | — | usage |
| `POST` | `/api/usage/reset-session` | — | usage |
| `GET` | `/api/usage/subscription-by-person` | query:days? | usage |
| `GET` | `/api/users` | — | users |
| `POST` | `/api/users` | body! | users |
| `POST` | `/api/users/switch` | body! | users |
| `DELETE` | `/api/users/{user_id}` | path:user_id! | users |
| `PUT` | `/api/users/{user_id}` | body!, path:user_id! | users |
| `GET` | `/api/users/{user_id}/activity` | path:user_id! | users |
| `GET` | `/api/workers/me` | — | audit-workers-admin |
| `GET` | `/api/workers/status` | — | audit-workers-admin |
| `GET` | `/audit-workers` | — | — |
| `GET` | `/login` | — | — |
