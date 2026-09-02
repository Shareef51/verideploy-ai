from functools import lru_cache
from services.ai.retrieval import get_settings
from verideploy.database.session import DatabaseManager
from verideploy.database.factory import create_database_manager
from verideploy.rag.visual_retrieval.providers import CpuVisualFallbackAdapter, ColPaliAdapter
from verideploy.rag.visual_retrieval.repository import PostgresVisualPageRepository
from verideploy.rag.visual_retrieval.service import VisualDocumentService
from verideploy.rag.visual_retrieval.rendering import PdfPageRenderer

@lru_cache
def get_visual_retrieval_service()->VisualDocumentService:
    settings=get_settings()
    if not settings.database_url.startswith("postgresql"): raise RuntimeError("visual retrieval runtime requires PostgreSQL")
    db=create_database_manager(settings)
    adapter=ColPaliAdapter(settings.visual_retrieval_model) if settings.visual_retrieval_backend=="colpali" else CpuVisualFallbackAdapter()
    return VisualDocumentService(repository=PostgresVisualPageRepository(db),adapter=adapter,renderer=PdfPageRenderer(settings.visual_retrieval_page_root,dpi=settings.visual_retrieval_dpi,max_pages=settings.visual_retrieval_max_pages),index_root=settings.visual_retrieval_index_root)
