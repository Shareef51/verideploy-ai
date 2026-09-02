# NestJS Python Boundary Verification

Run `make api-boundary-validate` and `pytest -q tests/unit/test_api_boundary.py`.

Production/staging must use a strong `APP_SECRET_KEY` and should set a distinct `INTERNAL_SERVICE_AUTH_SECRET`. The AI service must not publish port 8000 externally. Gateway retries are bounded and mutation calls that are not intrinsically idempotent must set `retry:false`.

Upload-handoff operators should keep object-store URLs short lived and preserve lifecycle cleanup for abandoned handoffs. Completion verifies object metadata before the Kafka ingestion command is emitted.
