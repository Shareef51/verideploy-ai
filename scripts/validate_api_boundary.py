from pathlib import Path
import json,yaml
ROOT=Path(__file__).resolve().parents[1]
web='\n'.join(p.read_text(errors='ignore') for p in (ROOT/'apps/web').rglob('*') if p.suffix in {'.ts','.tsx','.js','.jsx'})
gateway=[p for p in (ROOT/'apps/gateway/src').rglob('*.ts') if p.name!='private-ai.client.ts' and 'fetch(' in p.read_text(errors='ignore')]
contract=yaml.safe_load((ROOT/'contracts/openapi/gateway.yaml').read_text())
result={'valid':not gateway and '/internal/v1/' not in web and 'AI_SERVICE_BASE_URL' not in web and not any('/internal/' in p for p in contract['paths']),'gateway_direct_fetch_offenders':[str(p.relative_to(ROOT)) for p in gateway],'browser_internal_refs':'/internal/v1/' in web,'public_contract_internal_paths':[p for p in contract['paths'] if '/internal/' in p],'public_contract_version':contract['info']['version']}
out=ROOT/'artifacts/api-boundary-validation.json';out.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2));raise SystemExit(0 if result['valid'] else 1)
