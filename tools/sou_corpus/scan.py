#!/usr/bin/env python3
"""Reproducible source-stratified census of 瞍 and possible lookalikes in ancient texts.

Primary: gujilab/chinese-classical-corpus output/corpus.jsonl (1 line per unit).
Supplementary: hanzhaodeng/chinese-ancient-text selected work JSONs.
No merging of similarly pronounced or visually similar graphemes.
"""
import argparse,csv,hashlib,json,re,collections,datetime,pathlib,unicodedata

TARGETS = ['瞍','𥈃','𥈟']  # 瞍通行形；𥈃、𥈟见汉典/《说文》字书。按字形分列后合计
CONTROLS = ['馊','叟','瞽','盲','眇']
CONTEXT = 52

def walk(value):
    if isinstance(value,str):
        yield value
    elif isinstance(value,list):
        for v in value: yield from walk(v)
    elif isinstance(value,dict):
        for v in value.values(): yield from walk(v)

def is_han(c):
    n=ord(c)
    return (0x3400<=n<=0x9FFF or 0x20000<=n<=0x2FA1F or 0xF900<=n<=0xFAFF)

def load_primary(path):
    with open(path,encoding='utf8') as f:
        for lineno,line in enumerate(f,1):
            if not line.strip():continue
            o=json.loads(line)
            yield {'dataset':'gujilab-v1.3','work':o.get('source','UNKNOWN'), 'section':str(o.get('volume',o.get('chapter',''))),
                   'kind':str(o.get('category','未知')), 'era':str(o.get('era','')), 'id':o.get('id',str(lineno)),
                   'text':str(o.get('content','')), 'line':lineno}

def load_extra(path):
    o=json.loads(path.read_text(encoding='utf8'))
    if not isinstance(o,dict) or not isinstance(o.get('articles'),list):raise ValueError('unexpected supplementary schema '+str(path))
    book=o.get('name',path.stem)
    # Supplementary works are counted only if not present in primary; see main().
    for i,article in enumerate(o['articles'],1):
        content=article.get('content',[]) if isinstance(article,dict) else article
        yield {'dataset':'hanzhaodeng-public','work':book,'section':article.get('title',str(i)) if isinstance(article,dict) else str(i),
               'kind':'志怪/神话' if book in ('搜神记','山海经') else '其他子书','era':'版本待审','id':f'{book}#{i}',
               'text':'\n'.join(walk(content)),'line':i}

def classify(text,i):
    l=text[max(0,i-2):i];r=text[i+1:i+3]
    if l.endswith('瞽'):return '瞽瞍：舜父称谓候选，人工复核'
    if l.endswith('矇') or l.endswith('蒙'):return '矇瞍：礼乐称谓候选'
    if r.startswith('赋') or r.startswith('賦'):return '瞍赋：礼仪职能候选'
    return '其他：须全文复核'

def main():
    p=argparse.ArgumentParser();p.add_argument('--primary',type=pathlib.Path,required=True)
    p.add_argument('--extras-dir',type=pathlib.Path);p.add_argument('--out',type=pathlib.Path,required=True)
    p.add_argument('--commit',default='unknown');p.add_argument('--supp-commit',default='unknown');args=p.parse_args()
    if not args.primary.is_file() or args.primary.stat().st_size==0:raise SystemExit('PRIMARY_CORPUS_UNAVAILABLE, refusing to publish frequency zeros')
    args.out.mkdir(exist_ok=True,parents=True)
    processed=set();stats=collections.defaultdict(lambda:{'chars':0,'han_chars':0,'segments':0,'occ':collections.Counter()})
    hits=[];sha=hashlib.sha256()
    with args.primary.open('rb') as f:
        for blk in iter(lambda:f.read(1048576),b''):sha.update(blk)
    records=list(load_primary(args.primary))
    sources={r['work'] for r in records}
    if args.extras_dir and args.extras_dir.is_dir():
        for fn in sorted(args.extras_dir.glob('*.json')):
            work=fn.stem
            if work not in sources:
                records.extend(load_extra(fn))
    for rec in records:
        t=rec['text'];key=(rec['dataset'],rec['work'],hashlib.sha256(t.encode()).hexdigest())
        if key in processed:continue
        processed.add(key)
        st=stats[(rec['dataset'],rec['work'],rec['kind'])]
        st['chars']+=len(t);st['han_chars']+=sum(map(is_han,t));st['segments']+=1
        for c in TARGETS+CONTROLS:
            for m in re.finditer(re.escape(c),t):
                st['occ'][c]+=1
                if c in TARGETS:
                    i=m.start();hits.append({'dataset':rec['dataset'],'book':rec['work'],'category':rec['kind'],
                          'section':rec['section'],'id':rec['id'],'grapheme':c,'position':i,'function':classify(t,i),
                          'context':t[max(0,i-CONTEXT):min(len(t),i+CONTEXT)].replace('\n',' '),'source_era':rec['era']})
    columns=['dataset','book','category','segments','chars','han_chars']+TARGETS+CONTROLS+['exact_per_million_han','has_exact']
    rr=[]
    for (dataset,work,kind),st in sorted(stats.items(),key=lambda q:(q[0][2],q[0][1])):
        row=dict(dataset=dataset,book=work,category=kind,segments=st['segments'],chars=st['chars'],han_chars=st['han_chars'],
                 exact_per_million_han=round(1e6*st['occ']['瞍']/st['han_chars'],3) if st['han_chars'] else None,has_exact=bool(st['occ']['瞍']))
        row.update({c:st['occ'][c] for c in TARGETS+CONTROLS});rr.append(row)
    with (args.out/'counts_by_book.csv').open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=columns);w.writeheader();w.writerows(rr)
    with (args.out/'occurrences.csv').open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=['dataset','book','category','section','id','grapheme','position','function','context','source_era']);w.writeheader();w.writerows(hits)
    kinds=collections.defaultdict(lambda: {'works':0,'chars':0,'han_chars':0,'瞍':0,'𥈃':0,'𥈟':0})
    for row in rr:
        z=kinds[row['category']];z['works']+=1;z['chars']+=row['chars'];z['han_chars']+=row['han_chars']
        for c in TARGETS:z[c]+=row[c]
    report={'run_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'source_primary_url':'https://github.com/gujilab/chinese-classical-corpus/blob/main/output/corpus.jsonl',
        'primary_commit':args.commit,'primary_sha256':sha.hexdigest(),'supplementary_commit':args.supp_commit,
        'works_count':len(rr),'books_with_exact':sum(1 for r in rr if r['瞍']>0),
        'exact_count':sum(r['瞍'] for r in rr),'variants_attested_count':sum(r['𥈃']+r['𥈟'] for r in rr),
        'han_chars':sum(r['han_chars'] for r in rr),'groups':dict(kinds),
        'coverage_warning':'仅索引语料库覆盖的作品。主库历史仅前15部正史；补充仅山海经、搜神记。不可称全二十四史、全部志怪或全部传本。',
        'editorial_note':'瞽瞍多为舜父专名，段玉裁主张人名应作瞽叟；不能作为瞍人种族出没。𥈃/𥈟均为可追溯字书的历史异写但保留分列；叟/馊/瞽/盲不自动等值。'
    }
    (args.out/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    md=['# 「瞍」古籍频率 — 可复验批量搜索','',f'主版本: gujilab {args.commit[:12]}, SHA256 {sha.hexdigest()}',
       f'补充版本: hanzhaodeng {args.supp_commit[:12]}','',f'纳入作品: {len(rr)} 部；正文汉字总量: {report["han_chars"]:,}',
       f'「瞍」精确命中: {report["exact_count"]}；命中作品数: {report["books_with_exact"]}',
       f'字书异体「𥈃」「𥈟」各自单列: {sum(r["𥈃"] for r in rr)}, {sum(r["𥈟"] for r in rr)}；三种同词形合计: {report["exact_count"] + report["variants_attested_count"]}',
       '', '| 类别 | 作品数 | 紑精确命中 | 每百万汉字 |','|---|---:|---:|---:|']
    for kind,z in sorted(kinds.items()):md.append(f'| {kind} | {z["works"]} | {z["瞍"]} | {1e6*z["瞍"]/z["han_chars"] if z["han_chars"] else 0:.2f} |')
    md.extend(['','## 命中原典（精确字）','', '| 书名 | 类别 | 「瞍」 | 每百万汉字 |','|---|---|---:|---:|'])
    for r in sorted([r for r in rr if r['瞍']>0],key=lambda x:-x['瞍']):md.append(f'| {r["book"]} | {r["category"]} | {r["瞍"]} | {r["exact_per_million_han"]} |')
    md.extend(['','## 解释边界','- 《说文》瞍：无目；但和瞽、盲、叟均有注释层面的交叉，不能凭机械字频证明不同生物族群。',
    '- 将「瞽瞍」人名、《诗经》矇瞍礼乐，以及字书释义分别标注；清代段玉裁主张舜父人名应作「瞽叟」而非「瞽瞍」，故须保留版本/释读竞争。不能从字频反推出“无眼人”真实存在。',
    '- 小体量小说/志怪只统计公开文本中已得到的数据集，必须另做更多文本扩容。','',report['coverage_warning'],'',
    '更细逐例出处见 occurrences.csv，零命中的书也在 counts_by_book.csv，便于审计“全书是否真的被读取”。'])
    (args.out/'REPORT.md').write_text('\n'.join(md)+'\n',encoding='utf8')
    print(json.dumps({'books':report['works_count'],'exact':report['exact_count'],'han_chars':report['han_chars'],'books_with_exact':report['books_with_exact']},ensure_ascii=False))
if __name__=='__main__':main()
