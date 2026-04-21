"""
Shared fixtures for pymanager tests.

Key helpers:
  - make_venv(tmp_path, version)  — build a minimal fake venv directory
  - fake_python(tmp_path, version) — write a tiny shell script that acts
                                     like `python --version`
  - real_venv(tmp_path, version)  — create an actual venv (slower, used
                                     sparingly for integration tests)
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Fake venv builder
#
# SyncChecker inspects the filesystem and runs subprocesses. We build a
# directory that looks exactly like a real venv so tests are fast and
# hermetic — no actual `python -m venv` needed for most cases.
# ---------------------------------------------------------------------------


def _write_fake_python(bin_dir: Path, version: str) -> Path:
    """
    Write a shell script that mimics `python --version` output.
    Returns the path to the script.
    """
    script = bin_dir / "python"
    script.write_text(
        f"#!/bin/sh\n"
        f'if [ "$1" = "--version" ]; then echo "Python {version}"; exit 0; fi\n'
        f'if [ "$1" = "-c" ]; then eval "$2"; exit 0; fi\n'
        f"exit 1\n"
    )
    script.chmod(0o755)
    return script


def _write_fake_pip(bin_dir: Path, pip_version: str = "23.3.1") -> Path:
    """Write a shell script that mimics `pip --version`."""
    script = bin_dir / "pip"
    script.write_text(
        f"#!/bin/sh\n"
        f'if [ "$1" = "--version" ]; then\n'
        f'  echo "pip {pip_version} from /fake/site-packages/pip (python 3.x)"\n'
        f"  exit 0\n"
        f"fi\n"
        f"exit 0\n"
    )
    script.chmod(0o755)
    return script


def _write_pyvenv_cfg(venv_dir: Path, version: str, home: str) -> Path:
    """Write a minimal pyvenv.cfg."""
    cfg = venv_dir / "pyvenv.cfg"
    major_minor = ".".join(version.split(".")[:2])
    cfg.write_text(
        f"home = {home}\n"
        f"include-system-site-packages = false\n"
        f"version = {version}\n"
        f"version_info = {version}.final.0\n"
    )
    return cfg


def _write_metadata(venv_dir: Path, python_version: str) -> Path:
    """Write .pyversion-metadata."""
    import json
    from datetime import datetime, timezone
    meta = venv_dir / ".pyversion-metadata"
    meta.write_text(json.dumps({
        "python_version": python_version,
        "created": datetime.now(timezone.utc).isoformat(),
        "last_used": datetime.now(timezone.utc).isoformat(),
    }, indent=2))
    return meta


@pytest.fixture
def fake_venv(tmp_path):
    """
    Factory fixture — call it to create a minimal fake venv.

    Each call creates a uniquely-named subdirectory so the fixture can be
    called multiple times within the same test without path collisions.

    Usage:
        def test_something(fake_venv):
            venv = fake_venv(version="3.11", home="/usr/bin")
    """
    _counter = {"n": 0}

    def _make(
        version: str = "3.11.5",
        home: str = "/usr/bin",
        include_pip: bool = True,
        include_cfg: bool = True,
        include_metadata: bool = True,
        pip_version: str = "23.3.1",
    ) -> Path:
        _counter["n"] += 1
        venv_dir = tmp_path / f".venv-{_counter['n']}"
        bin_dir = venv_dir / "bin"
        bin_dir.mkdir(parents=True)

        _write_fake_python(bin_dir, version)

        if include_pip:
            _write_fake_pip(bin_dir, pip_version)

        if include_cfg:
            _write_pyvenv_cfg(venv_dir, version, home)

        if include_metadata:
            _write_metadata(venv_dir, version)

        return venv_dir

    return _make


@pytest.fixture
def project_dir(tmp_path):
    """Return a temporary directory that looks like a project root."""
    return tmp_path


@pytest.fixture
def registry_path(tmp_path):
    """Return a temp path for a Registry instance isolated from the real one."""
    return tmp_path / "registry.json"
