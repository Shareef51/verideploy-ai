from __future__ import annotations
import json
from verideploy.operational_schema import validate_schema_catalog

if __name__ == "__main__":
    print(json.dumps(validate_schema_catalog(), indent=2, sort_keys=True))
