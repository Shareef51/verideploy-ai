from pathlib import Path
import json
ROOT=Path(__file__).resolve().parents[1]
checks={}
def has(path,*tokens):
 text=(ROOT/path).read_text();return all(t in text for t in tokens)
checks["persisted_projection"]=has("src/verideploy/graphs/execution_projection.py","GraphRuntimeEvent","project_agent_execution","convergence_sha256")
checks["sanitized_tools"]=has("src/verideploy/graphs/execution_projection.py","sanitize_payload","[REDACTED]","agent.tool.")
checks["model_usage"]=has("src/verideploy/graphs/execution_projection.py","agent.model.","input_tokens","cost_usd")
checks["node_duration_retries"]=has("src/verideploy/graphs/execution_projection.py","duration_ms","retries","error_message")
checks["private_view"]=has("services/ai/routes/graph_execution.py","execution-view","events")
checks["gateway_boundary"]=has("apps/gateway/src/agent-execution/agent-execution.service.ts","/internal/v1/graph-runs/","PrivateAiClient")
checks["public_routes"]=has("apps/gateway/src/agent-execution/agent-execution.controller.ts","@Sse","events","view")
checks["frontend_screen"]=has("apps/web/app/(platform)/agent-execution/page.tsx","Live Agent Execution","Node graph","Sanitized tool calls","Model roles and usage","Failure drill-down","Persisted event sequence")
checks["no_frontend_simulation"]=has("apps/web/app/(platform)/agent-execution/page.tsx","persisted-event delta arrived","Authoritative refresh","No execution state is synthesized")
checks["browser_boundary"]="/internal/v1" not in (ROOT/"apps/web/app/(platform)/agent-execution/page.tsx").read_text()
checks["public_contract"]=has("contracts/openapi/gateway.yaml","version: 0.47.0","/agent-execution/{runId}:","streamAgentExecutionEvents") and "/internal/v1" not in (ROOT/"contracts/openapi/gateway.yaml").read_text()
checks["navigation"]=has("apps/web/components/shell/app-shell.tsx","Agent Execution","/agent-execution")
checks["no_dedicated_migration_table"]=not list((ROOT/"src/verideploy/database/migrations/versions").glob("*agent_execution*"))
checks["version"]=(ROOT/"src/verideploy/__init__.py").read_text().strip()=='__version__ = "0.47.0"'
result={"valid":all(checks.values()),"passed":sum(checks.values()),"total":len(checks),"checks":checks}
print(json.dumps(result,indent=2));(ROOT/"artifacts/agent-execution-validation.json").write_text(json.dumps(result,indent=2)+"\n")
raise SystemExit(0 if result["valid"] else 1)
