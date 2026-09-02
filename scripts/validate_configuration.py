from pathlib import Path
import json,re,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from verideploy.environment.management import EnvironmentPolicy, apply_environment_overlay, validate_environment
p=EnvironmentPolicy.load(ROOT/"config/environments/manifest.json")
issues=[]
for env in p.environments:
    overlay=apply_environment_overlay({},env=env,config_dir=ROOT/"config/environments")
    if overlay.get("APP_ENV")!=env: issues.append(f"overlay mismatch: {env}")
if p.public_variables & p.secret_variables: issues.append("secret/public variable overlap")
# client scan
for path in (ROOT/"apps/web").rglob("*.ts*"):
    rel=path.relative_to(ROOT).as_posix()
    server_allowed=rel.endswith("lib/config/server.ts") or rel.endswith("lib/auth/session.ts") or rel.endswith("lib/auth/oidc.ts") or "/app/api/" in f"/{rel}/" or "/tests/" in f"/{rel}/"
    if server_allowed: continue
    text=path.read_text(errors="ignore")
    for name in p.secret_variables:
        if f"process.env.{name}" in text or f'process.env["{name}"]' in text or f"process.env['{name}']" in text: issues.append(f"client secret reference: {rel}:{name}")
report={"passed":not issues,"issues":issues,"public_variables":sorted(p.public_variables),"secret_variable_count":len(p.secret_variables),"environments":list(p.environments),"external_secret_schemes":sorted(p.external_secret_schemes)}
out=ROOT/"evals/reports/environment-secrets-configuration.json";out.write_text(json.dumps(report,indent=2)+"\n")
print(json.dumps(report,indent=2));raise SystemExit(0 if not issues else 1)
