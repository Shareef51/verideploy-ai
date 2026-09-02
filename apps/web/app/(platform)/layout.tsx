import { AppProviders } from "../../providers/app-providers";
import { requireFrontendSession } from "../../lib/auth/session";
import { AppShell } from "../../components/shell/app-shell";
export default async function PlatformLayout({ children }: { children: React.ReactNode }) { const session=await requireFrontendSession(); return <AppProviders session={session}><AppShell session={session}>{children}</AppShell></AppProviders>; }
