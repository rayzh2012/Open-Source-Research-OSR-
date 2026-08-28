# Ancient Document Rescue Playbook

A public, living field manual for preserving ancient and historical digital manuscripts from institutional repositories without bypassing access controls.

## Mission

The goal is not to collect links. The goal is to preserve verifiable digital objects with enough provenance that another researcher can independently identify, validate, and re-use the preserved corpus later.

A manuscript is **not archived** because it appeared in search results, because a metadata page loaded, or because a download URL was discovered. Preservation is complete only after real bytes are acquired, validated, fingerprinted, stored, and read back from the canonical archive.

## Core rule: search is not completion

For every eligible public-domain / Public Domain Mark / open-licensed / author-permitted object that is anonymously retrievable without bypassing login, CAPTCHA, paywall, robots, or other access controls, use the full path:

`DISCOVER → RIGHTS CHECK → FETCH REAL BYTES → VALIDATE TYPE/IDENTITY → SHA256 → STORE → READBACK VERIFY → LEDGER UPDATE`

If any stage fails, the item remains `PARTIAL`, `BLOCKED`, or `FAILED`; it is never silently promoted to `PASS`.

## Preservation package

Each completed item should retain, when available:

- stable institutional identifier (ARK, catalogue ID, persistent URL, etc.)
- source institution and source URL
- title, date, language, collection/shelfmark
- raw catalogue metadata and/or IIIF manifest
- explicit rights evidence captured at retrieval time
- original or official digital derivative bytes
- page/image inventory for paged objects
- byte count and MIME/type validation
- SHA256 fingerprint for every preserved payload
- retrieval timestamp
- `COMPLETE` record describing exactly what was verified

A corpus-level registry should aggregate item IDs, state, bytes, hashes, failures, retries, and canonical storage paths.

## Rights discipline

Rights are evaluated **per item**, not inferred from an institution as a whole.

Preferred states:

1. explicit public domain
2. explicit Public Domain Mark
3. explicit open licence permitting preservation/reuse
4. explicit author/institution permission

If rights are ambiguous, preserve metadata and stable identifiers only until the ambiguity is resolved. Do not use technical accessibility as a substitute for permission.

## Smoke before scale

Never begin with a thousand-item download just because discovery succeeded.

Use staged expansion:

1. **metadata smoke** — prove discovery and parse the real API/manifest shape
2. **single-item full smoke** — acquire every intended byte/page and verify readback
3. **small batch** — prove retries, rate limiting, dedupe, and resumability
4. **full corpus** — only after the bounded batch is green

This prevents a schema mistake, rights assumption, or endpoint failure from multiplying across a large corpus.

## Resumability and idempotence

Large rescues must expect interruption.

- use stable item IDs as primary keys
- write `COMPLETE` only after final readback verification
- skip already-verified items on rerun
- retry failed partitions instead of restarting the entire corpus
- preserve prior valid packages; never silently replace them with a different identity
- record the exact request/configuration that produced each batch

A rerun should be safe even after a runner crash, transient network failure, or partial institution outage.

## Rate limits and institutional boundaries

Treat 429, 403, Retry-After, and challenge pages as signals, not obstacles to defeat.

- obey server-provided backoff
- reduce concurrency before increasing retries
- use circuit breakers for repeated identical failures
- prefer official catalogue APIs, IIIF Presentation, IIIF Image, or documented download endpoints
- never solve/bypass CAPTCHA or Cloudflare challenges
- if one official endpoint is blocked but another official anonymous endpoint exposes the same public object, switch adapters and retain provenance for the path actually used

### Field lesson: portal URLs are not preservation APIs

Human-facing portals may rate-limit or challenge automated runners while their official catalogue/IIIF services remain intentionally machine-readable. Build adapters around institutional machine interfaces when available rather than repeatedly hitting presentation pages.

### Field lesson: official IIIF version fallback must stay identity-bounded

An institution may publish the same manifest through documented Presentation v2, v3, and content-negotiated routes while one route temporarily returns 403 or 404. A preservation adapter may test only those official variants on the same institutional host and stable object identifier.

Treat this as a bounded schema/availability fallback, not an access-control workaround:

- recheck the exact catalogue item's rights and open-access location first
- retain both the catalogue-declared manifest URL and the URL actually retrieved
- require the retrieved manifest to reconcile to the expected item and page count
- preserve and hash the manifest actually used
- if every documented official variant is blocked, stop at `ACCESS_BLOCKED`

### Field lesson: a transient 403 may justify one cooldown, never evasion

A public-domain, anonymously accessible IIIF object can be rejected transiently by an institutional edge layer even when the exact same official URL succeeds later. The safe response is bounded patience, not browser impersonation or access-control circumvention.

- retry the exact same official object route once after a meaningful cooldown
- keep the same stable identifier, host, rights gate, and ordinary transparent request headers
- do not rotate identities, spoof browsers, solve challenges, or expand to undocumented mirrors
- if the bounded retry and documented same-identity variants remain blocked, stop and record `ACCESS_BLOCKED`
- rerun only the failed item after the rest of the batch is destination-reconciled

This reduces avoidable failed-tail orchestration while preserving the distinction between transient availability and access authorization.


## IIIF lessons

IIIF is often the most durable cross-institution abstraction, but implementations vary.

Do not assume:

- Presentation v2 and v3 use identical shapes
- every manifest has a PDF derivative
- every canvas has one image
- every image service permits the same requested size
- catalogue rights and image-service rights are represented in the same field

Before scaling, inspect real manifests and keep raw manifests alongside derived inventories.

For image-based manuscripts, full-item completion means all intended canvases/pages were fetched and verified, not merely that the manifest itself was archived.

## Schema drift: inspect, then code

Institutional APIs frequently differ from documentation, examples, or older assumptions.

When a smoke test fails because a `workType`, licence field, nested location, image service, or identifier differs:

1. save the returned evidence
2. inspect the real payload shape
3. make the narrowest schema-compatible adapter change
4. rerun the bounded smoke
5. do **not** broaden rights criteria merely to make the run pass

## Failure taxonomy

Use failure labels that identify where the preservation chain broke:

- `DISCOVERY_MISS`
- `RIGHTS_AMBIGUOUS`
- `ACCESS_BLOCKED`
- `RATE_LIMITED`
- `METADATA_SCHEMA_MISMATCH`
- `BYTE_FETCH_FAILED`
- `TYPE_VALIDATION_FAILED`
- `PAGE_INVENTORY_INCOMPLETE`
- `HASH_FAILED`
- `STORE_FAILED`
- `READBACK_FAILED`

A transport failure is not evidence that a manuscript is unavailable in principle; an access-control block is not permission to bypass it.

## Verification standard

A corpus may be called `PASS` only when its declared target set is fully reconciled.

Minimum corpus audit:

- expected items
- verified complete items
- partial/failed/blocked items
- total stored bytes
- hashes present
- duplicate count
- missing page/image count where applicable
- readback status
- canonical archive path

If `verified_complete < expected`, status is not `PASS` unless the declared target set itself was explicitly revised with evidence.

### Page-level readback is stronger than marker-level readback

A `COMPLETE` record is evidence to audit, not evidence to trust blindly. For a paged object, the strongest bounded verification streams every stored page from the destination, recomputes its byte count and SHA256, and reconciles that result against the page index, checkpoint, manifest fingerprint, and declared total.

Do not call a full-item smoke green merely because the item folder exists or because `COMPLETE.json` says `PASS`. Require an exact page-name set, exact page count, exact total bytes, per-page hash agreement, metadata/manifest presence, and zero reconciliation errors.

### Census before corpus-scale acquisition

Page counts can vary by orders of magnitude within one institutional corpus. Item count alone is therefore a poor storage, bandwidth, and runner-time estimate.

Before launching a large paged rescue:

1. audit the qualifying registry and its rights boundary
2. run a low-concurrency manifest/page-count census
3. reconcile the census to the exact registry denominator
4. estimate storage from observed bytes per page in completed bounded tranches
5. expand by page-count bands, recording exact pages and bytes after each band

This turns scale-up into a measured capacity decision and keeps a pathological long tail from invalidating an otherwise sound preservation adapter.

### Destination reconciliation after a batch

Counting successful jobs is not enough, especially when an API or workflow listing is paginated. Reconcile the destination itself:

- enumerate the exact expected stable IDs
- require one canonical item folder per ID
- parse every item-level `COMPLETE` record
- sum page counts and image bytes from those records
- require the item-level destination-readback flag
- compare the totals with the request and registry

Only the intersection of workflow success, item-level evidence, and destination reconciliation supports a batch `PASS`.

## Separation of preservation and research claims

Preservation records should remain factual:

- what institution identified the object
- what bytes were retrieved
- what rights statement was present
- what hash was computed
- what storage path was verified

Historical interpretation, OCR, attribution, dating hypotheses, translations, and research conclusions belong in separate analytical layers. This prevents later scholarship from contaminating the preservation ledger.

## Public reproducibility

The rescue method should itself be preserved.

For every new institutional adapter or meaningful failure/fix:

- keep executable acquisition code in version control
- retain the request/configuration used for the run
- record the failure signature and the narrow fix
- update this playbook with reusable lessons
- keep public documentation free of credentials, private account data, and restricted URLs/tokens

The goal is that the corpus can outlive any one runner, API client, notebook, or operator.

## Lessons learned from early rescues

### 1. A discovered URL is only a lead

Early workflows were too easy to misread as successful once a search result or metadata record existed. The durable definition of success is now byte-level storage plus readback.

### 2. Partial success must stay partial

A batch that retrieves most objects can be operationally valuable, but the missing tail still matters. Record exact denominators and repair only failed partitions.

### 3. Failed-tail reruns need dedupe first

Before retrying a subset, check existing `COMPLETE` markers and fingerprints. Otherwise a recovery run can waste bandwidth and create inconsistent duplicates.

### 4. Institution-specific adapters should converge on one preservation contract

LOC, Gallica, Wellcome, Digital Bodleian, and future sources may expose very different APIs, but downstream storage should normalize around the same contract: stable ID, rights, metadata, bytes/pages, hashes, readback, completion state.

### 5. Public-domain status and anonymous technical access are separate gates

An item can be legally reusable but temporarily blocked by an anti-bot layer; another can be technically downloadable while reuse rights remain ambiguous. Both gates must pass independently.

### 6. The archive should preserve evidence of how it knows it is complete

A `COMPLETE` marker is not merely a boolean. It should summarize the expected object/page set, verified files, hashes, rights evidence, and readback result so future audits can reconstruct the decision.

## Long-term migration rule

Preservation infrastructure will change. Storage providers, APIs, runners, and repositories will not last forever.

Therefore the durable unit is not a particular cloud vendor. It is a **self-describing preservation package plus machine-readable registry**. If the canonical archive ever moves, migrate the verified packages together with their identifiers, metadata, hashes, rights evidence, and completion records; then perform destination readback before declaring migration complete.

Never discard the old verified location until the new location has been reconciled.

## Living-document rule

This file is intentionally maintained as a living public playbook. Each completed corpus, meaningful failure, adapter change, or migration should contribute only the reusable lesson—not private credentials or unnecessary operational noise.

The preservation principle is simple:

> **Find it, prove we may preserve it, acquire the real object, prove what we acquired, and make the proof survive the tool that acquired it.**
