import hashlib
import json
from pathlib import Path

from pilot import ROOT,PROJECT,ART


def digest(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for block in iter(lambda:f.read(1048576),b''):h.update(block)
    return h.hexdigest()


def main():
    exp17=PROJECT/'experiments/17_tactile_preference_feasibility'
    feasibility=json.loads((exp17/'artifacts/feasibility_results.json').read_text())
    previous=json.loads((PROJECT/'experiments/16_recommendation_reranking/artifacts/tactile_profile_manifest.json').read_text())
    raw_checks={path:digest(path)==expected for path,expected in feasibility['source_hashes'].items()}
    last2=digest(previous['checkpoint'])==previous['checkpoint_sha256_before']
    pilot=json.loads((ART/'pilot_results.json').read_text())
    verification={'raw_arrow_hashes_unchanged':raw_checks,'last2_matches_experiment16_hash':last2,
                  'official_raw_linkage_complete':feasibility['official_events']==feasibility['raw_to_official_unique_events_matched'],
                  'model_attempts_complete':pilot['model_records']==pilot['samples'],
                  'human_validation':'pending','human_accuracy_measured':False,
                  'old_experiments_write_policy':'Only read operations on experiments 12–16; no complete pre/post tree hash claim.',
                  'source_and_output_hashes':{str(path.relative_to(PROJECT)):digest(path) for folder in [exp17,ROOT] for path in folder.rglob('*') if path.is_file() and '__pycache__' not in str(path) and path.name!='verification.json' and 'annotations' not in path.parts}}
    assert all(raw_checks.values()) and last2 and verification['official_raw_linkage_complete'] and verification['model_attempts_complete']
    (ART/'verification.json').write_text(json.dumps(verification,indent=2))
    print('Raw data unchanged; Last2 unchanged; official linkage complete; pilot attempts complete; human validation pending.')


if __name__=='__main__':main()
