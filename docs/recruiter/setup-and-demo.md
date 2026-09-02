# Setup and Recruiter Demo

## Prerequisites
- Node.js 22+
- pnpm 10+
- Python 3.12+
- uv
- Docker Engine + Compose v2

## Local setup
```bash
cp .env.example .env
corepack enable
pnpm install
uv sync --all-groups
docker compose up -d --build
```

Never commit `.env`. Use only synthetic/authorized data. Production configuration uses external secret references and fail-fast validation.

## Health and readiness
- Next.js web: `http://localhost:3000`
- NestJS gateway: `http://localhost:3001`
- Private Python AI service is intentionally not a browser-facing API.

Use the health/readiness endpoints and `docker compose ps` before running demos. The Platform Integration Reliability Checkpoint platform checkpoint documents critical-dependency failure behavior.

## Recruiter demo path
1. Open `/demos` and show the synthetic one-click workflows.
2. Open `/demos/multimodal-killer`.
3. Explain the seven evidence sources and why every conclusion has evidence/citations.
4. Launch the synthetic flow through the public gateway.
5. Move to `/incidents` to explain live investigation state and graph events.
6. Open `/approvals` and show that consequential remediation remains blocked pending a reviewer.
7. Open the evaluation/release-candidate evidence in `evals/reports/` to distinguish measured results from claims.

## Production-like path
Browser → Next.js → NestJS gateway → Kafka → Python workers/LangGraph → PostgreSQL/pgvector + Redis + object storage → Kafka/WebSocket reconciliation → UI.

## Windows
PowerShell equivalents are documented in `docs/operations/local-development.md`.
