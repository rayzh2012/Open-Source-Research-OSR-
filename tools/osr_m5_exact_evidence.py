#!/usr/bin/env python3
import hashlib, json, pathlib, requests
import pyarrow.parquet as pq
from huggingface_hub import hf_hub_url

REQ=pathlib.Path('control/m5_exact_evidence_request.json')
req=json.loads(REQ.read_text('utf-8'))
router=json.loads(pathlib.Path(req['router_result']).read_text('utf-8'))
terms=req['terms']; top_n=int(req.get('top_n_shards',12)); cap=int(req.get('max_rows_per_shard',20)); ctx=int(req.get('context_chars',260))
rows=[]; bytes_dl=0
for rank,sh in enumerate(router['ranked_shards'][:top_n],1):
    repo=sh['repo']; fn=sh['file']; local=pathlib.Path('/tmp')/f'evidence-{rank}.parquet'
    url=hf_hub_url(repo, filename=fn, repo_type='dataset')
    with requests.get(url,stream=True,timeout=(30,240)) as r:
        r.raise_for_status(); h=hashlib.sha256(); total=0
        with local.open('wb') as f:
            for b in r.iter_content(8*1024*1024):
                if b: f.write(b); h.update(b); total+=len(b)
    bytes_dl+=total
    pf=pq.ParquetFile(local); names=[f.name for f in pf.schema_arrow if str(f.type) in {'string','large_string'}]
    col='text' if 'text' in names else names[0]
    found=0; global_row=0
    for batch in pf.iter_batches(batch_size=256,columns=[col]):
        arr=batch.column(0)
        for i in range(len(arr)):
            text=arr[i].as_py(); ridx=global_row; global_row+=1
            if not isinstance(text,str) or not text: continue
            present=[t for t in terms if t in text]
            if len(present)<2: continue
            pos=min(text.find(t) for t in present if text.find(t)>=0)
            start=max(0,pos-ctx); end=min(len(text),pos+ctx)
            rows.append({'ranked_shard':rank,'source':sh['source'],'repo':repo,'file':fn,'row':ridx,'row_sha256':hashlib.sha256(text.encode()).hexdigest(),'matched_terms':present,'matched_term_count':len(present),'snippet':text[start:end]})
            found+=1
            if found>=cap: break
        if found>=cap: break
    local.unlink(missing_ok=True)

rows.sort(key=lambda r:(-r['matched_term_count'], r['ranked_shard'], r['row']))
out={'format':'osr-exact-evidence/v1','run_id':req['run_id'],'terms':terms,'top_n_shards':top_n,'rows_found':len(rows),'bytes_downloaded':bytes_dl,'rows':rows}
pathlib.Path('control/m5_exact_evidence_result.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n','utf-8')
summary={'status':'PASS','run_id':req['run_id'],'top_n_shards':top_n,'rows_found':len(rows),'bytes_downloaded':bytes_dl,'all_5_term_rows':sum(1 for r in rows if r['matched_term_count']==5),'four_plus_term_rows':sum(1 for r in rows if r['matched_term_count']>=4)}
pathlib.Path('control/m5_exact_evidence_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n','utf-8')
print(json.dumps(summary,ensure_ascii=False))
