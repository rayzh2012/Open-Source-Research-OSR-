from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import unicodedata
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


_WS = re.compile(r"\s+")
_PUNCT_OR_SPACE = re.compile(r"[^0-9A-Za-z\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af]+")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def normalize_text(text: str) -> str:
    """Conservative normalization: Unicode NFKC + whitespace collapse."""
    text = unicodedata.normalize("NFKC", text)
    return _WS.sub(" ", text).strip()


def canonical_text(text: str) -> str:
    """Search canonicalization that keeps letters, digits and CJK/Kana/Hangul."""
    return _PUNCT_OR_SPACE.sub("", normalize_text(text).lower())


def paragraphs(text: str) -> list[str]:
    # Prefer blank-line paragraph boundaries; fall back to non-empty lines.
    chunks = [normalize_text(x) for x in re.split(r"\n\s*\n", text) if normalize_text(x)]
    if len(chunks) <= 1:
        chunks = [normalize_text(x) for x in text.splitlines() if normalize_text(x)]
    return chunks or [normalize_text(text)]


def qgrams(text: str, q: int = 3) -> set[str]:
    s = canonical_text(text)
    if not s:
        return set()
    if len(s) <= q:
        return {s}
    return {s[i : i + q] for i in range(len(s) - q + 1)}


def gram_hash(gram: str) -> str:
    # 64-bit textual fingerprint is enough for candidate indexing; exact text is rechecked.
    return hashlib.blake2b(gram.encode("utf-8"), digest_size=8).hexdigest()


def merkle_root(leaves: Iterable[str]) -> str:
    level = list(leaves)
    if not level:
        return sha256_text("")
    while len(level) > 1:
        if len(level) % 2:
            level.append(level[-1])
        level = [sha256_text(level[i] + level[i + 1]) for i in range(0, len(level), 2)]
    return level[0]


class KeywordAutomaton:
    """Small Aho-Corasick automaton for deterministic batch dictionary scans."""

    def __init__(self, keywords: Iterable[str]):
        self.next: list[dict[str, int]] = [{}]
        self.fail: list[int] = [0]
        self.out: list[list[str]] = [[]]
        for raw in keywords:
            kw = canonical_text(raw)
            if kw:
                self._insert(kw, raw)
        self._build_failures()

    def _insert(self, key: str, original: str) -> None:
        state = 0
        for ch in key:
            if ch not in self.next[state]:
                self.next[state][ch] = len(self.next)
                self.next.append({})
                self.fail.append(0)
                self.out.append([])
            state = self.next[state][ch]
        self.out[state].append(original)

    def _build_failures(self) -> None:
        q: deque[int] = deque()
        for nxt in self.next[0].values():
            q.append(nxt)
            self.fail[nxt] = 0
        while q:
            r = q.popleft()
            for ch, s in self.next[r].items():
                q.append(s)
                f = self.fail[r]
                while f and ch not in self.next[f]:
                    f = self.fail[f]
                self.fail[s] = self.next[f].get(ch, 0)
                self.out[s].extend(self.out[self.fail[s]])

    def scan(self, text: str) -> list[tuple[int, str]]:
        s = canonical_text(text)
        state = 0
        hits: list[tuple[int, str]] = []
        for i, ch in enumerate(s):
            while state and ch not in self.next[state]:
                state = self.fail[state]
            state = self.next[state].get(ch, 0)
            for kw in self.out[state]:
                hits.append((i, kw))
        return hits


@dataclass(frozen=True)
class SearchHit:
    witness_id: str
    segment_id: str
    ordinal: int
    text: str
    score: float


class MythDB:
    def __init__(self, path: str | Path):
        self.path = str(path)
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self._init_schema()

    def close(self) -> None:
        self.db.close()

    def _init_schema(self) -> None:
        self.db.executescript(
            """
            PRAGMA journal_mode=WAL;
            PRAGMA foreign_keys=ON;

            CREATE TABLE IF NOT EXISTS witness (
                witness_id TEXT PRIMARY KEY,
                doc_hash TEXT NOT NULL,
                merkle_root TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                normalized_text TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS segment (
                segment_id TEXT PRIMARY KEY,
                witness_id TEXT NOT NULL REFERENCES witness(witness_id),
                ordinal INTEGER NOT NULL,
                segment_hash TEXT NOT NULL,
                text TEXT NOT NULL,
                canonical TEXT NOT NULL,
                UNIQUE(witness_id, ordinal)
            );
            CREATE INDEX IF NOT EXISTS idx_segment_hash ON segment(segment_hash);
            CREATE INDEX IF NOT EXISTS idx_segment_witness ON segment(witness_id, ordinal);

            CREATE TABLE IF NOT EXISTS gram (
                gram_hash TEXT NOT NULL,
                segment_id TEXT NOT NULL REFERENCES segment(segment_id),
                PRIMARY KEY (gram_hash, segment_id)
            );
            CREATE INDEX IF NOT EXISTS idx_gram_segment ON gram(segment_id);

            CREATE TABLE IF NOT EXISTS semantic_version (
                semantic_version TEXT PRIMARY KEY,
                parent_version TEXT,
                config_hash TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS event (
                event_id TEXT PRIMARY KEY,
                witness_id TEXT NOT NULL REFERENCES witness(witness_id),
                segment_id TEXT REFERENCES segment(segment_id),
                ordinal INTEGER NOT NULL,
                semantic_version TEXT NOT NULL REFERENCES semantic_version(semantic_version),
                predicate TEXT NOT NULL,
                actor TEXT,
                patient TEXT,
                state_before TEXT,
                state_after TEXT,
                tags_json TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                event_hash TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_event_predicate ON event(predicate);
            CREATE INDEX IF NOT EXISTS idx_event_semver ON event(semantic_version);

            CREATE TABLE IF NOT EXISTS edge (
                src TEXT NOT NULL,
                dst TEXT NOT NULL,
                edge_type TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 1.0,
                provenance_json TEXT NOT NULL DEFAULT '{}',
                PRIMARY KEY(src, dst, edge_type)
            );
            CREATE INDEX IF NOT EXISTS idx_edge_src ON edge(src);
            CREATE INDEX IF NOT EXISTS idx_edge_dst ON edge(dst);
            """
        )
        self.db.commit()

    def add_witness(self, metadata: dict[str, Any], text: str) -> str:
        norm = normalize_text(text)
        doc_hash = sha256_text(norm)
        meta_key = stable_json(metadata)
        witness_id = sha256_text(doc_hash + "|" + meta_key)
        parts = paragraphs(text)
        seg_hashes = [sha256_text(normalize_text(p)) for p in parts]
        root = merkle_root(seg_hashes)

        self.db.execute(
            "INSERT OR IGNORE INTO witness VALUES (?, ?, ?, ?, ?)",
            (witness_id, doc_hash, root, meta_key, norm),
        )
        for i, p in enumerate(parts):
            pnorm = normalize_text(p)
            phash = sha256_text(pnorm)
            segment_id = sha256_text(witness_id + f"|{i}|" + phash)
            self.db.execute(
                "INSERT OR IGNORE INTO segment VALUES (?, ?, ?, ?, ?, ?)",
                (segment_id, witness_id, i, phash, pnorm, canonical_text(pnorm)),
            )
            rows = [(gram_hash(g), segment_id) for g in qgrams(pnorm)]
            self.db.executemany("INSERT OR IGNORE INTO gram VALUES (?, ?)", rows)
        self.db.commit()
        return witness_id

    def witness(self, witness_id: str) -> dict[str, Any] | None:
        row = self.db.execute("SELECT * FROM witness WHERE witness_id=?", (witness_id,)).fetchone()
        if not row:
            return None
        return {
            "witness_id": row["witness_id"],
            "doc_hash": row["doc_hash"],
            "merkle_root": row["merkle_root"],
            "metadata": json.loads(row["metadata_json"]),
        }

    def exact_segment_hash(self, segment_hash: str) -> list[SearchHit]:
        rows = self.db.execute(
            "SELECT witness_id, segment_id, ordinal, text FROM segment WHERE segment_hash=?",
            (segment_hash,),
        ).fetchall()
        return [SearchHit(r["witness_id"], r["segment_id"], r["ordinal"], r["text"], 1.0) for r in rows]

    def search_phrase(self, phrase: str, limit: int = 50) -> list[SearchHit]:
        needle = canonical_text(phrase)
        if not needle:
            return []
        grams = sorted(qgrams(needle))
        candidates: list[sqlite3.Row]
        if len(needle) < 3 or not grams:
            candidates = self.db.execute(
                "SELECT witness_id, segment_id, ordinal, text, canonical FROM segment WHERE canonical LIKE ? LIMIT ?",
                (f"%{needle}%", limit),
            ).fetchall()
        else:
            hashes = [gram_hash(g) for g in grams]
            placeholders = ",".join("?" for _ in hashes)
            sql = f"""
                SELECT s.witness_id, s.segment_id, s.ordinal, s.text, s.canonical,
                       COUNT(DISTINCT g.gram_hash) AS overlap
                FROM gram g JOIN segment s ON s.segment_id=g.segment_id
                WHERE g.gram_hash IN ({placeholders})
                GROUP BY s.segment_id
                HAVING overlap=?
                LIMIT ?
            """
            candidates = self.db.execute(sql, (*hashes, len(hashes), limit * 4)).fetchall()
        hits = [
            SearchHit(r["witness_id"], r["segment_id"], r["ordinal"], r["text"], 1.0)
            for r in candidates
            if needle in r["canonical"]
        ]
        return hits[:limit]

    def search_fuzzy(self, query: str, limit: int = 20, candidate_limit: int = 200) -> list[SearchHit]:
        query_grams = qgrams(query)
        if not query_grams:
            return []
        hashes = [gram_hash(g) for g in query_grams]
        placeholders = ",".join("?" for _ in hashes)
        rows = self.db.execute(
            f"""
            SELECT s.witness_id, s.segment_id, s.ordinal, s.text, s.canonical,
                   COUNT(DISTINCT g.gram_hash) AS overlap
            FROM gram g JOIN segment s ON s.segment_id=g.segment_id
            WHERE g.gram_hash IN ({placeholders})
            GROUP BY s.segment_id
            ORDER BY overlap DESC
            LIMIT ?
            """,
            (*hashes, candidate_limit),
        ).fetchall()
        out: list[SearchHit] = []
        for r in rows:
            sg = qgrams(r["canonical"])
            union = query_grams | sg
            score = len(query_grams & sg) / len(union) if union else 0.0
            out.append(SearchHit(r["witness_id"], r["segment_id"], r["ordinal"], r["text"], score))
        out.sort(key=lambda x: (-x.score, x.witness_id, x.ordinal))
        return out[:limit]

    def dictionary_scan(self, keywords: Iterable[str], limit_per_keyword: int = 100) -> dict[str, list[SearchHit]]:
        automaton = KeywordAutomaton(keywords)
        result: dict[str, list[SearchHit]] = {k: [] for k in keywords}
        for r in self.db.execute("SELECT witness_id, segment_id, ordinal, text FROM segment"):
            seen: set[str] = set()
            for _, kw in automaton.scan(r["text"]):
                if kw in seen or len(result.setdefault(kw, [])) >= limit_per_keyword:
                    continue
                seen.add(kw)
                result[kw].append(SearchHit(r["witness_id"], r["segment_id"], r["ordinal"], r["text"], 1.0))
        return result

    def add_semantic_version(self, name: str, config: dict[str, Any], parent: str | None = None, description: str = "") -> str:
        config_hash = sha256_text(stable_json(config))
        self.db.execute(
            "INSERT OR REPLACE INTO semantic_version VALUES (?, ?, ?, ?)",
            (name, parent, config_hash, description),
        )
        self.db.commit()
        return config_hash

    def add_event(
        self,
        *,
        witness_id: str,
        semantic_version: str,
        ordinal: int,
        predicate: str,
        actor: str | None = None,
        patient: str | None = None,
        segment_id: str | None = None,
        state_before: dict[str, Any] | None = None,
        state_after: dict[str, Any] | None = None,
        tags: list[str] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> str:
        event_obj = {
            "witness_id": witness_id,
            "semantic_version": semantic_version,
            "ordinal": ordinal,
            "predicate": predicate,
            "actor": actor,
            "patient": patient,
            "segment_id": segment_id,
            "state_before": state_before or {},
            "state_after": state_after or {},
            "tags": sorted(tags or []),
            "payload": payload or {},
        }
        event_hash = sha256_text(stable_json(event_obj))
        event_id = event_hash
        self.db.execute(
            """
            INSERT OR REPLACE INTO event
            (event_id,witness_id,segment_id,ordinal,semantic_version,predicate,actor,patient,
             state_before,state_after,tags_json,payload_json,event_hash)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                event_id,
                witness_id,
                segment_id,
                ordinal,
                semantic_version,
                predicate,
                actor,
                patient,
                stable_json(state_before or {}),
                stable_json(state_after or {}),
                stable_json(sorted(tags or [])),
                stable_json(payload or {}),
                event_hash,
            ),
        )
        self.db.commit()
        return event_id

    def search_events(self, predicate: str | None = None, semantic_version: str | None = None) -> list[dict[str, Any]]:
        clauses, params = [], []
        if predicate is not None:
            clauses.append("predicate=?")
            params.append(predicate)
        if semantic_version is not None:
            clauses.append("semantic_version=?")
            params.append(semantic_version)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        rows = self.db.execute("SELECT * FROM event" + where + " ORDER BY witness_id, ordinal", params).fetchall()
        return [dict(r) for r in rows]

    def add_edge(self, src: str, dst: str, edge_type: str, confidence: float = 1.0, provenance: dict[str, Any] | None = None) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO edge VALUES (?, ?, ?, ?, ?)",
            (src, dst, edge_type, confidence, stable_json(provenance or {})),
        )
        self.db.commit()

    def bfs(self, start: str, max_depth: int = 3, edge_type: str | None = None) -> list[tuple[str, int]]:
        q: deque[tuple[str, int]] = deque([(start, 0)])
        seen = {start}
        out: list[tuple[str, int]] = []
        while q:
            node, depth = q.popleft()
            out.append((node, depth))
            if depth >= max_depth:
                continue
            sql = "SELECT dst FROM edge WHERE src=?"
            params: list[Any] = [node]
            if edge_type:
                sql += " AND edge_type=?"
                params.append(edge_type)
            for r in self.db.execute(sql, params):
                nxt = r["dst"]
                if nxt not in seen:
                    seen.add(nxt)
                    q.append((nxt, depth + 1))
        return out

    def dfs(self, start: str, edge_type: str | None = None) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []

        def visit(node: str) -> None:
            if node in seen:
                return
            seen.add(node)
            out.append(node)
            sql = "SELECT dst FROM edge WHERE src=?"
            params: list[Any] = [node]
            if edge_type:
                sql += " AND edge_type=?"
                params.append(edge_type)
            for r in self.db.execute(sql, params):
                visit(r["dst"])

        visit(start)
        return out

    def compare_witnesses(self, left: str, right: str) -> dict[str, Any]:
        def segs(wid: str) -> list[sqlite3.Row]:
            return self.db.execute(
                "SELECT ordinal,segment_hash,text,canonical FROM segment WHERE witness_id=? ORDER BY ordinal",
                (wid,),
            ).fetchall()

        a, b = segs(left), segs(right)
        ah, bh = {x["segment_hash"] for x in a}, {x["segment_hash"] for x in b}
        exact = len(ah & bh)
        denom = len(ah | bh) or 1
        # Whole-witness fuzzy score uses q-gram Jaccard, still deterministic and non-vector.
        ag = qgrams(" ".join(x["canonical"] for x in a))
        bg = qgrams(" ".join(x["canonical"] for x in b))
        gunion = ag | bg
        return {
            "left": left,
            "right": right,
            "exact_segment_jaccard": exact / denom,
            "qgram_jaccard": len(ag & bg) / len(gunion) if gunion else 0.0,
            "left_segments": len(a),
            "right_segments": len(b),
            "left_merkle_root": self.witness(left)["merkle_root"] if self.witness(left) else None,
            "right_merkle_root": self.witness(right)["merkle_root"] if self.witness(right) else None,
        }
