#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime
from pathlib import Path

ROOTS = [
    ("curated", "gdrive:龍族古籍源庫｜Dragon Source Corpus/OPEN_CURATED_CORPORA"),
    ("kanripo", "gdrive:龍族古籍源庫｜Dragon Source Corpus/OPEN_KANRIPO_SELECTED"),
    ("wikisource", "gdrive:龍族古籍源庫｜Dragon Source Corpus/OPEN_WIKISOURCE_CORPUS"),
]


def run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, capture_output=True, check=check)


def cat(remote: str) -> str | None:
    p = run(["rclone", "cat", remote], check=False)
    return p.stdout if p.returncode == 0 else None


def lsjson(remote: str) -> list[dict]:
    p = run(["rclone", "lsjson", "-R", "--files-only", remote])
    return json.loads(p.stdout)


def sha_from_sidecar(text: str | None, filename: str) -> str | None:
    if not text:
        return None
    for line in text.splitlines():
        parts = line.strip().split()
        if len(parts) >= 2 and (parts[-1].lstrip("*") == filename or len(text.splitlines()) == 1):
            token = parts[0].lower()
            if len(token) == 64 and all(c in "0123456789abcdef" for c in token):
                return token
    return None


def parse_time(value: str | None) -> float:
    if not value:
        return 0.0
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


def curated_item(root: str, obj: dict, manifest_cache: dict[str, dict]) -> dict | None:
    rel = obj["Path"]
    if "/parquet/" not in rel or not rel.endswith(".parquet"):
        return None
    if rel.startswith("openiti/") and "/normalized/v1/parquet/" in rel:
        prefix = rel.split("/parquet/", 1)[0]
        manifest_remote = f"{root}/{prefix}/MANIFEST.json"
        if manifest_remote not in manifest_cache:
            raw = cat(manifest_remote)
            if not raw:
                return None
            try:
                manifest_cache[manifest_remote] = json.loads(raw)
            except Exception:
                return None
        name = Path(rel).name
        part = next((x for x in manifest_cache[manifest_remote].get("parts", []) if x.get("file") == name), None)
        if not part or not part.get("sha256"):
            return None
        return {
            "group": "openiti", "corpus": "openiti", "logical_key": f"openiti:{name}",
            "remote": f"{root}/{rel}", "path": rel, "bytes": int(obj.get("Size") or part.get("bytes") or 0),
            "modtime": obj.get("ModTime"), "sha256": part["sha256"],
        }

    source_id = rel.split("/", 1)[0]
    base = rel.split("/parquet/", 1)[0]
    side = cat(f"{root}/{base}/meta/PARQUET.sha256")
    sha = sha_from_sidecar(side, Path(rel).name)
    if not sha:
        return None
    return {
        "group": "curated", "corpus": source_id, "logical_key": f"curated:{source_id}",
        "remote": f"{root}/{rel}", "path": rel, "bytes": int(obj.get("Size") or 0),
        "modtime": obj.get("ModTime"), "sha256": sha,
    }


def kanripo_item(root: str, obj: dict) -> dict | None:
    rel = obj["Path"]
    if "/parquet/" not in rel or not rel.endswith(".parquet"):
        return None
    parts = rel.split("/")
    if len(parts) < 5:
        return None
    category, partition = parts[0], parts[1]
    base = rel.split("/parquet/", 1)[0]
    sha = sha_from_sidecar(cat(f"{root}/{base}/meta/PARQUET.sha256"), Path(rel).name)
    if not sha:
        return None
    return {
        "group": "kanripo", "corpus": f"kanripo-{category}",
        "logical_key": f"kanripo:{category}:{partition}",
        "remote": f"{root}/{rel}", "path": rel, "bytes": int(obj.get("Size") or 0),
        "modtime": obj.get("ModTime"), "sha256": sha,
    }


def wikisource_item(root: str, obj: dict) -> dict | None:
    rel = obj["Path"]
    if "/parquet/" not in rel or not rel.endswith(".parquet"):
        return None
    parts = rel.split("/")
    if len(parts) < 4:
        return None
    wiki, date = parts[0], parts[1]
    name = Path(rel).name
    sha = sha_from_sidecar(cat(f"{root}/{rel}.sha256"), name)
    if not sha:
        return None
    return {
        "group": "wikisource", "corpus": wiki,
        "logical_key": f"wikisource:{wiki}:{date}:{name}",
        "remote": f"{root}/{rel}", "path": rel, "bytes": int(obj.get("Size") or 0),
        "modtime": obj.get("ModTime"), "sha256": sha,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", required=True)
    args = ap.parse_args()
    candidates: list[dict] = []
    manifest_cache: dict[str, dict] = {}

    for kind, root in ROOTS:
        for obj in lsjson(root):
            if obj.get("IsDir"):
                continue
            if kind == "curated":
                item = curated_item(root, obj, manifest_cache)
            elif kind == "kanripo":
                item = kanripo_item(root, obj)
            else:
                item = wikisource_item(root, obj)
            if item:
                candidates.append(item)

    # Immutable snapshots can coexist. Keep only the newest snapshot for a logical corpus/partition.
    chosen: dict[str, dict] = {}
    for item in candidates:
        key = item["logical_key"]
        prev = chosen.get(key)
        if prev is None or parse_time(item.get("modtime")) > parse_time(prev.get("modtime")):
            chosen[key] = item

    items = sorted(chosen.values(), key=lambda x: (x["group"], x["corpus"], x["logical_key"], x["remote"]))
    identity_payload = json.dumps(
        [{k: x[k] for k in ("group", "corpus", "logical_key", "remote", "bytes", "sha256")} for x in items],
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    manifest = {
        "format": "osr-ancient-feature-source-inventory/v1",
        "inventory_sha256": hashlib.sha256(identity_payload).hexdigest(),
        "items": items,
        "item_count": len(items),
        "groups": {g: sum(1 for x in items if x["group"] == g) for g in sorted({x["group"] for x in items})},
        "identity_contract": "exact upstream parquet SHA256 + immutable remote path; newest snapshot per logical corpus/partition",
    }
    Path(args.output).write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({"item_count": manifest["item_count"], "groups": manifest["groups"], "inventory_sha256": manifest["inventory_sha256"]}, ensure_ascii=False))
    return 0 if items else 3


if __name__ == "__main__":
    raise SystemExit(main())
