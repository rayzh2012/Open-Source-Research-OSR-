import json
import os
import tempfile
import unittest
from pathlib import Path

from myth_engine.benchmark import compare_fixture_pair, ingest_fixture
from myth_engine.core import MythDB


FIXTURE_PATH = Path(__file__).resolve().parents[1] / "benchmarks" / "yunnan-songkran" / "fixtures.json"


class YunnanSongkranBenchmarkTests(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".sqlite")
        os.close(fd)
        self.db = MythDB(self.path)
        payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        self.semantic_version = payload["semantic_version"]
        self.fixtures = payload["fixtures"]
        self.ids = {}
        for fixture in self.fixtures:
            wid, _ = ingest_fixture(self.db, fixture)
            self.ids[fixture["fixture_id"]] = wid

    def tearDown(self):
        self.db.close()
        os.unlink(self.path)

    def test_provenance_is_preserved(self):
        dai = self.db.witness(self.ids["YUNNAN_2002_0353_DEHONG_DAI"])["metadata"]
        deang = self.db.witness(self.ids["YUNNAN_2002_0354_RUILI_DEANG"])["metadata"]

        self.assertEqual(dai["narrator"], "岩林")
        self.assertEqual(dai["collector"], "林木")
        self.assertEqual(dai["collection_location"], "德宏州")
        self.assertEqual(deang["narrator"], "满坎木")
        self.assertEqual(deang["collector"], "杨筑骧")
        self.assertEqual(deang["collection_location"], "瑞丽县")
        self.assertEqual(deang["collection_year"], 1985)
        self.assertFalse(dai["raw_source_committed"])
        self.assertFalse(deang["raw_source_committed"])

    def test_direct_dictionary_retrieval_finds_rare_bundle(self):
        hits = self.db.dictionary_scan(["头发", "断首", "十二", "水", "历法", "老象", "猴子"])
        dai = self.ids["YUNNAN_2002_0353_DEHONG_DAI"]
        deang = self.ids["YUNNAN_2002_0354_RUILI_DEANG"]

        self.assertTrue(any(h.witness_id == dai for h in hits["头发"]))
        self.assertTrue(any(h.witness_id == deang for h in hits["头发"]))
        self.assertTrue(any(h.witness_id == dai for h in hits["十二"]))
        self.assertTrue(any(h.witness_id == deang for h in hits["十二"]))
        self.assertTrue(any(h.witness_id == deang for h in hits["历法"]))
        self.assertTrue(any(h.witness_id == deang for h in hits["老象"]))
        self.assertTrue(any(h.witness_id == deang for h in hits["猴子"]))

    def test_semantic_diff_exposes_mutation_slots(self):
        dai = self.ids["YUNNAN_2002_0353_DEHONG_DAI"]
        deang = self.ids["YUNNAN_2002_0354_RUILI_DEANG"]
        report = compare_fixture_pair(self.db, dai, deang, self.semantic_version)
        sem = report["semantic"]

        for predicate in ["HAIR_WEAPON", "DECAPITATE", "DANGEROUS_HEAD", "FEMALE_ROTATION", "WATER_WASH", "RITUAL_ORIGIN"]:
            self.assertIn(predicate, sem["retained"])

        for predicate in ["CALENDAR_ERROR", "GRAFT_HEAD", "REVIVE", "CALENDAR_REPAIR", "AGRICULTURE_ORDER"]:
            self.assertIn(predicate, sem["added"])

        hair_delta = next(x for x in sem["changed"] if x["predicate"] == "HAIR_WEAPON")
        left_payload = hair_delta["delta"]["payload"]["left"]
        right_payload = hair_delta["delta"]["payload"]["right"]
        self.assertEqual(left_payload["hair_owner"], "male_target")
        self.assertEqual(left_payload["hair_count"], 1)
        self.assertEqual(right_payload["hair_owner"], "wives")
        self.assertEqual(right_payload["hair_count_per_wife"], 7)

    def test_graph_traversal_preserves_event_order(self):
        deang = self.ids["YUNNAN_2002_0354_RUILI_DEANG"]
        events = [
            e for e in self.db.search_events(semantic_version=self.semantic_version)
            if e["witness_id"] == deang
        ]
        events.sort(key=lambda e: e["ordinal"])
        start = events[0]["event_id"]
        bfs = self.db.bfs(start, max_depth=20, edge_type="NEXT_EVENT")
        self.assertEqual(len(bfs), len(events))
        self.assertEqual([node for node, _ in bfs], [e["event_id"] for e in events])


if __name__ == "__main__":
    unittest.main()
