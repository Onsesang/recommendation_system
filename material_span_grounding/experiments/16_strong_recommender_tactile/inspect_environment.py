import importlib.util
import platform
import shutil
import subprocess
import torch
from common import *

def main():
    event('environment','started')
    protected={}
    for name in ('12_class_multilabel_fashionclip_ft','13_category_only_baseline','14_same_category_evaluation','15_human_audit'):
        for p in sorted((PROJECT/'experiments'/name).rglob('*')):
            if p.is_file() and '__pycache__' not in p.parts and not p.name.endswith('.log'):
                protected[str(p.relative_to(PROJECT))]={'bytes':p.stat().st_size,'sha256':sha(p)}
    # Preserve initial manifest rather than blessing later changes.
    if not (ART/'protected_inputs.json').exists(): save_json(ART/'protected_inputs.json',protected)
    ck=torch.load(CHECKPOINT,map_location='cpu',weights_only=False)
    assert sha(CHECKPOINT)==CHECKPOINT_SHA
    assert ck['classes']==CLASSES
    from transformers import AutoProcessor
    proc=AutoProcessor.from_pretrained(str(CLIP),local_files_only=True)
    report={'status':'inspected','platform':platform.platform(),'gpu':subprocess.check_output(['nvidia-smi'],text=True),
            'ram':subprocess.check_output(['free','-b'],text=True),'disk':dict(zip(('total','used','free'),shutil.disk_usage(ROOT))),
            'torch':torch.__version__,'cuda_build':torch.version.cuda,'cuda_available':torch.cuda.is_available(),
            'packages':{m:bool(importlib.util.find_spec(m)) for m in ('recbole','faiss','streamlit','datasets','transformers','mmrec')},
            'checkpoint':str(CHECKPOINT),'checkpoint_sha256':sha(CHECKPOINT),'checkpoint_keys':list(ck),'classes':CLASSES,
            'preprocessing':proc.image_processor.to_dict(),'fashionclip_snapshot':str(CLIP),'protected_file_count':len(protected),
            'raw_reviews':str(WORKSPACE/'yoojeong/amazon_reviews_all/review_Amazon_Fashion'),
            'local_image_metadata':str(WORKSPACE/'texture_project/data/product_images.json'),
            'official_split_config':str(PROJECT/'experiments/16_recommendation_reranking/configs/recommendation_config.json'),
            'v3_targets':str(PROJECT/'experiments/12_class_multilabel_fashionclip_ft/artifacts/product_class_targets.npz'),
            'same_category_results':str(PROJECT/'experiments/14_same_category_evaluation/artifacts/same_category_results.json')}
    if torch.cuda.is_available(): report['cuda_smoke_sum']=float(torch.ones(1024,1024,device='cuda').sum().item())
    save_json(ART/'environment_report.json',report)
    event('environment','complete',cuda=report['cuda_available'],protected_files=len(protected))

if __name__=='__main__': main()
