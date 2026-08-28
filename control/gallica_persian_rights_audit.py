#!/usr/bin/env python3
from __future__ import annotations
import json, subprocess
from pathlib import Path

SRC='gdrive:龍族古籍源庫｜Dragon Source Corpus/ISLAMIC_PERSIAN_RESCUE/gallica_persian_manuscripts/worklists/bnf/worklist.jsonl'
ROOT='gdrive:龍族古籍源庫｜Dragon Source Corpus/ISLAMIC_PERSIAN_RESCUE/gallica_persian_manuscripts/rights_audit'
PUBLIC_MARKERS=('domaine public','public domain','public-domain','domaine_public')
RESTRICT_MARKERS=('copyright','sous droits','restricted','restriction','protégé','protege')

def main():
 p=subprocess.run(['rclone','cat',SRC],text=True,capture_output=True,check=True)
 rows=[json.loads(x) for x in p.stdout.splitlines() if x.strip()]
 if len(rows)!=1475:raise SystemExit(f'expected 1475, got {len(rows)}')
 audited=[];explicit=[];unresolved=[];restricted=[];pdf_format=[]
 for row in rows:
  ark=row['ark'];f=row.get('fields') or {};rights=' | '.join(f.get('rights') or []);source=' | '.join(f.get('source') or []);formats=' | '.join(f.get('format') or [])
  rlow=rights.lower();flow=formats.lower()
  if any(m in rlow for m in RESTRICT_MARKERS): cls='RESTRICTED_SIGNAL';restricted.append(ark)
  elif any(m in rlow for m in PUBLIC_MARKERS): cls='EXPLICIT_PUBLIC_DOMAIN';explicit.append(ark)
  else: cls='UNRESOLVED_RIGHTS_TEXT';unresolved.append(ark)
  if 'application/pdf' in flow or 'pdf' in flow:pdf_format.append(ark)
  audited.append({'ark':ark,'classification':cls,'rights':f.get('rights') or [],'source':f.get('source') or [],'format':f.get('format') or [],'title':f.get('title') or [],'date':f.get('date') or [],'provenance':'bnf.fr','free_access':'Libre'})
 out=Path('/tmp/gallica-rights');out.mkdir(parents=True,exist_ok=True)
 with (out/'rights_catalog.jsonl').open('w',encoding='utf-8') as h:
  for r in audited:h.write(json.dumps(r,ensure_ascii=False,sort_keys=True)+'\n')
 (out/'explicit_public_domain.txt').write_text('\n'.join(explicit)+'\n',encoding='utf-8')
 (out/'unresolved.txt').write_text('\n'.join(unresolved)+'\n',encoding='utf-8')
 (out/'restricted_signal.txt').write_text('\n'.join(restricted)+'\n',encoding='utf-8')
 (out/'pdf_format.txt').write_text('\n'.join(pdf_format)+'\n',encoding='utf-8')
 summary={'worklist':1475,'explicit_public_domain':len(explicit),'unresolved_rights_text':len(unresolved),'restricted_signal':len(restricted),'pdf_format_signal':len(pdf_format),'policy':'Only explicit public-domain BnF records are eligible for bytes backfill without further item-level rights lookup.'}
 (out/'SUMMARY.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2,sort_keys=True)+'\n',encoding='utf-8')
 subprocess.run(['rclone','copy',str(out),ROOT,'--drive-chunk-size','64M','--retries','8','--low-level-retries','16','--timeout','10m','--contimeout','30s'],check=True)
 print('RESULT_JSON='+json.dumps(summary,ensure_ascii=False,sort_keys=True));return 0
if __name__=='__main__':raise SystemExit(main())
