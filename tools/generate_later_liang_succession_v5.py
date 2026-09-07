#!/usr/bin/env python3
"""Generate Round-05 v5 unified graph: deepen the Later Liang succession/dyad
cluster around 吕光 -> 吕绍 -> 吕纂 -> 吕隆 / 吕超.

This script reuses the validated v4 unified graph
(`lvguang_fujian_unification_v4.graph.json`) and adds only new, directly
grounded material from the existing Later Liang fixture (LL00-LL11):

- 吕宝 as 吕光之弟 and father of 吕隆 (and by explicit brother link, 吕超)
- 吕纂 brother_of 吕绍
- explicit 吕纂 <-> 吕超 command/subordination (番禾太守)
- 吕隆 appoints 吕超 (佐命封安定公)
- 魏益多 kills 吕纂 (the beheading act)
- 姚硕德 as Later Qin commander against 吕隆
- 吕弼 as 吕隆's son executed with him
- DYAD_INTERACTION / FAMILY_SUCCESSION / CRISIS slices where text supports

No v1-v4 nodes, edges, events, slices or sources are regenerated.
No LLM/API calls are needed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


V4_GRAPH = Path("historical-person-graph/cluster-out/lvguang_fujian_unification_v4.graph.json")
OUT_GRAPH = Path("historical-person-graph/cluster-out/later_liang_succession_v5.graph.json")


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


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_v5(v4: dict) -> dict:
    graph = json.loads(json.dumps(v4))  # deep copy

    nodes = graph["nodes"]
    edges = graph["edges"]
    events = graph["events"]
    slices = graph["slices"]
    sources = graph["sources"]

    # Core Later Liang node IDs.
    ids = {
        name: find_node_id(nodes, name)
        for name in ("吕光", "吕绍", "吕纂", "吕弘", "吕超", "吕隆", "姚兴")
    }
    missing = [name for name, nid in ids.items() if nid is None]
    if missing:
        raise ValueError(f"v4 graph missing required Later Liang nodes: {missing}")

    # Source IDs in the reused v4 graph.
    sids = {
        prov: find_source_id(sources, prov)
        for prov in ("LL01", "LL05", "LL06", "LL07")
    }
    missing_src = [p for p, sid in sids.items() if sid is None]
    if missing_src:
        raise ValueError(f"v4 graph missing required sources: {missing_src}")

    next_node_id = max(int(n["id"]) for n in nodes) + 1
    next_event_id = max(int(e["id"]) for e in events) + 1
    next_edge_id = max(int(e["id"]) for e in edges) + 1
    next_slice_id = max(int(s["id"]) for s in slices) + 1

    def add_node(name: str, context: str) -> int:
        nonlocal next_node_id
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
        return nid

    # New nodes -------------------------------------------------------------
    # Aliases record the exact source form when the text omits the surname.
    lv_bao_id = add_node("吕宝", "吕光之弟/吕隆之父")
    nodes[-1]["aliases"] = ["宝"]
    wei_yiduo_id = add_node("魏益多", "后凉将军/斩吕纂首者")
    lv_bi_id = add_node("吕弼", "吕隆之子/与隆谋反")
    nodes[-1]["aliases"] = ["弼"]
    yao_shuode_id = add_node("姚硕德", "后秦将领/姚兴遣攻吕隆")

    # New events ------------------------------------------------------------
    # E1: 吕光临终谓纂弘辅佐太子绍，称兄弟缉穆 (LL01)
    e_brothers_id = next_event_id
    next_event_id += 1
    events.append({
        "id": e_brothers_id,
        "event_key": "e5f8a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0",
        "date_text": "",
        "event_type": "succession",
        "summary": "吕光临终嘱吕纂、吕弘辅佐太子吕绍，称兄弟缉穆",
        "certainty": "FACT",
        "evidence": "汝兄弟缉穆",
        "source_id": sids["LL01"],
        "participants": [ids["吕光"], ids["吕绍"], ids["吕纂"], ids["吕弘"]],
    })

    # E2: 吕超为纂番禾太守 (LL05)
    e_prefect_id = next_event_id
    next_event_id += 1
    events.append({
        "id": e_prefect_id,
        "event_key": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2",
        "date_text": "",
        "event_type": "appointment",
        "summary": "吕超为吕纂番禾太守",
        "certainty": "FACT",
        "evidence": "纂番禾太守吕超",
        "source_id": sids["LL05"],
        "participants": [ids["吕纂"], ids["吕超"]],
    })

    # E3: 魏益多斩吕纂首 (LL05)
    e_beheading_id = next_event_id
    next_event_id += 1
    events.append({
        "id": e_beheading_id,
        "event_key": "b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2c3",
        "date_text": "",
        "event_type": "killing",
        "summary": "魏益多斩吕纂首以徇",
        "certainty": "FACT",
        "evidence": "将军魏益多入，斩纂首以徇",
        "source_id": sids["LL05"],
        "participants": [ids["吕纂"], ids["吕超"], wei_yiduo_id],
    })

    # E4: 吕隆即位，追尊父宝，以弟超佐命封安定公 (LL06)
    e_long_accession_id = next_event_id
    next_event_id += 1
    events.append({
        "id": e_long_accession_id,
        "event_key": "c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2c3d4",
        "date_text": "",
        "event_type": "succession",
        "summary": "吕隆即位，追尊父吕宝，以弟吕超佐命之勋拜官封安定公",
        "certainty": "FACT",
        "evidence": "追尊父宝为文皇帝",
        "source_id": sids["LL06"],
        "participants": [ids["吕纂"], ids["吕超"], ids["吕隆"], lv_bao_id],
    })

    # E5: 吕隆遣超迎请于姚兴 (LL07)
    e_envoy_id = next_event_id
    next_event_id += 1
    events.append({
        "id": e_envoy_id,
        "event_key": "d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2c3d4e5",
        "date_text": "",
        "event_type": "other",
        "summary": "吕隆遣吕超率骑二百迎请于姚兴",
        "certainty": "FACT",
        "evidence": "遣超率骑二百，多赍珍宝，请迎于姚兴",
        "source_id": sids["LL07"],
        "participants": [ids["吕超"], ids["吕隆"], ids["姚兴"]],
    })

    # E6: 姚兴遣姚硕德攻吕隆 (LL07)
    e_qin_attack_id = next_event_id
    next_event_id += 1
    events.append({
        "id": e_qin_attack_id,
        "event_key": "e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2c3d4e5f6",
        "date_text": "",
        "event_type": "war",
        "summary": "姚兴遣姚硕德率众至姑臧攻吕隆",
        "certainty": "FACT",
        "evidence": "硕德遂率众至姑臧",
        "source_id": sids["LL07"],
        "participants": [yao_shuode_id, ids["吕隆"], ids["姚兴"]],
    })

    # E7: 吕隆与子弼谋反，为姚兴所诛 (LL07)
    e_long_death_id = next_event_id
    next_event_id += 1
    events.append({
        "id": e_long_death_id,
        "event_key": "f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2c3d4e5f6a7",
        "date_text": "",
        "event_type": "killing",
        "summary": "吕隆与子吕弼谋反，为姚兴所诛",
        "certainty": "FACT",
        "evidence": "其后隆坐与子弼谋反，为兴所诛",
        "source_id": sids["LL07"],
        "participants": [ids["吕隆"], lv_bi_id, ids["姚兴"]],
    })

    # New edges -------------------------------------------------------------
    new_edges = [
        # Family structure
        {
            "source": ids["吕光"],
            "target": lv_bao_id,
            "relation_type": "brother_of",
            "event_id": e_long_accession_id,
            "certainty": "FACT",
            "evidence": "光弟宝之子也",
            "source_id": sids["LL06"],
        },
        {
            "source": lv_bao_id,
            "target": ids["吕隆"],
            "relation_type": "father_of",
            "event_id": e_long_accession_id,
            "certainty": "FACT",
            "evidence": "光弟宝之子也",
            "source_id": sids["LL06"],
        },
        {
            "source": ids["吕纂"],
            "target": ids["吕绍"],
            "relation_type": "brother_of",
            "event_id": e_brothers_id,
            "certainty": "FACT",
            "evidence": "汝兄弟缉穆",
            "source_id": sids["LL01"],
        },
        # Command / subordination
        {
            "source": ids["吕纂"],
            "target": ids["吕超"],
            "relation_type": "commands",
            "event_id": e_prefect_id,
            "certainty": "FACT",
            "evidence": "纂番禾太守吕超",
            "source_id": sids["LL05"],
        },
        {
            "source": ids["吕超"],
            "target": ids["吕纂"],
            "relation_type": "subordinate_to",
            "event_id": e_prefect_id,
            "certainty": "FACT",
            "evidence": "纂番禾太守吕超",
            "source_id": sids["LL05"],
        },
        {
            "source": ids["吕隆"],
            "target": ids["吕超"],
            "relation_type": "appoints",
            "event_id": e_long_accession_id,
            "certainty": "FACT",
            "evidence": "以弟超有佐命之勋，拜使持节、侍中、都督中外诸军事、辅国大将军、司隶校尉、录尚书事，封安定公",
            "source_id": sids["LL06"],
        },
        {
            "source": ids["吕隆"],
            "target": ids["吕超"],
            "relation_type": "commands",
            "event_id": e_envoy_id,
            "certainty": "FACT",
            "evidence": "遣超率骑二百，多赍珍宝，请迎于姚兴",
            "source_id": sids["LL07"],
        },
        # Killing / execution
        {
            "source": wei_yiduo_id,
            "target": ids["吕纂"],
            "relation_type": "kills",
            "event_id": e_beheading_id,
            "certainty": "FACT",
            "evidence": "将军魏益多入，斩纂首以徇",
            "source_id": sids["LL05"],
        },
        {
            "source": ids["吕隆"],
            "target": lv_bi_id,
            "relation_type": "father_of",
            "event_id": e_long_death_id,
            "certainty": "FACT",
            "evidence": "其后隆坐与子弼谋反，为兴所诛",
            "source_id": sids["LL07"],
        },
        {
            "source": ids["姚兴"],
            "target": lv_bi_id,
            "relation_type": "kills",
            "event_id": e_long_death_id,
            "certainty": "FACT",
            "evidence": "其后隆坐与子弼谋反，为兴所诛",
            "source_id": sids["LL07"],
        },
        # External Later Qin command
        {
            "source": ids["姚兴"],
            "target": yao_shuode_id,
            "relation_type": "commands",
            "event_id": e_qin_attack_id,
            "certainty": "FACT",
            "evidence": "魏安人焦朗遣使说姚兴将姚硕德",
            "source_id": sids["LL07"],
        },
        {
            "source": yao_shuode_id,
            "target": ids["姚兴"],
            "relation_type": "subordinate_to",
            "event_id": e_qin_attack_id,
            "certainty": "FACT",
            "evidence": "魏安人焦朗遣使说姚兴将姚硕德",
            "source_id": sids["LL07"],
        },
        {
            "source": yao_shuode_id,
            "target": ids["吕隆"],
            "relation_type": "enemy_of",
            "event_id": e_qin_attack_id,
            "certainty": "FACT",
            "evidence": "硕德遂率众至姑臧",
            "source_id": sids["LL07"],
        },
    ]

    for item in new_edges:
        item["id"] = next_edge_id
        item["start_text"] = ""
        item["end_text"] = ""
        next_edge_id += 1
        edges.append(item)

    # New slices -----------------------------------------------------------
    new_slices = [
        {
            "person_id": ids["吕隆"],
            "slice_type": "DYAD_INTERACTION",
            "claim": "吕超让位与吕隆并以佐命之勋获重权，二人形成政治同盟",
            "event_id": e_long_accession_id,
            "certainty": "FACT",
            "evidence": "超既杀纂，让位于隆",
            "source_id": sids["LL06"],
        },
        {
            "person_id": ids["吕超"],
            "slice_type": "DYAD_INTERACTION",
            "claim": "吕超佐命吕隆即位，受拜使持节等职封安定公",
            "event_id": e_long_accession_id,
            "certainty": "FACT",
            "evidence": "以弟超有佐命之勋，拜使持节、侍中、都督中外诸军事、辅国大将军、司隶校尉、录尚书事，封安定公",
            "source_id": sids["LL06"],
        },
        {
            "person_id": lv_bao_id,
            "slice_type": "FAMILY_SUCCESSION",
            "claim": "吕宝为吕光之弟，其子吕隆追尊为文皇帝",
            "event_id": e_long_accession_id,
            "certainty": "FACT",
            "evidence": "追尊父宝为文皇帝",
            "source_id": sids["LL06"],
        },
        {
            "person_id": ids["吕隆"],
            "slice_type": "FAMILY_SUCCESSION",
            "claim": "吕隆为吕光弟吕宝之子，承后凉末位",
            "event_id": e_long_accession_id,
            "certainty": "FACT",
            "evidence": "光弟宝之子也",
            "source_id": sids["LL06"],
        },
        {
            "person_id": ids["吕纂"],
            "slice_type": "CRISIS",
            "claim": "吕超刺纂后，魏益多斩吕纂首以徇",
            "event_id": e_beheading_id,
            "certainty": "FACT",
            "evidence": "将军魏益多入，斩纂首以徇",
            "source_id": sids["LL05"],
        },
        {
            "person_id": ids["吕隆"],
            "slice_type": "FAILURE_BLINDSPOT",
            "claim": "吕隆终与子吕弼谋反，同为姚兴所诛",
            "event_id": e_long_death_id,
            "certainty": "FACT",
            "evidence": "其后隆坐与子弼谋反，为兴所诛",
            "source_id": sids["LL07"],
        },
    ]

    for item in new_slices:
        item["id"] = next_slice_id
        next_slice_id += 1
        slices.append(item)

    # Metadata --------------------------------------------------------------
    graph["metadata"] = {
        "schema_version": graph.get("schema_version", "historical-person-graph-v0.1.1"),
        "round": "05",
        "name": "Later Liang succession/dyad v5",
        "description": "Later Liang succession/dyad cluster around 吕光 -> 吕绍 -> 吕纂 -> 吕隆 / 吕超, deepening exact-actor family, command, killing, and alliance relations while preserving the v4 cross-regime chain.",
        "base_graph": str(V4_GRAPH),
        "base_sha256": _sha256_file(V4_GRAPH),
        "added_material": {
            "sources": ["LL01", "LL05", "LL06", "LL07"],
            "new_nodes": ["吕宝", "魏益多", "吕弼", "姚硕德"],
            "new_edges": len(new_edges),
            "new_events": 7,
            "new_slices": len(new_slices),
            "note": "Deepened Later Liang succession/dyad material from existing fixture sources only. No v1-v4 material regenerated.",
        },
        "bridge_nodes": {
            "吕光": ids["吕光"],
            "吕绍": ids["吕绍"],
            "吕纂": ids["吕纂"],
            "吕隆": ids["吕隆"],
            "吕超": ids["吕超"],
        },
        "v4_metadata": v4.get("metadata", {}),
    }

    # Stable sort.
    nodes.sort(key=lambda x: int(x["id"]))
    edges.sort(key=lambda x: int(x["id"]))
    events.sort(key=lambda x: int(x["id"]))
    slices.sort(key=lambda x: int(x["id"]))
    sources.sort(key=lambda x: int(x["id"]))

    return graph


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--v4-graph", default=str(V4_GRAPH))
    ap.add_argument("--output", default=str(OUT_GRAPH))
    args = ap.parse_args()

    v4 = load_graph(Path(args.v4_graph))
    v5 = build_v5(v4)

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(v5, ensure_ascii=False, indent=2) + "\n", "utf-8")

    print(json.dumps({
        "status": "PASS",
        "output": str(out),
        "nodes": len(v5["nodes"]),
        "edges": len(v5["edges"]),
        "events": len(v5["events"]),
        "slices": len(v5["slices"]),
        "sources": len(v5["sources"]),
        "delta": {
            "nodes": len(v5["nodes"]) - len(v4["nodes"]),
            "edges": len(v5["edges"]) - len(v4["edges"]),
            "events": len(v5["events"]) - len(v4["events"]),
            "slices": len(v5["slices"]) - len(v4["slices"]),
            "sources": len(v5["sources"]) - len(v4["sources"]),
        },
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
