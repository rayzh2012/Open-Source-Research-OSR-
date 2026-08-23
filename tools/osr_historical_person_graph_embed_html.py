#!/usr/bin/env python3
"""Embed a graph.json into a standalone copy of explorer.html."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--explorer", default="historical-person-graph/explorer.html")
    ap.add_argument("--graph-json", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    explorer = Path(args.explorer).read_text("utf-8")
    graph = json.loads(Path(args.graph_json).read_text("utf-8"))
    graph_json = json.dumps(graph, ensure_ascii=False)

    # Replace the manual file picker with a loaded indicator.
    explorer = explorer.replace(
        '<label class="file">载入 graph.json<input id="file" type="file" accept="application/json,.json"></label>',
        '<span class="file">后凉核心关系图 v1（已内嵌 graph.json）</span>',
    )

    # Inject the graph as a typed JSON script block before the main script.
    data_block = f'<script id="graph-data" type="application/json">{graph_json}</script>\n<script>'
    explorer = explorer.replace("<script>", data_block, 1)

    # Auto-load the embedded graph when the page opens.
    explorer = explorer.replace(
        "</script></body>",
        "loadGraph(JSON.parse(document.getElementById('graph-data').textContent));\n</script></body>",
    )

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(explorer, "utf-8")
    print(json.dumps({"status": "PASS", "output": str(out)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
