from __future__ import annotations

import argparse
import json
from pathlib import Path

from .core import MythDB


def _print_hits(hits) -> None:
    for h in hits:
        print(json.dumps({
            "witness_id": h.witness_id,
            "segment_id": h.segment_id,
            "ordinal": h.ordinal,
            "score": round(h.score, 6),
            "text": h.text,
        }, ensure_ascii=False))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Myth Engine deterministic corpus index")
    sub = p.add_subparsers(dest="cmd", required=True)

    init = sub.add_parser("init")
    init.add_argument("db")

    ingest = sub.add_parser("ingest")
    ingest.add_argument("db")
    ingest.add_argument("--meta", required=True, help="JSON metadata file")
    ingest.add_argument("--text", required=True, help="UTF-8 extracted text file")

    phrase = sub.add_parser("phrase")
    phrase.add_argument("db")
    phrase.add_argument("query")
    phrase.add_argument("--limit", type=int, default=50)

    fuzzy = sub.add_parser("fuzzy")
    fuzzy.add_argument("db")
    fuzzy.add_argument("query")
    fuzzy.add_argument("--limit", type=int, default=20)

    dictionary = sub.add_parser("dictionary")
    dictionary.add_argument("db")
    dictionary.add_argument("keywords", nargs="+")

    compare = sub.add_parser("compare")
    compare.add_argument("db")
    compare.add_argument("left")
    compare.add_argument("right")

    bfs = sub.add_parser("bfs")
    bfs.add_argument("db")
    bfs.add_argument("start")
    bfs.add_argument("--depth", type=int, default=3)
    bfs.add_argument("--edge-type")

    dfs = sub.add_parser("dfs")
    dfs.add_argument("db")
    dfs.add_argument("start")
    dfs.add_argument("--edge-type")

    return p


def main() -> int:
    args = build_parser().parse_args()
    db = MythDB(args.db)
    try:
        if args.cmd == "init":
            print(args.db)
        elif args.cmd == "ingest":
            meta = json.loads(Path(args.meta).read_text(encoding="utf-8"))
            text = Path(args.text).read_text(encoding="utf-8")
            print(db.add_witness(meta, text))
        elif args.cmd == "phrase":
            _print_hits(db.search_phrase(args.query, args.limit))
        elif args.cmd == "fuzzy":
            _print_hits(db.search_fuzzy(args.query, args.limit))
        elif args.cmd == "dictionary":
            data = db.dictionary_scan(args.keywords)
            for kw, hits in data.items():
                print(json.dumps({"keyword": kw, "hits": len(hits)}, ensure_ascii=False))
                _print_hits(hits)
        elif args.cmd == "compare":
            print(json.dumps(db.compare_witnesses(args.left, args.right), ensure_ascii=False, indent=2))
        elif args.cmd == "bfs":
            print(json.dumps(db.bfs(args.start, args.depth, args.edge_type), ensure_ascii=False, indent=2))
        elif args.cmd == "dfs":
            print(json.dumps(db.dfs(args.start, args.edge_type), ensure_ascii=False, indent=2))
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
