#!/usr/bin/env python3
import argparse
import json
import os
import pathlib
import re


def fail(msg: str) -> None:
    print(json.dumps({"status": "DRY_RUN_FAILED", "error": msg}, ensure_ascii=False))
    raise SystemExit(2)


def cost_guard(workflow_path: str | None) -> dict:
    """Fail closed before any corpus network access if a run could become billable."""
    token_names = (
        "HF_TOKEN",
        "HUGGING_FACE_HUB_TOKEN",
        "HUGGINGFACE_TOKEN",
        "HF_HUB_TOKEN",
    )
    present_tokens = [name for name in token_names if os.environ.get(name)]
    if present_tokens:
        fail(f"cost guard: authenticated Hugging Face token present: {present_tokens}")

    repo_visibility = None
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if event_path and pathlib.Path(event_path).exists():
        try:
            event = json.loads(pathlib.Path(event_path).read_text("utf-8"))
            repo = event.get("repository") or {}
            private = repo.get("private")
            visibility = repo.get("visibility")
            repo_visibility = visibility or ("private" if private else "public" if private is False else None)
            if private is True or visibility == "private":
                fail("cost guard: repository is private; standard hosted-runner minutes may be billable")
        except SystemExit:
            raise
        except Exception as e:
            fail(f"cost guard: cannot validate GitHub repository visibility: {e}")

    workflow_runner = None
    if workflow_path:
        wp = pathlib.Path(workflow_path)
        if not wp.exists():
            fail(f"cost guard: workflow not found: {wp}")
        text = wp.read_text("utf-8")
        runners = [x.strip(" '\"") for x in re.findall(r"^\s*runs-on:\s*([^#\n]+)", text, flags=re.M)]
        allowed = {"ubuntu-latest", "ubuntu-24.04", "ubuntu-22.04", "ubuntu-slim"}
        if not runners:
            fail("cost guard: workflow has no statically verifiable runs-on label")
        bad = [r for r in runners if r not in allowed]
        if bad:
            fail(f"cost guard: non-standard or unapproved runner label(s): {bad}")
        workflow_runner = sorted(set(runners))
        forbidden_markers = (
            "secrets.HF_TOKEN",
            "secrets.HUGGING_FACE_HUB_TOKEN",
            "secrets.HUGGINGFACE_TOKEN",
            "secrets.HF_HUB_TOKEN",
        )
        found = [m for m in forbidden_markers if m in text]
        if found:
            fail(f"cost guard: workflow wires authenticated HF credentials: {found}")

    return {
        "repo_visibility": repo_visibility,
        "workflow_runner": workflow_runner,
        "hf_authentication": "anonymous_public_download_only",
        "paid_compute_allowed": False,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Cheap/no-network preflight for OSR research requests.")
    ap.add_argument("--request", required=True)
    ap.add_argument("--workflow")
    ap.add_argument("--allow-existing-run", action="store_true")
    args = ap.parse_args()

    cost = cost_guard(args.workflow)

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

    required = req.get("required_any_terms")
    if required is not None:
        if not isinstance(required, list) or not required or not all(isinstance(x, str) and x.strip() for x in required):
            fail("required_any_terms must be a non-empty list of non-empty strings")
        if len(set(required)) != len(required):
            fail("required_any_terms must be unique")
        if not terms or any(x not in terms for x in required):
            fail("required_any_terms must be a subset of terms")

    numeric_bounds = {
        "top_n_shards": (1, 100),
        "max_rows_per_shard": (1, 500),
        "context_chars": (40, 4000),
        "min_local_terms": (1, len(terms) if terms else 100),
        "document_head_chars": (0, 10000),
        "max_occurrences_per_term": (1, 100),
    }
    for key, (lo, hi) in numeric_bounds.items():
        if key in req:
            try:
                v = int(req[key])
            except Exception:
                fail(f"{key} must be an integer")
            if not (lo <= v <= hi):
                fail(f"{key} out of bounds: {v}, expected {lo}..{hi}")

    profile = None
    profile_id = None
    profile_path = req.get("research_profile")
    if profile_path:
        pp = pathlib.Path(profile_path)
        if not pp.exists():
            fail(f"research profile not found: {pp}")
        try:
            profile = json.loads(pp.read_text("utf-8"))
        except Exception as e:
            fail(f"invalid research profile JSON: {e}")
        profile_id = profile.get("profile_id")
        budget = profile.get("budget") or {}
        default_top_n = int(budget.get("hard_default_top_n_shards", budget.get("initial_top_n_shards", 4)))
        top_n = int(req.get("top_n_shards", default_top_n))
        if top_n > default_top_n:
            justification = req.get("scale_justification")
            if not isinstance(justification, dict) or not justification:
                fail(f"research profile budget gate: top_n_shards={top_n} exceeds default={default_top_n}; scale_justification from a prior yield measurement is required")
            prior_rows = int(justification.get("prior_rows_with_source_cue", 0) or 0)
            prior_titles = int(justification.get("prior_unique_source_titles", 0) or 0)
            if top_n <= 8:
                gate = budget.get("expand_to_8_only_if") or {}
            else:
                gate = budget.get("expand_to_12_only_if") or {}
            min_rows = int(gate.get("minimum_rows_with_source_cue", 0) or 0)
            min_titles = int(gate.get("minimum_unique_source_titles", 0) or 0)
            if prior_rows < min_rows or prior_titles < min_titles:
                fail(f"research profile scale gate not met: rows {prior_rows}/{min_rows}, unique titles {prior_titles}/{min_titles}")

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
        required_fields = {"source", "repo", "file"}
        for i, row in enumerate(ranked[:top_n]):
            if not isinstance(row, dict) or not required_fields.issubset(row):
                fail(f"ranked_shards[{i}] missing one of {sorted(required_fields)}")

    archive = pathlib.Path("control/research_runs") / run_id
    existing = archive.exists() and any(archive.iterdir())
    if existing and not args.allow_existing_run:
        fail(f"run archive already exists: {archive}; bump run_id or pass --allow-existing-run")

    report = {
        "status": "DRY_RUN_PASS",
        "network_used": False,
        "writes_performed": False,
        "cost_guard": cost,
        "request": str(p),
        "run_id": run_id,
        "router_run_id": router_run_id,
        "research_profile_id": profile_id,
        "term_count": len(terms or []),
        "required_any_term_count": len(required or []),
        "top_n_shards": int(req.get("top_n_shards", 0) or 0),
        "archive_target": str(archive),
        "archive_already_exists": existing,
        "next": "REAL_RUN_ALLOWED",
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
