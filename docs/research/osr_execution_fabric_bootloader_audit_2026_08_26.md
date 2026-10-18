# OSR Execution Fabric Bootloader Audit v1.4

Bootloader snapshot: 2026-08-26
Notion: `3c82a508-97fd-8154-952e-fe89cea841ce`

## Cost gate
Verified implementation: public repo + approved standard Ubuntu runners + anonymous public Hugging Face only. HF auth tokens or private repo fail closed; paid compute is not allowed by current preflight policy.

## Current M3 truth
Current request: `feature-store-v1-resilient-001`, 128 partitions, requested max_parallel 12, 1,788 shards.

Durable status/catalog now exist and are PARTIAL:
- complete partitions 2/128
- shards 28/1788
- missing 1760
- rows scanned 3,093,566
- signal rows 1,746,459
- release integrity FAIL after cancelled trigger run

Thus old `TRIGGERED / NO FINAL WRITEBACK` is superseded, but M3 FULL PASS is still false.

### 2026-08-27 control-plane fix — HAN-94 CLOSED
The previous concurrency contradiction is fixed and independently read back:
- `plan.outputs.max_parallel` is now emitted from the validated request value;
- `GITHUB_OUTPUT` now carries `max_parallel`;
- both `extract.strategy.max-parallel` and `recover.strategy.max-parallel` use `fromJson(needs.plan.outputs.max_parallel)`;
- current request value `12` therefore resolves to matrix cap `12` in both jobs;
- the previous two hard-coded `max-parallel: 20` entries are gone.

Implementation commit: `00511a32f160a0a33a9f53177c80d74abc3afc64`.
Durable proof: `control/feature_concurrency_control_plane_check.json` = PASS for request `feature-store-v1-resilient-001`, requested/resolved max_parallel `12`, validated range `1..20`.

The patch did **not** modify `control/feature_extraction_request.json`; recent stage2 Actions readback showed no new `OSR 508GB Feature Extraction` run from this control-plane change. M3 remains PARTIAL at 28/1788 shards: fixing scheduler control is not Feature Store completion.

## M4
M4 already listens through `workflow_run`, but its old gate checked obsolete 20-worker M3 fields. Fixed on 2026-08-26 to gate against resilient M3 status + catalog + release-integrity objects.

Fix commit: `c4fc20c7c3e0d5c2b707240b565ed58368381557`.

M4 must not aggregate until M3 is strict PASS: all requested partitions complete, 1,788/1,788 shards, zero missing, catalog PASS, release integrity PASS.

## M5 current pointer
`control/m5_exact_evidence_summary.json` currently points to `m5-exact-ming-qing-myth-dense-smoke-001`: PASS, Top-4, 120 rows, 7,210,395,643 downloaded bytes, 120 source-profile-cue rows, 120 unique source titles.

The earlier 311-row source-ancestor experiment remains a historical bounded research result; it is no longer the current pointer. Its compact repair request still exists, but `control/research_runs/m5-exact-source-ancestor-smoke-001/run_manifest.json` remains absent, so repair is TRIGGERED / NOT VERIFIED COMPLETE.

## Routing rule
Dense late sources are discovery infrastructure, not chronology authority. Use compact/router/sketch layers to reduce raw I/O, then exact evidence; return to early originals/version provenance for origin and historical claims.

## Multi-corpus plane
Wikisource, Kanripo/KR5, CBETA, OpenITI and curated-corpus ingest paths are part of the expanded Fabric. Their statuses are mixed and must be verified per-source; existence of a workflow is not a PASS claim.
