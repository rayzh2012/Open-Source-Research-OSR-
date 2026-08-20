from __future__ import annotations

from typing import Any

from .core import MythDB
from .fingerprints import fingerprint_jaccard, winnow_fingerprints


def _fp_hex(value: int) -> str:
    return f"{value:016x}"


def ensure_fingerprint_schema(db: MythDB) -> None:
    db.db.executescript(
        """
        CREATE TABLE IF NOT EXISTS fingerprint_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS fingerprint (
            fingerprint TEXT NOT NULL,
            segment_id TEXT NOT NULL REFERENCES segment(segment_id),
            PRIMARY KEY (fingerprint, segment_id)
        );
        CREATE INDEX IF NOT EXISTS idx_fingerprint_segment ON fingerprint(segment_id);
        """
    )
    db.db.commit()


def rebuild_fingerprint_index(db: MythDB, *, k: int = 12, window: int = 8) -> dict[str, int]:
    """Rebuild the deterministic persistent fingerprint index for all segments."""
    ensure_fingerprint_schema(db)
    db.db.execute("DELETE FROM fingerprint")
    db.db.execute("INSERT OR REPLACE INTO fingerprint_meta VALUES ('k', ?)", (str(k),))
    db.db.execute("INSERT OR REPLACE INTO fingerprint_meta VALUES ('window', ?)", (str(window),))
    segments = 0
    fingerprints = 0
    rows = db.db.execute("SELECT segment_id, text FROM segment ORDER BY segment_id").fetchall()
    for row in rows:
        segments += 1
        values = sorted({_fp_hex(fp.value) for fp in winnow_fingerprints(row["text"], k=k, window=window)})
        db.db.executemany(
            "INSERT OR IGNORE INTO fingerprint (fingerprint, segment_id) VALUES (?, ?)",
            [(value, row["segment_id"]) for value in values],
        )
        fingerprints += len(values)
    db.db.commit()
    return {"segments": segments, "fingerprints": fingerprints}


def fingerprint_config(db: MythDB) -> tuple[int, int]:
    ensure_fingerprint_schema(db)
    rows = {r["key"]: r["value"] for r in db.db.execute("SELECT key, value FROM fingerprint_meta")}
    if "k" not in rows or "window" not in rows:
        raise ValueError("fingerprint index has not been built")
    return int(rows["k"]), int(rows["window"])


def search_fingerprint_candidates(
    db: MythDB,
    query: str,
    *,
    limit: int = 20,
    candidate_limit: int = 200,
    min_shared: int = 1,
) -> list[dict[str, Any]]:
    """Search the persistent fingerprint inverted table, then exact-recheck Jaccard."""
    k, window = fingerprint_config(db)
    query_values = sorted({_fp_hex(fp.value) for fp in winnow_fingerprints(query, k=k, window=window)})
    if not query_values:
        return []
    placeholders = ",".join("?" for _ in query_values)
    rows = db.db.execute(
        f"""
        SELECT s.witness_id, s.segment_id, s.ordinal, s.text,
               COUNT(DISTINCT f.fingerprint) AS shared
        FROM fingerprint f
        JOIN segment s ON s.segment_id=f.segment_id
        WHERE f.fingerprint IN ({placeholders})
        GROUP BY s.segment_id
        HAVING shared >= ?
        ORDER BY shared DESC, s.witness_id, s.ordinal
        LIMIT ?
        """,
        (*query_values, min_shared, candidate_limit),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        score = fingerprint_jaccard(query, row["text"], k=k, window=window)
        out.append(
            {
                "witness_id": row["witness_id"],
                "segment_id": row["segment_id"],
                "ordinal": row["ordinal"],
                "text": row["text"],
                "shared_fingerprints": row["shared"],
                "fingerprint_jaccard": score,
            }
        )
    out.sort(key=lambda x: (-float(x["fingerprint_jaccard"]), -int(x["shared_fingerprints"]), str(x["segment_id"])))
    return out[:limit]
