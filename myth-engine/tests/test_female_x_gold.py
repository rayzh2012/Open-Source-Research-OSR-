import json
import unittest
from pathlib import Path

from myth_engine.female_x import (
    classify_female_x_candidate,
    female_x_hit_hash,
    iter_female_x,
)


ROOT = Path(__file__).resolve().parents[1] / "benchmarks"
SHANHAIJING_GOLD = ROOT / "female-x-shanhaijing" / "gold_v1.json"
EARLY_TEXT_GOLD = ROOT / "female-x-early-texts" / "gold_v1.json"


class FemaleXGoldTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload = json.loads(SHANHAIJING_GOLD.read_text(encoding="utf-8"))
        cls.early = json.loads(EARLY_TEXT_GOLD.read_text(encoding="utf-8"))

    def test_gold_type_routing(self):
        failures = []
        for case in self.payload["cases"]:
            hint = classify_female_x_candidate(
                case["candidate"],
                case.get("left", ""),
                case.get("right", ""),
            )
            if hint.entity_type_hint != case["expected_type"]:
                failures.append(
                    (case["id"], case["candidate"], case["expected_type"], hint.entity_type_hint, hint.reasons)
                )
        self.assertEqual(failures, [])

    def test_chuci_grammar_negative_control(self):
        # 天问：玄鸟致贻，女何喜？  A raw 女X regex sees 女何, but it is
        # syntactic prose, not a deity name.
        hint = classify_female_x_candidate("女何", "玄鸟致贻，", "喜？")
        self.assertEqual(hint.entity_type_hint, "GRAMMATICAL_PHRASE")
        grammar_case = next(x for x in self.early["cases"] if x["id"] == "CHUCI_GRAMMAR_NUHE")
        self.assertEqual(grammar_case["identity_status"], "NOT_A_NAME")

    def test_early_text_controls_keep_cross_tradition_distinctions(self):
        ids = {x["id"] for x in self.early["cases"]}
        self.assertIn("CHUCI_NUQI_NINE_SONS", ids)
        self.assertIn("CHUCI_NUQI_SEWING", ids)
        self.assertIn("SHUOWEN_NUJIAN", ids)
        self.assertIn("CHUCI_NUWA", ids)
        nujian = next(x for x in self.early["cases"] if x["id"] == "SHUOWEN_NUJIAN")
        self.assertEqual(nujian["identity_status"], "DISTINCT_CONTROL_TRADITION")

    def test_generic_discovery_is_conservative_two_graph_shape(self):
        text = "女娃游海；女尸化草；女床之山；赤水女子献；天女曰妭。"
        found = [m.group(0) for m in iter_female_x(text)]
        self.assertIn("女娃", found)
        self.assertIn("女尸", found)
        self.assertIn("女床", found)
        self.assertNotIn("女子献", found)
        self.assertNotIn("天女曰妭", found)

    def test_same_context_distinct_entities_survive_dedupe_identity(self):
        context = "有寒荒之国。有二人女祭、女薎。女祭操俎而居两水之间。"
        nuji = female_x_hit_hash("seed", "女祭", context)
        numie = female_x_hit_hash("seed", "女薎", context)
        self.assertNotEqual(nuji, numie)
        self.assertEqual(nuji, female_x_hit_hash("seed", "女祭", context))
        self.assertNotEqual(nuji, female_x_hit_hash("discovery", "女祭", context))

    def test_textual_relations_never_assert_identity_fact(self):
        relations = self.payload["textual_relations"]
        self.assertTrue(any(x["a"] == "女戚" and x["b"] == "女薎" for x in relations))
        self.assertTrue(any(x["a"] == "女虔" and x["b"] == "女䖍" for x in relations))
        self.assertTrue(any(x["a"] == "赤水女子献" for x in relations))
        for rel in relations:
            self.assertNotEqual(rel["status"], "FACT_IDENTITY")


if __name__ == "__main__":
    unittest.main()
