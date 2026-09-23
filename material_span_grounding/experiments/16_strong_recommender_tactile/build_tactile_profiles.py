"""Resume-safe MAIN-image expansion, official Last2 inference only.

Generic features use separately loaded *unfine-tuned* FashionCLIP image/text
encoders. No Last2 weights/probabilities are supplied to the generic baseline.
"""
import argparse
import concurrent.futures
import io
import urllib.request
from urllib.parse import urlparse
import pandas as pd
import torch
from torch import nn
from torch.nn import functional as F
from PIL import Image
from transformers import CLIPModel,AutoProcessor
from common import *

class TactileClassifier(nn.Module):
    def __init__(self,clip):
        super().__init__();self.vision=clip.vision_model;self.projection=clip.visual_projection
        self.head=nn.Linear(self.projection.out_features,len(CLASSES))
    def forward(self,pixels):
        return self.head(F.normalize(self.projection(self.vision(pixel_values=pixels).pooler_output),dim=-1))

def load_last2(device):
    assert sha(CHECKPOINT)==CHECKPOINT_SHA
    ck=torch.load(CHECKPOINT,map_location='cpu',weights_only=False)
    assert ck['classes']==CLASSES
    model=TactileClassifier(CLIPModel.from_pretrained(str(CLIP),local_files_only=True))
    # The official training script intentionally persisted only trainable
    # Last2 parameters. Frozen layers come from the hash-pinned FashionCLIP.
    incompatible=model.load_state_dict(ck['state_dict'],strict=False)
    if incompatible.unexpected_keys:
        raise RuntimeError(f'unexpected Last2 keys: {incompatible.unexpected_keys}')
    loaded=set(ck['state_dict'])
    required={'head.weight','head.bias','projection.weight'}
    required.update(k for k in model.state_dict() if k.startswith(('vision.encoder.layers.10.','vision.encoder.layers.11.','vision.post_layernorm.')))
    missing_required=required-loaded
    if missing_required:
        raise RuntimeError(f'official Last2 missing trained keys: {sorted(missing_required)}')
    model.eval().requires_grad_(False).to(device)
    processor=AutoProcessor.from_pretrained(str(CLIP),local_files_only=True)
    return model,processor

def fetch_image(row):
    url=row.image_url
    if not isinstance(url,str) or not url:return {'iid':int(row.iid),'status':'no_url'}
    # Images are untrusted external data: allow only the expected Amazon CDN.
    if urlparse(url).hostname not in ('m.media-amazon.com','images-na.ssl-images-amazon.com','images-eu.ssl-images-amazon.com'):
        return {'iid':int(row.iid),'status':'unapproved_image_host'}
    p=DATA/'amazon_fashion_images'/f'{row.iid}.jpg';p.parent.mkdir(parents=True,exist_ok=True)
    started=time.monotonic()
    for attempt in range(3):
        try:
            if p.exists():
                with Image.open(p) as im:im.verify()
                return {'iid':int(row.iid),'status':'cached','path':str(p),'bytes':p.stat().st_size,'seconds':time.monotonic()-started}
            req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'})
            with urllib.request.urlopen(req,timeout=20) as r:
                content=r.read((25<<20)+1)
                assert len(content)<=(25<<20),'image exceeds 25MiB cap'
            with Image.open(io.BytesIO(content)) as im:im.verify()
            tmp=p.with_suffix('.part');tmp.write_bytes(content);os.replace(tmp,p)
            return {'iid':int(row.iid),'status':'downloaded','path':str(p),'bytes':len(content),'seconds':time.monotonic()-started}
        except Exception as e:
            error=type(e).__name__
            if attempt<2:time.sleep(.5*(attempt+1))
    return {'iid':int(row.iid),'status':'failed','error_type':error,'seconds':time.monotonic()-started}

def finalize(metadata,eligible,chunks):
    files=[p for p in chunks.glob('*.parquet') if not p.name.endswith('.downloads.parquet')]
    table=pd.concat([pd.read_parquet(p) for p in files],ignore_index=True).drop_duplicates('iid')
    download_files=sorted(chunks.glob('*.downloads.parquet'))
    downloads=pd.concat([pd.read_parquet(p) for p in download_files],ignore_index=True).drop_duplicates('iid',keep='last')
    assert len(downloads)==len(eligible),f'unfinished download coverage: {len(downloads)}/{len(eligible)}'
    assert set(table.iid)<=set(downloads.iid)
    table.to_parquet(ART/'product_tactile_profiles.parquet',index=False)
    status_counts={str(k):int(v) for k,v in downloads.status.value_counts().items()}
    failure_types={str(k):int(v) for k,v in downloads.loc[downloads.status=='failed','error_type'].fillna('unknown').value_counts().items()}
    result={'catalog_items':len(metadata),'metadata_available':int(metadata.metadata_available.sum()),'image_url_available':int(metadata.image_url.notna().sum()),
            'last2_inference_success':len(table),'coverage_fraction':len(table)/len(metadata),'failed_or_unavailable':len(metadata)-len(table),
            'expansion_ratio_vs_8498':len(table)/8498,'checkpoint_sha256':CHECKPOINT_SHA,'classes':CLASSES,
            'download_records':len(downloads),'download_status_counts':status_counts,'download_failure_types':failure_types,
            'image_download_or_cache_success':int(downloads.status.isin(['downloaded','cached']).sum()),
            'generic_encoder':'frozen original FashionCLIP (not Last2); image and product text; SMORE encoder adaptation',
            'last2_retrained':False,'qwen_rerun':False}
    save_json(ART/'tactile_coverage.json',result)
    event('full_image_inference','complete',inference_success=len(table),catalog_items=len(metadata))

def main():
    p=argparse.ArgumentParser();p.add_argument('--pilot',action='store_true');p.add_argument('--workers',type=int,default=24);p.add_argument('--batch-size',type=int,default=128)
    p.add_argument('--shard-index',type=int,default=0);p.add_argument('--num-shards',type=int,default=1);p.add_argument('--finalize-only',action='store_true');args=p.parse_args()
    assert 0<=args.shard_index<args.num_shards
    if not args.pilot:
        assert (ART/'image_pilot.json').exists(),'1000-item pilot required'
        assert load_json(ART/'image_pilot.json')['inference_success']>0
    metadata=pd.read_parquet(DATA/'item_metadata.parquet').sort_values('iid')
    # Pilot is first 1000 image-URL eligible IDs, independent of labels/outcomes.
    eligible=metadata[metadata.image_url.notna()]
    if args.pilot:eligible=eligible.head(1000)
    chunks=ART/'feature_chunks';chunks.mkdir(parents=True,exist_ok=True)
    if args.finalize_only:
        assert not args.pilot and args.num_shards==1
        finalize(metadata,eligible,chunks);return
    mode='image_pilot' if args.pilot else 'full_image_inference';event(mode,'started',shard_index=args.shard_index,num_shards=args.num_shards)
    torch.set_num_threads(8);device='cuda' if torch.cuda.is_available() else 'cpu'
    model,proc=load_last2(device)
    generic=CLIPModel.from_pretrained(str(CLIP),local_files_only=True).eval().requires_grad_(False).to(device)
    start=time.monotonic();total=0;download_records=[];infer_seconds=0.
    for startrow in range(0,len(eligible),1000):
        chunk_index=startrow//1000
        if chunk_index%args.num_shards!=args.shard_index:continue
        group=eligible.iloc[startrow:startrow+1000];tag=f'{int(group.iid.iloc[0]):07d}_{int(group.iid.iloc[-1]):07d}'
        profilefile=chunks/f'{tag}.parquet';genericfile=chunks/f'{tag}.npz'
        if profilefile.exists() and genericfile.exists():
            existing=len(pd.read_parquet(profilefile))
            # Pilot/previous failures are retried in full mode; a genuinely
            # complete chunk is the only safe resume boundary.
            if args.pilot or existing==len(group):
                total+=existing;continue
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
            downloads=list(pool.map(fetch_image,group.itertuples(index=False)))
        download_records.extend(downloads)
        pd.DataFrame(downloads).to_parquet(chunks/f'{tag}.downloads.parquet',index=False)
        good={r['iid']:r for r in downloads if r['status'] in ('downloaded','cached')}
        profiles=[];vis=[];txt=[];feature_ids=[]
        for b in range(0,len(group),args.batch_size):
            batch=group.iloc[b:b+args.batch_size];valid=batch[batch.iid.isin(good)]
            if len(valid):
                images=[]
                for row in valid.itertuples():
                    with Image.open(good[row.iid]['path']) as im:images.append(im.convert('RGB'))
                pixels=proc(images=images,return_tensors='pt')['pixel_values'].to(device)
                if device=='cuda':torch.cuda.synchronize()
                t=time.monotonic()
                with torch.inference_mode(),torch.autocast(device_type=device,dtype=torch.bfloat16,enabled=device=='cuda'):
                    probs=torch.sigmoid(model(pixels).float()).cpu().numpy()
                    vf=F.normalize(generic.visual_projection(generic.vision_model(pixel_values=pixels).pooler_output).float(),dim=-1).cpu().numpy()
                    inputs=proc.tokenizer(valid.text.tolist(),return_tensors='pt',padding=True,truncation=True,max_length=77).to(device)
                    tf=F.normalize(generic.text_projection(generic.text_model(**inputs).pooler_output).float(),dim=-1).cpu().numpy()
                if device=='cuda':torch.cuda.synchronize()
                infer_seconds+=time.monotonic()-t
                assert np.isfinite(probs).all() and ((probs>=0)&(probs<=1)).all()
                result=valid[['iid','parent_asin']].reset_index(drop=True)
                for j,name in enumerate(CLASSES):result[name]=probs[:,j]
                profiles.append(result);vis.append(vf.astype('float16'));txt.append(tf.astype('float16'));feature_ids.extend(valid.iid.tolist())
        combined=pd.concat(profiles,ignore_index=True) if profiles else pd.DataFrame(columns=['iid','parent_asin',*CLASSES])
        tmp=profilefile.with_suffix('.parquet.tmp');combined.to_parquet(tmp,index=False);os.replace(tmp,profilefile)
        # np.savez appends .npz; open explicit handle for atomic replacement.
        tmp=genericfile.with_suffix('.npz.tmp')
        with open(tmp,'wb') as f:np.savez(f,iid=np.array(feature_ids),image=np.concatenate(vis) if vis else np.empty((0,512)),text=np.concatenate(txt) if txt else np.empty((0,512)))
        os.replace(tmp,genericfile);total+=len(combined)
        event(mode,'chunk',processed_url_items=startrow+len(group),inference_success=total,total_url_items=len(eligible))
    elapsed=time.monotonic()-start
    if args.pilot:
        sizes=[r.get('bytes',0) for r in download_records];latencies=[r.get('seconds',0) for r in download_records]
        result={'pilot_selection':'first 1000 sorted canonical IDs with official URL','requested':len(eligible),'inference_success':total,
                'download_success_rate':total/max(len(eligible),1),'elapsed_seconds':elapsed,'gpu_inference_seconds':infer_seconds,
                'gpu_inference_items_per_second':total/infer_seconds if infer_seconds else None,
                'latency_seconds':distribution(latencies),'disk_bytes':sum(sizes),'estimated_full_image_bytes':int(np.mean(sizes)*metadata.image_url.notna().sum()) if sizes else None,
                'estimated_full_wall_seconds_at_pilot_rate':elapsed/max(len(eligible),1)*int(metadata.image_url.notna().sum()),
                'max_cuda_allocated':torch.cuda.max_memory_allocated() if device=='cuda' else 0,'checkpoint_sha256':CHECKPOINT_SHA}
        save_json(ART/'image_pilot.json',result)
    else:
        if args.num_shards==1:finalize(metadata,eligible,chunks)
        else:event(mode,'shard_complete',shard_index=args.shard_index,num_shards=args.num_shards,inference_success_this_shard=total,elapsed_seconds=round(elapsed,2))
    if args.pilot:event(mode,'complete',inference_success=total,elapsed_seconds=round(elapsed,2))

if __name__=='__main__':main()
