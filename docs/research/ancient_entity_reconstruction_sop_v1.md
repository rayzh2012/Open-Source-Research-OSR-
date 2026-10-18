# 上古氏族／古帝重构 SOP v1.0

Bootloader snapshot: 2026-08-26
Notion: `3c82a508-97fd-81c5-bf33-ea2ac20d9091`

## Pipeline
`ENTITY SPLIT → SOURCE/WITNESS SPLIT → ORTHOGRAPHIC VARIANTS → PHONOLOGY GRID → MORPHOLOGY FACTORIZATION → REMOVE GRAPH BOUNDARIES → ALL CUTS → CONTROLLED MISSING/ADDED PHONEMES → CROSS-LANGUAGE SEARCH → GEO/TIME CHECK → GENEALOGY vs SUCCESSION → HOLDER/POLITY/OFFICE SPLIT → COMPETING HYPOTHESES → HOLDOUT BREAKER → VERSIONED WRITEBACK`

## Hard gates
- Same label must first split PERSON / CLAN-LINEAGE / POLITY / OFFICE-TITLE / CULT-DEITY / TOPONYM / LATER GENEALOGICAL PROJECTION.
- Recurring names across centuries first test SLOT + multiple HOLDERS.
- `生/子/孙/后/出自` are genealogy/lineage edges, not automatic succession edges.
- Succession requires markers such as `立 / 代立 / 即位 / 崩而X立 / 授政 / 受天下`.
- Genealogy graph and succession graph are separate.
- Shanhaijing-style `某帝之子` must compete among literal son / later descendant / lineage affiliation / political incorporation / compiler join.
- Orthographic carrier is not the lexeme; OCR bridges never upgrade identity.
- Multiple ancient readings remain separate reading nodes until stemma/early evidence resolves direction.
- Compound names must test social wrapper + core name before whole-word transliteration.
- Cross-language hits require phonology + semantics + geography + chronology.
- Derived late sources do not double-count their quoted early source.
- Frequent narrative formulas are low-information identity evidence.
- Every important claim must expose competing models and a holdout/breaker.

## Claim labels
TEXTUAL FACT / COMMENTARIAL FACT / STRONG INFERENCE / WORKING HYPOTHESIS / FICTION CANON / OPEN / REJECTED-SUPERSEDED.

Benchmarks: 叔歜—肃慎; 高辛—帝喾—帝挚.
