#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, os, subprocess, time
from pathlib import Path
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


def sha(p:Path):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(8*1024*1024),b''):h.update(b)
 return h.hexdigest()

def dump(p:Path,o):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(o,ensure_ascii=False,indent=2,sort_keys=True)+'\n',encoding='utf-8')
def rc(src:Path,dst:str):subprocess.run(['rclone','copyto',str(src),dst,'--drive-chunk-size','64M','--retries','8','--low-level-retries','16','--timeout','10m','--contimeout','30s','--stats','30s'],check=True)
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--target-id',required=True);ap.add_argument('--registry',required=True);ap.add_argument('--work-dir',required=True);a=ap.parse_args()
 reg=json.load(open(a.registry,encoding='utf-8'));item=next(x for x in reg['items'] if x['id']==a.target_id);iid=item['ia_id'];root=f"gdrive:{reg['destination_root']}/{item['id']}"
 cp=subprocess.run(['rclone','cat',f'{root}/COMPLETE.json'],text=True,capture_output=True)
 if cp.returncode==0 and cp.stdout.strip():
  try:
   old=json.loads(cp.stdout)
   if old.get('status')=='PASS' and old.get('ia_id')==iid:print('RESULT_JSON='+json.dumps({'status':'SKIP_COMPLETE','id':item['id']}));return 0
  except:pass
 retry=Retry(total=10,connect=10,read=10,backoff_factor=2,status_forcelist=(429,500,502,503,504),allowed_methods=frozenset(['GET']),respect_retry_after_header=True)
 s=requests.Session();s.headers['User-Agent']='OSR-Preservation/1.0';s.mount('https://',HTTPAdapter(max_retries=retry));w=Path(a.work_dir);w.mkdir(parents=True,exist_ok=True)
 files={
  'pdf':f'https://archive.org/download/{iid}/{iid}.pdf',
  'ocr_text':f'https://archive.org/download/{iid}/{iid}_djvu.txt',
  'meta_xml':f'https://archive.org/download/{iid}/{iid}_meta.xml',
  'files_xml':f'https://archive.org/download/{iid}/{iid}_files.xml'
 }
 done={}
 for kind,url in files.items():
  out=w/Path(url).name;tmp=out.with_suffix(out.suffix+'.part')
  print(f'DOWNLOAD {kind} {url}',flush=True)
  with s.get(url,stream=True,timeout=(30,1800)) as r:
   if r.status_code==404 and kind=='ocr_text':done[kind]={'status':'MISSING_OPTIONAL','url':url};continue
   r.raise_for_status();expected=int(r.headers.get('Content-Length') or 0);n=0
   with tmp.open('wb') as f:
    for chunk in r.iter_content(8*1024*1024):
     if chunk:f.write(chunk);n+=len(chunk)
   if expected and n!=expected:raise IOError(f'short {kind}: {n}!={expected}')
  os.replace(tmp,out);digest=sha(out);rc(out,f'{root}/raw/{out.name}');done[kind]={'status':'PASS','url':url,'bytes':n,'sha256':digest};out.unlink(missing_ok=True);time.sleep(0.3)
 meta={'schema_version':'osr-persian-catalogue-complete-v1','status':'PASS','id':item['id'],'ia_id':iid,'title':item['title'],'year':item['year'],'rights':item['rights'],'source_note':item['source_note'],'files':done}
 p=w/'COMPLETE.json';dump(p,meta);rc(p,f'{root}/COMPLETE.json');print('RESULT_JSON='+json.dumps(meta,ensure_ascii=False,sort_keys=True));return 0
if __name__=='__main__':raise SystemExit(main())
