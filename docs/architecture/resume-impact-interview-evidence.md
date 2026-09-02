# Resume Impact and Interview Evidence

Resume Impact Interview Evidence converts the AI Engineering Job Description Mapping evidence graph into recruiter-facing material without relaxing evidence standards. `config/career/resume-interview.json` contains the canonical metric registry, resume templates, STAR stories, trade-offs, cost/latency decisions, lessons, and recruiter questions.

Numeric facts are not typed directly into resume or result templates. They are rendered from JSON reports produced by earlier measured checkpoints. Each metric carries a qualifier so deterministic in-process latency, synthetic demo budgets, estimated model cost, and CI-only browser execution cannot be misrepresented as measured production behavior.

`scripts/validate_resume_interview.py` fails when a metric source/path is missing, a template contains undeclared numeric literals, evidence files are absent, or the interview package is incomplete. It writes the machine-readable gate report and the recruiter-facing `docs/career/resume-impact-and-interview-evidence.md` from the same source.
