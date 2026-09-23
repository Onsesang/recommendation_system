"""Fetch pinned official metadata, verify content hash, preserve every catalog ID."""
import argparse
import urllib.request
import pandas as pd
from common import *

CATEGORY_RULES=[
 ('dress',('dress','gown')),('top',('shirt','tee','top','blouse','tank')),
 ('sweater',('sweater','cardigan','pullover','hoodie','sweatshirt')),
 ('pants',('pants','legging','jean','trouser','jogger')),('skirt',('skirt',)),
 ('outerwear',('jacket','coat','vest')),('sleepwear',('pajama','sleepwear','robe','nightgown')),
 ('underwear',('bra','underwear','lingerie','sock')),('swimwear',('swim','bikini','tankini')),
 ('accessory',('scarf','hat','cap','beanie','mask','belt'))]

def inferred_category(title):
    text=(title or '').casefold()
    for category,words in CATEGORY_RULES:
        if any(word in text for word in words):return category
    return 'other'

REV='2aa726ef444e72c6a1364c4baa0bcdfb1de55db6'
META_SHA='629dde620a4001934a8af705f6e5514a1b2d349720c26876ee803b90051a62df'
META_SIZE=1422365805
URL=f'https://huggingface.co/datasets/McAuley-Lab/Amazon-Reviews-2023/resolve/{REV}/raw/meta_categories/meta_Amazon_Fashion.jsonl?download=true'

def download():
    dest=DATA/'meta_Amazon_Fashion.jsonl'
    if dest.exists() and sha(dest)==META_SHA: return dest
    part=dest.with_suffix('.jsonl.part')
    for attempt in range(5):
        try:
            offset=part.stat().st_size if part.exists() else 0
            if offset==META_SIZE and sha(part)==META_SHA:
                os.replace(part,dest);return dest
            request=urllib.request.Request(URL,headers={'Range':f'bytes={offset}-','User-Agent':'tactile-research/1.0'})
            with urllib.request.urlopen(request,timeout=60) as response:
                if response.status==206:
                    assert response.headers.get('Content-Range','').startswith(f'bytes {offset}-')
                else: offset=0
                with open(part,'ab' if offset else 'wb') as f:
                    while True:
                        b=response.read(4<<20)
                        if not b: break
                        f.write(b)
            assert part.stat().st_size==META_SIZE
            assert sha(part)==META_SHA
            os.replace(part,dest);return dest
        except Exception as e:
            event('metadata_download','retry',attempt=attempt+1,error_type=type(e).__name__)
            if attempt==4: raise
            time.sleep(min(2**attempt,15))

def choose_image(images):
    if not isinstance(images,list): return None
    ordered=sorted(images,key=lambda x:x.get('variant')!='MAIN')
    for im in ordered:
        for key in ('hi_res','large','url','thumb'):
            url=im.get(key)
            if isinstance(url,str) and url.startswith('https://'):
                return url
    return None

def main():
    event('metadata','started')
    p=download();catalog=pd.read_parquet(DATA/'catalog.parquet'); wanted=set(catalog.parent_asin)
    rows=[]; n=0
    with open(p) as f:
        for line in f:
            x=json.loads(line);n+=1
            if x['parent_asin'] not in wanted: continue
            categories=x.get('categories') or []
            # Official Fashion metadata has an empty category list throughout.
            # Reuse the frozen pre-v3 title heuristic for diagnostics/demo only.
            category=inferred_category(x.get('title'))
            text=' '.join([str(x.get('title') or ''),*map(str,x.get('features') or []),*map(str,x.get('description') or [])])
            rows.append({'parent_asin':x['parent_asin'],'title':x.get('title') or '', 'text':text,
                         'category':category,'image_url':choose_image(x.get('images')),'metadata_available':True})
    m=pd.DataFrame(rows)
    assert not m.parent_asin.duplicated().any()
    c=catalog.merge(m,on='parent_asin',how='left',validate='one_to_one')
    c['metadata_available']=c.metadata_available.fillna(False).astype(bool)
    for col in ('title','text'): c[col]=c[col].fillna('')
    c['category']=c.category.fillna('unknown')
    c.to_parquet(DATA/'item_metadata.parquet',index=False)
    r=load_json(ART/'item_mapping_report.json')
    r.update({'official_metadata_revision':REV,'official_metadata_sha256':META_SHA,'official_metadata_rows':n,
              'catalog_items':len(c),'metadata_available':int(c.metadata_available.sum()),'image_url_available':int(c.image_url.notna().sum()),
              'category_missing':int((c.category=='unknown').sum()),
              'category_rule':'frozen title heuristic from tactile_coldstart.full_pool._category; metadata categories are empty; diagnostic/demo filter only, no oracle target category'})
    save_json(ART/'item_mapping_report.json',r)
    event('metadata','complete',catalog=len(c),metadata=r['metadata_available'],image_urls=r['image_url_available'])

if __name__=='__main__': main()
