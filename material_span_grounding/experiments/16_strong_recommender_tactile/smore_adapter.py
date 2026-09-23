"""Thin scalable adapter around the vendored official WSDM 2025 SMORE model."""
import sys
import numpy as np
import scipy.sparse as sp
import torch
from common import ROOT,DATA

_vendor=str(ROOT/'vendor/SMORE/src');sys.path.insert(0,_vendor)
_saved={name:sys.modules.pop(name) for name in ('models','common') if name in sys.modules}
try:
    from models.smore import SMORE as UpstreamSMORE
finally:
    # Keep already-imported project modules authoritative for the experiment.
    for name in ('models','common'):sys.modules.pop(name,None)
    sys.modules.update(_saved)

class DatasetAdapter:
    def __init__(self,d):
        self.d=d
        # Upstream GeneralRecommender expects a dataloader.dataset object,
        # while SMORE itself calls inter_matrix on the same argument.
        self.dataset=self
    def get_user_num(self):return len(self.d.train_uids)
    def get_item_num(self):return self.d.nitems
    def inter_matrix(self,form='coo'):
        assert form=='coo'
        return sp.coo_matrix((np.ones(len(self.d.train),dtype=np.float32),(self.d.train.local_uid,self.d.train.iid)),shape=(self.get_user_num(),self.get_item_num()))

class ScalableSMORE(UpstreamSMORE):
    def calculate_loss(self,interaction):
        users,pos,neg=interaction
        ue,ie,side,content=self.forward(self.norm_adj,train=True)
        mf,emb,reg=self.bpr_loss(ue[users],ie[pos],ie[neg])
        # Official InfoNCE is quadratic in batch size. Full interaction BPR is
        # retained; a deterministic shuffled in-batch cap bounds CL memory.
        cap=min(1024,len(users));u=users[:cap];p=pos[:cap]
        su,si=torch.split(side,[self.n_users,self.n_items]);cu,ci=torch.split(content,[self.n_users,self.n_items])
        cl=self.InfoNCE(si[p],ci[p],.2)+self.InfoNCE(su[u],cu[u],.2)
        return mf+emb+reg+self.cl_loss*cl

def make_smore(d,c):
    folder=DATA/'smore';assert (folder/'image_feat.npy').exists() and (folder/'text_feat.npy').exists()
    config={'USER_ID_FIELD':'user','ITEM_ID_FIELD':'item','NEG_PREFIX':'neg_','train_batch_size':c['smore_batch_size'],'device':'cuda' if torch.cuda.is_available() else 'cpu',
      'data_path':str(DATA)+'/', 'dataset':'smore','end2end':False,'is_multimodal_model':True,'vision_feature_file':'image_feat.npy','text_feature_file':'text_feat.npy',
      'cl_loss':.01,'n_ui_layers':3,'embedding_size':c['dim'],'n_layers':1,'reg_weight':c['regularization'],'image_knn_k':40,'text_knn_k':10,'dropout_rate':.1}
    return ScalableSMORE(config,DatasetAdapter(d))
