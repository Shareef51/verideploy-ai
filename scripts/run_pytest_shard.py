#!/usr/bin/env python3
from __future__ import annotations
import argparse,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/"src"))
from verideploy.testing.strategy import shard_for
def main():
 p=argparse.ArgumentParser(); p.add_argument("--shard",type=int,required=True); p.add_argument("--shards",type=int,default=4); a=p.parse_args()
 proc=subprocess.run([sys.executable,"-m","pytest","--collect-only","-q"],cwd=ROOT,text=True,capture_output=True)
 if proc.returncode: print(proc.stdout); print(proc.stderr,file=sys.stderr); return proc.returncode
 nodes=[x.strip() for x in proc.stdout.splitlines() if "::" in x and not x.startswith("<")]; selected=[n for n in nodes if shard_for(n,a.shards)==a.shard]
 print(f" shard {a.shard}/{a.shards}: {len(selected)} tests")
 if not selected: return 0
 return subprocess.call([sys.executable,"-m","pytest","-q",*selected],cwd=ROOT)
if __name__=="__main__": raise SystemExit(main())
