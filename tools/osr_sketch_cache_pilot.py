#!/usr/bin/env python3
import argparse, json, math, pathlib, time, hashlib
from collections import Counter

DEFAULT_QUERIES=[
    '女娲','共工','炎帝','神农','黄帝','后土','句龙','不周山','补天','天柱','洪水','治水',
    '罔物','网雾','天降','绝地天通','龙伯国','鳌','高诱','论衡','淮南子','三皇本纪','方志','祀典',
    # Low-frequency proper-name / lineage-form probes for real research routing.
    '孺帝','少昊孺帝颛顼','颛顼之子','颛顼子','颛顼之后','高阳氏之子','高阳氏之后','高阳之后',
    '元子','颛顼崩','帝喾立'
]


def cjk_only(text):
    return ''.join(ch for ch in text if '\u4e00' <= ch <= '\u9fff')


def grams(text, n):
    text=cjk_only(text)
    return {text[i:i+n] for i in range(max(0, len(text)-n+1))}


def query_grams(q,n):
    q=cjk_only(q)
    if len(q) < n: return []
    return [q[i:i+n] for i in range(len(q)-n+1)]


def bloom_bits(n_items, fpr):
    if n_items <= 0: return 0
    return int(math.ceil(-n_items * math.log(fpr) / (math.log(2)**2)))


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--input-jsonl', required=True, help='One JSON object per shard with fields file,text_sample or text')
    ap.add_argument('--out', default='control/sketch_cache_pilot_result.json')
    args=ap.parse_args()
    rows=[json.loads(x) for x in pathlib.Path(args.input_jsonl).read_text('utf-8').splitlines() if x.strip()]
    out={'format':'osr-sketch-cache-pilot/v2','shards':[],'created_unix':time.time(),'held_out_queries':DEFAULT_QUERIES}
    totals=Counter(); exact_reject2=0; exact_reject3=0; checks2=0; checks3=0
    for r in rows:
        text=str(r.get('text_sample') or r.get('text') or '')
        g2=grams(text,2); g3=grams(text,3)
        rec={'file':r.get('file'),'sample_chars':len(text),'unique_2grams':len(g2),'unique_3grams':len(g3),'estimates':{},'query_probe':[]}
        for fpr in (0.01,0.001):
            b2=bloom_bits(len(g2),fpr); b3=bloom_bits(len(g3),fpr)
            rec['estimates'][str(fpr)]={'bloom_2gram_bytes':(b2+7)//8,'bloom_3gram_bytes':(b3+7)//8,'bloom_combined_bytes':(b2+b3+7)//8}
        for q in DEFAULT_QUERIES:
            q2=query_grams(q,2); q3=query_grams(q,3)
            possible2 = True if not q2 else all(x in g2 for x in q2)
            possible3 = True if not q3 else all(x in g3 for x in q3)
            actual=q in text
            if q2:
                checks2+=1
                if not possible2: exact_reject2+=1
            if q3:
                checks3+=1
                if not possible3: exact_reject3+=1
            rec['query_probe'].append({'query':q,'actual_in_sample':actual,'all_2grams_present':possible2,'all_3grams_present':possible3})
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
        'exact_2gram_rejection_rate_on_probe': (exact_reject2/checks2 if checks2 else None),
        'exact_3gram_rejection_rate_on_probe': (exact_reject3/checks3 if checks3 else None),
        'probe_checks_2gram':checks2,
        'probe_checks_3gram':checks3,
        'note':'Bounded shard samples only. Rejection metrics are exact-set upper-bound routing tests before Bloom/XOR false positives. Full-shard cardinality may be higher.'
    }
    pathlib.Path(args.out).write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n','utf-8')
    print(json.dumps(out['summary'],ensure_ascii=False))

if __name__=='__main__': main()
