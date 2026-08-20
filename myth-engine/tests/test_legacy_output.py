import json
import tempfile
import unittest
from pathlib import Path

from myth_engine.legacy import build_legacy_record, scan_export_directory, split_output_blocks


class LegacyOutputTests(unittest.TestCase):
    def test_blocks_and_labels_are_deterministic(self):
        text = """# Old research note

FACT: one-arm motif appears in source A.

HYPOTHESIS: this may connect to a half-body family.

TODO: verify the original page.
"""
        a = build_legacy_record(source={"source_path": "old.md"}, text=text, dictionary=["一臂", "half-body"])
        b = build_legacy_record(source={"source_path": "old.md"}, text=text, dictionary=["一臂", "half-body"])
        self.assertEqual(a["output_id"], b["output_id"])
        self.assertEqual(a["blocks"], b["blocks"])
        labels = [label for block in a["blocks"] for label in block["labels"]]
        self.assertIn("FACT", labels)
        self.assertIn("HYPOTHESIS", labels)
        self.assertIn("TODO", labels)
        self.assertEqual(a["source"]["artifact_kind"], "ANALYST_OUTPUT")
        self.assertEqual(a["source"]["epistemic_status"], "UNVERIFIED_LEGACY_OUTPUT")

    def test_unlabelled_output_never_becomes_source_fact(self):
        record = build_legacy_record(source={"source_path": "idea.txt"}, text="A strange old idea about dragons.")
        self.assertEqual(record["blocks"][0]["labels"], ["IDEA_CANDIDATE"])
        self.assertEqual(record["blocks"][0]["epistemic_status"], "UNVERIFIED_LEGACY_OUTPUT")

    def test_batch_scan_builds_index(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as out:
            srcp, outp = Path(src), Path(out)
            (srcp / "a.md").write_text("LOCK: keep this model.\n\nTODO: source-check it.", encoding="utf-8")
            (srcp / "b.txt").write_text("CONTRADICTION: version B differs.", encoding="utf-8")
            rows = scan_export_directory(srcp, outp, dictionary=["model", "version"])
            self.assertEqual(len(rows), 2)
            index_path = outp / "LEGACY_INDEX.jsonl"
            self.assertTrue(index_path.exists())
            index_rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual([r["source_path"] for r in index_rows], ["a.md", "b.txt"])
            for row in rows:
                manifest = json.loads((Path(row["bundle_path"]) / "manifest.json").read_text(encoding="utf-8"))
                self.assertEqual(manifest["epistemic_guard"], "ANALYST_OUTPUT_NEVER_COUNTS_AS_PRIMARY_SOURCE")

    def test_heading_is_its_own_block(self):
        blocks = split_output_blocks("# A\ntext one\n\n## B\ntext two")
        self.assertEqual(blocks[0], "# A")
        self.assertEqual(blocks[2], "## B")


if __name__ == "__main__":
    unittest.main()
