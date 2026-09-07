#!/usr/bin/env python3
"""Audit a historical-person SQLite/graph build for grounding and gold-20 semantics."""
from __future__ import annotations

import argparse
import json
import sqlite3
from collections import defaultdict
from pathlib import Path


def _source_map(db: sqlite3.Connection):
    out = {}
    for r in db.execute("SELECT id,text,provenance_json,row_sha256 FROM sources"):
        out[int(r[0])] = {
            "text": r[1],
            "provenance": json.loads(r[2]),
            "row_sha256": r[3],
        }
    return out


def grounding_audit(db_path: Path) -> dict:
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    try:
        sources = _source_map(db)
        checks = []
        bad = []
        for table in ("events", "relations", "slices"):
            for r in db.execute(f"SELECT id,source_id,evidence FROM {table}"):
                evidence = (r["evidence"] or "").strip()
                text = sources[int(r["source_id"])]["text"]
                ok = bool(evidence) and evidence in text
                checks.append(ok)
                if not ok:
                    bad.append({"table": table, "id": r["id"], "source_id": r["source_id"], "evidence": evidence})

        # Person names must occur in at least one source to which that person is linked.
        for p in db.execute("SELECT id,canonical_name FROM persons"):
            linked = set()
            for row in db.execute(
                "SELECT e.source_id FROM events e JOIN event_persons ep ON ep.event_id=e.id WHERE ep.person_id=?",
                (p["id"],),
            ):
                linked.add(int(row[0]))
            for row in db.execute(
                "SELECT source_id FROM relations WHERE source_person_id=? OR target_person_id=?",
                (p["id"], p["id"]),
            ):
                linked.add(int(row[0]))
            for row in db.execute("SELECT source_id FROM slices WHERE person_id=?", (p["id"],)):
                linked.add(int(row[0]))
            ok = bool(linked) and any(p["canonical_name"] in sources[sid]["text"] for sid in linked)
            checks.append(ok)
            if not ok:
                bad.append({"table": "persons", "id": p["id"], "name": p["canonical_name"], "linked_sources": sorted(linked)})

        return {
            "status": "PASS" if all(checks) else "FAIL",
            "grounded_evidence": (sum(checks) / len(checks)) if checks else 1.0,
            "checks": len(checks),
            "failures": bad,
            "sources": len(sources),
        }
    finally:
        db.close()


def semantic_eval(graph_path: Path, expectations_path: Path) -> dict:
    graph = json.loads(graph_path.read_text("utf-8"))
    exp = json.loads(expectations_path.read_text("utf-8"))
    expected = exp["records"]

    sid_to_rid = {}
    source_prov = {}
    for s in graph["sources"]:
        rid = (s.get("provenance") or {}).get("id")
        if rid:
            sid_to_rid[int(s["id"])] = rid
            source_prov[rid] = s.get("provenance") or {}

    events = defaultdict(list)
    slices = defaultdict(list)
    relations = defaultdict(list)
    for x in graph["events"]:
        rid = sid_to_rid.get(int(x["source_id"]))
        if rid:
            events[rid].append(x)
    for x in graph["slices"]:
        rid = sid_to_rid.get(int(x["source_id"]))
        if rid:
            slices[rid].append(x)
    for x in graph["edges"]:
        rid = sid_to_rid.get(int(x["source_id"]))
        if rid:
            relations[rid].append(x)

    record_ids = set(expected)
    source_cov = sum(r in source_prov for r in record_ids) / len(record_ids)
    event_cov = sum(bool(events[r]) for r in record_ids) / len(record_ids)
    slice_cov = sum(bool(slices[r]) for r in record_ids) / len(record_ids)

    slice_match_n = event_match_n = 0
    relation_required = relation_match_n = 0
    variant_required = variant_ok = 0
    detail = {}
    for rid, rule in expected.items():
        got_slice = {x["slice_type"] for x in slices[rid]}
        got_event = {x["event_type"] for x in events[rid]}
        got_rel = {x["relation_type"] for x in relations[rid]}
        sm = bool(got_slice.intersection(rule.get("slice_any", [])))
        em = bool(got_event.intersection(rule.get("event_any", [])))
        slice_match_n += int(sm)
        event_match_n += int(em)
        rm = None
        if rule.get("relation_any"):
            relation_required += 1
            rm = bool(got_rel.intersection(rule["relation_any"]))
            relation_match_n += int(rm)
        vm = None
        if rule.get("must_preserve_variant_group"):
            variant_required += 1
            vm = bool(source_prov.get(rid, {}).get("variant_group"))
            variant_ok += int(vm)
        detail[rid] = {
            "slice_match": sm, "event_match": em, "relation_match": rm, "variant_preserved": vm,
            "got_slices": sorted(got_slice), "got_events": sorted(got_event), "got_relations": sorted(got_rel),
        }

    target = exp.get("target_person")
    target_nodes = [n for n in graph["nodes"] if n.get("name") == target]
    target_count = len(target_nodes)
    metrics = {
        "source_coverage": source_cov,
        "event_coverage": event_cov,
        "slice_coverage": slice_cov,
        "slice_match": slice_match_n / len(record_ids),
        "event_match": event_match_n / len(record_ids),
        "relation_match": relation_match_n / relation_required if relation_required else 1.0,
        "provenance_variant_preservation": variant_ok / variant_required if variant_required else 1.0,
        "target_person_present": target_count > 0,
        "target_person_node_count": target_count,
        "target_person_unity": 1.0 if target_count == 1 else (1.0 / target_count if target_count else 0.0),
    }
    return {"metrics": metrics, "detail": detail, "thresholds": exp.get("strict_thresholds", {})}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--graph-json", required=True)
    ap.add_argument("--expectations", default="historical-person-graph/fixtures/lvguang_gold_20_expectations.json")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()

    grounding = grounding_audit(Path(args.db))
    semantic = semantic_eval(Path(args.graph_json), Path(args.expectations))
    semantic["metrics"]["grounded_evidence"] = grounding["grounded_evidence"]
    result = {"grounding": grounding, "semantic": semantic}

    failures = []
    if grounding["status"] != "PASS":
        failures.append("grounding")
    if not semantic["metrics"]["target_person_present"]:
        failures.append("target_person_present")
    if args.strict:
        for k, threshold in semantic["thresholds"].items():
            if semantic["metrics"].get(k, 0) < threshold:
                failures.append(f"{k}<{threshold}")

    result["status"] = "PASS" if not failures else "FAIL"
    result["failures"] = failures
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
