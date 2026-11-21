"""Run manifests: capture the parameters, environment and accounting of a run.

A manifest makes a result reproducible and auditable: it records when the data
snapshot was taken, which config/seed produced it, request counts and volume, and
the versions of key dependencies. Manifests are written next to result files.
"""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _pkg_versions() -> dict[str, str]:
    import importlib.metadata as md

    out: dict[str, str] = {}
    for pkg in ("httpx", "pandas", "numpy", "pyarrow", "pyyaml", "matplotlib",
                "python-dotenv", "scientific-link-prediction-experiments"):
        try:
            out[pkg] = md.version(pkg)
        except md.PackageNotFoundError:
            out[pkg] = "not-installed"
    return out


def _git_commit() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5
        )
        return out.stdout.strip() or None if out.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def file_sha256(path: str | Path) -> str | None:
    """SHA-256 of a file's bytes, or None if it doesn't exist."""
    p = Path(path)
    if not p.exists():
        return None
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class RunManifest:
    run_name: str
    params: dict[str, Any] = field(default_factory=dict)
    stats: dict[str, Any] = field(default_factory=dict)
    # ex_ante vs retrospective (see traceability matrix 0.4); characterization is
    # a snapshot of current OpenAlex metadata -> an approximation of history.
    temporal_mode: str = "retrospective_snapshot"
    run_utc: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    python: str = field(default_factory=lambda: sys.version.split()[0])
    platform_: str = field(default_factory=platform.platform)
    versions: dict[str, str] = field(default_factory=_pkg_versions)
    git_commit: str | None = field(default_factory=_git_commit)
    config_sha256: str | None = None
    artifact_hashes: dict[str, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def hash_artifacts(self, paths: dict[str, str | Path]) -> None:
        """Record SHA-256 of produced artifacts (name -> path)."""
        for name, path in paths.items():
            digest = file_sha256(path)
            if digest:
                self.artifact_hashes[name] = digest

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_name": self.run_name,
            # run_utc is when the CODE ran; it is NOT a frozen snapshot of the
            # OpenAlex database. Per-response provenance lives in the cache envelopes.
            "run_utc": self.run_utc,
            "temporal_mode": self.temporal_mode,
            "params": self.params,
            "stats": self.stats,
            "python": self.python,
            "platform": self.platform_,
            "versions": self.versions,
            "git_commit": self.git_commit,
            "config_sha256": self.config_sha256,
            "artifact_hashes": self.artifact_hashes,
            "errors": self.errors,
        }

    def write(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        return path
