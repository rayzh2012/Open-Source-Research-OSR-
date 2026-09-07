#!/usr/bin/env python3
"""Merge a v1 historical person graph with a bridge-only graph to produce v2.

v1 nodes/edges/events/slices/sources are kept unchanged. Bridge nodes that match
an existing v1 node by (name, context) are remapped; all other bridge items are
renumbered deterministically to avoid ID collisions. No already-audited v1 edges
are regenerated.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def _norm(value: str) -> str:
    return (value or "").strip()


def load_graph(path: Path) -> dict:
    return json.loads(path.read_text("utf-8"))


def build_node_merge_map(v1_nodes: list[dict], bridge_nodes: list[dict]) -> dict[int, int]:
    """Map bridge node IDs to v2 node IDs. Matching (name, context) -> v1 ID."""
    v1_by_signature: dict[tuple[str, str], int] = {}
    for n in v1_nodes:
        v1_by_signature[(_norm(n["name"]), _norm(n["context"]))] = int(n["id"])

    mapping: dict[int, int] = {}
    next_id = max((int(n["id"]) for n in v1_nodes), default=0) + 1
    for n in bridge_nodes:
        bid = int(n["id"])
        sig = (_norm(n["name"]), _norm(n["context"]))
        if sig in v1_by_signature:
            mapping[bid] = v1_by_signature[sig]
        else:
            mapping[bid] = next_id
            next_id += 1
    return mapping


def build_source_merge_map(v1_sources: list[dict], bridge_sources: list[dict]) -> dict[int, int]:
    """Map bridge source IDs to v2 source IDs by provenance id if known, else new."""
    v1_by_prov_id: dict[str, int] = {}
    for s in v1_sources:
        prov_id = (s.get("provenance") or {}).get("id")
        if prov_id is not None:
            v1_by_prov_id[str(prov_id)] = int(s["id"])

    mapping: dict[int, int] = {}
    next_id = max((int(s["id"]) for s in v1_sources), default=0) + 1
    for s in bridge_sources:
        bid = int(s["id"])
        prov_id = (s.get("provenance") or {}).get("id")
        if prov_id is not None and str(prov_id) in v1_by_prov_id:
            mapping[bid] = v1_by_prov_id[str(prov_id)]
        else:
            mapping[bid] = next_id
            next_id += 1
    return mapping


def remap_items(items: list[dict], node_map: dict[int, int], source_map: dict[int, int],
                id_key: str = "id") -> list[dict]:
    """Remap IDs in graph items and assign new sequential IDs."""
    remapped = []
    for item in items:
        new_item = dict(item)
        # Remap source/target/participants/person_id fields.
        for key in ("source", "target", "person_id"):
            if key in new_item and new_item[key] is not None:
                new_item[key] = node_map.get(int(new_item[key]), int(new_item[key]))
        if "participants" in new_item:
            new_item["participants"] = [node_map.get(int(p), int(p)) for p in new_item["participants"]]
        if "source_id" in new_item and new_item["source_id"] is not None:
            new_item["source_id"] = source_map.get(int(new_item["source_id"]), int(new_item["source_id"]))
        # event_id references events; events will be renumbered separately, so keep for now.
        remapped.append(new_item)
    return remapped


def merge_graphs(v1: dict, bridge: dict) -> dict:
    v1_nodes = v1.get("nodes", [])
    bridge_nodes = bridge.get("nodes", [])
    node_map = build_node_merge_map(v1_nodes, bridge_nodes)

    v1_sources = v1.get("sources", [])
    bridge_sources = bridge.get("sources", [])
    source_map = build_source_merge_map(v1_sources, bridge_sources)

    # Nodes: keep v1 nodes, add bridge nodes that are not merged into v1.
    v2_nodes = [dict(n) for n in v1_nodes]
    seen_node_ids = {int(n["id"]) for n in v2_nodes}
    for n in bridge_nodes:
        bid = int(n["id"])
        vid = node_map[bid]
        if vid not in seen_node_ids:
            new_node = dict(n)
            new_node["id"] = vid
            v2_nodes.append(new_node)
            seen_node_ids.add(vid)

    # Sources: same pattern.
    v2_sources = [dict(s) for s in v1_sources]
    seen_source_ids = {int(s["id"]) for s in v2_sources}
    for s in bridge_sources:
        bid = int(s["id"])
        vid = source_map[bid]
        if vid not in seen_source_ids:
            new_source = dict(s)
            new_source["id"] = vid
            v2_sources.append(new_source)
            seen_source_ids.add(vid)

    # Events: v1 events keep IDs; bridge events get new IDs and remapped refs.
    v2_events = [dict(e) for e in v1.get("events", [])]
    event_id_map: dict[int, int] = {int(e["id"]): int(e["id"]) for e in v2_events}
    next_event_id = max((int(e["id"]) for e in v2_events), default=0) + 1
    bridge_events_remapped = remap_items(bridge.get("events", []), node_map, source_map)
    for e in bridge_events_remapped:
        old_eid = int(e["id"])
        new_eid = next_event_id
        event_id_map[old_eid] = new_eid
        e["id"] = new_eid
        v2_events.append(e)
        next_event_id += 1

    # Edges: remap node/source IDs and event IDs.
    v2_edges = [dict(r) for r in v1.get("edges", [])]
    next_edge_id = max((int(r["id"]) for r in v2_edges), default=0) + 1
    bridge_edges_remapped = remap_items(bridge.get("edges", []), node_map, source_map)
    for r in bridge_edges_remapped:
        r["id"] = next_edge_id
        r["source"] = node_map.get(int(r["source"]), int(r["source"]))
        r["target"] = node_map.get(int(r["target"]), int(r["target"]))
        if r.get("event_id") is not None:
            r["event_id"] = event_id_map.get(int(r["event_id"]), int(r["event_id"]))
        r["source_id"] = source_map.get(int(r["source_id"]), int(r["source_id"]))
        v2_edges.append(r)
        next_edge_id += 1

    # Slices: remap person/source IDs and event IDs.
    v2_slices = [dict(sl) for sl in v1.get("slices", [])]
    next_slice_id = max((int(sl["id"]) for sl in v2_slices), default=0) + 1
    bridge_slices_remapped = remap_items(bridge.get("slices", []), node_map, source_map)
    for sl in bridge_slices_remapped:
        sl["id"] = next_slice_id
        sl["person_id"] = node_map.get(int(sl["person_id"]), int(sl["person_id"]))
        if sl.get("event_id") is not None:
            sl["event_id"] = event_id_map.get(int(sl["event_id"]), int(sl["event_id"]))
        sl["source_id"] = source_map.get(int(sl["source_id"]), int(sl["source_id"]))
        v2_slices.append(sl)
        next_slice_id += 1

    return {
        "schema_version": v1.get("schema_version", "historical-person-graph-v0.1.1"),
        "metadata": {
            "merged_from": {
                "v1_graph": "historical-person-graph/cluster-out/later_liang_cluster.graph.json",
                "bridge_graph": "yao_hong_liu_yu_bridge.graph.json",
                "bridge_fixture": "historical-person-graph/fixtures/yao_hong_liu_yu_bridge.jsonl",
            },
            "node_merge_map": {str(k): v for k, v in node_map.items()},
            "source_merge_map": {str(k): v for k, v in source_map.items()},
        },
        "nodes": sorted(v2_nodes, key=lambda x: int(x["id"])),
        "edges": sorted(v2_edges, key=lambda x: int(x["id"])),
        "events": sorted(v2_events, key=lambda x: int(x["id"])),
        "slices": sorted(v2_slices, key=lambda x: int(x["id"])),
        "sources": sorted(v2_sources, key=lambda x: int(x["id"])),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--v1-graph", required=True)
    ap.add_argument("--bridge-graph", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    v1 = load_graph(Path(args.v1_graph))
    bridge = load_graph(Path(args.bridge_graph))
    v2 = merge_graphs(v1, bridge)

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(v2, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({
        "status": "PASS",
        "output": str(out),
        "nodes": len(v2["nodes"]),
        "edges": len(v2["edges"]),
        "events": len(v2["events"]),
        "slices": len(v2["slices"]),
        "sources": len(v2["sources"]),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
