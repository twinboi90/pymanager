"""
Registry — tracks which projects use which Python versions.

Stored at ~/.pymanager/registry.json.

Entries are written each time `pymanager pip` runs successfully in a project.
The cleanup command reads this to determine which Python versions are actively
in use vs orphaned (no live projects referencing them).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


REGISTRY_PATH = Path.home() / ".pymanager" / "registry.json"


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


class ProjectEntry:
    """A single registered project."""

    def __init__(self, path: str, python_version: str, last_seen: str):
        self.path = path
        self.python_version = python_version
        self.last_seen = last_seen

    @property
    def exists(self) -> bool:
        """Return True if the project directory still exists on disk."""
        return Path(self.path).exists()

    @property
    def last_seen_dt(self) -> Optional[datetime]:
        try:
            return datetime.fromisoformat(self.last_seen)
        except Exception:
            return None

    def to_dict(self) -> dict:
        return {
            "python_version": self.python_version,
            "last_seen": self.last_seen,
        }


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class Registry:
    """
    Persistent map of project_path → {python_version, last_seen}.

    Thread-safety: uses a simple read-modify-write with no locking.
    Good enough for a developer tool used by one person at a time.
    """

    def __init__(self, path: Path = REGISTRY_PATH):
        self._path = path

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def register(self, project_path: Path, python_version: str) -> None:
        """
        Record that project_path is using python_version.
        Called after every successful `pymanager pip` run.
        """
        data = self._load()
        key = str(project_path.resolve())
        data[key] = {
            "python_version": python_version,
            "last_seen": datetime.now(timezone.utc).isoformat(),
        }
        self._save(data)

    def unregister(self, project_path: Path) -> None:
        """Remove a project from the registry (e.g. after cleanup)."""
        data = self._load()
        key = str(project_path.resolve())
        data.pop(key, None)
        self._save(data)

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def all_projects(self) -> list[ProjectEntry]:
        """Return all registered projects."""
        data = self._load()
        entries = []
        for path, info in data.items():
            entries.append(ProjectEntry(
                path=path,
                python_version=info.get("python_version", "unknown"),
                last_seen=info.get("last_seen", ""),
            ))
        return sorted(entries, key=lambda e: e.last_seen, reverse=True)

    def projects_for_version(self, python_version: str) -> list[ProjectEntry]:
        """
        Return projects that use a given Python version.

        Matches on major.minor so '3.11' matches entries recorded as
        '3.11', '3.11.5', '3.11.10', etc.
        """
        minor = ".".join(python_version.split(".")[:2])
        return [
            e for e in self.all_projects()
            if ".".join(e.python_version.split(".")[:2]) == minor
        ]

    def active_versions(self) -> set[str]:
        """
        Return the set of Python minor versions (e.g. '3.11') that have
        at least one project directory that still exists on disk.
        """
        active = set()
        for entry in self.all_projects():
            if entry.exists:
                minor = ".".join(entry.python_version.split(".")[:2])
                active.add(minor)
        return active

    def prune_stale(self) -> list[str]:
        """
        Remove registry entries whose project directories no longer exist.
        Returns the list of pruned paths.
        """
        data = self._load()
        stale = [path for path in data if not Path(path).exists()]
        for path in stale:
            del data[path]
        if stale:
            self._save(data)
        return stale

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _load(self) -> dict:
        if not self._path.exists():
            return {}
        try:
            return json.loads(self._path.read_text())
        except Exception:
            return {}

    def _save(self, data: dict) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(data, indent=2, sort_keys=True))
