#!/usr/bin/env python3
"""Occurrence census of 瞍 in two documented public classical-text corpora."""
import csv, hashlib, json, re, time
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from pathlib import Path
from collections import defaultdict, Counter
ROOT=Path('research/sou-lexical-audit')
OUT=Path('reports/sou'); OUT.mkdir(parents=True,exist_ok=True)
CACHE=Path('.sou-cache');CACHE.mkdir(exist_ok=True)
BASE='https://raw.githubusercontent.com'
MAIN=BASE+'/gujilab/chinese-classical-corpus/main/output/corpus.jsonl'
SECOND=['山海经','搜神记','神异经','列仙传','博物志','搜神后记','淮南子','庄子','列子']
HIST=set('史记 汉书 后汉书 三国志 晋书 宋书 南齐书 梁书 陈书 魏书 北齐书 周书 南史 北史 隋书 资治通鉴'.split())
CLASSICS=set('大学 中庸 论语 孟子 诗经 尚书 礼记 周易 春秋左传 春秋公羊传 春秋穀梁传 孝经 尔雅'.split())
TERMS=['瞍','瞽瞍','矇瞍','蒙瞍','瞍人','朦瞍','瞽叟','馊','叟','瞽','𥈃','𥈟']
stats=defaultdict(lambda:{'chars':0,'segments':0,'words':Counter(),'roles':Counter()})
rows=[]; provenance=[]; unavailable=[]
def download(url,path,required=False):
 for attempt in range(3):
  try:
   req=Request(url,headers={'User-Agent':'ClassicalSouAudit/1.1'})
   h=hashlib.sha256();size=0
   with urlopen(req,timeout=100) as response, path.open('wb') as f:
    while chunk:=response.read(1024*1024):
     size+=len(chunk)
     if size>150000000:raise RuntimeError('file exceeds limit')
     f.write(chunk);h.update(chunk)
   provenance.append({'url':url,'bytes':size,'sha256':h.hexdigest(),'status':'ok'})
   return True
  except HTTPError as exc:
   if exc.code==404 and not required:
    unavailable.append(url);provenance.append({'url':url,'status':'404'});return False
   if attempt==2:raise
  except Exception as exc:
   if attempt==2:
    if required:raise
    unavailable.append(url);provenance.append({'url':url,'status':str(exc)});return False
  time.sleep(2*(attempt+1))
 return False
def genre(book,secondary=False):
 if secondary:return '志怪／神话' if book in SECOND[:6] else '诸子'
 return '正史／编年史' if book in HIST else '经部' if book in CLASSICS else '字书' if book=='说文解字' else '其他'
def label(text,pos):
 prev=text[max(0,pos-1):pos]
 if prev=='瞽':return 'NAME_GUSOU'
 if prev in ('矇','蒙','朦'):return 'RITUAL_MUSIC'
 if text[pos:pos+2]=='瞍人':return 'EXPLICIT_SOU_REN'
 if text[pos:pos+2] in ('瞍赋','瞍賦','瞍奏','瞍工','瞍诵','瞍誦'):return 'RITUAL_MUSIC'
 return 'UNRESOLVED'
def scan(book,edition,chapter,segment,text,secondary=False):
 key=(edition,genre(book,secondary),book); s=stats[key]
 s['segments']+=1;s['chars']+=len(text)
 for term in TERMS:s['words'][term]+=text.count(term)
 for hit in re.finditer('瞍',text):
  i=hit.start(); tag=label(text,i);s['roles'][tag]+=1
  rows.append({'corpus':edition,'genre':key[1],'book':book,'chapter':chapter,'segment':segment,
   'offset':i,'role_auto':tag,'context':text[max(0,i-50):i+51].replace('\n',' ')})
p=CACHE/'main.jsonl'
download(MAIN,p,required=True)
with p.open(encoding='utf-8-sig') as f:
 for ln,line in enumerate(f,1):
  if not line.strip():continue
  d=json.loads(line);t=d.get('content')
  if isinstance(t,str):
   book=d.get('source') or 'UNKNOWN'
   scan(book,'gujilab',str(d.get('chapter') or d.get('volume') or ''),
        str(d.get('id') or ln),t)
for book in SECOND:
 path=CACHE/(book+'.json')
 url=BASE+'/hanzhaodeng/chinese-ancient-text/master/'+book+'.json'
 if not download(url,path):continue
 try:items=json.loads(path.read_text(encoding='utf-8-sig')).get('articles',[])
 except ValueError as exc:
  unavailable.append(book+': bad JSON '+str(exc));continue
 for i,article in enumerate(items,1):
  content=article.get('content',[])
  if isinstance(content,str):content=[content]
  if not isinstance(content,list):continue
  for j,t in enumerate(content,1):
   if isinstance(t,str):scan(book,'hanzhaodeng',str(article.get('title') or ''),
                            str(i)+'/'+str(j),t,True)
fields=['corpus','genre','book','chars','segments']+TERMS+['per_million',
        'NAME_GUSOU','RITUAL_MUSIC','EXPLICIT_SOU_REN','UNRESOLVED']
with (OUT/'per_work.csv').open('w',encoding='utf-8-sig',newline='') as f:
 w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
 for (edition,cat,book),s in sorted(stats.items()):
  d={'corpus':edition,'genre':cat,'book':book,'chars':s['chars'],
     'segments':s['segments'],'per_million':round(1e6*s['words']['瞍']/s['chars'],4) if s['chars'] else 0}
  d.update({term:s['words'][term] for term in TERMS})
  d.update({term:s['roles'][term] for term in fields[-4:]})
  w.writerow(d)
with (OUT/'contexts.csv').open('w',encoding='utf-8-sig',newline='') as f:
 cols=['corpus','genre','book','chapter','segment','offset','role_auto','context']
 w=csv.DictWriter(f,fieldnames=cols);w.writeheader();w.writerows(rows)
group=defaultdict(Counter)
for (ed,cat,b),s in stats.items():
 g=group[(ed,cat)];g['chars']+=s['chars'];g['segments']+=s['segments']
 g['sou']+=s['words']['瞍'];g['name']+=s['roles']['NAME_GUSOU']
 g['ritual']+=s['roles']['RITUAL_MUSIC'];g['explicit']+=s['roles']['EXPLICIT_SOU_REN']
with (OUT/'per_genre.csv').open('w',encoding='utf-8-sig',newline='') as f:
 w=csv.writer(f);w.writerow(['corpus','genre','chars','segments','瞍','per_million','name','ritual','literal_瞍人'])
 for (ed,cat),d in sorted(group.items()):
  w.writerow([ed,cat,d['chars'],d['segments'],d['sou'],
   round(1e6*d['sou']/d['chars'],4) if d['chars'] else 0,d['name'],d['ritual'],d['explicit']])
(OUT/'provenance.json').write_text(json.dumps({'sources':provenance,'missing':unavailable,
 'scope':'13 classics + first 15/24 histories + Zizhi Tongjian + Shuowen, supplemented by selected myths',
 'excluded':'last nine official histories, other editions and most fantasy texts',
 'counting_rule':'counts text content only; overlapping witnesses not independent'},ensure_ascii=False,indent=2),encoding='utf8')
rank=sorted([(b,ed,cat,s['words']['瞍']) for (ed,cat,b),s in stats.items() if s['words']['瞍']],key=lambda x:-x[3])
lines=['# 瞍字古籍频率审计','','仅为电子传本的字频，绝不等于独立古史证据或「瞍人」存在证据。','','| 书名 | 语料库 | 类别 | 瞍次数 |','|---|---|---|---:|']
lines.extend('| '+b+' | '+ed+' | '+cat+' | '+str(n)+' |' for b,ed,cat,n in rank)
lines+=['','瞽瞍是人名候选；瞍人另列；叟、馊不得并入瞍。','',
 '详情见 contexts.csv、per_work.csv、per_genre.csv、provenance.json。','',
 '未覆盖的九部正史或志怪不能被报为零。','',
 '总精确字频（跨不同版本可能重复）：'+str(len(rows))]
(OUT/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
print('Records',sum(s['segments'] for s in stats.values()),'Hits 瞍',len(rows),'books',len(stats))
