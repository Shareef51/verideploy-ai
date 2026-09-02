from verideploy.llm.redaction import redact_mapping, redact_text


def test_redacts_openai_style_key_without_logging_value() -> None:
    raw = "Authorization: Bearer " + "sk-" + ("a" * 32)
    clean = redact_text(raw)
    assert ("a" * 24) not in clean
    assert "[REDACTED]" in clean


def test_redacts_sensitive_mapping_keys_recursively() -> None:
    result = redact_mapping({"api_key": "secret", "nested": {"token": "abc", "safe": "ok"}})
    assert result["api_key"] == "[REDACTED]"
    assert result["nested"]["token"] == "[REDACTED]"
    assert result["nested"]["safe"] == "ok"
