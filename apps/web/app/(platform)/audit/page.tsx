import { requireFrontendSession } from "../../../lib/auth/session";import { AuditViewer } from "../../../components/audit/audit-viewer";
export default async function AuditPage(){const session=await requireFrontendSession();return <AuditViewer session={session}/>;}
