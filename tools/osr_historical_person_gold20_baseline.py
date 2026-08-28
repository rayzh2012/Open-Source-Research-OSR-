#!/usr/bin/env python3
"""Deterministic baseline for the Lv Guang gold-20 fixture.

This is NOT a replacement for Kimi. It proves that the same real-source fixture can
flow through the provenance store/export/UI path before model extraction is enabled.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from osr_historical_person_graph import GraphStore, iter_source_records, validate_extraction


def slice_type(text: str) -> str:
    if any(k in text for k in ("战", "攻", "龟兹", "军", "阵", "骑", "粮")):
        return "WAR_COMMAND"
    if any(k in text for k in ("太子", "继承", "兄弟", "临终", "绍", "纂", "弘")):
        return "FAMILY_SUCCESSION"
    if any(k in text for k in ("信谗", "杜进", "尉祐", "忠孝", "反叛")):
        return "TRUST_BETRAYAL"
    if any(k in text for k in ("严刑", "责躬", "宽简", "政")):
        return "GOVERNANCE"
    if any(k in text for k in ("异", "重瞳", "神光", "史文", "评")):
        return "HISTORIOGRAPHY_BIAS"
    return "DECISION"


def event_type(text: str) -> str:
    if any(k in text for k in ("杀", "诛")):
        return "killing"
    if any(k in text for k in ("战", "攻", "龟兹", "军", "阵", "骑")):
        return "war"
    if any(k in text for k in ("太子", "继承", "临终")):
        return "succession"
    if any(k in text for k in ("曰", "评价", "判断", "反对")):
        return "speech"
    return "other"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="historical-person-graph/fixtures/lvguang_gold_20.jsonl")
    ap.add_argument("--db", default="historical-person-graph/baseline-out/lvguang_gold_20.sqlite")
    ap.add_argument("--graph-json", default="historical-person-graph/baseline-out/lvguang_gold_20.graph.json")
    args = ap.parse_args()

    Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    Path(args.graph_json).parent.mkdir(parents=True, exist_ok=True)
    store = GraphStore(Path(args.db))
    count = 0
    try:
        for rec in iter_source_records([Path(args.input)]):
            count += 1
            text = rec["text"]
            name = str(rec.get("target_person") or "吕光")
            obj = {
                "persons": [{
                    "local_id": "p1",
                    "name": name,
                    "aliases": [],
                    "context": "4世纪前秦将领/后凉建立者",
                    "certainty": "FACT",
                    "evidence": name,
                }],
                "events": [{
                    "local_id": "e1",
                    "date_text": "",
                    "event_type": event_type(text),
                    "participants": ["p1"],
                    "summary": text[:120],
                    "certainty": "FACT" if "primary" in str(rec.get("source_kind", "")) else "INFERENCE",
                    "evidence": text[:80],
                }],
                "relations": [],
                "slices": [{
                    "person": "p1",
                    "slice_type": slice_type(text),
                    "claim": "Deterministic baseline classification only; semantic claim reserved for Kimi extraction.",
                    "event": "e1",
                    "certainty": "OPEN",
                    "evidence": text[:80],
                }],
            }
            store.ingest(rec, validate_extraction(obj), {
                "model": "deterministic-gold20-baseline",
                "elapsed_seconds": 0.0,
                "usage": None,
            })
        graph = store.export_graph()
    finally:
        store.close()

    Path(args.graph_json).write_text(json.dumps(graph, ensure_ascii=False, indent=2) + "\n", "utf-8")
    assert count == 20, count
    assert len(graph["sources"]) == 20, len(graph["sources"])
    assert len(graph["nodes"]) == 1, len(graph["nodes"])
    assert len(graph["events"]) == 20, len(graph["events"])
    assert len(graph["slices"]) == 20, len(graph["slices"])
    print(json.dumps({
        "status": "PASS",
        "records": count,
        "sources": len(graph["sources"]),
        "nodes": len(graph["nodes"]),
        "events": len(graph["events"]),
        "slices": len(graph["slices"]),
        "graph_json": args.graph_json,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
