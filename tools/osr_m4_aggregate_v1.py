#!/usr/bin/env python3
import json, gzip, pathlib, collections, math, time

ROOT=pathlib.Path('control')


def load_json(p):
    return json.loads(pathlib.Path(p).read_text('utf-8'))


def main():
    feature_path=ROOT/'feature_catalog.json'
    qsum_path=ROOT/'stage2_query_index_summary.json'
    if not feature_path.exists():
        raise SystemExit('feature_catalog.json missing: M3 must finish first')
    if not qsum_path.exists():
        raise SystemExit('stage2_query_index_summary.json missing: M2 must finish first')

    feat=load_json(feature_path)
    qsum=load_json(qsum_path)

    features=feat.get('features',[])
    top_features=sorted(features,key=lambda x:(-int(x.get('rows_with_feature',0)),-int(x.get('occurrences',0)),x.get('feature_id','')))[:500]
    fam=collections.defaultdict(lambda:{'feature_count':0,'occurrences':0,'rows_with_feature':0})
    for f in features:
        b=fam[f.get('family','unknown')]
        b['feature_count']+=1
        b['occurrences']+=int(f.get('occurrences',0))
        b['rows_with_feature']+=int(f.get('rows_with_feature',0))

    term_stats=[]
    for term,rec in qsum.get('terms',{}).items():
        term_stats.append({
            'term':term,
            'total_count':int(rec.get('total_count',0)),
            'hit_shards':int(rec.get('hit_shards',0)),
            'top_shards':rec.get('top_shards',[])[:10],
        })
    term_stats.sort(key=lambda x:(-x['hit_shards'],-x['total_count'],x['term']))

    corpora={}
    for name,st in feat.get('corpus_stats',{}).items():
        rows=int(st.get('rows',st.get('rows_scanned',0)) or 0)
        chars=int(st.get('chars',st.get('chars_scanned',0)) or 0)
        corpora[name]={**st,'avg_chars_per_row':round(chars/rows,3) if rows else None}

    output={
        'format':'osr-research-aggregation/v1',
        'created_unix':time.time(),
        'inputs':{
            'feature_run_id':feat.get('run_id'),
            'feature_schema_sha256':feat.get('feature_schema_sha256'),
            'query_run_id':qsum.get('run_id'),
            'query_pack_sha256':qsum.get('query_pack_sha256'),
        },
        'corpus_summary':corpora,
        'feature_family_summary':dict(sorted(fam.items())),
        'top_features':top_features,
        'query_term_summary':term_stats,
        'top_cooccurrence':feat.get('top_cooccurrence',[])[:500],
        'research_contract':'All aggregates are routing/statistical signals; historical claims require exact source-row recheck.'
    }
    out=ROOT/'research_aggregation_v1.json'
    out.write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n','utf-8')
    print(json.dumps({'status':'PASS','features':len(features),'terms':len(term_stats),'corpora':len(corpora),'output':str(out)},ensure_ascii=False))

if __name__=='__main__':
    main()
