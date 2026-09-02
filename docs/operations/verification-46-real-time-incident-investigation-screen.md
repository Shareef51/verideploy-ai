# Real Time Incident Investigation Screen Verification

Run `python scripts/validate_incident_screen.py` and `pytest -q tests/unit/test_incident_investigation_screen.py`.

The acceptance gate is satisfied only when replay from the durable journal and authoritative refresh project the same investigation state, and the frontend contains explicit sequence-gap/replay/reconciliation logic.
