#!/usr/bin/env python3
"""Audit the Round-05 v5 Later Liang succession/dyad graph.

Checks:
- Source grounding: every event/edge/slice evidence is a literal substring of the
  fixture text it cites; every person name occurs in at least one linked source.
- Required/optional person coverage (Later Liang core + new exact actors).
- Cross-regime chain from 吕光 to 刘裕 through 苻坚/姚苌/姚兴/姚泓 remains intact.
- Lv Guang <-> Fu Jian bridge remains intact.
- Western expedition exact-actor edges remain intact.
- New v5 depth edges are present and grounded:
    * 吕纂 brother_of 吕绍
    * 吕光 brother_of 吕宝; 吕宝 father_of 吕隆
    * 吕纂 commands 吕超; 吕超 subordinate_to 吕纂
    * 吕隆 appoints 吕超; 吕隆 commands 吕超
    * 魏益多 kills 吕纂
    * 吕隆 father_of 吕弼; 姚兴 kills 吕弼
    * 姚兴 commands 姚硕德; 姚硕德 enemy_of 吕隆
- Relation-type whitelist; no OPEN or unsupported edges.
- No target-person fracture for 吕光.
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
    "吕宝", "魏益多", "吕弼", "姚硕德",
}
OPTIONAL_PEOPLE = {
    "苻坚", "姚兴", "姚泓", "刘裕", "姜飞", "彭晃", "杜进", "康盛",
    "董方", "郭抱", "贾虔", "杨颖", "王镇恶", "檀道济", "吴忠", "姚苌",
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
        names = {n["name"]} | set(n.get("aliases") or [])
        ok = bool(linked_sids) and any(
            any(name in text_by_source_id.get(sid, "") for name in names)
            for sid in linked_sids
        )
        checks.append(ok)
        if not ok:
            failures.append({"table": "persons", "id": n["id"], "name": n["name"], "aliases": list(names), "linked_sources": sorted(linked_sids)})

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

    def has_edge(src_name: str, tgt_name: str, rel: str) -> dict | None:
        src_id = next((int(n["id"]) for n in graph["nodes"] if n["name"] == src_name), None)
        tgt_id = next((int(n["id"]) for n in graph["nodes"] if n["name"] == tgt_name), None)
        if src_id is None or tgt_id is None:
            return None
        for e in graph["edges"]:
            if int(e["source"]) == src_id and int(e["target"]) == tgt_id and e["relation_type"] == rel:
                return edge_summary(e)
        return None

    # Target-person unity: there must be exactly one 吕光 node.
    lv_guang_nodes = [n for n in graph["nodes"] if n["name"] == "吕光"]
    target_unity_ok = len(lv_guang_nodes) == 1

    # Later Liang succession/dyad depth checks
    depth_checks = {
        "吕纂 brother_of 吕绍": has_edge("吕纂", "吕绍", "brother_of"),
        "吕光 brother_of 吕宝": has_edge("吕光", "吕宝", "brother_of"),
        "吕宝 father_of 吕隆": has_edge("吕宝", "吕隆", "father_of"),
        "吕纂 commands 吕超": has_edge("吕纂", "吕超", "commands"),
        "吕超 subordinate_to 吕纂": has_edge("吕超", "吕纂", "subordinate_to"),
        "吕隆 appoints 吕超": has_edge("吕隆", "吕超", "appoints"),
        "吕隆 commands 吕超": has_edge("吕隆", "吕超", "commands"),
        "魏益多 kills 吕纂": has_edge("魏益多", "吕纂", "kills"),
        "吕隆 father_of 吕弼": has_edge("吕隆", "吕弼", "father_of"),
        "姚兴 kills 吕弼": has_edge("姚兴", "吕弼", "kills"),
        "姚兴 commands 姚硕德": has_edge("姚兴", "姚硕德", "commands"),
        "姚硕德 enemy_of 吕隆": has_edge("姚硕德", "吕隆", "enemy_of"),
    }
    missing_depth_edges = sorted(label for label, e in depth_checks.items() if e is None)

    # Cross-regime chain checks (preserved from v4)
    chain_people = ["吕光", "苻坚", "姚苌", "姚兴", "姚泓", "刘裕"]
    chain_node_ids = {name: next((int(n["id"]) for n in graph["nodes"] if n["name"] == name), None) for name in chain_people}
    missing_chain_nodes = sorted(name for name, nid in chain_node_ids.items() if nid is None)

    chain_checks = {
        "吕光 subordinate_to 苻坚": has_edge("吕光", "苻坚", "subordinate_to"),
        "苻坚 executed_by 姚苌": has_edge("苻坚", "姚苌", "executed_by"),
        "姚苌 father_of 姚兴": has_edge("姚苌", "姚兴", "father_of"),
        "姚兴 succeeds 姚苌": has_edge("姚兴", "姚苌", "succeeds"),
        "姚兴 father_of 姚泓": has_edge("姚兴", "姚泓", "father_of"),
        "姚泓 succeeds 姚兴": has_edge("姚泓", "姚兴", "succeeds"),
        "刘裕 enemy_of 姚泓": has_edge("刘裕", "姚泓", "enemy_of"),
        "姚泓 executed_by 刘裕": has_edge("姚泓", "刘裕", "executed_by"),
    }
    missing_chain_edges = sorted(label for label, e in chain_checks.items() if e is None)

    # Lv Guang <-> Fu Jian bridge checks
    bridge_checks = {
        "苻坚 appoints 吕光": has_edge("苻坚", "吕光", "appoints"),
        "吕光 subordinate_to 苻坚": has_edge("吕光", "苻坚", "subordinate_to"),
        "苻坚 supports 吕光": has_edge("苻坚", "吕光", "supports"),
    }
    missing_bridge_edges = sorted(label for label, e in bridge_checks.items() if e is None)

    # Western expedition exact-actor edges
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
    if missing_depth_edges:
        status = "FAIL"
    if missing_chain_nodes or missing_chain_edges:
        status = "FAIL"
    if missing_bridge_edges:
        status = "FAIL"
    if unsupported_relations:
        status = "FAIL"
    if open_edges:
        status = "FAIL"
    if not target_unity_ok:
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
        "target_person_unity": {
            "吕光_node_count": len(lv_guang_nodes),
            "ok": target_unity_ok,
        },
        "later_liang_depth": {
            "edges": depth_checks,
            "missing_edges": missing_depth_edges,
        },
        "bridge": {
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
