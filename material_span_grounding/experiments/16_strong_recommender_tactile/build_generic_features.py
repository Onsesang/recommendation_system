"""Assemble generic FashionCLIP features and approximate modality kNN graphs.

The official SMORE implementation forms a dense 825869 x 825869 similarity
matrix before top-k, which is infeasible (~2.7 TB float32 per modality). We
replace only that precomputation with deterministic FAISS IVF cosine search;
the official SMORE model/fusion/loss code remains vendored and reused.
"""
import argparse
import pandas as pd
import torch
from torch.nn import functional as F
from transformers import CLIPModel,AutoProcessor
from common import *

def assemble():
    n=len(pd.read_parquet(DATA/'catalog.parquet'));folder=ART/'feature_chunks';out=DATA/'smore';out.mkdir(parents=True,exist_ok=True)
    image=np.lib.format.open_memmap(out/'image_feat.npy',mode='w+',dtype='float32',shape=(n,512))
    text=np.lib.format.open_memmap(out/'text_feat.npy',mode='w+',dtype='float32',shape=(n,512));image_available=np.zeros(n,dtype=bool);text_available=np.zeros(n,dtype=bool)
    for p in sorted(folder.glob('*.npz')):
        x=np.load(p);ids=x['iid'];image[ids]=x['image'].astype('float32');text[ids]=x['text'].astype('float32');image_available[ids]=True;text_available[ids]=True
    # Text is an independent modality. Image download failures must not erase
    # otherwise available title/features/description evidence.
    missing=np.flatnonzero(~text_available);device='cuda' if torch.cuda.is_available() else 'cpu'
    if len(missing):
        metadata=pd.read_parquet(DATA/'item_metadata.parquet',columns=['iid','text']).set_index('iid')
        model=CLIPModel.from_pretrained(str(CLIP),local_files_only=True).eval().requires_grad_(False).to(device)
        proc=AutoProcessor.from_pretrained(str(CLIP),local_files_only=True)
        for start in range(0,len(missing),512):
            ids=missing[start:start+512];inputs=proc.tokenizer(metadata.loc[ids].text.tolist(),return_tensors='pt',padding=True,truncation=True,max_length=77).to(device)
            with torch.inference_mode(),torch.autocast(device_type=device,dtype=torch.bfloat16,enabled=device=='cuda'):
                feat=F.normalize(model.text_projection(model.text_model(**inputs).pooler_output).float(),dim=-1).cpu().numpy()
            text[ids]=feat;text_available[ids]=True
    image.flush();text.flush();np.save(out/'image_available.npy',image_available);np.save(out/'text_available.npy',text_available)
    return out,image_available,text_available

def knn(feature_path,available,k,dest,seed=SEED):
    import faiss
    if dest.exists():return
    vectors=np.load(feature_path,mmap_mode='r');ids=np.flatnonzero(available).astype('int64');dim=vectors.shape[1]
    nlist=min(8192,max(256,int(np.sqrt(len(ids))*8)));quantizer=faiss.IndexFlatIP(dim)
    index=faiss.IndexIVFFlat(quantizer,dim,nlist,faiss.METRIC_INNER_PRODUCT);rng=np.random.default_rng(seed)
    sample=ids[rng.choice(len(ids),size=min(150000,len(ids)),replace=False)]
    index.train(np.asarray(vectors[sample],dtype='float32'));index.nprobe=32
    for start in range(0,len(ids),50000):index.add_with_ids(np.asarray(vectors[ids[start:start+50000]],dtype='float32'),ids[start:start+50000])
    src=[];dst=[];weight=[]
    for start in range(0,len(ids),10000):
        qids=ids[start:start+10000];score,neighbor=index.search(np.asarray(vectors[qids],dtype='float32'),k+1)
        for j,q in enumerate(qids):
            keep=neighbor[j]!=q;nn=neighbor[j][keep][:k];ss=score[j][keep][:k];valid=nn>=0
            src.append(np.full(valid.sum(),q,dtype='int64'));dst.append(nn[valid]);weight.append(np.maximum(ss[valid],0).astype('float32'))
        if start%100000==0:event('generic_knn','progress',modality=feature_path.stem,done=min(start+10000,len(ids)),total=len(ids))
    src=np.concatenate(src);dst=np.concatenate(dst);weight=np.concatenate(weight)
    # Symmetric normalized adjacency, matching SMORE's sparse graph interface.
    forward_src,forward_dst,forward_weight=src,dst,weight
    src=np.concatenate([forward_src,forward_dst])
    dst=np.concatenate([forward_dst,forward_src])
    weight=np.concatenate([forward_weight,forward_weight])
    deg=np.bincount(src,weights=weight,minlength=len(vectors));norm=weight/np.sqrt(np.maximum(deg[src],1e-12)*np.maximum(deg[dst],1e-12))
    graph=torch.sparse_coo_tensor(torch.tensor(np.stack([src,dst])),torch.tensor(norm,dtype=torch.float32),(len(vectors),len(vectors))).coalesce()
    tmp=dest.with_suffix('.tmp');torch.save(graph,tmp);os.replace(tmp,dest)
    save_json(dest.with_suffix('.json'),{'method':'FAISS IndexIVFFlat cosine on normalized 512D generic FashionCLIP features','faiss_version':faiss.__version__,
      'nlist':nlist,'nprobe':32,'k':k,'index_training_sample':min(150000,len(ids)),'nodes':len(vectors),'feature_items':int(available.sum()),
      'directed_edges_before_symmetrization':int(len(src)//2),'seed':seed,'self_edges_removed':True,'negative_cosine_clamped_to_zero':True,
      'reverse_edges_added':True,'symmetric_renormalization':True,'exact_neighbor_recall_measured':False,'graph_sha256':sha(dest)})

def main():
    assert (ART/'tactile_coverage.json').exists(),'full feature inference must complete first';event('generic_features','started')
    out,image_available,text_available=assemble();knn(out/'image_feat.npy',image_available,40,out/'image_adj_40_True.pt');knn(out/'text_feat.npy',text_available,10,out/'text_adj_10_True.pt',SEED+1)
    graph_meta={name:load_json(out/name) for name in ('image_adj_40_True.json','text_adj_10_True.json')}
    save_json(ART/'generic_feature_report.json',{'status':'complete','encoder':'unfine-tuned pinned FashionCLIP feature extractor','fashionclip_encoder_frozen':True,
      'smore_modality_embedding_tables_trainable':True,'dedicated_last2_or_tactile_pseudolabel_inputs_used':False,'implicit_tactile_cues_possible_in_image_or_text':True,
      'tactile_features_used':False,'items':len(image_available),'image_covered':int(image_available.sum()),'text_covered':int(text_available.sum()),'dimension':512,
      'smore_upstream':'https://github.com/kennethorq/SMORE','adaptation':'fixed-seed FAISS IVF approximate kNN; self edges removed; negative cosine clamped to zero; reverse-edge union and symmetric renormalization',
      'exact_neighbor_recall_measured':False,'graph_metadata':graph_meta})
    event('generic_features','complete',items=len(image_available),image_covered=int(image_available.sum()),text_covered=int(text_available.sum()))

if __name__=='__main__':main()
