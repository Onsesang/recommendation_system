import unittest
import numpy as np
import torch
from models import BPR,LightGCN,SASRec
from esasrec_adapter import ESASRec
from recommender import metrics,padded
from prepare_metadata import choose_image,inferred_category
from tune_tactile_reranker import average_tie_percentile,category_index_tensor

class Tests(unittest.TestCase):
    def test_metrics(self):
        m=metrics([1,2,11]);self.assertAlmostEqual(m['hr_at_10'],2/3);self.assertAlmostEqual(m['ndcg_at_10'],(1+1/np.log2(3))/3)
    def test_padding(self):
        np.testing.assert_array_equal(padded({3:np.array([4,5,6])},[3,8],2),[[6,7],[0,0]])
    def test_image_main_priority(self):
        self.assertEqual(choose_image([{'variant':'PT01','hi_res':'https://a'},{'variant':'MAIN','large':'https://b'}]),'https://b')
    def test_frozen_category_rule(self):
        self.assertEqual(inferred_category('Warm Wool Cardigan'),'sweater')
        self.assertEqual(inferred_category('Novelty Charm'),'other')
    def test_bpr_descent(self):
        torch.manual_seed(4);m=BPR(4,10,8);u=torch.tensor([0,1]);p=torch.tensor([2,3]);n=torch.tensor([5,6]);o=torch.optim.Adam(m.parameters(),.01)
        before=m.loss(u,p,n).item()
        for _ in range(20):o.zero_grad();loss=m.loss(u,p,n);loss.backward();o.step()
        self.assertLess(m.loss(u,p,n).item(),before)
    def test_graph_normalized(self):
        u=torch.tensor([0,0,1]);p=torch.tensor([0,1,1]);m=LightGCN(2,3,(u,p),8,layers=1)
        a=m.adj.to_dense();self.assertTrue(torch.allclose(a,a.T));self.assertEqual(float(a[4].sum()),0)
        self.assertTrue(torch.isfinite(m.loss(u,p,torch.tensor([2,2,2]))))
    def test_sasrec_causal(self):
        torch.manual_seed(2);m=SASRec(1000,dim=8,layers=2,heads=2,maxlen=5,dropout=0).eval()
        a=torch.tensor([[0,3,4,5,6]]);b=a.clone();b[0,-1]=9
        torch.testing.assert_close(m(a)[:,:-1],m(b)[:,:-1])
        self.assertTrue(torch.isfinite(m(a)).all())
    def test_esasrec_sampled_softmax(self):
        m=ESASRec(50,dim=8,layers=1,heads=2,maxlen=4,dropout=0)
        seq=torch.tensor([[0,1,2,3]]);pos=torch.tensor([[0,2,3,4]])
        neg=torch.tensor([[[0,0],[5,6],[7,8],[9,10]]])
        loss=m.sampled_softmax_loss(seq,pos,neg)
        self.assertTrue(torch.isfinite(loss));loss.backward()
    def test_no_fake_classes(self):
        from common import CLASSES,RELIABLE
        self.assertEqual(len(CLASSES),14);self.assertEqual(len(set(CLASSES)),14);self.assertTrue(set(RELIABLE)<=set(CLASSES))
    def test_category_indices_are_torch_long(self):
        categories=np.array([0,1,2],dtype=np.int16);candidate=np.array([[2,0]],dtype=np.int32)
        index=category_index_tensor(candidate,categories,'cpu')
        self.assertEqual(index.dtype,torch.long)
        values=torch.arange(9).reshape(1,3,3)
        selected=values[torch.arange(1)[:,None],index]
        torch.testing.assert_close(selected,values[:,[2,0]])
    def test_tactile_percentile_averages_ties(self):
        scores=torch.tensor([[.8,.8,.2],[.7,.4,9.],[.3,8.,7.]])
        valid=torch.tensor([[True,True,True],[True,True,False],[True,False,False]])
        got=average_tie_percentile(scores,valid)
        expected=torch.tensor([[.75,.75,0.],[1.,0.,.5],[.5,.5,.5]])
        torch.testing.assert_close(got,expected)

if __name__=='__main__':unittest.main()
