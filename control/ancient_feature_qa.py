#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pyarrow.parquet as pq

# These are smoke expectations, not completeness claims. They are intentionally broad and conservative.
EXPECTATIONS = {
    "perseus-greek": {"min_signal_rows": 1, "families_any": ["greek_deity", "ritual_concept", "comparative_motif", "natural_deity_concept"]},
    "perseus-latin": {"min_signal_rows": 1, "families_any": ["ritual_concept", "comparative_motif", "natural_deity_concept", "creature_concept"]},
    "gretil-sanskrit": {"min_signal_rows": 1, "families_any": ["indic_deity", "ritual_concept", "religion_concept", "creature_concept"]},
    "sarit-indic": {"min_signal_rows": 1, "families_any": ["indic_deity", "ritual_concept", "religion_concept", "creature_concept"]},
    "dcs-sanskrit": {"min_signal_rows": 1, "families_any": ["indic_deity", "ritual_concept", "religion_concept", "creature_concept"]},
    "pali-vri-corpus": {"min_signal_rows": 1, "families_any": ["ritual_concept", "religion_concept", "creature_concept", "comparative_motif"]},
    "kr5-daoist-corpus": {"min_signal_rows": 1, "families_any": ["chinese_mythic_entity", "ritual_concept", "religion_concept", "natural_deity_concept"]},
    "cbeta-esoteric-corpus": {"min_signal_rows": 1, "families_any": ["ritual_concept", "religion_concept", "creature_concept", "comparative_motif"]},
    "cbeta-xml-p5": {"min_signal_rows": 1, "families_any": ["ritual_concept", "religion_concept", "creature_concept", "comparative_motif"]},
}


def read_records(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return pq.read_table(path).to_pylist()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--result", required=True)
    ap.add_argument("--feature-totals", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    result = json.loads(Path(args.result).read_text("utf-8"))
    corpus = result.get("corpus", "")
    totals = read_records(Path(args.feature_totals))
    positive = [
        r for r in totals
        if int(r.get("occurrences") or 0) > 0 or int(r.get("rows_with_feature") or 0) > 0
    ]
    positive_families = sorted({str(r.get("family") or "") for r in positive if r.get("family")})
    positive_features = sorted(str(r.get("feature_id") or "") for r in positive)
    density = int(result.get("signal_rows", 0)) / max(1, int(result.get("rows_nonempty", 0)))

    expectation = EXPECTATIONS.get(corpus)
    failures = []
    if expectation:
        if int(result.get("signal_rows", 0)) < int(expectation["min_signal_rows"]):
            failures.append(f"signal_rows<{expectation['min_signal_rows']}")
        if not set(expectation["families_any"]).intersection(positive_families):
            failures.append("no_expected_family_hit")

    qa = {
        "format": "osr-ancient-feature-qa/v1.1",
        "corpus": corpus,
        "logical_key": result.get("logical_key"),
        "source_parquet_sha256": result.get("source_parquet_sha256"),
        "feature_schema_sha256": result.get("feature_schema_sha256"),
        "rows": int(result.get("rows", 0)),
        "rows_nonempty": int(result.get("rows_nonempty", 0)),
        "signal_rows": int(result.get("signal_rows", 0)),
        "signal_density": density,
        "positive_feature_count": len(positive_features),
        "positive_families": positive_families,
        "positive_features": positive_features,
        "expectation_applied": expectation is not None,
        "expected_families_any": expectation["families_any"] if expectation else [],
        "status": "PASS" if not failures else "FAIL",
        "failures": failures,
        "interpretation": "Smoke QA only; lexical density is not evidence of identity, common origin, borrowing, or historical dependence.",
    }
    Path(args.output).write_text(json.dumps(qa, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps(qa, ensure_ascii=False))
    return 0 if not failures else 4


if __name__ == "__main__":
    raise SystemExit(main())
