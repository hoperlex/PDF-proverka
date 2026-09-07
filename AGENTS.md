# Agent development safety

Development happens directly in `/home/coder/projects/PDF-proverka` on `main`,
in small isolated commits. No per-task feature branches, no per-task Git
worktrees.

This checkout is also the deployment source, so keep it releasable:

- one logical change = one commit on `main`; stage only the files that belong
  to the task (never `git add -A`);
- do not leave long-lived uncommitted work in the tree — a dirty tree blocks
  `scripts/production_source_guard.py` and therefore blocks release builds;
- the live portal is not served from this tree (it runs from
  `/home/coder/auditmanager/current`), so editing files here never changes
  production by itself — only a new release does;
- before a release, the commit must be reachable from `origin/main`; that is
  still enforced by `scripts/production_source_guard.py` (see
  `docs/production_source_guard.md`).

## Bounded acceptance and rework

The mandatory project policy is
`docs/architecture/ACCEPTANCE_REWORK_POLICY_V1.md` (`acceptance-rework/v1`).
For every task, slice, checkpoint, gate, or release candidate entering formal
acceptance:

- freeze the candidate SHA, allowed paths, non-goals, and verification command
  before the first full regression gate;
- run targeted checks and capability probes first; a known-red preflight must
  never be promoted into a full gate;
- allow at most **two full-gate attempts total**: the initial attempt and one
  final attempt after at most one in-scope remediation commit;
- count every started full gate, including timeout, cancellation, invalid
  JUnit, and environment failure; there are no automatic retries;
- after the first failure, classify findings before editing. Only a
  candidate-caused regression inside the frozen scope may be fixed in the same
  acceptance window. Pre-existing/flaky, environment/evidence, and unrelated
  findings are recorded separately and do not expand the candidate;
- after the second unsuccessful attempt, stop. Split or reject the candidate,
  or mark the window externally blocked. A third attempt requires an explicit
  human-owner decision starting a new documented acceptance window;
- do not rerun the full regression gate for receipt/publication-only or other
  non-executable documentation changes after a source candidate is green.

Do not keep checking and patching until green. Reaching the attempt limit is a
required terminal outcome, not permission to continue autonomously.
