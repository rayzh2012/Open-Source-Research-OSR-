# Myth Engine v0.1 — Merkle DAG + Direct Search

Myth Engine treats historical/mythological corpora as a version-control problem rather than an embedding-search problem.

## Design rule

**No dense-vector index is required for primary retrieval.** The fast path is deterministic and inspectable:

1. **Content addressing** — SHA-256 for file/text/segment/event identity.
2. **Merkle tree** — each witness has a Merkle root built from ordered segment hashes.
3. **Inverted q-gram index** — direct phrase/fuzzy candidate retrieval for Chinese and multilingual text without relying on a tokenizer.
4. **Dictionary automaton** — Aho-Corasick-style trie for one-pass scans of motif/entity dictionaries.
5. **Versioned semantic IR** — stories are translated into explicit symbolic events (`HAIR_WEAPON`, `DECAPITATE`, `BODY_COMPLETENESS`, etc.), each tied to a schema version and hash.
6. **Variant/provenance DAG** — `translated_from`, `quoted_from`, `same_occurrence_candidate`, `variant_of`, `mutation`, etc.
7. **BFS/DFS only after indexed retrieval** — graph traversal explores relatives/lineages; it does not scan the raw corpus.

## Why Git branches are not myth branches

Git branches are used for **code/schema/import/hypothesis states**:

```text
master
├── ingest/yunnan-2002
├── ingest/bezemer-1904
├── schema/semantic-v2
├── hypothesis/half-body
└── hypothesis/songkran-reticulation
```

Individual story versions are data nodes inside the Variant DAG. This avoids thousands of Git branches and keeps historical relationships separate from repository workflow.

## Storage split

```text
Google Drive = immutable source blobs / PDFs / scans
GitHub       = code, manifests, extracted text, schemas, hashes, tests
SQLite       = local/query index for MVP
Parquet/DuckDB = scale-out analytical layer later
```

A source record should retain the Drive/file URI and source hash. Large source PDFs should not be committed to Git.

## Search ladder

```text
L0 hash lookup       O(1)-style exact identity
L1 dictionary trie   one-pass multi-keyword scan
L2 q-gram index      phrase + near-copy retrieval
L3 semantic IR       exact symbolic mechanism search
L4 graph traversal   BFS/DFS over already-linked candidates
```

Example semantic query:

```text
HAIR_WEAPON + DECAPITATION + DANGEROUS_HEAD
```

This is deliberately different from asking a vector database for “similar myths”. The result is auditable: each hit has explicit fields, text spans, provenance and version.

## Semantic versioning

Semantic interpretation is itself versioned:

```text
semantic/v1
  └── semantic/v2
       ├── hypothesis-A
       └── hypothesis-B
```

A text segment never changes identity. New interpretation creates a new semantic event/version linked to the same segment. This preserves old readings and makes reinterpretation diffable.

## Universal Myth Archive contract

The long-term target is **not a collection of notes**. It is a programmable archive in which every myth, legend, historical anecdote, and later retelling can be addressed, versioned, dated, traversed, compared, and rendered as a graph.

### Identity hierarchy

```text
story_family_id
  └── witness_id
       └── segment_id
            └── semantic_event_id
```

- `story_family_id` groups candidate versions without asserting common origin.
- `witness_id` identifies one concrete textual/oral witness or publication occurrence.
- `segment_id` identifies stable source spans by hash.
- `semantic_event_id` identifies versioned symbolic interpretation attached to a stable source span.

Every layer is addressable by dictionary/hash-table style key lookup; graph edges are secondary relations, not identity.

### Time is first-class data

Every witness should carry separate dates where available:

```text
composition_date_min / composition_date_max
collection_date
publication_date
manuscript_date
attestation_date
translation_date
import_date
```

Unknown dates stay unknown. A later publication must never silently become the origin date of the story.

This enables chronological slicing, holdout tests, lineage visualization, and queries such as:

```text
show all witnesses of family X before 1500
show all mutations appearing after witness Y
show earliest attestation of event bundle Z
```

### Graph model

Nodes may include:

```text
STORY_FAMILY / WITNESS / SEGMENT / EVENT / ENTITY / PLACE / SOURCE / LANGUAGE / PERIOD
```

Edges may include:

```text
VARIANT_OF / DERIVED_FROM / QUOTED_FROM / TRANSLATED_FROM
SAME_OCCURRENCE_CANDIDATE / MUTATION_OF / NEXT_EVENT
MENTIONS_ENTITY / LOCATED_AT / ATTESTED_IN / DATED_TO
INTERPRETS_AS / SUPPORTS / CONTRADICTS
```

The graph is a DAG where provenance requires acyclicity, but analytical association edges may form a broader graph. Reticulation is allowed: one witness can inherit from multiple sources.

### Traversal contract

- **Hash/dictionary/inverted index** finds candidate nodes quickly.
- **BFS** answers neighborhood questions: all relatives within N hops, all versions reachable from a witness, all sources connected to an entity.
- **DFS** answers lineage/path questions: provenance chains, deep mutation paths, dependency exploration.
- Traversal never substitutes for source retrieval or chronology validation.

### Visualization contract

The same graph must support machine-readable export for:

1. witness stemmata / reticulation graphs;
2. chronological timelines;
3. geography × time maps;
4. entity-story networks;
5. mutation/event diff graphs;
6. source-provenance diagrams.

Visualization is therefore a projection of the stored graph, not a manually redrawn research product.

### One substrate, three output modes

The archive is deliberately shared by three downstream uses:

1. **Historical research** — source criticism, provenance, chronology, competing hypotheses, falsification, transmission analysis.
2. **Chronicle / personal history writing** — query verified events and dated relationships without rebuilding context manually.
3. **Fiction / myth construction** — reuse the same entities, variants, motifs and timelines while keeping `FACT / INFERENCE / HYPOTHESIS / CANON` explicitly separated.

The storage substrate is shared; epistemic status is not. Fictional canon must never overwrite historical evidence.

## MVP layout

```text
myth-engine/
├── myth_engine/
│   ├── __init__.py
│   ├── core.py
│   └── cli.py
├── schema/
│   └── semantic-event-v1.json
└── tests/
    └── test_core.py
```

## CLI sketch

```bash
python -m myth_engine.cli init myth.db
python -m myth_engine.cli ingest myth.db --meta source.json --text story.txt
python -m myth_engine.cli phrase myth.db '七根头发'
python -m myth_engine.cli fuzzy myth.db '头发勒断头颅'
python -m myth_engine.cli bfs myth.db <node-id> --depth 3
```

## Core invariant

**Text identity, semantic interpretation, provenance, chronology, hypothesis, and canon are separate layers.** Never rewrite a source because an interpretation changed, never count a republished/translated occurrence as independent evidence merely because it appears in another publication, and never let fiction-layer canon back-propagate into historical fact.
