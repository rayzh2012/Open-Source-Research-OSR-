import os,time,random,subprocess,sys,requests
from pathlib import Path
from urllib.parse import quote

ROOT='1sHOCwDh5aLu7228jyTSBpDi8Rro8pxkd'
RUN='BULK_500GB_SECONDARY_CORPUS_2026-08'
WORK=Path('/content/bulk500'); WORK.mkdir(exist_ok=True)
SAFETY=15*1024**3
DCHUNK=16*1024**2
UCHUNK=64*1024**2
DATASETS=[
 ('Geralt-Targaryen/Literature-zh','Literature-zh_229GB'),
 ('Morton-Li/ChineseWebText2.0-HighQuality','ChineseWebText2.0-HighQuality_279GB')]
EXT=('.parquet','.jsonl','.json','.zst','.gz','.bz2','.zip','.tar')

subprocess.run([sys.executable,'-m','pip','-q','install','-U','huggingface_hub','google-auth','requests'],check=True)
from huggingface_hub import HfApi,login
from google.colab import auth
import google.auth
from google.auth.transport.requests import AuthorizedSession

tok=os.environ.get('HF_TOKEN')
if not tok: raise RuntimeError('HF_TOKEN missing from Colab Secret')
login(token=tok,add_to_git_credential=False)
auth.authenticate_user()
creds,_=google.auth.default(scopes=['https://www.googleapis.com/auth/drive'])
g=AuthorizedSession(creds)
h=requests.Session(); h.headers.update({'Authorization':f'Bearer {tok}','User-Agent':'bulk500-night-run/1.0'})
api=HfApi(token=tok)

def wait(attempt,base=20,cap=600):
 return min(cap,base*(2**max(0,attempt-1)))+random.randint(0,12)

def folder(name,parent):
 safe=name.replace("'","\\'")
 q=f"name = '{safe}' and '{parent}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
 r=g.get('https://www.googleapis.com/drive/v3/files',params={'q':q,'fields':'files(id,name)'},timeout=120); r.raise_for_status(); x=r.json().get('files',[])
 if x:return x[0]['id']
 r=g.post('https://www.googleapis.com/drive/v3/files',json={'name':name,'parents':[parent],'mimeType':'application/vnd.google-apps.folder'},params={'fields':'id'},timeout=120); r.raise_for_status(); return r.json()['id']

def find(name,parent):
 safe=name.replace("'","\\'")
 q=f"name = '{safe}' and '{parent}' in parents and trashed = false"
 r=g.get('https://www.googleapis.com/drive/v3/files',params={'q':q,'fields':'files(id,name,size,md5Checksum,webViewLink)','pageSize':100},timeout=120); r.raise_for_status(); return r.json().get('files',[])

def free_space():
 r=g.get('https://www.googleapis.com/drive/v3/about',params={'fields':'storageQuota'},timeout=120); r.raise_for_status(); q=r.json().get('storageQuota',{}); lim=int(q.get('limit',0) or 0); use=int(q.get('usage',0) or 0); return None if not lim else max(0,lim-use)

def start_upload(path,parent,name):
 total=os.path.getsize(path)
 u='https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable&fields=id,name,size,md5Checksum,webViewLink'
 r=g.post(u,headers={'Content-Type':'application/json; charset=UTF-8','X-Upload-Content-Type':'application/octet-stream','X-Upload-Content-Length':str(total)},json={'name':name,'parents':[parent]},timeout=120); r.raise_for_status(); loc=r.headers.get('Location')
 if not loc: raise RuntimeError('Drive resumable Location missing')
 return loc

def offset(url,total):
 r=g.put(url,headers={'Content-Length':'0','Content-Range':f'bytes */{total}'},timeout=120,allow_redirects=False)
 if r.status_code in (200,201): return total,r.json()
 if r.status_code==308:
  rg=r.headers.get('Range'); return (int(rg.split('-')[-1])+1 if rg else 0),None
 raise RuntimeError(f'Drive offset HTTP {r.status_code}: {r.text[:300]}')

def upload(path,parent,name):
 total=os.path.getsize(path)
 for x in find(name,parent):
  try:
   if int(x.get('size',-1))==total: print('SKIP DRIVE',name); return x
  except: pass
 url=start_upload(path,parent,name); sent=0
 with open(path,'rb') as f:
  while sent<total:
   f.seek(sent); data=f.read(min(UCHUNK,total-sent)); end=sent+len(data)-1
   for a in range(1,16):
    try:
     r=g.put(url,headers={'Content-Length':str(len(data)),'Content-Range':f'bytes {sent}-{end}/{total}'},data=data,timeout=420,allow_redirects=False)
     if r.status_code in (200,201): print('DRIVE 100%',name); return r.json()
     if r.status_code==308:
      rg=r.headers.get('Range'); sent=int(rg.split('-')[-1])+1 if rg else offset(url,total)[0]; print(f'DRIVE {name}: {sent/total*100:.1f}%'); break
     if r.status_code in (408,409,429,500,502,503,504): raise RuntimeError(f'transient {r.status_code}')
     raise RuntimeError(f'Drive HTTP {r.status_code}: {r.text[:300]}')
    except Exception as e:
     if a==15: raise
     print('DRIVE RETRY',a,repr(e)); time.sleep(min(120,5*a))
     try: sent,done=offset(url,total)
     except: pass
 raise RuntimeError('upload ended unexpectedly')

def list_files(repo):
 for a in range(1,8):
  try:
   out=[]
   for x in api.list_repo_tree(repo_id=repo,repo_type='dataset',recursive=True,expand=True):
    p=getattr(x,'path',''); s=getattr(x,'size',None)
    if p and isinstance(s,int) and s>0 and p.lower().endswith(EXT): out.append((p,s))
   out.sort(); print(repo,'files',len(out),'GiB',round(sum(s for _,s in out)/1024**3,2)); return out
  except Exception as e:
   if a==7: raise
   w=wait(a,60,600); print('ENUM RETRY',repo,repr(e),'sleep',w); time.sleep(w)

def get_file(repo,src,size,stage):
 name=src.replace('/','__'); final=stage/name; part=stage/(name+'.part'); got=part.stat().st_size if part.exists() else 0
 url=f'https://huggingface.co/datasets/{repo}/resolve/main/{quote(src,safe="/")}?download=true'
 for a in range(1,13):
  try:
   headers={'Range':f'bytes={got}-'} if got else {}
   r=h.get(url,headers=headers,stream=True,timeout=900,allow_redirects=True)
   if r.status_code==429:
    ra=r.headers.get('Retry-After'); w=max(60,int(float(ra))) if ra else wait(a,60,900); print('HF 429 sleep',w); time.sleep(w); continue
   if r.status_code in (500,502,503,504): time.sleep(wait(a)); continue
   if r.status_code not in (200,206): raise RuntimeError(f'HF HTTP {r.status_code}')
   if got and r.status_code==200: got=0; part.unlink(missing_ok=True)
   mode='ab' if got and r.status_code==206 else 'wb'; last=got
   with open(part,mode) as f:
    for chunk in r.iter_content(DCHUNK):
     if chunk:
      f.write(chunk); got+=len(chunk)
      if got-last>=256*1024**2: print(f'HF {name}: {got/1024**3:.2f}/{size/1024**3:.2f} GiB'); last=got
   if got==size: part.replace(final); return final
   print('INCOMPLETE',name,got,size)
  except Exception as e:
   if a==12: raise
   w=wait(a); print('HF RETRY',a,repr(e),'sleep',w); time.sleep(w)
 raise RuntimeError('download exhausted')

run_id=folder(RUN,ROOT)
fs=free_space(); print('DRIVE FREE GiB',None if fs is None else round(fs/1024**3,2))
plans=[]
for repo,label in DATASETS:
 files=list_files(repo); plans.append((repo,label,files))
print('TOTAL PLANNED GiB',round(sum(s for _,_,f in plans for _,s in f)/1024**3,2))

for repo,label,files in plans:
 did=folder(label,run_id); stage=WORK/label; stage.mkdir(exist_ok=True)
 for i,(src,size) in enumerate(files,1):
  dest=src.replace('/','__')
  exists=False
  for x in find(dest,did):
   try:
    if int(x.get('size',-1))==size: exists=True; break
   except: pass
  if exists: print(f'[{i}/{len(files)}] SKIP',dest); continue
  fs=free_space()
  if fs is not None and fs<size+SAFETY: print('STOP FOR DRIVE QUOTA'); raise SystemExit
  print(f'[{i}/{len(files)}] {repo} {src} {size/1024**3:.3f} GiB')
  local=get_file(repo,src,size,stage)
  upload(str(local),did,dest)
  local.unlink(missing_ok=True); Path(str(local)+'.part').unlink(missing_ok=True)
print('DONE — ALL AVAILABLE SHARDS ARCHIVED')
