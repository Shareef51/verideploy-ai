# LangGraph Production Runtime Verification

Checks performed in the build environment:

- focused runtime/registry/node-wrapper tests;
- simulated worker-crash/checkpoint resume test;
- timeout and cancellation tests;
- streaming contract test;
- migration/RLS contract tests;
- cumulative Python regression suite;
- offline Alembic upgrade/downgrade SQL generation;
- Python byte compilation;
- FastAPI health smoke;
- JSON/YAML/TOML parsing;
- TypeScript/TSX syntax transpilation when the local compiler is available;
- source placeholder and secret-pattern scans;
- ZIP integrity and SHA-256.

Environment limitation: the `langgraph` packages and a live PostgreSQL test URL are not installed/configured in this runtime. The real production dependencies are declared and the production factory uses `AsyncPostgresSaver`; focused tests use protocol-compatible deterministic doubles and do not claim a live LangGraph/PostgreSQL execution.
