#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from urllib.parse import quote, urljoin, urlparse
import zipfile

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


def sess() -> requests.Session:
    retry = Retry(
        total=8, connect=8, read=8, backoff_factor=1.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET", "HEAD"]),
        raise_on_status=False,
    )
    s = requests.Session()
    s.headers.update({
        "User-Agent": "OSR-Islamicate-Rescue/1.0 (preservation research; GitHub Actions)",
        "Accept-Language": "en,fa,ar;q=0.8",
    })
    s.mount("https://", HTTPAdapter(max_retries=retry))
    return s


def run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    print("+", " ".join(cmd), flush=True)
    return subprocess.run(cmd, check=check, text=True)


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        while True:
            b = f.read(8 * 1024 * 1024)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def dump_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def dump_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def rclone_copyto(src: Path, dst: str) -> None:
    run([
        "rclone", "copyto", str(src), dst,
        "--drive-chunk-size", "64M", "--retries", "8",
        "--low-level-retries", "16", "--timeout", "10m",
        "--contimeout", "30s", "--stats", "30s",
    ])


def rclone_copy_dir(src: Path, dst: str) -> None:
    if not src.exists():
        return
    run([
        "rclone", "copy", str(src), dst,
        "--drive-chunk-size", "64M", "--transfers", "6",
        "--checkers", "12", "--retries", "8", "--low-level-retries", "16",
        "--timeout", "10m", "--contimeout", "30s", "--stats", "30s",
    ])


def rclone_cat(path: str) -> str | None:
    p = subprocess.run(["rclone", "cat", path], text=True, capture_output=True)
    return p.stdout if p.returncode == 0 else None


def download(s: requests.Session, url: str, out: Path) -> tuple[int, str]:
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".part")
    tmp.unlink(missing_ok=True)
    h = hashlib.sha256()
    size = 0
    with s.get(url, stream=True, timeout=(30, 900)) as r:
        r.raise_for_status()
        with tmp.open("wb") as f:
            for chunk in r.iter_content(8 * 1024 * 1024):
                if not chunk:
                    continue
                f.write(chunk)
                h.update(chunk)
                size += len(chunk)
    os.replace(tmp, out)
    return size, h.hexdigest()


def header_snapshot(s: requests.Session, url: str) -> dict:
    r = s.head(url, allow_redirects=True, timeout=60)
    if r.status_code >= 400:
        r = s.get(url, stream=True, timeout=60)
    return {
        "url": r.url,
        "etag": r.headers.get("ETag"),
        "last_modified": r.headers.get("Last-Modified"),
        "content_length": r.headers.get("Content-Length"),
        "content_type": r.headers.get("Content-Type"),
    }


def extract_urls(obj) -> list[str]:
    out: list[str] = []
    def walk(x):
        if isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
        elif isinstance(x, str) and x.startswith(("http://", "https://")):
            out.append(x)
    walk(obj)
    return out


def loc_manifest_url(s: requests.Session, item_json: dict, html: str) -> str | None:
    candidates = []
    for u in extract_urls(item_json):
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
    seen = set()
    for u in candidates:
        if u in seen:
            continue
        seen.add(u)
        try:
            r = s.get(u, timeout=60)
            if r.ok and "json" in r.headers.get("Content-Type", "").lower():
                r.json()
                return r.url
        except Exception:
            continue
    return None


def process_ganjoor(s: requests.Session, cfg: dict, work: Path, remote: str) -> dict:
    url = cfg["download_url"]
    hdr = header_snapshot(s, url)
    identity = sha256_bytes((cfg["version"] + "|" + url + "|" + str(hdr)).encode())
    prev = rclone_cat(f"{remote}/meta/COMPLETE.json")
    if prev:
        try:
            if json.loads(prev).get("identity") == identity:
                return {"status": "SKIP_COMPLETE", "identity": identity}
        except Exception:
            pass

    zip_path = work / "raw" / "ganjoor.s3db.zip"
    size, sha = download(s, url, zip_path)
    if cfg.get("expected_bytes") and size != int(cfg["expected_bytes"]):
        raise RuntimeError(f"Ganjoor byte mismatch: expected {cfg['expected_bytes']} got {size}")
    extract = work / "derived"
    extract.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(extract)
    dbs = list(extract.rglob("*.s3db")) + list(extract.rglob("*.sqlite")) + list(extract.rglob("*.db"))
    if not dbs:
        raise RuntimeError("Ganjoor SQLite file not found in release zip")
    db = dbs[0]
    tables = []
    con = sqlite3.connect(str(db))
    try:
        for (name,) in con.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%' order by name"):
            try:
                count = int(con.execute(f'SELECT COUNT(*) FROM "{name.replace(chr(34), chr(34)*2)}"').fetchone()[0])
            except Exception:
                count = -1
            tables.append({"name": name, "rows": count})
    finally:
        con.close()
    db_sha = sha256_file(db)
    source = {
        "schema_version": "osr-rescue-source-v1", "source_id": cfg["id"],
        "version": cfg["version"], "source_page": cfg.get("source_page"),
        "download_url": url, "headers": hdr, "identity": identity,
        "archive_sha256": sha, "archive_bytes": size, "sqlite_sha256": db_sha,
        "tables": tables, "rights_note": cfg.get("rights_note"),
    }
    dump_json(work / "meta" / "SOURCE.json", source)
    rclone_copy_dir(work / "raw", f"{remote}/raw")
    rclone_copyto(db, f"{remote}/derived/{db.name}")
    rclone_copy_dir(work / "meta", f"{remote}/meta")
    complete = {"identity": identity, "status": "PASS", "archive_sha256": sha, "sqlite_sha256": db_sha}
    dump_json(work / "COMPLETE.json", complete)
    rclone_copyto(work / "COMPLETE.json", f"{remote}/meta/COMPLETE.json")
    return complete


def process_hmml(s: requests.Session, cfg: dict, work: Path, remote_root: str) -> dict:
    hdr = header_snapshot(s, cfg["download_url"])
    # HMML dataset is rolling; use Last-Modified when present, otherwise retrieval UTC date.
    stamp = (hdr.get("last_modified") or time.strftime("%Y-%m-%d", time.gmtime())).replace("/", "-").replace(":", "-")
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", stamp).strip("_")
    remote = f"{remote_root}/{safe}"
    identity = sha256_bytes((cfg["download_url"] + "|" + json.dumps(hdr, sort_keys=True)).encode())
    prev = rclone_cat(f"{remote}/meta/COMPLETE.json")
    if prev:
        try:
            if json.loads(prev).get("identity") == identity:
                return {"status": "SKIP_COMPLETE", "identity": identity, "snapshot": safe}
        except Exception:
            pass
    zp = work / "raw" / "vhmml_rr_fulldata.zip"
    size, sha = download(s, cfg["download_url"], zp)
    out = work / "derived"
    out.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zp) as zf:
        names = zf.namelist()
        zf.extractall(out)
    extracted = []
    for p in sorted(out.rglob("*")):
        if p.is_file():
            extracted.append({"file": str(p.relative_to(out)), "bytes": p.stat().st_size, "sha256": sha256_file(p)})
    source = {
        "schema_version": "osr-rescue-source-v1", "source_id": cfg["id"],
        "snapshot": safe, "download_url": cfg["download_url"], "headers": hdr,
        "identity": identity, "archive_bytes": size, "archive_sha256": sha,
        "license": cfg.get("license"), "rights_note": cfg.get("rights_note"),
        "extracted": extracted,
    }
    dump_json(work / "meta" / "SOURCE.json", source)
    rclone_copy_dir(work / "raw", f"{remote}/raw")
    rclone_copy_dir(out, f"{remote}/derived")
    rclone_copy_dir(work / "meta", f"{remote}/meta")
    complete = {"identity": identity, "status": "PASS", "snapshot": safe, "archive_sha256": sha, "files": len(extracted)}
    dump_json(work / "COMPLETE.json", complete)
    rclone_copyto(work / "COMPLETE.json", f"{remote}/meta/COMPLETE.json")
    return complete


def process_loc(s: requests.Session, cfg: dict, work: Path, remote: str) -> dict:
    results: list[dict] = []
    page = 1
    while True:
        u = f"https://www.loc.gov/collections/{cfg['collection_slug']}/"
        r = s.get(u, params={"fo": "json", "c": 100, "sp": page, "at": "results,pagination"}, timeout=120)
        r.raise_for_status()
        data = r.json()
        batch = data.get("results") or []
        results.extend(batch)
        pag = data.get("pagination") or {}
        if not batch or not pag.get("next"):
            break
        page += 1
        if page > 20:
            raise RuntimeError("LOC pagination runaway")

    items_dir = work / "items"
    html_dir = work / "html"
    iiif_dir = work / "iiif"
    items_dir.mkdir(parents=True, exist_ok=True); html_dir.mkdir(parents=True, exist_ok=True); iiif_dir.mkdir(parents=True, exist_ok=True)
    inventory = []
    manifest_count = 0
    for i, row in enumerate(results, 1):
        item_url = row.get("id") or row.get("url")
        if not item_url:
            continue
        item_url = item_url.rstrip("/") + "/"
        item_id = row.get("item_id") or item_url.rstrip("/").split("/")[-1]
        print(f"LOC {i}/{len(results)} {item_id}", flush=True)
        jr = s.get(item_url, params={"fo": "json"}, timeout=120)
        jr.raise_for_status(); item_json = jr.json()
        hr = s.get(item_url, timeout=120); hr.raise_for_status(); html = hr.text
        dump_json(items_dir / f"{item_id}.json", item_json)
        (html_dir / f"{item_id}.html").write_text(html, encoding="utf-8")
        mu = loc_manifest_url(s, item_json, html)
        manifest_sha = None
        if mu:
            mr = s.get(mu, timeout=120); mr.raise_for_status()
            mb = mr.content
            (iiif_dir / f"{item_id}.json").write_bytes(mb)
            manifest_sha = sha256_bytes(mb)
            manifest_count += 1
        inventory.append({
            "item_id": item_id, "item_url": item_url, "title": row.get("title"),
            "date": row.get("date"), "language": row.get("language"),
            "iiif_manifest": mu, "iiif_sha256": manifest_sha,
        })
    inventory.sort(key=lambda x: x["item_id"])
    inv_bytes = b"".join((json.dumps(x, ensure_ascii=False, sort_keys=True) + "\n").encode() for x in inventory)
    identity = sha256_bytes(inv_bytes)
    dump_jsonl(work / "meta" / "inventory.jsonl", inventory)
    dump_json(work / "meta" / "SOURCE.json", {
        "schema_version": "osr-rescue-source-v1", "source_id": cfg["id"],
        "collection_url": cfg["collection_url"], "items": len(inventory),
        "iiif_manifests": manifest_count, "inventory_sha256": identity,
        "rights_note": cfg.get("rights_note"), "image_policy": cfg.get("image_policy"),
    })
    rclone_copy_dir(items_dir, f"{remote}/item_json")
    rclone_copy_dir(html_dir, f"{remote}/item_html")
    rclone_copy_dir(iiif_dir, f"{remote}/iiif")
    rclone_copy_dir(work / "meta", f"{remote}/meta")
    complete = {"identity": identity, "status": "PASS", "items": len(inventory), "iiif_manifests": manifest_count}
    if cfg.get("expected_items") and len(inventory) < int(cfg["expected_items"]) * 0.9:
        complete["status"] = "PARTIAL"
        complete["warning"] = f"Expected about {cfg['expected_items']} items, discovered {len(inventory)}"
    dump_json(work / "COMPLETE.json", complete)
    rclone_copyto(work / "COMPLETE.json", f"{remote}/meta/COMPLETE.json")
    return complete


def qdl_search_urls(s: requests.Session, cfg: dict) -> list[str]:
    found = set()
    for query in cfg.get("queries", []):
        no_new = 0
        for page in range(int(cfg.get("max_pages_per_query", 10))):
            urls = [
                cfg["search_base"] + "?q=" + quote(query) + f"&page={page}",
                cfg["search_base"] + "?search_api_fulltext=" + quote(query) + f"&page={page}",
            ]
            page_links = set()
            for u in urls:
                try:
                    r = s.get(u, timeout=120)
                    if not r.ok:
                        continue
                    soup = BeautifulSoup(r.text, "html.parser")
                    for a in soup.find_all("a", href=True):
                        href = urljoin(r.url, a["href"])
                        if "/archive/81055/" in href:
                            page_links.add(href.split("#", 1)[0].replace("/en/archive/", "/archive/"))
                except Exception:
                    continue
            before = len(found); found.update(page_links)
            if len(found) == before:
                no_new += 1
            else:
                no_new = 0
            if no_new >= 2:
                break
    return sorted(found)


def process_qdl(s: requests.Session, cfg: dict, work: Path, remote: str) -> dict:
    archive_urls = qdl_search_urls(s, cfg)
    records_dir = work / "record_html"; iiif_dir = work / "iiif"
    records_dir.mkdir(parents=True, exist_ok=True); iiif_dir.mkdir(parents=True, exist_ok=True)
    manifests: dict[str, dict] = {}
    for i, u in enumerate(archive_urls, 1):
        print(f"QDL {i}/{len(archive_urls)} {u}", flush=True)
        r = s.get(u, timeout=120)
        if not r.ok:
            continue
        html = r.text
        rid = u.rstrip("/").split("/")[-1]
        (records_dir / f"{rid}.html").write_text(html, encoding="utf-8")
        urls = re.findall(r'https?://(?:www\.)?qdl\.qa/(?:en/)?iiif/[^"\'<>\s]+/manifest', html, flags=re.I)
        # Known QDL pages sometimes escape manifest links inside attributes.
        urls += [urljoin(r.url, x.replace("&amp;", "&")) for x in re.findall(r'href=["\']([^"\']*/iiif/[^"\']*/manifest)["\']', html, flags=re.I)]
        for mu in urls:
            mu = mu.replace("http://", "https://")
            if mu in manifests:
                continue
            try:
                mr = s.get(mu, timeout=120)
                if not mr.ok:
                    continue
                obj = mr.json()
                mid = hashlib.sha1(mu.encode()).hexdigest()[:16]
                p = iiif_dir / f"{mid}.json"
                dump_json(p, obj)
                rights = obj.get("license") or obj.get("rights")
                manifests[mu] = {"manifest": mu, "sha256": sha256_file(p), "rights": rights}
            except Exception:
                continue
    inv = sorted(manifests.values(), key=lambda x: x["manifest"])
    identity = sha256_bytes(b"".join((json.dumps(x, sort_keys=True) + "\n").encode() for x in inv))
    dump_jsonl(work / "meta" / "inventory.jsonl", inv)
    dump_json(work / "meta" / "SOURCE.json", {
        "schema_version": "osr-rescue-source-v1", "source_id": cfg["id"],
        "archive_pages_discovered": len(archive_urls), "iiif_manifests": len(inv),
        "inventory_sha256": identity, "queries": cfg.get("queries"),
        "image_policy": cfg.get("image_policy"), "rights_note": cfg.get("rights_note"),
    })
    rclone_copy_dir(records_dir, f"{remote}/record_html")
    rclone_copy_dir(iiif_dir, f"{remote}/iiif")
    rclone_copy_dir(work / "meta", f"{remote}/meta")
    complete = {"identity": identity, "status": "PASS" if inv else "PARTIAL", "archive_pages": len(archive_urls), "iiif_manifests": len(inv)}
    dump_json(work / "COMPLETE.json", complete)
    rclone_copyto(work / "COMPLETE.json", f"{remote}/meta/COMPLETE.json")
    return complete


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source-id", required=True)
    ap.add_argument("--registry", default="control/islamicate_rescue_targets.json")
    ap.add_argument("--work-dir", required=True)
    args = ap.parse_args()
    reg = json.loads(Path(args.registry).read_text(encoding="utf-8"))
    cfg = next((x for x in reg["sources"] if x["id"] == args.source_id), None)
    if not cfg:
        raise SystemExit(f"unknown source {args.source_id}")
    if not cfg.get("enabled"):
        raise SystemExit(f"source disabled: {args.source_id}")
    work = Path(args.work_dir)
    if work.exists(): shutil.rmtree(work)
    work.mkdir(parents=True)
    s = sess()
    root = reg["destination_root"].strip("/")
    remote_base = f"gdrive:{root}/{cfg['id']}"
    kind = cfg["kind"]
    started = time.time()
    if kind == "ganjoor_sqlite":
        result = process_ganjoor(s, cfg, work, f"{remote_base}/{cfg['version']}")
    elif kind == "hmml_metadata":
        result = process_hmml(s, cfg, work, remote_base)
    elif kind == "loc_collection":
        result = process_loc(s, cfg, work, remote_base)
    elif kind == "qdl_manifest_discovery":
        result = process_qdl(s, cfg, work, remote_base)
    else:
        raise RuntimeError(f"unsupported kind {kind}")
    result.update({"source_id": cfg["id"], "kind": kind, "elapsed_seconds": round(time.time() - started, 3)})
    print("RESULT_JSON=" + json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("status") in {"PASS", "SKIP_COMPLETE", "PARTIAL"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
