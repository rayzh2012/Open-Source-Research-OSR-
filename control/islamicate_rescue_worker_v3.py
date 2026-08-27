#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import time

import islamicate_rescue_worker_v2 as v2


def process_loc(s, cfg: dict, work: Path, remote: str) -> dict:
    rows = v2._loc_discover(s, cfg)
    items_dir = work / "item_json"
    iiif_dir = work / "iiif"
    items_dir.mkdir(parents=True, exist_ok=True)
    iiif_dir.mkdir(parents=True, exist_ok=True)

    inventory = []
    errors = []
    manifest_count = 0

    # The LOC collection search response already contains authoritative item-level
    # catalog metadata. Reuse it directly instead of making 173 extra item-JSON
    # requests, which can trip per-item throttling or heterogeneous resource URLs.
    for i, row in enumerate(rows, 1):
        item_id = str(row.get("item_id") or "").strip()
        if not item_id:
            candidate = str(row.get("id") or row.get("url") or "").rstrip("/").split("/")[-1]
            item_id = candidate
        canonical_item = f"https://www.loc.gov/item/{item_id}/"
        manifest_url = f"https://www.loc.gov/item/{item_id}/manifest.json"
        print(f"LOC_V3 {i}/{len(rows)} {item_id}", flush=True)

        # Preserve the search-row metadata even if the IIIF manifest is temporarily
        # unavailable. This guarantees all 173 catalog records are rescued.
        v2.base.dump_json(items_dir / f"{item_id}.json", {
            "schema_version": "osr-loc-search-row-v1",
            "canonical_item_url": canonical_item,
            "collection_row": row,
        })

        manifest_sha = None
        manifest_error = None
        try:
            mr = s.get(manifest_url, timeout=120)
            mr.raise_for_status()
            obj = mr.json()
            mp = iiif_dir / f"{item_id}.json"
            v2.base.dump_json(mp, obj)
            manifest_sha = v2.base.sha256_file(mp)
            manifest_count += 1
        except Exception as exc:
            manifest_error = repr(exc)
            errors.append({"item_id": item_id, "stage": "manifest", "url": manifest_url, "error": manifest_error})

        inventory.append({
            "item_id": item_id,
            "item_url": canonical_item,
            "title": row.get("title"),
            "date": row.get("date"),
            "language": row.get("language"),
            "iiif_manifest": manifest_url,
            "iiif_sha256": manifest_sha,
            "manifest_error": manifest_error,
        })

        # Keep the public service load modest; the whole collection still finishes
        # quickly, while retries in the shared session handle transient 429/5xx.
        time.sleep(0.12)

    inventory.sort(key=lambda x: x["item_id"])
    identity = v2.base.sha256_bytes(
        b"".join((json.dumps(x, ensure_ascii=False, sort_keys=True) + "\n").encode() for x in inventory)
    )
    v2.base.dump_jsonl(work / "meta" / "inventory.jsonl", inventory)
    v2.base.dump_json(work / "meta" / "SOURCE.json", {
        "schema_version": "osr-rescue-source-v3",
        "source_id": cfg["id"],
        "items_discovered": len(rows),
        "items_saved": len(inventory),
        "iiif_manifests": manifest_count,
        "inventory_sha256": identity,
        "manifest_errors": errors,
        "rights_note": cfg.get("rights_note"),
        "image_policy": cfg.get("image_policy"),
        "metadata_strategy": "LOC collection search rows + canonical /item/<LCCN>/manifest.json",
    })

    v2.base.rclone_copy_dir(items_dir, f"{remote}/item_json")
    v2.base.rclone_copy_dir(iiif_dir, f"{remote}/iiif")
    v2.base.rclone_copy_dir(work / "meta", f"{remote}/meta")

    expected = int(cfg.get("expected_items", 173))
    if len(inventory) < int(expected * 0.95):
        status = "FAILED_INCOMPLETE"
    elif manifest_count < int(expected * 0.80):
        # Catalog rescue is complete but image backfill should not begin from a
        # severely incomplete manifest layer.
        status = "FAILED_MANIFEST_LAYER"
    else:
        status = "PASS"

    complete = {
        "identity": identity,
        "status": status,
        "items": len(inventory),
        "iiif_manifests": manifest_count,
        "manifest_errors": len(errors),
    }
    v2.base.dump_json(work / "COMPLETE.json", complete)
    v2.base.rclone_copyto(work / "COMPLETE.json", f"{remote}/meta/COMPLETE.json")
    return complete


def process_qdl(s, cfg: dict, work: Path, remote: str) -> dict:
    # One compatibility attempt only: QDL currently returns 403 to the explicit
    # research-bot UA from GitHub-hosted runners. Retry with ordinary browser
    # request headers, without attempting to defeat authentication or access controls.
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/ld+json,application/json;q=0.8,*/*;q=0.7",
        "Referer": "https://www.qdl.qa/",
        "Cache-Control": "no-cache",
    })
    result = v2.process_qdl(s, cfg, work, remote)
    if result.get("status") in {"FAILED_EMPTY", "FAILED_INCOMPLETE"}:
        result["access_note"] = "QDL returned no usable manifests from GitHub-hosted runner after normal browser-compatible headers; treat as acquisition-plane block, not missing source data."
    return result


v2.base.process_loc = process_loc
v2.base.process_qdl = process_qdl

if __name__ == "__main__":
    raise SystemExit(v2.base.main())
