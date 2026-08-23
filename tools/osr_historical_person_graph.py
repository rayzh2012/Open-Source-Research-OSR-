#!/usr/bin/env python3
"""Build a provenance-first historical person graph from OSR corpus snippets.

Downstream only: this tool never mutates Stage-2 raw Parquet/checkpoints. It accepts
Stage-2 result.json(.gz) samples or JSONL rehydrated rows, calls an OpenAI-compatible
Sub2API/Kimi route, and persists evidence-bound people/events/relations/slices.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator

import requests

SLICE_TYPES = {
    "DECISION", "WAR_COMMAND", "POWER", "RELATION", "FAMILY_SUCCESSION",
    "TRUST_BETRAYAL", "GOVERNANCE", "CRISIS", "FAILURE_BLINDSPOT",
    "LANGUAGE_SELF_MODEL", "HISTORIOGRAPHY_BIAS", "DYAD_INTERACTION",
}
CERTAINTY = {"FACT", "INFERENCE", "OPEN"}
SCHEMA_VERSION = "historical-person-graph-v0.1.1"

SYSTEM_PROMPT = f"""You are Historical Extractor, a strict evidence compiler.
Use ONLY the supplied source snippet. Never add biographical knowledge from memory.
Return one JSON object and nothing else. If identity is ambiguous, keep it OPEN;
never merge two people because they share a name/title/clan.

Allowed certainty values: FACT, INFERENCE, OPEN.
Allowed slice_type values: {', '.join(sorted(SLICE_TYPES))}.

JSON schema:
{{
  "persons": [{{"local_id":"p1","name":"name from snippet","aliases":[],"context":"visible polity/time/office disambiguator or empty","certainty":"FACT|INFERENCE|OPEN","evidence":"short supporting phrase"}}],
  "events": [{{"local_id":"e1","date_text":"visible date or empty","event_type":"war|appointment|succession|killing|alliance|betrayal|governance|speech|other","participants":["p1"],"summary":"minimal evidence-bound paraphrase","certainty":"FACT|INFERENCE|OPEN","evidence":"short supporting phrase"}}],
  "relations": [{{"source":"p1","target":"p2","relation_type":"father_of|son_of|brother_of|ruler_of|serves|commands|allied_with|enemy_of|kills|succeeds|appoints|supports|opposes|other","event":"e1 or empty","start_text":"visible start/date or empty","end_text":"visible end/date or empty","certainty":"FACT|INFERENCE|OPEN","evidence":"short supporting phrase"}}],
  "slices": [{{"person":"p1","slice_type":"one allowed value","claim":"single bounded behavioral observation; no lifetime personality claim","event":"e1 or empty","certainty":"FACT|INFERENCE|OPEN","evidence":"short supporting phrase"}}]
}}

Hard rules:
- One event is not a permanent personality trait.
- Historiography/narrative judgment belongs in HISTORIOGRAPHY_BIAS, not FACT about mind.
- Relation edges are temporal when the snippet supports dates/state changes.
- Do not infer family relations from shared surname.
- Do not infer motive unless text states it; otherwise INFERENCE/OPEN.
"""


def _stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _norm_name(value: str) -> str:
    return re.sub(r"[\s·•・\-—_]+", "", value or "").strip()


def _read_json(path: Path) -> Any:
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return json.load(f)
    return json.loads(path.read_text("utf-8"))


def iter_source_records(paths: Iterable[Path]) -> Iterator[dict[str, Any]]:
    """Yield normalized snippet records from Stage-2 JSON/GZ or generic JSONL."""
    for path in paths:
        if path.suffix in {".json", ".gz"}:
            obj = _read_json(path)
            if isinstance(obj, dict) and isinstance(obj.get("results"), list):
                for shard in obj["results"]:
                    for term, samples in (shard.get("samples") or {}).items():
                        for sample in samples or []:
                            snippet = sample.get("snippet")
                            if not isinstance(snippet, str) or not snippet.strip():
                                continue
                            yield {
                                "text": snippet,
                                "source_kind": "osr-stage2-sample",
                                "source": shard.get("source"),
                                "repo": shard.get("repo"),
                                "file": shard.get("file"),
                                "row": sample.get("row"),
                                "position": sample.get("position"),
                                "row_sha256": sample.get("row_sha256"),
                                "query_term": term,
                                "input_file": str(path),
                            }
                continue
            items = obj if isinstance(obj, list) else [obj]
            for item in items:
                if not isinstance(item, dict):
                    continue
                text = item.get("text") or item.get("snippet") or item.get("content")
                if isinstance(text, str) and text.strip():
                    rec = dict(item)
                    rec["text"] = text
                    rec.setdefault("input_file", str(path))
                    yield rec
            continue
        with path.open("rt", encoding="utf-8") as f:
            for line_no, line in enumerate(f, 1):
                if not line.strip():
                    continue
                item = json.loads(line)
                if not isinstance(item, dict):
                    continue
                text = item.get("text") or item.get("snippet") or item.get("content")
                if not isinstance(text, str) or not text.strip():
                    continue
                rec = dict(item)
                rec["text"] = text
                rec.setdefault("input_file", str(path))
                rec.setdefault("input_line", line_no)
                yield rec


@dataclass
class GatewayConfig:
    base_url: str
    api_key: str
    model: str
    chat_path: str = "/v1/chat/completions"
    timeout: int = 120

    @classmethod
    def from_args(cls, args: argparse.Namespace) -> "GatewayConfig":
        base_url = args.base_url or os.getenv("SUB2API_BASE_URL") or os.getenv("KIMI_BASE_URL")
        api_key = args.api_key or os.getenv("SUB2API_API_KEY") or os.getenv("KIMI_API_KEY")
        model = args.model or os.getenv("SUB2API_MODEL") or os.getenv("KIMI_MODEL") or "kimi"
        if not base_url or not api_key:
            raise SystemExit(
                "Missing gateway config: set SUB2API_BASE_URL + SUB2API_API_KEY "
                "(preferred) or KIMI_BASE_URL + KIMI_API_KEY."
            )
        return cls(base_url=base_url, api_key=api_key, model=model, chat_path=args.chat_path, timeout=args.timeout)


class ChatExtractor:
    def __init__(self, config: GatewayConfig):
        self.config = config

    def extract(self, source: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        provenance = {k: v for k, v in source.items() if k != "text"}
        user_prompt = json.dumps(
            {"provenance": provenance, "snippet": source["text"]},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        base = self.config.base_url.rstrip("/")
        path = "/" + self.config.chat_path.lstrip("/")
        if base.endswith("/v1") and path.startswith("/v1/"):
            path = path[3:]
        url = base + path
        payload = {
            "model": self.config.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        }
        t0 = time.time()
        r = requests.post(
            url,
            headers={"Authorization": f"Bearer {self.config.api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=self.config.timeout,
        )
        r.raise_for_status()
        body = r.json()
        content = body["choices"][0]["message"]["content"]
        return parse_json_object(content), {
            "model": self.config.model,
            "elapsed_seconds": round(time.time() - t0, 3),
            "usage": body.get("usage"),
        }


def parse_json_object(content: str) -> dict[str, Any]:
    content = content.strip()
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content)
    try:
        obj = json.loads(content)
    except json.JSONDecodeError:
        start, end = content.find("{"), content.rfind("}")
        if start < 0 or end <= start:
            raise
        obj = json.loads(content[start : end + 1])
    if not isinstance(obj, dict):
        raise ValueError("Extractor response must be a JSON object")
    return obj


def validate_extraction(obj: dict[str, Any]) -> dict[str, Any]:
    for key in ("persons", "events", "relations", "slices"):
        if not isinstance(obj.get(key, []), list):
            raise ValueError(f"{key} must be a list")
        obj.setdefault(key, [])
    person_ids = {str(p.get("local_id")) for p in obj["persons"] if p.get("local_id")}
    event_ids = {str(e.get("local_id")) for e in obj["events"] if e.get("local_id")}
    for p in obj["persons"]:
        if not p.get("local_id") or not p.get("name"):
            raise ValueError("person requires local_id and name")
        if p.get("certainty", "OPEN") not in CERTAINTY:
            p["certainty"] = "OPEN"
    for e in obj["events"]:
        if not e.get("local_id"):
            raise ValueError("event requires local_id")
        e["participants"] = [x for x in e.get("participants", []) if x in person_ids]
        if e.get("certainty", "OPEN") not in CERTAINTY:
            e["certainty"] = "OPEN"
    for rel in obj["relations"]:
        if rel.get("source") not in person_ids or rel.get("target") not in person_ids:
            raise ValueError("relation source/target must reference local person ids")
        if rel.get("event") and rel["event"] not in event_ids:
            rel["event"] = ""
        if rel.get("certainty", "OPEN") not in CERTAINTY:
            rel["certainty"] = "OPEN"
    for sl in obj["slices"]:
        if sl.get("person") not in person_ids:
            raise ValueError("slice person must reference a local person id")
        if sl.get("slice_type") not in SLICE_TYPES:
            raise ValueError(f"invalid slice_type: {sl.get('slice_type')}")
        if sl.get("event") and sl["event"] not in event_ids:
            sl["event"] = ""
        if sl.get("certainty", "OPEN") not in CERTAINTY:
            sl["certainty"] = "OPEN"
    return obj


SCHEMA_SQL = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS sources (
  id INTEGER PRIMARY KEY, source_key TEXT NOT NULL UNIQUE, text TEXT NOT NULL,
  provenance_json TEXT NOT NULL, row_sha256 TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS extraction_runs (
  id INTEGER PRIMARY KEY, source_id INTEGER NOT NULL REFERENCES sources(id), model TEXT,
  schema_version TEXT NOT NULL, response_sha256 TEXT NOT NULL, raw_json TEXT NOT NULL,
  usage_json TEXT, elapsed_seconds REAL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(source_id, model, schema_version, response_sha256)
);
CREATE TABLE IF NOT EXISTS persons (
  id INTEGER PRIMARY KEY, resolver_key TEXT NOT NULL UNIQUE, canonical_name TEXT NOT NULL,
  context TEXT NOT NULL DEFAULT '', resolution_status TEXT NOT NULL DEFAULT 'OPEN',
  certainty TEXT NOT NULL DEFAULT 'OPEN'
);
CREATE TABLE IF NOT EXISTS aliases (
  person_id INTEGER NOT NULL REFERENCES persons(id), alias TEXT NOT NULL,
  source_id INTEGER NOT NULL REFERENCES sources(id), PRIMARY KEY(person_id, alias, source_id)
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY, event_key TEXT NOT NULL UNIQUE, date_text TEXT, event_type TEXT,
  summary TEXT NOT NULL, certainty TEXT NOT NULL, evidence TEXT,
  source_id INTEGER NOT NULL REFERENCES sources(id)
);
CREATE TABLE IF NOT EXISTS event_persons (
  event_id INTEGER NOT NULL REFERENCES events(id), person_id INTEGER NOT NULL REFERENCES persons(id),
  PRIMARY KEY(event_id, person_id)
);
CREATE TABLE IF NOT EXISTS relations (
  id INTEGER PRIMARY KEY, relation_key TEXT NOT NULL UNIQUE,
  source_person_id INTEGER NOT NULL REFERENCES persons(id),
  target_person_id INTEGER NOT NULL REFERENCES persons(id), relation_type TEXT NOT NULL,
  event_id INTEGER REFERENCES events(id), start_text TEXT, end_text TEXT,
  certainty TEXT NOT NULL, evidence TEXT, source_id INTEGER NOT NULL REFERENCES sources(id)
);
CREATE TABLE IF NOT EXISTS slices (
  id INTEGER PRIMARY KEY, slice_key TEXT NOT NULL UNIQUE,
  person_id INTEGER NOT NULL REFERENCES persons(id), slice_type TEXT NOT NULL, claim TEXT NOT NULL,
  event_id INTEGER REFERENCES events(id), certainty TEXT NOT NULL, evidence TEXT,
  source_id INTEGER NOT NULL REFERENCES sources(id)
);
CREATE INDEX IF NOT EXISTS idx_rel_source ON relations(source_person_id);
CREATE INDEX IF NOT EXISTS idx_rel_target ON relations(target_person_id);
CREATE INDEX IF NOT EXISTS idx_slice_person ON slices(person_id, slice_type);
CREATE INDEX IF NOT EXISTS idx_event_date ON events(date_text);
"""


class GraphStore:
    def __init__(self, path: Path):
        self.path = path
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA_SQL)

    def close(self) -> None:
        self.db.commit()
        self.db.close()

    def source_id(self, source: dict[str, Any]) -> int:
        text = source["text"]
        prov = {k: v for k, v in source.items() if k != "text"}
        row_sha = source.get("row_sha256") or _stable_hash(text)
        source_key = _stable_hash(
            json.dumps([prov, row_sha], ensure_ascii=False, sort_keys=True, default=str)
        )
        self.db.execute(
            "INSERT OR IGNORE INTO sources(source_key,text,provenance_json,row_sha256) VALUES(?,?,?,?)",
            (source_key, text, json.dumps(prov, ensure_ascii=False, sort_keys=True, default=str), row_sha),
        )
        return int(self.db.execute("SELECT id FROM sources WHERE source_key=?", (source_key,)).fetchone()[0])

    def has_source_run(self, source_id: int, model: str) -> bool:
        return self.db.execute(
            "SELECT 1 FROM extraction_runs WHERE source_id=? AND model=? AND schema_version=? LIMIT 1",
            (source_id, model, SCHEMA_VERSION),
        ).fetchone() is not None

    def ingest(self, source: dict[str, Any], obj: dict[str, Any], meta: dict[str, Any]) -> None:
        sid = self.source_id(source)
        local_people: dict[str, int] = {}
        for p in obj["persons"]:
            name = str(p["name"]).strip()
            context = str(p.get("context") or "").strip()
            # Critical Entity Split rule: context-free same-name mentions remain source-scoped OPEN
            # nodes. Only context-bearing candidates may meet across sources in this v0.1 resolver.
            resolver_context = context if context else f"OPEN_SOURCE_{sid}"
            resolver_key = _stable_hash(_norm_name(name) + "|" + resolver_context)
            self.db.execute(
                "INSERT OR IGNORE INTO persons(resolver_key,canonical_name,context,resolution_status,certainty) VALUES(?,?,?,?,?)",
                (resolver_key, name, context, "OPEN" if not context else "CANDIDATE", p.get("certainty", "OPEN")),
            )
            pid = int(self.db.execute("SELECT id FROM persons WHERE resolver_key=?", (resolver_key,)).fetchone()[0])
            local_people[str(p["local_id"])] = pid
            for alias in p.get("aliases") or []:
                if str(alias).strip():
                    self.db.execute(
                        "INSERT OR IGNORE INTO aliases(person_id,alias,source_id) VALUES(?,?,?)",
                        (pid, str(alias).strip(), sid),
                    )

        local_events: dict[str, int] = {}
        for e in obj["events"]:
            event_key = _stable_hash(
                json.dumps(
                    [sid, e.get("date_text"), e.get("event_type"), e.get("summary"), e.get("evidence")],
                    ensure_ascii=False,
                )
            )
            self.db.execute(
                "INSERT OR IGNORE INTO events(event_key,date_text,event_type,summary,certainty,evidence,source_id) VALUES(?,?,?,?,?,?,?)",
                (event_key, e.get("date_text"), e.get("event_type"), e.get("summary") or "", e.get("certainty", "OPEN"), e.get("evidence"), sid),
            )
            eid = int(self.db.execute("SELECT id FROM events WHERE event_key=?", (event_key,)).fetchone()[0])
            local_events[str(e["local_id"])] = eid
            for lp in e.get("participants") or []:
                if lp in local_people:
                    self.db.execute(
                        "INSERT OR IGNORE INTO event_persons(event_id,person_id) VALUES(?,?)",
                        (eid, local_people[lp]),
                    )

        for rel in obj["relations"]:
            sp, tp = local_people[rel["source"]], local_people[rel["target"]]
            eid = local_events.get(str(rel.get("event") or ""))
            key = _stable_hash(
                json.dumps(
                    [sid, sp, tp, rel.get("relation_type"), eid, rel.get("start_text"), rel.get("end_text"), rel.get("evidence")],
                    ensure_ascii=False,
                )
            )
            self.db.execute(
                "INSERT OR IGNORE INTO relations(relation_key,source_person_id,target_person_id,relation_type,event_id,start_text,end_text,certainty,evidence,source_id) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (key, sp, tp, rel.get("relation_type") or "other", eid, rel.get("start_text"), rel.get("end_text"), rel.get("certainty", "OPEN"), rel.get("evidence"), sid),
            )

        for sl in obj["slices"]:
            pid = local_people[sl["person"]]
            eid = local_events.get(str(sl.get("event") or ""))
            key = _stable_hash(
                json.dumps(
                    [sid, pid, sl.get("slice_type"), sl.get("claim"), eid, sl.get("evidence")],
                    ensure_ascii=False,
                )
            )
            self.db.execute(
                "INSERT OR IGNORE INTO slices(slice_key,person_id,slice_type,claim,event_id,certainty,evidence,source_id) VALUES(?,?,?,?,?,?,?,?)",
                (key, pid, sl["slice_type"], sl.get("claim") or "", eid, sl.get("certainty", "OPEN"), sl.get("evidence"), sid),
            )

        raw = json.dumps(obj, ensure_ascii=False, sort_keys=True)
        self.db.execute(
            "INSERT OR IGNORE INTO extraction_runs(source_id,model,schema_version,response_sha256,raw_json,usage_json,elapsed_seconds) VALUES(?,?,?,?,?,?,?)",
            (sid, meta.get("model"), SCHEMA_VERSION, _stable_hash(raw), raw, json.dumps(meta.get("usage"), ensure_ascii=False), meta.get("elapsed_seconds")),
        )
        self.db.commit()

    def export_graph(self) -> dict[str, Any]:
        nodes = []
        for r in self.db.execute("SELECT * FROM persons ORDER BY canonical_name,id"):
            aliases = [
                x[0]
                for x in self.db.execute(
                    "SELECT alias FROM aliases WHERE person_id=? ORDER BY alias", (r["id"],)
                )
            ]
            nodes.append(
                {"id": r["id"], "name": r["canonical_name"], "context": r["context"],
                 "resolution_status": r["resolution_status"], "certainty": r["certainty"], "aliases": aliases}
            )
        events = []
        for r in self.db.execute("SELECT * FROM events ORDER BY date_text,id"):
            item = dict(r)
            item["participants"] = [
                x[0]
                for x in self.db.execute(
                    "SELECT person_id FROM event_persons WHERE event_id=? ORDER BY person_id", (r["id"],)
                )
            ]
            events.append(item)
        edges = [
            dict(r)
            for r in self.db.execute(
                "SELECT id,source_person_id AS source,target_person_id AS target,relation_type,event_id,start_text,end_text,certainty,evidence,source_id FROM relations ORDER BY id"
            )
        ]
        slices = [
            dict(r)
            for r in self.db.execute(
                "SELECT id,person_id,slice_type,claim,event_id,certainty,evidence,source_id FROM slices ORDER BY person_id,slice_type,id"
            )
        ]
        sources = []
        for r in self.db.execute("SELECT id,provenance_json,row_sha256 FROM sources ORDER BY id"):
            sources.append(
                {"id": r["id"], "provenance": json.loads(r["provenance_json"]), "row_sha256": r["row_sha256"]}
            )
        return {
            "schema_version": SCHEMA_VERSION,
            "nodes": nodes,
            "edges": edges,
            "events": events,
            "slices": slices,
            "sources": sources,
        }


def run_build(args: argparse.Namespace) -> int:
    config = GatewayConfig.from_args(args)
    extractor = ChatExtractor(config)
    store = GraphStore(Path(args.db))
    processed = skipped = failed = 0
    try:
        for rec in iter_source_records([Path(p) for p in args.input]):
            if args.max_records and processed + failed >= args.max_records:
                break
            sid = store.source_id(rec)
            if not args.force and store.has_source_run(sid, config.model):
                skipped += 1
                continue
            try:
                obj, meta = extractor.extract(rec)
                store.ingest(rec, validate_extraction(obj), meta)
                processed += 1
                print(json.dumps({"status": "OK", "processed": processed, "source_id": sid}, ensure_ascii=False), flush=True)
            except Exception as exc:
                failed += 1
                print(json.dumps({"status": "ERROR", "source_id": sid, "error": repr(exc)}, ensure_ascii=False), file=sys.stderr, flush=True)
                if args.fail_fast:
                    raise
        graph = store.export_graph()
        Path(args.graph_json).write_text(json.dumps(graph, ensure_ascii=False, indent=2) + "\n", "utf-8")
    finally:
        store.close()
    print(
        json.dumps(
            {"status": "PASS" if failed == 0 else "PARTIAL", "processed": processed,
             "skipped": skipped, "failed": failed, "db": args.db, "graph_json": args.graph_json},
            ensure_ascii=False,
        )
    )
    return 0 if failed == 0 else 2


def run_export(args: argparse.Namespace) -> int:
    store = GraphStore(Path(args.db))
    try:
        graph = store.export_graph()
    finally:
        store.close()
    Path(args.graph_json).write_text(json.dumps(graph, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({"status": "PASS", "nodes": len(graph["nodes"]), "edges": len(graph["edges"]), "graph_json": args.graph_json}, ensure_ascii=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build", help="extract snippets through Sub2API/Kimi and update SQLite graph")
    b.add_argument("--input", nargs="+", required=True, help="Stage-2 result.json(.gz) or JSONL row-store")
    b.add_argument("--db", default="historical_person_graph.sqlite")
    b.add_argument("--graph-json", default="graph.json")
    b.add_argument("--base-url")
    b.add_argument("--api-key")
    b.add_argument("--model")
    b.add_argument("--chat-path", default="/v1/chat/completions")
    b.add_argument("--timeout", type=int, default=120)
    b.add_argument("--max-records", type=int, default=0)
    b.add_argument("--force", action="store_true")
    b.add_argument("--fail-fast", action="store_true")
    b.set_defaults(func=run_build)
    e = sub.add_parser("export", help="export an existing SQLite graph to UI JSON")
    e.add_argument("--db", default="historical_person_graph.sqlite")
    e.add_argument("--graph-json", default="graph.json")
    e.set_defaults(func=run_export)
    return ap


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
