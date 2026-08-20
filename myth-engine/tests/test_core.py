import os
import tempfile
import unittest

from myth_engine.core import KeywordAutomaton, MythDB, canonical_text, merkle_root, qgrams


class CoreTests(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".sqlite")
        os.close(fd)
        self.db = MythDB(self.path)

    def tearDown(self):
        self.db.close()
        os.unlink(self.path)

    def test_canonical_and_qgrams(self):
        self.assertEqual(canonical_text(" 七 根 头发！"), "七根头发")
        self.assertIn("七根头", qgrams("七根头发", 3))

    def test_merkle_is_order_sensitive(self):
        a = merkle_root(["a", "b", "c"])
        b = merkle_root(["b", "a", "c"])
        self.assertNotEqual(a, b)

    def test_phrase_and_fuzzy(self):
        w1 = self.db.add_witness(
            {"title": "A", "collection_location": "Dehong"},
            "妻子拔下七根头发。\n\n她们把头发搓成绳子勒住脖子。",
        )
        w2 = self.db.add_witness(
            {"title": "B", "collection_location": "Other"},
            "七根头发被搓成绳，随后勒住颈部。",
        )
        exact = self.db.search_phrase("七根头发")
        self.assertTrue(any(h.witness_id == w1 for h in exact))
        fuzzy = self.db.search_fuzzy("七根头发搓成绳")
        self.assertTrue(fuzzy)
        self.assertIn(fuzzy[0].witness_id, {w1, w2})

    def test_dictionary_automaton(self):
        ac = KeywordAutomaton(["一臂", "一足", "断头"])
        hits = ac.scan("此人一臂一足，后来断头。")
        terms = {term for _, term in hits}
        self.assertEqual(terms, {"一臂", "一足", "断头"})

    def test_semantic_versions_and_graph(self):
        w = self.db.add_witness({"title": "C"}, "一个短故事。")
        self.db.add_semantic_version("semantic/v1", {"rules": 1})
        e1 = self.db.add_event(
            witness_id=w,
            semantic_version="semantic/v1",
            ordinal=0,
            predicate="DECAPITATE",
            tags=["HAIR_WEAPON"],
        )
        e2 = self.db.add_event(
            witness_id=w,
            semantic_version="semantic/v1",
            ordinal=1,
            predicate="GRAFT_HEAD",
            tags=["ELEPHANT_HEAD"],
        )
        self.db.add_edge(e1, e2, "NEXT_EVENT")
        self.assertEqual(self.db.bfs(e1, max_depth=2), [(e1, 0), (e2, 1)])
        self.assertEqual(self.db.dfs(e1), [e1, e2])


if __name__ == "__main__":
    unittest.main()
