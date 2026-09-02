import { requireFrontendSession } from "../../../lib/auth/session";
import { ProductionDemos } from "../../../components/demos/production-demos";
export default async function DemosPage(){const session=await requireFrontendSession();return <ProductionDemos session={session}/>;}
