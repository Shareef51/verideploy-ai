from __future__ import annotations

import argparse
import json
from pathlib import Path

from verideploy.events import EventEnvelope, OrderedInbox, RetryPolicy, TopicRegistry

ROOT = Path(__file__).resolve().parents[1]


def build(seq: int) -> EventEnvelope:
    return EventEnvelope(event_type="investigation.progressed", tenant_id="synthetic-nexuspay", aggregate_id="inv-500", ordering_key="synthetic-nexuspay:inv-500", sequence_number=seq, payload={"step":seq}, correlation_id="kafka-correlation", producer="kafka-benchmark", schema_family="investigation-event")


def main() -> int:
    parser=argparse.ArgumentParser(); parser.add_argument('--report',default=str(ROOT/'evals/reports/kafka-event-architecture.json')); args=parser.parse_args()
    registry=TopicRegistry.from_mapping(json.loads((ROOT/'config/kafka/topics.json').read_text()))
    topic='verideploy.events.investigation.v1'; registry.assert_family_compatible(topic,'investigation-event','1.0')
    inbox=OrderedInbox(); applied=[]
    events={i:build(i) for i in range(1,101)}
    # deterministic deliberately out-of-order delivery, then duplicates
    order=list(range(2,101,2))+list(range(1,101,2))+list(range(1,101))
    statuses={'applied':0,'buffered':0,'duplicate':0}
    for i in order:
        result=inbox.accept(events[i],lambda item: applied.append(item.sequence_number)); statuses[result.status]=statuses.get(result.status,0)+1
    retry=RetryPolicy(max_attempts=5).decide('base',5,'verideploy.retry.platform.v1','verideploy.dlq.platform.v1')
    report={'case':'duplicate-and-out-of-order-convergence','deliveries':len(order),'unique_events':100,
      'applied_count':len(applied),'high_watermark':inbox.high_watermark('synthetic-nexuspay','inv-500'),
      'applied_in_order':applied==list(range(1,101)),'statuses':statuses,
      'stable_partition':registry.partition(topic,'synthetic-nexuspay:inv-500'),
      'terminal_failures_route_to_dlq':retry.terminal and retry.destination_topic=='verideploy.dlq.platform.v1',
      'passed':len(applied)==100 and applied==list(range(1,101)) and statuses['duplicate']==100 and retry.terminal,
    }
    out=Path(args.report); out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    print(json.dumps(report,indent=2,sort_keys=True)); return 0 if report['passed'] else 1

if __name__=='__main__': raise SystemExit(main())
