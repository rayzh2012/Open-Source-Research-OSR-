#!/usr/bin/env python3
import argparse, csv, json
from collections import Counter
from pathlib import Path


def load_json(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def write_csv(path, rows, fields):
    with open(path, 'w', newline='', encoding='utf-8-sig') as f:
        w=csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--controls', required=True)
    ap.add_argument('--output-dir', required=True)
    args=ap.parse_args()

    data=load_json(args.controls)
    out=Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)

    fields=[
        'id','book_form','book_context','author_match','author_language','author_meaning',
        'source_date_gate','yeniseian_control','yeniseian_meaning','control_strength',
        'uniqueness_effect','reason','next_gate'
    ]
    rows=[]
    for r in data['rows']:
        rows.append({k:r.get(k,'') for k in fields})
    write_csv(out/'book_lexical_controls.csv', rows, fields)

    effect_counts=Counter(r['uniqueness_effect'] for r in rows)
    strength_counts=Counter(r['control_strength'] for r in rows)

    exact_or_strong=[]
    unresolved=[]
    for r in rows:
        if r['control_strength'] in {'EXACT_SOUND_MEANING_CONTROL','STRONG_CONTROL_UNDER_AUTHOR_LOOSE_PHONETICS','STRONG_FIRST_ELEMENT_COMPETITOR'}:
            exact_or_strong.append(r['id'])
        if r['control_strength'].startswith('NO_STRONG') or 'UNPROVEN' in r['uniqueness_effect'] or 'LITTLE_EFFECT' in r['uniqueness_effect']:
            unresolved.append(r['id'])

    summary={
        'version':data['version'],
        'row_count':len(rows),
        'effect_counts':dict(sorted(effect_counts.items())),
        'strength_counts':dict(sorted(strength_counts.items())),
        'strong_uniqueness_stress_ids':exact_or_strong,
        'unresolved_or_low_control_ids':unresolved,
        'interpretation':'A competing sound+meaning control weakens uniqueness only. It never establishes Yeniseian etymology. Every surviving author match must still pass chronology, historical-sound, geography/contact, systematic-correspondence and morphology gates.'
    }
    (out/'book_uniqueness_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')

    lines=[
        f"# Book lexical uniqueness stress test — {data['version']}",
        '',
        f"Rows audited: {len(rows)}",
        '',
        '## Rule',
        'A sound+meaning resemblance is not counted as strong ancestry evidence until it survives a uniqueness/null test. A competitor is a false-positive control, not an alternative etymology by itself.',
        '',
        '## Results'
    ]
    for r in rows:
        lines.append(f"- {r['book_form']} → author: {r['author_match']} ({r['author_meaning']}); control: {r['yeniseian_control']} ({r['yeniseian_meaning']}); {r['control_strength']} / {r['uniqueness_effect']}")
    lines += ['', '## Strong stress cases']
    for rid in exact_or_strong:
        row=next(x for x in rows if x['id']==rid)
        lines.append(f"- {row['book_form']}: {row['reason']}")
    lines += ['', '## Guardrail', summary['interpretation']]
    (out/'book_controls_report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')


if __name__=='__main__':
    main()
