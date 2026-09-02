from pathlib import Path
import json
from verideploy.release_handoff import validate_final_release
ROOT=Path(__file__).resolve().parents[2]

def test_final_release_gate_passes():
    r=validate_final_release(ROOT); assert r['gate']=='pass', r['findings']; assert r['versioned_images']==4

def test_versioned_images_and_helm_release_are_aligned():
    cfg=json.loads((ROOT/'config/release/final-release.json').read_text())
    assert {i['component'] for i in cfg['images']}=={'web','gateway','ai','worker'}
    assert all(i['ref'].endswith(':0.86.0') for i in cfg['images'])
    values=(ROOT/'infrastructure/helm/verideploy/values-production.yaml').read_text(); assert values.count('0.86.0')>=5

def test_terraform_is_real_planable_baseline_not_placeholder():
    tf=(ROOT/'infrastructure/terraform/main.tf').read_text()
    assert 'resource "helm_release" "verideploy"' in tf and 'resource "kubernetes_namespace_v1" "verideploy"' in tf
    assert (ROOT/'infrastructure/terraform/versions.tf').stat().st_size>100
    assert not (ROOT/'infrastructure/terraform/.gitkeep').exists()

def test_release_workflow_signs_and_fails_closed():
    w=(ROOT/'.github/workflows/release.yml').read_text()
    for token in ['docker buildx build','--provenance=true','--sbom=true','cosign sign --yes','cosign verify','terraform plan','cosign sign-blob']: assert token in w
    assert '|| true' not in w

def test_deploy_and_rollback_require_human_approval_and_seed_uses_public_api():
    deploy=(ROOT/'scripts/release/deploy.sh').read_text(); rollback=(ROOT/'scripts/release/rollback.sh').read_text(); seed=(ROOT/'scripts/release/seed_demo.sh').read_text()
    assert 'VERIDEPLOY_RELEASE_APPROVED' in deploy and 'VERIDEPLOY_ROLLBACK_APPROVED' in rollback
    assert '/api/v1/demos/multimodal-killer/run' in seed and 'insert into' not in seed.lower()
