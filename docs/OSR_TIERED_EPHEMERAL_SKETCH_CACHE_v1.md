# OSR Tiered Ephemeral Sketch Cache v1

## Problem
Repeated exact-evidence runs currently re-download ~17 GiB for a Top-12 shard set. Three recent runs consumed ~48.13 GiB total. Trie-only buffering helps only after raw text has already been downloaded; it does not solve shard selection for unseen future queries.

## Design goal
Convert one expensive raw pass into tiny reusable shard fingerprints, then make future queries progressively cheaper. Preserve exact source-row recheck as the final evidence gate.

## Architecture

### L0 — Persistent Compact Term Index
Existing M2 compact query index. Exact counts / shard locators for known query-pack terms. MB-scale and permanent.

### L1 — Persistent Static N-gram Membership Sketches
For each shard, build static approximate-membership fingerprints over normalized Chinese 2-grams and 3-grams. A future literal query is decomposed into its n-grams; if a shard is missing any required gram it can be rejected without downloading raw text.

Preferred static structure: XOR/Ribbon-style filter when implementation maturity is acceptable; Bloom filter is the conservative baseline. Cuckoo filter is not the default because this corpus is static and deletion is unnecessary.

Contract: membership sketch may produce false positives, but must not produce false negatives under the same normalization/version. Therefore it is a routing layer only, never evidence.

### L2 — Tiny Similarity / Distribution Sketches
Per-shard MinHash or weighted MinHash signatures for document/shingle-set similarity; SimHash for near-duplicate clustering; HyperLogLog for approximate cardinalities; Count-Min Sketch / Top-K for approximate frequency-heavy-hitters. These are optional, compact, and mergeable.

Use cases: identify duplicate-heavy shards, find source-family neighbors, rank likely related shards, estimate whether a query family is worth opening raw data.

### L3 — TTL Hot Buffer
Temporary compressed cache for shards or extracted row blocks that actually survive L0/L1/L2 routing. Store Zstd-compressed text/Arrow blocks plus row offsets and hashes. Cache key includes source/repo/file/blob identity and normalization version.

Default TTL: 24–72h. LRU + byte budget. Delete automatically after TTL or when budget is exceeded. This is where a trie / Aho-Corasick automaton can be useful for repeated searches over the same hot buffer.

### L4 — Exact Raw Retrieval
Only remaining candidate shards are downloaded from Hugging Face and exact rows rechecked. Raw shards remain ephemeral and are deleted immediately after extraction unless L3 explicitly retains a bounded TTL copy.

## Query path
`query -> L0 known-term lookup -> L1 2/3-gram rejection -> L2 similarity/source ranking -> L3 hot-buffer hit? -> L4 exact retrieval -> evidence audit`

## Why not a universal full-text index?
The Quickwit pilot expanded to ~6.16x raw and the q-gram pilot to ~1.82x raw. A full persistent index violates the cheap-player constraint. The sketch architecture stores only enough information to reject or rank shards; exact text remains in the canonical public source.

## Data-structure choice
- Trie: excellent inside an already hydrated hot buffer; poor as the primary global routing structure.
- Bloom filter: simple, mergeable, no false negatives, but more bits/key than newer static filters.
- XOR filter: static corpus fit; lower memory than classic Bloom at comparable false-positive rates, but rebuild required when corpus changes.
- Ribbon/BuRR-style retrieval/filter: even tighter static-space frontier; treat as experimental until implementation and reproducibility are proven.
- Cuckoo filter: deletion support is unnecessary for immutable corpus shards, so not preferred for L1.
- MinHash: approximate set similarity, useful for shard/source-family routing and dedup clusters.
- SimHash: very cheap near-duplicate fingerprinting for long documents/rows.
- Count-Min Sketch: cheap approximate frequency estimates; never substitute for exact counts when historical claims depend on counts.
- HyperLogLog: cheap approximate distinct counts for corpus/source diagnostics.

## Storage policy
Persistent: L0, L1 and selected L2 sketches only.
Ephemeral: L3 hot buffers and all raw shard downloads.
No Mac-local heavy corpus cache.

## Scale gate
Before building L1 across all 1,788 shards, benchmark 4 representative shards and report:
1. raw bytes read;
2. unique normalized 2-grams / 3-grams;
3. sketch bytes per shard at 1%, 0.1% target FPR;
4. build wall time;
5. rejection rate on held-out queries;
6. false-positive candidate rate;
7. estimated full-corpus sketch size.

Promote only if expected persistent sketch size and one-time build cost beat repeated 17-GiB retrieval economics.

## Research routing law
Large corpus = candidate discovery / source-density discovery.
Dense later sources (e.g. Ming-Qing gazetteers, notebooks, encyclopedias, ritual records) are discovery-first; early sparse sources are exact chronology verification. Do not spend a multi-GiB run to answer a question that a handful of canonical texts can settle directly.
