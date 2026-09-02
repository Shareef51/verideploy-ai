# ADR-0022 — Retrieval authorization is monotonic intersection

Status: Accepted.

Retrieval authorization must never be supplied or enlarged by an LLM. Trusted headers/internal context define the maximum tenant/service/environment/team/type/permission scope. User or model metadata filters can only narrow that scope. Empty requested filters preserve trusted constraints; conflicting constraints return an explicit empty scope. Cache entries are partitioned by the effective-scope fingerprint. Database queries still enforce tenant RLS and per-document required permissions.

This avoids post-retrieval filtering as the primary control because ranking, cache population, visual scoring, and previews would otherwise observe unauthorized candidates.
