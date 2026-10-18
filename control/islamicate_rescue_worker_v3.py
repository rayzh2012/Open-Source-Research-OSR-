#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import time

import islamicate_rescue_worker_v2 as v2


def _walk_urls(obj):
    out = []
    def walk(x, path=""):
        if isinstance(x, dict):
            for k, val in x.items():
                walk(val, f"{path}.{k}" if path else str(k))
        elif isinstance(x, list):
            for i, val in enumerate(x):
                walk(val, f"{path}[{i}]")
        elif isinstance(x, str) and x.startswith(("http://", "https://")):
            out.append((path, x))
    walk(obj)
    return out


def _loc_service_inventory(item_json: dict) -> dict:
    manifest_urls = []
    info_urls = []
    image_urls = []
    storage_urls = []
    for path, url in _walk_urls(item_json):
        low = url.lower()
        if "manifest" in low and "iiif" in low:
            manifest_urls.append(url)
        if "tile.loc.gov/image-services/iiif/" in low and low.endswith("/info.json"):
            info_urls.append(url)
        if "tile.loc.gov/image-services/iiif/" in low and "/full/" in low:
            image_urls.append(url)
        if "tile.loc.gov/storage-services/" in low:
            storage_urls.append(url)
    def uniq(xs):
        return sorted(set(xs))
    return {
        "manifest_urls_metadata_only": uniq(manifest_urls),
        "iiif_info_urls": uniq(info_urls),
        "iiif_image_urls": uniq(image_urls),
        "storage_urls": uniq(storage_urls),
    }


def process_loc(s, cfg: dict, work: Path, remote: str) -> dict:
    rows = v2._loc_discover(s, cfg)
    items_dir = work / "item_json"
    items_dir.mkdir(parents=True, exist_ok=True)
    inventory = []
    service_rows = []
    errors = []
    item_json_saved = 0
    service_count = 0

    # Probe evidence on 2026-08-27 showed /item/<id>/manifest.json is behind a
    # Cloudflare challenge on GitHub-hosted runners, while /item/<id>/?fo=json is
    # public and returns the manifest URL plus the complete tile.loc.gov IIIF/file
    # inventory. Do not fight the challenge. Preserve the public item JSON and a
    # deterministic service inventory derived from it instead.
    for i, row in enumerate(rows, 1):
        item_id = str(row.get("item_id") or "").strip()
        if not item_id:
            item_id = str(row.get("id") or row.get("url") or "").rstrip("/").split("/")[-1]
        canonical_item = f"https://www.loc.gov/item/{item_id}/"
        print(f"LOC_V3 {i}/{len(rows)} {item_id}", flush=True)

        try:
            # Keep well under the public API's rate limiter. v2._loc_get also
            # respects Retry-After/403/429 and has bounded exponential cooldown.
            jr = v2._loc_get(s, canonical_item, params={"fo": "json"}, timeout=120, accept_json=True)
            if jr is None:
                raise RuntimeError("LOC item JSON returned no response")
            jr.raise_for_status()
            item_json = jr.json()
        except Exception as exc:
            errors.append({"item_id": item_id, "stage": "item_json", "error": repr(exc)})
            continue

        p = items_dir / f"{item_id}.json"
        v2.base.dump_json(p, item_json)
        item_json_saved += 1
        services = _loc_service_inventory(item_json)
        service_count += len(services["iiif_info_urls"])
        service_rows.append({
            "item_id": item_id,
            "item_url": canonical_item,
            **services,
        })
        manifest_urls = services["manifest_urls_metadata_only"]
        inventory.append({
            "item_id": item_id,
            "item_url": canonical_item,
            "title": row.get("title") or item_json.get("title"),
            "date": row.get("date") or item_json.get("date"),
            "language": row.get("language") or item_json.get("language"),
            "item_json_sha256": v2.base.sha256_file(p),
            "iiif_manifest_url": manifest_urls[0] if manifest_urls else None,
            "manifest_fetch_status": "BLOCKED_CLOUDFLARE_CHALLENGE_NOT_BYPASSED" if manifest_urls else "NOT_ADVERTISED",
            "iiif_service_count": len(services["iiif_info_urls"]),
        })

        # Additional spacing beyond _loc_get so a 173-item run does not repeat
        # the previous burst that was blocked after ~16 records.
        time.sleep(2.0)

    inventory.sort(key=lambda x: x["item_id"])
    service_rows.sort(key=lambda x: x["item_id"])
    identity = v2.base.sha256_bytes(
        b"".join((json.dumps(x, ensure_ascii=False, sort_keys=True) + "\n").encode() for x in inventory)
    )
    v2.base.dump_jsonl(work / "meta" / "inventory.jsonl", inventory)
    v2.base.dump_jsonl(work / "meta" / "iiif_services.jsonl", service_rows)
    v2.base.dump_json(work / "meta" / "SOURCE.json", {
        "schema_version": "osr-rescue-source-v4",
        "source_id": cfg["id"],
        "items_discovered": len(rows),
        "item_json_saved": item_json_saved,
        "iiif_info_services": service_count,
        "manifest_layer_status": "BLOCKED_CLOUDFLARE_CHALLENGE_NOT_BYPASSED",
        "inventory_sha256": identity,
        "errors": errors,
        "rights_note": cfg.get("rights_note"),
        "image_policy": cfg.get("image_policy"),
        "metadata_strategy": "paced public LOC item JSON + derived tile.loc.gov IIIF service inventory",
    })

    v2.base.rclone_copy_dir(items_dir, f"{remote}/item_json")
    v2.base.rclone_copy_dir(work / "meta", f"{remote}/meta")

    expected = int(cfg.get("expected_items", 173))
    if item_json_saved < int(expected * 0.95):
        status = "FAILED_INCOMPLETE"
    elif service_count <= 0:
        status = "FAILED_NO_IIIF_SERVICES"
    else:
        # The catalog + service layer is preserved, but the challenged manifest
        # bytes themselves are intentionally not claimed as acquired.
        status = "PARTIAL"

    complete = {
        "identity": identity,
        "status": status,
        "items": item_json_saved,
        "iiif_info_services": service_count,
        "iiif_manifests_fetched": 0,
        "manifest_layer_status": "BLOCKED_CLOUDFLARE_CHALLENGE_NOT_BYPASSED",
        "errors": len(errors),
    }
    v2.base.dump_json(work / "COMPLETE.json", complete)
    v2.base.rclone_copyto(work / "COMPLETE.json", f"{remote}/meta/COMPLETE.json")
    return complete


def process_qdl(s, cfg: dict, work: Path, remote: str) -> dict:
    # QDL is currently returning 403 from GitHub-hosted runners. Use only the
    # transparent research session and known public seed URLs. Do not spoof a
    # browser, solve a challenge, supply cookies, or otherwise bypass controls.
    iiif_dir = work / "iiif"
    iiif_dir.mkdir(parents=True, exist_ok=True)
    manifests = []
    blocked = []
    errors = []

    for mu in cfg.get("verified_seed_manifests", []):
        try:
            time.sleep(1.0)
            r = s.get(mu, timeout=120, allow_redirects=True)
            if r.status_code == 403:
                blocked.append({"url": mu, "status": 403})
                continue
            r.raise_for_status()
            obj = r.json()
            mid = hashlib.sha1(mu.encode()).hexdigest()[:16]
            p = iiif_dir / f"{mid}.json"
            v2.base.dump_json(p, obj)
            manifests.append({
                "manifest": r.url,
                "sha256": v2.base.sha256_file(p),
                "rights": obj.get("license") or obj.get("rights"),
                "discovered_via": "verified_seed",
            })
        except Exception as exc:
            errors.append({"url": mu, "error": repr(exc)})

    manifests.sort(key=lambda x: x["manifest"])
    identity = v2.base.sha256_bytes(
        b"".join((json.dumps(x, ensure_ascii=False, sort_keys=True) + "\n").encode() for x in manifests)
    )
    v2.base.dump_jsonl(work / "meta" / "inventory.jsonl", manifests)
    v2.base.dump_json(work / "meta" / "SOURCE.json", {
        "schema_version": "osr-rescue-source-v4",
        "source_id": cfg["id"],
        "verified_seed_manifests": cfg.get("verified_seed_manifests"),
        "iiif_manifests": len(manifests),
        "blocked_403": blocked,
        "errors": errors,
        "inventory_sha256": identity,
        "rights_note": cfg.get("rights_note"),
        "image_policy": cfg.get("image_policy"),
        "access_policy": "anonymous public URLs only; no Cloudflare/CAPTCHA/access-control bypass",
    })
    v2.base.rclone_copy_dir(iiif_dir, f"{remote}/iiif")
    v2.base.rclone_copy_dir(work / "meta", f"{remote}/meta")

    minimum = int(cfg.get("minimum_manifests", 1))
    if len(manifests) >= minimum:
        status = "PASS"
    elif blocked:
        status = "FAILED_ACCESS_BLOCK"
    else:
        status = "FAILED_EMPTY"
    complete = {
        "identity": identity,
        "status": status,
        "iiif_manifests": len(manifests),
        "blocked_403": len(blocked),
        "errors": len(errors),
    }
    v2.base.dump_json(work / "COMPLETE.json", complete)
    v2.base.rclone_copyto(work / "COMPLETE.json", f"{remote}/meta/COMPLETE.json")
    return complete


v2.base.process_loc = process_loc
v2.base.process_qdl = process_qdl

if __name__ == "__main__":
    raise SystemExit(v2.base.main())
