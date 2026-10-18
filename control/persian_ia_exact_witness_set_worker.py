#!/usr/bin/env python3
from __future__ import annotations
import argparse,hashlib,json,os,subprocess
from pathlib import Path
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

def sha256(path:Path)->str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(8*1024*1024),b''): h.update(b)
    return h.hexdigest()

def sha1(path:Path)->str:
    h=hashlib.sha1()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(8*1024*1024),b''): h.update(b)
    return h.hexdigest()

def run(cmd): subprocess.run(cmd,check=True)

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--registry',required=True); ap.add_argument('--work-dir',required=True); a=ap.parse_args()
    t=json.load(open(a.registry,encoding='utf-8')); root=f"gdrive:{t['destination_root']}/{t['id']}"
    cp=subprocess.run(['rclone','cat',root+'/COMPLETE.json'],text=True,capture_output=True)
    if cp.returncode==0:
        try:
            old=json.loads(cp.stdout)
            if old.get('status')=='PASS' and old.get('id')==t['id'] and old.get('ia_id')==t['ia_id'] and old.get('licenseurl')==t['licenseurl']:
                print('RESULT_JSON='+json.dumps({'status':'SKIP_COMPLETE','id':t['id']},sort_keys=True)); return 0
        except Exception: pass
    retry=Retry(total=10,connect=10,read=10,backoff_factor=2,status_forcelist=(429,500,502,503,504),allowed_methods=frozenset(['GET']),respect_retry_after_header=True)
    s=requests.Session(); s.headers['User-Agent']='OSR-Preservation/1.0'; s.mount('https://',HTTPAdapter(max_retries=retry))
    meta=s.get('https://archive.org/metadata/'+t['ia_id'],timeout=120).json(); m=meta.get('metadata') or {}
    if m.get('licenseurl') != t['licenseurl']: raise RuntimeError(f"license changed: {m.get('licenseurl')} != {t['licenseurl']}")
    by_name={f.get('name'):f for f in meta.get('files',[])}
    wd=Path(a.work_dir); wd.mkdir(parents=True,exist_ok=True); done={}; total=0
    meta_path=wd/'ia_metadata.json'; meta_path.write_text(json.dumps(meta,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    run(['rclone','copyto',str(meta_path),root+'/metadata/ia_metadata.json','--retries','8','--low-level-retries','16'])
    for spec in t['witnesses']:
        name=spec['source_filename']; f=by_name.get(name)
        if not f: raise RuntimeError(f'missing IA file: {name}')
        if f.get('source')!='original': raise RuntimeError(f'not original: {name} source={f.get("source")}')
        declared_sha1=f.get('sha1'); declared_size=int(f.get('size') or 0)
        if declared_sha1 != spec['source_sha1']: raise RuntimeError(f'IA sha1 changed for {name}: {declared_sha1} != {spec["source_sha1"]}')
        if declared_size != int(spec['source_bytes']): raise RuntimeError(f'IA size changed for {name}: {declared_size} != {spec["source_bytes"]}')
        url='https://archive.org/download/'+t['ia_id']+'/'+requests.utils.quote(name,safe='/')
        out=wd/name; out.parent.mkdir(parents=True,exist_ok=True); tmp=Path(str(out)+'.part')
        print('DOWNLOAD_WITNESS',spec['witness_id'],name,declared_size,flush=True)
        with s.get(url,stream=True,timeout=(30,1800)) as r:
            r.raise_for_status(); expected=int(r.headers.get('Content-Length') or 0); n=0
            with tmp.open('wb') as fh:
                for chunk in r.iter_content(8*1024*1024):
                    if chunk: fh.write(chunk); n+=len(chunk)
        if expected and n!=expected: raise IOError(f'short download {name}: {n}!={expected}')
        if n!=declared_size: raise IOError(f'IA size mismatch after download {name}: {n}!={declared_size}')
        os.replace(tmp,out); got_sha1=sha1(out)
        if got_sha1!=spec['source_sha1']: raise IOError(f'SHA1 mismatch {name}: {got_sha1}!={spec["source_sha1"]}')
        digest=sha256(out)
        dst=f"{root}/raw/witnesses/{spec['witness_id']}/{name}"
        run(['rclone','copyto',str(out),dst,'--drive-chunk-size','128M','--retries','8','--low-level-retries','16','--timeout','30m','--contimeout','30s'])
        done[spec['witness_id']]={'label':spec['label'],'source_filename':name,'bytes':n,'source_sha1':got_sha1,'sha256':digest,'url':url,'status':'PASS'}; total+=n; out.unlink(missing_ok=True)
    complete={'schema_version':'osr-persian-witness-set-complete-v1','status':'PASS','id':t['id'],'ia_id':t['ia_id'],'title':t['title'],'collection':t.get('collection'),'license':t['license'],'licenseurl':t['licenseurl'],'source_metadata_licenseurl':m.get('licenseurl'),'witness_count':len(done),'total_witness_bytes':total,'witnesses':done,'selection_policy':'Preserve only the four distinct highest-resolution witness PDFs; exclude _s/_xs lower-resolution duplicates and translation derivative.'}
    p=wd/'COMPLETE.json'; p.write_text(json.dumps(complete,ensure_ascii=False,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    run(['rclone','copyto',str(p),root+'/COMPLETE.json','--retries','8','--low-level-retries','16'])
    print('RESULT_JSON='+json.dumps(complete,ensure_ascii=False,sort_keys=True)); return 0

if __name__=='__main__': raise SystemExit(main())
