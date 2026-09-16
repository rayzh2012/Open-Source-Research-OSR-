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
                'phonology_lattice_4c.csv','blind_fit_matrix.csv','blind_ablation.csv','ablation_summary.json','evidence_ledger.csv',
                'gu_reading_audit.csv','couplet_morpheme_audit.csv','couplet_global_findings.csv'
            }
            self.assertTrue(expected.issubset({p.name for p in out.iterdir()}))

            manifest=json.loads((out/'run_manifest.json').read_text(encoding='utf-8'))
            self.assertGreaterEqual(manifest['witness_count'],4)
            self.assertGreaterEqual(manifest['priority_term_count'],10)
            self.assertIn('not historical verdicts',manifest['note'])
            self.assertEqual(manifest['lattice_major_divergence_chars'],['谷'])
            self.assertEqual(manifest['gu_status'],'LATENT_READING_NOT_RESOLVED')
            self.assertEqual(manifest['gu_latent_state_count'],3)
            self.assertGreaterEqual(manifest['morpheme_audit_row_count'],10)
            self.assertIn('ek',manifest['morpheme_direct_gap_units'])
            self.assertIn('got',manifest['morpheme_direct_gap_units'])
            self.assertIn('kt',manifest['morpheme_direct_gap_units'])
            self.assertIn('ke',manifest['morpheme_strong_units'])

            vg=json.loads((out/'variant_graph.json').read_text(encoding='utf-8'))
            self.assertIn('fotucheng-tradition',vg['dependency_groups'])

            with open(out/'blind_fit_matrix.csv',encoding='utf-8-sig') as f:
                blind=list(csv.DictReader(f))
            scores={r['id']:int(r['blind_evidence_balance']) for r in blind}
            self.assertEqual(scores['H_OLD_ARIN'],2)
            self.assertEqual(scores['H_CONTACT'],2)
            self.assertGreater(scores['H_OLD_ARIN'],scores['H_TURKIC'])
            self.assertEqual(set(manifest['blind_top_models']),{'H_OLD_ARIN','H_CONTACT'})

            with open(out/'couplet_morpheme_audit.csv',encoding='utf-8-sig') as f:
                morph=list(csv.DictReader(f))
            by_unit={r['unit']:r for r in morph}
            self.assertEqual(by_unit['ke']['status'],'DIRECT_ARIN_LEXICAL_AFTER_GLOSS_REVEAL')
            self.assertEqual(by_unit['ek']['status'],'DIRECT_ARIN_GAP')
            self.assertEqual(by_unit['got']['status'],'DIRECT_LEXICAL_MISMATCH_OPEN')
            self.assertEqual(by_unit['kt']['status'],'DIRECT_ARIN_GAP')
            self.assertEqual(by_unit['surface taŋ']['status'],'DOWNGRADED_SEGMENTATION_FORK')

            with open(out/'evidence_ledger.csv',encoding='utf-8-sig') as f:
                ledger=list(csv.DictReader(f))
            semantic=[r for r in ledger if r['dimension']=='semantics']
            self.assertTrue(semantic)
            self.assertTrue(all(r['blind']=='false' for r in semantic))

            summary=json.loads((out/'ablation_summary.json').read_text(encoding='utf-8'))
            self.assertIn('H_CONTACT',summary['BLIND_ALL']['leaders'])
            self.assertIn('H_OLD_ARIN',summary['BLIND_ALL']['leaders'])
            self.assertIn('H_CONTACT',summary['NO_MORPHOLOGY']['leaders'])
            self.assertIn('H_OLD_ARIN',summary['GLOSS_REVEAL']['leaders'])

            nxt=json.loads((out/'next_search.json').read_text(encoding='utf-8'))
            self.assertEqual(nxt['highest_information_gain'][0]['id'],'IG_PROTO_ROOTS')
            self.assertEqual(nxt['highest_information_gain'][1]['id'],'IG_SEGMENTATION')
            self.assertEqual(nxt['highest_information_gain'][3]['id'],'IG_BOOK_74')


if __name__=='__main__':
    unittest.main()
