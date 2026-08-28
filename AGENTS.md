# OSR Agent Instructions

## Mission
Maintain and extend the Open-Source-Research OSR pipeline with reproducible, resumable, source-grounded data processing. Prefer small validation steps before expensive corpus-wide work.

## Current execution model
- Repository: `~/Open-Source-Research-OSR-`
- Google Drive is archival/state storage, not the preferred 508GB compute data plane.
- The 508GB corpus consists of 1,788 Parquet shards: Literature-zh (233) + ChineseWebText2.0-HighQuality (1,555).
- Google Drive for Desktop/FUSE is too slow/unreliable for large Parquet scans. Do not recursively traverse `~/Library/CloudStorage/.../My Drive`.
- When Drive access is needed on Mac, prefer `rclone gdrive:` and exact folder IDs/paths.
- For large scans, favor shard-at-a-time processing and resumable outputs. Never require all 508GB to fit locally.

## Safety and correctness gates
- Never launch the full Stage-2 scan unless Stage-1 identity and the Stage-2 minimal preflight have passed.
- Preserve `manifest_sha256` binding between Stage-1 and Stage-2 checkpoints.
- Treat checkpoint reuse as invalid if corpus identity changes.
- Prefer deterministic locators and raw-row SHA verification.
- Do not silently weaken schema, shard-count, ordinal, or identity checks to make a run pass.

## Development workflow
1. Inspect existing code and current git diff before editing.
2. Make the smallest change that fixes the issue.
3. Run focused tests or a smoke check before broader execution.
4. Summarize changed files, validation performed, remaining risk, and exact next step.
5. Avoid committing generated corpus data, credentials, OAuth tokens, API keys, or large artifacts.

## Kimi Code automation
- Non-interactive work should use `kimi -p "<task>" --output-format stream-json`.
- Work only inside this repository unless a task explicitly names another workspace.
- Do not expose secrets from `~/.config/rclone`, OAuth tokens, Keychain, or environment variables in logs.
- When asked to modify code, edit the repository and validate the change instead of only explaining what to do.
