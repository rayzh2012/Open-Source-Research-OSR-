import os
import tempfile
import unittest
from pathlib import Path

from myth_engine.core import MythDB
from myth_engine.pipeline import batch_ingest, build_witness_bundle, ingest_bundle, verify_bundle


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        fd, self.db_path = tempfile.mkstemp(suffix=".sqlite", dir=self.tmp.name)
        os.close(fd)
        self.db = MythDB(self.db_path)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_build_verify_and_ingest_bundle(self):
        bundle = self.root / "w1"
        manifest = build_witness_bundle(
            source={"title": "synthetic", "collection_location": "test"},
            text="第一段有一臂一足。\n\n第二段发生断头与复活。",
            output_dir=bundle,
            include_raw=False,
        )
        self.assertFalse(manifest["raw_included"])
        self.assertFalse((bundle / "raw.txt").exists())
        self.assertTrue(verify_bundle(bundle)["ok"])

        wid = ingest_bundle(self.db, bundle)
        witness = self.db.witness(wid)
        self.assertIsNotNone(witness)
        self.assertEqual(witness["metadata"]["title"], "synthetic")
        self.assertEqual(witness["metadata"]["artifact_merkle_root"], manifest["merkle_root"])
        self.assertTrue(self.db.search_phrase("一臂一足"))

    def test_tamper_detection(self):
        bundle = self.root / "w2"
        build_witness_bundle(
            source={"title": "tamper-test"},
            text="甲段。\n\n乙段。",
            output_dir=bundle,
        )
        (bundle / "normalized.txt").write_text("内容被修改。\n", encoding="utf-8")
        report = verify_bundle(bundle)
        self.assertFalse(report["ok"])
        self.assertIn("doc_hash_mismatch", report["errors"])
        with self.assertRaises(ValueError):
            ingest_bundle(self.db, bundle)

    def test_batch_ingest_is_deterministic(self):
        for name, text in [("b", "第二份。"), ("a", "第一份。")]:
            build_witness_bundle(
                source={"title": name},
                text=text,
                output_dir=self.root / "corpus" / name,
            )
        rows = batch_ingest(self.db, self.root / "corpus")
        self.assertEqual([Path(path).name for path, _ in rows], ["a", "b"])
        self.assertEqual(len(rows), 2)


if __name__ == "__main__":
    unittest.main()
