from __future__ import annotations
import json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; WEB=ROOT/'apps/web'; PLATFORM=WEB/'app/(platform)'
def files(root): return [p for p in root.rglob('*') if p.is_file() and p.suffix in {'.ts','.tsx','.js','.jsx'}]
def text(root): return '\n'.join(p.read_text(errors='ignore') for p in files(root))
app=text(WEB/'app')+text(WEB/'components')+text(WEB/'providers')
platform=text(PLATFORM)
legacy=[name for name in ['approvals','citations','evidence-graph','evidence','incidents','postmortems','release-risk','topology'] if (WEB/'app'/name).exists()]
page_fetch=[str(p.relative_to(ROOT)) for p in files(WEB/'app') if 'fetch(' in p.read_text(errors='ignore')]
mock_terms=[token for token in ['demo tenant','mock data','automated postmortem workflow ready','fake success'] if token in platform.lower()]
package=json.loads((WEB/'package.json').read_text())
checks={
 'protected_layout': all(t in (PLATFORM/'layout.tsx').read_text() for t in ['requireFrontendSession','AppShell','AppProviders']),
 'signed_session': all(t in (WEB/'lib/auth/session.ts').read_text() for t in ['createHmac','timingSafeEqual','FRONTEND_SESSION_SECRET']),
 'production_bypass_disabled': 'FRONTEND_DEV_AUTH_BYPASS=false' in (ROOT/'.env.example').read_text() and 'NODE_ENV !== "production"' in (WEB/'lib/auth/session.ts').read_text(),
 'legacy_unprotected_routes': not legacy,
 'page_fetch_offenders': not page_fetch,
 'browser_internal_refs': '/internal/v1' not in app and 'AI_SERVICE_BASE_URL' not in app and 'ai-service:8000' not in app,
 'hardcoded_product_identity': '11111111-1111-4111-8111-111111111111' not in platform and '22222222-2222-4222-8222-222222222222' not in platform,
 'tanstack_query': '@tanstack/react-query' in package['dependencies'] and 'QueryClientProvider' in (WEB/'providers/query-provider.tsx').read_text(),
 'zod_validation': 'zod' in package['dependencies'] and 'schema.parse(body)' in (WEB/'lib/api/gateway-client.ts').read_text(),
 'tailwind_shadcn': (WEB/'tailwind.config.ts').exists() and (WEB/'components.json').exists() and '@import "tailwindcss"' in (WEB/'app/globals.css').read_text(),
 'realtime_clients': (WEB/'lib/realtime/sse-client.ts').exists() and (WEB/'lib/realtime/websocket-client.ts').exists(),
 'error_boundaries': all(p.exists() for p in [PLATFORM/'error.tsx',PLATFORM/'loading.tsx',WEB/'app/global-error.tsx']),
 'accessibility': 'Skip to content' in (WEB/'components/shell/app-shell.tsx').read_text() and 'prefers-reduced-motion' in (WEB/'app/globals.css').read_text(),
 'playwright_shell': (WEB/'tests/e2e/shell.spec.ts').exists() and '@playwright/test' in package['devDependencies'],
 'mock_only_terms': not mock_terms,
}
result={'valid':all(checks.values()),'checks':checks,'legacy_routes':legacy,'page_fetch_offenders':page_fetch,'mock_terms':mock_terms,'web_version':package['version']}
out=ROOT/'artifacts/frontend-foundation-validation.json';out.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2));raise SystemExit(0 if result['valid'] else 1)
