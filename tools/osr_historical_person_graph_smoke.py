#!/usr/bin/env python3
"""Offline smoke test for the historical person graph store and schema."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from osr_historical_person_graph import GraphStore, validate_extraction


def main() -> int:
    source = {"text":"甲命乙守城，后乙继甲任。","source_kind":"synthetic-smoke","file":"smoke","row":0}
    extraction = validate_extraction({
        "persons":[
            {"local_id":"p1","name":"甲","aliases":[],"context":"synthetic","certainty":"FACT","evidence":"甲"},
            {"local_id":"p2","name":"乙","aliases":[],"context":"synthetic","certainty":"FACT","evidence":"乙"}
        ],
        "events":[{"local_id":"e1","date_text":"","event_type":"appointment","participants":["p1","p2"],"summary":"甲命乙守城","certainty":"FACT","evidence":"甲命乙守城"}],
        "relations":[{"source":"p1","target":"p2","relation_type":"appoints","event":"e1","start_text":"","end_text":"","certainty":"FACT","evidence":"甲命乙守城"}],
        "slices":[{"person":"p1","slice_type":"POWER","claim":"甲可下令乙守城","event":"e1","certainty":"FACT","evidence":"甲命乙守城"}]
    })
    with tempfile.TemporaryDirectory() as td:
        store = GraphStore(Path(td)/"graph.sqlite")
        store.ingest(source, extraction, {"model":"offline-smoke","elapsed_seconds":0,"usage":None})
        store.ingest(source, extraction, {"model":"offline-smoke","elapsed_seconds":0,"usage":None})
        graph = store.export_graph(); store.close()
        assert len(graph["nodes"]) == 2, graph
        assert len(graph["edges"]) == 1, graph
        assert len(graph["events"]) == 1, graph
        assert len(graph["slices"]) == 1, graph
        assert graph["edges"][0]["relation_type"] == "appoints"
        print(json.dumps({"status":"PASS","nodes":2,"edges":1,"events":1,"slices":1}))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
