#!/usr/bin/env python3
import json
import os
import pathlib
import sys

try:
    import requests
except Exception:
    requests = None

ROOT = pathlib.Path("control")
OUT = ROOT / "notion_writeback_latest.json"
ARCHIVE = ROOT / "research_runs"


def read_json(name):
    p = ROOT / name
    if not p.exists():
        return None
    return json.loads(p.read_text("utf-8"))


def main():
    exact = read_json("m5_exact_evidence_summary.json") or {}
    analysis = read_json("m5_evidence_analysis.json") or {}
    quality = read_json("m5_evidence_quality_audit.json") or {}
    source = read_json("m5_source_chronology_audit.json") or {}
    graph = read_json("m6_graph_prep.json") or {}

    run_id = exact.get("run_id") or analysis.get("run_id") or source.get("run_id") or "unknown"
    exact_run = exact.get("run_id")
    mismatches = []
    for label, obj in (("analysis", analysis), ("quality", quality), ("source", source)):
        other = obj.get("run_id")
        if other and exact_run and other != exact_run:
            mismatches.append({"component": label, "expected": exact_run, "got": other})
    graph_run = graph.get("source_run_id")
    if graph_run and exact_run and graph_run != exact_run:
        mismatches.append({"component": "graph", "expected": exact_run, "got": graph_run})

    local = analysis.get("local_window") or {}
    quality_gate = quality.get("quality_gate") or {}
    text = (
        f"【OSR Research Run】{run_id} | exact={exact.get('status','UNKNOWN')} | "
        f"rows={exact.get('rows_found','?')} | bytes={exact.get('bytes_downloaded','?')} | "
        f"3+local={exact.get('three_plus_local_term_rows','?')} | 4+local={exact.get('four_plus_local_term_rows','?')} | "
        f"local_pairs={len(local.get('pair_counts') or [])} | graph_edges={len(graph.get('edges') or [])} | "
        f"historical_fact_upgrade_allowed={quality_gate.get('historical_fact_upgrade_allowed', False)}"
    )

    payload = {
        "format": "osr-notion-writeback/v1",
        "run_id": run_id,
        "status": "BLOCKED_COMPONENT_MISMATCH" if mismatches else "READY",
        "component_mismatches": mismatches,
        "summary_text": text,
        "notion_target_from_env": bool(os.getenv("NOTION_PAGE_ID")),
        "direct_sync_attempted": False,
        "direct_sync_status": "NOT_ATTEMPTED",
    }

    token = os.getenv("NOTION_TOKEN")
    page_id = os.getenv("NOTION_PAGE_ID")
    if not mismatches and token and page_id:
        payload["direct_sync_attempted"] = True
        if requests is None:
            payload["direct_sync_status"] = "SKIPPED_REQUESTS_UNAVAILABLE"
        else:
            body = {
                "children": [
                    {
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {
                            "rich_text": [
                                {"type": "text", "text": {"content": text}}
                            ]
                        },
                    }
                ]
            }
            r = requests.patch(
                f"https://api.notion.com/v1/blocks/{page_id}/children",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Notion-Version": "2022-06-28",
                    "Content-Type": "application/json",
                },
                json=body,
                timeout=30,
            )
            payload["direct_sync_status"] = "PASS" if r.ok else f"HTTP_{r.status_code}"
            if not r.ok:
                payload["direct_sync_error"] = (r.text or "")[:800]
    elif mismatches:
        payload["direct_sync_status"] = "BLOCKED_COMPONENT_MISMATCH"
    else:
        payload["direct_sync_status"] = "PAYLOAD_ONLY_NO_SECRET"

    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", "utf-8")
    if run_id and run_id != "unknown":
        d = ARCHIVE / run_id
        d.mkdir(parents=True, exist_ok=True)
        (d / "notion_writeback.json").write_text(OUT.read_text("utf-8"), "utf-8")

    print(json.dumps(payload, ensure_ascii=False))
    if mismatches:
        raise SystemExit(3)
    if payload["direct_sync_attempted"] and payload["direct_sync_status"] != "PASS":
        raise SystemExit(4)


if __name__ == "__main__":
    main()
