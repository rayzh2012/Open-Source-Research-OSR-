#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, re, subprocess, time
from pathlib import Path
import xml.etree.ElementTree as ET
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ROOT='gdrive:龍族古籍源庫｜Dragon Source Corpus/ISLAMIC_PERSIAN_RESCUE/gallica_persian_manuscripts/worklists'
BASE='((dc.language all "per") or (dc.language all "fas")) and (dc.type all "manuscrit")'
QUERIES={
 'bnf': BASE+' and (provenance adj "bnf.fr")',
 'partner_ecodice': BASE+' and (provenance adj "ecodice")',
}
EXPECTED={'bnf':1475,'partner_ecodice':5}

def sess():
 r=Retry(total=8,connect=8,read=8,backoff_factor=2,status_forcelist=(429,500,502,503,504),allowed_methods=frozenset(['GET']),respect_retry_after_header=True,raise_on_status=False)
 s=requests.Session();s.headers.update({'User-Agent':'OSR-Preservation/1.0','Accept':'application/xml,*/*;q=0.5'});s.mount('https://',HTTPAdapter(max_retries=r));return s

def local(t):return t.rsplit('}',1)[-1]
def dump(p,o):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(o,ensure_ascii=False,indent=2,sort_keys=True)+'\n',encoding='utf-8')
def copy(src,dst):subprocess.run(['rclone','copy',str(src),dst,'--drive-chunk-size','64M','--transfers','4','--checkers','8','--retries','8','--low-level-retries','16','--timeout','10m','--contimeout','30s'],check=True)

def parse_record(rec):
 fields={}
 for x in rec.iter():
  n=local(x.tag)
  if n in {'title','creator','contributor','subject','description','publisher','date','type','format','identifier','source','language','relation','coverage','rights'} and x.text and x.text.strip():fields.setdefault(n,[]).append(x.text.strip())
 vals=fields.get('identifier',[])
 ark=None
 for v in vals:
  m=re.search(r'ark:/12148/([A-Za-z0-9]+)',v)
  if m:ark=m.group(1);break
 return {'ark':ark,'fields':fields} if ark else None

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--work-dir',required=True);a=ap.parse_args();w=Path(a.work_dir);s=sess();summary={}
 for label,q in QUERIES.items():
  out=w/label;out.mkdir(parents=True,exist_ok=True);rows={};start=1;reported=None
  while True:
   params={'version':'1.2','operation':'searchRetrieve','query':q,'startRecord':start,'maximumRecords':50,'collapsing':'false'}
   r=s.get('https://gallica.bnf.fr/SRU',params=params,timeout=(30,180));r.raise_for_status();raw=r.content
   (out/'sru').mkdir(exist_ok=True);(out/'sru'/f'{start:06d}.xml').write_bytes(raw)
   root=ET.fromstring(raw)
   if reported is None:
    nums=[x.text.strip() for x in root.iter() if local(x.tag)=='numberOfRecords' and x.text];reported=int(nums[0]) if nums else 0
   recs=[x for x in root.iter() if local(x.tag)=='record']
   for rec in recs:
    z=parse_record(rec)
    if z: rows[z['ark']]=z
   print(f'{label} start={start} reported={reported} unique={len(rows)}',flush=True)
   if not recs or start+50>reported:break
   start+=50;time.sleep(0.5)
  data=[rows[k] for k in sorted(rows)]
  with (out/'worklist.jsonl').open('w',encoding='utf-8') as f:
   for z in data:f.write(json.dumps(z,ensure_ascii=False,sort_keys=True)+'\n')
  arks='\n'.join(z['ark'] for z in data)+'\n';(out/'arks.txt').write_text(arks,encoding='utf-8')
  sha=hashlib.sha256((out/'worklist.jsonl').read_bytes()).hexdigest()
  status='PASS' if reported==EXPECTED[label] and len(data)==EXPECTED[label] else 'MISMATCH'
  meta={'label':label,'query':q,'reported':reported,'unique_arks':len(data),'expected':EXPECTED[label],'worklist_sha256':sha,'status':status}
  dump(out/'SUMMARY.json',meta);summary[label]=meta
  copy(out,f'{ROOT}/{label}')
 print('RESULT_JSON='+json.dumps(summary,ensure_ascii=False,sort_keys=True))
 return 0 if all(x['status']=='PASS' for x in summary.values()) else 2
if __name__=='__main__':raise SystemExit(main())
