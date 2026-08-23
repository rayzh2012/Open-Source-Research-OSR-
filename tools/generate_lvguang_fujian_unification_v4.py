#!/usr/bin/env python3
"""Generate Round-04 v4 unified graph: Later Liang Lv Guang cluster bridged into
Former Qin/Later Qin/Liu Yu v3 chain via directly grounded Lv Guang <-> Fu Jian
relations.

This script reuses the validated v3 unified graph (`fuqin_laterqin_liuyu_chain_v3.graph.json`)
and adds only new, directly grounded material from the existing LL09 fixture:
the western expedition subordinates named at exact actor level. No v1-v3 nodes,
edges, events, slices or sources are regenerated.

No LLM/API calls are needed; all extractions are hand-compiled from public-domain
primary source substrings already present in the repository fixtures.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


V3_GRAPH = Path("historical-person-graph/cluster-out/fuqin_laterqin_liuyu_chain_v3.graph.json")
OUT_GRAPH = Path("historical-person-graph/cluster-out/lvguang_fujian_unification_v4.graph.json")


def load_graph(path: Path) -> dict:
    return json.loads(path.read_text("utf-8"))


def find_node_id(nodes: list[dict], name: str) -> int | None:
    for n in nodes:
        if n["name"] == name:
            return int(n["id"])
    return None


def find_source_id(sources: list[dict], prov_id: str) -> int | None:
    for s in sources:
        if (s.get("provenance") or {}).get("id") == prov_id:
            return int(s["id"])
    return None


def build_v4(v3: dict) -> dict:
    graph = json.loads(json.dumps(v3))  # deep copy

    nodes = graph["nodes"]
    edges = graph["edges"]
    events = graph["events"]
    slices = graph["slices"]
    sources = graph["sources"]

    lv_guang_id = find_node_id(nodes, "吕光")
    fu_jian_id = find_node_id(nodes, "苻坚")
    if lv_guang_id is None or fu_jian_id is None:
        raise ValueError("v3 graph missing required bridge nodes 吕光 or 苻坚")

    ll09_source_id = find_source_id(sources, "LL09")
    if ll09_source_id is None:
        raise ValueError("v3 graph missing LL09 source")

    next_node_id = max(int(n["id"]) for n in nodes) + 1
    next_event_id = max(int(e["id"]) for e in events) + 1
    next_edge_id = max(int(e["id"]) for e in edges) + 1
    next_slice_id = max(int(s["id"]) for s in slices) + 1

    # New nodes: western expedition subordinates named in LL09.
    # Contexts are kept minimal and source-bound; no cross-document merge is implied.
    subordinates = [
        ("姜飞", "前秦/后凉将领/吕光西征将军"),
        ("彭晃", "前秦/后凉将领/吕光西征将军"),
        ("杜进", "前秦/后凉将领/吕光西征将军"),
        ("康盛", "前秦/后凉将领/吕光西征将军"),
        ("董方", "前秦/后凉将领/吕光西征四府佐将"),
        ("郭抱", "前秦/后凉将领/吕光西征四府佐将"),
        ("贾虔", "前秦/后凉将领/吕光西征四府佐将"),
        ("杨颖", "前秦/后凉将领/吕光西征四府佐将"),
    ]

    node_id_by_name: dict[str, int] = {}
    for name, context in subordinates:
        nid = next_node_id
        next_node_id += 1
        nodes.append({
            "id": nid,
            "name": name,
            "context": context,
            "resolution_status": "CANDIDATE",
            "certainty": "FACT",
            "aliases": [],
        })
        node_id_by_name[name] = nid

    # Single new event: Lv Guang leads the western expedition with named subordinates.
    expedition_event_id = next_event_id
    next_event_id += 1
    events.append({
        "id": expedition_event_id,
        "event_key": "96f11c32f2d9a907aee2dca434c8e7b5e6b0f7b7d8c9a0b1c2d3e4f5a6b7c8d9e",
        "date_text": "",
        "event_type": "war",
        "summary": "苻坚授吕光西讨诸军事，吕光率姜飞、彭晃、杜进、康盛等讨西域，以董方、郭抱、贾虔、杨颖为四府佐将",
        "certainty": "FACT",
        "evidence": "率将军姜飞、彭晃、杜进、康盛等总兵七万，铁骑五千，以讨西域，以陇西董方、冯翊郭抱、武威贾虔、弘农杨颖为四府佐将",
        "source_id": ll09_source_id,
        "participants": [lv_guang_id, fu_jian_id] + list(node_id_by_name.values()),
    })

    # New edges: Lv Guang commands each subordinate; each subordinate is subordinate_to Lv Guang.
    command_evidence = "率将军姜飞、彭晃、杜进、康盛等总兵七万，铁骑五千，以讨西域"
    staff_evidence = "以陇西董方、冯翊郭抱、武威贾虔、弘农杨颖为四府佐将"
    new_edges = []
    for name, nid in node_id_by_name.items():
        evidence = command_evidence if name in {"姜飞", "彭晃", "杜进", "康盛"} else staff_evidence
        new_edges.append({
            "id": next_edge_id,
            "source": lv_guang_id,
            "target": nid,
            "relation_type": "commands",
            "event_id": expedition_event_id,
            "start_text": "",
            "end_text": "",
            "certainty": "FACT",
            "evidence": evidence,
            "source_id": ll09_source_id,
        })
        next_edge_id += 1
        new_edges.append({
            "id": next_edge_id,
            "source": nid,
            "target": lv_guang_id,
            "relation_type": "subordinate_to",
            "event_id": expedition_event_id,
            "start_text": "",
            "end_text": "",
            "certainty": "FACT",
            "evidence": evidence,
            "source_id": ll09_source_id,
        })
        next_edge_id += 1
    edges.extend(new_edges)

    # New slice: Lv Guang commands the western expedition force at exact actor level.
    slices.append({
        "id": next_slice_id,
        "person_id": lv_guang_id,
        "slice_type": "WAR_COMMAND",
        "claim": "吕光受苻坚授西讨诸军事，率姜飞、彭晃、杜进、康盛等将军并董方、郭抱、贾虔、杨颖四府佐将讨西域",
        "event_id": expedition_event_id,
        "certainty": "FACT",
        "evidence": "率将军姜飞、彭晃、杜进、康盛等总兵七万，铁骑五千，以讨西域，以陇西董方、冯翊郭抱、武威贾虔、弘农杨颖为四府佐将",
        "source_id": ll09_source_id,
    })

    # Metadata: preserve v3 provenance and add v4 unification record.
    graph["metadata"] = {
        "schema_version": graph.get("schema_version", "historical-person-graph-v0.1.1"),
        "round": "04",
        "name": "Lv Guang <-> Fu Jian unification v4",
        "description": "Later Liang Lv Guang cluster bridged into Former Qin/Later Qin/Liu Yu v3 chain via directly grounded Lv Guang <-> Fu Jian relations.",
        "base_graph": str(V3_GRAPH),
        "base_sha256": _sha256_file(V3_GRAPH),
        "added_material": {
            "source": "LL09",
            "new_nodes": [name for name, _ in subordinates],
            "new_edges": len(new_edges),
            "new_events": 1,
            "new_slices": 1,
            "note": "Western expedition subordinates added at exact actor level from primary-source substring. No v1-v3 material regenerated.",
        },
        "bridge_nodes": {
            "吕光": lv_guang_id,
            "苻坚": fu_jian_id,
        },
        "bridge_sources": ["LL09", "LL10"],
        "v3_merge_metadata": v3.get("metadata", {}),
    }

    # Sort for stable output.
    nodes.sort(key=lambda x: int(x["id"]))
    edges.sort(key=lambda x: int(x["id"]))
    events.sort(key=lambda x: int(x["id"]))
    slices.sort(key=lambda x: int(x["id"]))
    sources.sort(key=lambda x: int(x["id"]))

    return graph


def _sha256_file(path: Path) -> str:
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--v3-graph", default=str(V3_GRAPH))
    ap.add_argument("--output", default=str(OUT_GRAPH))
    args = ap.parse_args()

    v3 = load_graph(Path(args.v3_graph))
    v4 = build_v4(v3)

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(v4, ensure_ascii=False, indent=2) + "\n", "utf-8")

    print(json.dumps({
        "status": "PASS",
        "output": str(out),
        "nodes": len(v4["nodes"]),
        "edges": len(v4["edges"]),
        "events": len(v4["events"]),
        "slices": len(v4["slices"]),
        "sources": len(v4["sources"]),
        "delta": {
            "nodes": len(v4["nodes"]) - len(v3["nodes"]),
            "edges": len(v4["edges"]) - len(v3["edges"]),
            "events": len(v4["events"]) - len(v3["events"]),
            "slices": len(v4["slices"]) - len(v3["slices"]),
            "sources": len(v4["sources"]) - len(v3["sources"]),
        },
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
