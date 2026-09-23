"""eSASRec adapter based on the vendored official LiGR implementation.

The official package pins RecTools 0.13 and numpy<2 while this validated image
environment has numpy 2.2.6. To keep one reproducible environment, the small
LiGR/SwiGLU module is adapted directly and its provenance is recorded. The
training objective uses sampled softmax (64 uniform train-catalog negatives).
"""
import math
import torch
from torch import nn
from torch.nn import functional as F
from models import SASRec

class SwiGLU(nn.Module):
    def __init__(self,dim,mult=2,dropout=.2):
        super().__init__();hidden=dim*mult
        self.a=nn.Linear(dim,hidden,bias=False);self.b=nn.Linear(dim,hidden,bias=False)
        self.out=nn.Linear(hidden,dim,bias=False);self.drop=nn.Dropout(dropout)
    def forward(self,x):return self.out(self.drop(F.silu(self.a(x))*self.b(x)))

class LiGRBlock(nn.Module):
    def __init__(self,dim,heads,dropout):
        super().__init__();self.attn=nn.MultiheadAttention(dim,heads,dropout=dropout,batch_first=True)
        self.ln1=nn.LayerNorm(dim);self.ln2=nn.LayerNorm(dim);self.ff=SwiGLU(dim,2,dropout)
        self.g1=nn.Linear(dim,dim);self.g2=nn.Linear(dim,dim);self.d1=nn.Dropout(dropout);self.d2=nn.Dropout(dropout)
    def forward(self,x,padding):
        q=self.ln1(x);causal=torch.triu(torch.ones(x.shape[1],x.shape[1],device=x.device,dtype=torch.bool),1)
        a=self.attn(q,q,q,attn_mask=causal,key_padding_mask=padding,need_weights=False)[0]
        x=x+torch.sigmoid(self.g1(x))*self.d1(a)
        z=self.ln2(x);x=x+torch.sigmoid(self.g2(x))*self.d2(self.ff(z))
        return x.masked_fill(padding.unsqueeze(-1),0)

class ESASRec(SASRec):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        layers=kwargs.get('layers',2);heads=kwargs.get('heads',2);dropout=kwargs.get('dropout',.2)
        self.blocks=nn.ModuleList([LiGRBlock(self.dim,heads,dropout) for _ in range(layers)])

    def sampled_softmax_loss(self,seq,pos,neg):
        """neg: [batch,time,nneg], IDs shifted by one."""
        z=self(seq);valid=pos>0;query=z[valid];positive=self.item(pos[valid])
        negative=self.item(neg[valid])
        logits=torch.cat([(query*positive).sum(-1,keepdim=True),torch.einsum('bd,bnd->bn',query,negative)],1)
        return F.cross_entropy(logits,torch.zeros(len(query),dtype=torch.long,device=query.device))
