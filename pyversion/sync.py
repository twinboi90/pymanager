"""
SyncChecker — comprehensive venv health and sync validation.

Detects every way a venv can fall out of sync with the project's Python
requirement, returning a structured SyncResult so callers can decide
what to do (report, auto-fix, or abort).
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Issue taxonomy
# ---------------------------------------------------------------------------


class SyncIssue(str, Enum):
    """Every way a venv can be broken or out of sync."""

    # Structural problems — venv is damaged
    VENV_MISSING         = "venv_missing"           # .venv dir doesn't exist
    PYTHON_MISSING       = "python_missing"          # bin/python not present
    PYTHON_BROKEN_LINK   = "python_broken_link"      # symlink → missing target
    PYTHON_NOT_EXEC      = "python_not_executable"   # file exists but not +x
    PIP_MISSING          = "pip_missing"             # bin/pip not present
    CFG_MISSING          = "pyvenv_cfg_missing"      # pyvenv.cfg absent

    # Version problems — venv exists but wrong Python
    VERSION_MISMATCH     = "version_mismatch"        # venv Python ≠ requirement
    CFG_VERSION_MISMATCH = "cfg_version_mismatch"    # pyvenv.cfg disagrees
    HOME_PYTHON_GONE     = "home_python_gone"        # Python that built venv is gone

    # Soft warnings — venv works but something is off
    PIP_OUTDATED         = "pip_outdated"            # pip is very old (< 22)
    METADATA_MISSING     = "metadata_missing"        # no .pyversion-metadata


# Group issues by severity
FATAL_ISSUES = {
    SyncIssue.VENV_MISSING,
    SyncIssue.PYTHON_MISSING,
    SyncIssue.PYTHON_BROKEN_LINK,
    SyncIssue.PYTHON_NOT_EXEC,
    SyncIssue.PIP_MISSING,
    SyncIssue.VERSION_MISMATCH,
    SyncIssue.CFG_VERSION_MISMATCH,
    SyncIssue.HOME_PYTHON_GONE,
}

WARNING_ISSUES = {
    SyncIssue.CFG_MISSING,
    SyncIssue.PIP_OUTDATED,
    SyncIssue.METADATA_MISSING,
}


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class SyncResult:
    """Full health report for a venv."""

    venv_path: Path
    required_version: str

    issues: list[SyncIssue] = field(default_factory=list)
    warnings: list[SyncIssue] = field(default_factory=list)

    # Populated during checks
    actual_version: Optional[str] = None
    cfg_version: Optional[str] = None
    home_python: Optional[str] = None   # from pyvenv.cfg
    pip_version: Optional[str] = None

    @property
    def is_healthy(self) -> bool:
        """True if venv exists and all fatal issues are clear."""
        return not self.issues

    @property
    def needs_rebuild(self) -> bool:
        """True if the venv must be rebuilt (not just repaired in-place)."""
        rebuild_triggers = {
            SyncIssue.VERSION_MISMATCH,
            SyncIssue.CFG_VERSION_MISMATCH,
            SyncIssue.HOME_PYTHON_GONE,
            SyncIssue.PYTHON_BROKEN_LINK,
            SyncIssue.PYTHON_MISSING,
            SyncIssue.PIP_MISSING,
        }
        return bool(set(self.issues) & rebuild_triggers)

    @property
    def is_missing(self) -> bool:
        return SyncIssue.VENV_MISSING in self.issues

    def describe(self) -> list[str]:
        """Human-readable description of each issue."""
        messages = []
        for issue in self.issues:
            messages.append(_ISSUE_MESSAGES.get(issue, str(issue)))
        for warn in self.warnings:
            messages.append(f"[warning] {_ISSUE_MESSAGES.get(warn, str(warn))}")
        return messages


_ISSUE_MESSAGES: dict[SyncIssue, str] = {
    SyncIssue.VENV_MISSING:         "Virtual environment does not exist",
    SyncIssue.PYTHON_MISSING:       "Python binary missing from venv (bin/python)",
    SyncIssue.PYTHON_BROKEN_LINK:   "Python binary is a broken symlink — original Python was moved or deleted",
    SyncIssue.PYTHON_NOT_EXEC:      "Python binary exists but is not executable",
    SyncIssue.PIP_MISSING:          "pip binary missing from venv (bin/pip)",
    SyncIssue.CFG_MISSING:          "pyvenv.cfg is missing — venv may be corrupted",
    SyncIssue.VERSION_MISMATCH:     "Venv Python version does not match project requirement",
    SyncIssue.CFG_VERSION_MISMATCH: "pyvenv.cfg records a different Python version than the binary reports",
    SyncIssue.HOME_PYTHON_GONE:     "The Python that created this venv no longer exists at its original path",
    SyncIssue.PIP_OUTDATED:         "pip is outdated (< 22.0) — consider upgrading",
    SyncIssue.METADATA_MISSING:     "pymanager metadata file missing — run any pymanager pip command to regenerate",
}


# ---------------------------------------------------------------------------
# SyncChecker
# ---------------------------------------------------------------------------


class SyncChecker:
    """
    Run all sync checks against a venv and return a SyncResult.

    Usage:
        checker = SyncChecker()
        result = checker.check(venv_path, required_version="3.11")
        if not result.is_healthy:
            for msg in result.describe():
                print(msg)
    """

    def check(self, venv_path: Path, required_version: str) -> SyncResult:
        result = SyncResult(venv_path=venv_path, required_version=required_version)

        # ── 1. Venv directory itself ──────────────────────────────────
        if not venv_path.exists():
            result.issues.append(SyncIssue.VENV_MISSING)
            return result  # nothing else to check

        # ── 2. Python binary ─────────────────────────────────────────
        python = self._venv_python(venv_path)
        python_ok = self._check_python_binary(python, result)

        # ── 3. pip binary ────────────────────────────────────────────
        pip = self._venv_pip(venv_path)
        self._check_pip_binary(pip, result)

        # ── 4. pyvenv.cfg ────────────────────────────────────────────
        self._check_pyvenv_cfg(venv_path, result)

        # ── 5. Version match ─────────────────────────────────────────
        if python_ok:
            self._check_version(python, required_version, result)

        # ── 6. pymanager metadata ────────────────────────────────────
        meta = venv_path / ".pyversion-metadata"
        if not meta.exists():
            result.warnings.append(SyncIssue.METADATA_MISSING)

        return result

    # ------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------

    def _check_python_binary(self, python: Path, result: SyncResult) -> bool:
        """Check the python binary. Returns True if it's usable."""
        if not python.exists() and not python.is_symlink():
            result.issues.append(SyncIssue.PYTHON_MISSING)
            return False

        if python.is_symlink() and not python.resolve().exists():
            result.issues.append(SyncIssue.PYTHON_BROKEN_LINK)
            return False

        if not os.access(python, os.X_OK):
            result.issues.append(SyncIssue.PYTHON_NOT_EXEC)
            return False

        return True

    def _check_pip_binary(self, pip: Path, result: SyncResult) -> None:
        if not pip.exists() and not pip.is_symlink():
            result.issues.append(SyncIssue.PIP_MISSING)
            return

        if pip.is_symlink() and not pip.resolve().exists():
            result.issues.append(SyncIssue.PIP_MISSING)
            return

        # Check pip version (soft warning if very old)
        try:
            r = subprocess.run(
                [str(pip), "--version"],
                capture_output=True, text=True, timeout=5
            )
            m = re.search(r"pip (\d+)\.", r.stdout)
            if m:
                result.pip_version = f"pip {m.group(1)}.x"
                major = int(m.group(1))
                if major < 22:
                    result.warnings.append(SyncIssue.PIP_OUTDATED)
        except Exception:
            pass

    def _check_pyvenv_cfg(self, venv_path: Path, result: SyncResult) -> None:
        cfg_path = venv_path / "pyvenv.cfg"
        if not cfg_path.exists():
            result.warnings.append(SyncIssue.CFG_MISSING)
            return

        cfg = self._parse_pyvenv_cfg(cfg_path)

        # Extract the Python version from cfg
        version_str = cfg.get("version") or cfg.get("version_info", "")
        if version_str:
            m = re.search(r"(\d+\.\d+(?:\.\d+)?)", version_str)
            if m:
                result.cfg_version = m.group(1)

        # Extract the home path (where the base Python lives)
        home = cfg.get("home", "")
        if home:
            result.home_python = home
            home_path = Path(home)
            if not home_path.exists():
                result.issues.append(SyncIssue.HOME_PYTHON_GONE)

    def _check_version(self, python: Path, required: str, result: SyncResult) -> None:
        """Run the venv Python and verify its version matches required."""
        actual = self._get_python_version(python)
        if actual is None:
            result.issues.append(SyncIssue.VERSION_MISMATCH)
            return

        result.actual_version = actual

        if not self._versions_compatible(actual, required):
            result.issues.append(SyncIssue.VERSION_MISMATCH)

        # Cross-check with pyvenv.cfg version if available
        if result.cfg_version:
            cfg_minor = ".".join(result.cfg_version.split(".")[:2])
            actual_minor = ".".join(actual.split(".")[:2])
            if cfg_minor != actual_minor:
                result.issues.append(SyncIssue.CFG_VERSION_MISMATCH)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _venv_python(self, venv_path: Path) -> Path:
        for name in ("python", "python3"):
            p = venv_path / "bin" / name
            if p.exists() or p.is_symlink():
                return p
        return venv_path / "Scripts" / "python.exe"

    def _venv_pip(self, venv_path: Path) -> Path:
        p = venv_path / "bin" / "pip"
        if p.exists() or p.is_symlink():
            return p
        return venv_path / "Scripts" / "pip.exe"

    def _parse_pyvenv_cfg(self, cfg_path: Path) -> dict[str, str]:
        """Parse pyvenv.cfg key = value format (no section headers)."""
        result: dict[str, str] = {}
        try:
            for line in cfg_path.read_text().splitlines():
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    key, _, val = line.partition("=")
                    result[key.strip().lower()] = val.strip()
        except Exception:
            pass
        return result

    def _get_python_version(self, python: Path) -> Optional[str]:
        try:
            r = subprocess.run(
                [str(python), "--version"],
                capture_output=True, text=True, timeout=5
            )
            text = r.stdout.strip() or r.stderr.strip()
            m = re.search(r"(\d+\.\d+(?:\.\d+)?)", text)
            return m.group(1) if m else None
        except Exception:
            return None

    def _versions_compatible(self, actual: str, required: str) -> bool:
        req_parts = required.split(".")
        act_parts = actual.split(".")
        return act_parts[: len(req_parts)] == req_parts
