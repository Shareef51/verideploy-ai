from __future__ import annotations
from copy import deepcopy
from dataclasses import dataclass
from typing import Generic, TypeVar
from .schemas import EffectiveRetrievalScope
import json
from pydantic import BaseModel
T=TypeVar("T")
@dataclass
class ScopedRetrievalCache(Generic[T]):
    def __post_init__(self): self._data:dict[tuple[str,str],T]={}
    def get(self,key:str,scope:EffectiveRetrievalScope)->T|None:
        value=self._data.get((key,scope.fingerprint())); return deepcopy(value) if value is not None else None
    def put(self,key:str,scope:EffectiveRetrievalScope,value:T)->None:
        self._data[(key,scope.fingerprint())]=deepcopy(value)
    def size(self)->int:return len(self._data)


class RedisScopedRetrievalCache(Generic[T]):
    """Replica-safe retrieval cache; tenant generations provide bounded invalidation."""
    def __init__(self, redis_url: str, *, value_model: type[BaseModel], ttl_seconds: int, embedding_model_version: str, index_version: str, corpus_version: str, pipeline_version: str):
        from redis.asyncio import Redis
        self.redis=Redis.from_url(redis_url,decode_responses=True); self.value_model=value_model; self.ttl_seconds=ttl_seconds
        self.versions=(embedding_model_version,index_version,corpus_version,pipeline_version)
    async def _generation(self,tenant_id)->str:
        return await self.redis.get(f"rag:generation:{tenant_id}") or "0"
    async def _key(self,key:str,scope:EffectiveRetrievalScope)->str:
        generation=await self._generation(scope.tenant_id)
        payload="|".join((str(scope.tenant_id),scope.fingerprint(),key,*self.versions,generation))
        import hashlib
        return "rag:result:"+hashlib.sha256(payload.encode()).hexdigest()
    async def get(self,key:str,scope:EffectiveRetrievalScope):
        value=await self.redis.get(await self._key(key,scope))
        return self.value_model.model_validate_json(value) if value else None
    async def put(self,key:str,scope:EffectiveRetrievalScope,value:T)->None:
        serialized=value.model_dump_json() if isinstance(value,BaseModel) else json.dumps(value)
        await self.redis.set(await self._key(key,scope),serialized,ex=self.ttl_seconds)
    async def invalidate_tenant(self,tenant_id)->None:
        await self.redis.incr(f"rag:generation:{tenant_id}")
