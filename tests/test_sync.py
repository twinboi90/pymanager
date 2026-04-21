"""
Tests for pymanager.sync — SyncChecker and SyncResult.

Strategy: build minimal fake venv directories using the fake_venv fixture
from conftest.py. This avoids running `python -m venv` for every test,
keeping the suite fast. A handful of tests that need real subprocess
behaviour create an actual venv via the stdlib.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from pyversion.sync import SyncChecker, SyncIssue, SyncResult, FATAL_ISSUES, WARNING_ISSUES


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def check(venv_path: Path, version: str = "3.11") -> SyncResult:
    return SyncChecker().check(venv_path, version)


# ---------------------------------------------------------------------------
# Venv missing
# ---------------------------------------------------------------------------


def test_venv_missing(tmp_path):
    result = check(tmp_path / ".venv")
    assert SyncIssue.VENV_MISSING in result.issues
    assert result.is_missing
    assert not result.is_healthy


def test_venv_missing_returns_early(tmp_path):
    """No other issues should be reported when the venv dir is absent."""
    result = check(tmp_path / ".venv")
    assert result.issues == [SyncIssue.VENV_MISSING]
    assert result.warnings == []


# ---------------------------------------------------------------------------
# Healthy venv
# ---------------------------------------------------------------------------


def test_healthy_venv(fake_venv):
    venv = fake_venv(version="3.11.5", home="/usr/bin")
    result = check(venv, "3.11")
    assert result.is_healthy
    assert result.issues == []
    assert result.actual_version == "3.11.5"


def test_healthy_venv_exact_patch_match(fake_venv):
    venv = fake_venv(version="3.11.5")
    result = check(venv, "3.11.5")
    assert result.is_healthy


def test_healthy_venv_minor_only_requirement(fake_venv):
    """Requiring '3.11' should pass when venv has '3.11.9'."""
    venv = fake_venv(version="3.11.9")
    result = check(venv, "3.11")
    assert result.is_healthy


# ---------------------------------------------------------------------------
# Python binary issues
# ---------------------------------------------------------------------------


def test_python_missing(fake_venv):
    venv = fake_venv()
    (venv / "bin" / "python").unlink()
    result = check(venv)
    assert SyncIssue.PYTHON_MISSING in result.issues
    assert not result.is_healthy


def test_python_broken_symlink(fake_venv):
    venv = fake_venv()
    python = venv / "bin" / "python"
    python.unlink()
    python.symlink_to("/nonexistent/python3.99")
    result = check(venv)
    assert SyncIssue.PYTHON_BROKEN_LINK in result.issues
    assert not result.is_healthy


def test_python_not_executable(fake_venv):
    venv = fake_venv()
    python = venv / "bin" / "python"
    original_mode = python.stat().st_mode
    python.chmod(0o644)  # remove execute bit
    try:
        result = check(venv)
        assert SyncIssue.PYTHON_NOT_EXEC in result.issues
        assert not result.is_healthy
    finally:
        python.chmod(original_mode)  # restore so pytest can clean up tmp_path


# ---------------------------------------------------------------------------
# pip issues
# ---------------------------------------------------------------------------


def test_pip_missing(fake_venv):
    venv = fake_venv()
    (venv / "bin" / "pip").unlink()
    result = check(venv)
    assert SyncIssue.PIP_MISSING in result.issues
    assert not result.is_healthy


def test_pip_broken_symlink(fake_venv):
    venv = fake_venv()
    pip = venv / "bin" / "pip"
    pip.unlink()
    pip.symlink_to("/nonexistent/pip")
    result = check(venv)
    assert SyncIssue.PIP_MISSING in result.issues


def test_pip_outdated_warning(fake_venv):
    venv = fake_venv(pip_version="19.3.1")
    result = check(venv)
    assert SyncIssue.PIP_OUTDATED in result.warnings
    # Should still be healthy (warnings don't block)
    assert result.is_healthy


def test_pip_modern_no_warning(fake_venv):
    venv = fake_venv(pip_version="24.0.0")
    result = check(venv)
    assert SyncIssue.PIP_OUTDATED not in result.warnings


# ---------------------------------------------------------------------------
# pyvenv.cfg issues
# ---------------------------------------------------------------------------


def test_pyvenv_cfg_missing_is_warning(fake_venv):
    venv = fake_venv(include_cfg=False)
    result = check(venv)
    assert SyncIssue.CFG_MISSING in result.warnings
    # Missing cfg is a warning, not fatal
    assert result.is_healthy


def test_home_python_gone(fake_venv):
    venv = fake_venv(home="/nonexistent/python/bin")
    result = check(venv)
    assert SyncIssue.HOME_PYTHON_GONE in result.issues
    assert not result.is_healthy


def test_home_python_exists(fake_venv, tmp_path):
    real_home = tmp_path / "python_home"
    real_home.mkdir()
    venv = fake_venv(home=str(real_home))
    result = check(venv)
    assert SyncIssue.HOME_PYTHON_GONE not in result.issues


# ---------------------------------------------------------------------------
# Version mismatch
# ---------------------------------------------------------------------------


def test_version_mismatch(fake_venv):
    """Venv has Python 3.10, project requires 3.11."""
    venv = fake_venv(version="3.10.12")
    result = check(venv, "3.11")
    assert SyncIssue.VERSION_MISMATCH in result.issues
    assert not result.is_healthy


def test_version_mismatch_major(fake_venv):
    venv = fake_venv(version="2.7.18")
    result = check(venv, "3.11")
    assert SyncIssue.VERSION_MISMATCH in result.issues


def test_version_compatible_patch_ignored(fake_venv):
    """Requiring 3.11 should accept 3.11.0 through 3.11.99."""
    for patch in ("3.11.0", "3.11.5", "3.11.99"):
        venv = fake_venv(version=patch)
        result = check(venv, "3.11")
        assert SyncIssue.VERSION_MISMATCH not in result.issues, f"Failed for {patch}"


def test_cfg_version_mismatch(fake_venv, tmp_path):
    """
    pyvenv.cfg says 3.10 but the python binary reports 3.11.
    This catches manual edits or a corrupted cfg.
    """
    venv = fake_venv(version="3.11.5", home=str(tmp_path))
    # Overwrite cfg with mismatched version
    cfg = venv / "pyvenv.cfg"
    cfg.write_text(
        f"home = {tmp_path}\n"
        f"version = 3.10.12\n"
        f"version_info = 3.10.12.final.0\n"
    )
    result = check(venv, "3.11")
    assert SyncIssue.CFG_VERSION_MISMATCH in result.issues


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------


def test_metadata_missing_is_warning(fake_venv):
    venv = fake_venv(include_metadata=False)
    result = check(venv)
    assert SyncIssue.METADATA_MISSING in result.warnings
    assert result.is_healthy  # warning only


def test_metadata_present_no_warning(fake_venv):
    venv = fake_venv(include_metadata=True)
    result = check(venv)
    assert SyncIssue.METADATA_MISSING not in result.warnings


# ---------------------------------------------------------------------------
# SyncResult properties
# ---------------------------------------------------------------------------


def test_needs_rebuild_on_version_mismatch(fake_venv):
    venv = fake_venv(version="3.10.12")
    result = check(venv, "3.11")
    assert result.needs_rebuild


def test_needs_rebuild_on_broken_symlink(fake_venv):
    venv = fake_venv()
    (venv / "bin" / "python").unlink()
    (venv / "bin" / "python").symlink_to("/nonexistent")
    result = check(venv)
    assert result.needs_rebuild


def test_needs_rebuild_on_pip_missing(fake_venv):
    venv = fake_venv()
    (venv / "bin" / "pip").unlink()
    result = check(venv)
    assert result.needs_rebuild


def test_needs_rebuild_false_for_warnings_only(fake_venv):
    venv = fake_venv(include_metadata=False, pip_version="19.0.0")
    result = check(venv)
    assert not result.needs_rebuild
    assert result.is_healthy  # warnings don't block


def test_describe_returns_messages(fake_venv):
    """describe() should return human-readable strings for every issue."""
    venv = fake_venv(version="3.10.12")
    result = check(venv, "3.11")
    descriptions = result.describe()
    assert len(descriptions) >= 1
    assert all(isinstance(d, str) for d in descriptions)
    assert all(len(d) > 10 for d in descriptions)  # not empty/trivial


def test_describe_includes_warnings(fake_venv):
    venv = fake_venv(include_metadata=False)
    result = check(venv)
    descriptions = result.describe()
    assert any("[warning]" in d for d in descriptions)


# ---------------------------------------------------------------------------
# Issue taxonomy sanity checks
# ---------------------------------------------------------------------------


def test_fatal_and_warning_sets_are_disjoint():
    assert FATAL_ISSUES.isdisjoint(WARNING_ISSUES)


def test_all_issues_are_categorised():
    all_issues = set(SyncIssue)
    categorised = FATAL_ISSUES | WARNING_ISSUES
    assert all_issues == categorised, (
        f"Uncategorised issues: {all_issues - categorised}"
    )
