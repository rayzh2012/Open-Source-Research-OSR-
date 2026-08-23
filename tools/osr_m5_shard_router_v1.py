#!/usr/bin/env python3
import json, gzip, pathlib, math, time, collections

ROOT=pathlib.Path('control')

def main():
    req=json.loads((ROOT/'m5_router_request.json').read_text('utf-8'))
    with gzip.open(ROOT/'stage2_query_index.json.gz','rt',encoding='utf-8') as f:
        idx=json.load(f)
    wanted=[]
    for x in req.get('terms',[]):
        s=str(x).strip()
        if s and s not in wanted: wanted.append(s)
    if not wanted: raise SystemExit('no query terms')
    top_k=max(1,min(int(req.get('top_k',50)),500))

    scores=collections.defaultdict(float)
    evidence=collections.defaultdict(list)
    for term in wanted:
        bucket=idx.get('terms',{}).get(term)
        if not bucket: continue
        total=max(1,int(bucket.get('total_count',0)))
        shard_n=max(1,int(bucket.get('hit_shards',0)))
        rarity=math.log1p(max(1,len(idx.get('inventory',[])))/shard_n)
        for sh in bucket.get('shards',[]):
            key=(sh.get('source',''),sh.get('repo',''),sh.get('file',''))
            count=max(0,int(sh.get('count',0)))
            signal=rarity*math.log1p(count)
            scores[key]+=signal
            evidence[key].append({'term':term,'count':count,'signal':round(signal,6)})

    ranked=[]
    for key,score in scores.items():
        src,repo,file=key
        ev=sorted(evidence[key],key=lambda x:(-x['signal'],-x['count'],x['term']))
        ranked.append({'source':src,'repo':repo,'file':file,'score':round(score,6),'matched_terms':len(ev),'evidence':ev})
    ranked.sort(key=lambda x:(-x['score'],-x['matched_terms'],x['source'],x['file']))
    out={
      'format':'osr-shard-router/v1',
      'run_id':req.get('run_id'),
      'query_terms':wanted,
      'known_terms':[t for t in wanted if t in idx.get('terms',{})],
      'unknown_terms':[t for t in wanted if t not in idx.get('terms',{})],
      'candidate_shards':len(ranked),
      'top_k':top_k,
      'ranked_shards':ranked[:top_k],
      'routing_contract':'Router ranks candidate shards only. Any factual conclusion requires exact source-row retrieval/recheck.',
      'created_unix':time.time()
    }
    (ROOT/'m5_router_result.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n','utf-8')
    print(json.dumps({'status':'PASS','known_terms':out['known_terms'],'unknown_terms':out['unknown_terms'],'candidates':len(ranked),'returned':len(out['ranked_shards'])},ensure_ascii=False))

if __name__=='__main__': main()
