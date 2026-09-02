from scripts.supply_chain.core import build_artifact_manifest, dependency_snapshot, release_gate, validate_exception

def test_artifact_manifest_has_sha_and_provenance():
 m=build_artifact_manifest(['package.json']); assert len(m['artifacts'][0]['sha256'])==64; assert m['provenance']['git_commit']

def test_dependency_snapshot_is_explicitly_not_transitive_lock():
 s=dependency_snapshot(); assert s['node']; assert s['python_direct_requirements']; assert 'release still requires' in s['note']

def test_exception_requires_auditable_fields():
 assert 'ticket' in validate_exception({'id':'x','kind':'vulnerability','subject':'a','reason':'r','owner':'o','expires_at':'2026-12-01'})

def test_offline_gate_passes_without_faking_network_material():
 g=release_gate(require_network_material=False); assert g['passed']; assert not g['base_images_digest_pinned']

def test_release_gate_blocks_missing_locks_and_base_digests():
 g=release_gate(require_network_material=True); assert not g['passed']; assert any(f['control']=='SC-LOCK' for f in g['findings']); assert any(f['control']=='SC-IMAGE-DIGEST' for f in g['findings'])
