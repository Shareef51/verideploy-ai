import json
from uuid import uuid4
import pytest
from tests.unit.test_postmortems import stack, completed_investigation, command
from workers.postmortem.postmortem_worker import handle_postmortem_command

@pytest.mark.asyncio
async def test_worker_generates_and_replays_idempotently(tmp_path):
    investigations,service=stack(tmp_path); tenant,user=uuid4(),uuid4(); inv=completed_investigation(investigations,tenant,user); cmd=command(inv,user); seen=[]
    async def emit(t,p): seen.append((t,p))
    payload=cmd.model_dump_json().encode(); await handle_postmortem_command(payload,service,emit); await handle_postmortem_command(payload,service,emit)
    assert [v[0] for v in seen]==["postmortem.generated","postmortem.replayed"]

@pytest.mark.asyncio
async def test_worker_rejects_malformed_command(tmp_path):
    _,service=stack(tmp_path); seen=[]
    async def emit(t,p): seen.append((t,p))
    await handle_postmortem_command(json.dumps({"bad":True}).encode(),service,emit)
    assert seen==[("postmortem.command.rejected",{"reason":"schema_validation_failed"})]
