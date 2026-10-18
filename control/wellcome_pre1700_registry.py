#!/usr/bin/env python3
from __future__ import annotations
import hashlib, json, subprocess, sys, time
from pathlib import Path
import requests

API='https://api.wellcomecollection.org/catalogue/v2/works'
ROOT='gdrive:龍族古籍源庫｜Dragon Source Corpus/WELLCOME_PRE1700_RESCUE'
UA='OSR-Preservation/1.0 (+research preservation; contact via repository)'

def dump(path:Path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(obj,ensure_ascii=False,indent=2,sort_keys=True)+'\n',encoding='utf-8')

def sha256_bytes(data:bytes)->str:
    return hashlib.sha256(data).hexdigest()

def sha256_file(path:Path)->str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(8*1024*1024),b''): h.update(b)
    return h.hexdigest()

def rc_copyto(src:Path,dst:str):
    subprocess.run(['rclone','copyto',str(src),dst,'--drive-chunk-size','64M','--retries','8','--low-level-retries','16','--timeout','10m','--contimeout','30s'],check=True)

def rc_cat(path:str)->bytes:
    q=subprocess.run(['rclone','cat',path],capture_output=True)
    if q.returncode: raise RuntimeError(q.stderr.decode('utf-8','replace') or f'rclone cat failed: {path}')
    return q.stdout

def get_json(s:requests.Session,url:str,params=None):
    r=s.get(url,params=params,timeout=(30,300),headers={'Accept':'application/json'})
    r.raise_for_status()
    return r.json(),r.content

def iter_locations(work:dict):
    for item in work.get('items') or []:
        for loc in item.get('locations') or []:
            yield item,loc

def pdm_open(loc:dict)->bool:
    if ((loc.get('license') or {}).get('id') or '').lower()!='pdm': return False
    statuses={((x.get('status') or {}).get('id') or '').lower() for x in (loc.get('accessConditions') or [])}
    return not statuses or bool(statuses & {'open','open-with-advisory'})

def image_count(manifest:dict)->int:
    n=0
    for seq in manifest.get('sequences') or []:
        for canvas in (seq or {}).get('canvases') or []:
            if canvas.get('images'): n+=1
    for canvas in manifest.get('items') or []:
        if any((page or {}).get('items') for page in (canvas or {}).get('items') or []): n+=1
    return n

def manifest_locations(work:dict):
    out=[]
    for item,loc in iter_locations(work):
        if not pdm_open(loc): continue
        url=loc.get('url') or ''
        lt=((loc.get('locationType') or {}).get('id') or '').lower()
        if 'iiif-presentation' not in lt and 'manifest' not in url.lower() and '/iiif/' not in url.lower(): continue
        out.append({
            'item_id':item.get('id'),'manifest_url':url,'locationType':loc.get('locationType'),
            'license':loc.get('license'),'accessConditions':loc.get('accessConditions')
        })
    return out

def main():
    wd=Path(sys.argv[1] if len(sys.argv)>1 else '/tmp/wellcome-registry'); wd.mkdir(parents=True,exist_ok=True)
    s=requests.Session(); s.headers['User-Agent']=UA
    common={
        'items.locations.license':'pdm','availabilities':'online','production.dates.to':'1699-12-31',
        'items.locations.accessConditions.status':'open',
        'include':'items,identifiers,production,genres,languages','pageSize':100,
        'sort':'production.dates','sortOrder':'asc'
    }
    rows=[]; rejected=[]; seen=set(); api_pages=0
    for work_type in ('b','h'):
        page=1
        while True:
            params=dict(common); params['workType']=work_type; params['page']=page
            data,_=get_json(s,API,params); api_pages+=1
            results=data.get('results') or []
            if not results: break
            for work in results:
                wid=work.get('id')
                if not wid or wid in seen: continue
                seen.add(wid)
                locs=manifest_locations(work)
                chosen=None
                for loc in locs:
                    try:
                        manifest,raw=get_json(s,loc['manifest_url'])
                        count=image_count(manifest)
                        if count>0:
                            chosen=(loc,count,sha256_bytes(raw)); break
                    except Exception as e:
                        rejected.append({'id':wid,'manifest_url':loc['manifest_url'],'reason':repr(e)})
                if not chosen:
                    rejected.append({'id':wid,'reason':'no_anonymous_pdm_open_iiif_manifest'})
                    continue
                loc,count,msha=chosen
                rows.append({
                    'schema_version':'osr-wellcome-pre1700-registry-row-v1',
                    'work_id':wid,'title':work.get('title'),'referenceNumber':work.get('referenceNumber'),
                    'workType':work.get('workType'),'production':work.get('production'),
                    'languages':work.get('languages'),'identifiers':work.get('identifiers'),
                    'manifest_url':loc['manifest_url'],'page_count':count,'manifest_sha256_at_registry':msha,
                    'rights_evidence':{'license':loc['license'],'accessConditions':loc['accessConditions'],'item_id':loc['item_id']},
                    'source_work_url':f'{API}/{wid}'
                })
                time.sleep(0.2)
            total=int(data.get('totalResults') or 0)
            if len(results)<int(common['pageSize']) or page*int(common['pageSize'])>=total: break
            page+=1
    rows.sort(key=lambda x:x['work_id'])
    reg=wd/'registry.jsonl'
    reg.write_text(''.join(json.dumps(x,ensure_ascii=False,sort_keys=True)+'\n' for x in rows),encoding='utf-8')
    summary={
        'schema_version':'osr-wellcome-pre1700-registry-v1','status':'PASS' if rows else 'FAIL',
        'query_gate':'production <=1699; online; item location license id=pdm; access open; anonymous IIIF manifest',
        'qualified_items':len(rows),'api_pages':api_pages,'rejected_count':len(rejected),
        'registry_sha256':sha256_file(reg),'total_pages_declared':sum(int(x['page_count']) for x in rows),
        'source':'Wellcome Collection Catalogue API + IIIF','work_types':['b','h']
    }
    dump(wd/'summary.json',summary); dump(wd/'rejected.json',rejected)
    for p in (reg,wd/'summary.json',wd/'rejected.json'):
        rc_copyto(p,f'{ROOT}/registry/{p.name}')
    remote_reg=rc_cat(f'{ROOT}/registry/registry.jsonl')
    remote_summary=json.loads(rc_cat(f'{ROOT}/registry/summary.json').decode('utf-8'))
    remote_rows=[json.loads(x) for x in remote_reg.decode('utf-8').splitlines() if x.strip()]
    if sha256_bytes(remote_reg)!=summary['registry_sha256'] or len(remote_rows)!=len(rows) or remote_summary!=summary:
        raise RuntimeError('Drive registry readback mismatch')
    complete=dict(summary); complete['drive_readback_verified']=True
    dump(wd/'COMPLETE_REGISTRY.json',complete)
    rc_copyto(wd/'COMPLETE_REGISTRY.json',f'{ROOT}/registry/COMPLETE_REGISTRY.json')
    if json.loads(rc_cat(f'{ROOT}/registry/COMPLETE_REGISTRY.json').decode('utf-8'))!=complete:
        raise RuntimeError('Drive COMPLETE_REGISTRY readback mismatch')
    print('RESULT_JSON='+json.dumps(complete,ensure_ascii=False,sort_keys=True),flush=True)
    return 0 if complete['status']=='PASS' else 2

if __name__=='__main__': raise SystemExit(main())
