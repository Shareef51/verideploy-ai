#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path
from verideploy.rag.checkpoint import run_rag_checkpoint
ROOT=Path(__file__).resolve().parents[1]
result=run_rag_checkpoint()
report={"gate":"pass" if result.passed else "fail","clean_index_fingerprint":result.clean_index_fingerprint,"metrics":result.metrics,"latency_ms":result.latency_ms,"cache":result.cache,"failures":list(result.failures)}
out=ROOT/'evals/reports/rag-performance.json'; out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
print(json.dumps(report,sort_keys=True))
raise SystemExit(0 if result.passed else 1)
