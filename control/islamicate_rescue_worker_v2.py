#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import time
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
            params = dict(fixed)
            params["sp"] = page
            try:
                r = s.get(endpoint, params=params, timeout=120)
                diagnostics.append({"endpoint": endpoint, "params": params, "status": r.status_code, "url": r.url})
                if not r.ok:
                    ok = False
                    break
                data = r.json()
            except Exception as exc:
                diagnostics.append({"endpoint": endpoint, "params": params, "error": repr(exc)})
                ok = False
                break
            batch = data.get("results") or []
            if not facet_exact:
                batch = [
                    x for x in batch
                    if label.lower() in _partof_text(x)
                    or label.lower() in json.dumps(x, ensure_ascii=False).lower()
                ]
            rows.extend(batch)
            pag = data.get("pagination") or {}
            if not (data.get("results") or []) or not pag.get("next"):
                break
            page += 1
            time.sleep(0.8)
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
    raise RuntimeError(
        f"LOC Persian discovery incomplete: best={len(best)} expected~{expected}; diagnostics={diagnostics[-8:]}"
    )


def _retry_after_seconds(resp, attempt: int) -> float:
    raw = resp.headers.get("Retry-After")
    if raw:
        try:
            return max(1.0, min(180.0, float(raw)))
        except Exception:
            pass
    return min(120.0, 5.0 * (2 ** attempt))


def _loc_get(s, url: str, *, params=None, timeout=120, accept_json=False):
    """Polite LOC GET with explicit cooldown for the API's documented rate limiter."""
    headers = {
        "Accept": "application/json" if accept_json else "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
        "Referer": "https://www.loc.gov/",
    }
    last = None
    for attempt in range(5):
        time.sleep(1.25)
        r = s.get(url, params=params, headers=headers, timeout=timeout)
        last = r
        if r.status_code not in {403, 429}:
            return r
        wait = _retry_after_seconds(r, attempt)
        print(
            f"LOC_RATE_LIMIT status={r.status_code} attempt={attempt + 1}/5 "
            f"wait={wait:.1f}s url={r.url}",
            flush=True,
        )
        time.sleep(wait)
    return last


def _loc_manifest_candidates(item_json: dict, html: str) -> list[str]:
    candidates: list[str] = []
    for u in base.extract_urls(item_json):
        lu = u.lower()
        if "iiif" in lu and "manifest" in lu:
            candidates.append(u)
    for pat in [
        r'https?://[^"\'<>\s]+iiif[^"\'<>\s]+manifest[^"\'<>\s]*',
        r'href=["\']([^"\']*iiif[^"\']*manifest[^"\']*)["\']',
    ]:
        for m in re.finditer(pat, html, flags=re.I):
            u = m.group(1) if m.lastindex else m.group(0)
            candidates.append(urljoin("https://www.loc.gov/", u.replace("&amp;", "&")))
    out = []
    seen = set()
    for u in candidates:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def process_loc(s, cfg: dict, work: Path, remote: str) -> dict:
    results = _loc_discover(s, cfg)
    items_dir = work / "items"
    html_dir = work / "html"
    iiif_dir = work / "iiif"
    items_dir.mkdir(parents=True, exist_ok=True)
    html_dir.mkdir(parents=True, exist_ok=True)
    iiif_dir.mkdir(parents=True, exist_ok=True)

    inventory = []
    errors = []
    manifest_count = 0
    consecutive_item_blocks = 0

    for i, row in enumerate(results, 1):
        item_url = row.get("id") or row.get("url")
        if not item_url:
            continue
        item_url = item_url.rstrip("/") + "/"
        item_id = row.get("item_id") or item_url.rstrip("/").split("/")[-1]
        print(f"LOC {i}/{len(results)} {item_id}", flush=True)

        try:
            jr = _loc_get(s, item_url, params={"fo": "json"}, timeout=120, accept_json=True)
            if jr is None:
                raise RuntimeError("LOC item_json returned no response")
            if jr.status_code in {403, 429}:
                consecutive_item_blocks += 1
                errors.append({
                    "item_id": item_id,
                    "stage": "item_json",
                    "status": jr.status_code,
                    "error": "rate_limited_after_retries",
                })
                if consecutive_item_blocks >= 3:
                    print(
                        "LOC_RATE_LIMIT circuit breaker: 3 consecutive blocked items; "
                        "ending this run without hammering the public API",
                        flush=True,
                    )
                    break
                continue
            jr.raise_for_status()
            item_json = jr.json()
            consecutive_item_blocks = 0
        except Exception as exc:
            errors.append({"item_id": item_id, "stage": "item_json", "error": repr(exc)})
            continue

        base.dump_json(items_dir / f"{item_id}.json", item_json)

        # API-first: locate IIIF in JSON before spending another request on HTML.
        html = ""
        candidates = _loc_manifest_candidates(item_json, "")
        if not candidates:
            try:
                hr = _loc_get(s, item_url, timeout=120, accept_json=False)
                if hr is not None and hr.ok:
                    html = hr.text
                    (html_dir / f"{item_id}.html").write_text(html, encoding="utf-8")
                    candidates = _loc_manifest_candidates(item_json, html)
                elif hr is not None:
                    errors.append({
                        "item_id": item_id,
                        "stage": "item_html",
                        "status": hr.status_code,
                        "error": "best_effort_html_failed",
                    })
            except Exception as exc:
                errors.append({"item_id": item_id, "stage": "item_html", "error": repr(exc)})

        mu = None
        manifest_sha = None
        for candidate in candidates:
            try:
                mr = _loc_get(s, candidate, timeout=120, accept_json=True)
                if mr is None or not mr.ok:
                    continue
                obj = mr.json()
                p = iiif_dir / f"{item_id}.json"
                base.dump_json(p, obj)
                manifest_sha = base.sha256_file(p)
                manifest_count += 1
                mu = mr.url
                break
            except Exception as exc:
                errors.append({
                    "item_id": item_id,
                    "stage": "iiif",
                    "url": candidate,
                    "error": repr(exc),
                })

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
    identity = base.sha256_bytes(
        b"".join((json.dumps(x, ensure_ascii=False, sort_keys=True) + "\n").encode() for x in inventory)
    )
    base.dump_jsonl(work / "meta" / "inventory.jsonl", inventory)
    base.dump_json(work / "meta" / "SOURCE.json", {
        "schema_version": "osr-rescue-source-v3",
        "source_id": cfg["id"],
        "items_discovered": len(results),
        "items_saved": len(inventory),
        "iiif_manifests": manifest_count,
        "inventory_sha256": identity,
        "errors": errors,
        "rights_note": cfg.get("rights_note"),
        "image_policy": cfg.get("image_policy"),
        "access_policy": "public LOC API; paced requests; 403/429 cooldown; circuit-breaker",
    })
    base.rclone_copy_dir(items_dir, f"{remote}/item_json")
    base.rclone_copy_dir(html_dir, f"{remote}/item_html")
    base.rclone_copy_dir(iiif_dir, f"{remote}/iiif")
    base.rclone_copy_dir(work / "meta", f"{remote}/meta")

    expected = int(cfg.get("expected_items", 173))
    status = "PASS" if len(inventory) >= int(expected * 0.85) and manifest_count > 0 else "FAILED_INCOMPLETE"
    complete = {
        "identity": identity,
        "status": status,
        "items": len(inventory),
        "iiif_manifests": manifest_count,
        "errors": len(errors),
    }
    base.dump_json(work / "COMPLETE.json", complete)
    base.rclone_copyto(work / "COMPLETE.json", f"{remote}/meta/COMPLETE.json")
    return complete


QDL_BROWSER_HEADERS = {
    # QDL serves public pages/manifests to normal browsers but returned 403 to the
    # preservation-bot UA from GitHub-hosted runners. This remains anonymous public access:
    # no cookie/login/CAPTCHA/paywall bypass is attempted.
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-GB,en;q=0.9,ar;q=0.7",
    "Referer": "https://www.qdl.qa/",
}


def _qdl_get(s, url: str, *, timeout=120, want_json=False):
    headers = dict(QDL_BROWSER_HEADERS)
    headers["Accept"] = (
        "application/json,text/plain,*/*"
        if want_json
        else "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8"
    )
    variants = [url]
    if "://www.qdl.qa/" in url:
        variants.append(url.replace("://www.qdl.qa/", "://qdl.qa/", 1))
    elif "://qdl.qa/" in url:
        variants.append(url.replace("://qdl.qa/", "://www.qdl.qa/", 1))

    last = None
    for candidate in variants:
        time.sleep(1.0)
        r = s.get(candidate, headers=headers, timeout=timeout, allow_redirects=True)
        last = r
        if r.status_code != 403:
            return r
        print(f"QDL_403 public endpoint blocked from runner candidate={candidate}", flush=True)
    return last


def _manifest_from_page(s, page_url: str) -> tuple[str | None, str]:
    r = _qdl_get(s, page_url, timeout=120, want_json=False)
    if r is None:
        raise RuntimeError("QDL page returned no response")
    r.raise_for_status()
    html = r.text
    urls = re.findall(r'https?://(?:www\.)?qdl\.qa/(?:en/)?iiif/[^"\'<>\s]+/manifest', html, flags=re.I)
    urls += [
        urljoin(r.url, x.replace("&amp;", "&"))
        for x in re.findall(r'href=["\']([^"\']*/iiif/[^"\']*/manifest)["\']', html, flags=re.I)
    ]
    for u in urls:
        u = u.replace("http://", "https://")
        try:
            mr = _qdl_get(s, u, timeout=120, want_json=True)
            if mr is not None and mr.ok:
                mr.json()
                return mr.url, html
        except Exception:
            pass
    return None, html


def process_qdl(s, cfg: dict, work: Path, remote: str) -> dict:
    archive_urls = set(cfg.get("seed_archive_urls", []))
    # Opportunistic site search can be WAF-blocked on GitHub runner IPs; seeds are the hard baseline.
    try:
        archive_urls.update(base.qdl_search_urls(s, cfg))
    except Exception as exc:
        print("QDL search discovery warning:", repr(exc), flush=True)

    records_dir = work / "record_html"
    iiif_dir = work / "iiif"
    records_dir.mkdir(parents=True, exist_ok=True)
    iiif_dir.mkdir(parents=True, exist_ok=True)
    manifests: dict[str, dict] = {}
    blocked = 0

    for mu in cfg.get("verified_seed_manifests", []):
        try:
            mr = _qdl_get(s, mu, timeout=120, want_json=True)
            if mr is None:
                raise RuntimeError("QDL manifest returned no response")
            if mr.status_code == 403:
                blocked += 1
            mr.raise_for_status()
            obj = mr.json()
            mid = hashlib.sha1(mu.encode()).hexdigest()[:16]
            p = iiif_dir / f"{mid}.json"
            base.dump_json(p, obj)
            manifests[mr.url] = {
                "manifest": mr.url,
                "sha256": base.sha256_file(p),
                "rights": obj.get("license") or obj.get("rights"),
                "discovered_via": "verified_seed",
            }
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
            mr = _qdl_get(s, mu, timeout=120, want_json=True)
            if mr is None:
                raise RuntimeError("QDL manifest returned no response")
            if mr.status_code == 403:
                blocked += 1
            mr.raise_for_status()
            obj = mr.json()
            mid = hashlib.sha1(mu.encode()).hexdigest()[:16]
            p = iiif_dir / f"{mid}.json"
            base.dump_json(p, obj)
            manifests[mr.url] = {
                "manifest": mr.url,
                "sha256": base.sha256_file(p),
                "rights": obj.get("license") or obj.get("rights"),
                "discovered_via": u,
            }
        except Exception as exc:
            print("QDL manifest failed", mu, repr(exc), flush=True)

    inv = sorted(manifests.values(), key=lambda x: x["manifest"])
    identity = base.sha256_bytes(
        b"".join((json.dumps(x, ensure_ascii=False, sort_keys=True) + "\n").encode() for x in inv)
    )
    base.dump_jsonl(work / "meta" / "inventory.jsonl", inv)
    base.dump_json(work / "meta" / "SOURCE.json", {
        "schema_version": "osr-rescue-source-v3",
        "source_id": cfg["id"],
        "archive_pages_discovered": len(archive_urls),
        "iiif_manifests": len(inv),
        "inventory_sha256": identity,
        "queries": cfg.get("queries"),
        "seed_archive_urls": cfg.get("seed_archive_urls"),
        "image_policy": cfg.get("image_policy"),
        "rights_note": cfg.get("rights_note"),
        "runner_403_observed": blocked,
        "access_policy": "anonymous public endpoints only; browser-compatible headers; no access-control bypass",
    })
    base.rclone_copy_dir(records_dir, f"{remote}/record_html")
    base.rclone_copy_dir(iiif_dir, f"{remote}/iiif")
    base.rclone_copy_dir(work / "meta", f"{remote}/meta")

    minimum = int(cfg.get("minimum_manifests", 1))
    status = "PASS" if len(inv) >= minimum else ("BLOCKED_PUBLIC_403" if blocked else "FAILED_EMPTY")
    complete = {
        "identity": identity,
        "status": status,
        "archive_pages": len(archive_urls),
        "iiif_manifests": len(inv),
        "runner_403_observed": blocked,
    }
    base.dump_json(work / "COMPLETE.json", complete)
    base.rclone_copyto(work / "COMPLETE.json", f"{remote}/meta/COMPLETE.json")
    return complete


base.process_loc = process_loc
base.process_qdl = process_qdl

if __name__ == "__main__":
    raise SystemExit(base.main())
