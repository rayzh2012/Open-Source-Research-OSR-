from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Iterable

from .core import canonical_text


@dataclass(frozen=True)
class Fingerprint:
    position: int
    value: int


def rolling_hashes(text: str, k: int = 12) -> list[Fingerprint]:
    """Return deterministic fixed-width fingerprints over canonical characters.

    This intentionally avoids tokenization and embeddings.  Hash collisions only
    generate candidates; callers can always re-check the underlying text.
    """
    s = canonical_text(text)
    if not s:
        return []
    if k <= 0:
        raise ValueError("k must be positive")
    if len(s) <= k:
        digest = hashlib.blake2b(s.encode("utf-8"), digest_size=8).digest()
        return [Fingerprint(0, int.from_bytes(digest, "big"))]
    out: list[Fingerprint] = []
    for i in range(len(s) - k + 1):
        chunk = s[i : i + k]
        digest = hashlib.blake2b(chunk.encode("utf-8"), digest_size=8).digest()
        out.append(Fingerprint(i, int.from_bytes(digest, "big")))
    return out


def winnow_fingerprints(text: str, k: int = 12, window: int = 8) -> list[Fingerprint]:
    """Winnow rolling hashes by selecting the right-most minimum in each window."""
    hashes = rolling_hashes(text, k=k)
    if not hashes:
        return []
    if window <= 0:
        raise ValueError("window must be positive")
    if len(hashes) <= window:
        minimum = min(fp.value for fp in hashes)
        for fp in reversed(hashes):
            if fp.value == minimum:
                return [fp]
    selected: list[Fingerprint] = []
    last_position = -1
    for start in range(len(hashes) - window + 1):
        chunk = hashes[start : start + window]
        minimum = min(fp.value for fp in chunk)
        chosen = next(fp for fp in reversed(chunk) if fp.value == minimum)
        if chosen.position != last_position:
            selected.append(chosen)
            last_position = chosen.position
    return selected


def fingerprint_values(text: str, k: int = 12, window: int = 8) -> set[int]:
    return {fp.value for fp in winnow_fingerprints(text, k=k, window=window)}


def fingerprint_jaccard(left: str, right: str, k: int = 12, window: int = 8) -> float:
    a = fingerprint_values(left, k=k, window=window)
    b = fingerprint_values(right, k=k, window=window)
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def ordered_segment_alignment(
    left_segments: Iterable[str],
    right_segments: Iterable[str],
    *,
    k: int = 8,
    window: int = 5,
    min_similarity: float = 0.15,
    gap_penalty: float = 0.05,
) -> list[dict[str, float | int]]:
    """Order-preserving dynamic-programming alignment of paragraph-like segments.

    Similarity is deterministic winnowing Jaccard.  The algorithm does not force a
    match when a pair is weak, so insertions/deletions remain visible.
    """
    left = list(left_segments)
    right = list(right_segments)
    n, m = len(left), len(right)
    sim = [[fingerprint_jaccard(left[i], right[j], k=k, window=window) for j in range(m)] for i in range(n)]
    dp = [[0.0] * (m + 1) for _ in range(n + 1)]
    choice = [[""] * (m + 1) for _ in range(n + 1)]

    for i in range(1, n + 1):
        dp[i][0] = dp[i - 1][0] - gap_penalty
        choice[i][0] = "U"
    for j in range(1, m + 1):
        dp[0][j] = dp[0][j - 1] - gap_penalty
        choice[0][j] = "L"

    for i in range(1, n + 1):
        for j in range(1, m + 1):
            s = sim[i - 1][j - 1]
            diag = dp[i - 1][j - 1] + (s if s >= min_similarity else -gap_penalty)
            up = dp[i - 1][j] - gap_penalty
            left_score = dp[i][j - 1] - gap_penalty
            best = max(diag, up, left_score)
            dp[i][j] = best
            choice[i][j] = "D" if best == diag else ("U" if best == up else "L")

    matches: list[dict[str, float | int]] = []
    i, j = n, m
    while i > 0 or j > 0:
        move = choice[i][j]
        if move == "D":
            s = sim[i - 1][j - 1]
            if s >= min_similarity:
                matches.append({"left_ordinal": i - 1, "right_ordinal": j - 1, "score": s})
            i -= 1
            j -= 1
        elif move == "U":
            i -= 1
        elif move == "L":
            j -= 1
        else:
            break
    matches.reverse()
    return matches
