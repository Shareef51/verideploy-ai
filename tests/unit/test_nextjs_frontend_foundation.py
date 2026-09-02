from __future__ import annotations
import json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
WEB=ROOT/'apps/web'
PLATFORM=WEB/'app/(platform)'

def _source(root: Path, suffixes={'.ts','.tsx'}):
    return '\n'.join(p.read_text(errors='ignore') for p in root.rglob('*') if p.is_file() and p.suffix in suffixes)

def test_version_and_frontend_dependencies():
    assert tuple(map(int,(ROOT/'src/verideploy/__init__.py').read_text().split('\"')[1].split('.'))) >= (0,44,0)
    package=json.loads((WEB/'package.json').read_text())
    assert tuple(map(int,package['version'].split('.'))) >= (0,44,0)
    for dep in ['@tanstack/react-query','zod','clsx','tailwind-merge','lucide-react']:
        assert dep in package['dependencies']
    for dep in ['tailwindcss','@tailwindcss/postcss','@playwright/test']:
        assert dep in package['devDependencies']

def test_authenticated_app_router_layout_uses_signed_server_session():
    layout=(PLATFORM/'layout.tsx').read_text(); auth=(WEB/'lib/auth/session.ts').read_text()
    assert 'requireFrontendSession' in layout and 'AppShell' in layout and 'AppProviders' in layout
    for token in ['createHmac','timingSafeEqual','verideploy_session','FRONTEND_SESSION_SECRET','redirect("/sign-in")']:
        assert token in auth
    assert 'bypass && process.env.NODE_ENV !== "production"' in auth

def test_all_product_routes_live_under_protected_route_group_and_no_legacy_directories():
    expected=['approvals','citations','evidence-graph','evidence','incidents','postmortems','release-risk','topology']
    for name in expected:
        assert (PLATFORM/name).exists(), name
        assert not (WEB/'app'/name).exists(), f'legacy unprotected route remains: {name}'
    assert (PLATFORM/'page.tsx').exists()

def test_browser_network_is_centralized_gateway_only_and_has_no_demo_identity():
    app_source=_source(WEB/'app')+_source(WEB/'components')+_source(WEB/'providers')
    assert 'fetch(' not in app_source
    assert '/internal/v1' not in app_source
    assert 'AI_SERVICE_BASE_URL' not in app_source and 'ai-service:8000' not in app_source
    platform=_source(PLATFORM)
    assert '11111111-1111-4111-8111-111111111111' not in platform
    assert '22222222-2222-4222-8222-222222222222' not in platform
    client=(WEB/'lib/api/gateway-client.ts').read_text()
    assert 'fetch(' in client and 'x-tenant-id' in client and 'x-user-id' in client and 'x-correlation-id' in client
    assert '/internal\\/v1' in client and ':8000' in client

def test_tanstack_query_and_zod_are_used_in_live_product_screens():
    provider=(WEB/'providers/query-provider.tsx').read_text()
    assert 'QueryClientProvider' in provider and 'staleTime' in provider
    combined='\n'.join((PLATFORM/p/'page.tsx').read_text() for p in ['approvals','topology','evidence-graph'])
    assert 'useQuery' in combined and 'gatewayFetch' in combined
    schemas=_source(WEB/'lib/schemas', {'.ts'})
    assert 'z.object' in schemas and '.parse(' not in schemas  # schemas are declarations; gateway client performs parse
    assert 'schema.parse(body)' in (WEB/'lib/api/gateway-client.ts').read_text()

def test_shadcn_tailwind_design_tokens_and_responsive_grid_foundation():
    assert (WEB/'components.json').exists()
    assert (WEB/'tailwind.config.ts').exists() and (WEB/'postcss.config.mjs').exists()
    css=(WEB/'app/globals.css').read_text()
    for token in ['--background','--foreground','--card','--border','--primary','--radius-xl','@import "tailwindcss"']:
        assert token in css
    overview=(PLATFORM/'page.tsx').read_text()
    assert 'grid-cols-1' in overview and 'md:grid-cols-2' in overview and 'xl:grid-cols-3' in overview
    for component in ['button.tsx','card.tsx','badge.tsx','state-panel.tsx']:
        assert (WEB/'components/ui'/component).exists()

def test_realtime_clients_are_gateway_scoped():
    sse=(WEB/'lib/realtime/sse-client.ts').read_text(); ws=(WEB/'lib/realtime/websocket-client.ts').read_text()
    assert 'gatewayRequest' in sse and 'text/event-stream' in sse
    assert 'WebSocket' in ws and 'gatewayOriginForRealtime' in ws
    assert '/internal/v1' not in sse+ws and 'ai-service:8000' not in sse+ws

def test_error_loading_empty_and_global_boundaries_are_accessible():
    for path in [PLATFORM/'loading.tsx',PLATFORM/'error.tsx',PLATFORM/'not-found.tsx',WEB/'app/global-error.tsx']:
        assert path.exists()
    shell=(WEB/'components/shell/app-shell.tsx').read_text()
    assert 'Skip to content' in shell and 'aria-label="Primary navigation"' in shell and 'id="main-content"' in shell
    css=(WEB/'app/globals.css').read_text()
    assert ':focus-visible' in css and 'prefers-reduced-motion' in css

def test_next_production_config_has_standalone_and_security_headers():
    source=(WEB/'next.config.ts').read_text()
    for token in ['output: "standalone"','poweredByHeader: false','reactStrictMode: true','X-Content-Type-Options','X-Frame-Options','Permissions-Policy']:
        assert token in source

def test_playwright_shell_tests_cover_auth_and_no_mock_path():
    spec=(WEB/'tests/e2e/shell.spec.ts').read_text(); config=(WEB/'playwright.config.ts').read_text()
    assert 'unauthenticated workspace redirects to sign-in' in spec
    assert 'keyboard-accessible navigation' in spec
    assert 'mock banner or legacy route' in spec
    assert 'chromium' in config and 'mobile' in config

def test_frontend_env_contract_disables_production_bypass_by_default():
    env=(ROOT/'.env.example').read_text()
    assert 'FRONTEND_SESSION_SECRET=' in env
    assert 'FRONTEND_DEV_AUTH_BYPASS=false' in env
    assert 'NEXT_PUBLIC_GATEWAY_URL=http://localhost:4000' in env

def test_no_mock_only_or_build_status_copy_in_protected_product_source():
    source=_source(PLATFORM).lower()
    forbidden=['demo tenant','mock data','automated postmortem workflow ready','fake success']
    assert not any(token in source for token in forbidden)
