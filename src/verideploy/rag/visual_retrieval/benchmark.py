from __future__ import annotations
import math
from dataclasses import dataclass
@dataclass(frozen=True)
class VisualCase:
    query:str; relevant_page:int

def ndcg_at_k(ranked:list[int],relevant:int,k:int=4)->float:
    dcg=0.0
    for i,p in enumerate(ranked[:k],start=1):
        if p==relevant:dcg=1.0/math.log2(i+1);break
    return dcg # ideal DCG=1 for one relevant page
