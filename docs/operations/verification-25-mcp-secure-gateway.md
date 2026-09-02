# MCP Secure Gateway Verification

Run the focused suite:

```bash
pytest -q tests/unit/test_mcp_gateway.py tests/unit/test_mcp_sdk_contract.py tests/unit/test_mcp_api.py
```

Run all cumulative tests with `pytest -q`. Generate migration SQL with `alembic upgrade head --sql` and the MCP Secure Gateway downgrade range. A provisioned environment should also install the declared `mcp>=2,<3` dependency and exercise each `MCPServer` with the official MCP Client/Inspector.

The current build environment does not contain the `mcp` package, Docker Engine, or a live PostgreSQL integration URL, so live MCP transport and live RLS execution are not claimed by this verification record.
