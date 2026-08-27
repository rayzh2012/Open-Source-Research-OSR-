#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, os, subprocess, time
from email.utils import parsedate_to_datetime
from pathlib import Path
import requests

ROOT='gdrive:龍族古籍源庫｜Dragon Source Corpus/ISLAMIC_PERSIAN_RESCUE/gallica_persian_manuscripts'
PD_LIST=f'{ROOT}/rights_audit/explicit_public_domain.txt'
WORKLIST=f'{ROOT}/worklists/bnf/worklist.jsonl'
DEST=f'{ROOT}/items'


def rc_cat(p:str)->str|None:
 q=subprocess.run(['rclone','cat',p],text=True,capture_output=True)
 return q.stdout if q.returncode==0 else None

def rc_copyto(src:Path,dst:str):
 subprocess.run(['rclone','copyto',str(src),dst,'--drive-chunk-size','64M','--retries','8','--low-level-retries','16','--timeout','10m','--contimeout','30s','--stats','30s'],check=True)
def dump(p:Path,o):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(o,ensure_ascii=False,indent=2,sort_keys=True)+'\n',encoding='utf-8')
def sha(p:Path):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(8*1024*1024),b''):h.update(b)
 return h.hexdigest()

def wait_for_429(r:requests.Response,attempt:int):
 ra=(r.headers.get('Retry-After') or '').strip()
 wait=None
 if ra.isdigit():wait=int(ra)
 elif ra:
  try:wait=max(1,int((parsedate_to_datetime(ra)-parsedate_to_datetime(r.headers.get('Date'))).total_seconds()))
  except:pass
 if wait is None:wait=min(300,15*(2**min(attempt,4)))
 wait=min(max(wait,15),600)
 print(f'RATE_LIMIT status={r.status_code} retry_after={ra!r} sleep={wait}s',flush=True);time.sleep(wait)

def download_pdf(s:requests.Session,url:str,out:Path,attempts:int=12):
 tmp=out.with_suffix('.pdf.part');last=None
 for a in range(1,attempts+1):
  tmp.unlink(missing_ok=True);size=0;h=hashlib.sha256()
  try:
   with s.get(url,stream=True,timeout=(30,1800),allow_redirects=True,headers={'Accept':'application/pdf,*/*;q=0.5'}) as r:
    if r.status_code in (429,503):
     wait_for_429(r,a);continue
    r.raise_for_status();ctype=(r.headers.get('Content-Type') or '').lower();expected=int(r.headers.get('Content-Length') or 0)
    with tmp.open('wb') as f:
     for chunk in r.iter_content(8*1024*1024):
      if chunk:f.write(chunk);h.update(chunk);size+=len(chunk)
    prefix=tmp.read_bytes()[:5]
    if prefix!=b'%PDF-':raise IOError(f'non-PDF payload content-type={ctype} prefix={prefix!r}')
    if expected and size!=expected:raise IOError(f'short PDF {size}!={expected}')
   os.replace(tmp,out);return size,h.hexdigest(),ctype
  except Exception as e:
   last=e;print(f'PDF_RETRY {a}/{attempts} url={url} bytes={size} error={e!r}',flush=True);tmp.unlink(missing_ok=True);time.sleep(min(120,5*(2**min(a,4))))
 raise last or RuntimeError('download failed')

def load_state():
 ids=[x.strip() for x in (rc_cat(PD_LIST) or '').splitlines() if x.strip()]
 rows={}
 for line in (rc_cat(WORKLIST) or '').splitlines():
  if line.strip():
   x=json.loads(line);rows[x['ark']]=x
 if len(ids)!=1472:raise RuntimeError(f'expected 1472 explicit PD ARKs, got {len(ids)}')
 return ids,rows

def process(ark:str,row:dict,s:requests.Session,w:Path):
 remote=f'{DEST}/{ark}';prior=rc_cat(f'{remote}/COMPLETE.json')
 if prior:
  try:
   p=json.loads(prior)
   if p.get('status')=='PASS' and p.get('ark')==ark:return {'ark':ark,'status':'SKIP_COMPLETE','pdf_bytes':int(p.get('pdf_bytes') or 0)}
  except:pass
 fields=row.get('fields') or {};rights=fields.get('rights') or []
 if not any(('domaine public' in x.lower() or 'public domain' in x.lower() or 'domaine_public' in x.lower()) for x in rights):raise RuntimeError(f'{ark} lost explicit-PD predicate: {rights!r}')
 pdf_url=f'https://gallica.bnf.fr/ark:/12148/{ark}.pdf';pdf=w/f'{ark}.pdf';meta=w/f'{ark}.json';dump(meta,row)
 size,digest,ctype=download_pdf(s,pdf_url,pdf)
 rc_copyto(meta,f'{remote}/metadata/sru_record.json');rc_copyto(pdf,f'{remote}/raw/{ark}.pdf')
 complete={'schema_version':'osr-gallica-persian-complete-v1','status':'PASS','ark':ark,'canonical_url':f'https://gallica.bnf.fr/ark:/12148/{ark}','pdf_url':pdf_url,'pdf_bytes':size,'pdf_sha256':digest,'pdf_content_type':ctype,'rights':rights,'provenance':'bnf.fr','free_access':'Libre','attribution':'Source: gallica.bnf.fr / Bibliothèque nationale de France'}
 cp=w/f'{ark}.COMPLETE.json';dump(cp,complete);rc_copyto(cp,f'{remote}/COMPLETE.json');pdf.unlink(missing_ok=True);meta.unlink(missing_ok=True);cp.unlink(missing_ok=True);return {'ark':ark,'status':'PASS','pdf_bytes':size}

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--partition',type=int,default=0);ap.add_argument('--partitions',type=int,default=1);ap.add_argument('--limit',type=int,default=0);ap.add_argument('--work-dir',required=True);a=ap.parse_args()
 ids,rows=load_state();chosen=[x for x in ids if int(hashlib.sha1(x.encode()).hexdigest(),16)%a.partitions==a.partition]
 if a.limit:chosen=chosen[:a.limit]
 s=requests.Session();s.headers['User-Agent']='OSR-Preservation/1.0 (+research preservation; polite rate-limited client)';w=Path(a.work_dir);w.mkdir(parents=True,exist_ok=True)
 result=[];fails=[];new_bytes=0
 for i,ark in enumerate(chosen,1):
  print(f'[{i}/{len(chosen)}] {ark}',flush=True)
  try:
   z=process(ark,rows[ark],s,w);result.append(z);new_bytes+=z.get('pdf_bytes',0) if z.get('status')=='PASS' else 0
  except Exception as e:fails.append({'ark':ark,'error':repr(e)});print(f'FAILED {ark} {e!r}',flush=True)
  time.sleep(2.0)
 summary={'partition':a.partition,'partitions':a.partitions,'selected':len(chosen),'pass_or_cached':len(result),'failures':fails,'new_pdf_bytes':new_bytes,'status':'PASS' if not fails else 'PARTIAL_FAILURE'}
 print('RESULT_JSON='+json.dumps(summary,ensure_ascii=False,sort_keys=True));return 0 if not fails else 2
if __name__=='__main__':raise SystemExit(main())
