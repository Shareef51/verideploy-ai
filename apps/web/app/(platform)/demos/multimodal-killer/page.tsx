import { requireFrontendSession } from "../../../../lib/auth/session";
import { MultimodalKillerDemo } from "../../../../components/demos/multimodal-killer-demo";
export default async function MultimodalKillerPage(){const session=await requireFrontendSession();return <MultimodalKillerDemo session={session}/>;}
