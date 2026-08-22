# OSR Execution Fabric

## Goal
Minimize direct user interaction with terminals and machines while preserving fast, cheap, auditable execution.

## Routing rule

### Cloud compute path
Use GitHub Actions standard hosted runners for public-repository work that is:
- heavy indexing or corpus scanning;
- general shardable data processing, transforms, aggregation, feature extraction, validation, conversion, or batch analysis;
- embarrassingly parallel or bounded into independent workers;
- based on public source data such as Hugging Face;
- reproducible without private Mac-local state.

The 508GB OSR corpus must not be downloaded, scanned, or cached on the user's Mac. Fetch source shards directly from the public upstream, process one shard or bounded batch at a time, emit compact results, then delete transient source data.

### Mac execution path
Use OSR Watcher only when execution genuinely requires Mac-local state or permissions, including local files, rclone credentials, Google Drive-local operations, or locally installed CLIs.

Mac tasks must be repo-defined, hash-locked, bounded, and auditable. Avoid arbitrary shell execution. Results return through the existing OSR RemoteControl channel.

## Standard lifecycle
Idea -> classify execution surface -> create/update repo task -> smoke test -> inspect result -> scale only after smoke passes -> reduce/merge -> persist compact result -> update Notion state.

## Cost and safety gates
1. Default to one worker and one representative shard.
2. Scale only after a passing smoke result.
3. Standard hosted runners only unless explicitly approved.
4. Matrix concurrency cap: 20 workers.
5. Never store the 508GB corpus as GitHub artifacts.
6. Artifacts contain only compact outputs, manifests, logs, indexes, or hit locators.
7. Heavy tasks should be resumable and idempotent.
8. A failed worker must not invalidate successful shards; use checkpoints.
9. Repeated future queries should prefer a reusable compact/specialized index when that saves repeated I/O, but never build a giant index merely because indexing is possible.
10. Paid/larger/GPU runners, Colab paid compute, Replit agent compute, and paid VMs require explicit approval; they are not the default execution plane.

## Generic compute template
`.github/workflows/osr_compute_template.yml`

Inputs:
- `task_id`: stable run identifier.
- `task_mode`: `single` or `matrix`.
- `worker_count`: 1-20.
- `task_script`: repo-relative Python file under `tasks/` only.
- `task_args`: JSON input passed to the task.

Each task implements a bounded worker interface and writes only to its supplied output directory. The workflow uploads short-lived worker artifacts and commits a compact manifest back to the repository.

## Stage-2 cheap-player direct miner
Primary implementation:
- `.github/workflows/osr-stage2-direct-miner.yml`
- `tools/osr_stage2_actions_direct_miner.py`
- `control/stage2_query_pack.json`
- `control/stage2_direct_miner_request.json`
- `control/stage2_direct_miner_status.json`

The miner enumerates the two public Hugging Face corpora, partitions the 1,788 Parquet shards across 1-20 workers, downloads one shard at a time to ephemeral `/tmp`, scans the text column, stores exhaustive term counts plus capped locators/snippets, deletes the source shard immediately, and emits only compact compressed results. Query packs may evolve without changing the execution fabric.

## Benchmark ledger — 2026-08-22
### Mac / Google Drive path — REJECTED for 508GB compute
- rclone 64 MiB sequential head: **2.4 MiB/s** (26.44 s)
- 1 MiB tail latency: **3.224 s**
- one 76.6 MiB shard hydration: **1.7 MiB/s** (44.12 s)
- local Parquet footer after hydration: **0.001 s**
Conclusion: CPU/Parquet parsing is not the bottleneck; remote Drive transfer is. Mac remains control/local-permission plane only.

### GitHub Actions + Hugging Face — VERIFIED preferred data plane
Single-shard transport smoke:
- file: `literature_zh-00233-of-00233.parquet`
- bytes: **80,314,697**
- download: **1.837 s = 41.698 MiB/s**
- rows: **9,660**; row groups: **1**
- Parquet footer: **0.00068 s**

Two-worker end-to-end direct-mining smoke:
- run: `stage2-cheap-smoke-001`
- workers: **2/2 PASS**
- shards scanned: **2**
- aggregate bytes: **254,764,608 (0.237 GiB)**
- max worker wall time: **6.081 s**
Conclusion: direct HF -> hosted runner -> scan -> compact result -> reducer writeback works end-to-end.

### Permanent-index experiments — NOT default
Quickwit/Tantivy full-text pilot:
- sampled text: **53,189,535 bytes**
- index: **327,465,051 bytes**
- expansion: **6.1566x**
- ingest throughput: **3.52 MiB/s**
- query latency: roughly **6-7 ms**
Decision: reject full 508GB backfill; projected storage is economically wasteful.

Tantivy 3-gram locator pilot:
- sampled text: **53,189,535 bytes**
- index: **96,793,020 bytes**
- expansion: **1.8198x**
- query latency: roughly **0.34-0.42 ms**
Decision: keep as an optional specialized index for high-frequency query families, not as the universal primary index.

## Default decision
If the user says “弄 / run / test / index / scan / process data” and the work can run without Mac-private state, prefer GitHub Actions. If Mac-private state is required, prefer OSR Watcher. Asking the user to open Terminal is the fallback, not the default.
