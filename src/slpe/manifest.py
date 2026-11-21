"""Run manifests: capture the parameters, environment and accounting of a run.

A manifest makes a result reproducible and auditable: it records when the data
snapshot was taken, which config/seed produced it, request counts and volume, and
the versions of key dependencies. Manifests are written next to result files.
"""

from __future__ import annotations

import json
import platform
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _pkg_versions() -> dict[str, str]:
    import importlib.metadata as md

    out: dict[str, str] = {}
    for pkg in ("httpx", "pandas", "numpy", "pyarrow", "pyyaml"):
        try:
            out[pkg] = md.version(pkg)
        except md.PackageNotFoundError:
            out[pkg] = "not-installed"
    return out


@dataclass
class RunManifest:
    run_name: str
    params: dict[str, Any] = field(default_factory=dict)
    stats: dict[str, Any] = field(default_factory=dict)
    # ex_ante vs retrospective (see traceability matrix 0.4); characterization is
    # a snapshot of current OpenAlex metadata -> an approximation of history.
    temporal_mode: str = "retrospective_snapshot"
    snapshot_utc: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    python: str = field(default_factory=lambda: sys.version.split()[0])
    platform_: str = field(default_factory=platform.platform)
    versions: dict[str, str] = field(default_factory=_pkg_versions)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_name": self.run_name,
            "snapshot_utc": self.snapshot_utc,
            "temporal_mode": self.temporal_mode,
            "params": self.params,
            "stats": self.stats,
            "python": self.python,
            "platform": self.platform_,
            "versions": self.versions,
            "errors": self.errors,
        }

    def write(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        return path
