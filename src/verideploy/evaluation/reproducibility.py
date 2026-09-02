from __future__ import annotations

import hashlib
import importlib.metadata
import platform
import subprocess
import sys

from verideploy.evaluation.models import ReproducibilityMetadata


def _git_value(*args: str) -> str | None:
    try:
        value = subprocess.check_output(["git", *args], text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    return value or None


def dependency_fingerprint() -> str:
    packages = sorted(f"{d.metadata['Name']}=={d.version}" for d in importlib.metadata.distributions() if d.metadata.get("Name"))
    return hashlib.sha256("\n".join(packages).encode()).hexdigest()


def collect_reproducibility(*, seed: int, environment: str) -> ReproducibilityMetadata:
    commit = _git_value("rev-parse", "HEAD")
    dirty_text = _git_value("status", "--porcelain")
    return ReproducibilityMetadata(
        python_version=sys.version.split()[0],
        platform=platform.platform(),
        git_commit=commit,
        git_dirty=None if commit is None else bool(dirty_text),
        seed=seed,
        dependency_fingerprint=dependency_fingerprint(),
        environment=environment,
    )
