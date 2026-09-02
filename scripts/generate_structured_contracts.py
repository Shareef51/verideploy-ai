from pathlib import Path

from verideploy.llm.structured_schemas import build_builtin_structured_registry


def main() -> None:
    registry = build_builtin_structured_registry()
    registry.export_json_schemas(Path("contracts/structured-output"))
    registry.export_typescript(Path("packages/contracts/src/generated/structured-output.ts"))


if __name__ == "__main__":
    main()
