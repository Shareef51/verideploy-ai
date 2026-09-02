# Live Agent Execution Screen Verification

Run `make agent-execution-screen-validate` and `pytest -q tests/unit/test_live_agent_execution_screen.py`. Confirm the browser references only `/api/v1/agent-execution/*`, public OpenAPI contains no `/internal/v1`, and a replay followed by authoritative refresh converges.
