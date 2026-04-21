"""
EnvironmentManager — create, validate, sync, and track virtual environments.

Default venv location: <project_root>/.venv
Metadata file:         <venv>/.pyversion-metadata  (tracks which Python built it)
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# EnvironmentManager
# ---------------------------------------------------------------------------


class EnvironmentManager:
    """Manage .venv creation, sync-checking, and rebuilding."""

    METADATA_FILE = ".pyversion-metadata"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_or_create_venv(self, python_path: Path, version: str, venv_path: Optional[Path] = None) -> Path:
        """
        Return the path to a valid, correct-version venv, creating it if needed.

        Args:
            python_path:  Path to the Python executable that should own the venv.
            version:      Required Python version string (e.g. '3.11').
            venv_path:    Where to put the venv. Defaults to <cwd>/.venv.

        Returns:
            Path to the venv directory.
        """
        if venv_path is None:
            venv_path = Path.cwd() / ".venv"

        if not venv_path.exists():
            self._create_venv(python_path, venv_path, version)
        else:
            # Validate existing venv is intact (python binary still there)
            if not self._venv_python(venv_path).exists():
                print(f"   ⚠️  Venv at {venv_path} appears broken (missing python). Recreating...")
                shutil.rmtree(venv_path)
                self._create_venv(python_path, venv_path, version)

        return venv_path

    def is_synced(self, venv_path: Path, required_version: str) -> bool:
        """
        Return True if the venv's Python version matches required_version.

        Checks both:
          - The actual Python binary inside the venv
          - The .pyversion-metadata file (fast path)
        """
        # Fast path: check metadata
        meta = self._read_metadata(venv_path)
        if meta:
            stored_ver = meta.get("python_version", "")
            if not self._versions_compatible(stored_ver, required_version):
                return False

        # Authoritative check: run the venv's Python
        venv_python = self._venv_python(venv_path)
        if not venv_python.exists():
            return False

        actual = self._get_version(venv_python)
        if actual is None:
            return False

        return self._versions_compatible(actual, required_version)

    def rebuild_venv(self, venv_path: Path, python_path: Path, version: str) -> None:
        """
        Rebuild the venv with a new Python, preserving installed packages.

        Steps:
          1. Freeze current packages to a temp requirements file.
          2. Remove the old venv.
          3. Create a new venv with the correct Python.
          4. Reinstall packages.
        """
        # Save requirements before destroying the venv
        saved_reqs: Optional[Path] = None
        venv_python = self._venv_python(venv_path)
        if venv_python.exists():
            saved_reqs = venv_path.parent / ".pyversion-saved-reqs.txt"
            result = subprocess.run(
                [str(self._venv_pip(venv_path)), "freeze"],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0 and result.stdout.strip():
                saved_reqs.write_text(result.stdout)
                print(f"   → Saved {len(result.stdout.splitlines())} package(s) from old venv")
            else:
                saved_reqs = None

        # Wipe and recreate
        shutil.rmtree(venv_path)
        self._create_venv(python_path, venv_path, version)

        # Reinstall
        if saved_reqs and saved_reqs.exists():
            reqs_content = saved_reqs.read_text().strip()
            if reqs_content:
                print(f"   → Reinstalling packages into new venv...")
                subprocess.run(
                    [
                        str(self._venv_pip(venv_path)),
                        "install",
                        "--quiet",
                        "-r",
                        str(saved_reqs),
                    ],
                    check=False,
                )
            saved_reqs.unlink(missing_ok=True)

    def update_tracking(self, venv_path: Path, version: str) -> None:
        """Update the metadata file with the last-used timestamp."""
        meta = self._read_metadata(venv_path) or {}
        meta["python_version"] = version
        meta["last_used"] = datetime.now(timezone.utc).isoformat()
        self._write_metadata(venv_path, meta)

    def get_venv_info(self, venv_path: Path) -> dict:
        """
        Return a dict with info about the venv for `pymanager status`.

        Keys: exists, python_version, package_count, path, synced_with
        """
        if not venv_path.exists():
            return {"exists": False, "path": str(venv_path)}

        venv_python = self._venv_python(venv_path)
        actual_version = self._get_version(venv_python) if venv_python.exists() else None
        meta = self._read_metadata(venv_path) or {}

        # Count installed packages (excluding pip, setuptools, wheel)
        pkg_count = self._count_packages(venv_path)

        return {
            "exists": True,
            "path": str(venv_path),
            "python_version": actual_version,
            "tracked_version": meta.get("python_version"),
            "last_used": meta.get("last_used"),
            "package_count": pkg_count,
        }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _create_venv(self, python_path: Path, venv_path: Path, version: str) -> None:
        print(f"   → Creating .venv with Python {version}...")
        result = subprocess.run(
            [str(python_path), "-m", "venv", str(venv_path)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Failed to create virtual environment:\n{result.stderr}"
            )
        self._save_venv_metadata(venv_path, version)

        # Upgrade pip quietly so users don't see the "outdated pip" warning
        pip = self._venv_pip(venv_path)
        subprocess.run(
            [str(pip), "install", "--quiet", "--upgrade", "pip"],
            capture_output=True,
        )

    def _save_venv_metadata(self, venv_path: Path, version: str) -> None:
        meta = {
            "python_version": version,
            "created": datetime.now(timezone.utc).isoformat(),
            "last_used": datetime.now(timezone.utc).isoformat(),
        }
        self._write_metadata(venv_path, meta)

    def _read_metadata(self, venv_path: Path) -> Optional[dict]:
        meta_file = venv_path / self.METADATA_FILE
        if not meta_file.exists():
            return None
        try:
            return json.loads(meta_file.read_text())
        except Exception:
            return None

    def _write_metadata(self, venv_path: Path, data: dict) -> None:
        meta_file = venv_path / self.METADATA_FILE
        meta_file.write_text(json.dumps(data, indent=2))

    def _venv_python(self, venv_path: Path) -> Path:
        """Return path to python binary inside venv (cross-platform)."""
        # Unix
        p = venv_path / "bin" / "python"
        if p.exists():
            return p
        # Windows
        p = venv_path / "Scripts" / "python.exe"
        return p

    def _venv_pip(self, venv_path: Path) -> Path:
        """Return path to pip binary inside venv (cross-platform)."""
        p = venv_path / "bin" / "pip"
        if p.exists():
            return p
        p = venv_path / "Scripts" / "pip.exe"
        return p

    def _get_version(self, python: Path) -> Optional[str]:
        """Run python --version and return the version string."""
        try:
            r = subprocess.run(
                [str(python), "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            text = r.stdout.strip() or r.stderr.strip()
            m = re.search(r"(\d+\.\d+(?:\.\d+)?)", text)
            return m.group(1) if m else None
        except Exception:
            return None

    def _versions_compatible(self, actual: str, required: str) -> bool:
        """
        Return True if 'actual' satisfies 'required'.

        '3.11.5' is compatible with required '3.11' or '3.11.5'.
        '3.12.1' is NOT compatible with required '3.11'.
        """
        req_parts = required.split(".")
        act_parts = actual.split(".")
        # Compare only as many components as required specifies
        return act_parts[: len(req_parts)] == req_parts

    def _count_packages(self, venv_path: Path) -> int:
        """Return number of user-installed packages (excludes pip/setuptools/wheel)."""
        try:
            result = subprocess.run(
                [str(self._venv_pip(venv_path)), "list", "--format=json"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                packages = json.loads(result.stdout)
                exclude = {"pip", "setuptools", "wheel", "distribute"}
                return sum(1 for p in packages if p["name"].lower() not in exclude)
        except Exception:
            pass
        return 0
