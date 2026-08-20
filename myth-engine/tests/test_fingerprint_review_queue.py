import os
import tempfile
import unittest

from myth_engine.core import MythDB
from myth_engine.fingerprint_index import rebuild_fingerprint_index, search_fingerprint_candidates
from myth_engine.legacy import build_legacy_record
from myth_engine.review_queue import apply_audited_resolution, build_legacy_review_queue


class FingerprintReviewQueueTests(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".sqlite")
        os.close(fd)
        self.db = MythDB(self.path)

    def tearDown(self):
        self.db.close()
        os.unlink(self.path)

    def test_persistent_index_finds_long_near_copy(self):
        wid = self.db.add_witness(
            {"title": "source", "source_layer": "PRIMARY_TEXT"},
            "妻子拔下七根头发搓成绳子勒住脖子。\n\n头落地以后喷出火来。",
        )
        stats = rebuild_fingerprint_index(self.db, k=4, window=3)
        self.assertGreater(stats["fingerprints"], 0)
        hits = search_fingerprint_candidates(self.db, "旧笔记：妻子拔下七根头发搓成绳子勒住脖子", limit=5)
        self.assertTrue(hits)
        self.assertEqual(hits[0]["witness_id"], wid)
        self.assertGreater(hits[0]["fingerprint_jaccard"], 0.3)

    def test_legacy_output_routes_to_source_candidate_without_auto_verdict(self):
        self.db.add_witness(
            {"title": "field source", "source_layer": "FIELD_COLLECTION"},
            "有十二个妻子，她们拔下七根头发搓成绳子，勒下丈夫的头。",
        )
        rebuild_fingerprint_index(self.db, k=4, window=3)
        legacy = build_legacy_record(
            source={"source_path": "old-output.md"},
            text="HYPOTHESIS: 十二个妻子拔七根头发搓成绳子勒下丈夫的头。",
        )
        queue = build_legacy_review_queue(self.db, legacy, min_score=0.1)
        self.assertEqual(queue[0]["resolution_status"], "UNRESOLVED_CANDIDATES")
        self.assertTrue(queue[0]["candidate_segments"])
        self.assertEqual(queue[0]["guard"], "TEXT_SIMILARITY_IS_NOT_EVIDENCE_VERDICT")

    def test_resolution_requires_explicit_evidence_segment(self):
        item = {
            "output_id": "o",
            "block_id": "b",
            "resolution_status": "UNRESOLVED_CANDIDATES",
            "candidate_segments": [],
        }
        with self.assertRaises(ValueError):
            apply_audited_resolution(item, verdict="SUPPORTED", evidence_segment_ids=[], reviewer="test")
        resolved = apply_audited_resolution(
            item,
            verdict="SUPPORTED",
            evidence_segment_ids=["segment-123"],
            reviewer="test",
            note="original page checked",
        )
        self.assertEqual(resolved["resolution_status"], "SUPPORTED")
        self.assertEqual(resolved["evidence_segment_ids"], ["segment-123"])


if __name__ == "__main__":
    unittest.main()
