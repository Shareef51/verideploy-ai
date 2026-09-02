.PHONY: evidence-graph-seed topology-generate topology-validate topology-seed knowledge-corpus-validate setup up down migrate migrate-down db-check db-backup db-restore-verify api gateway web worker ingestion-worker embedding-worker video-worker kafka-topics test lint typecheck contracts retrieval-benchmark visual-retrieval-benchmark fusion-benchmark rca-benchmark demo
setup:
	corepack enable
	pnpm install --frozen-lockfile || pnpm install
	uv sync --all-groups
up:
	docker compose up -d --build
down:
	docker compose down --remove-orphans
migrate:
	PYTHONPATH=src:. uv run alembic upgrade head
migrate-down:
	PYTHONPATH=src:. uv run alembic downgrade -1
db-check:
	PYTHONPATH=src:. uv run python scripts/check_database_foundation.py
db-backup:
	docker compose exec -T postgres pg_dump -U verideploy -d verideploy -Fc > verideploy.dump
db-restore-verify:
	PYTHONPATH=src:. uv run python scripts/verify_database_restore.py
api:
	PYTHONPATH=src:. uv run uvicorn services.ai.main:app --host 0.0.0.0 --port 8000 --reload
gateway:
	pnpm --filter @verideploy/gateway dev
web:
	pnpm --filter @verideploy/web dev
worker:
	PYTHONPATH=src:. uv run python -m workers.investigation.investigation_main
ingestion-worker:
	PYTHONPATH=src:. uv run python -m workers.ingestion.ingestion_main
embedding-worker:
	@echo "Embedding worker is transport-ready; invoke workers.embedding.embedding_worker.EmbeddingWorker from the Kafka runtime adapter."
video-worker:
	PYTHONPATH=src:. python -m workers.multimodal.video_evidence_main

kafka-topics:
	docker compose run --rm kafka-init
contracts:
	PYTHONPATH=src:. python scripts/generate_structured_contracts.py
	python scripts/validate_contracts.py
test:
	uv run pytest -q
	pnpm test
retrieval-benchmark:
	PYTHONPATH=src:. python scripts/benchmark_retrieval.py
visual-retrieval-benchmark:
	PYTHONPATH=src:. python scripts/benchmark_visual_retrieval.py
fusion-benchmark:
	PYTHONPATH=src:. python scripts/benchmark_multimodal_fusion.py
rca-benchmark:
	PYTHONPATH=src:. python scripts/benchmark_rca.py
lint:
	uv run ruff check .
	pnpm lint
typecheck:
	uv run mypy src services workers
	pnpm typecheck
demo:
	@echo "Demo: start stack with 'make up' and open http://localhost:3000/evidence"

critic-benchmark:
	PYTHONPATH=src python scripts/benchmark_critic.py

knowledge-corpus-validate:
	PYTHONPATH=src:. python scripts/validate_knowledge_corpus.py

integration-contracts:
	PYTHONPATH=src:. python scripts/verify_integration_contracts.py


topology-generate:
	PYTHONPATH=src:. python scripts/generate_nexuspay_topology.py

topology-validate:
	PYTHONPATH=src:. python scripts/validate_topology.py

topology-seed:
	PYTHONPATH=src:. python scripts/seed_nexuspay_topology.py

incident-dataset-generate:
	PYTHONPATH=src:. python scripts/generate_incident_dataset.py

incident-dataset-validate:
	PYTHONPATH=src:. python scripts/validate_incident_dataset.py

incident-dataset-seed:
	PYTHONPATH=src:. python scripts/seed_incident_dataset.py


evidence-graph-seed:
	PYTHONPATH=src:. python scripts/seed_evidence_graph.py

schema-catalog-validate:
	PYTHONPATH=src:. python scripts/validate_schema.py

postgres-performance-validate:
	PYTHONPATH=src:. python scripts/validate_postgres_performance.py

metadata-filter-validate:
	PYTHONPATH=src:. python scripts/validate_metadata_filters.py

self-corrective-rag-validate:
	PYTHONPATH=src:. pytest -q tests/unit/test_self_corrective_rag.py

hallucination-protection-validate:
	PYTHONPATH=src:. python scripts/validate_hallucination_protection.py

citation-architecture-validate:
	PYTHONPATH=src:. pytest -q tests/unit/test_citation_architecture.py

langgraph-state-validate:
	PYTHONPATH=src:. python scripts/validate_langgraph_state.py

dynamic-parallel-validate:
	PYTHONPATH=src:. python scripts/validate_dynamic_parallelism.py

human-approval-validate:
	PYTHONPATH=src:. python scripts/validate_human_approval.py

workflow-durability-validate:
	PYTHONPATH=src:. python scripts/validate_workflow_durability.py

api-boundary-validate:
	PYTHONPATH=src:. python scripts/validate_api_boundary.py

frontend-foundation-validate:
	PYTHONPATH=src:. python scripts/validate_frontend_foundation.py

release-risk-screen-validate:
	python scripts/validate_release_risk_screen.py

incident-screen-validate:
	PYTHONPATH=src:. python scripts/validate_incident_screen.py

.PHONY: agent-execution-screen-validate
agent-execution-screen-validate:
	PYTHONPATH=src:. python scripts/validate_agent_execution_screen.py

.PHONY: llmops-data-validate
llmops-data-validate:
	PYTHONPATH=src:. python scripts/validate_llmops_data_platform.py

.PHONY: langsmith-integration-validate
langsmith-integration-validate:
	PYTHONPATH=src:. python scripts/validate_langsmith_integration.py

.PHONY: release-validate release-plan release-deploy release-verify release-seed release-rollback
release-validate:
	PYTHONPATH=src:. python scripts/validate_release.py
release-plan:
	./scripts/release/plan.sh
release-deploy:
	./scripts/release/deploy.sh
release-verify:
	./scripts/release/verify.sh
release-seed:
	./scripts/release/seed_demo.sh
release-rollback:
	@test -n "$(REVISION)" || (echo "REVISION is required" && exit 2)
	./scripts/release/rollback.sh "$(REVISION)"
