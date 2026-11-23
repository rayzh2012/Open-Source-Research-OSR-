#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""《天龙八部》三版本场景/武功比对 v1.0.

Usage:
  python tianlong_three_version_scene_diff.py --download --output ./tianlong_diff
  python tianlong_three_version_scene_diff.py --corpus /path/to/JY --output ./tianlong_diff

Data source: https://github.com/OliverCWY/JY
The scanner emits short source anchors and chapter links, not full copyrighted text.
A match is a candidate, NOT proof of equivalent action or actual skill proficiency.
"""
import argparse
import csv
import json
import re
import shutil
import sys
import urllib.request
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import quote

VERSIONS = ('旧版', '三联版', '新修版')
PEOPLE = {
    '慕容复': ('慕容复', '慕容公子'),
    '慕容博': ('慕容博', '慕容先生'),
    '乔峰／萧峰': ('乔峰', '萧峰', '乔帮主', '萧大侠'),
    '庄聚贤／游坦之': ('庄聚贤', '游坦之', '铁丑', '铁头人', '庄帮主'),
    '王玉燕／王语嫣': ('王玉燕', '王语嫣'),
    '段誉': ('段誉', '段公子'),
    '虚竹': ('虚竹', '虚竹子'),
    '鸠摩智': ('鸠摩智', '大轮明王'),
    '丁春秋': ('丁春秋', '星宿老怪'),
}
# Avoid a single blanket replacement: 旧版18掌 and 新修28掌 are distinct
# historical configurations, not 'identical aliases'.
SKILLS = [
    '降龙十八掌', '降龙廿八掌', '降龙二十八掌', '见龙在田', '亢龙有悔',
    '斗转星移', '参合指', '擒龙功', '龙爪手', '沛然有雨', '抢珠三式',
    '易筋经', '神足经', '欲三摩地断行成就神足经', '冰蚕', '冰蚕异功',
    '六脉神剑', '火焰刀', '打狗棒法', '北冥神功', '朱蛤神功',
    '天鉴神功', '凌波微步', '小无相功', '天山折梅手', '天山六阳掌',
    '化功大法', '金刚杵', '一阳指', '罗汉拳', '多罗指',
]
# Overlapping terms, e.g. 神足经 within full name, are longest-match-first.
SKILLS = sorted(SKILLS, key=len, reverse=True)
LOCATIONS = ['杏子林', '无锡', '聚贤庄', '少室山', '少林寺', '藏经阁', '曼陀山庄',
             '听香水榭', '雁门关', '丐帮', '西夏', '皇宫', '灵鹫宫', '枯井',
             '珍珑棋局', '擂鼓山', '燕子坞', '天龙寺', '大理']
USE_VERBS = '施展|使出|使了|运起|运用|挥出|打出|拍出|一掌|掌力|掌风|施出|发动|使上|展开|弹向|挥舞'
LEARN_VERBS = '练成|修习|练习|修炼|传授|传给|学到|学会|授予|偷学|精简|创出|创制|参悟'
NEGATE_VERBS = '不会|不懂|尚未|未曾|没有学|一招也不会|不能使|无法使|无法施|不曾学'
REPORT_VERBS = '听说|据说|传闻|名闻|据传|自称|传说|声称|听闻'
CHINESE_RE = re.compile(r'[\u3400-\u9fff]+')

@dataclass
class Hit:
    version: str
    chapter_no: int
    chapter: str
    path: str
    person: str
    skill: str
    context_type: str
    anchor: str
    location: str
    sentence: str  # memory only; never written to output


def download_source(dest: Path):
    repo_dir = dest / 'JY'
    if (repo_dir / 'Markdown' / '旧版' / '天龙八部' / 'index.md').exists():
        return repo_dir
    dest.mkdir(parents=True, exist_ok=True)
    zip_path = dest / 'JY-master.zip'
    url = 'https://github.com/OliverCWY/JY/archive/refs/heads/master.zip'
    try:
        request = urllib.request.Request(url, headers={'User-Agent': 'tianlong-scene-compare/1.0'})
        with urllib.request.urlopen(request, timeout=75) as src, zip_path.open('wb') as dst:
            shutil.copyfileobj(src, dst)
    except Exception as exc:
        raise RuntimeError(f'Cannot download from GitHub: {exc}. Supply --corpus local cloned directory.')
    with zipfile.ZipFile(zip_path) as zf:
        # Python-safe extraction, strip archive top-level; all entries path validated.
        for item in zf.infolist():
            p = Path(item.filename)
            if not p.parts or p.parts[0] != 'JY-master' or '..' in p.parts:
                continue
            rest = Path(*p.parts[1:])
            if not rest.parts or item.is_dir():
                continue
            target = repo_dir / rest
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(item) as src, target.open('wb') as dst:
                shutil.copyfileobj(src, dst)
    return repo_dir


def corpus_dir(root: Path):
    if (root / 'Markdown' / '旧版' / '天龙八部').exists():
        return root
    for p in root.glob('*/Markdown/旧版/天龙八部'):
        return p.parents[2]
    raise FileNotFoundError('Could not find Markdown/旧版/天龙八部 under --corpus')


def chapters(root, version):
    folder = root / 'Markdown' / version / '天龙八部'
    if not folder.exists():
        raise FileNotFoundError(folder)
    index = folder / 'index.md'
    if not index.exists():
        raise FileNotFoundError(index)
    entries = []
    for line in index.read_text(encoding='utf-8-sig').splitlines():
        match = re.search(r'\- \[(.+?)\]\((.+?\.md)\)', line)
        if not match:
            continue
        title = match.group(1)
        fn = Path(__import__('urllib.parse', fromlist=['unquote']).unquote(match.group(2))).name
        if title in ('释名', '后记', '陈世骧先生书函') or '附录' in title:
            continue
        entries.append((title, folder / fn))
    return entries


def normalize(s):
    s = re.sub(r'\s+', '', s)
    for name, aliases in PEOPLE.items():
        for alias in sorted(aliases, key=len, reverse=True):
            s = s.replace(alias, name)
    return s


def grams(s, n=2):
    s = ''.join(CHINESE_RE.findall(normalize(s)))
    return set(s[i:i+n] for i in range(max(0, len(s)-n+1)))


def segments(s):
    s = re.sub(r'(?m)^#+[^\n]*\n?', '', s)
    # First divide long prose by full stops rather than trusting Markdown paragraphs.
    chunks = re.split(r'(?<=[。！？])|\n\s*\n+', s)
    chunks = [re.sub(r'\s+', ' ', x).strip() for x in chunks]
    return [x for x in chunks if len(x) >= 15]


def classify(sentence, skill):
    p = sentence.find(skill)
    local = sentence[max(0, p-65):min(len(sentence),p+len(skill)+65)]
    if re.search(NEGATE_VERBS, local):
        return '否定／明确不会'
    if re.search(REPORT_VERBS, local):
        return '转述／评价'
    if re.search(LEARN_VERBS, local):
        return '修习／传授／传承'
    if re.search(USE_VERBS, local):
        return '可能实际施展（待人工核对主语）'
    return '提及／背景／未判定'


def find_person(sentence, skill):
    # Interpret very local grammatical subject, but never label it as certified user.
    p = sentence.find(skill)
    verb_candidates=list(re.finditer(USE_VERBS+'|'+LEARN_VERBS, sentence[:p]))
    if verb_candidates:
        vb=verb_candidates[-1].start()
        left=sentence[max(0,vb-60):vb]
        # Strip addressed opponent (对X / 向X), which is usually NOT the practitioner.
        for aliases in PEOPLE.values():
            for alias in aliases:
                left=left.replace('对'+alias,'').replace('向'+alias,'').replace('给'+alias,'')
        subjects=[]
        for person,aliases in PEOPLE.items():
            for alias in aliases:
                q=left.rfind(alias)
                if q>=0: subjects.append((len(left)-q-len(alias),person))
        if subjects:
            return min(subjects)[1]
    # Last-resort proximity only; output field labels warn it is not a certified user.
    eligible=[]
    for person, aliases in PEOPLE.items():
        for alias in aliases:
            for m in re.finditer(re.escape(alias), sentence):
                dist = min(abs(m.start()-p), abs(m.end()-p))
                if dist <= 130:
                    eligible.append((dist, person))
    return min(eligible)[1] if eligible else '未判定'


def parse_hits(root):
    hits=[]; chapter_rows=[]
    for version in VERSIONS:
        entries=chapters(root,version)
        for no,(title,path) in enumerate(entries,1):
            if not path.exists():
                continue
            raw=path.read_text(encoding='utf-8-sig',errors='replace')
            if not raw.strip():
                continue
            ch_counts=Counter()
            for sentence in segments(raw):
                # Honor longest match: remove overlaps.
                spans=[]
                for skill in SKILLS:
                    for match in re.finditer(re.escape(skill),sentence):
                        span=(match.start(),match.end())
                        if any(not (span[1]<=a or span[0]>=b) for a,b in spans):
                            continue
                        spans.append(span)
                        candidate=find_person(sentence,skill)
                        typ=classify(sentence,skill)
                        loc=next((l for l in LOCATIONS if l in sentence),'未定位')
                        anchor=re.sub(r'\s+',' ',sentence[max(0,match.start()-9):match.end()+9])[:36]
                        hits.append(Hit(version,no,title,str(path),candidate,skill,typ,anchor,loc,sentence))
                        ch_counts[skill]+=1
            chapter_rows.append([version,no,title,path.name,len(raw),sum(ch_counts.values()),
                                 '; '.join(f'{x}×{n}' for x,n in ch_counts.most_common(12))])
    return hits,chapter_rows


def candidate_match(source, target, allowed_same_chapter=False, cached_grams=None):
    # Each candidate must share same technique or anchor characters; sequence similarity
    # rejects most coincidences. Cross-version chapter numbers alone never suffice for L0.
    match_score=-1; match_hit=None
    sg=cached_grams[id(source)] if cached_grams is not None else grams(source.sentence)
    for other in target:
        if allowed_same_chapter and source.chapter_no != other.chapter_no:
            continue
        same_skill=source.skill==other.skill
        same_family=(source.skill.replace('廿','二十').replace('二十八','十八')==
                     other.skill.replace('廿','二十').replace('二十八','十八'))
        same_person=(source.person!='未判定' and source.person==other.person)
        if not (same_skill or same_family or same_person):
            continue
        j=cached_grams[id(other)] if cached_grams is not None else grams(other.sentence)
        jacc=len(sg&j)/max(1,len(sg|j))
        # For renamed techniques, shared scene meaning/person can still align.
        score=(0.68*jacc + 0.18*(same_person) + 0.14*(same_skill or same_family))
        if allowed_same_chapter:
            score += 0.03
        if score>match_score:
            match_score=score;match_hit=other
    return match_hit,round(match_score,3)


def source_link(h):
    # File names in JY Markdown are safely URL-encoded.
    return 'https://github.com/OliverCWY/JY/blob/master/Markdown/'+quote(h.version)+'/'+quote('天龙八部')+'/'+quote(Path(h.path).name)


def csv_write(path, header, rows):
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        wr=csv.writer(f)
        wr.writerow(header)
        wr.writerows(rows)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--download',action='store_true',help='Download three Markdown editions from public JY repository')
    ap.add_argument('--corpus',type=Path,help='Existing JY repo checkout')
    ap.add_argument('--output',type=Path,default=Path('tianlong_diff'))
    ap.add_argument('--max-candidates',type=int,default=500,help='Max alignment rows in candidate sheet')
    args=ap.parse_args()
    if not args.download and not args.corpus:
        ap.error('Use --download or --corpus')
    output=args.output.resolve();output.mkdir(parents=True,exist_ok=True)
    root=download_source(output/'sources') if args.download else corpus_dir(args.corpus.resolve())
    hits, chrows=parse_hits(root)
    if not hits:
        raise RuntimeError('No scenes extracted: check Markdown contents')
    csv_write(output/'chapter_scan.csv',
              ['版本','章序(仅本版有效)','章节','源文件','字符数','命中数','命中技法TOP12'],chrows)
    rows=[]
    for h in hits:
        rows.append([h.version,h.chapter_no,h.chapter,h.person,h.skill,h.context_type,
                     h.location,h.anchor,source_link(h)])
    csv_write(output/'person_skill_hits.csv',
              ['版本','章节序号','章节','邻近人物(非自动认定施术者)','武功名称','语境分类','地点线索','极短原文锚点','原文链接'],rows)
    cnt=Counter((h.version,h.person,h.skill,h.context_type) for h in hits)
    count_rows=[list(k)+[v] for k,v in sorted(cnt.items())]
    csv_write(output/'person_skill_matrix.csv',
              ['版本','邻近人物','武功','语境分类','出现次数(非实际施展次数)'],count_rows)
    by_version={ver:[x for x in hits if x.version==ver] for ver in VERSIONS}
    # Book-wide A vs B; B vs C same chapter alignment.
    selected=[x for x in hits if x.person in ('慕容复','慕容博','乔峰／萧峰','庄聚贤／游坦之','王玉燕／王语嫣')]
    pairs=[('旧版','三联版',False),('三联版','新修版',True)]
    cached_grams={id(x):grams(x.sentence) for x in hits}
    # Inverted index avoids exhaustive all-pairs comparison.
    by_skill={v:defaultdict(list) for v in VERSIONS}
    by_person={v:defaultdict(list) for v in VERSIONS}
    for ver, vv in by_version.items():
        for h in vv:
            by_skill[ver][h.skill].append(h)
            if h.person != '未判定':
                by_person[ver][h.person].append(h)
    alignrows=[]
    for a,b,same_ch in pairs:
        for h in [x for x in selected if x.version==a]:
            pool=list(by_skill[b].get(h.skill,[]))
            if h.skill=='降龙十八掌': pool+=by_skill[b].get('降龙二十八掌',[])+by_skill[b].get('降龙廿八掌',[])
            if h.skill in ('降龙二十八掌','降龙廿八掌'): pool+=by_skill[b].get('降龙十八掌',[])
            # A shared person alone is not enough: keep local scene (same location)
            # or a chapter-level filter for B↔C.
            pool+=[x for x in by_person[b].get(h.person,[]) if
                   (same_ch and x.chapter_no==h.chapter_no) or
                   (h.location!='未定位' and x.location==h.location)]
            pool=list({id(x):x for x in pool}.values())
            q,s=candidate_match(h,pool,same_ch,cached_grams)
            if q and s>=0.32:
                state='候选：需逐字人工核对'
                if h.skill!=q.skill:
                    state='候选：可能改名／改技法（必须人工核对）'
                alignrows.append([a,b,h.chapter,q.chapter,h.person,q.person,h.skill,q.skill,
                                  s,state,h.anchor,q.anchor,source_link(h),source_link(q)])
    alignrows.sort(key=lambda r:-r[8])
    csv_write(output/'scene_alignment_candidates.csv',
              ['版本A','版本B','A章节','B章节','A邻近人物','B邻近人物','A功法','B功法','匹配分数(启发式)',
               '状态','A短锚','B短锚','A链接','B链接'],alignrows[:args.max_candidates])
    manifest={'source':'OliverCWY/JY', 'source_url':'https://github.com/OliverCWY/JY',
              'version_chapters':{v:sum(r[0]==v for r in chrows) for v in VERSIONS},
              'number_of_skill_mentions':len(hits),
              'number_of_alignment_candidates':len(alignrows),
              'caveats':['The downloaded Markdown is a third-party transcription, not a verified facsimile of newspaper serials.',
                        'Keyword presence is not evidence that a person can use a technique.',
                        'Cross-chapter matched rows are heuristic candidates, never mechanically asserted historical changes.',
                        'A long technique and its substring are counted once per span.',
                        'Aliases are merged only for requested fictional identities.']}
    (output/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(manifest,ensure_ascii=False,indent=2))
    print('Output:',output)

if __name__=='__main__':
    main()