#!/usr/bin/env python3
"""Audit the Later Liang cluster graph for grounding and coverage."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

PREFERRED_RELATIONS = {
    "father_of", "son_of", "brother_of", "succeeds", "predecessor_of",
    "kills", "executed_by", "rebels_against", "subordinate_to", "supports",
    "enemy_of", "sends_envoy_to", "captured_by", "deposed_by", "ruler_of",
    "appoints", "uncle_of", "other",
}

REQUIRED_PEOPLE = {
    "吕光", "吕绍", "吕纂", "吕弘", "吕隆", "吕超", "沮渠蒙逊", "沮渠罗仇",
}
OPTIONAL_PEOPLE = {"苻坚", "姚兴", "姚泓", "刘裕"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--graph-json", required=True)
    ap.add_argument("--fixture", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    graph = json.loads(Path(args.graph_json).read_text("utf-8"))
    fixture_records = []
    with Path(args.fixture).open("rt", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                fixture_records.append(json.loads(line))

    sources_by_id = {int(s["id"]): s for s in graph["sources"]}
    nodes_by_id = {int(n["id"]): n for n in graph["nodes"]}

    # Graph sources do not carry the full text; map back to fixture text via provenance id.
    fixture_text_by_record_id = {rec["id"]: rec["text"] for rec in fixture_records}
    text_by_source_id = {}
    for s in graph["sources"]:
        rid = (s.get("provenance") or {}).get("id")
        if rid:
            text_by_source_id[int(s["id"])] = fixture_text_by_record_id.get(rid, "")

    # Grounding checks
    failures = []
    checks = []

    def check_evidence(item: dict, table: str):
        sid = int(item.get("source_id", 0))
        text = text_by_source_id.get(sid, "")
        if not text:
            failures.append({"table": table, "id": item["id"], "reason": "missing_source_text", "source_id": sid})
            checks.append(False)
            return
        evidence = (item.get("evidence") or "").strip()
        ok = bool(evidence) and evidence in text
        checks.append(ok)
        if not ok:
            failures.append({
                "table": table, "id": item["id"], "source_id": sid,
                "evidence": evidence, "source_prefix": text[:120],
            })

    for e in graph["events"]:
        check_evidence(e, "events")
    for e in graph["edges"]:
        check_evidence(e, "relations")
    for s in graph["slices"]:
        check_evidence(s, "slices")

    # Person-name grounding: each person name must occur in at least one linked source.
    for n in graph["nodes"]:
        linked_sids = set()
        for e in graph["events"]:
            if int(n["id"]) in (e.get("participants") or []):
                linked_sids.add(int(e["source_id"]))
        for e in graph["edges"]:
            if int(e["source"]) == int(n["id"]) or int(e["target"]) == int(n["id"]):
                linked_sids.add(int(e["source_id"]))
        for s in graph["slices"]:
            if int(s.get("person_id", 0)) == int(n["id"]):
                linked_sids.add(int(s["source_id"]))
        ok = bool(linked_sids) and any(n["name"] in text_by_source_id.get(sid, "") for sid in linked_sids)
        checks.append(ok)
        if not ok:
            failures.append({"table": "persons", "id": n["id"], "name": n["name"], "linked_sources": sorted(linked_sids)})

    # Counts
    node_names = {n["name"] for n in graph["nodes"]}
    missing_required = sorted(REQUIRED_PEOPLE - node_names)
    present_optional = sorted(OPTIONAL_PEOPLE & node_names)
    absent_optional = sorted(OPTIONAL_PEOPLE - node_names)

    relation_counts = Counter(e["relation_type"] for e in graph["edges"])
    unsupported_relations = [
        e for e in graph["edges"] if e["relation_type"] not in PREFERRED_RELATIONS
    ]
    open_edges = [e for e in graph["edges"] if e.get("certainty") == "OPEN"]

    # Structured edge lists
    succession_edges = [
        {
            "source": nodes_by_id[int(e["source"])]["name"],
            "target": nodes_by_id[int(e["target"])]["name"],
            "relation": e["relation_type"],
            "evidence": e["evidence"],
        }
        for e in graph["edges"] if e["relation_type"] == "succeeds"
    ]
    family_edges = [
        {
            "source": nodes_by_id[int(e["source"])]["name"],
            "target": nodes_by_id[int(e["target"])]["name"],
            "relation": e["relation_type"],
            "evidence": e["evidence"],
        }
        for e in graph["edges"] if e["relation_type"] in {"father_of", "son_of", "brother_of", "uncle_of"}
    ]
    rebellion_killing_edges = [
        {
            "source": nodes_by_id[int(e["source"])]["name"],
            "target": nodes_by_id[int(e["target"])]["name"],
            "relation": e["relation_type"],
            "evidence": e["evidence"],
        }
        for e in graph["edges"] if e["relation_type"] in {"kills", "executed_by", "rebels_against", "enemy_of"}
    ]

    # Source provenance list
    source_texts = []
    for rec in fixture_records:
        sid = None
        for s in graph["sources"]:
            prov = s.get("provenance") or {}
            if prov.get("id") == rec["id"]:
                sid = int(s["id"])
                break
        source_texts.append({
            "record_id": rec["id"],
            "graph_source_id": sid,
            "source_title": rec.get("source_title"),
            "source_locator": rec.get("source_locator"),
            "quoted_source": rec.get("quoted_source"),
            "evidence_tier": rec.get("evidence_tier"),
            "text_preview": rec["text"][:160] + "..." if len(rec["text"]) > 160 else rec["text"],
        })

    result = {
        "status": "PASS" if all(checks) and not missing_required else "FAIL",
        "grounding": {
            "grounded_evidence": sum(checks) / len(checks) if checks else 1.0,
            "checks": len(checks),
            "failures": failures,
        },
        "coverage": {
            "nodes": len(graph["nodes"]),
            "edges": len(graph["edges"]),
            "events": len(graph["events"]),
            "slices": len(graph["slices"]),
            "sources": len(graph["sources"]),
            "required_people_present": sorted(REQUIRED_PEOPLE & node_names),
            "required_people_missing": missing_required,
            "optional_people_present": present_optional,
            "optional_people_absent": absent_optional,
        },
        "relation_counts": dict(relation_counts.most_common()),
        "succession_chain": succession_edges,
        "family_edges": family_edges,
        "rebellion_killing_edges": rebellion_killing_edges,
        "unsupported_relations": [
            {
                "source": nodes_by_id[int(e["source"])]["name"],
                "target": nodes_by_id[int(e["target"])]["name"],
                "relation": e["relation_type"],
                "evidence": e["evidence"],
            }
            for e in unsupported_relations
        ],
        "open_relations": [
            {
                "source": nodes_by_id[int(e["source"])]["name"],
                "target": nodes_by_id[int(e["target"])]["name"],
                "relation": e["relation_type"],
                "evidence": e["evidence"],
            }
            for e in open_edges
        ],
        "sources_used": source_texts,
    }

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({"status": result["status"], "output": str(out)}, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
