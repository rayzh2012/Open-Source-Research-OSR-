#!/usr/bin/env python3
import argparse,hashlib,json,os,subprocess
from pathlib import Path
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

def sha256(p):
    h=hashlib.sha256()
    with open(p,'rb') as f:
        for b in iter(lambda:f.read(8*1024*1024),b''): h.update(b)
    return h.hexdigest()

def run(cmd,**kw): return subprocess.run(cmd,check=True,**kw)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--target-id',required=True);ap.add_argument('--registry',required=True);ap.add_argument('--work-dir',required=True);a=ap.parse_args()
    reg=json.load(open(a.registry,encoding='utf-8')); t=next(x for x in reg['items'] if x['id']==a.target_id)
    root=f"gdrive:{reg['destination_root']}/{t['id']}"; cp=subprocess.run(['rclone','cat',root+'/COMPLETE.json'],text=True,capture_output=True)
    if cp.returncode==0:
        try:
            old=json.loads(cp.stdout)
            if old.get('status')=='PASS' and old.get('ia_id')==t['ia_id'] and old.get('licenseurl')==t['licenseurl']:
                print('RESULT_JSON='+json.dumps({'status':'SKIP_COMPLETE','id':t['id'],'ia_id':t['ia_id']},ensure_ascii=False));return 0
        except Exception: pass
    retry=Retry(total=10,connect=10,read=10,backoff_factor=2,status_forcelist=(429,500,502,503,504),allowed_methods=frozenset(['GET']),respect_retry_after_header=True)
    s=requests.Session();s.headers['User-Agent']='OSR-Preservation/1.0';s.mount('https://',HTTPAdapter(max_retries=retry))
    meta=s.get('https://archive.org/metadata/'+t['ia_id'],timeout=120).json(); m=meta.get('metadata') or {}
    if m.get('licenseurl') != t['licenseurl']: raise RuntimeError(f"license changed: {m.get('licenseurl')} != {t['licenseurl']}")
    files=[]
    for f in meta.get('files',[]):
        n=f.get('name',''); src=f.get('source'); fmt=f.get('format','')
        low=n.lower()
        wanted=False
        if src=='original' and (low.endswith(('.tif','.tiff','.jpg','.jpeg','.pdf','.xml'))): wanted=True
        if t['license'].startswith('CC0') and (fmt in ('DjVuTXT','Djvu XML','Additional Text PDF','Scandata') or low.endswith(('_djvu.txt','_djvu.xml','_text.pdf','_scandata.xml'))): wanted=True
        if low.endswith('_files.xml') or low.endswith('_meta.xml') or low.endswith('_dc.xml') or low.endswith('_marc.xml'): wanted=True
        if wanted: files.append({'name':n,'format':fmt,'source':src,'declared_size':f.get('size')})
    if not files: raise RuntimeError('no preservable files selected')
    wd=Path(a.work_dir);wd.mkdir(parents=True,exist_ok=True);done={}
    for spec in files:
        name=spec['name']; url=f"https://archive.org/download/{t['ia_id']}/{name}"; out=wd/name; out.parent.mkdir(parents=True,exist_ok=True); tmp=Path(str(out)+'.part')
        print('DOWNLOAD',name,url,flush=True)
        with s.get(url,stream=True,timeout=(30,1800)) as r:
            r.raise_for_status(); expected=int(r.headers.get('Content-Length') or 0); n=0
            with open(tmp,'wb') as fh:
                for chunk in r.iter_content(8*1024*1024):
                    if chunk: fh.write(chunk); n+=len(chunk)
        if expected and n!=expected: raise IOError(f'short download {name}: {n}!={expected}')
        os.replace(tmp,out); digest=sha256(out)
        run(['rclone','copyto',str(out),f'{root}/raw/{name}','--drive-chunk-size','128M','--retries','8','--low-level-retries','16','--timeout','20m','--contimeout','30s'])
        done[name]={'bytes':n,'sha256':digest,'format':spec['format'],'source':spec['source'],'url':url,'status':'PASS'}; out.unlink(missing_ok=True)
    complete={'schema_version':'osr-persian-manuscript-complete-v1','status':'PASS','id':t['id'],'ia_id':t['ia_id'],'title':t['title'],'date':t.get('date'),'collection':t.get('collection'),'license':t['license'],'licenseurl':t['licenseurl'],'source_metadata_licenseurl':m.get('licenseurl'),'files':done}
    p=wd/'COMPLETE.json';p.write_text(json.dumps(complete,ensure_ascii=False,indent=2,sort_keys=True)+'\n',encoding='utf-8');run(['rclone','copyto',str(p),root+'/COMPLETE.json','--retries','8','--low-level-retries','16'])
    print('RESULT_JSON='+json.dumps(complete,ensure_ascii=False,sort_keys=True));return 0
if __name__=='__main__': raise SystemExit(main())
