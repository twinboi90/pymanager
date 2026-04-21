"""
PipWrapper — route pip commands to the correct virtual environment.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


class PipWrapper:
    """Execute pip in the venv that EnvironmentManager prepared."""

    def run(self, venv_path: Path, args: list[str]) -> subprocess.CompletedProcess:
        """
        Run `pip <args>` inside venv_path.

        Streams output live (no capture) so the user sees pip's normal
        progress bars and install messages.

        Returns:
            CompletedProcess with returncode set.
        """
        pip = self._pip_path(venv_path)

        if not pip.exists():
            raise RuntimeError(
                f"pip not found at {pip}. The virtual environment may be corrupted."
            )

        cmd = [str(pip)] + args
        return subprocess.run(cmd)

    def run_captured(self, venv_path: Path, args: list[str]) -> subprocess.CompletedProcess:
        """
        Like run(), but captures stdout/stderr — useful for `pymanager status` checks.
        """
        pip = self._pip_path(venv_path)
        return subprocess.run(
            [str(pip)] + args,
            capture_output=True,
            text=True,
        )

    def _pip_path(self, venv_path: Path) -> Path:
        """Return the pip executable path for the given venv."""
        # Unix
        p = venv_path / "bin" / "pip"
        if p.exists():
            return p
        # Windows
        p = venv_path / "Scripts" / "pip.exe"
        return p
