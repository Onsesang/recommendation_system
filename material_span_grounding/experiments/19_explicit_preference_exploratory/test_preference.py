import unittest
import numpy as np
import pandas as pd
from pipeline import validate
from preference_core import history_rows,desired_presence,build_profile,match_profile,blend,target_ranks

CFG={'allowed_scopes':['unknown','whole_garment'],'allowed_conditions':['unknown'],'exclude_categories':['other']}


def annotation(**kwargs):
    return dict(class_id='soft',property_state='present',attitude='like',scope='unknown',condition='unknown',**kwargs)


class PreferenceTests(unittest.TestCase):
    def test_time_split_and_target_exclusion(self):
        rows=pd.DataFrame([dict(user_id='u',official_split=s,timestamp=t,parent_asin=p) for s,t,p in [('train',1,'a'),('validation',2,'b'),('test',3,'c'),('train',4,'d'),('train',2,'c')]])
        self.assertEqual(history_rows(rows,'u','validation',3,'c').parent_asin.tolist(),['a'])
        self.assertEqual(history_rows(rows,'u','test',3,'c').parent_asin.tolist(),['a','b'])

    def test_state_attitude_not_conflated(self):
        a=annotation();self.assertEqual(desired_presence(a,CFG)[0],1)
        a['property_state']='absent';self.assertEqual(desired_presence(a,CFG)[0],0)
        a['attitude']='dislike';self.assertEqual(desired_presence(a,CFG)[0],1)
        a['property_state']='present';self.assertEqual(desired_presence(a,CFG)[0],0)

    def test_abstentions(self):
        for key,value in [('attitude','unknown'),('attitude','mixed'),('property_state','uncertain'),('property_state','not_tactile'),('scope','third_party:husband'),('scope','sleeve'),('condition','summer'),('class_id','unmapped')]:
            a=annotation();a[key]=value;self.assertIsNone(desired_presence(a,CFG)[0])

    def test_review_duplicate_not_extra_weight(self):
        a={**annotation(),'event_id':'e','parent_asin':'a','sample_id':'s1'}
        b={**a,'sample_id':'s2'}
        p=build_profile(pd.DataFrame([a,b]),{'a':'top'},CFG)
        self.assertEqual(p[('top','soft')]['review_count'],1)

    def test_category_local_and_missing_review(self):
        p={('top','soft'):{'desired_presence':1,'review_count':2}}
        prob=np.full((3,14),.9);prob[2]=np.nan
        score,n=match_profile(p,np.array(['top','dress','top']),prob)
        np.testing.assert_allclose(score,[.2,0,0]);np.testing.assert_equal(n,[1,0,0])

    def test_absent_like_rewards_low_same_class_only(self):
        p={('top','soft'):{'desired_presence':0,'review_count':2}}
        prob=np.full((2,14),.5);prob[:,0]=[.1,.9]
        score,_=match_profile(p,np.array(['top','top']),prob)
        self.assertGreater(score[0],score[1])

    def test_zero_alpha_and_no_profile_ranking(self):
        base=np.array([[.2,.8,.5]])
        np.testing.assert_equal(blend(base,np.ones_like(base),0),base)
        np.testing.assert_equal(target_ranks(blend(base,np.zeros_like(base),.5),[1]),target_ranks(base,[1]))

    def test_missing_target_is_not_inserted(self):
        self.assertEqual(target_ranks(np.array([[.2,.8]]),[-1]).tolist(),[3])

    def test_quote_exact_occurrence(self):
        import json
        row={'focal_phrase':'soft','focal_start':15,'context_start':0,'context':'soft but never soft'}
        a={**annotation(),'property_phrase':'soft','evidence_quote':'soft but'}
        self.assertIsNone(validate(json.dumps(a),row)[0])
        a['evidence_quote']='never soft';self.assertIsNotNone(validate(json.dumps(a),row)[0])

    def test_review_item_features_exclude_self_future_and_test(self):
        from types import SimpleNamespace
        from evaluate import review_probabilities
        products=pd.DataFrame({'item_id':['a']})
        rows=[]
        for user,t,split,state,event in [('other',1,'train','present','1'),('u',1,'train','absent','2'),('other',3,'train','absent','3'),('other',1,'test','absent','4')]:
            r={**annotation(),'user_id':user,'timestamp':t,'official_split':split,'parent_asin':'a','event_id':event}
            r['property_state']=state;rows.append(r)
        p=review_probabilities(pd.DataFrame(rows),SimpleNamespace(user_id='u',split='validation',target_timestamp=2),np.array([0]),products,CFG)
        self.assertEqual(p[0,0],1);self.assertTrue(np.isnan(p[0,1:]).all())

    def test_components_synthetic_offline(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        import evaluate as ev
        from pipeline import CLASSES,write,sha
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)
            products=pd.DataFrame([dict(item_id=x,category='top',v3_family_split='train',**{c:.9 for c in CLASSES}) for x in ['a','b','c']])
            cases=pd.DataFrame([dict(user_id='u',target_item='b',target_timestamp=3,split='validation'),dict(user_id='v',target_item='c',target_timestamp=3,split='validation')])
            events=pd.DataFrame([dict(user_id=u,item_id='a',timestamp=1,split='train') for u in ['u','v']])
            evidence=pd.DataFrame([{**annotation(),'user_id':'u','official_split':'train','timestamp':1,'parent_asin':'a','event_id':'e','sample_id':'s'},
                                   {**annotation(),'user_id':'v','official_split':'train','timestamp':4,'parent_asin':'a','event_id':'e2','sample_id':'s2'}])
            write(root/'config.json',{**CFG,'seed':3})
            a={'candidate_indices':np.array([[1,2],[1,2]]),'base_norm':np.array([[1.,0],[1,0]]),'category_norm':np.ones((2,2)),
               'target_positions':np.array([0,1]),'popularity_full_ranks':np.array([1,2])}
            np.savez_compressed(root/'validation_candidates.npz',**a)
            write(root/'evaluation_protocol.json',{'shrinkage_reviews':2.,'candidate_sha256':{'validation':sha(root/'validation_candidates.npz')}})
            with patch.object(ev,'ART',root),patch.object(ev,'load',return_value=(products,cases,events)):
                out,_,_,profiles=ev.components('validation',evidence)
            self.assertTrue(profiles[0]);self.assertFalse(profiles[1])
            self.assertGreater(out['explicit'][0,0],0)
            np.testing.assert_equal(out['explicit'][1],[0,0])


if __name__=='__main__':unittest.main()
