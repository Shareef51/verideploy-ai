from __future__ import annotations
import importlib.util, json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]

def load(name:str,path:Path):
    spec=importlib.util.spec_from_file_location(name,path); mod=importlib.util.module_from_spec(spec); assert spec and spec.loader; spec.loader.exec_module(mod); return mod

def test_release_version_is_consistent():
    m=load('p67',ROOT/'scripts/validate_monorepo.py'); assert m.validate()==[]

def test_generated_contract_manifest_is_current():
    m=load('p67b',ROOT/'scripts/validate_monorepo.py'); assert json.loads((ROOT/'config/monorepo/integrity.json').read_text())==m.manifest()

def test_codeowners_cover_workspace_owners():
    policy=json.loads((ROOT/'config/monorepo/policy.json').read_text()); code=(ROOT/'.github/CODEOWNERS').read_text(); assert all(x['owner'] in code for x in policy['workspace_packages'].values())

def test_incremental_ci_routes_frontend_change_without_python():
    m=load('aff',ROOT/'scripts/ci/affected.py'); got=m.compute(['apps/web/app/page.tsx']); assert got['web'] and not got['python'] and not got['kubernetes']

def test_global_monorepo_policy_change_invalidates_all_groups():
    m=load('aff2',ROOT/'scripts/ci/affected.py'); got=m.compute(['config/monorepo/policy.json']); assert all(got.values())
