#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, subprocess, time
from pathlib import Path
import requests

API='https://api.wellcomecollection.org/catalogue/v2/works'
ROOT='gdrive:龍族古籍源庫｜Dragon Source Corpus/WELLCOME_PRE1700_RESCUE'
REGISTRY=f'{ROOT}/registry/registry.jsonl'
DEST=f'{ROOT}/items'
UA='OSR-Preservation/1.0 (+research preservation; contact via repository)'

def dump(path:Path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(obj,ensure_ascii=False,indent=2,sort_keys=True)+'\n',encoding='utf-8')

def hashes(path:Path):
    hs=hashlib.sha256(); hm=hashlib.md5()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(8*1024*1024),b''): hs.update(b); hm.update(b)
    return hs.hexdigest(),hm.hexdigest()

def rc_copyto(src:Path,dst:str):
    subprocess.run(['rclone','copyto',str(src),dst,'--drive-chunk-size','64M','--retries','8','--low-level-retries','16','--timeout','10m','--contimeout','30s'],check=True)

def rc_cat(path:str)->bytes|None:
    q=subprocess.run(['rclone','cat',path],capture_output=True)
    return q.stdout if q.returncode==0 else None

def remote_stat(path:str):
    q=subprocess.run(['rclone','lsjson',path,'--hash','--files-only'],text=True,capture_output=True)
    if q.returncode: return None
    obj=json.loads(q.stdout or '[]')
    if isinstance(obj,list): obj=obj[0] if obj else None
    return obj

def remote_matches(path:str,size:int,md5:str)->bool:
    obj=remote_stat(path)
    if not obj or int(obj.get('Size') or -1)!=size: return False
    hs=obj.get('Hashes') or obj.get('hashes') or {}
    got=(hs.get('MD5') or hs.get('md5') or '').lower()
    return got==md5.lower()

def pdm_open(loc:dict)->bool:
    if ((loc.get('license') or {}).get('id') or '').lower()!='pdm': return False
    statuses={((x.get('status') or {}).get('id') or '').lower() for x in (loc.get('accessConditions') or [])}
    return not statuses or bool(statuses & {'open','open-with-advisory'})

def manifest_locations(work:dict):
    for item in work.get('items') or []:
        for loc in item.get('locations') or []:
            if not pdm_open(loc): continue
            url=loc.get('url') or ''; lt=((loc.get('locationType') or {}).get('id') or '').lower()
            if 'iiif-presentation' in lt or 'manifest' in url.lower() or '/iiif/' in url.lower():
                yield item,loc

def extract_images(manifest:dict):
    out=[]
    for seq in manifest.get('sequences') or []:
        for canvas in (seq or {}).get('canvases') or []:
            images=canvas.get('images') or []
            if not images: continue
            res=(images[0] or {}).get('resource') or {}; svc=res.get('service')
            if isinstance(svc,list): svc=svc[0] if svc else {}
            out.append({'canvas_id':canvas.get('@id') or canvas.get('id'),'width':canvas.get('width'),'height':canvas.get('height'),
                        'service':(svc or {}).get('@id') or (svc or {}).get('id'),'direct':res.get('@id') or res.get('id')})
    for canvas in manifest.get('items') or []:
        body=None
        for page in canvas.get('items') or []:
            anns=(page or {}).get('items') or []
            if anns: body=(anns[0] or {}).get('body') or {}; break
        if body is None: continue
        svc=body.get('service') or []
        if isinstance(svc,dict): svc=[svc]
        one=svc[0] if svc else {}
        out.append({'canvas_id':canvas.get('id') or canvas.get('@id'),'width':canvas.get('width'),'height':canvas.get('height'),
                    'service':one.get('id') or one.get('@id'),'direct':body.get('id') or body.get('@id')})
    return out

def get_json(s:requests.Session,url:str,params=None):
    r=s.get(url,params=params,timeout=(30,300),headers={'Accept':'application/json','Accept-Encoding':'identity'})
    r.raise_for_status()
    return r.json(),r.content

def get_manifest_json(s:requests.Session,url:str):
    candidates=[url]
    if url.startswith('https://iiif.wellcomecollection.org/presentation/v2/'):
        candidates += [
            url.replace('/presentation/v2/','/presentation/v3/',1),
            url.replace('/presentation/v2/','/presentation/',1),
        ]
    failures=[]
    for candidate in dict.fromkeys(candidates):
        for attempt in range(1,5):
            r=s.get(candidate,timeout=(30,300),headers={
                'Accept':'application/ld+json,application/json;q=0.9',
                'Accept-Encoding':'identity',
            })
            if r.status_code==200:
                return r.json(),r.content,candidate
            failures.append({'url':candidate,'status':r.status_code,'attempt':attempt})
            if r.status_code in (429,503):
                raw=r.headers.get('Retry-After')
                try: wait=max(1,min(300,int(raw))) if raw else min(120,10*(2**(attempt-1)))
                except ValueError: wait=min(120,10*(2**(attempt-1)))
                print(f'MANIFEST_RETRY status={r.status_code} sleep={wait}s url={candidate}',flush=True)
                time.sleep(wait)
                continue
            if r.status_code==403:
                # A same-identity official route can recover after a short edge/CDN cooldown.
                # Retry it once only; do not change identity, headers, or access method.
                if attempt==1:
                    wait=60
                    print(f'MANIFEST_403_COOLDOWN sleep={wait}s url={candidate}',flush=True)
                    time.sleep(wait)
                    continue
                break
            if r.status_code==404:
                break
            r.raise_for_status()
    raise RuntimeError('official IIIF manifest unavailable without access bypass: '+json.dumps(failures,sort_keys=True))

def download_image(s:requests.Session,entry:dict,out:Path):
    urls=[]
    if entry.get('service'):
        base=entry['service'].rstrip('/')
        urls.extend([base+'/full/max/0/default.jpg',base+'/full/full/0/default.jpg'])
    if entry.get('direct'): urls.append(entry['direct'])
    last=None
    for attempt in range(1,9):
        for url in urls:
            tmp=out.with_suffix('.part'); tmp.unlink(missing_ok=True)
            try:
                with s.get(url,stream=True,timeout=(30,900),headers={'Accept':'image/jpeg,image/*;q=0.8','Accept-Encoding':'identity'}) as r:
                    if r.status_code in (429,503):
                        wait=min(300,15*(2**min(attempt,4))); print(f'RATE_LIMIT {r.status_code} sleep={wait}s',flush=True); time.sleep(wait); continue
                    r.raise_for_status()
                    with tmp.open('wb') as f:
                        for chunk in r.iter_content(4*1024*1024):
                            if chunk: f.write(chunk)
                if tmp.read_bytes()[:3]!=b'\xff\xd8\xff': raise IOError('non-JPEG payload')
                tmp.replace(out); sha,md5=hashes(out)
                return {'url':url,'bytes':out.stat().st_size,'sha256':sha,'md5':md5,'content_type':'image/jpeg'}
            except Exception as e:
                last=e; tmp.unlink(missing_ok=True)
        time.sleep(min(120,5*(2**min(attempt,4))))
    raise RuntimeError(f'no official image derivative: {last!r}')

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--work-id',required=True); ap.add_argument('--work-dir',required=True); a=ap.parse_args()
    rows=[json.loads(x) for x in (rc_cat(REGISTRY) or b'').decode('utf-8').splitlines() if x.strip()]
    row=next((x for x in rows if x.get('work_id')==a.work_id),None)
    if not row: raise RuntimeError(f'{a.work_id} absent from verified registry')
    remote=f'{DEST}/{a.work_id}'
    prior=rc_cat(f'{remote}/COMPLETE.json')
    if prior:
        obj=json.loads(prior)
        if obj.get('status')=='PASS' and obj.get('work_id')==a.work_id and obj.get('drive_readback_verified') is True:
            print('RESULT_JSON='+json.dumps({'status':'SKIP_COMPLETE','work_id':a.work_id,'page_count':obj.get('page_count'),'image_bytes':obj.get('image_bytes')},sort_keys=True)); return 0

    wd=Path(a.work_dir); wd.mkdir(parents=True,exist_ok=True)
    s=requests.Session(); s.headers['User-Agent']=UA
    work,work_raw=get_json(s,f'{API}/{a.work_id}',{'include':'items,identifiers,production,genres,languages'})
    valid=[]
    for item,loc in manifest_locations(work):
        if loc.get('url')==row.get('manifest_url'): valid.append((item,loc))
    if not valid: raise RuntimeError('item lost exact PDM/open manifest location')
    item,loc=valid[0]
    manifest,manifest_raw,manifest_url_retrieved=get_manifest_json(s,row['manifest_url'])
    images=extract_images(manifest)
    if not images or len(images)!=int(row.get('page_count') or -1):
        raise RuntimeError(f'manifest page-count drift {len(images)} != {row.get("page_count")}')
    work_path=wd/'work.json'; manifest_path=wd/'manifest.json'
    work_path.write_bytes(work_raw); manifest_path.write_bytes(manifest_raw)
    msha,_=hashes(manifest_path)
    rc_copyto(work_path,f'{remote}/metadata/work.json'); rc_copyto(manifest_path,f'{remote}/metadata/manifest.json')

    checkpoint={'schema_version':'osr-wellcome-pre1700-checkpoint-v1','work_id':a.work_id,'manifest_sha256':msha,'page_count':len(images),'done':{}}
    old=rc_cat(f'{remote}/CHECKPOINT.json')
    if old:
        try:
            q=json.loads(old)
            if q.get('work_id')==a.work_id and q.get('manifest_sha256')==msha: checkpoint['done']=q.get('done') or {}
        except Exception: pass

    page_index=[]; total=0
    for i,entry in enumerate(images,1):
        key=str(i); dst=f'{remote}/raw/pages/page-{i:04d}.jpg'; rec=checkpoint['done'].get(key)
        if rec and remote_matches(dst,int(rec.get('bytes') or 0),rec.get('md5') or ''):
            page_index.append(rec); total+=int(rec['bytes']); continue
        out=wd/f'page-{i:04d}.jpg'; got=download_image(s,entry,out)
        rc_copyto(out,dst)
        if not remote_matches(dst,got['bytes'],got['md5']): raise RuntimeError(f'Drive fingerprint mismatch page {i}')
        rec={'page':i,'canvas_id':entry.get('canvas_id'),'width':entry.get('width'),'height':entry.get('height'),**got,'drive_readback_verified':True}
        checkpoint['done'][key]=rec; page_index.append(rec); total+=got['bytes']
        cp=wd/'CHECKPOINT.json'; dump(cp,checkpoint); rc_copyto(cp,f'{remote}/CHECKPOINT.json')
        out.unlink(missing_ok=True); print(f'PAGE {i}/{len(images)} bytes={got["bytes"]}',flush=True); time.sleep(0.5)

    index={'schema_version':'osr-wellcome-pre1700-page-index-v1','work_id':a.work_id,'page_count':len(images),'pages':page_index}
    idx=wd/'PAGE_INDEX.json'; dump(idx,index); rc_copyto(idx,f'{remote}/PAGE_INDEX.json')
    idx_sha,_=hashes(idx)
    complete={
        'schema_version':'osr-wellcome-pre1700-complete-v1','status':'PASS','work_id':a.work_id,
        'title':work.get('title'),'referenceNumber':work.get('referenceNumber'),'page_count':len(images),
        'image_bytes':total,'manifest_url':row['manifest_url'],'manifest_url_retrieved':manifest_url_retrieved,'manifest_sha256':msha,'page_index_sha256':idx_sha,
        'rights_evidence':{'license':loc.get('license'),'accessConditions':loc.get('accessConditions'),'item_id':item.get('id')},
        'rights_gate':'item location license id=pdm; open access; anonymous official IIIF retrieval',
        'source_work_url':f'{API}/{a.work_id}','retrieval_mode':'official_iiif_pages','drive_readback_verified':True
    }
    cp=wd/'COMPLETE.json'; dump(cp,complete); rc_copyto(cp,f'{remote}/COMPLETE.json')
    back=rc_cat(f'{remote}/COMPLETE.json')
    if not back or json.loads(back)!=complete: raise RuntimeError('Drive COMPLETE readback mismatch')
    print('RESULT_JSON='+json.dumps(complete,ensure_ascii=False,sort_keys=True),flush=True)
    return 0

if __name__=='__main__': raise SystemExit(main())
