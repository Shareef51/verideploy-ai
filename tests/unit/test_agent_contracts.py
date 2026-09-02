from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from verideploy.agents.contracts import (
    AgentAuthorization, AgentPlan, AgentRequest, GitHubToolCall, GitHubToolPlan,
    PlanStep, SupervisorDecision, ToolBudget, ToolPermission,
)
from verideploy.agents.github import GitHubAgent
from verideploy.agents.planner import PlanningAgent
from verideploy.agents.prompts import build_prompt_registry
from verideploy.agents.repository import InMemoryAgentRunRepository
from verideploy.agents.supervisor import SupervisorAgent


class FakeModel:
    def __init__(self, outputs): self.outputs=list(outputs); self.calls=[]
    async def generate(self, **kwargs):
        self.calls.append(kwargs); output=self.outputs.pop(0); return kwargs["output_model"].model_validate(output)


class FakeGitHubTools:
    def __init__(self): self.calls=[]
    async def invoke(self, operation, arguments):
        self.calls.append((operation, arguments)); return {"summary": f"read:{operation}:{arguments.get('repo','')}"}


def request():
    tenant=uuid4()
    return AgentRequest(tenant_id=tenant, user_id="user-1", correlation_id="corr-19", objective="Inspect checkout repository release risk", context={"repo":"acme/checkout"})


def auth(req, *permissions):
    return AgentAuthorization(tenant_id=req.tenant_id, user_id=req.user_id, allowed_permissions=frozenset(permissions))


def test_prompt_registry_is_versioned_and_hash_stable():
    a=build_prompt_registry(); b=build_prompt_registry()
    assert a.get("supervisor","1.0.0").sha256 == b.get("supervisor","1.0.0").sha256
    assert len(a.get("github","1.0.0").sha256) == 64


def test_plan_rejects_forward_dependency_and_duplicate_steps():
    with pytest.raises(ValidationError):
        AgentPlan(rationale="x", steps=[PlanStep(step_id="step-01", agent="github", objective="x", depends_on=["step-02"])])
    with pytest.raises(ValidationError):
        AgentPlan(rationale="x", steps=[PlanStep(step_id="step-01", agent="github", objective="x"), PlanStep(step_id="step-01", agent="github", objective="y")])


def test_github_tool_permission_must_match_operation():
    with pytest.raises(ValidationError, match="permission mismatch"):
        GitHubToolCall(call_id="call-01", permission=ToolPermission.GITHUB_COMMIT_READ, operation="repository.get", arguments={})


def test_tool_budget_is_hard_bounded():
    budget=ToolBudget(max_calls=1)
    budget=budget.consume(); assert budget.calls_used == 1 and budget.remaining == 0
    with pytest.raises(RuntimeError, match="exhausted"): budget.consume()


@pytest.mark.asyncio
async def test_supervisor_route_is_schema_valid_authorized_and_persisted():
    req=request(); repo=InMemoryAgentRunRepository(); model=FakeModel([{"route":"github","rationale":"single repository read","confidence":0.93,"required_permissions":["github.repository.read"]}])
    agent=SupervisorAgent(model=model, prompts=build_prompt_registry(), repository=repo)
    out=await agent.run(req, authorization=auth(req, ToolPermission.GITHUB_REPOSITORY_READ))
    assert out.route == "github"
    call=model.calls[0]
    assert (call["prompt_name"], call["prompt_version"], call["schema_version"], call["agent_version"]) == ("supervisor", "1.6.0", "2.0.0", "2.1.0")
    assert len(call["prompt_sha256"]) == 64 and call["model"] == "role:fast" and call["reasoning_setting"] == "low"
    record=next(iter(repo.records.values())); assert record.status.value == "COMPLETED" and record.prompt_sha256 and record.input_sha256


@pytest.mark.asyncio
async def test_supervisor_excludes_bulk_evidence_from_prompt_payload():
    req=request().model_copy(update={"context":{"service":"checkout","raw_logs":"x"*100_000,"fused_evidence":{"secret":"bulk"}}})
    model=FakeModel([{"route":"rag","rationale":"retrieve","confidence":.9,"required_permissions":[]}])
    await SupervisorAgent(model=model,prompts=build_prompt_registry(),repository=InMemoryAgentRunRepository()).run(req,authorization=auth(req))
    assert model.calls[0]["payload"]["context"] == {"service":"checkout"}


@pytest.mark.asyncio
async def test_supervisor_cannot_escalate_permissions():
    req=request(); repo=InMemoryAgentRunRepository(); model=FakeModel([{"route":"github","rationale":"need commit","confidence":0.8,"required_permissions":["github.commit.read"]}])
    agent=SupervisorAgent(model=model, prompts=build_prompt_registry(), repository=repo)
    with pytest.raises(PermissionError): await agent.run(req, authorization=auth(req, ToolPermission.GITHUB_REPOSITORY_READ))
    assert next(iter(repo.records.values())).status.value == "FAILED"


@pytest.mark.asyncio
async def test_planner_enforces_total_tool_budget_and_authorization():
    req=request(); repo=InMemoryAgentRunRepository(); model=FakeModel([{"rationale":"inspect repo and workflow","steps":[{"step_id":"step-01","agent":"github","objective":"repo","required_permissions":["github.repository.read"],"max_tool_calls":2,"depends_on":[]},{"step_id":"step-02","agent":"github","objective":"workflow","required_permissions":["github.workflow.read"],"max_tool_calls":2,"depends_on":["step-01"]}]}])
    agent=PlanningAgent(model=model, prompts=build_prompt_registry(), repository=repo)
    out=await agent.run(req, authorization=auth(req, ToolPermission.GITHUB_REPOSITORY_READ, ToolPermission.GITHUB_WORKFLOW_READ), max_total_tool_calls=4)
    assert [s.step_id for s in out.steps] == ["step-01","step-02"]

    repo2=InMemoryAgentRunRepository(); model2=FakeModel([{"rationale":"too large","steps":[{"step_id":"step-01","agent":"github","objective":"repo","required_permissions":[],"max_tool_calls":5,"depends_on":[]}]}])
    with pytest.raises(RuntimeError, match="exceeds"):
        await PlanningAgent(model=model2,prompts=build_prompt_registry(),repository=repo2).run(req, authorization=auth(req), max_total_tool_calls=4)
    assert next(iter(repo2.records.values())).status.value == "FAILED"


@pytest.mark.asyncio
async def test_github_agent_executes_only_authorized_reads_with_budget():
    req=request(); repo=InMemoryAgentRunRepository(); tools=FakeGitHubTools(); model=FakeModel([{"rationale":"read repository","calls":[{"call_id":"call-01","permission":"github.repository.read","operation":"repository.get","arguments":{"repo":"acme/checkout"}}]}])
    agent=GitHubAgent(model=model,prompts=build_prompt_registry(),repository=repo,tools=tools)
    out=await agent.run(req, authorization=auth(req, ToolPermission.GITHUB_REPOSITORY_READ), budget=ToolBudget(max_calls=1))
    assert out.tool_calls_used == 1 and tools.calls == [("repository.get", {"repo":"acme/checkout"})]
    assert out.findings[0].source_call_ids == ["call-01"]
    assert next(iter(repo.records.values())).tool_calls_used == 1


@pytest.mark.asyncio
async def test_github_agent_refuses_plan_over_remaining_budget_before_tool_execution():
    req=request(); tools=FakeGitHubTools(); repo=InMemoryAgentRunRepository(); model=FakeModel([{"rationale":"two reads","calls":[{"call_id":"call-01","permission":"github.repository.read","operation":"repository.get","arguments":{}},{"call_id":"call-02","permission":"github.commit.read","operation":"commit.get","arguments":{}}]}])
    agent=GitHubAgent(model=model,prompts=build_prompt_registry(),repository=repo,tools=tools)
    with pytest.raises(RuntimeError, match="exceeds"):
        await agent.run(req, authorization=auth(req, ToolPermission.GITHUB_REPOSITORY_READ, ToolPermission.GITHUB_COMMIT_READ), budget=ToolBudget(max_calls=1))
    assert tools.calls == []


def test_migration_and_prompts_exist():
    text=Path("src/verideploy/database/migrations/versions/0007_agent_contracts.py").read_text()
    assert 'revision = "0007_milestone19_agent_contracts"' in text
    assert 'down_revision = "0006_milestone18_langgraph_runtime"' in text
    assert '"agent_runs"' in text
    assert "FORCE ROW LEVEL SECURITY" in text
    assert "ck_agent_run_tool_budget" in text
    assert all(Path(f"prompts/{name}/v1.0.0.txt").exists() for name in ("supervisor","planner","github"))
