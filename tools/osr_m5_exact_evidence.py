#!/usr/bin/env python3
import hashlib, json, pathlib, re, requests
import pyarrow.parquet as pq
from huggingface_hub import hf_hub_url

REQ=pathlib.Path('control/m5_exact_evidence_request.json')
CURRENT=pathlib.Path('control/m5_exact_evidence_result.json')
CURRENT_SUMMARY=pathlib.Path('control/m5_exact_evidence_summary.json')
ARCHIVE_ROOT=pathlib.Path('control/research_runs')

req=json.loads(REQ.read_text('utf-8'))
router=json.loads(pathlib.Path(req['router_result']).read_text('utf-8'))
expected=req.get('expected_router_run_id')
if expected and router.get('run_id') != expected:
    raise RuntimeError(f"router run mismatch: expected {expected}, got {router.get('run_id')}")

# Preserve the previous current-pointer result before replacing it.
if CURRENT.exists():
    previous=json.loads(CURRENT.read_text('utf-8'))
    previous_run=previous.get('run_id')
    if previous_run:
        d=ARCHIVE_ROOT/previous_run
        d.mkdir(parents=True,exist_ok=True)
        p=d/'exact_evidence.json'
        if not p.exists(): p.write_text(CURRENT.read_text('utf-8'),'utf-8')
        if CURRENT_SUMMARY.exists() and not (d/'exact_evidence_summary.json').exists():
            (d/'exact_evidence_summary.json').write_text(CURRENT_SUMMARY.read_text('utf-8'),'utf-8')

terms=list(req['terms'])
top_n=int(req.get('top_n_shards',12))
cap=int(req.get('max_rows_per_shard',20))
ctx=int(req.get('context_chars',260))
min_local=int(req.get('min_local_terms',1))
max_occurrences_per_term=int(req.get('max_occurrences_per_term',8))
head_chars=int(req.get('document_head_chars',600))
rows=[]; bytes_dl=0

META_NAME_RE=re.compile(r'(^|_)(title|name|author|creator|source|book|journal|publication|publisher|date|year|time|url|uri|id|document_id|doc_id)($|_)',re.I)

def best_window(text,present):
    centers=[]
    for t in present:
        start=0; seen=0
        while seen < max_occurrences_per_term:
            p=text.find(t,start)
            if p<0: break
            centers.append(p); seen+=1; start=p+len(t)
    if not centers:
        return '',[],None
    best=None
    for p in centers:
        s=max(0,p-ctx); e=min(len(text),p+ctx)
        sn=text[s:e]
        local=[t for t in terms if t in sn]
        poss=[]
        for t in local:
            q=sn.find(t)
            if q>=0: poss.append((q,q+len(t)))
        span=(max(x[1] for x in poss)-min(x[0] for x in poss)) if len(poss)>=2 else None
        score=(len(local), -(span if span is not None else 10**9))
        if best is None or score>best[0]: best=(score,sn,local,span)
    return best[1],best[2],best[3]

def clean_meta(v):
    if v is None or isinstance(v,(bool,int,float)): return v
    if isinstance(v,str):
        v=' '.join(v.split())
        return v[:500]
    return str(v)[:500]

for rank,sh in enumerate(router['ranked_shards'][:top_n],1):
    repo=sh['repo']; fn=sh['file']; local_file=pathlib.Path('/tmp')/f'evidence-{rank}.parquet'
    url=hf_hub_url(repo, filename=fn, repo_type='dataset')
    with requests.get(url,stream=True,timeout=(30,240)) as r:
        r.raise_for_status(); total=0
        with local_file.open('wb') as f:
            for b in r.iter_content(8*1024*1024):
                if b: f.write(b); total+=len(b)
    bytes_dl+=total
    pf=pq.ParquetFile(local_file)
    fields=list(pf.schema_arrow)
    string_names=[f.name for f in fields if str(f.type) in {'string','large_string'}]
    col='text' if 'text' in string_names else string_names[0]
    meta_cols=[]
    for f in fields:
        if f.name==col: continue
        typ=str(f.type)
        if META_NAME_RE.search(f.name) and (typ in {'string','large_string','int32','int64','float','double','bool'} or typ.startswith('timestamp')):
            meta_cols.append(f.name)
        if len(meta_cols)>=8: break
    read_cols=[col]+meta_cols
    candidates=[]; global_row=0
    for batch in pf.iter_batches(batch_size=256,columns=read_cols):
        dct=batch.to_pydict(); texts=dct[col]
        for i,text in enumerate(texts):
            ridx=global_row; global_row+=1
            if not isinstance(text,str) or not text: continue
            present=[t for t in terms if t in text]
            if len(present)<2: continue
            snippet,local_terms,local_span=best_window(text,present)
            if len(local_terms)<min_local: continue
            metadata={k:clean_meta(dct[k][i]) for k in meta_cols if dct[k][i] is not None}
            candidates.append({
                'ranked_shard':rank,'source':sh['source'],'repo':repo,'file':fn,'row':ridx,
                'row_sha256':hashlib.sha256(text.encode()).hexdigest(),
                'matched_terms':present,'matched_term_count':len(present),
                'local_terms':local_terms,'local_term_count':len(local_terms),'local_span_chars':local_span,
                'text_length_chars':len(text),'document_head':text[:head_chars],
                'metadata':metadata,'snippet':snippet
            })
    candidates.sort(key=lambda r:(-r['local_term_count'],-r['matched_term_count'],r['local_span_chars'] if r['local_span_chars'] is not None else 10**9,r['row']))
    rows.extend(candidates[:cap])
    local_file.unlink(missing_ok=True)

rows.sort(key=lambda r:(-r['local_term_count'],-r['matched_term_count'],r['ranked_shard'],r['row']))
out={
  'format':'osr-exact-evidence/v2.1','run_id':req['run_id'],'router_run_id':router.get('run_id'),
  'terms':terms,'top_n_shards':top_n,'min_local_terms':min_local,'rows_found':len(rows),
  'bytes_downloaded':bytes_dl,'selection_mode':'best_local_window_per_shard','rows':rows
}
summary={
  'status':'PASS','run_id':req['run_id'],'router_run_id':router.get('run_id'),'query_term_count':len(terms),
  'top_n_shards':top_n,'rows_found':len(rows),'bytes_downloaded':bytes_dl,
  'all_query_term_rows':sum(1 for r in rows if r['local_term_count']==len(terms)),
  'four_plus_local_term_rows':sum(1 for r in rows if r['local_term_count']>=4),
  'three_plus_local_term_rows':sum(1 for r in rows if r['local_term_count']>=3),
  'rows_with_metadata':sum(1 for r in rows if r.get('metadata')),
  'min_local_terms':min_local,'selection_mode':'best_local_window_per_shard'
}
CURRENT.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n','utf-8')
CURRENT_SUMMARY.write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n','utf-8')
d=ARCHIVE_ROOT/req['run_id']; d.mkdir(parents=True,exist_ok=True)
(d/'exact_evidence.json').write_text(CURRENT.read_text('utf-8'),'utf-8')
(d/'exact_evidence_summary.json').write_text(CURRENT_SUMMARY.read_text('utf-8'),'utf-8')
print(json.dumps(summary,ensure_ascii=False))
