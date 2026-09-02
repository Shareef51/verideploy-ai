import Link from "next/link";
import { Card, CardContent, CardHeader } from "../../components/ui/card";
const capabilities=[
 {href:"/demos",eyebrow:"Recruiter demo",title:"Five Production Demos",text:"Run seeded synthetic release-risk, RCA and multimodal scenarios through real services."},
 {href:"/release-risk",eyebrow:"Release assurance",title:"Release Risk",text:"Assess change risk through the audited NestJS → AI-service boundary."},
 {href:"/incidents",eyebrow:"Incident intelligence",title:"Investigations",text:"Launch durable, replayable investigations with live event reconciliation."},
 {href:"/agent-execution",eyebrow:"Agent observability",title:"Agent Execution",text:"Inspect persisted node, tool, model, retry and failure telemetry in real time."},
 {href:"/evidence",eyebrow:"Evidence",title:"Multimodal Intake",text:"Ingest documents, images, audio and video through verified gateway workflows."},
 {href:"/approvals",eyebrow:"Governance",title:"Approval Queue",text:"Review high-risk actions through durable signed human decisions."},
 {href:"/topology",eyebrow:"Architecture",title:"Service Topology",text:"Explore the tenant-isolated NexusPay service and dependency model."},
 {href:"/evidence-graph",eyebrow:"Lineage",title:"Evidence Graph",text:"Trace PR-to-service-to-incident-to-cause evidence relationships."},
];
export default function WorkspaceOverview(){return <div className="page"><section className="workspace-hero"><p className="eyebrow">VeriDeploy AI</p><h1>Release assurance and incident intelligence, grounded in evidence.</h1><p className="lede">A production workspace for release risk, durable investigations, multimodal evidence, human review, and citation-safe engineering decisions.</p></section><section className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3" aria-label="Workspace capabilities">{capabilities.map(item=><Link className="capability-link" href={item.href} key={item.href}><Card><CardHeader><p className="eyebrow">{item.eyebrow}</p><h2>{item.title}</h2></CardHeader><CardContent><p>{item.text}</p><span aria-hidden="true">Open workspace →</span></CardContent></Card></Link>)}</section></div>}
