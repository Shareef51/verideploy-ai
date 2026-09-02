# LangSmith Integration Verification

## Configuration

LangSmith is disabled by default. To enable it, configure `LANGSMITH_ENABLED=true`, an API key, endpoint/workspace if required, and a project prefix. Project name is derived as `<prefix>-<APP_ENV>`.

Dataset export additionally requires `LANGSMITH_DATASET_EXPORT_ENABLED=true` and explicit use of the dataset hook.

## Operational checks

- `make langsmith-integration-validate`
- `pytest -q tests/unit/test_langsmith_integration.py`
- `GET /internal/v1/langsmith/status` from a trusted service identity

The status endpoint never returns the API key.

## Failure handling

A LangSmith outage should update `last_error` on the observer status while business execution continues. Local LLMOps Data Platform LLMOps persistence is independent of external tracing.
