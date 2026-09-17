import csv, json, subprocess, sys, tempfile, unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
SCRIPT=ROOT/'myth-engine'/'tools'/'shile_book_controls.py'
CONTROLS=ROOT/'research'/'shile-anre'/'book_lexical_controls_v15.json'


class ShileBookControlsTest(unittest.TestCase):
    def test_outputs_and_guardrails(self):
        with tempfile.TemporaryDirectory() as td:
            subprocess.run([sys.executable,str(SCRIPT),'--controls',str(CONTROLS),'--output-dir',td],check=True,cwd=ROOT)
            out=Path(td)
            expected={'book_lexical_controls.csv','book_uniqueness_summary.json','book_controls_report.md'}
            self.assertTrue(expected.issubset({p.name for p in out.iterdir()}))

            with open(out/'book_lexical_controls.csv',encoding='utf-8-sig') as f:
                rows=list(csv.DictReader(f))
            self.assertGreaterEqual(len(rows),10)
            by_id={r['id']:r for r in rows}
            self.assertEqual(by_id['LC_ABBA']['control_strength'],'EXACT_SOUND_MEANING_CONTROL')
            self.assertEqual(by_id['LC_AN']['control_strength'],'NO_STRONG_YENISEIAN_PHONETIC_CONTROL')
            self.assertIn('not a unique match',by_id['LC_ABBA']['reason'])

            summary=json.loads((out/'book_uniqueness_summary.json').read_text(encoding='utf-8'))
            self.assertGreaterEqual(summary['row_count'],10)
            self.assertIn('LC_ABBA',summary['strong_uniqueness_stress_ids'])
            self.assertIn('LC_SHEMESH',summary['strong_uniqueness_stress_ids'])
            self.assertIn('LC_AN',summary['unresolved_or_low_control_ids'])
            self.assertIn('never establishes Yeniseian etymology',summary['interpretation'])


if __name__=='__main__':
    unittest.main()
