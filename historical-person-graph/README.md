# OSR Historical Person Graph × Kimi MVP

This is a downstream, provenance-first prototype for the **二十六史 Person Graph Explorer**. It deliberately does **not** modify raw Stage-2 Parquet, checkpoints, or the PR #17 production runner.

## Pipeline

```text
OSR Stage-2 snippet / rehydrated row
  -> Sub2API / Kimi extractor
  -> conservative entity resolution
  -> event atoms
  -> temporal relation edges
  -> Historical Slices
  -> SQLite canonical store
  -> graph.json
  -> touch/click explorer.html
```

The LLM is an extractor/compiler, not the source of truth. Every derived event, edge and slice keeps a `source_id`; sources keep Stage-2 provenance and row SHA-256. Ambiguous identity stays `OPEN` instead of being silently merged.

## Historical Slice schema

The first MVP uses 12 reusable slice families:

- `DECISION`
- `WAR_COMMAND`
- `POWER`
- `RELATION`
- `FAMILY_SUCCESSION`
- `TRUST_BETRAYAL`
- `GOVERNANCE`
- `CRISIS`
- `FAILURE_BLINDSPOT`
- `LANGUAGE_SELF_MODEL`
- `HISTORIOGRAPHY_BIAS`
- `DYAD_INTERACTION`

A single event may emit multiple slices. A slice is a bounded observation, **not** a lifetime personality label.

## Input

`tools/osr_historical_person_graph.py` accepts:

1. PR #17 Stage-2 `result.json` / `result.json.gz` sample output; or
2. JSONL from Stage-2B / row rehydration. Each row only needs `text`/`snippet`/`content`; all extra fields are preserved as provenance.

For serious historical runs prefer rehydrated row JSONL over bounded Stage-2 representative samples.

## Kimi via the existing Sub2API gateway

Preferred environment variables:

```bash
export SUB2API_BASE_URL='https://YOUR-GATEWAY'
export SUB2API_API_KEY='...'
export SUB2API_MODEL='YOUR-KIMI-ROUTE-OR-MODEL'
```

Direct Kimi-compatible credentials can also be supplied with `KIMI_BASE_URL`, `KIMI_API_KEY`, and `KIMI_MODEL`. Real credentials must stay outside Git.

The default chat path is `/v1/chat/completions`; override it if the configured gateway exposes a different OpenAI-compatible path:

```bash
python tools/osr_historical_person_graph.py build \
  --input /path/to/result.json.gz \
  --db /path/to/historical_person_graph.sqlite \
  --graph-json /path/to/graph.json \
  --max-records 20
```

A safe first pass is `--max-records 20`. Re-running is resumable/idempotent for already compiled `(source, model, schema_version)` rows unless `--force` is supplied.

## Offline validation

No model key is required:

```bash
PYTHONPATH=tools python tools/osr_historical_person_graph_smoke.py
```

Expected result:

```json
{"status":"PASS","nodes":2,"edges":1,"events":1,"slices":1}
```

## Explorer

Open `historical-person-graph/explorer.html`, choose the generated `graph.json`, then:

- search a person/alias;
- tap/click a person to recenter and expand first-hop relations;
- filter relation type;
- move the time slider (double-click it to return to all time);
- inspect events, temporal relations, Historical Slices, and source provenance.

The UI is intentionally dependency-free so the first regression can run from a local file on desktop/mobile without a frontend build.

## First regression cluster

Do **not** start with the full 508GB scan. Use already verified row-store / rehydrated samples for:

1. 后凉：吕光 → 吕绍 → 吕纂 → 吕隆 / 吕超
2. 后秦：姚苌 → 姚兴 → 姚泓
3. 刘裕 and the nodes directly connected to the Later Qin terminal phase

Acceptance gates before scaling:

- source provenance survives end-to-end;
- rerun is idempotent;
- same-name/title ambiguity is not auto-merged;
- relation edges can change over time;
- every slice is traceable to evidence;
- the explorer can recenter by touch/click and expose source/event/slice layers.

## Deliberately out of scope for v0.1

- automatic cross-document entity merge without a separate adjudication pass;
- Agent Genome synthesis from too few slices;
- inferred dates not present in source text;
- full Stage-2 production scan;
- writing CANON/novel interpretations into the historical fact store.
