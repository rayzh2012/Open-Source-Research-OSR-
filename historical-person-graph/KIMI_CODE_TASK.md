# Kimi Code Task — Historical Person Graph gold-20

Work on branch `historical-person-graph-kimi-mvp` in `rayzh2012/Open-Source-Research-OSR-`.

## Goal

Run and harden the first real 20-record Lv Guang extraction without changing the Stage-2 production miner or raw corpus pipeline.

Pipeline under test:

`gold-20 / Stage-2 snippet -> Sub2API/Kimi -> entity split -> event atom -> temporal relation edge -> Historical Slice -> SQLite -> graph.json -> explorer.html`

## Historical safety rules

1. Treat the model as extractor/compiler, never canonical truth.
2. Use only supplied snippets. Do not add biography from model memory.
3. Preserve `FACT / INFERENCE / OPEN`.
4. Context-free same-name mentions must remain source-scoped OPEN; never silently merge.
5. Do not infer family relation from surname/clan alone.
6. A single action cannot become a lifetime personality trait.
7. Historiography/narrative claims go to `HISTORIOGRAPHY_BIAS`, not mind-reading FACT.
8. Do not modify `tools/osr_stage2_actions_direct_miner.py`, raw Parquet logic, or Stage-2 checkpoints.
9. Do not print, commit, or echo API keys.
10. If a source is research synthesis rather than a primary quote, preserve that provenance and do not upgrade it to primary evidence.

## Inputs

- `historical-person-graph/fixtures/lvguang_gold_20.jsonl`
- `tools/osr_historical_person_graph.py`
- `historical-person-graph/run_kimi_gold20.sh`
- `historical-person-graph/explorer.html`

The fixture is deliberately mixed:
- exact primary quotations carried through the Drive audit;
- primary phrase + bounded synthesis;
- lost-source fragments preserved through later quotation layers;
- textual variants that must remain variants.

## Execution

Assume the environment already provides a project-specific gateway key:

```bash
export SUB2API_BASE_URL='...'
export SUB2API_API_KEY='...'
export SUB2API_MODEL='...'
```

Then run:

```bash
bash historical-person-graph/run_kimi_gold20.sh
```

Do not paste credentials into shell history if a safer environment injection mechanism is available.

## Acceptance criteria

The run must produce:

- exactly 20 source records in SQLite / graph JSON;
- >= 1 resolved/candidate Lv Guang node;
- events and Historical Slices for the evidence-bearing records;
- no silent merge of an unrelated same-name person;
- every event/edge/slice traceable to `source_id` and stored provenance;
- no source upgraded from synthesis to primary by the extractor;
- parser survives fenced JSON or surrounding text;
- repeated run is idempotent unless `--force` is used;
- explorer can load the produced `lvguang_gold_20.graph.json`.

## Review targets

After the first run, inspect failures in this order:

1. JSON/API compatibility (`/v1/chat/completions`, response shape, model alias).
2. Provenance loss or certainty inflation.
3. Entity resolution mistakes.
4. Event over-splitting / under-splitting.
5. Temporal relation edge quality.
6. Slice assignment quality, especially `TRUST_BETRAYAL`, `WAR_COMMAND`, `FAMILY_SUCCESSION`, `HISTORIOGRAPHY_BIAS`.
7. UI usefulness for one-hop historical exploration.

## Patch policy

Make the smallest patch that fixes observed failures. Add or extend tests for every bug found. Do not redesign the whole architecture after one 20-record run.

At completion, report:

- exact model route used (model alias only, no credential);
- processed / failed counts;
- node / edge / event / slice counts;
- entity-resolution errors found;
- certainty/provenance errors found;
- files changed;
- next highest-information-gain test.
