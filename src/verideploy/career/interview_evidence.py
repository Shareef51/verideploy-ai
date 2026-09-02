from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

TOKEN = re.compile(r"\{([a-zA-Z0-9_]+)\}")
NUMERIC_LITERAL = re.compile(r"(?<![A-Za-z_])(?:\$?\d+(?:\.\d+)?%?)(?![A-Za-z_])")
NON_FACTUAL_TECHNICAL_NUMBER = re.compile(r"(?:Recall@\d+|\bp\d+\b)", re.IGNORECASE)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def _get(data: Any, dotted: str) -> Any:
    cur = data
    for part in dotted.split("."):
        if isinstance(cur, list):
            cur = cur[int(part)]
        else:
            cur = cur[part]
    return cur


def _format(value: Any, fmt: str) -> str:
    if fmt == "integer":
        return str(int(value))
    if fmt == "percent_0":
        return f"{float(value) * 100:.0f}%"
    if fmt == "percent_1":
        return f"{float(value) * 100:.1f}%"
    if fmt == "percent_2":
        return f"{float(value):.2f}%"
    if fmt == "decimal_2":
        return f"{float(value):.2f}"
    if fmt == "usd_3":
        return f"${float(value):.3f}"
    if fmt == "ms_5":
        return f"{float(value):.5f} ms"
    raise ValueError(f"unknown format: {fmt}")


def load_config(root: Path) -> dict[str, Any]:
    return _load_json(root / "config/career/resume-interview.json")


def resolve_metrics(root: Path) -> dict[str, dict[str, Any]]:
    cfg = load_config(root)
    resolved: dict[str, dict[str, Any]] = {}
    for item in cfg["metrics"]:
        source = root / item["source"]
        data = _load_json(source)
        value = _get(data, item["path"])
        resolved[item["id"]] = {
            **item,
            "value": value,
            "rendered": _format(value, item["format"]),
        }
    return resolved


def render_template(template: str, metric_ids: list[str], metrics: dict[str, dict[str, Any]]) -> str:
    declared = set(metric_ids)
    tokens = set(TOKEN.findall(template))
    if tokens != declared:
        raise ValueError(f"template metrics mismatch: tokens={sorted(tokens)} declared={sorted(declared)}")
    rendered = template
    for metric_id in metric_ids:
        rendered = rendered.replace("{" + metric_id + "}", metrics[metric_id]["rendered"])
    return rendered


def validate(root: Path) -> list[str]:
    cfg = load_config(root)
    findings: list[str] = []
    metric_items = cfg.get("metrics", [])
    metric_ids = [m.get("id") for m in metric_items]
    if len(set(metric_ids)) != len(metric_ids):
        findings.append("duplicate metric identifiers")
    try:
        metrics = resolve_metrics(root)
    except Exception as exc:  # fail closed: source/path/format errors are release blockers
        return [f"metric resolution failed: {exc}"]

    for item in metric_items:
        for key in ("source", "path", "format", "qualifier"):
            if not str(item.get(key, "")).strip():
                findings.append(f"{item.get('id')}: missing {key}")
        source = root / item["source"]
        if not source.exists() or source.stat().st_size == 0:
            findings.append(f"{item['id']}: missing metric source {item['source']}")

    sections = [
        ("resume_bullets", "template"),
        ("star_stories", "result_template"),
        ("cost_latency_decisions", "statement_template"),
    ]
    for section, template_key in sections:
        for entry in cfg.get(section, []):
            template = entry.get(template_key, "")
            declared = entry.get("metrics", [])
            try:
                render_template(template, declared, metrics)
            except Exception as exc:
                findings.append(f"{section}/{entry.get('id','unknown')}: {exc}")
            # Numeric facts must arrive through metric placeholders, never be typed directly in templates.
            stripped = TOKEN.sub("{metric}", template)
            stripped = NON_FACTUAL_TECHNICAL_NUMBER.sub("{technical_label}", stripped)
            if NUMERIC_LITERAL.search(stripped):
                findings.append(f"{section}/{entry.get('id','unknown')}: raw numeric literal in template")
            for rel in entry.get("evidence", []):
                p = root / rel
                if not p.exists() or (p.is_file() and p.stat().st_size == 0):
                    findings.append(f"{section}/{entry.get('id','unknown')}: missing evidence {rel}")

    for section in ("tradeoffs", "failure_lessons"):
        for idx, entry in enumerate(cfg.get(section, [])):
            if not entry.get("evidence"):
                findings.append(f"{section}/{idx}: missing evidence")
            for rel in entry.get("evidence", []):
                p = root / rel
                if not p.exists() or (p.is_file() and p.stat().st_size == 0):
                    findings.append(f"{section}/{idx}: missing evidence {rel}")

    if len(cfg.get("resume_bullets", [])) < 5:
        findings.append("insufficient resume bullets")
    if len(cfg.get("star_stories", [])) < 4:
        findings.append("insufficient STAR stories")
    if len(cfg.get("recruiter_questions", [])) < 10:
        findings.append("insufficient recruiter questions")
    return findings


def build_report(root: Path) -> dict[str, Any]:
    cfg = load_config(root)
    metrics = resolve_metrics(root)
    findings = validate(root)
    bullets = [
        {"id": b["id"], "text": render_template(b["template"], b["metrics"], metrics), "evidence": b["evidence"]}
        for b in cfg["resume_bullets"]
    ]
    stories = []
    for s in cfg["star_stories"]:
        stories.append({
            "id": s["id"],
            "title": s["title"],
            "situation": s["situation"],
            "task": s["task"],
            "action": s["action"],
            "result": render_template(s["result_template"], s["metrics"], metrics),
            "evidence": s["evidence"],
        })
    costs = [
        {"id": c["id"], "statement": render_template(c["statement_template"], c["metrics"], metrics), "evidence": c["evidence"]}
        for c in cfg["cost_latency_decisions"]
    ]
    return {
        "release": cfg["release"],
        "gate": "pass" if not findings else "fail",
        "measured_metrics": len(metrics),
        "resume_bullets": bullets,
        "star_stories": stories,
        "tradeoffs": cfg["tradeoffs"],
        "cost_latency_decisions": costs,
        "failure_lessons": cfg["failure_lessons"],
        "recruiter_questions": cfg["recruiter_questions"],
        "findings": findings,
    }


def write_markdown(root: Path, report: dict[str, Any]) -> Path:
    lines = [
        "# VeriDeploy AI — Resume Impact and Interview Evidence",
        "",
        "All numeric claims below are rendered from measured repository evidence. Qualifiers are preserved for synthetic, estimated, CI-only, or in-process measurements.",
        "",
        "## Resume-ready bullets",
        "",
    ]
    for bullet in report["resume_bullets"]:
        lines.append(f"- {bullet['text']}")
    lines += ["", "## STAR stories", ""]
    for story in report["star_stories"]:
        lines += [
            f"### {story['title']}",
            f"- **Situation:** {story['situation']}",
            f"- **Task:** {story['task']}",
            f"- **Action:** {story['action']}",
            f"- **Result:** {story['result']}",
            "",
        ]
    lines += ["## Trade-offs", ""]
    for item in report["tradeoffs"]:
        lines += [f"### {item['decision']}", item["tradeoff"], ""]
    lines += ["## Cost and latency decisions", ""]
    for item in report["cost_latency_decisions"]:
        lines.append(f"- {item['statement']}")
    lines += ["", "## Failure lessons", ""]
    for item in report["failure_lessons"]:
        lines.append(f"- {item['lesson']}")
    lines += ["", "## Likely recruiter / interviewer questions", ""]
    for q in report["recruiter_questions"]:
        lines.append(f"- {q}")
    path = root / "docs/career/resume-impact-and-interview-evidence.md"
    path.write_text("\n".join(lines) + "\n")
    return path
