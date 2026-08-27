#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urljoin

import islamicate_rescue_worker as base


def _partof_text(row: dict) -> str:
    vals = []
    for key in ("partof", "part_of", "partof_title", "partof_url"):
        v = row.get(key)
        if v is not None:
            vals.append(json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v)
    return " ".join(vals).lower()


def _loc_discover(s, cfg: dict) -> list[dict]:
    expected = int(cfg.get("expected_items", 173))
    label = str(cfg.get("loc_partof", "Persian Manuscripts"))
    candidates = []
    for endpoint in cfg.get("loc_search_paths", ["https://www.loc.gov/manuscripts/", "https://www.loc.gov/search/"]):
        candidates.append((endpoint, {"fo": "json", "c": 100, "fa": f"partof:{label}"}, True))
        candidates.append((endpoint, {"fo": "json", "c": 100, "q": label}, False))

    best: list[dict] = []
    diagnostics = []
    for endpoint, fixed, facet_exact in candidates:
        rows: list[dict] = []
        page = 1
        ok = True
        while page <= 20:
            params = dict(fixed); params["sp"] = page
            try:
                r = s.get(endpoint, params=params, timeout=120)
                diagnostics.append({"endpoint": endpoint, "params": params, "status": r.status_code, "url": r.url})
                if not r.ok:
                    ok = False; break
                data = r.json()
            except Exception as exc:
                diagnostics.append({"endpoint": endpoint, "params": params, "error": repr(exc)})
                ok = False; break
            batch = data.get("results") or []
            if not facet_exact:
                batch = [x for x in batch if label.lower() in _partof_text(x) or label.lower() in json.dumps(x, ensure_ascii=False).lower()]
            rows.extend(batch)
            pag = data.get("pagination") or {}
            if not (data.get("results") or []) or not pag.get("next"):
                break
            page += 1
        unique = {}
        for row in rows:
            u = row.get("id") or row.get("url")
            if u:
                unique[u] = row
        rows = list(unique.values())
        print(f"LOC_DISCOVERY endpoint={endpoint} facet_exact={facet_exact} items={len(rows)}", flush=True)
        if ok and len(rows) > len(best):
            best = rows
        if len(rows) >= max(100, int(expected * 0.85)):
            return rows
    raise RuntimeError(f"LOC Persian discovery incomplete: best={len(best)} expected~{expected}; diagnostics={diagnostics[-8:]}")


def process_loc(s, cfg: dict, work: Path, remote: str) -> dict:
    results = _loc_discover(s, cfg)
    items_dir = work / "items"; html_dir = work / "html"; iiif_dir = work / "iiif"
    items_dir.mkdir(parents=True, exist_ok=True); html_dir.mkdir(parents=True, exist_ok=True); iiif_dir.mkdir(parents=True, exist_ok=True)
    inventory = []
    errors = []
    manifest_count = 0
    for i, row in enumerate(results, 1):
        item_url = row.get("id") or row.get("url")
        if not item_url:
            continue
        item_url = item_url.rstrip("/") + "/"
        item_id = row.get("item_id") or item_url.rstrip("/").split("/")[-1]
        print(f"LOC {i}/{len(results)} {item_id}", flush=True)
        try:
            jr = s.get(item_url, params={"fo": "json"}, timeout=120)
            jr.raise_for_status(); item_json = jr.json()
        except Exception as exc:
            errors.append({"item_id": item_id, "stage": "item_json", "error": repr(exc)})
            continue
        html = ""
        try:
            hr = s.get(item_url, timeout=120)
            if hr.ok:
                html = hr.text
                (html_dir / f"{item_id}.html").write_text(html, encoding="utf-8")
        except Exception:
            pass
        base.dump_json(items_dir / f"{item_id}.json", item_json)
        mu = base.loc_manifest_url(s, item_json, html)
        manifest_sha = None
        if mu:
            try:
                mr = s.get(mu, timeout=120); mr.raise_for_status()
                obj = mr.json()
                p = iiif_dir / f"{item_id}.json"
                base.dump_json(p, obj)
                manifest_sha = base.sha256_file(p)
                manifest_count += 1
            except Exception as exc:
                errors.append({"item_id": item_id, "stage": "iiif", "url": mu, "error": repr(exc)})
                mu = None
        inventory.append({
            "item_id": item_id,
            "item_url": item_url,
            "title": row.get("title") or item_json.get("title"),
            "date": row.get("date") or item_json.get("date"),
            "language": row.get("language") or item_json.get("language"),
            "iiif_manifest": mu,
            "iiif_sha256": manifest_sha,
        })
    inventory.sort(key=lambda x: x["item_id"])
    identity = base.sha256_bytes(b"".join((json.dumps(x, ensure_ascii=False, sort_keys=True) + "\n").encode() for x in inventory))
    base.dump_jsonl(work / "meta" / "inventory.jsonl", inventory)
    base.dump_json(work / "meta" / "SOURCE.json", {
        "schema_version": "osr-rescue-source-v2",
        "source_id": cfg["id"], "items_discovered": len(results), "items_saved": len(inventory),
        "iiif_manifests": manifest_count, "inventory_sha256": identity,
        "errors": errors, "rights_note": cfg.get("rights_note"), "image_policy": cfg.get("image_policy"),
    })
    base.rclone_copy_dir(items_dir, f"{remote}/item_json")
    base.rclone_copy_dir(html_dir, f"{remote}/item_html")
    base.rclone_copy_dir(iiif_dir, f"{remote}/iiif")
    base.rclone_copy_dir(work / "meta", f"{remote}/meta")
    expected = int(cfg.get("expected_items", 173))
    # Discovery must be close to the known 173-item collection. A weak inventory is a hard failure, not a green partial.
    status = "PASS" if len(inventory) >= int(expected * 0.85) and manifest_count > 0 else "FAILED_INCOMPLETE"
    complete = {"identity": identity, "status": status, "items": len(inventory), "iiif_manifests": manifest_count, "errors": len(errors)}
    base.dump_json(work / "COMPLETE.json", complete)
    base.rclone_copyto(work / "COMPLETE.json", f"{remote}/meta/COMPLETE.json")
    return complete


def _manifest_from_page(s, page_url: str) -> tuple[str | None, str]:
    r = s.get(page_url, timeout=120)
    r.raise_for_status()
    html = r.text
    urls = re.findall(r'https?://(?:www\.)?qdl\.qa/(?:en/)?iiif/[^"\'<>\s]+/manifest', html, flags=re.I)
    urls += [urljoin(r.url, x.replace("&amp;", "&")) for x in re.findall(r'href=["\']([^"\']*/iiif/[^"\']*/manifest)["\']', html, flags=re.I)]
    for u in urls:
        u = u.replace("http://", "https://")
        try:
            mr = s.get(u, timeout=120)
            if mr.ok:
                mr.json()
                return mr.url, html
        except Exception:
            pass
    return None, html


def process_qdl(s, cfg: dict, work: Path, remote: str) -> dict:
    archive_urls = set(cfg.get("seed_archive_urls", []))
    # Keep opportunistic site discovery, but do not depend on it.
    try:
        archive_urls.update(base.qdl_search_urls(s, cfg))
    except Exception as exc:
        print("QDL search discovery warning:", repr(exc), flush=True)
    records_dir = work / "record_html"; iiif_dir = work / "iiif"
    records_dir.mkdir(parents=True, exist_ok=True); iiif_dir.mkdir(parents=True, exist_ok=True)
    manifests: dict[str, dict] = {}

    # Verified seeds guarantee a non-empty preservation baseline even if site search markup changes.
    for mu in cfg.get("verified_seed_manifests", []):
        try:
            mr = s.get(mu, timeout=120); mr.raise_for_status(); obj = mr.json()
            mid = hashlib.sha1(mu.encode()).hexdigest()[:16]
            p = iiif_dir / f"{mid}.json"; base.dump_json(p, obj)
            manifests[mr.url] = {"manifest": mr.url, "sha256": base.sha256_file(p), "rights": obj.get("license") or obj.get("rights"), "discovered_via": "verified_seed"}
        except Exception as exc:
            print("QDL verified seed failed", mu, repr(exc), flush=True)

    for i, u in enumerate(sorted(archive_urls), 1):
        print(f"QDL {i}/{len(archive_urls)} {u}", flush=True)
        try:
            mu, html = _manifest_from_page(s, u)
        except Exception as exc:
            print("QDL page failed", u, repr(exc), flush=True)
            continue
        rid = u.rstrip("/").split("/")[-1]
        (records_dir / f"{rid}.html").write_text(html, encoding="utf-8")
        if not mu or mu in manifests:
            continue
        try:
            mr = s.get(mu, timeout=120); mr.raise_for_status(); obj = mr.json()
            mid = hashlib.sha1(mu.encode()).hexdigest()[:16]
            p = iiif_dir / f"{mid}.json"; base.dump_json(p, obj)
            manifests[mr.url] = {"manifest": mr.url, "sha256": base.sha256_file(p), "rights": obj.get("license") or obj.get("rights"), "discovered_via": u}
        except Exception as exc:
            print("QDL manifest failed", mu, repr(exc), flush=True)

    inv = sorted(manifests.values(), key=lambda x: x["manifest"])
    identity = base.sha256_bytes(b"".join((json.dumps(x, ensure_ascii=False, sort_keys=True) + "\n").encode() for x in inv))
    base.dump_jsonl(work / "meta" / "inventory.jsonl", inv)
    base.dump_json(work / "meta" / "SOURCE.json", {
        "schema_version": "osr-rescue-source-v2", "source_id": cfg["id"],
        "archive_pages_discovered": len(archive_urls), "iiif_manifests": len(inv),
        "inventory_sha256": identity, "queries": cfg.get("queries"), "seed_archive_urls": cfg.get("seed_archive_urls"),
        "image_policy": cfg.get("image_policy"), "rights_note": cfg.get("rights_note"),
    })
    base.rclone_copy_dir(records_dir, f"{remote}/record_html")
    base.rclone_copy_dir(iiif_dir, f"{remote}/iiif")
    base.rclone_copy_dir(work / "meta", f"{remote}/meta")
    minimum = int(cfg.get("minimum_manifests", 1))
    status = "PASS" if len(inv) >= minimum else "FAILED_EMPTY"
    complete = {"identity": identity, "status": status, "archive_pages": len(archive_urls), "iiif_manifests": len(inv)}
    base.dump_json(work / "COMPLETE.json", complete)
    base.rclone_copyto(work / "COMPLETE.json", f"{remote}/meta/COMPLETE.json")
    return complete


base.process_loc = process_loc
base.process_qdl = process_qdl

if __name__ == "__main__":
    raise SystemExit(base.main())
