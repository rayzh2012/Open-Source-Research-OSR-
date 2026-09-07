#!/usr/bin/env python3
"""Audit the Round-04 v4 Lv Guang <-> Fu Jian unification graph.

Checks:
- Source grounding: every event/edge/slice evidence is a literal substring of the
  fixture text it cites; every person name occurs in at least one linked source.
- Required/optional person coverage.
- Lv Guang <-> Fu Jian bridge: at least one directly grounded appoints/subordinate_to
  edge and one supports/trust edge between 吕光 and 苻坚.
- Full chain connectivity: a path exists from 吕光 to 刘裕 through 苻坚/姚苌/姚兴/姚泓.
- Relation-type whitelist; no OPEN or unsupported edges.
- No inferred loyalty/rebellion beyond text (relation types are restricted to
  those directly supported by source substrings).
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
    "吕光", "苻坚", "姚苌", "姚兴", "姚泓", "刘裕",
}
OPTIONAL_PEOPLE = {
    "吕绍", "吕纂", "吕弘", "吕隆", "吕超", "沮渠蒙逊", "沮渠罗仇",
    "王镇恶", "檀道济", "吴忠",
}


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

    # Lv Guang <-> Fu Jian bridge audit
    bridge_required = {"吕光", "苻坚"}
    bridge_node_ids = {name: next((int(n["id"]) for n in graph["nodes"] if n["name"] == name), None) for name in bridge_required}
    missing_bridge_nodes = sorted(name for name, nid in bridge_node_ids.items() if nid is None)

    def has_bridge_edge(src_name: str, tgt_name: str, rel: str) -> dict | None:
        src_id = bridge_node_ids.get(src_name)
        tgt_id = bridge_node_ids.get(tgt_name)
        if src_id is None or tgt_id is None:
            return None
        for e in graph["edges"]:
            if int(e["source"]) == src_id and int(e["target"]) == tgt_id and e["relation_type"] == rel:
                return edge_summary(e)
        return None

    bridge_checks = {
        "苻坚 appoints 吕光": has_bridge_edge("苻坚", "吕光", "appoints"),
        "吕光 subordinate_to 苻坚": has_bridge_edge("吕光", "苻坚", "subordinate_to"),
        "苻坚 supports 吕光": has_bridge_edge("苻坚", "吕光", "supports"),
    }
    missing_bridge_edges = sorted(label for label, e in bridge_checks.items() if e is None)

    # Full chain connectivity audit (Lv Guang -> Fu Jian -> Yao Chang -> Yao Xing -> Yao Hong -> Liu Yu)
    chain_people = ["吕光", "苻坚", "姚苌", "姚兴", "姚泓", "刘裕"]
    chain_node_ids = {name: next((int(n["id"]) for n in graph["nodes"] if n["name"] == name), None) for name in chain_people}
    missing_chain_nodes = sorted(name for name, nid in chain_node_ids.items() if nid is None)

    def has_chain_edge(src_name: str, tgt_name: str, rel: str) -> dict | None:
        src_id = chain_node_ids.get(src_name)
        tgt_id = chain_node_ids.get(tgt_name)
        if src_id is None or tgt_id is None:
            return None
        for e in graph["edges"]:
            if int(e["source"]) == src_id and int(e["target"]) == tgt_id and e["relation_type"] == rel:
                return edge_summary(e)
        return None

    chain_checks = {
        "吕光 subordinate_to 苻坚": has_chain_edge("吕光", "苻坚", "subordinate_to"),
        "苻坚 executed_by 姚苌": has_chain_edge("苻坚", "姚苌", "executed_by"),
        "姚苌 father_of 姚兴": has_chain_edge("姚苌", "姚兴", "father_of"),
        "姚兴 succeeds 姚苌": has_chain_edge("姚兴", "姚苌", "succeeds"),
        "姚兴 father_of 姚泓": has_chain_edge("姚兴", "姚泓", "father_of"),
        "姚泓 succeeds 姚兴": has_chain_edge("姚泓", "姚兴", "succeeds"),
        "刘裕 enemy_of 姚泓": has_chain_edge("刘裕", "姚泓", "enemy_of"),
        "姚泓 executed_by 刘裕": has_chain_edge("姚泓", "刘裕", "executed_by"),
    }
    missing_chain_edges = sorted(label for label, e in chain_checks.items() if e is None)

    # Western expedition exact-actor edges audit
    western_subordinates = {"姜飞", "彭晃", "杜进", "康盛", "董方", "郭抱", "贾虔", "杨颖"}
    western_edges = [
        edge_summary(e) for e in graph["edges"]
        if nodes_by_id[int(e["source"])]["name"] == "吕光"
        and nodes_by_id[int(e["target"])]["name"] in western_subordinates
    ]

    status = "PASS"
    if not all(checks):
        status = "FAIL"
    if missing_required:
        status = "FAIL"
    if missing_bridge_nodes:
        status = "FAIL"
    if missing_bridge_edges:
        status = "FAIL"
    if missing_chain_nodes:
        status = "FAIL"
    if missing_chain_edges:
        status = "FAIL"
    if unsupported_relations:
        status = "FAIL"
    if open_edges:
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
        },
        "relation_counts": dict(relation_counts.most_common()),
        "bridge": {
            "nodes": bridge_node_ids,
            "missing_nodes": missing_bridge_nodes,
            "edges": bridge_checks,
            "missing_edges": missing_bridge_edges,
        },
        "chain": {
            "nodes": chain_node_ids,
            "missing_nodes": missing_chain_nodes,
            "edges": chain_checks,
            "missing_edges": missing_chain_edges,
        },
        "western_expedition": {
            "subordinate_edges": western_edges,
            "subordinate_count": len(western_edges),
        },
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
