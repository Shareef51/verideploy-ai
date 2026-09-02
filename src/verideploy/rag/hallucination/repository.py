from __future__ import annotations

import copy
import json
from typing import Protocol
from uuid import UUID

from sqlalchemy import text

from verideploy.database.session import DatabaseManager
from .schemas import HallucinationProtectionResult


class HallucinationProtectionRepository(Protocol):
    def save(self, result: HallucinationProtectionResult) -> None: ...
    def get(self, *, tenant_id: UUID, verification_id: UUID) -> HallucinationProtectionResult | None: ...


class InMemoryHallucinationProtectionRepository:
    def __init__(self) -> None:
        self._items: dict[tuple[UUID, UUID], HallucinationProtectionResult] = {}

    def save(self, result: HallucinationProtectionResult) -> None:
        self._items[(result.tenant_id, result.verification_id)] = copy.deepcopy(result)

    def get(self, *, tenant_id: UUID, verification_id: UUID) -> HallucinationProtectionResult | None:
        item = self._items.get((tenant_id, verification_id))
        return copy.deepcopy(item) if item else None


class PostgresHallucinationProtectionRepository:
    def __init__(self, db: DatabaseManager) -> None:
        self.db = db

    def save(self, result: HallucinationProtectionResult) -> None:
        payload = result.model_dump(mode="json")
        with self.db.transaction(result.tenant_id) as session:
            session.execute(text("""
                INSERT INTO hallucination_protection_runs
                  (verification_id, tenant_id, self_corrective_run_id, verifier_version, protected,
                   supported_count, uncertain_count, unsupported_count, unsupported_material_rate,
                   prompt_injection_evidence_count, result_json)
                VALUES (:verification_id, :tenant_id, :source_run_id, :version, :protected,
                        :supported, :uncertain, :unsupported, :unsupported_rate, :injection_count,
                        CAST(:result_json AS jsonb))
            """), {
                "verification_id": str(result.verification_id), "tenant_id": str(result.tenant_id),
                "source_run_id": str(result.self_corrective_run_id), "version": result.verifier_version,
                "protected": result.protected, "supported": result.supported_count,
                "uncertain": result.uncertain_count, "unsupported": result.unsupported_count,
                "unsupported_rate": result.unsupported_material_rate,
                "injection_count": result.prompt_injection_evidence_count,
                "result_json": json.dumps(payload, sort_keys=True, separators=(",", ":")),
            })
            for claim in result.claims:
                session.execute(text("""
                    INSERT INTO hallucination_claim_verifications
                      (verification_id, claim_id, tenant_id, label, action, material, proposed_confidence,
                       adjusted_confidence, claim_json)
                    VALUES (:verification_id, :claim_id, :tenant_id, :label, :action, :material,
                            :proposed_confidence, :adjusted_confidence, CAST(:claim_json AS jsonb))
                """), {
                    "verification_id": str(result.verification_id), "claim_id": claim.claim_id,
                    "tenant_id": str(result.tenant_id), "label": claim.label.value, "action": claim.action.value,
                    "material": claim.material, "proposed_confidence": claim.proposed_confidence,
                    "adjusted_confidence": claim.adjusted_confidence,
                    "claim_json": json.dumps(claim.model_dump(mode="json"), sort_keys=True, separators=(",", ":")),
                })

    def get(self, *, tenant_id: UUID, verification_id: UUID) -> HallucinationProtectionResult | None:
        with self.db.transaction(tenant_id) as session:
            row = session.execute(text("""
                SELECT result_json FROM hallucination_protection_runs
                WHERE tenant_id=:tenant_id AND verification_id=:verification_id
            """), {"tenant_id": str(tenant_id), "verification_id": str(verification_id)}).scalar_one_or_none()
        return HallucinationProtectionResult.model_validate(row) if row else None
