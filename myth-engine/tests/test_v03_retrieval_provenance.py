import unittest

from myth_engine.acquisition import join_archive_records, parse_archive_manifest, source_stub
from myth_engine.fingerprints import fingerprint_jaccard, ordered_segment_alignment, winnow_fingerprints
from myth_engine.provenance import compare_provenance, internal_provenance_conflicts, slot_mutation_report


class ArchiveBridgeTests(unittest.TestCase):
    def test_manifest_results_join_never_invents_success(self):
        manifest = (
            "source_id\turl\tfilename\n"
            "a\thttps://example.org/a.pdf\ta.pdf\n"
            "b\thttps://example.org/b.pdf\tb.pdf\n"
        )
        results = (
            "source_id\tstatus\tfilename\tsize_bytes\tsha256\tsource_url\n"
            "a\tOK_PDF\ta.pdf\t123\tabc123\thttps://example.org/a.pdf\n"
            "b\tDOWNLOAD_FAILED\tb.pdf\t\t\thttps://example.org/b.pdf\n"
        )
        rows = join_archive_records(manifest, results)
        self.assertEqual(rows[0]["acquisition_status"], "ACQUIRED_VERIFIED_BY_BRIDGE")
        self.assertEqual(rows[0]["source_sha256"], "abc123")
        self.assertEqual(rows[1]["acquisition_status"], "DOWNLOAD_FAILED")
        self.assertIsNone(rows[1]["source_sha256"])
        stub = source_stub(rows[0], collection="TBG")
        self.assertFalse(stub["raw_source_committed"])
        self.assertEqual(stub["collection"], "TBG")

    def test_duplicate_source_id_is_rejected(self):
        text = "source_id\turl\tfilename\na\tu\tf\na\tu2\tf2\n"
        with self.assertRaises(ValueError):
            parse_archive_manifest(text)


class FingerprintTests(unittest.TestCase):
    def test_winnowing_is_deterministic_and_nonempty(self):
        text = "十二个妻子拔下七根头发搓成绳子勒住脖子"
        a = winnow_fingerprints(text, k=4, window=3)
        b = winnow_fingerprints(text, k=4, window=3)
        self.assertEqual(a, b)
        self.assertTrue(a)

    def test_near_copy_similarity_and_ordered_alignment(self):
        left = [
            "妻子拔下七根头发搓成绳子勒住脖子",
            "头落地以后喷出火来",
            "她们每天轮换并用水清洗头颅",
        ]
        right = [
            "这是一个新增的开头段落",
            "妻子拔下七根头发搓成绳子勒住脖子",
            "头落到地面以后喷出火来",
            "她们每天轮换并用水清洗头颅",
        ]
        self.assertGreater(fingerprint_jaccard(left[0], right[1], k=4, window=3), 0.95)
        aligned = ordered_segment_alignment(left, right, k=4, window=3, min_similarity=0.15)
        pairs = [(x["left_ordinal"], x["right_ordinal"]) for x in aligned]
        self.assertIn((0, 1), pairs)
        self.assertIn((2, 3), pairs)
        self.assertEqual(pairs, sorted(pairs))


class ProvenanceTests(unittest.TestCase):
    def test_geographic_relabel_can_raise_pseudoreplication_alert(self):
        left = {
            "collector": "林木",
            "narrator": "岩林",
            "collection_location": "德宏州",
        }
        right = {
            "collector": "Lin Mu",
            "publication_section_label": "西双版纳",
        }
        report = compare_provenance(
            left,
            right,
            text_similarity=0.96,
            rare_sequence_overlap=1.0,
            alias_map={"Lin Mu": "林木"},
        )
        self.assertTrue(report["same_collector"])
        self.assertTrue(report["publication_relabel"])
        self.assertEqual(report["alerts"][0]["type"], "PSEUDOREPLICATION_ALERT")
        self.assertEqual(report["alerts"][0]["severity"], "HIGH")

    def test_internal_geography_slots_stay_separate(self):
        conflicts = internal_provenance_conflicts(
            {"collection_location": "德宏州", "publication_section_label": "西双版纳"}
        )
        self.assertEqual(conflicts[0]["type"], "GEOGRAPHY_SLOT_CONFLICT")

    def test_slot_mutation_report_exposes_number_and_species_changes(self):
        left = [
            {"predicate": "HAIR_WEAPON", "payload": {"hair_owner": "male_target", "hair_count": 1}},
            {"predicate": "DECAPITATE", "payload": {}},
        ]
        right = [
            {"predicate": "HAIR_WEAPON", "payload": {"hair_owner": "wives", "hair_count_per_wife": 7}},
            {"predicate": "DECAPITATE", "payload": {}},
            {"predicate": "GRAFT_HEAD", "payload": {"species": ["buffalo", "elephant", "dragon", "monkey"]}},
        ]
        report = slot_mutation_report(left, right)
        self.assertIn("GRAFT_HEAD", report["added"])
        hair = next(x for x in report["changed"] if x["predicate"] == "HAIR_WEAPON")
        self.assertEqual(hair["slot_delta"]["hair_owner"]["left"], "male_target")
        self.assertEqual(hair["slot_delta"]["hair_owner"]["right"], "wives")


if __name__ == "__main__":
    unittest.main()
