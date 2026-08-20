# Yunnan Songkran benchmark v1

This benchmark is the first production-style Myth Engine import target.

## Source witnesses

- No.353, Dai, narrator 岩林, collector 林木, collected in 德宏州.
- No.354, De'ang, narrator 满坎木, collector 杨筑骧, collected in 瑞丽县 in 1985.
- Canonical Drive source: `1yGg5yYBBiTOKsULEODQoW6MAl67SNGpy`.

## Copyright / storage boundary

The source PDF remains in Google Drive. Raw copyrighted story text is **not** copied into this public Git repository. `fixtures.json` contains:

1. provenance sufficient to reacquire the private source;
2. paraphrased derived test segments for deterministic CI;
3. manually audited semantic gold events derived from the source pages.

A private/local ingest adapter may read the complete Drive text and generate content hashes, Merkle roots and segment indexes. Those private-source hashes can be committed; the source text itself should remain outside Git unless its license permits redistribution.

## Expected semantic relation

Shared event spine:

`HAIR_WEAPON -> DECAPITATE -> DANGEROUS_HEAD -> FEMALE_ROTATION -> WATER_WASH -> RITUAL_ORIGIN`

No.354 additionally carries:

`CALENDAR_ERROR -> GRAFT_HEAD -> REVIVE -> CALENDAR_REPAIR -> AGRICULTURE_ORDER`

The benchmark is intentionally designed to separate **lexical overlap** from **semantic-event mutation**. CI must remain deterministic and non-vector-first.
