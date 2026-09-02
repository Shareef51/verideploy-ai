from decimal import Decimal
from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "VeriDeploy AI"
    app_env: Literal["development", "test", "staging", "production"] = "development"
    app_debug: bool = False
    app_secret_key: SecretStr = SecretStr("local-development-only")
    log_level: str = "INFO"
    web_base_url: str = "http://localhost:3000"
    gateway_base_url: str = "http://localhost:4000"
    ai_service_base_url: str = "http://ai-service:8000"
    internal_service_auth_required: bool = False
    internal_service_auth_secret: SecretStr | None = None
    internal_service_auth_secrets_json: str = "{}"
    internal_service_auth_max_skew_seconds: int = Field(default=60, ge=5, le=600)
    database_url: str = "postgresql+psycopg://verideploy:verideploy@postgres:5432/verideploy"
    redis_url: str = "redis://redis:6379/0"
    # Multi Layer Caching — multi-layer caching. Production must use Redis and encrypted sensitive layers.
    cache_backend: Literal["memory", "redis"] = "redis"
    cache_policy_path: str = "config/cache/policy.json"
    cache_encryption_secret: SecretStr | None = None
    kafka_brokers: str = "kafka:9092"
    s3_endpoint: str = "http://minio:9000"
    s3_bucket: str = "verideploy-evidence"
    s3_region: str = "us-east-1"
    s3_access_key: SecretStr | None = None
    s3_secret_key: SecretStr | None = None
    max_document_upload_bytes: int = 25 * 1024 * 1024
    max_image_upload_bytes: int = 25 * 1024 * 1024
    max_audio_upload_bytes: int = 100 * 1024 * 1024
    max_video_upload_bytes: int = 500 * 1024 * 1024
    video_max_duration_seconds: float = Field(default=3600.0, gt=1, le=21600)
    video_scene_threshold: float = Field(default=0.35, ge=0.05, le=0.95)
    video_keyframe_interval_seconds: float = Field(default=10.0, gt=0.5, le=300)
    video_max_keyframes: int = Field(default=60, ge=1, le=500)
    video_alignment_window_seconds: float = Field(default=5.0, ge=0, le=60)
    video_frame_root: str = "data/processed/video_frames"
    langgraph_default_timeout_seconds: float = Field(default=300.0, gt=1, le=3600)
    langgraph_durability: Literal["sync"] = "sync"
    langgraph_state_encryption_policy: Literal["reference_only"] = "reference_only"
    langgraph_parallel_max_concurrency: int = Field(default=8, ge=1, le=64)
    langgraph_parallel_max_tasks: int = Field(default=16, ge=1, le=256)
    langgraph_parallel_default_deadline_seconds: float = Field(default=30.0, gt=0, le=600)
    langgraph_parallel_max_deadline_seconds: float = Field(default=120.0, gt=0, le=600)
    graph_max_steps: int = Field(default=30, ge=5, le=500)
    graph_max_llm_calls: int = Field(default=15, ge=1, le=100)
    graph_max_tool_calls: int = Field(default=30, ge=1, le=500)
    graph_max_critic_loops: int = Field(default=2, ge=1, le=10)
    graph_max_rag_rewrites: int = Field(default=3, ge=0, le=10)
    graph_max_wall_time_seconds: float = Field(default=300.0, gt=1, le=3600)
    graph_max_context_tokens: int = Field(default=16_000, ge=256, le=200_000)
    graph_max_cost_usd: Decimal = Field(default=Decimal("2.00"), gt=0)
    workflow_lease_ttl_seconds: float = Field(default=30.0, gt=2, le=3600)
    workflow_heartbeat_seconds: float = Field(default=10.0, gt=0, le=1800)
    workflow_stuck_grace_seconds: float = Field(default=5.0, ge=0, le=600)
    workflow_step_default_timeout_seconds: float = Field(default=60.0, gt=0, le=3600)
    workflow_retry_max_attempts: int = Field(default=3, ge=1, le=20)
    workflow_retry_base_seconds: float = Field(default=1.0, ge=0, le=300)
    agent_default_tool_budget: int = Field(default=8, ge=0, le=64)
    agent_max_plan_tool_calls: int = Field(default=12, ge=1, le=64)
    rag_agent_tool_budget: int = Field(default=4, ge=1, le=16)
    rag_agent_min_evidence: int = Field(default=2, ge=1, le=20)
    rag_agent_min_sources: int = Field(default=1, ge=1, le=20)
    visual_agent_tool_budget: int = Field(default=4, ge=2, le=16)
    visual_agent_max_analyses: int = Field(default=3, ge=1, le=5)
    visual_agent_min_short_side: int = Field(default=720, ge=128, le=8192)
    visual_agent_min_confidence: float = Field(default=0.55, ge=0, le=1)
    runtime_evidence_adapter: Literal["synthetic", "live"] = "synthetic"
    runtime_agent_tool_budget: int = Field(default=4, ge=1, le=8)
    runtime_agent_min_evidence: int = Field(default=1, ge=1, le=20)
    runtime_agent_min_sources: int = Field(default=1, ge=1, le=4)
    runtime_anomaly_z_threshold: float = Field(default=2.0, ge=0, le=20)
    runtime_anomaly_percent_threshold: float = Field(default=50.0, ge=0, le=10000)
    runtime_http_timeout_seconds: float = Field(default=15.0, gt=0, le=120)
    prometheus_base_url: str | None = None
    grafana_base_url: str | None = None
    tempo_base_url: str | None = None
    loki_base_url: str | None = None
    runtime_observability_token: SecretStr | None = None
    rca_agent_min_root_support: int = Field(default=2, ge=1, le=16)
    rca_agent_min_confidence: float = Field(default=0.55, ge=0, le=1)
    rca_agent_max_evidence: int = Field(default=40, ge=2, le=128)
    critic_agent_tool_budget: int = Field(default=2, ge=0, le=8)
    critic_max_followups: int = Field(default=2, ge=0, le=8)
    critic_followup_top_k: int = Field(default=4, ge=1, le=20)
    critic_entailment_threshold: float = Field(default=0.18, ge=0, le=1)
    critic_partial_entailment_threshold: float = Field(default=0.08, ge=0, le=1)
    critic_pass_confidence: float = Field(default=0.55, ge=0, le=1)
    mcp_tool_timeout_seconds: float = Field(default=15.0, gt=0, le=120)
    mcp_circuit_breaker_threshold: int = Field(default=3, ge=1, le=20)
    mcp_circuit_breaker_reset_seconds: float = Field(default=30.0, gt=0, le=600)
    mcp_external_writes_enabled: bool = False
    github_api_base_url: str = "https://api.github.com"
    github_api_token: SecretStr | None = None
    jira_base_url: str | None = None
    jira_api_token: SecretStr | None = None
    jira_email: str | None = None
    jira_auth_mode: Literal["basic", "bearer"] = "basic"
    integration_allowed_hosts: str = "api.github.com,localhost,prometheus,grafana,tempo,loki"
    integration_http_timeout_seconds: float = Field(default=15.0, gt=0, le=120)
    integration_max_attempts: int = Field(default=3, ge=1, le=8)
    integration_max_requests_per_run: int = Field(default=50, ge=1, le=500)
    integration_backoff_base_seconds: float = Field(default=0.25, ge=0, le=10)
    integration_max_retry_delay_seconds: float = Field(default=60.0, ge=0, le=600)

    # OpenTelemetry Across All Services — OpenTelemetry across all services.
    otel_enabled: bool = False
    otel_exporter_otlp_endpoint: str = "http://otel-collector:4317"
    otel_exporter_otlp_insecure: bool = True
    otel_excluded_urls: str = "health/live,health/ready"
    otel_traces_sampler: str = "parentbased_traceidratio"
    otel_traces_sampler_arg: float = Field(default=1.0, ge=0, le=1)
    otel_browser_exporter_url: str = "http://localhost:4318/v1/traces"

    # LangSmith Integration — LangSmith integration (observability only).
    langsmith_enabled: bool = False
    langsmith_api_key: SecretStr | None = None
    langsmith_endpoint: str = "https://api.smith.langchain.com"
    langsmith_workspace_id: str | None = None
    langsmith_project_prefix: str = "verideploy"
    langsmith_dataset_export_enabled: bool = False
    langsmith_dataset_prefix: str = "verideploy-evals"

    ai_provider: Literal["openai", "test"] = "openai"
    ai_control_backend: Literal["memory", "redis"] = "memory"
    ai_timeout_seconds: float = Field(default=45.0, gt=0, le=600)
    ai_max_attempts: int = Field(default=3, ge=1, le=8)
    ai_requests_per_minute: int = Field(default=60, ge=1, le=100_000)
    ai_monthly_budget_usd: Decimal = Field(default=Decimal("250.00"), gt=0)
    ai_default_estimated_request_cost_usd: Decimal = Field(default=Decimal("0.01"), ge=0)
    openai_api_key: SecretStr | None = None
    openai_reasoning_model: str | None = None
    openai_standard_model: str | None = None
    openai_fast_model: str | None = None
    openai_fast_fallback_models: str = ""
    openai_standard_fallback_models: str = ""
    openai_reasoning_fallback_models: str = ""
    ai_fast_concurrency: int = Field(default=16, ge=1, le=10000)
    ai_standard_concurrency: int = Field(default=8, ge=1, le=10000)
    ai_reasoning_concurrency: int = Field(default=4, ge=1, le=10000)
    ai_pricing_catalog_path: str = "config/model-pricing.json"
    ai_allow_unpriced_models: bool = False
    ai_operation_role_overrides_json: str = "{}"
    openai_embedding_model: str = "text-embedding-3-large"
    openai_embedding_dimensions: int = Field(default=3072, ge=1, le=65536)
    embedding_batch_size: int = Field(default=128, ge=1, le=2048)
    embedding_max_concurrency: int = Field(default=4, ge=1, le=128)
    embedding_max_attempts: int = Field(default=3, ge=1, le=8)
    vector_index_config_path: str = "config/vector-index.json"
    retrieval_rrf_k: int = Field(default=60, ge=1, le=1000)
    retrieval_candidate_k: int = Field(default=60, ge=1, le=200)
    retrieval_max_per_source: int = Field(default=2, ge=1, le=20)
    retrieval_cache_ttl_seconds: int = Field(default=300, ge=1, le=86400)
    retrieval_index_version: str = "embedding_index_v1"
    retrieval_corpus_version: str = "1.0.0"
    retrieval_pipeline_version: str = "1.0.0"
    retrieval_pipeline_top_k: int = Field(default=8, ge=1, le=50)
    retrieval_pipeline_max_expansions: int = Field(default=2, ge=0, le=4)
    retrieval_pipeline_min_rerank_score: float = Field(default=0.10, ge=0, le=1)
    self_corrective_rag_max_attempts: int = Field(default=3, ge=1, le=5)
    self_corrective_rag_max_query_rewrites: int = Field(default=2, ge=0, le=4)
    self_corrective_rag_allow_scope_relaxation: bool = True
    self_corrective_rag_external_search_mode: Literal["disabled", "authorized_only"] = "disabled"
    hallucination_supported_threshold: float = Field(default=0.68, ge=0, le=1)
    hallucination_uncertain_threshold: float = Field(default=0.42, ge=0, le=1)
    hallucination_contradiction_threshold: float = Field(default=0.65, ge=0, le=1)
    hallucination_unsupported_material_threshold: float = Field(default=0.05, ge=0, le=1)
    visual_retrieval_backend: Literal["cpu_fallback", "colpali"] = "cpu_fallback"
    visual_retrieval_model: str = "vidore/colpali-v1.3-hf"
    visual_retrieval_dpi: int = Field(default=144, ge=72, le=300)
    visual_retrieval_max_pages: int = Field(default=500, ge=1, le=5000)
    visual_retrieval_page_root: str = "data/processed/visual_pages"
    visual_retrieval_index_root: str = "data/processed/visual_index"
    rag_context_max_tokens: int = Field(default=8_000, ge=256, le=200_000)
    rag_context_max_images: int = Field(default=4, ge=0, le=50)
    rag_context_max_evidence: int = Field(default=20, ge=1, le=200)
    rag_context_max_per_channel: int = Field(default=8, ge=1, le=100)
    db_pool_size: int = Field(default=10, ge=1, le=200)
    db_max_overflow: int = Field(default=20, ge=0, le=500)
    db_pool_timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    db_statement_timeout_ms: int = Field(default=15_000, ge=100, le=600_000)
    db_lock_timeout_ms: int = Field(default=2_000, ge=50, le=120_000)
    db_idle_in_transaction_timeout_ms: int = Field(default=30_000, ge=1_000, le=900_000)
    db_pool_recycle_seconds: int = Field(default=1_800, ge=30, le=86_400)
    db_slow_query_threshold_ms: float = Field(default=750.0, gt=0, le=600_000)
    db_migration_lock_timeout_seconds: int = Field(default=120, ge=1, le=1800)
    openai_transcription_model: str | None = None
    transcription_max_attempts: int = Field(default=3, ge=1, le=8)
    transcription_timeout_seconds: float = Field(default=120.0, gt=0, le=900)
    transcription_pii_patterns_json: str = "[]"
    transcription_response_mode: Literal["timestamped", "diarized"] = "timestamped"
    ai_image_default_detail: Literal["low", "high", "original", "auto"] = "auto"
    ai_image_allow_original_detail: bool = False
    ai_image_max_pixels: int = Field(default=40_000_000, ge=1_000_000, le=200_000_000)
    ai_image_max_side: int = Field(default=8192, ge=512, le=50_000)

    demo_mode: bool = True
    synthetic_data_seed: int = 8421
    require_human_approval_at_risk_score: int = Field(default=80, ge=0, le=100)
    approval_default_expiry_seconds: int = Field(default=3600, ge=60, le=604800)
    approval_signing_secret: SecretStr | None = None

    # Environment Secrets Configuration Management — environment, secrets, and configuration management.
    environment_manifest_path: str = "config/environments/manifest.json"
    external_secret_provider: Literal["aws-sm", "azure-kv", "gcp-sm", "vault", "k8s-secret", "none"] = "none"
    config_kms_key_ref: str | None = None
    secret_rotation_max_age_days: int = Field(default=90, ge=1, le=365)
    configuration_management_enforced: bool = False
    platform_dependency_readiness_enabled: bool = False
    platform_readiness_timeout_seconds: float = Field(default=1.5, gt=0.1, le=10.0)

    @field_validator("app_secret_key")
    @classmethod
    def strong_secret_in_production(cls, value: SecretStr, info):
        env = info.data.get("app_env")
        if env == "production" and len(value.get_secret_value()) < 32:
            raise ValueError("APP_SECRET_KEY must be at least 32 characters in production")
        return value

    @model_validator(mode="after")
    def production_ai_controls(self) -> "Settings":
        if self.app_env == "production" and self.ai_control_backend != "redis":
            raise ValueError("AI_CONTROL_BACKEND must be redis in production")
        if self.app_env == "production" and self.cache_backend != "redis":
            raise ValueError("CACHE_BACKEND must be redis in production")
        if self.app_env == "production" and self.cache_encryption_secret is not None:
            if len(self.cache_encryption_secret.get_secret_value().encode()) < 32:
                raise ValueError("CACHE_ENCRYPTION_SECRET must be at least 32 bytes when configured")
        if self.ai_provider == "openai" and self.app_env in {"staging", "production"} and self.openai_api_key is None:
            raise ValueError("OPENAI_API_KEY is required for OpenAI provider in staging/production")
        if self.app_env in {"staging", "production"}:
            missing_roles = [name for name, model in (("FAST", self.openai_fast_model), ("STANDARD", self.openai_standard_model), ("REASONING", self.openai_reasoning_model)) if not model]
            if missing_roles:
                raise ValueError(f"OpenAI model bindings required for roles: {', '.join(missing_roles)}")
        if self.critic_max_followups > self.critic_agent_tool_budget:
            raise ValueError("CRITIC_MAX_FOLLOWUPS must not exceed CRITIC_AGENT_TOOL_BUDGET")
        if self.critic_partial_entailment_threshold > self.critic_entailment_threshold:
            raise ValueError("CRITIC_PARTIAL_ENTAILMENT_THRESHOLD must not exceed CRITIC_ENTAILMENT_THRESHOLD")
        if self.hallucination_uncertain_threshold > self.hallucination_supported_threshold:
            raise ValueError("HALLUCINATION_UNCERTAIN_THRESHOLD must not exceed HALLUCINATION_SUPPORTED_THRESHOLD")
        if self.workflow_heartbeat_seconds >= self.workflow_lease_ttl_seconds:
            raise ValueError("WORKFLOW_HEARTBEAT_SECONDS must be less than WORKFLOW_LEASE_TTL_SECONDS")
        if self.otel_enabled and not self.otel_exporter_otlp_endpoint.strip():
            raise ValueError("OTEL_EXPORTER_OTLP_ENDPOINT must not be blank when OpenTelemetry is enabled")
        if self.langsmith_enabled and self.app_env in {"staging", "production"} and self.langsmith_api_key is None:
            raise ValueError("LANGSMITH_API_KEY is required when LangSmith is enabled in staging/production")
        if not self.langsmith_project_prefix.strip():
            raise ValueError("LANGSMITH_PROJECT_PREFIX must not be blank")
        if not self.langsmith_dataset_prefix.strip():
            raise ValueError("LANGSMITH_DATASET_PREFIX must not be blank")
        if self.app_env == "production" and self.configuration_management_enforced:
            if self.external_secret_provider == "none":
                raise ValueError("EXTERNAL_SECRET_PROVIDER is required when production configuration management is enforced")
            if not (self.config_kms_key_ref or "").strip():
                raise ValueError("CONFIG_KMS_KEY_REF is required when production configuration management is enforced")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
