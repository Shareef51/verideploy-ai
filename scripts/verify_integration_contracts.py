from __future__ import annotations
import asyncio, json
from datetime import datetime, timezone
from verideploy.integrations.adapters import SyntheticIntegrationBundle
from verideploy.integrations.contracts import IntegrationResult, IntegrationType

async def main() -> None:
    start=datetime(2026,8,17,12,0,tzinfo=timezone.utc); end=datetime(2026,8,17,13,0,tzinfo=timezone.utc)
    result=await SyntheticIntegrationBundle().snapshot(service="checkout",environment="production",start=start,end=end)
    expected={x.value for x in IntegrationType}
    if set(result) != expected:
        raise SystemExit("synthetic integration source parity failed")
    for item in result.values():
        IntegrationResult.model_validate(item.model_dump(mode="json"))
    print(json.dumps({"sources":sorted(expected),"contract":"IntegrationResult","status":"pass"},indent=2))

if __name__ == "__main__": asyncio.run(main())
