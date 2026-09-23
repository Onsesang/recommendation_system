import fcntl
import os
import re
import tempfile
from pathlib import Path

import pandas as pd

from pilot import ART, ROOT, FIELDS, CLASSES, STATES, ATTITUDES


def validate_human(row, sample):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,40}',row.get('annotator_id','')):
        raise ValueError('Annotator ID: use 1–40 English letters, digits, _ or -')
    if row.get('sample_id')!=sample['sample_id']: raise ValueError('Unknown sample ID')
    if any(not str(row.get(k,'')).strip() for k in FIELDS): raise ValueError('Complete all fields; use unknown when appropriate')
    if row['class_id'] not in CLASSES or row['property_state'] not in STATES or row['attitude'] not in ATTITUDES: raise ValueError('Invalid category')
    if row['evidence_quote'] not in sample['context']: raise ValueError('Evidence must be copied exactly from context')
    if sample['focal_phrase'].casefold() not in row['evidence_quote'].casefold(): raise ValueError('Evidence must include focal phrase')


def save_human(row,sample,directory=None):
    validate_human(row,sample)
    directory=Path(directory or ROOT/'annotations');directory.mkdir(parents=True,exist_ok=True)
    path=directory/f"{row['annotator_id']}.csv"
    with (directory/f"{row['annotator_id']}.lock").open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        frame=pd.read_csv(path,keep_default_na=False) if path.exists() else pd.DataFrame()
        if len(frame): frame=frame[frame.sample_id!=row['sample_id']]
        frame=pd.concat([frame,pd.DataFrame([{**row,'split_role':sample['split_role']}])],ignore_index=True)
        fd,temp=tempfile.mkstemp(dir=directory,prefix='.save-');os.close(fd)
        try:
            frame.to_csv(temp,index=False);os.replace(temp,path)
        finally:
            if os.path.exists(temp):os.unlink(temp)

