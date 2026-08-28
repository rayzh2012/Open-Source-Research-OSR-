#!/usr/bin/env python3
"""Audit the v3 Fu Jian -> Yao Chang -> Yao Xing -> Yao Hong -> Liu Yu chain graph.

Checks:
- v1/v2 grounding invariants (all evidence/slices/events traceable to fixture text)
- v1/v2 required/optional person coverage
- v3 chain coverage: 苻坚、姚苌、姚兴、姚泓、刘裕 present and linked by the expected
  edges (service/appointment, rupture/rebellion, father_of, succeeds, enemy_of,
  captured_by, executed_by)
- relation-type whitelist
- no unsupported or OPEN edges
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

PREFERRED_RELATIONS = {
    "father_of", "son_of", "brother_of", "succeeds", "predecessor_of",
    "kills", "executed_by", "rebels_against", "subordinate_to", "supports",
    "enemy_of", "sends_envoy_to", "captured_by", "deposed_by", "ruler_of",
    "appoints", "uncle_of", "commands", "other",
}

REQUIRED_PEOPLE = {
    "吕光", "吕绍", "吕纂", "吕弘", "吕隆", "吕超", "沮渠蒙逊", "沮渠罗仇",
    "姚泓", "刘裕",
}
OPTIONAL_PEOPLE = {"苻坚", "姚兴", "王镇恶", "檀道济"}

CHAIN_PEOPLE = {"苻坚", "姚苌", "姚兴", "姚泓", "刘裕"}


def load_graph(path: Path) -> dict:
    return json.loads(path.read_text("utf-8"))


def load_fixture_texts(paths: list[Path]) -> dict[str, str]:
    texts: dict[str, str] = {}
    for path in paths:
        with path.open("rt", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                rec = json.loads(line)
                texts[rec["id"]] = rec["text"]
    return texts


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--graph-json", required=True)
    ap.add_argument("--fixtures", nargs="+", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    graph = load_graph(Path(args.graph_json))
    fixture_texts = load_fixture_texts([Path(p) for p in args.fixtures])

    text_by_source_id: dict[int, str] = {}
    for s in graph["sources"]:
        rid = (s.get("provenance") or {}).get("id")
        if rid:
            text_by_source_id[int(s["id"])] = fixture_texts.get(rid, "")

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

    # Person-name grounding
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

    nodes_by_id = {int(n["id"]): n for n in graph["nodes"]}
    node_names = {n["name"] for n in graph["nodes"]}
    missing_required = sorted(REQUIRED_PEOPLE - node_names)
    present_optional = sorted(OPTIONAL_PEOPLE & node_names)
    absent_optional = sorted(OPTIONAL_PEOPLE - node_names)

    relation_counts = Counter(e["relation_type"] for e in graph["edges"])
    unsupported_relations = [e for e in graph["edges"] if e["relation_type"] not in PREFERRED_RELATIONS]
    open_edges = [e for e in graph["edges"] if e.get("certainty") == "OPEN"]

    def edge_summary(e: dict) -> dict:
        return {
            "source": nodes_by_id[int(e["source"])]["name"],
            "target": nodes_by_id[int(e["target"])]["name"],
            "relation": e["relation_type"],
            "evidence": e["evidence"],
        }

    # v1/v2 bridge edges audit
    bridge_people = {"姚泓", "刘裕", "王镇恶", "檀道济"}
    bridge_edges = [
        edge_summary(e) for e in graph["edges"]
        if nodes_by_id[int(e["source"])]["name"] in bridge_people
        or nodes_by_id[int(e["target"])]["name"] in bridge_people
    ]

    # v3 chain audit
    chain_nodes = {name: next((int(n["id"]) for n in graph["nodes"] if n["name"] == name), None) for name in CHAIN_PEOPLE}
    missing_chain = sorted(name for name, nid in chain_nodes.items() if nid is None)

    def has_edge(src_name: str, tgt_name: str, rel: str) -> dict | None:
        src_id = chain_nodes.get(src_name)
        tgt_id = chain_nodes.get(tgt_name)
        # Allow targets that are not core chain people (e.g. 吴忠, 王镇恶).
        if tgt_id is None:
            tgt_id = next((int(n["id"]) for n in graph["nodes"] if n["name"] == tgt_name), None)
        if src_id is None or tgt_id is None:
            return None
        for e in graph["edges"]:
            if int(e["source"]) == src_id and int(e["target"]) == tgt_id and e["relation_type"] == rel:
                return edge_summary(e)
        return None

    chain_checks = {
        "苻坚 appoints 姚苌": has_edge("苻坚", "姚苌", "appoints"),
        "姚苌 subordinate_to 苻坚": has_edge("姚苌", "苻坚", "subordinate_to"),
        "姚苌 rebels_against 苻坚": has_edge("姚苌", "苻坚", "rebels_against"),
        "姚苌 enemy_of 苻坚": has_edge("姚苌", "苻坚", "enemy_of"),
        "苻坚 captured_by 吴忠": has_edge("苻坚", "吴忠", "captured_by"),
        "苻坚 executed_by 姚苌": has_edge("苻坚", "姚苌", "executed_by"),
        "姚苌 father_of 姚兴": has_edge("姚苌", "姚兴", "father_of"),
        "姚兴 succeeds 姚苌": has_edge("姚兴", "姚苌", "succeeds"),
        "姚兴 father_of 姚泓": has_edge("姚兴", "姚泓", "father_of"),
        "姚泓 succeeds 姚兴": has_edge("姚泓", "姚兴", "succeeds"),
        "刘裕 enemy_of 姚泓": has_edge("刘裕", "姚泓", "enemy_of"),
        "姚泓 captured_by 王镇恶": has_edge("姚泓", "王镇恶", "captured_by"),
        "姚泓 executed_by 刘裕": has_edge("姚泓", "刘裕", "executed_by"),
    }
    missing_chain_edges = sorted(label for label, e in chain_checks.items() if e is None)

    status = "PASS"
    if not all(checks):
        status = "FAIL"
    if missing_required:
        status = "FAIL"
    if missing_chain:
        status = "FAIL"
    if missing_chain_edges:
        status = "FAIL"

    result = {
        "status": status,
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
            "chain_people_present": sorted(CHAIN_PEOPLE & node_names),
            "chain_people_missing": missing_chain,
        },
        "relation_counts": dict(relation_counts.most_common()),
        "bridge_edges": bridge_edges,
        "chain_edges": chain_checks,
        "missing_chain_edges": missing_chain_edges,
        "unsupported_relations": [edge_summary(e) for e in unsupported_relations],
        "open_relations": [edge_summary(e) for e in open_edges],
    }

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({"status": status, "output": str(out)}, ensure_ascii=False))
    return 0 if status == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
