from functools import lru_cache
from verideploy.config import get_settings
from verideploy.database.session import DatabaseManager
from verideploy.llmops.repository import InMemoryLLMOpsRepository,PostgresLLMOpsRepository
from verideploy.llmops.service import LLMOpsService
@lru_cache
def get_llmops_service():
    s=get_settings()
    if s.database_url.startswith('postgresql'): return LLMOpsService(PostgresLLMOpsRepository(DatabaseManager(s.database_url)))
    return LLMOpsService(InMemoryLLMOpsRepository())
