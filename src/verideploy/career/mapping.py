from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REQUIRED_SKILLS = {"python","typescript","openai","rag","agents","langgraph","mcp","multimodal","apis","realtime","evaluation","llmops","security","cloud_native"}

def load_mapping(root: Path) -> dict[str, Any]:
    return json.loads((root / "config/career/jd-mapping.json").read_text())

def validate_mapping(root: Path) -> list[str]:
    data = load_mapping(root)
    findings: list[str] = []
    claims = data.get("claims", [])
    ids = {c.get("skill_id") for c in claims}
    missing = REQUIRED_SKILLS - ids
    if missing:
        findings.append("missing required skills: " + ", ".join(sorted(missing)))
    for claim in claims:
        sid = claim.get("skill_id", "unknown")
        evidence = claim.get("evidence", {})
        code = evidence.get("code", [])
        verification = evidence.get("tests", []) + evidence.get("reports", []) + evidence.get("traces", [])
        if not code:
            findings.append(f"{sid}: missing code evidence")
        if not verification:
            findings.append(f"{sid}: missing verification evidence")
        for kind, paths in evidence.items():
            for rel in paths:
                p = root / rel
                if not p.exists():
                    findings.append(f"{sid}: missing {kind} evidence {rel}")
                elif p.is_file() and p.stat().st_size == 0:
                    findings.append(f"{sid}: empty {kind} evidence {rel}")
        if "claim" not in claim or not str(claim["claim"]).strip():
            findings.append(f"{sid}: empty claim")
    if len(ids) != len(claims):
        findings.append("duplicate skill identifiers")
    return findings

def build_report(root: Path) -> dict[str, Any]:
    data = load_mapping(root)
    findings = validate_mapping(root)
    claims = data["claims"]
    return {
        "release": data["release"],
        "gate": "pass" if not findings else "fail",
        "skill_claims": len(claims),
        "skills_with_code_evidence": sum(bool(c["evidence"].get("code")) for c in claims),
        "skills_with_verification_evidence": sum(bool(c["evidence"].get("tests") or c["evidence"].get("reports") or c["evidence"].get("traces")) for c in claims),
        "findings": findings,
    }
