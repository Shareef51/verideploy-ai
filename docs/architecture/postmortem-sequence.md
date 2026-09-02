# Postmortem Sequence

```text
Reviewed completed investigation
 |
 v
Next.js postmortem shell
 |
 v
NestJS POST /api/v1/postmortems
 |
 +-- deterministic postmortem id + idempotency key
 v
Kafka verideploy.commands.postmortem.v1
 |
 v
Python postmortem worker
 |
 +-- verify tenant + COMPLETED source investigation
 +-- validate reviewed evidence closure
 +-- persist source investigation version
 v
Postmortem PENDING_APPROVAL
 |
 v
NestJS review endpoint -> private FastAPI -> optimistic version check
 |
 +--> APPROVED -> final Markdown/JSON export enabled
 +--> CHANGES_REQUESTED
 +--> REJECTED
```
