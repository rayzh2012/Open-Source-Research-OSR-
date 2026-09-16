import csv, json, subprocess, sys, tempfile, unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
SCRIPT=ROOT/'myth-engine'/'tools'/'shile_anre_pipeline.py'
PACK=ROOT/'myth-engine'/'query-packs'/'shile_anre_v1.json'

class ShileANREPipelineTest(unittest.TestCase):
    def test_pipeline_outputs_and_guards(self):
        with tempfile.TemporaryDirectory() as td:
            subprocess.run([sys.executable,str(SCRIPT),'--query-pack',str(PACK),'--output-dir',td],check=True)
            out=Path(td)
            expected={'variant_graph.json','hypothesis_matrix.csv','phonology_queue.csv','run_manifest.json','next_search.json','report.md'}
            self.assertTrue(expected.issubset({p.name for p in out.iterdir()}))
            manifest=json.loads((out/'run_manifest.json').read_text(encoding='utf-8'))
            self.assertGreaterEqual(manifest['witness_count'],4)
            self.assertGreaterEqual(manifest['priority_term_count'],10)
            self.assertIn('not historical verdicts',manifest['note'])
            vg=json.loads((out/'variant_graph.json').read_text(encoding='utf-8'))
            self.assertIn('fotucheng-tradition',vg['dependency_groups'])
            with open(out/'hypothesis_matrix.csv',encoding='utf-8-sig') as f:
                rows=list(csv.DictReader(f))
            self.assertEqual(len(rows),5)
            stitched=next(r for r in rows if r['id']=='H_AUTHOR_STITCHED')
            old_arin=next(r for r in rows if r['id']=='H_OLD_ARIN')
            self.assertGreater(float(old_arin['anre_score']),float(stitched['anre_score']))

if __name__=='__main__': unittest.main()
