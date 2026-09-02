from __future__ import annotations

import asyncio
import json
from pathlib import Path

from verideploy.graphs.parallel import DynamicParallelExecutor, ParallelPlan, ParallelTaskSpec


class Planner:
    def __init__(self, tasks, concurrency):
        self.value = ParallelPlan.deterministic(
            planner_version="validation-planner-v1",
            tasks=tasks,
            requested_concurrency=concurrency,
            minimum_successes=len(tasks),
        )

    async def plan(self, state):
        return self.value


async def run_with(delays: dict[str, float], concurrency: int):
    tasks = [
        ParallelTaskSpec(task_id=name, source=name, node_name=f"{name}_node", deadline_seconds=1.0)
        for name in sorted(delays)
    ]
    workers = {}
    for name, delay in delays.items():
        async def worker(spec, state, name=name, delay=delay):
            await asyncio.sleep(delay)
            return {
                "output": {"source": name},
                "state_update": {
                    "agent_outputs": {name: {"status": "completed"}},
                    "evidence_ids": [f"ev-{name}"],
                },
            }
        workers[name] = worker
    return await DynamicParallelExecutor(
        planner=Planner(tasks, concurrency),
        workers=workers,
        max_concurrency=concurrency,
        max_tasks=8,
        default_deadline_seconds=1.0,
        max_deadline_seconds=1.0,
    ).execute({"investigation_id": "validation"})


async def main() -> int:
    base = {"logs": 0.05, "metrics": 0.05, "traces": 0.05, "visual": 0.05}
    sequential = await run_with(base, 1)
    parallel = await run_with(base, 4)
    reordered = await run_with({"logs": .01, "metrics": .04, "traces": .02, "visual": .03}, 4)
    reordered_2 = await run_with({"logs": .04, "metrics": .01, "traces": .03, "visual": .02}, 4)

    speedup = sequential.wall_time_ms / max(parallel.wall_time_ms, 0.001)
    deterministic = reordered.state_update_sha256 == reordered_2.state_update_sha256
    same_workload_state = parallel.state_update_sha256 == sequential.state_update_sha256
    valid = speedup >= 1.75 and deterministic and same_workload_state
    report = {
        "valid": valid,
        "parallel_version": parallel.parallel_version,
        "task_count": 4,
        "sequential_wall_time_ms": round(sequential.wall_time_ms, 3),
        "parallel_wall_time_ms": round(parallel.wall_time_ms, 3),
        "measured_speedup": round(speedup, 3),
        "required_speedup": 1.75,
        "parallel_state_equals_sequential": same_workload_state,
        "completion_order_state_deterministic": deterministic,
        "state_update_sha256": parallel.state_update_sha256,
        "completed_count": parallel.completed_count,
        "partial_completion": parallel.partial_completion,
    }
    path = Path("artifacts/dynamic-parallel-validation.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
