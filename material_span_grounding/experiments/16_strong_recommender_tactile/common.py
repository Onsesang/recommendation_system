"""Isolated full-catalog experiment utilities. Never write outside ROOT."""
from pathlib import Path
import hashlib
import json
import os
import time
import numpy as np

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parent.parent
WORKSPACE = PROJECT.parent
ART = ROOT / 'artifacts'
DATA = ROOT / 'data'
SEED = 20260904
CLASSES = ['soft','firm','smooth','rough','non_elastic','elastic','thin','thick','flexible','stiff','warm','cool','spongy','crisp']
RELIABLE = ['smooth','rough','thin','thick','flexible','stiff','warm','cool']
CHECKPOINT = PROJECT / 'experiments/12_class_multilabel_fashionclip_ft/models/fashionclip_last2.pt'
CHECKPOINT_SHA = '073b542a9d6bd4450aa1f48596c756cc0812b1b5d914945e8f94f7c3fda1934a'
CLIP = WORKSPACE / '.cache/huggingface/hub/models--patrickjohncyh--fashion-clip/snapshots/7e3ba62ce16b379a1ab479346b66f192e76f51b7'

def sha(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for b in iter(lambda:f.read(8<<20), b''): h.update(b)
    return h.hexdigest()

def save_json(path, value):
    path=Path(path)
    assert path.resolve().is_relative_to(ROOT)
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+'.tmp')
    tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    os.replace(tmp,path)

def load_json(path):
    return json.loads(Path(path).read_text())

def event(stage, status, **extra):
    ART.mkdir(parents=True,exist_ok=True)
    row={'time_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'stage':stage,'status':status,**extra}
    with open(ART/'events.jsonl','a') as f: f.write(json.dumps(row,ensure_ascii=False)+'\n')
    print(json.dumps(row,ensure_ascii=False),flush=True)
    # Secret belongs in the launch environment, never source/checkpoints/reports.
    url=os.environ.get('DISCORD_WEBHOOK_URL')
    if url and status in ('started','complete','failed','blocked'):
        import urllib.request
        message=f'[Strong recommender] {stage}: {status}\n'+json.dumps(extra,ensure_ascii=False)[:1200]
        try:
            req=urllib.request.Request(url,data=json.dumps({'content':message,'allowed_mentions':{'parse':[]}}).encode(),headers={'Content-Type':'application/json','User-Agent':'Mozilla/5.0'})
            with urllib.request.urlopen(req,timeout=15) as r: code=r.status
            with open(ART/'notifications.jsonl','a') as f: f.write(json.dumps({'time_utc':row['time_utc'],'stage':stage,'status':status,'http':code})+'\n')
        except Exception as e:
            # Exception text can include credentials. Record class only.
            with open(ART/'notifications.jsonl','a') as f: f.write(json.dumps({'stage':stage,'error_type':type(e).__name__})+'\n')

def distribution(a):
    a=np.asarray(a)
    return {'n':int(a.size),'mean':float(a.mean()) if a.size else None,'median':float(np.median(a)) if a.size else None,
            **{f'p{p}':float(np.percentile(a,p)) if a.size else None for p in (25,50,75,90,95)},
            **{f'ge_{k}':int((a>=k).sum()) for k in (1,2,3,5,10,20)},'zero':int((a==0).sum())}
