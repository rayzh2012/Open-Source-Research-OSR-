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
11. Event/relation/slice `evidence` must be a literal substring of the supplied snippet; invented pseudo-quotes are a hard failure.

## Inputs

- `historical-person-graph/fixtures/lvguang_gold_20.jsonl`
- `historical-person-graph/fixtures/lvguang_gold_20_expectations.json`
- `tools/osr_historical_person_graph.py`
- `tools/osr_historical_person_graph_audit.py`
- `historical-person-graph/run_kimi_gold20.sh`
- `historical-person-graph/explorer.html`

The fixture is deliberately mixed:
- exact primary quotations carried through the Drive audit;
- primary phrase + bounded synthesis;
- lost-source fragments preserved through later quotation layers;
- textual variants that must remain variants.

## Lower control already measured

The deterministic baseline is deliberately weak but perfectly grounded:

- source coverage: `1.00`
- event coverage: `1.00`
- slice coverage: `1.00`
- grounded evidence: `1.00` (`41/41` checks)
- slice match: `0.50`
- event match: `0.80`
- relation match: `0.00`
- target-person unity: `1.00`
- variant provenance preservation: `1.00`

Kimi must improve semantic extraction without giving back evidence grounding.

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

The runner is fail-closed: it writes to `.candidate`, runs the strict audit, and promotes to `live-out` only on PASS.

## Strict acceptance criteria

The current gold thresholds are:

- source coverage `>= 1.00`
- event coverage `>= 0.90`
- slice coverage `>= 0.90`
- slice match `>= 0.75`
- event match `>= 0.70`
- relation match `>= 1.00` for explicitly required relations (currently LG07/LG08 `kills`)
- target-person unity `>= 1.00` — the same Lv Guang must not fracture into multiple nodes because free-form context wording changed
- grounded evidence `>= 1.00`
- variant provenance preservation `>= 1.00`

Additionally:
- exactly 20 source records must remain represented;
- no silent merge of an unrelated same-name person;
- every event/edge/slice must remain traceable to `source_id` and stored provenance;
- parser must survive fenced JSON or surrounding text;
- repeated run must be idempotent unless `--force` is used;
- explorer must load the promoted `lvguang_gold_20.graph.json`.

## Review targets

After the first run, inspect failures in this order:

1. JSON/API compatibility (`/v1/chat/completions`, response shape, model alias).
2. Unsupported evidence / pseudo-quotation.
3. Provenance loss or certainty inflation.
4. Entity resolution mistakes, especially Lv Guang node fragmentation.
5. Missing explicit relation edges, especially LG07/LG08 kills.
6. Event over-splitting / under-splitting.
7. Temporal relation edge quality.
8. Slice assignment quality, especially `TRUST_BETRAYAL`, `WAR_COMMAND`, `FAMILY_SUCCESSION`, `HISTORIOGRAPHY_BIAS`.
9. UI usefulness for one-hop historical exploration.

## Patch policy

Make the smallest patch that fixes observed failures. Add or extend tests for every bug found. Do not redesign the whole architecture after one 20-record run.

At completion, report:

- exact model route used (model alias only, no credential);
- processed / failed counts;
- node / edge / event / slice counts;
- complete `audit.json` metric summary;
- entity-resolution errors found;
- certainty/provenance/grounding errors found;
- files changed;
- next highest-information-gain test.
