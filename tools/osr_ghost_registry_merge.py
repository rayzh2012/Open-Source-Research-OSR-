#!/usr/bin/env python3
import argparse, csv, json, pathlib, re, hashlib
from collections import defaultdict

KNOWN_FAMILIES = {
    'DISEASE': ['疫鬼','疟鬼','虐鬼','瘟鬼','病鬼','疾病鬼','疫神','厉神'],
    'WATER': ['水鬼','溺鬼','河鬼','江鬼','井鬼','船鬼','水精'],
    'DANGER': ['厉鬼','恶鬼','饿鬼','尸鬼','冤鬼','怨鬼','孤魂野鬼'],
    'PREDATOR': ['尺郭','天郭','赤郭','食邪','黄父'],
    'ZHONGKUI': ['钟馗','鍾馗','中魁','终葵','钟葵','魌头'],
    'EXORCIST': ['神荼','郁垒','方相氏','大傩','逐疫'],
    'WANGLIANG': ['罔两','罔象','象罔','蝄蜽','魍魉','魍魉鬼','魑魅'],
    'LOCAL': ['黎丘鬼','野仲','游光','黄父鬼','黄文鬼','鬼母','鬼姑','虚耗','魖耗'],
}

# Conservative pattern: candidate is a compact lexical unit ending in 鬼. It is a discovery candidate only,
# never an automatic entity assertion.
GHOST_TOKEN = re.compile(r'([\u4e00-\u9fff]{1,8}鬼)')


def load_json(path):
    return json.loads(pathlib.Path(path).read_text('utf-8'))


def write_csv(path, headers, rows):
    p=pathlib.Path(path); p.parent.mkdir(parents=True, exist_ok=True)
    with p.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=headers); w.writeheader(); w.writerows(rows)


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--evidence', required=True, help='M5 exact evidence JSON')
    ap.add_argument('--out-dir', default='control/ghost_registry')
    args=ap.parse_args()
    data=load_json(args.evidence)
    run_id=data.get('run_id') or data.get('summary',{}).get('run_id','UNKNOWN')
    rows=data.get('evidence') or data.get('rows') or data.get('items') or []

    evidence=[]; candidates=defaultdict(lambda:{'hits':0,'shards':set(),'examples':[]}); aliases=[]
    known={x for xs in KNOWN_FAMILIES.values() for x in xs}
    for i,r in enumerate(rows):
        text=str(r.get('snippet') or r.get('text') or '')
        shard=str(r.get('file') or r.get('shard') or '')
        row_hash=str(r.get('row_sha256') or r.get('row_hash') or hashlib.sha256(text.encode()).hexdigest())
        matched=r.get('matched_terms') or []
        if isinstance(matched,str): matched=[matched]
        eid=f'{run_id}:{i:05d}'
        evidence.append({
            'Evidence_ID':eid,'Matched_Name':'|'.join(matched),'Source_Title':r.get('title',''),
            'Source_Date':r.get('date',''),'Dynasty_Period':r.get('period',''),'Region':r.get('region',''),
            'Genre':r.get('genre',''),'Quote_or_Snippet':text,'Source_URL_or_Locator':r.get('source',''),
            'Shard':shard,'Row_Hash':row_hash,'Evidence_Type':'FABRIC_EXACT','Grade':'CANDIDATE',
            'Run_ID':run_id,'Review_Status':'NEW'
        })
        for token in set(GHOST_TOKEN.findall(text)):
            rec=candidates[token]; rec['hits']+=1; rec['shards'].add(shard)
            if len(rec['examples'])<3: rec['examples'].append(text[:280])
    cand_rows=[]
    for name,rec in sorted(candidates.items(), key=lambda kv:(-kv[1]['hits'],kv[0])):
        cand_rows.append({
            'Candidate_Name':name,'Known_Query_Term':'YES' if name in known else 'NO',
            'Hit_Count':rec['hits'],'Shard_Count':len(rec['shards']),'Example_Snippets':' || '.join(rec['examples']),
            'Run_ID':run_id,'Decision':'REVIEW'
        })
    out=pathlib.Path(args.out_dir)
    write_csv(out/'ghost_evidence.csv', list(evidence[0].keys()) if evidence else ['Evidence_ID'], evidence)
    write_csv(out/'ghost_candidates.csv', ['Candidate_Name','Known_Query_Term','Hit_Count','Shard_Count','Example_Snippets','Run_ID','Decision'], cand_rows)
    write_csv(out/'alias_candidates.csv', ['Alias','Candidate_Canonical','Evidence','Run_ID','Decision'], aliases)
    summary={'run_id':run_id,'evidence_rows':len(evidence),'candidate_ghost_tokens':len(cand_rows),'new_candidate_tokens':sum(1 for x in cand_rows if x['Known_Query_Term']=='NO')}
    (out/'ghost_registry_merge_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n','utf-8')
    print(json.dumps(summary,ensure_ascii=False))

if __name__=='__main__': main()
