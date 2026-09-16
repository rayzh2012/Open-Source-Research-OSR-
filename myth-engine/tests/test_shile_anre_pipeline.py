import csv, json, subprocess, sys, tempfile, unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
SCRIPT=ROOT/'myth-engine'/'tools'/'shile_anre_pipeline.py'
PACK=ROOT/'myth-engine'/'query-packs'/'shile_anre_v1.json'


class ShileANREPipelineTest(unittest.TestCase):
    def test_pipeline_outputs_and_guards(self):
        with tempfile.TemporaryDirectory() as td:
            subprocess.run([sys.executable,str(SCRIPT),'--query-pack',str(PACK),'--output-dir',td],check=True,cwd=ROOT)
            out=Path(td)
            expected={
                'variant_graph.json','hypothesis_matrix.csv','phonology_queue.csv','run_manifest.json','next_search.json','report.md',
                'phonology_lattice_4c.csv','blind_fit_matrix.csv','blind_ablation.csv','ablation_summary.json','evidence_ledger.csv'
            }
            self.assertTrue(expected.issubset({p.name for p in out.iterdir()}))

            manifest=json.loads((out/'run_manifest.json').read_text(encoding='utf-8'))
            self.assertGreaterEqual(manifest['witness_count'],4)
            self.assertGreaterEqual(manifest['priority_term_count'],10)
            self.assertIn('not historical verdicts',manifest['note'])
            self.assertEqual(manifest['lattice_major_divergence_chars'],['谷'])

            vg=json.loads((out/'variant_graph.json').read_text(encoding='utf-8'))
            self.assertIn('fotucheng-tradition',vg['dependency_groups'])

            with open(out/'hypothesis_matrix.csv',encoding='utf-8-sig') as f:
                legacy=list(csv.DictReader(f))
            self.assertEqual(len(legacy),5)
            stitched=next(r for r in legacy if r['id']=='H_AUTHOR_STITCHED')
            old_arin_legacy=next(r for r in legacy if r['id']=='H_OLD_ARIN')
            self.assertGreater(float(old_arin_legacy['anre_score']),float(stitched['anre_score']))

            with open(out/'blind_fit_matrix.csv',encoding='utf-8-sig') as f:
                blind=list(csv.DictReader(f))
            self.assertEqual(blind[0]['id'],'H_OLD_ARIN')
            old_arin=next(r for r in blind if r['id']=='H_OLD_ARIN')
            turkic=next(r for r in blind if r['id']=='H_TURKIC')
            self.assertGreater(int(old_arin['blind_evidence_balance']),int(turkic['blind_evidence_balance']))

            with open(out/'evidence_ledger.csv',encoding='utf-8-sig') as f:
                ledger=list(csv.DictReader(f))
            semantic=[r for r in ledger if r['dimension']=='semantics']
            self.assertTrue(semantic)
            self.assertTrue(all(r['blind']=='false' for r in semantic))

            summary=json.loads((out/'ablation_summary.json').read_text(encoding='utf-8'))
            self.assertIn('H_OLD_ARIN',summary['BLIND_ALL']['leaders'])
            self.assertIn('H_CONTACT',summary['NO_MORPHOLOGY']['leaders'])
            self.assertNotEqual(summary['BLIND_ALL']['leaders'],summary['NO_MORPHOLOGY']['leaders'])


if __name__=='__main__':
    unittest.main()
