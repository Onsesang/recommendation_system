#!/usr/bin/env python3
"""Leakage-safe staged FashionCLIP multi-label fine-tuning on review-derived targets."""
import argparse, json, random
from pathlib import Path
import numpy as np
import torch
from PIL import Image
from sklearn.metrics import average_precision_score, f1_score
from torch import nn
from torch.utils.data import DataLoader, Dataset
from transformers import AutoProcessor, CLIPModel

EXP=Path(__file__).resolve().parent; ROOT=EXP.parents[1]
SNAP=Path("/home/user/onsesang/.cache/huggingface/hub/models--patrickjohncyh--fashion-clip/snapshots/7e3ba62ce16b379a1ab479346b66f192e76f51b7")
IMAGE=Path("/home/user/onsesang/texture_project/images_train")
SPLIT=ROOT/"tactile_coldstart_qwen_v2_full/manifests/family_split_20260901.json"

class Data(Dataset):
    def __init__(self, ids,y,m,processor): self.ids,self.y,self.m,self.processor=ids,y,m,processor
    def __len__(self): return len(self.ids)
    def __getitem__(self,i):
        with Image.open(IMAGE/f"{self.ids[i]}.jpg") as im: px=self.processor(images=im.convert("RGB"),return_tensors="pt")["pixel_values"][0]
        return px,torch.from_numpy(self.y[i]),torch.from_numpy(self.m[i].astype(np.float32))

class Model(nn.Module):
    def __init__(self,n,stage):
        super().__init__(); self.clip=CLIPModel.from_pretrained(SNAP,local_files_only=True); self.head=nn.Linear(self.clip.config.projection_dim,n)
        for p in self.clip.parameters(): p.requires_grad=False
        if stage in {"projection","last1","last2","full"}:
            for p in self.clip.visual_projection.parameters(): p.requires_grad=True
        layers=self.clip.vision_model.encoder.layers
        if stage=="last1": chosen=layers[-1:]
        elif stage=="last2": chosen=layers[-2:]
        elif stage=="full": chosen=layers
        else: chosen=[]
        for layer in chosen:
            for p in layer.parameters(): p.requires_grad=True
    def forward(self,x): return self.head(self.clip.get_image_features(pixel_values=x))

def scores(y,m,p,threshold):
    keep=m.astype(bool); true=(y>=.5).astype(int); pred=(p>=threshold).astype(int)
    ap=[]
    for j in range(y.shape[1]):
        k=keep[:,j]
        if k.sum() and len(np.unique(true[k,j]))>1: ap.append(average_precision_score(true[k,j],p[k,j]))
    return {"micro_f1":float(f1_score(true[keep],pred[keep],zero_division=0)),"macro_ap":float(np.mean(ap)) if ap else None,"observed":int(keep.sum())}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--stage",choices=["frozen","projection","last1","last2","full"],required=True); ap.add_argument("--epochs",type=int,default=40); args=ap.parse_args()
    random.seed(20260903); np.random.seed(20260903); torch.manual_seed(20260903)
    z=np.load(EXP/"artifacts/product_class_targets.npz"); ids=z["product_ids"].astype(str); y=z["values"].astype(np.float32); m=z["mask"].astype(bool); idx={x:i for i,x in enumerate(ids)}
    split=json.loads(SPLIT.read_text())["splits"]; processor=AutoProcessor.from_pretrained(SNAP,local_files_only=True)
    loaders={}
    for name in ("train","development","test"):
        ii=np.array([idx[x] for x in split[name] if x in idx and m[idx[x]].any()]); loaders[name]=DataLoader(Data(ids[ii],y[ii],m[ii],processor),batch_size=64,shuffle=name=="train",num_workers=8,pin_memory=True)
    model=Model(y.shape[1],args.stage).cuda(); groups=[]
    head=[p for n,p in model.named_parameters() if p.requires_grad and n.startswith("head")]; enc=[p for n,p in model.named_parameters() if p.requires_grad and not n.startswith("head")]
    groups.append({"params":head,"lr":1e-4});
    if enc: groups.append({"params":enc,"lr":5e-6})
    opt=torch.optim.AdamW(groups,weight_decay=.01); best=None; patience=0
    def infer(loader):
        model.eval(); yy=[];mm=[];pp=[]
        with torch.inference_mode():
            for x,a,b in loader: pp.append(torch.sigmoid(model(x.cuda())).cpu().numpy()); yy.append(a.numpy()); mm.append(b.numpy())
        return np.concatenate(yy),np.concatenate(mm),np.concatenate(pp)
    for epoch in range(args.epochs):
        model.train()
        for x,a,b in loaders["train"]:
            x,a,b=x.cuda(),a.cuda(),b.cuda(); opt.zero_grad(); loss=(nn.functional.binary_cross_entropy_with_logits(model(x),a,reduction="none")*b).sum()/b.sum().clamp_min(1); loss.backward(); nn.utils.clip_grad_norm_(model.parameters(),1.); opt.step()
        dy,dm,dp=infer(loaders["development"]); metric=scores(dy,dm,dp,.5)["macro_ap"] or -1
        if best is None or metric>best[0]: best=(metric,{k:v.detach().cpu() for k,v in model.state_dict().items()},epoch); patience=0
        else: patience+=1
        print(f"stage={args.stage} epoch={epoch} dev_macro_ap={metric:.6f}",flush=True)
        if patience>=6: break
    model.load_state_dict(best[1]); dy,dm,dp=infer(loaders["development"]); thresholds=np.linspace(.1,.9,17); threshold=max(thresholds,key=lambda t:scores(dy,dm,dp,t)["micro_f1"])
    ty,tm,tp=infer(loaders["test"]); result={"stage":args.stage,"best_epoch":best[2],"threshold":float(threshold),"development":scores(dy,dm,dp,threshold),"test":scores(ty,tm,tp,threshold)}
    out=EXP/"results"; out.mkdir(exist_ok=True); torch.save(best[1],out/f"fashionclip_{args.stage}.pt"); (out/f"metrics_{args.stage}.json").write_text(json.dumps(result,indent=2)); print(json.dumps(result))
if __name__=="__main__": main()
