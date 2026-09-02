from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class ReadinessFinding:
    domain: str
    severity: str
    message: str

@dataclass(frozen=True)
class ReadinessReport:
    release: str
    domains_checked: int
    critical_gaps: int
    high_gaps: int
    findings: tuple[ReadinessFinding, ...]

    @property
    def passed(self) -> bool:
        return self.critical_gaps == 0


def review_operational_readiness(root: Path) -> ReadinessReport:
    policy = json.loads((root / "config/operations/readiness.json").read_text())
    findings: list[ReadinessFinding] = []
    for domain, spec in policy["domains"].items():
        for evidence in spec["evidence"]:
            path = root / evidence
            if not path.exists() or (path.is_file() and path.stat().st_size == 0):
                severity = "critical" if spec.get("critical") else "high"
                findings.append(ReadinessFinding(domain, severity, f"missing evidence: {evidence}"))
        if not spec.get("owner"):
            findings.append(ReadinessFinding(domain, "critical", "missing accountable owner"))
    alerts = json.loads((root / "config/operations/alerts.json").read_text())["alerts"]
    alert_ids = {a["id"] for a in alerts}
    required_alerts = {"gateway-slo-burn", "kafka-consumer-lag", "backup-age"}
    for alert in sorted(required_alerts - alert_ids):
        findings.append(ReadinessFinding("slos_alerts", "critical", f"missing alert: {alert}"))
    critical = sum(f.severity == "critical" for f in findings)
    high = sum(f.severity == "high" for f in findings)
    return ReadinessReport(policy["release"], len(policy["domains"]), critical, high, tuple(findings))
