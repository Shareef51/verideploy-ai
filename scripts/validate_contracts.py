from pathlib import Path
import json
import re
import sys

import yaml

required_yaml = [Path("contracts/openapi/gateway.yaml"), Path("contracts/asyncapi/events.yaml")]
structured_manifest = Path("contracts/structured-output/manifest.json")
structured_schema_dir = Path("contracts/structured-output")

required_json = [
    Path("contracts/events/release-risk-command.v1.json"),
    Path("contracts/events/release-risk-event.v1.json"),
    Path("contracts/events/investigation-command.v1.json"),
    Path("contracts/events/investigation-cancel-command.v1.json"),
    Path("contracts/events/investigation-event.v1.json"),
    Path("contracts/events/ingestion-command.v1.json"),
    Path("contracts/events/ingestion-event.v1.json"),
    Path("contracts/events/postmortem-command.v1.json"),
    Path("contracts/events/postmortem-event.v1.json"),
]
missing = [str(path) for path in [*required_yaml, *required_json, structured_manifest] if not path.exists() or not path.read_text(encoding="utf-8").strip()]
if missing:
    print("invalid contracts:", ", ".join(missing), file=sys.stderr)
    raise SystemExit(1)

semver = re.compile(r"^\s*version:\s*[0-9]+\.[0-9]+\.[0-9]+\s*$", re.MULTILINE)
for path in required_yaml:
    text = path.read_text(encoding="utf-8")
    if not semver.search(text):
        raise SystemExit(f"{path} missing semantic contract version")
    parsed = yaml.safe_load(text)
    if not isinstance(parsed, dict):
        raise SystemExit(f"{path} is not a mapping")

for path in required_json:
    parsed = json.loads(path.read_text(encoding="utf-8"))
    if parsed.get("type") != "object" or not parsed.get("required"):
        raise SystemExit(f"{path} missing strict object contract metadata")

openapi = yaml.safe_load(required_yaml[0].read_text())
for required_path in ["/investigations", "/investigations/{investigationId}", "/investigations/{investigationId}/events", "/investigations/{investigationId}/cancel", "/investigations/{investigationId}/stream", "/ingestion/documents", "/ingestion/images", "/ingestion/audio", "/ingestion/video", "/ingestion/jobs/{jobId}", "/postmortems", "/postmortems/{postmortem_id}", "/postmortems/{postmortem_id}/review", "/postmortems/{postmortem_id}/export"]:
    if required_path not in openapi.get("paths", {}):
        raise SystemExit(f"OpenAPI missing {required_path}")

asyncapi = yaml.safe_load(required_yaml[1].read_text())
for channel in ["investigationCommands", "investigationCancelCommands", "investigationEvents", "ingestionCommands", "ingestionEvents", "postmortemCommands", "postmortemEvents"]:
    if channel not in asyncapi.get("channels", {}):
        raise SystemExit(f"AsyncAPI missing {channel}")
manifest = json.loads(structured_manifest.read_text(encoding="utf-8"))
if not manifest.get("schemas"):
    raise SystemExit("structured-output manifest has no schemas")
for item in manifest["schemas"]:
    path = structured_schema_dir / item["file"]
    parsed = json.loads(path.read_text(encoding="utf-8"))
    if parsed.get("type") != "object" or parsed.get("additionalProperties") is not False:
        raise SystemExit(f"structured schema is not a closed object: {path}")
print("contract files parsed; REST/event/structured contracts present")
