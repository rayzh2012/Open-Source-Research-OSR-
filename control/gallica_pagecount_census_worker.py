#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, subprocess, time
from pathlib import Path
import requests

ROOT='gdrive:龍族古籍源庫｜Dragon Source Corpus/ISLAMIC_PERSIAN_RESCUE/gallica_persian_manuscripts'
PD_LIST=f'{ROOT}/rights_audit/explicit_public_domain.txt'


def cat(path:str)->str:
    p=subprocess.run(['rclone','cat',path],text=True,capture_output=True,check=True)
    return p.stdout


def copyto(src:Path,dst:str):
    subprocess.run(['rclone','copyto',str(src),dst,'--retries','8','--low-level-retries','16','--timeout','10m','--contimeout','30s'],check=True)


def get_manifest(s:requests.Session,ark:str,attempts:int=8):
    url=f'https://gallica.bnf.fr/iiif/ark:/12148/{ark}/manifest.json'
    last=None
    for attempt in range(1,attempts+1):
        try:
            r=s.get(url,timeout=(20,90),headers={'Accept':'application/json,*/*;q=0.5','Accept-Encoding':'identity'})
            if r.status_code in (429,503):
                wait=min(300,10*(2**min(attempt,4)))
                print(f'RATE_LIMIT ark={ark} status={r.status_code} sleep={wait}',flush=True)
                time.sleep(wait); continue
            r.raise_for_status()
            raw=r.content; m=r.json()
            canvases=((m.get('sequences') or [{}])[0].get('canvases') or [])
            dims=[(int(c.get('width') or 0),int(c.get('height') or 0)) for c in canvases]
            return {
                'ark':ark,
                'status':'PASS',
                'page_count':len(canvases),
                'max_width':max((w for w,_ in dims),default=0),
                'max_height':max((h for _,h in dims),default=0),
                'manifest_bytes':len(raw),
                'manifest_sha256':hashlib.sha256(raw).hexdigest(),
                'manifest_url':url,
            }
        except Exception as e:
            last=e
            wait=min(120,5*(2**min(attempt,4)))
            print(f'RETRY ark={ark} attempt={attempt}/{attempts} error={e!r} sleep={wait}',flush=True)
            time.sleep(wait)
    return {'ark':ark,'status':'FAILED','error':repr(last)}


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--partition',type=int,required=True)
    ap.add_argument('--partitions',type=int,required=True)
    ap.add_argument('--sleep-seconds',type=float,default=2.5)
    ap.add_argument('--destination',required=True)
    ap.add_argument('--work-dir',required=True)
    a=ap.parse_args()
    if not (0 <= a.partition < a.partitions): raise SystemExit('bad partition')
    arks=sorted({x.strip() for x in cat(PD_LIST).splitlines() if x.strip()})
    if len(arks)!=1472: raise RuntimeError(f'expected 1472 ARKs, got {len(arks)}')
    targets=[ark for i,ark in enumerate(arks) if i % a.partitions == a.partition]
    remote=f'gdrive:{a.destination}/parts/part-{a.partition:02d}'
    prior=subprocess.run(['rclone','cat',remote+'/COMPLETE.json'],text=True,capture_output=True)
    if prior.returncode==0:
        try:
            p=json.loads(prior.stdout)
            if p.get('status')=='PASS' and int(p.get('expected') or -1)==len(targets):
                print('RESULT_JSON='+json.dumps({'status':'SKIP_COMPLETE','partition':a.partition,'count':len(targets)},sort_keys=True)); return 0
        except Exception: pass

    s=requests.Session(); s.headers['User-Agent']='OSR-Preservation/1.0 (+noncommercial research preservation; polite IIIF census)'
    rows=[]
    for n,ark in enumerate(targets,1):
        row=get_manifest(s,ark); rows.append(row)
        print(f'CENSUS partition={a.partition} item={n}/{len(targets)} ark={ark} status={row.get("status")} pages={row.get("page_count")}',flush=True)
        if n < len(targets): time.sleep(max(0,a.sleep_seconds))

    wd=Path(a.work_dir); wd.mkdir(parents=True,exist_ok=True)
    data=wd/f'part-{a.partition:02d}.jsonl'
    data.write_text(''.join(json.dumps(x,ensure_ascii=False,sort_keys=True)+'\n' for x in rows),encoding='utf-8')
    passed=[x for x in rows if x.get('status')=='PASS' and int(x.get('page_count') or 0)>0]
    failed=[x for x in rows if x.get('status')!='PASS' or int(x.get('page_count') or 0)<=0]
    summary={
        'schema_version':'osr-gallica-pagecount-census-part-v1',
        'status':'PASS' if len(passed)==len(targets) and not failed else 'FAILED',
        'partition':a.partition,'partitions':a.partitions,'expected':len(targets),
        'passed':len(passed),'failed':len(failed),
        'total_pages':sum(int(x.get('page_count') or 0) for x in passed),
        'min_pages':min((int(x.get('page_count') or 0) for x in passed),default=0),
        'max_pages':max((int(x.get('page_count') or 0) for x in passed),default=0),
        'failed_arks':[x.get('ark') for x in failed],
        'jsonl_sha256':hashlib.sha256(data.read_bytes()).hexdigest(),
    }
    comp=wd/'COMPLETE.json'; comp.write_text(json.dumps(summary,ensure_ascii=False,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    copyto(data,remote+'/part.jsonl'); copyto(comp,remote+'/COMPLETE.json')
    print('RESULT_JSON='+json.dumps(summary,ensure_ascii=False,sort_keys=True))
    return 0 if summary['status']=='PASS' else 2

if __name__=='__main__': raise SystemExit(main())
