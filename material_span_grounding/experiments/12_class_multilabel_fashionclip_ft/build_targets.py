#!/usr/bin/env python3
"""Build reviewer-first positive/unlabeled class targets without changing source data."""
import hashlib, json
from collections import defaultdict
from pathlib import Path
import numpy as np

EXP=Path(__file__).resolve().parent
GROUND=EXP/"artifacts/class_groundings_qwen3vl32b.jsonl"
PRODUCTS=Path("/home/user/onsesang/material_span_grounding/tactile_coldstart_qwen_v2_full/data/product_master_full_pool.json")
CLASSES=["soft","firm","smooth","rough","non_elastic","elastic","thin","thick","flexible","stiff","warm","cool","spongy","crisp"]
OPPOSITE={a:b for a,b in zip(CLASSES[::2],CLASSES[1::2])}|{b:a for a,b in zip(CLASSES[::2],CLASSES[1::2])}

def main():
    products=json.loads(PRODUCTS.read_text()); ids=[str(x["product_id"]) for x in products]; pi={x:i for i,x in enumerate(ids)}; ci={x:i for i,x in enumerate(CLASSES)}
    reviewer=defaultdict(set)
    with GROUND.open() as f:
        for line in f:
            r=json.loads(line)
            if r["status"]!="success" or r["confidence"]<.55 or r["asin"] not in pi: continue
            key=(r["asin"],hashlib.sha256(r["user_id"].encode()).hexdigest()[:16])
            reviewer[key].update(r["classes"])
    votes=defaultdict(list)
    for (pid,_), labels in reviewer.items():
        for label in labels: votes[(pid,label)].append(1.)
        for label in labels:
            other=OPPOSITE[label]
            if other not in labels: votes[(pid,other)].append(0.)
    values=np.zeros((len(ids),len(CLASSES)),np.float32); mask=np.zeros_like(values,np.uint8); support=np.zeros_like(values,np.int16)
    records=[]
    for pid in ids:
        for label in CLASSES:
            xs=votes.get((pid,label),[]); i,j=pi[pid],ci[label]
            if xs: values[i,j]=np.mean(xs); mask[i,j]=1; support[i,j]=len(xs)
            records.append({"product_id":pid,"class_id":label,"target_probability":float(values[i,j]) if xs else None,"mask":int(mask[i,j]),"support_reviewers":len(xs),"source":"review_pseudo" if xs else "review_unobserved"})
    out=EXP/"artifacts"; out.mkdir(exist_ok=True)
    np.savez_compressed(out/"product_class_targets.npz",product_ids=np.array(ids),class_ids=np.array(CLASSES),values=values,mask=mask,support=support)
    with (out/"product_class_targets.jsonl").open("w") as f:
        for r in records: f.write(json.dumps(r)+"\n")
    print(json.dumps({"products":len(ids),"classes":len(CLASSES),"observed_pairs":int(mask.sum()),"reviewers":len(reviewer)}))
if __name__=="__main__": main()
