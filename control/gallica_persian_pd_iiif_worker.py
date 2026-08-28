#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, subprocess, time
from pathlib import Path
from email.utils import parsedate_to_datetime
import requests

ROOT='gdrive:龍族古籍源庫｜Dragon Source Corpus/ISLAMIC_PERSIAN_RESCUE/gallica_persian_manuscripts'
PD_LIST=f'{ROOT}/rights_audit/explicit_public_domain.txt'
WORKLIST=f'{ROOT}/worklists/bnf/worklist.jsonl'
DEST=f'{ROOT}/items'
UA='OSR-Preservation/1.0 (+noncommercial research preservation; polite IIIF client)'

def rc_cat(path:str)->str|None:
    q=subprocess.run(['rclone','cat',path],text=True,capture_output=True)
    return q.stdout if q.returncode==0 else None

def rc_copyto(src:Path,dst:str):
    subprocess.run(['rclone','copyto',str(src),dst,'--drive-chunk-size','64M','--retries','8','--low-level-retries','16','--timeout','10m','--contimeout','30s'],check=True)

def write_json(path:Path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(obj,ensure_ascii=False,indent=2,sort_keys=True)+'\n',encoding='utf-8')

def sha256(path:Path)->str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(8*1024*1024),b''): h.update(b)
    return h.hexdigest()

def backoff(r:requests.Response,attempt:int):
    ra=(r.headers.get('Retry-After') or '').strip(); wait=None
    if ra.isdigit(): wait=int(ra)
    elif ra:
        try:
            wait=max(1,int((parsedate_to_datetime(ra)-parsedate_to_datetime(r.headers.get('Date'))).total_seconds()))
        except Exception: pass
    if wait is None: wait=min(300,15*(2**min(attempt,4)))
    wait=min(max(wait,15),600)
    print(f'RATE_LIMIT status={r.status_code} sleep={wait}s',flush=True); time.sleep(wait)

def fetch_bytes(session:requests.Session,url:str,out:Path,accept:str,attempts:int=8):
    last=None
    for attempt in range(1,attempts+1):
        tmp=out.with_suffix(out.suffix+'.part'); tmp.unlink(missing_ok=True)
        try:
            with session.get(url,stream=True,timeout=(30,600),allow_redirects=True,headers={'Accept':accept}) as r:
                if r.status_code in (429,503): backoff(r,attempt); continue
                r.raise_for_status(); expected=int(r.headers.get('Content-Length') or 0); n=0
                with tmp.open('wb') as f:
                    for chunk in r.iter_content(4*1024*1024):
                        if chunk: f.write(chunk); n+=len(chunk)
                if expected and n!=expected: raise IOError(f'short payload {n}!={expected}')
                tmp.replace(out)
                return n,(r.headers.get('Content-Type') or '').lower()
        except Exception as e:
            last=e; print(f'RETRY {attempt}/{attempts} {url} error={e!r}',flush=True); tmp.unlink(missing_ok=True); time.sleep(min(120,5*(2**min(attempt,4))))
    raise last or RuntimeError('download failed')

def load_state():
    pd={x.strip() for x in (rc_cat(PD_LIST) or '').splitlines() if x.strip()}
    rows={}
    for line in (rc_cat(WORKLIST) or '').splitlines():
        if line.strip():
            row=json.loads(line); rows[row['ark']]=row
    if len(pd)!=1472: raise RuntimeError(f'expected 1472 explicit PD ARKs, got {len(pd)}')
    return pd,rows

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--ark',required=True); ap.add_argument('--work-dir',required=True); ap.add_argument('--max-pages',type=int,default=0); args=ap.parse_args()
    ark=args.ark; pd,rows=load_state()
    if ark not in pd or ark not in rows: raise RuntimeError(f'{ark} not in explicit-PD canonical worklist')
    row=rows[ark]; rights=(row.get('fields') or {}).get('rights') or []
    if not any(('domaine public' in str(x).lower() or 'public domain' in str(x).lower() or 'domaine_public' in str(x).lower()) for x in rights):
        raise RuntimeError(f'{ark} lost explicit-PD predicate: {rights!r}')
    remote=f'{DEST}/{ark}'; prior=rc_cat(f'{remote}/COMPLETE.json')
    if prior:
        try:
            p=json.loads(prior)
            if p.get('status')=='PASS' and p.get('delivery_mode')=='iiif_pages' and p.get('ark')==ark:
                print('RESULT_JSON='+json.dumps({'ark':ark,'status':'SKIP_COMPLETE','page_count':p.get('page_count'),'image_bytes':p.get('image_bytes')},sort_keys=True)); return 0
        except Exception: pass

    w=Path(args.work_dir); w.mkdir(parents=True,exist_ok=True)
    s=requests.Session(); s.headers['User-Agent']=UA
    manifest_url=f'https://gallica.bnf.fr/iiif/ark:/12148/{ark}/manifest.json'
    pagination_url=f'https://gallica.bnf.fr/services/Pagination?ark={ark}'
    mf=w/'manifest.json'; pg=w/'pagination.xml'
    fetch_bytes(s,manifest_url,mf,'application/json,*/*;q=0.5'); time.sleep(2)
    fetch_bytes(s,pagination_url,pg,'application/xml,text/xml,*/*;q=0.5')
    manifest=json.loads(mf.read_text(encoding='utf-8'))
    canvases=((manifest.get('sequences') or [{}])[0].get('canvases') or [])
    page_count=len(canvases)
    if page_count<=0: raise RuntimeError('manifest has no canvases')
    selected=page_count if not args.max_pages else min(page_count,args.max_pages)
    rc_copyto(mf,f'{remote}/metadata/manifest.json'); rc_copyto(pg,f'{remote}/metadata/pagination.xml')

    checkpoint={'schema_version':'osr-gallica-iiif-checkpoint-v1','ark':ark,'manifest_sha256':sha256(mf),'page_count':page_count,'selected_pages':selected,'done':{}}
    old=rc_cat(f'{remote}/CHECKPOINT.json')
    if old:
        try:
            q=json.loads(old)
            if q.get('ark')==ark and q.get('manifest_sha256')==checkpoint['manifest_sha256']:
                checkpoint['done']=q.get('done') or {}
        except Exception: pass

    index=[]; image_bytes=0
    for i in range(1,selected+1):
        key=str(i); canvas=canvases[i-1]
        if key in checkpoint['done']:
            rec=checkpoint['done'][key]; index.append(rec); image_bytes+=int(rec.get('bytes') or 0); continue
        url=f'https://gallica.bnf.fr/iiif/ark:/12148/{ark}/f{i}/full/full/0/native.jpg'
        out=w/f'f{i:04d}.jpg'
        n,ctype=fetch_bytes(s,url,out,'image/jpeg,image/*;q=0.8')
        with out.open('rb') as f:
            if f.read(2)!=b'\xff\xd8': raise IOError(f'non-JPEG page {i} content-type={ctype}')
        digest=sha256(out)
        rc_copyto(out,f'{remote}/raw/pages/f{i:04d}.jpg')
        rec={'page':i,'canvas_id':canvas.get('@id'),'width':canvas.get('width'),'height':canvas.get('height'),'url':url,'bytes':n,'sha256':digest,'content_type':ctype}
        checkpoint['done'][key]=rec; index.append(rec); image_bytes+=n; out.unlink(missing_ok=True)
        if i%5==0 or i==selected:
            cp=w/'CHECKPOINT.json'; write_json(cp,checkpoint); rc_copyto(cp,f'{remote}/CHECKPOINT.json')
        print(f'PAGE {i}/{selected} bytes={n}',flush=True); time.sleep(2)

    idx=w/'PAGE_INDEX.json'; write_json(idx,{'schema_version':'osr-gallica-iiif-page-index-v1','ark':ark,'page_count':page_count,'selected_pages':selected,'pages':index}); rc_copyto(idx,f'{remote}/PAGE_INDEX.json')
    complete={'schema_version':'osr-gallica-persian-complete-v2','status':'PASS' if selected==page_count else 'PARTIAL_SMOKE','delivery_mode':'iiif_pages','ark':ark,'canonical_url':f'https://gallica.bnf.fr/ark:/12148/{ark}','manifest_url':manifest_url,'pagination_url':pagination_url,'page_count':page_count,'preserved_pages':selected,'image_bytes':image_bytes,'manifest_sha256':sha256(mf),'page_index_sha256':sha256(idx),'rights':rights,'provenance':'bnf.fr','free_access':'Libre','attribution':'Source: gallica.bnf.fr / Bibliothèque nationale de France'}
    c=w/'COMPLETE.json'; write_json(c,complete); rc_copyto(c,f'{remote}/COMPLETE.json')
    print('RESULT_JSON='+json.dumps(complete,ensure_ascii=False,sort_keys=True)); return 0 if complete['status']=='PASS' else 2

if __name__=='__main__': raise SystemExit(main())
