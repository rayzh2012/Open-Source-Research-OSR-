# OSR Execution Fabric

## Goal
Minimize direct user interaction with terminals and machines while preserving fast, cheap, auditable execution.

## Routing rule

### Cloud compute path
Use GitHub Actions standard hosted runners for public-repository work that is:
- heavy indexing or corpus scanning;
- embarrassingly parallel or shardable;
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
9. Repeated future queries should prefer a reusable index over rescanning all source data.

## Generic compute template
`.github/workflows/osr_compute_template.yml`

Inputs:
- `task_id`: stable run identifier.
- `task_mode`: `single` or `matrix`.
- `worker_count`: 1-20.
- `task_script`: repo-relative Python file under `tasks/` only.
- `task_args`: JSON input passed to the task.

Each task implements a bounded worker interface and writes only to its supplied output directory. The workflow uploads short-lived worker artifacts and commits a compact manifest back to the repository.

## Default decision
If the user says “弄 / run / test / index / scan” and the work can run without Mac-private state, prefer GitHub Actions. If Mac-private state is required, prefer OSR Watcher. Asking the user to open Terminal is the fallback, not the default.

## Verified benchmark
2026-08-22 Stage-2 smoke: `literature_zh-00233-of-00233.parquet`, 80,314,697 bytes, downloaded by GitHub Actions in 1.837 s at 41.698 MiB/s; 9,660 rows; Parquet footer read in 0.00068 s. This validated GitHub Actions + Hugging Face as the preferred 508GB data plane.
