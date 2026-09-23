import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from pilot import validate,FIELDS,ART
from human_audit import save_human


class PilotTests(unittest.TestCase):
    def test_model_hallucinated_quote_rejected(self):
        import json
        obj=dict(zip(FIELDS,['soft','soft','present','like','unknown','unknown','fabric is very soft']))
        self.assertIsNotNone(validate(json.dumps(obj),{'context':'soft fabric','focal_phrase':'soft'})[1])

    def test_independent_user_holdout_and_original_text(self):
        f=pd.read_parquet(ART/'pilot_samples.parquet')
        self.assertFalse(set(f[f.split_role=='development'].user_id)&set(f[f.split_role=='audit_holdout'].user_id))
        self.assertFalse((f.official_split=='test').any())
        self.assertTrue(f.sample_id.is_unique)
        for r in f.itertuples():
            self.assertEqual(r.text[r.context_start:r.context_end],r.context)
            self.assertEqual(r.text[r.focal_start:r.focal_end],r.focal_phrase)

    def test_save_update_and_traversal_rejected(self):
        sample={'sample_id':'id','context':'soft fabric','focal_phrase':'soft','split_role':'development'}
        row={'sample_id':'id','annotator_id':'r1',**dict(zip(FIELDS,['soft','soft','present','unknown','unknown','unknown','soft fabric']))}
        with tempfile.TemporaryDirectory() as d:
            save_human(row,sample,d);save_human({**row,'attitude':'like'},sample,d)
            result=pd.read_csv(Path(d)/'r1.csv');self.assertEqual(len(result),1);self.assertEqual(result.iloc[0].attitude,'like')
            with self.assertRaises(ValueError):save_human({**row,'annotator_id':'../bad'},sample,d)

    def test_human_analysis_in_isolated_directory(self):
        import json
        import pilot
        sample={'sample_id':'synthetic','context':'soft fabric','focal_phrase':'soft','split_role':'development'}
        annotation=dict(zip(FIELDS,['soft','soft','present','unknown','unknown','unknown','soft fabric']))
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);art=root/'artifacts';art.mkdir()
            pd.DataFrame([sample]).to_parquet(art/'pilot_samples.parquet',index=False)
            (art/'model_annotations.jsonl').write_text(json.dumps({'sample_id':'synthetic','annotation':annotation,'validation_error':None})+'\n')
            for aid in ['a','b']:
                save_human({'sample_id':'synthetic','annotator_id':aid,**annotation},sample,root/'annotations')
            with patch.object(pilot,'ROOT',root),patch.object(pilot,'ART',art):pilot.analyze()
            result=json.loads((art/'pilot_results.json').read_text())
            self.assertEqual(result['human_completed'],2)
            self.assertIsNone(result['human_accuracy'])
            self.assertEqual(len(result['human_inter_annotator_agreement']),3)
            self.assertTrue(all(x['raw_agreement']==1 for x in result['human_inter_annotator_agreement']))


if __name__=='__main__':unittest.main()
