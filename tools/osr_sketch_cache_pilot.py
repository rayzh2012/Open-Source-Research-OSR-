#!/usr/bin/env python3
import argparse, json, math, pathlib, time, hashlib
from collections import Counter


def grams(text, n):
    text=''.join(ch for ch in text if '\u4e00' <= ch <= '\u9fff')
    return {text[i:i+n] for i in range(max(0, len(text)-n+1))}


def bloom_bits(n_items, fpr):
    if n_items <= 0: return 0
    return int(math.ceil(-n_items * math.log(fpr) / (math.log(2)**2)))


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--input-jsonl', required=True, help='One JSON object per shard with fields file,text_sample or text')
    ap.add_argument('--out', default='control/sketch_cache_pilot_result.json')
    args=ap.parse_args()
    rows=[json.loads(x) for x in pathlib.Path(args.input_jsonl).read_text('utf-8').splitlines() if x.strip()]
    out={'format':'osr-sketch-cache-pilot/v1','shards':[],'created_unix':time.time()}
    totals=Counter()
    for r in rows:
        text=str(r.get('text_sample') or r.get('text') or '')
        g2=grams(text,2); g3=grams(text,3)
        rec={'file':r.get('file'),'sample_chars':len(text),'unique_2grams':len(g2),'unique_3grams':len(g3),'estimates':{}}
        for fpr in (0.01,0.001):
            b2=bloom_bits(len(g2),fpr); b3=bloom_bits(len(g3),fpr)
            rec['estimates'][str(fpr)]={'bloom_2gram_bytes':(b2+7)//8,'bloom_3gram_bytes':(b3+7)//8,'bloom_combined_bytes':(b2+b3+7)//8}
        rec['fingerprint_sha256']=hashlib.sha256((r.get('file','')+'|'+str(len(g2))+'|'+str(len(g3))).encode()).hexdigest()
        out['shards'].append(rec)
        totals['chars']+=len(text); totals['g2']+=len(g2); totals['g3']+=len(g3)
        totals['bloom01']+=rec['estimates']['0.01']['bloom_combined_bytes']
        totals['bloom001']+=rec['estimates']['0.001']['bloom_combined_bytes']
    n=max(1,len(rows))
    out['summary']={
        'shard_count':len(rows),
        'sample_chars':totals['chars'],
        'mean_unique_2grams':totals['g2']/n,
        'mean_unique_3grams':totals['g3']/n,
        'mean_bloom_bytes_fpr_1pct':totals['bloom01']/n,
        'mean_bloom_bytes_fpr_0_1pct':totals['bloom001']/n,
        'projected_1788_shards_mib_fpr_1pct':totals['bloom01']/n*1788/1024/1024,
        'projected_1788_shards_mib_fpr_0_1pct':totals['bloom001']/n*1788/1024/1024,
        'note':'Pilot uses bounded shard text samples. Full-shard gram cardinality may be higher; do not scale without held-out rejection-rate validation.'
    }
    pathlib.Path(args.out).write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n','utf-8')
    print(json.dumps(out['summary'],ensure_ascii=False))

if __name__=='__main__': main()
