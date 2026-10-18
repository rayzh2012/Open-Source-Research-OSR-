# Persian / Islamicate Rescue Asset Model

Canonical root: `龍族古籍源庫｜Dragon Source Corpus/ISLAMIC_PERSIAN_RESCUE`

This file freezes the preservation/audit semantics so future batches do not re-invent identity, deduplication, rights, or completion logic.

## 1. `reference_catalogue`

Use for catalogues, handlists, bibliographies, descriptive catalogues, and reference works about manuscript collections.

Canonical destination: `reference_catalogues/<canonical_id>/`.

Invariants:
- one `canonical_id` per intellectual catalogue object/volume;
- preserve source PDF(s), useful OCR/text derivatives when allowed, and metadata/provenance;
- `COMPLETE.json.status == PASS` is required before counting the object;
- folder name must equal `COMPLETE.json.id`;
- duplicate IA identifiers are rejected unless explicitly modeled as aliases;
- preserved byte totals are derived from `COMPLETE.json.files`, not from workflow success alone.

## 2. `manuscript`

Use when one source record maps to one manuscript/codex/document object and its associated preservation files.

Canonical destination: `manuscripts/<canonical_id>/`.

Invariants:
- runtime re-check the source license URL before downloading bytes;
- keep original image/PDF assets and provenance metadata; derived OCR/text may be kept when license permits;
- folder name must equal `COMPLETE.json.id`;
- one canonical object may not silently reuse another canonical object's IA ID;
- `COMPLETE.json.status == PASS` is the only completion gate;
- bytes are counted from `COMPLETE.json.files`.

## 3. `multi_witness_set`

Use when one source record/container contains multiple genuinely distinct manuscript witnesses. Do **not** split these into fake independent source records merely to satisfy a one-record/one-manuscript assumption.

Canonical destination: `manuscripts/<canonical_set_id>/raw/witnesses/<witness_id>/`.

Invariants:
- one canonical set-level `COMPLETE.json` with one source ID;
- each preserved witness must have an explicit stable `witness_id`;
- exact source filename, declared byte size, and source checksum are pinned in the registry and revalidated at runtime;
- lower-resolution `_s`, `_xs`, thumbnail, OCR, or other resolution derivatives are excluded when a higher-resolution copy of the same witness is preserved, unless independently useful and explicitly registered;
- multiple distinct witnesses are preserved even when bundled under one IA/source item;
- audit byte totals must include `total_witness_bytes` and count individual witness files separately from ordinary `files` entries.

## 4. `alias`

Use when two source identifiers point to the exact same preserved bitstream.

Canonical destination: `manuscripts/<alias_id>/ALIAS.json` only; do not duplicate the original bytes.

Invariants:
- `status == ALIAS_ONLY`;
- `canonical_id` must resolve to an existing PASS canonical object;
- source checksum must be present and must establish exact-content identity;
- alias source IDs remain searchable so title/identifier variants are not lost;
- aliases do not increase preserved-byte totals.

## 5. `quarantine`

Use for discovered objects whose bytes are not yet eligible for canonical preservation.

Typical reasons:
- no explicit reusable license and no independent rights evidence;
- NoDerivatives terms when the intended processing route creates derivatives;
- conflicting or incomplete rights metadata.

Invariants:
- metadata-only discovery is allowed;
- canonical bytes are not downloaded into the preservation corpus;
- if an exact licensed copy is later found, record the old source as `SUPERSEDED_BY_LICENSED_EXACT_COPY` with checksum evidence instead of silently deleting the history.

## 6. `gallica_iiif_item`

Use for BnF/Gallica manuscript objects where the bulk PDF endpoint is unavailable or persistently rate-limited but IIIF is openly retrievable.

Canonical destination: `gallica_persian_manuscripts/items/<ark>/`.

Preservation package:
- `metadata/manifest.json` — IIIF Presentation manifest;
- `metadata/pagination.xml` — Gallica pagination metadata;
- `raw/pages/fNNNN.jpg` — full-resolution IIIF JPEG pages;
- `CHECKPOINT.json` — resumable page-level state;
- `PAGE_INDEX.json` — page number, canvas ID, dimensions, source URL, bytes, SHA256;
- `COMPLETE.json` — final object-level completion record.

Invariants:
- ARK must remain in the explicit-public-domain canonical worklist at runtime;
- source rights predicate is revalidated before page download;
- each JPEG is validated, hashed, uploaded, then deleted from the runner;
- checkpoint is persisted after every successfully uploaded full-resolution page, so a runner failure loses at most one in-flight page;
- a Gallica item counts as PASS only when `preserved_pages == page_count`;
- the legacy direct-PDF path is not used after persistent HTTP 429 evidence from GitHub-hosted runners.

## HTTP transfer integrity rule

HTTP transport byte accounting must distinguish the encoded transfer representation from the decoded entity body.

Invariants:
- if `Content-Encoding` is absent, a declared `Content-Length` may be compared directly to the streamed byte count;
- if `Content-Encoding` such as gzip/br is present and the HTTP client transparently decodes the response, do **not** compare the decoded byte count against the encoded `Content-Length`;
- request `Accept-Encoding: identity` when practical, but still inspect the actual response headers because intermediaries/origins may return encoded bodies;
- validate decoded JSON/XML by parsing it and binary assets by format signature/checksum rather than creating a false short-payload failure from mixed transfer layers;
- incident precedent: Gallica IIIF manifests were valid but falsely rejected when gzip-layer `Content-Length` values (~3 KB) were compared with decoded JSON bodies (~70–82 KB). The fix preserved full-resolution delivery; no quality reduction was required.

## Cross-cutting rules

1. **Workflow green is not asset PASS.** Count only Drive-side COMPLETE/ALIAS records that pass identity and schema validation.
2. **Rights are runtime gates.** A registry value is not enough; source metadata is re-checked before bytes move.
3. **Deduplicate by content, not title or byte size alone.** Exact checksums establish aliases; same-size files are only candidates for comparison.
4. **Preserve provenance before transformation.** Raw source assets and source identifiers remain traceable even when clean text/OCR/feature layers are later derived.
5. **Do not duplicate resolution variants without a reason.** Preserve the best available source representation, plus separately useful derivatives when explicitly modeled.
6. **Audit totals must be schema-aware.** Ordinary `files`, multi-witness bytes, and IIIF page bytes are different accounting paths and must all be included in the overall ledger without double counting.
7. **Failures are object-local.** Retry only missing/failed objects or pages; never restart successful assets merely because another matrix member failed.
8. **Checkpoint granularity follows recovery cost.** For large page/image assets, persist completion after each unit; coarser checkpoints are acceptable only when replay cost is demonstrably trivial.
