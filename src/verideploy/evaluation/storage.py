from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from verideploy.evaluation.models import CaseResult, RunManifest


class EvaluationStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_schema(self) -> None:
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS evaluation_runs (
                    run_id TEXT PRIMARY KEY,
                    dataset_id TEXT NOT NULL,
                    dataset_version TEXT NOT NULL,
                    aggregate_score REAL NOT NULL,
                    status TEXT NOT NULL,
                    manifest_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS evaluation_case_results (
                    run_id TEXT NOT NULL,
                    case_id TEXT NOT NULL,
                    passed INTEGER NOT NULL,
                    result_json TEXT NOT NULL,
                    PRIMARY KEY (run_id, case_id),
                    FOREIGN KEY (run_id) REFERENCES evaluation_runs(run_id)
                );
                CREATE INDEX IF NOT EXISTS idx_evaluation_runs_dataset
                    ON evaluation_runs(dataset_id, dataset_version, created_at);
                CREATE TABLE IF NOT EXISTS evaluation_baselines (
                    dataset_id TEXT NOT NULL,
                    environment TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    promoted_by TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    promoted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (dataset_id, environment)
                );
                CREATE TABLE IF NOT EXISTS evaluation_overrides (
                    override_id TEXT PRIMARY KEY,
                    candidate_run_id TEXT NOT NULL,
                    policy_id TEXT NOT NULL,
                    approval_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_evaluation_overrides_candidate
                    ON evaluation_overrides(candidate_run_id, policy_id, created_at);
                """
            )

    def save_run(self, manifest: RunManifest, results: list[CaseResult]) -> None:
        payload = manifest.model_dump_json()
        with self._connect() as db:
            db.execute(
                """INSERT OR REPLACE INTO evaluation_runs
                (run_id, dataset_id, dataset_version, aggregate_score, status, manifest_json)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (manifest.run_id, manifest.dataset_id, manifest.dataset_version, manifest.aggregate_score, manifest.status, payload),
            )
            db.executemany(
                """INSERT OR REPLACE INTO evaluation_case_results
                (run_id, case_id, passed, result_json) VALUES (?, ?, ?, ?)""",
                [(manifest.run_id, r.case_id, int(r.passed), r.model_dump_json()) for r in results],
            )

    def get_run(self, run_id: str) -> RunManifest | None:
        with self._connect() as db:
            row = db.execute("SELECT manifest_json FROM evaluation_runs WHERE run_id = ?", (run_id,)).fetchone()
        return None if row is None else RunManifest.model_validate_json(row["manifest_json"])

    def latest_completed(self, dataset_id: str, *, exclude_run_id: str | None = None) -> RunManifest | None:
        query = "SELECT manifest_json FROM evaluation_runs WHERE dataset_id = ? AND status = 'completed'"
        params: list[object] = [dataset_id]
        if exclude_run_id:
            query += " AND run_id <> ?"
            params.append(exclude_run_id)
        query += " ORDER BY created_at DESC, rowid DESC LIMIT 1"
        with self._connect() as db:
            row = db.execute(query, params).fetchone()
        return None if row is None else RunManifest.model_validate_json(row["manifest_json"])


    def list_runs(self, *, dataset_id: str | None = None, limit: int = 100) -> list[RunManifest]:
        query = "SELECT manifest_json FROM evaluation_runs"
        params: list[object] = []
        if dataset_id:
            query += " WHERE dataset_id = ?"
            params.append(dataset_id)
        query += " ORDER BY created_at DESC, rowid DESC LIMIT ?"
        params.append(limit)
        with self._connect() as db:
            rows = db.execute(query, params).fetchall()
        return [RunManifest.model_validate_json(row["manifest_json"]) for row in rows]

    def get_case_results(self, run_id: str) -> list[CaseResult]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT result_json FROM evaluation_case_results WHERE run_id = ? ORDER BY case_id",
                (run_id,),
            ).fetchall()
        return [CaseResult.model_validate_json(row["result_json"]) for row in rows]

    def export_run_json(self, run_id: str, target: Path) -> None:
        with self._connect() as db:
            run = db.execute("SELECT manifest_json FROM evaluation_runs WHERE run_id = ?", (run_id,)).fetchone()
            rows = db.execute("SELECT result_json FROM evaluation_case_results WHERE run_id = ? ORDER BY case_id", (run_id,)).fetchall()
        if run is None:
            raise KeyError(run_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({"manifest": json.loads(run[0]), "results": [json.loads(r[0]) for r in rows]}, indent=2), encoding="utf-8")
    def promote_baseline(self, *, dataset_id: str, environment: str, run_id: str, promoted_by: str, reason: str) -> None:
        if self.get_run(run_id) is None:
            raise KeyError(run_id)
        with self._connect() as db:
            db.execute(
                """INSERT OR REPLACE INTO evaluation_baselines
                (dataset_id, environment, run_id, promoted_by, reason, promoted_at)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
                (dataset_id, environment, run_id, promoted_by, reason),
            )

    def get_baseline(self, *, dataset_id: str, environment: str) -> RunManifest | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT run_id FROM evaluation_baselines WHERE dataset_id = ? AND environment = ?",
                (dataset_id, environment),
            ).fetchone()
        return None if row is None else self.get_run(str(row["run_id"]))

    def save_override(self, approval: object) -> None:
        from verideploy.evaluation.regression_gates import OverrideApproval
        parsed = approval if isinstance(approval, OverrideApproval) else OverrideApproval.model_validate(approval)
        with self._connect() as db:
            db.execute(
                """INSERT OR REPLACE INTO evaluation_overrides
                (override_id, candidate_run_id, policy_id, approval_json) VALUES (?, ?, ?, ?)""",
                (parsed.override_id, parsed.candidate_run_id, parsed.policy_id, parsed.model_dump_json()),
            )

    def get_active_override(self, candidate_run_id: str, policy_id: str):
        from verideploy.evaluation.regression_gates import OverrideApproval
        with self._connect() as db:
            rows = db.execute(
                """SELECT approval_json FROM evaluation_overrides
                WHERE candidate_run_id = ? AND policy_id = ? ORDER BY created_at DESC, rowid DESC""",
                (candidate_run_id, policy_id),
            ).fetchall()
        for row in rows:
            approval = OverrideApproval.model_validate_json(row["approval_json"])
            if approval.active():
                return approval
        return None

