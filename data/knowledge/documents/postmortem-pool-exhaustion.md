# Synthetic Postmortem: Checkout Connection Pool Exhaustion

Incident INC-SYN-0042 occurred after release rel-2026.08.17-rc3 increased checkout-api worker concurrency without increasing the PostgreSQL client pool. Traffic growth was the trigger; undersized connection capacity relative to concurrency was the root cause. Request queueing increased within three minutes of deployment, while database CPU remained below saturation.

The incident was mitigated by rolling back the application release after human approval. Follow-up work increased pool sizing tests, added a release-risk check comparing worker concurrency against pool capacity, and added a dashboard panel for connection wait time. No database restart was required.

This record is synthetic and exists only to exercise historical-incident retrieval, RCA ranking, critic validation, and postmortem evidence workflows.
