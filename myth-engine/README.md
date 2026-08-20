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

**Text identity, semantic interpretation, provenance, and hypothesis are four separate layers.** Never rewrite a source because an interpretation changed, and never count a republished/translated occurrence as independent evidence merely because it appears in another publication.
