#!/usr/bin/env python3
import argparse
import json
import pathlib
import sys


def fail(msg: str) -> None:
    print(json.dumps({"status": "DRY_RUN_FAILED", "error": msg}, ensure_ascii=False))
    raise SystemExit(2)


def main() -> None:
    ap = argparse.ArgumentParser(description="Cheap/no-network preflight for OSR research requests.")
    ap.add_argument("--request", required=True)
    ap.add_argument("--allow-existing-run", action="store_true")
    args = ap.parse_args()

    p = pathlib.Path(args.request)
    if not p.exists():
        fail(f"request not found: {p}")
    try:
        req = json.loads(p.read_text("utf-8"))
    except Exception as e:
        fail(f"invalid JSON: {e}")
    if not isinstance(req, dict):
        fail("request must be a JSON object")

    run_id = req.get("run_id")
    if not isinstance(run_id, str) or not run_id.strip():
        fail("run_id is required")
    if any(x in run_id for x in ("/", "\\", "..")):
        fail("run_id must be path-safe")

    terms = req.get("terms")
    if terms is not None:
        if not isinstance(terms, list) or not terms or not all(isinstance(x, str) and x.strip() for x in terms):
            fail("terms must be a non-empty list of non-empty strings")
        if len(set(terms)) != len(terms):
            fail("terms must be unique")

    numeric_bounds = {
        "top_n_shards": (1, 100),
        "max_rows_per_shard": (1, 500),
        "context_chars": (40, 4000),
        "min_local_terms": (1, len(terms) if terms else 100),
    }
    for key, (lo, hi) in numeric_bounds.items():
        if key in req:
            try:
                v = int(req[key])
            except Exception:
                fail(f"{key} must be an integer")
            if not (lo <= v <= hi):
                fail(f"{key} out of bounds: {v}, expected {lo}..{hi}")

    router_path = req.get("router_result")
    router_run_id = None
    if router_path:
        rp = pathlib.Path(router_path)
        if not rp.exists():
            fail(f"router result not found: {rp}")
        try:
            router = json.loads(rp.read_text("utf-8"))
        except Exception as e:
            fail(f"invalid router JSON: {e}")
        router_run_id = router.get("run_id")
        expected = req.get("expected_router_run_id")
        if expected and router_run_id != expected:
            fail(f"router run mismatch: expected {expected}, got {router_run_id}")
        ranked = router.get("ranked_shards")
        if not isinstance(ranked, list) or not ranked:
            fail("router result has no ranked_shards")
        top_n = int(req.get("top_n_shards", 12))
        if top_n > len(ranked):
            fail(f"top_n_shards={top_n} exceeds ranked_shards={len(ranked)}")
        required = {"source", "repo", "file"}
        for i, row in enumerate(ranked[:top_n]):
            if not isinstance(row, dict) or not required.issubset(row):
                fail(f"ranked_shards[{i}] missing one of {sorted(required)}")

    archive = pathlib.Path("control/research_runs") / run_id
    existing = archive.exists() and any(archive.iterdir())
    if existing and not args.allow_existing_run:
        fail(f"run archive already exists: {archive}; bump run_id or pass --allow-existing-run")

    report = {
        "status": "DRY_RUN_PASS",
        "network_used": False,
        "writes_performed": False,
        "request": str(p),
        "run_id": run_id,
        "router_run_id": router_run_id,
        "term_count": len(terms or []),
        "top_n_shards": int(req.get("top_n_shards", 0) or 0),
        "archive_target": str(archive),
        "archive_already_exists": existing,
        "next": "REAL_RUN_ALLOWED",
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
