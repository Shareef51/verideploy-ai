from verideploy.testing.strategy import shard_for

def test_sharding_is_deterministic_and_balanced_enough():
    counts=[0,0,0,0]
    for i in range(1000): counts[shard_for(f"tests/test_{i}.py::test_case",4)]+=1
    assert sum(counts)==1000
    assert min(counts)>200 and max(counts)<300
