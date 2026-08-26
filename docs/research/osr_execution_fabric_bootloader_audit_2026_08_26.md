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

Open control-plane bug: current feature workflow hard-codes matrix max-parallel 20 even though request asks 12. Recorded; not fixed in this Bootloader session because targeted patching of the large heavy workflow is preferable to risky full-file rewrite.

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
