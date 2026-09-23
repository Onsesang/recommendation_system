"""Transparent BPR-MF, normalized LightGCN, causal SASRec baselines.

Equations follow the original model papers. These are local implementations,
not claims to reproduce authors' published Amazon Clothing benchmark metrics.
"""
import math
import torch
from torch import nn
from torch.nn import functional as F

class BPR(nn.Module):
    def __init__(self,nusers,nitems,dim=64,**kwargs):
        super().__init__()
        self.user=nn.Embedding(nusers,dim); self.item=nn.Embedding(nitems,dim)
        nn.init.normal_(self.user.weight,std=.01);nn.init.normal_(self.item.weight,std=.01)

    def representations(self): return self.user.weight,self.item.weight

    def loss(self,u,p,n,reg=1e-6):
        ue,ie=self.representations();a,b,c=ue[u],ie[p],ie[n]
        rank=F.softplus(-(a*(b-c)).sum(-1)).mean()
        penalty=(self.user(u).square().sum()+self.item(p).square().sum()+self.item(n).square().sum())/len(u)
        return rank+reg*penalty

class LightGCN(BPR):
    def __init__(self,nusers,nitems,edges,dim=64,layers=3,**kwargs):
        super().__init__(nusers,nitems,dim)
        self.nusers=nusers;self.layers=layers
        u,p=edges
        src=torch.cat([u,p+nusers]);dst=torch.cat([p+nusers,u])
        deg=torch.bincount(src,minlength=nusers+nitems).float().clamp_min(1)
        weights=deg[src].rsqrt()*deg[dst].rsqrt()
        self.register_buffer('adj',torch.sparse_coo_tensor(torch.stack([src,dst]),weights,(nusers+nitems,nusers+nitems)).coalesce())

    def representations(self):
        x=torch.cat([self.user.weight,self.item.weight]); xs=[x]
        for _ in range(self.layers):
            x=torch.sparse.mm(self.adj,x);xs.append(x)
        x=torch.stack(xs).mean(0)
        return x[:self.nusers],x[self.nusers:]

class SASBlock(nn.Module):
    def __init__(self,dim,heads,dropout):
        super().__init__()
        self.attn=nn.MultiheadAttention(dim,heads,dropout=dropout,batch_first=True)
        self.ln1=nn.LayerNorm(dim);self.ln2=nn.LayerNorm(dim)
        self.ff=nn.Sequential(nn.Linear(dim,dim),nn.ReLU(),nn.Dropout(dropout),nn.Linear(dim,dim),nn.Dropout(dropout))

    def forward(self,x,padding):
        q=self.ln1(x)
        causal=torch.triu(torch.ones(x.shape[1],x.shape[1],device=x.device,dtype=torch.bool),1)
        x=q+self.attn(q,x,x,attn_mask=causal,need_weights=False)[0]
        x=self.ln2(x);x=x+self.ff(x)
        return x.masked_fill(padding.unsqueeze(-1),0)

class SASRec(nn.Module):
    def __init__(self,nitems,dim=64,layers=2,heads=2,maxlen=50,dropout=.2,**kwargs):
        super().__init__(); self.dim=dim;self.maxlen=maxlen
        # zero denotes padding, real global catalog IDs are shifted by one.
        self.item=nn.Embedding(nitems+1,dim,padding_idx=0)
        self.pos=nn.Embedding(maxlen,dim);self.drop=nn.Dropout(dropout)
        self.blocks=nn.ModuleList([SASBlock(dim,heads,dropout) for _ in range(layers)])
        self.norm=nn.LayerNorm(dim)
        nn.init.normal_(self.item.weight,std=.02)
        with torch.no_grad(): self.item.weight[0].zero_()

    def forward(self,seq):
        pad=seq==0
        x=self.drop(self.item(seq)*math.sqrt(self.dim)+self.pos(torch.arange(seq.shape[1],device=seq.device)))
        x=x.masked_fill(pad.unsqueeze(-1),0)
        for block in self.blocks:x=block(x,pad)
        return self.norm(x)

    def loss(self,seq,pos,neg):
        z=self(seq);valid=pos>0
        a=(z*self.item(pos)).sum(-1)[valid]
        b=(z*self.item(neg)).sum(-1)[valid]
        return F.softplus(-a).mean()+F.softplus(b).mean()
