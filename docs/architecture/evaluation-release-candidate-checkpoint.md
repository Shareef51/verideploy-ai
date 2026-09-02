# Evaluation and Release-Candidate Checkpoint

Evaluation Release Candidate Checkpoint aggregates the existing production gates into one release-candidate decision. Evaluation, security, load, chaos, accessibility, contracts, and cumulative regression are supported by repository evidence. Browser execution is mandatory in GitHub Actions via Playwright Chromium; local environments without installed browser dependencies are never reported as having executed browser tests.

The release-candidate state `RC_READY_FOR_CI` means all locally verifiable critical gates pass and the mandatory browser CI gate is correctly wired. The CI run must complete before publication or deployment.
