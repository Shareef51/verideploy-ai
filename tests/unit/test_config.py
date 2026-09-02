from verideploy.config import Settings

def test_default_settings_are_safe_for_demo() -> None:
    s=Settings(_env_file=None)
    assert s.demo_mode is True
    assert s.require_human_approval_at_risk_score == 80
    assert s.openai_api_key is None
