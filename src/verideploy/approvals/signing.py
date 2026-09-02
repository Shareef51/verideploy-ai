from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any


def canonical_event_payload(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


class ApprovalAuditSigner:
    def __init__(self, secret: str) -> None:
        if len(secret) < 16:
            raise ValueError("approval audit signing secret must be at least 16 characters")
        self._secret = secret.encode("utf-8")

    def sign(self, payload: dict[str, Any]) -> tuple[str, str]:
        body = canonical_event_payload(payload)
        digest = hashlib.sha256(body).hexdigest()
        signature = hmac.new(self._secret, body, hashlib.sha256).hexdigest()
        return digest, signature

    def verify(self, payload: dict[str, Any], signature: str) -> bool:
        body = canonical_event_payload(payload)
        expected = hmac.new(self._secret, body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)
