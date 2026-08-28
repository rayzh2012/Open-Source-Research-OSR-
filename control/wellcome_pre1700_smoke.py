#!/usr/bin/env python3
from __future__ import annotations
import hashlib, json, os, subprocess, sys, time
from pathlib import Path
from urllib.parse import urljoin
import requests

API='https://api.wellcomecollection.org/catalogue/v2/works'
ROOT='gdrive:龍族古籍源庫｜Dragon Source Corpus/WELLCOME_PRE1700_RESCUE'


def dump(p:Path,obj):
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(obj,ensure_ascii=False,indent=2,sort_keys=True)+'\n',encoding='utf-8')

def sha256(p:Path):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(8*1024*1024),b''): h.update(b)
    return h.hexdigest()

def run(cmd:list[str]):
    print('+',' '.join(cmd),flush=True)
    subprocess.run(cmd,check=True)

def get_json(s:requests.Session,url:str,params=None):
    r=s.get(url,params=params,timeout=(30,180))
    r.raise_for_status()
    return r.json()

def iter_locations(work:dict):
    for item in work.get('items') or []:
        for loc in item.get('locations') or []:
            yield item,loc

def pdm_open(loc:dict)->bool:
    lic=(loc.get('license') or {}).get('id')
    conds=loc.get('accessConditions') or []
    statuses={(c.get('status') or {}).get('id') for c in conds}
    return lic=='pdm' and (not statuses or 'open' in statuses or 'open-with-advisory' in statuses)

def extract_image_services(manifest:dict):
    out=[]
    # IIIF v2
    for seq in manifest.get('sequences') or []:
        for canvas in (seq or {}).get('canvases') or []:
            for ann in canvas.get('images') or []:
                res=(ann or {}).get('resource') or {}
                svc=res.get('service')
                if isinstance(svc,list): svc=svc[0] if svc else None
                sid=(svc or {}).get('@id') or (svc or {}).get('id') if isinstance(svc,dict) else None
                direct=res.get('@id') or res.get('id')
                out.append({'service':sid,'direct':direct,'canvas':canvas.get('@id') or canvas.get('id')})
    # IIIF v3
    for canvas in manifest.get('items') or []:
        for page in (canvas or {}).get('items') or []:
            for ann in (page or {}).get('items') or []:
                body=(ann or {}).get('body') or {}
                svcs=body.get('service') or []
                if isinstance(svcs,dict): svcs=[svcs]
                svc=svcs[0] if svcs else {}
                sid=(svc or {}).get('id') or (svc or {}).get('@id')
                direct=body.get('id') or body.get('@id')
                out.append({'service':sid,'direct':direct,'canvas':canvas.get('id') or canvas.get('@id')})
    # stable de-dupe
    seen=set(); ded=[]
    for x in out:
        k=(x.get('service'),x.get('direct'),x.get('canvas'))
        if k in seen: continue
        seen.add(k); ded.append(x)
    return ded

def download_first_image(s:requests.Session,entry:dict,out:Path):
    urls=[]
    if entry.get('service'):
        base=entry['service'].rstrip('/')
        urls += [base+'/full/max/0/default.jpg', base+'/full/full/0/default.jpg']
    if entry.get('direct'): urls.append(entry['direct'])
    last=None
    for url in urls:
        try:
            with s.get(url,stream=True,timeout=(30,600)) as r:
                if r.status_code!=200:
                    last=f'HTTP {r.status_code} {url}'; continue
                ctype=(r.headers.get('Content-Type') or '').lower()
                with out.open('wb') as f:
                    for chunk in r.iter_content(4*1024*1024):
                        if chunk: f.write(chunk)
            prefix=out.read_bytes()[:16]
            if not (prefix.startswith(b'\xff\xd8\xff') or prefix.startswith(b'\x89PNG') or prefix[:4] in (b'GIF8',b'RIFF')):
                last=f'non-image payload {url} prefix={prefix!r} ctype={ctype}'; out.unlink(missing_ok=True); continue
            return {'url':url,'content_type':ctype,'bytes':out.stat().st_size,'sha256':sha256(out)}
        except Exception as e:
            last=repr(e); out.unlink(missing_ok=True)
    raise RuntimeError(f'no downloadable image derivative: {last}')

def main():
    wd=Path(sys.argv[1] if len(sys.argv)>1 else '/tmp/wellcome-pre1700'); wd.mkdir(parents=True,exist_ok=True)
    s=requests.Session(); s.headers['User-Agent']='OSR-Preservation/1.0 (+research preservation; contact via repository)'
    base_params={
        'items.locations.license':'pdm',
        'availabilities':'online',
        'production.dates.to':'1699-12-31',
        'items.locations.accessConditions.status':'open',
        'include':'items,identifiers,production,genres,languages',
        'aggregations':'workType,items.locations.license',
        'pageSize':100,
        'sort':'production.dates',
        'sortOrder':'asc',
    }
    first=get_json(s,API,base_params)
    buckets=((first.get('aggregations') or {}).get('workType') or {}).get('buckets') or []
    manuscript_ids=[]
    for b in buckets:
        data=b.get('data') or {}; label=(data.get('label') or '').lower(); wid=data.get('id')
        if wid and ('manuscript' in label or 'archive' in label): manuscript_ids.append(wid)
    summary0={'total_pre1700_pdm_online':first.get('totalResults'),'workType_buckets':buckets,'candidate_workType_ids':manuscript_ids}
    dump(wd/'discovery.json',summary0)
    if not manuscript_ids:
        raise RuntimeError('No manuscript/archive-like workType bucket found; inspect discovery.json before broadening.')

    candidates=[]
    for wid in manuscript_ids:
        params=dict(base_params); params.pop('aggregations',None); params['workType']=wid; params['pageSize']=25
        page=get_json(s,API,params)
        for work in page.get('results') or []:
            pdloc=[]
            for item,loc in iter_locations(work):
                if pdm_open(loc):
                    pdloc.append({'item_id':item.get('id'),'url':loc.get('url'),'locationType':loc.get('locationType'),'license':loc.get('license'),'accessConditions':loc.get('accessConditions')})
            if pdloc:
                candidates.append({'id':work.get('id'),'title':work.get('title'),'referenceNumber':work.get('referenceNumber'),'workType':work.get('workType'),'production':work.get('production'),'locations':pdloc})
    dump(wd/'candidates.json',candidates)
    if not candidates: raise RuntimeError('No PDM/open manuscript candidates after item-level recheck')

    chosen=None; manifest=None; manifest_url=None; images=[]
    for cand in candidates:
        for loc in cand['locations']:
            lt=((loc.get('locationType') or {}).get('id') or '').lower()
            url=loc.get('url') or ''
            if 'iiif-presentation' in lt or 'manifest' in url.lower() or '/iiif/' in url.lower():
                try:
                    obj=get_json(s,url)
                    imgs=extract_image_services(obj)
                    if imgs:
                        chosen=cand; manifest=obj; manifest_url=url; images=imgs; break
                except Exception as e:
                    print('MANIFEST_FAIL',cand['id'],url,repr(e),flush=True)
        if chosen: break
    if not chosen: raise RuntimeError('No candidate exposed a usable anonymous IIIF Presentation manifest')

    itemdir=wd/chosen['id']; itemdir.mkdir(parents=True,exist_ok=True)
    dump(itemdir/'work.json',chosen); dump(itemdir/'manifest.json',manifest)
    img_path=itemdir/'page-0001.jpg'; im=download_first_image(s,images[0],img_path)
    complete={
        'schema_version':'osr-wellcome-pre1700-smoke-v1','status':'PASS','scope':'SMOKE_ONLY_NOT_FULL_ITEM',
        'work_id':chosen['id'],'title':chosen.get('title'),'referenceNumber':chosen.get('referenceNumber'),
        'manifest_url':manifest_url,'manifest_sha256':sha256(itemdir/'manifest.json'),'page_count_detected':len(images),
        'sample_image':im,'rights_gate':'item location license id=pdm; open access; anonymous retrieval',
        'source':'Wellcome Collection Catalogue API + IIIF','source_policy':'Respect per-item licence; this smoke only accepts Public Domain Mark locations.',
    }
    dump(itemdir/'COMPLETE_SMOKE.json',complete)
    for p in [wd/'discovery.json',wd/'candidates.json',itemdir/'work.json',itemdir/'manifest.json',img_path,itemdir/'COMPLETE_SMOKE.json']:
        rel=p.relative_to(wd)
        run(['rclone','copyto',str(p),f'{ROOT}/smoke/{rel.as_posix()}','--drive-chunk-size','64M','--retries','8','--low-level-retries','16','--timeout','10m','--contimeout','30s'])
    print('RESULT_JSON='+json.dumps(complete,ensure_ascii=False,sort_keys=True),flush=True)
    return 0

if __name__=='__main__': raise SystemExit(main())
