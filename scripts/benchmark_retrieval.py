from __future__ import annotations

import json

from verideploy.rag.retrieval.benchmark import run_seed_benchmark


def main() -> int:
    results = run_seed_benchmark()
    payload = {name: {"recall_at_5": value.recall_at_5, "mrr": value.mrr} for name, value in results.items()}
    print(json.dumps(payload, indent=2, sort_keys=True))
    hybrid = results["hybrid"]
    best_recall = max(results["keyword"].recall_at_5, results["dense"].recall_at_5)
    best_mrr = max(results["keyword"].mrr, results["dense"].mrr)
    return 0 if hybrid.recall_at_5 >= best_recall and hybrid.mrr >= best_mrr else 1


if __name__ == "__main__":
    raise SystemExit(main())
