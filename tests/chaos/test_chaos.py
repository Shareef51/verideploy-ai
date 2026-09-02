from verideploy.realtime.flow import reconcile_event_stream

def test_disconnect_duplicate_and_reorder_converges_after_replay():
    first=reconcile_event_stream([{"sequence_number":3},{"sequence_number":1},{"sequence_number":1}],authoritative_high_watermark=3)
    assert not first.converged and first.missing_sequences==(2,)
    recovered=reconcile_event_stream([{"sequence_number":3},{"sequence_number":1},{"sequence_number":2},{"sequence_number":1}],authoritative_high_watermark=3)
    assert recovered.converged and recovered.applied_sequences==(1,2,3)
