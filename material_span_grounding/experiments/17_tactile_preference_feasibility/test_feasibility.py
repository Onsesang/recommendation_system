import json
import unittest
from pathlib import Path

import pandas as pd

OUT=Path(__file__).resolve().parent/'artifacts'


class FeasibilityTests(unittest.TestCase):
    def test_raw_official_coverage(self):
        r=json.loads((OUT/'feasibility_results.json').read_text())
        self.assertEqual(r['raw_reviews'],2500939)
        self.assertEqual(r['official_events'],r['raw_to_official_unique_events_matched'])

    def test_unique_mapping_and_cohort_time(self):
        lex=pd.read_parquet(OUT/'lexical_reviews.parquet')
        self.assertTrue(lex.event_id.is_unique)
        cohort=pd.read_parquet(OUT/'cohort_events.parquet')
        self.assertFalse(cohort.duplicated(['user_id','official_split']).any())
        self.assertTrue((cohort.latest_history_timestamp<cohort.timestamp).all())
        self.assertTrue((cohort.eligible_history_count>=1).all())
        self.assertTrue((cohort.past_lexical_reviews_all_items>=cohort.past_lexical_reviews_eligible_items).all())


if __name__=='__main__':unittest.main()
