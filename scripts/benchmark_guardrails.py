from __future__ import annotations
import argparse, json
from pathlib import Path
from verideploy.guardrails import GuardrailContext, GuardrailPolicy, GuardrailEngine

def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument("--report", default="evals/reports/guardrails.json"); args=ap.parse_args()
    root=Path(__file__).resolve().parents[1]
    engine=GuardrailEngine(GuardrailPolicy.load(root/"config/guardrails/policy.json"))
    cases=json.loads((root/"evals/fixtures/guardrails/redteam.json").read_text())
    rows=[]; passed=0
    for c in cases:
        ctx=GuardrailContext(tenant_id="tenant-a", actor_id="redteam", role="viewer", correlation_id=c["id"], channel=c["channel"], trace_id=f"trace-{c['id']}", span_id=f"span-{c['id']}")
        if c["layer"]=="input": d=engine.check_input(c["payload"],ctx)
        elif c["layer"]=="retrieval": d=engine.check_retrieval([c["payload"]],ctx)
        elif c["layer"]=="tool": d=engine.check_tool(c["tool"],c["payload"],ctx,risk=c["risk"],approved=c["approved"],dry_run=c["dry_run"])
        elif c["layer"]=="output": d=engine.check_output(c["payload"],ctx,claims=c["claims"])
        else: d=engine.check_operational(c["operation"],ctx,retries=c.get("retries",0))
        ok=d.action.value==c["expect"]; passed+=int(ok)
        rows.append({"id":c["id"],"expected":c["expect"],"actual":d.action.value,"passed":ok,"controls":[v.control_id for v in d.violations]})
    report={"policy_version":engine.policy.version,"policy_sha256":engine.policy.sha256,"cases":len(cases),"passed":passed,"failed":len(cases)-passed,"gate_passed":passed==len(cases),"results":rows,"telemetry":engine.telemetry.snapshot()}
    out=root/args.report; out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    print(json.dumps({k:report[k] for k in ("cases","passed","failed","gate_passed")},indent=2))
    return 0 if report["gate_passed"] else 1
if __name__=="__main__": raise SystemExit(main())
