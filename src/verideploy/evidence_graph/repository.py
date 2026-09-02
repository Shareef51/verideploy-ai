from __future__ import annotations

import copy
from abc import ABC, abstractmethod
from collections import deque
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text

from verideploy.database.session import DatabaseManager
from verideploy.evidence_graph.schemas import GraphEdge, GraphEntity, GraphRelationship


class GraphNotFoundError(LookupError): pass
class GraphConflictError(RuntimeError): pass
class GraphTenantViolation(PermissionError): pass


class EvidenceGraphRepository(ABC):
    @abstractmethod
    def upsert_entity(self, entity: GraphEntity) -> GraphEntity: ...
    @abstractmethod
    def upsert_edge(self, edge: GraphEdge) -> GraphEdge: ...
    @abstractmethod
    def get_entity(self, *, tenant_id: UUID, entity_id: UUID) -> GraphEntity | None: ...
    @abstractmethod
    def list_entities(self, *, tenant_id: UUID) -> tuple[GraphEntity, ...]: ...
    @abstractmethod
    def list_edges(self, *, tenant_id: UUID) -> tuple[GraphEdge, ...]: ...
    @abstractmethod
    def neighbors(self, *, tenant_id: UUID, entity_id: UUID) -> tuple[tuple[GraphEdge, GraphEntity], ...]: ...
    @abstractmethod
    def shortest_path(self, *, tenant_id: UUID, source_entity_id: UUID, target_entity_id: UUID, max_depth: int) -> tuple[tuple[GraphEntity, ...], tuple[GraphEdge, ...]] | None: ...


class InMemoryEvidenceGraphRepository(EvidenceGraphRepository):
    def __init__(self) -> None:
        self._entities: dict[UUID, GraphEntity] = {}
        self._edges: dict[UUID, GraphEdge] = {}

    def upsert_entity(self, entity: GraphEntity) -> GraphEntity:
        existing = self._entities.get(entity.entity_id)
        if existing and (existing.tenant_id != entity.tenant_id or existing.entity_type != entity.entity_type or existing.natural_key != entity.natural_key):
            raise GraphConflictError("stable entity identity conflicts with existing entity")
        self._entities[entity.entity_id] = copy.deepcopy(entity)
        return copy.deepcopy(entity)

    def upsert_edge(self, edge: GraphEdge) -> GraphEdge:
        source = self._entities.get(edge.source_entity_id); target = self._entities.get(edge.target_entity_id)
        if source is None or target is None or source.tenant_id != edge.tenant_id or target.tenant_id != edge.tenant_id:
            raise GraphNotFoundError("graph edge endpoints not found in tenant scope")
        self._edges[edge.edge_id] = copy.deepcopy(edge)
        return copy.deepcopy(edge)

    def get_entity(self, *, tenant_id: UUID, entity_id: UUID) -> GraphEntity | None:
        row = self._entities.get(entity_id)
        return copy.deepcopy(row) if row and row.tenant_id == tenant_id else None

    def list_entities(self, *, tenant_id: UUID) -> tuple[GraphEntity, ...]:
        return tuple(copy.deepcopy(x) for x in sorted((e for e in self._entities.values() if e.tenant_id == tenant_id), key=lambda e: (e.entity_type.value, e.natural_key)))

    def list_edges(self, *, tenant_id: UUID) -> tuple[GraphEdge, ...]:
        return tuple(copy.deepcopy(x) for x in sorted((e for e in self._edges.values() if e.tenant_id == tenant_id), key=lambda e: (str(e.source_entity_id), e.relationship.value, str(e.target_entity_id))))

    def neighbors(self, *, tenant_id: UUID, entity_id: UUID) -> tuple[tuple[GraphEdge, GraphEntity], ...]:
        if self.get_entity(tenant_id=tenant_id, entity_id=entity_id) is None:
            raise GraphNotFoundError("graph entity not found")
        rows=[]
        for edge in self._edges.values():
            if edge.tenant_id != tenant_id: continue
            other = edge.target_entity_id if edge.source_entity_id == entity_id else edge.source_entity_id if edge.target_entity_id == entity_id else None
            if other is not None:
                entity=self.get_entity(tenant_id=tenant_id,entity_id=other)
                if entity: rows.append((copy.deepcopy(edge),entity))
        return tuple(sorted(rows,key=lambda x:(x[0].relationship.value,str(x[1].entity_id))))

    def shortest_path(self, *, tenant_id: UUID, source_entity_id: UUID, target_entity_id: UUID, max_depth: int) -> tuple[tuple[GraphEntity,...],tuple[GraphEdge,...]]|None:
        if self.get_entity(tenant_id=tenant_id, entity_id=source_entity_id) is None or self.get_entity(tenant_id=tenant_id, entity_id=target_entity_id) is None:
            return None
        outgoing: dict[UUID,list[GraphEdge]]={}
        for edge in self._edges.values():
            if edge.tenant_id==tenant_id: outgoing.setdefault(edge.source_entity_id,[]).append(edge)
        q=deque([(source_entity_id,[source_entity_id],[])])
        visited={(source_entity_id,0)}
        while q:
            current,nodes,edges=q.popleft()
            if current==target_entity_id:
                return tuple(self._entities[n] for n in nodes),tuple(edges)
            if len(edges)>=max_depth: continue
            for edge in sorted(outgoing.get(current,[]),key=lambda e:(e.relationship.value,str(e.target_entity_id))):
                state=(edge.target_entity_id,len(edges)+1)
                if state in visited: continue
                visited.add(state); q.append((edge.target_entity_id,nodes+[edge.target_entity_id],edges+[edge]))
        return None


class PostgresEvidenceGraphRepository(EvidenceGraphRepository):
    def __init__(self, db: DatabaseManager) -> None: self.db=db

    @staticmethod
    def _entity(row: dict[str,Any]) -> GraphEntity:
        return GraphEntity(entity_id=row["entity_id"],tenant_id=row["tenant_id"],entity_type=row["entity_type"],natural_key=row["natural_key"],label=row["label"],reference_uri=row["reference_uri"],evidence_record_id=row["evidence_record_id"],attributes=row["attributes"],observed_at=row["observed_at"],created_at=row["created_at"])
    @staticmethod
    def _edge(row: dict[str,Any]) -> GraphEdge:
        return GraphEdge(edge_id=row["edge_id"],tenant_id=row["tenant_id"],source_entity_id=row["source_entity_id"],target_entity_id=row["target_entity_id"],relationship=row["relationship"],confidence=float(row["confidence"]),occurred_at=row["occurred_at"],valid_from=row["valid_from"],valid_to=row["valid_to"],attributes=row["attributes"],created_at=row["created_at"])

    def upsert_entity(self, entity: GraphEntity) -> GraphEntity:
        with self.db.tenant_session(entity.tenant_id) as s:
            row=s.execute(text("""
                INSERT INTO graph_entities(entity_id,tenant_id,entity_type,natural_key,label,reference_uri,evidence_record_id,attributes,observed_at,created_at)
                VALUES(:entity_id,:tenant_id,:entity_type,:natural_key,:label,:reference_uri,:evidence_record_id,CAST(:attributes AS jsonb),:observed_at,:created_at)
                ON CONFLICT (tenant_id,entity_type,natural_key) DO UPDATE SET label=EXCLUDED.label, reference_uri=EXCLUDED.reference_uri,
                    evidence_record_id=EXCLUDED.evidence_record_id, attributes=EXCLUDED.attributes, observed_at=EXCLUDED.observed_at
                RETURNING *
            """),{**entity.model_dump(),"entity_type":entity.entity_type.value,"attributes":__import__('json').dumps(entity.attributes)}).mappings().one(); s.commit(); return self._entity(dict(row))

    def upsert_edge(self, edge: GraphEdge) -> GraphEdge:
        with self.db.tenant_session(edge.tenant_id) as s:
            row=s.execute(text("""
                INSERT INTO graph_edges(edge_id,tenant_id,source_entity_id,target_entity_id,relationship,confidence,occurred_at,valid_from,valid_to,attributes,created_at)
                VALUES(:edge_id,:tenant_id,:source_entity_id,:target_entity_id,:relationship,:confidence,:occurred_at,:valid_from,:valid_to,CAST(:attributes AS jsonb),:created_at)
                ON CONFLICT (edge_id) DO NOTHING RETURNING *
            """),{**edge.model_dump(),"relationship":edge.relationship.value,"attributes":__import__('json').dumps(edge.attributes)}).mappings().first()
            if row is None: row=s.execute(text("SELECT * FROM graph_edges WHERE tenant_id=:tenant AND edge_id=:edge"),{"tenant":str(edge.tenant_id),"edge":str(edge.edge_id)}).mappings().one()
            s.commit(); return self._edge(dict(row))

    def get_entity(self, *, tenant_id: UUID, entity_id: UUID) -> GraphEntity | None:
        with self.db.tenant_session(tenant_id) as s:
            row=s.execute(text("SELECT * FROM graph_entities WHERE tenant_id=:tenant AND entity_id=:id"),{"tenant":str(tenant_id),"id":str(entity_id)}).mappings().first(); return self._entity(dict(row)) if row else None
    def list_entities(self, *, tenant_id: UUID) -> tuple[GraphEntity,...]:
        with self.db.tenant_session(tenant_id) as s:
            rows=s.execute(text("SELECT * FROM graph_entities WHERE tenant_id=:tenant ORDER BY entity_type,natural_key"),{"tenant":str(tenant_id)}).mappings().all(); return tuple(self._entity(dict(r)) for r in rows)
    def list_edges(self, *, tenant_id: UUID) -> tuple[GraphEdge,...]:
        with self.db.tenant_session(tenant_id) as s:
            rows=s.execute(text("SELECT * FROM graph_edges WHERE tenant_id=:tenant ORDER BY source_entity_id,relationship,target_entity_id"),{"tenant":str(tenant_id)}).mappings().all(); return tuple(self._edge(dict(r)) for r in rows)
    def neighbors(self, *, tenant_id: UUID, entity_id: UUID) -> tuple[tuple[GraphEdge,GraphEntity],...]:
        if self.get_entity(tenant_id=tenant_id,entity_id=entity_id) is None: raise GraphNotFoundError("graph entity not found")
        with self.db.tenant_session(tenant_id) as s:
            rows=s.execute(text("""
                SELECT e.*, n.entity_id AS n_entity_id,n.tenant_id AS n_tenant_id,n.entity_type AS n_entity_type,n.natural_key AS n_natural_key,n.label AS n_label,n.reference_uri AS n_reference_uri,n.evidence_record_id AS n_evidence_record_id,n.attributes AS n_attributes,n.observed_at AS n_observed_at,n.created_at AS n_created_at
                FROM graph_edges e JOIN graph_entities n ON n.tenant_id=e.tenant_id AND n.entity_id=CASE WHEN e.source_entity_id=:id THEN e.target_entity_id ELSE e.source_entity_id END
                WHERE e.tenant_id=:tenant AND (e.source_entity_id=:id OR e.target_entity_id=:id)
                ORDER BY e.relationship,n.entity_id
            """),{"tenant":str(tenant_id),"id":str(entity_id)}).mappings().all()
            out=[]
            for r in rows:
                d=dict(r); ed={k:d[k] for k in ("edge_id","tenant_id","source_entity_id","target_entity_id","relationship","confidence","occurred_at","valid_from","valid_to","attributes","created_at")}; nd={"entity_id":d["n_entity_id"],"tenant_id":d["n_tenant_id"],"entity_type":d["n_entity_type"],"natural_key":d["n_natural_key"],"label":d["n_label"],"reference_uri":d["n_reference_uri"],"evidence_record_id":d["n_evidence_record_id"],"attributes":d["n_attributes"],"observed_at":d["n_observed_at"],"created_at":d["n_created_at"]}; out.append((self._edge(ed),self._entity(nd)))
            return tuple(out)

    def shortest_path(self, *, tenant_id: UUID, source_entity_id: UUID, target_entity_id: UUID, max_depth: int) -> tuple[tuple[GraphEntity,...],tuple[GraphEdge,...]]|None:
        with self.db.tenant_session(tenant_id) as s:
            row=s.execute(text("""
                WITH RECURSIVE walk AS (
                  SELECT ARRAY[CAST(:source AS uuid)] AS nodes, ARRAY[]::uuid[] AS edges, CAST(:source AS uuid) AS current, 0 AS depth
                  UNION ALL
                  SELECT w.nodes || e.target_entity_id, w.edges || e.edge_id, e.target_entity_id, w.depth+1
                  FROM walk w JOIN graph_edges e ON e.tenant_id=:tenant AND e.source_entity_id=w.current
                  WHERE w.depth < :max_depth AND NOT e.target_entity_id = ANY(w.nodes)
                )
                SELECT nodes,edges FROM walk WHERE current=CAST(:target AS uuid) ORDER BY depth LIMIT 1
            """),{"tenant":str(tenant_id),"source":str(source_entity_id),"target":str(target_entity_id),"max_depth":max_depth}).mappings().first()
            if not row: return None
            entities=[]; edges=[]
            for eid in row["nodes"]:
                er=s.execute(text("SELECT * FROM graph_entities WHERE tenant_id=:tenant AND entity_id=:id"),{"tenant":str(tenant_id),"id":str(eid)}).mappings().one(); entities.append(self._entity(dict(er)))
            for edge_id in row["edges"]:
                rr=s.execute(text("SELECT * FROM graph_edges WHERE tenant_id=:tenant AND edge_id=:id"),{"tenant":str(tenant_id),"id":str(edge_id)}).mappings().one(); edges.append(self._edge(dict(rr)))
            return tuple(entities),tuple(edges)
