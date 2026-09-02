from contextlib import asynccontextmanager
from fastapi import FastAPI
from services.ai.middleware.correlation import CorrelationIdMiddleware
from services.ai.middleware.internal_service_auth import InternalServiceAuthMiddleware
from services.ai.routes.health import router as health_router
from services.ai.routes.releases import router as releases_router
from services.ai.routes.investigations import router as investigations_router
from services.ai.routes.ingestion import router as ingestion_router
from services.ai.routes.postmortems import router as postmortems_router
from services.ai.routes.ai_status import router as ai_status_router
from services.ai.routes.ai_responses import router as ai_responses_router
from services.ai.routes.image_intelligence import router as image_intelligence_router
from services.ai.routes.embeddings import router as embeddings_router
from services.ai.routes.retrieval import router as retrieval_router
from services.ai.routes.visual_retrieval import router as visual_retrieval_router
from services.ai.routes.fusion import router as fusion_router
from services.ai.routes.audio_transcription import router as audio_transcription_router
from services.ai.routes.video_evidence import router as video_evidence_router
from services.ai.routes.agents import router as agents_router
from services.ai.routes.mcp import router as mcp_router
from services.ai.routes.integrations import router as integrations_router
from services.ai.routes.topology import router as topology_router
from services.ai.routes.evidence import router as evidence_router
from services.ai.routes.evidence_graph import router as evidence_graph_router
from services.ai.routes.operational_schema import router as operational_schema_router
from services.ai.routes.citations import router as citations_router
from services.ai.routes.approvals import router as approvals_router
from services.ai.routes.durability import router as durability_router
from services.ai.routes.graph_execution import router as graph_execution_router
from services.ai.routes.llmops import router as llmops_router
from services.ai.routes.langsmith import router as langsmith_router
from services.ai.routes.evaluations import router as evaluations_router
from services.ai.routes.audit import router as audit_router
from verideploy import __version__
from verideploy.config import get_settings
from verideploy.database.vector_config import load_vector_index_config, validate_embedding_settings
from verideploy.observability.logging import configure_logging
from verideploy.observability.telemetry import configure_telemetry

@asynccontextmanager
async def lifespan(app: FastAPI):
    settings=get_settings(); configure_logging(settings.log_level)
    if settings.app_env != "test" and settings.database_url.startswith("postgresql"):
        vector_config = load_vector_index_config(settings.vector_index_config_path)
        validate_embedding_settings(
            config=vector_config, model=settings.openai_embedding_model, dimensions=settings.openai_embedding_dimensions
        )
    app.state.settings=settings
    yield

app=FastAPI(title="VeriDeploy AI Private Service", version=__version__, docs_url=None, redoc_url=None, lifespan=lifespan)
configure_telemetry(get_settings(), service_name="verideploy-ai-service", fastapi_app=app)
app.add_middleware(CorrelationIdMiddleware)
app.add_middleware(InternalServiceAuthMiddleware)
app.include_router(health_router)
app.include_router(releases_router)
app.include_router(investigations_router)
app.include_router(ingestion_router)
app.include_router(postmortems_router)
app.include_router(ai_status_router)
app.include_router(ai_responses_router)
app.include_router(image_intelligence_router)
app.include_router(embeddings_router)
app.include_router(retrieval_router)
app.include_router(visual_retrieval_router)
app.include_router(fusion_router)
app.include_router(audio_transcription_router)
app.include_router(video_evidence_router)
app.include_router(agents_router)
app.include_router(mcp_router)
app.include_router(integrations_router)
app.include_router(topology_router)
app.include_router(evidence_router)
app.include_router(evidence_graph_router)
app.include_router(operational_schema_router)
app.include_router(citations_router)
app.include_router(approvals_router)
app.include_router(durability_router)
app.include_router(graph_execution_router)
app.include_router(llmops_router)
app.include_router(langsmith_router)
app.include_router(evaluations_router)
app.include_router(audit_router)
