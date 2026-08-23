#!/usr/bin/env python3
from __future__ import annotations
import gzip, hashlib, json, re, time
from collections import Counter, defaultdict
from pathlib import Path
import pyarrow.parquet as pq
import requests
from huggingface_hub import HfApi, hf_hub_url

SOURCES=[('Literature-zh','Geralt-Targaryen/Literature-zh'),('ChineseWebText2.0-HighQuality','Morton-Li/ChineseWebText2.0-HighQuality')]
DATE_RE=re.compile(r'(?:公元前|前)?\d{2,4}年|(?:春秋|战国|秦|汉|魏|晋|隋|唐|宋|元|明|清)[初中晚末]?期?')
PLACE_RE=re.compile(r'[\u4e00-\u9fff]{2,8}(?:山|河|江|湖|州|郡|县|國|国|城|村|寨|府)')

def download(repo, fn, dest):
    u=hf_hub_url(repo,filename=fn,repo_type='dataset'); h=hashlib.sha256(); n=0; t=time.time()
    with requests.get(u,stream=True,timeout=(30,240)) as r:
        r.raise_for_status()
        with open(dest,'wb') as f:
            for b in r.iter_content(8*1024*1024):
                if b: f.write(b); h.update(b); n+=len(b)
    return n,time.time()-t,h.hexdigest()

def text_col(pf):
    names=[f.name for f in pf.schema_arrow if str(f.type) in {'string','large_string'}]
    for n in ('text','content','body'):
        if n in names:return n
    return names[0]

def main():
    pack=json.load(open('control/stage2_query_pack.json',encoding='utf-8'))
    schema=json.load(open('control/m3_feature_schema.json',encoding='utf-8'))
    terms=list(dict.fromkeys(pack['terms'])); motifs=schema['motif_map']
    output={'format':'osr-m3-feature-smoke/v1','started_unix':time.time(),'files':[]}
    total_raw=0
    for source,repo in SOURCES:
        files=sorted(x for x in HfApi().list_repo_files(repo,repo_type='dataset') if x.endswith('.parquet'))
        fn=files[-1]; local=Path('/tmp')/('m3-'+source.replace('/','_')+'.parquet')
        nb,ds,fsha=download(repo,fn,local); total_raw+=nb
        pf=pq.ParquetFile(local); col=text_col(pf)
        term_counts=Counter(); pair_counts=Counter(); motif_counts=Counter(); date_counts=Counter(); place_counts=Counter()
        pair_samples=defaultdict(list); temporal_samples=defaultdict(list); place_samples=defaultdict(list); motif_samples=defaultdict(list)
        rows=chars=0; global_row=0; t0=time.time()
        for batch in pf.iter_batches(batch_size=256,columns=[col]):
            arr=batch.column(0)
            for i in range(len(arr)):
                text=arr[i].as_py(); row=global_row; global_row+=1
                if not isinstance(text,str) or not text: continue
                rows+=1; chars+=len(text); rh=None
                present=[t for t in terms if t in text]
                for t in present: term_counts[t]+=text.count(t)
                unique=sorted(set(present))
                for a_i,a in enumerate(unique):
                    for b in unique[a_i+1:]:
                        pair=(a,b); pair_counts[pair]+=1
                        if len(pair_samples[pair])<3:
                            if rh is None: rh=hashlib.sha256(text.encode()).hexdigest()
                            pair_samples[pair].append({'row':row,'row_sha256':rh})
                for m, mts in motifs.items():
                    matched=sorted(t for t in mts if t in text)
                    if matched:
                        motif_counts[m]+=1
                        if len(motif_samples[m])<3:
                            if rh is None: rh=hashlib.sha256(text.encode()).hexdigest()
                            motif_samples[m].append({'row':row,'row_sha256':rh,'matched_terms':matched})
                for s in DATE_RE.findall(text):
                    date_counts[s]+=1
                    if len(temporal_samples[s])<2:
                        if rh is None: rh=hashlib.sha256(text.encode()).hexdigest()
                        temporal_samples[s].append({'row':row,'row_sha256':rh})
                for s in PLACE_RE.findall(text):
                    place_counts[s]+=1
                    if len(place_samples[s])<2:
                        if rh is None: rh=hashlib.sha256(text.encode()).hexdigest()
                        place_samples[s].append({'row':row,'row_sha256':rh})
        rec={'source':source,'repo':repo,'file':fn,'file_sha256':fsha,'download_bytes':nb,'download_seconds':round(ds,3),'rows_scanned':rows,'chars_scanned':chars,'scan_seconds':round(time.time()-t0,3),
             'entity_term_counts':dict(term_counts),'top_cooccurrence':[{'terms':list(k),'row_count':v,'sample_locators':pair_samples[k]} for k,v in pair_counts.most_common(100)],
             'motifs':{k:{'row_count':v,'samples':motif_samples[k]} for k,v in motif_counts.items()},
             'temporal_hints':[{'surface':k,'count':v,'samples':temporal_samples[k]} for k,v in date_counts.most_common(100)],
             'place_hints':[{'surface':k,'count':v,'samples':place_samples[k]} for k,v in place_counts.most_common(100)]}
        output['files'].append(rec); local.unlink(missing_ok=True)
    output['finished_unix']=time.time(); raw=json.dumps(output,ensure_ascii=False,separators=(',',':')).encode()
    Path('control/m3_feature_smoke_result.json.gz').write_bytes(gzip.compress(raw,compresslevel=9))
    summary={'status':'PASS','files':len(output['files']),'raw_bytes_downloaded':total_raw,'feature_result_bytes':Path('control/m3_feature_smoke_result.json.gz').stat().st_size,'compression_ratio_vs_raw':round(Path('control/m3_feature_smoke_result.json.gz').stat().st_size/total_raw,8),'sources':[{'source':x['source'],'file':x['file'],'rows':x['rows_scanned'],'chars':x['chars_scanned'],'scan_seconds':x['scan_seconds'],'entity_terms':len(x['entity_term_counts']),'cooccurrence_pairs':len(x['top_cooccurrence']),'motifs':len(x['motifs']),'temporal_hints':len(x['temporal_hints']),'place_hints':len(x['place_hints'])} for x in output['files']]}
    Path('control/m3_feature_smoke_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False,indent=2))
if __name__=='__main__': main()
