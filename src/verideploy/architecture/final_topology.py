from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class ArchitectureResult:
    passed: bool
    findings: tuple[str, ...]
    node_count: int
    flow_count: int

def load_topology(root: Path) -> dict:
    return json.loads((root / "config/architecture/production-topology.json").read_text())

def validate_topology(root: Path) -> ArchitectureResult:
    cfg = load_topology(root)
    findings: list[str] = []
    nodes = {n["id"]: n for n in cfg["layers"]}
    if len(nodes) != len(cfg["layers"]): findings.append("duplicate architecture node id")
    for f in cfg["flows"]:
        if f["from"] not in nodes: findings.append(f"unknown flow source: {f['from']}")
        if f["to"] not in nodes: findings.append(f"unknown flow target: {f['to']}")
    required = {"client","gateway","kafka","ai","langgraph","openai","mcp","workers","postgres","redis","object","identity","otel","observability","kubernetes"}
    missing = sorted(required - set(nodes))
    if missing: findings.append("missing required nodes: " + ",".join(missing))
    # Public boundary invariant.
    public = {k for k,v in nodes.items() if v.get("public")}
    if public != {"client","gateway"}: findings.append(f"unexpected public nodes: {sorted(public)}")
    if any(f["from"] == "client" and f["to"] == "ai" for f in cfg["flows"]): findings.append("browser bypasses NestJS public boundary")
    # Deployed artifacts must exist.
    for path in ["apps/web","apps/gateway","services/ai","src/verideploy/graphs","src/verideploy/mcp","workers","infrastructure/helm/verideploy","docker-compose.yml"]:
        if not (root/path).exists(): findings.append(f"missing deployed component: {path}")
    return ArchitectureResult(not findings, tuple(findings), len(nodes), len(cfg["flows"]))
