#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
PATH=ROOT/'config/supply-chain/base-images.json'

def load(): return json.loads(PATH.read_text())

def resolve()->None:
    data=load(); cache={}
    for item in data['images']:
        image=item['image']
        if image not in cache:
            raw=subprocess.check_output(['docker','buildx','imagetools','inspect',image,'--format','{{json .Manifest.Digest}}'],text=True).strip().strip('"')
            if not raw.startswith('sha256:'): raise SystemExit(f'no immutable digest resolved for {image}')
            cache[image]=raw
        item['digest']=cache[image]; item['release_status']='resolved_in_trusted_builder'
    PATH.write_text(json.dumps(data,indent=2)+'\n')
    for image,digest in sorted(cache.items()): print(f'{image}@{digest}')

def ref_for(dockerfile:str)->None:
    item=next((x for x in load()['images'] if x['dockerfile']==dockerfile),None)
    if not item or not item.get('digest'): raise SystemExit(f'no resolved digest for {dockerfile}')
    print(f"{item['image']}@{item['digest']}")

def main()->int:
    ap=argparse.ArgumentParser(); ap.add_argument('--ref-for-dockerfile'); args=ap.parse_args()
    if args.ref_for_dockerfile: ref_for(args.ref_for_dockerfile)
    else: resolve()
    return 0
if __name__=='__main__': raise SystemExit(main())
