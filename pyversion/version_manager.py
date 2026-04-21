"""
VersionManager — detect, install, and locate Python versions.

Install layout:  ~/.pyversion/versions/<version>/bin/python
Download source: python.org precompiled installers (macOS pkg) or
                 python-build-standalone releases (fast, cross-platform).
"""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PYMANAGER_HOME = Path.home() / ".pyversion"
VERSIONS_DIR = PYMANAGER_HOME / "versions"
CACHE_DIR = PYMANAGER_HOME / "cache"

# python-build-standalone (PBS) is the fastest source of precompiled binaries.
# Releases page: https://github.com/astral-sh/python-build-standalone/releases
# We use the "install_only" tarballs — small, no compilation required.
PBS_BASE_URL = (
    "https://github.com/astral-sh/python-build-standalone/releases/download"
    "/20241016"  # pinned release — bump periodically
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _detect_arch() -> str:
    """Return 'x86_64' or 'aarch64' for the current machine."""
    machine = platform.machine().lower()
    if machine in ("arm64", "aarch64"):
        return "aarch64"
    return "x86_64"


def _pbs_asset_name(version: str) -> str:
    """
    Build the python-build-standalone asset filename for this machine.

    Example:
        cpython-3.11.10+20241016-aarch64-apple-darwin-install_only.tar.gz
    """
    arch = _detect_arch()
    system = platform.system().lower()

    if system == "darwin":
        os_tag = "apple-darwin"
    elif system == "linux":
        os_tag = "unknown-linux-gnu"
    else:
        raise RuntimeError(f"Unsupported OS: {system}. Windows support is Phase 3.")

    # PBS uses full patch versions — we need to find the right one.
    # We'll pick the latest patch for the requested minor version.
    patch = _resolve_patch_version(version)
    return f"cpython-{patch}+20241016-{arch}-{os_tag}-install_only.tar.gz"


# Map of minor → latest patch version known in the pinned PBS release.
# Keep this updated alongside PBS_BASE_URL.
_KNOWN_PATCH_VERSIONS: dict[str, str] = {
    "3.9": "3.9.20",
    "3.10": "3.10.15",
    "3.11": "3.11.10",
    "3.12": "3.12.7",
    "3.13": "3.13.0",
}


def _resolve_patch_version(version: str) -> str:
    """
    Given '3.11' or '3.11.5', return a full patch version we know exists in PBS.

    If the user pinned an exact patch (e.g. '3.11.5') we try it as-is; if it
    turns out not to exist in our table we fall back to the latest known patch.
    """
    parts = version.split(".")
    if len(parts) == 3:
        # Full patch specified — use it directly.
        return version

    # Minor-only: look up latest known patch.
    minor_key = ".".join(parts[:2])
    if minor_key not in _KNOWN_PATCH_VERSIONS:
        raise RuntimeError(
            f"Python {version} is not in pymanager's known version table.\n"
            f"Supported versions: {', '.join(sorted(_KNOWN_PATCH_VERSIONS))}\n"
            "Run `pymanager versions` to see what's available."
        )
    return _KNOWN_PATCH_VERSIONS[minor_key]


# ---------------------------------------------------------------------------
# VersionManager
# ---------------------------------------------------------------------------


class VersionManager:
    """Detect project Python requirement; ensure that version is installed."""

    # ------------------------------------------------------------------
    # Detection
    # ------------------------------------------------------------------

    def detect_project_requirement(self) -> Optional[str]:
        """
        Walk standard config files and return the required Python version string,
        or None if no requirement is found.

        Priority:
          1. .python-version  (pyenv / uv convention)
          2. pyproject.toml   [project] requires-python
          3. setup.cfg        python_requires
          4. setup.py         (best-effort regex)
          5. .tool-versions   (asdf / mise convention)
        """
        cwd = Path.cwd()

        # 1. .python-version
        pv = cwd / ".python-version"
        if pv.exists():
            raw = pv.read_text().strip()
            version = self._normalize_version(raw)
            if version:
                return version

        # 2. pyproject.toml
        ppt = cwd / "pyproject.toml"
        if ppt.exists():
            version = self._parse_pyproject_toml(ppt)
            if version:
                return version

        # 3. setup.cfg
        scfg = cwd / "setup.cfg"
        if scfg.exists():
            version = self._parse_setup_cfg(scfg)
            if version:
                return version

        # 4. setup.py
        spy = cwd / "setup.py"
        if spy.exists():
            version = self._parse_setup_py(spy)
            if version:
                return version

        # 5. .tool-versions (asdf / mise)
        tv = cwd / ".tool-versions"
        if tv.exists():
            version = self._parse_tool_versions(tv)
            if version:
                return version

        return None

    def _normalize_version(self, raw: str) -> Optional[str]:
        """Strip 'python', 'cpython-', leading 'v', etc. Return '3.11' or '3.11.5' style."""
        raw = raw.strip()
        # Remove common prefixes
        for prefix in ("cpython-", "python-", "python", "v"):
            if raw.lower().startswith(prefix):
                raw = raw[len(prefix):]
        # Must look like 3.x or 3.x.y
        if re.match(r"^\d+\.\d+(\.\d+)?$", raw):
            return raw
        return None

    def _parse_pyproject_toml(self, path: Path) -> Optional[str]:
        """Extract requires-python from pyproject.toml without adding a toml dep."""
        try:
            if sys.version_info >= (3, 11):
                import tomllib  # stdlib in 3.11+
                data = tomllib.loads(path.read_text())
            else:
                # Fallback: regex parse — good enough for common cases.
                return self._regex_requires_python(path.read_text())

            req = (
                data.get("project", {}).get("requires-python")
                or data.get("tool", {}).get("poetry", {}).get("dependencies", {}).get("python")
            )
            if req:
                return self._specifier_to_version(req)
        except Exception:
            pass
        return None

    def _parse_setup_cfg(self, path: Path) -> Optional[str]:
        text = path.read_text()
        m = re.search(r"python_requires\s*=\s*([^\n]+)", text)
        if m:
            return self._specifier_to_version(m.group(1).strip())
        return None

    def _parse_setup_py(self, path: Path) -> Optional[str]:
        text = path.read_text()
        m = re.search(r"""python_requires\s*=\s*["']([^"']+)["']""", text)
        if m:
            return self._specifier_to_version(m.group(1))
        return None

    def _parse_tool_versions(self, path: Path) -> Optional[str]:
        for line in path.read_text().splitlines():
            if line.lower().startswith("python"):
                parts = line.split()
                if len(parts) >= 2:
                    return self._normalize_version(parts[1])
        return None

    def _regex_requires_python(self, text: str) -> Optional[str]:
        m = re.search(r"""requires-python\s*=\s*["']([^"']+)["']""", text)
        if m:
            return self._specifier_to_version(m.group(1))
        return None

    def _specifier_to_version(self, spec: str) -> Optional[str]:
        """
        Convert a PEP 440 specifier like '>=3.11', '~=3.11.0', '^3.11' to '3.11'.

        We extract the first version number found and return just major.minor.
        """
        spec = spec.strip().strip("\"'")
        m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", spec)
        if m:
            major, minor = m.group(1), m.group(2)
            patch = m.group(3)
            if patch:
                return f"{major}.{minor}.{patch}"
            return f"{major}.{minor}"
        return None

    # ------------------------------------------------------------------
    # System Python fallback
    # ------------------------------------------------------------------

    def get_system_python(self) -> str:
        """Return the running Python's major.minor version string."""
        return f"{sys.version_info.major}.{sys.version_info.minor}"

    # ------------------------------------------------------------------
    # Install / locate
    # ------------------------------------------------------------------

    def is_installed(self, version: str) -> bool:
        """Return True if we have a pymanager-managed Python for this version."""
        return self._managed_python_path(version).exists()

    def get_path(self, version: str) -> Path:
        """
        Return the path to the Python executable for the given version.

        Looks in (priority order):
          1. ~/.pyversion/versions/<version>/bin/python
          2. system: python3.<minor>, python3, python
        """
        managed = self._managed_python_path(version)
        if managed.exists():
            return managed

        # Fall back to system Python if it matches
        for candidate in (f"python{version}", f"python3", "python"):
            found = shutil.which(candidate)
            if found:
                ver = self._get_python_version(Path(found))
                if ver and ver.startswith(self._to_minor(version)):
                    return Path(found)

        raise RuntimeError(
            f"Python {version} not found. Run `pymanager pip install` to trigger auto-install."
        )

    def install(self, version: str) -> Path:
        """
        Download and extract a precompiled Python binary from python-build-standalone.

        Returns the path to the installed python executable.
        """
        patch_version = _resolve_patch_version(version)
        install_dir = VERSIONS_DIR / self._to_minor(version)

        if install_dir.exists():
            python_bin = install_dir / "bin" / "python3"
            if python_bin.exists():
                return python_bin

        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        VERSIONS_DIR.mkdir(parents=True, exist_ok=True)

        asset_name = _pbs_asset_name(version)
        url = f"{PBS_BASE_URL}/{asset_name}"
        cache_file = CACHE_DIR / asset_name

        if not cache_file.exists():
            print(f"   → Downloading Python {patch_version}...")
            print(f"     Source: {url}")
            self._download(url, cache_file)
            print(f"   → Download complete ({cache_file.stat().st_size // 1024 // 1024} MB)")
        else:
            print(f"   → Using cached download: {cache_file.name}")

        print(f"   → Extracting to {install_dir}...")
        self._extract_pbs(cache_file, install_dir)

        python_bin = install_dir / "bin" / "python3"
        if not python_bin.exists():
            # Some PBS builds use 'python' not 'python3'
            python_bin = install_dir / "bin" / "python"

        if not python_bin.exists():
            raise RuntimeError(f"Extraction succeeded but python binary not found in {install_dir}/bin/")

        # Verify it runs
        result = subprocess.run(
            [str(python_bin), "--version"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Installed Python failed version check: {result.stderr}")

        print(f"   → Verified: {result.stdout.strip() or result.stderr.strip()}")
        return python_bin

    def _managed_python_path(self, version: str) -> Path:
        """Return ~/.pyversion/versions/<minor>/bin/python3"""
        minor = self._to_minor(version)
        for name in ("python3", "python"):
            p = VERSIONS_DIR / minor / "bin" / name
            if p.exists():
                return p
        # Return the preferred path even if it doesn't exist (for is_installed check)
        return VERSIONS_DIR / minor / "bin" / "python3"

    def _to_minor(self, version: str) -> str:
        """'3.11.5' → '3.11'"""
        parts = version.split(".")
        return f"{parts[0]}.{parts[1]}"

    def _get_python_version(self, python: Path) -> Optional[str]:
        """Run `python --version` and return the version string, or None."""
        try:
            r = subprocess.run(
                [str(python), "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            text = r.stdout.strip() or r.stderr.strip()
            m = re.search(r"(\d+\.\d+\.\d+)", text)
            if m:
                return m.group(1)
        except Exception:
            pass
        return None

    def _make_ssl_context(self) -> "ssl.SSLContext":
        """
        Build an SSL context that works on macOS with python.org Python installs.

        python.org Python on macOS ships without system certificates — it expects
        you to run 'Install Certificates.command'. We work around this by trying
        certificate sources in order:
          1. Default context (works on Homebrew Python, Linux)
          2. macOS system keychain via `security export`
          3. certifi if installed
          4. Unverified context with a warning (last resort)
        """
        import ssl

        # Try default first — works on Homebrew Python and Linux
        ctx = ssl.create_default_context()
        try:
            # Quick probe: connect to PyPI to test the context
            import urllib.request as _ur
            opener = _ur.build_opener(_ur.HTTPSHandler(context=ctx))
            opener.open("https://pypi.org", timeout=5).close()
            return ctx
        except ssl.SSLError:
            pass
        except Exception:
            # Non-SSL error (network down, timeout) — return default and let
            # the real download fail with a meaningful message
            return ctx

        # macOS system keychain
        if sys.platform == "darwin":
            try:
                import subprocess, tempfile, os
                proc = subprocess.run(
                    [
                        "security", "export", "-t", "certs", "-f", "pemseq",
                        "-k", "/System/Library/Keychains/SystemRootCertificates.keychain",
                    ],
                    capture_output=True,
                    timeout=10,
                )
                if proc.returncode == 0 and proc.stdout:
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".pem") as f:
                        f.write(proc.stdout)
                        tmp = f.name
                    try:
                        ctx = ssl.create_default_context(cafile=tmp)
                        return ctx
                    finally:
                        os.unlink(tmp)
            except Exception:
                pass

        # certifi fallback (installed alongside requests, pip, etc.)
        try:
            import certifi
            return ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            pass

        # Last resort — unverified. Warn the user.
        print(
            "   ⚠  SSL certificate verification disabled. "
            "Run: /Applications/Python*/Install\\ Certificates.command"
        )
        return ssl._create_unverified_context()

    def _download(self, url: str, dest: Path) -> None:
        """Download url → dest with a progress indicator."""
        import ssl

        ssl_ctx = self._make_ssl_context()
        opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=ssl_ctx)
        )

        try:
            with opener.open(url) as response:
                total_size = int(response.headers.get("Content-Length", 0))
                downloaded = 0
                block_size = 65536  # 64 KB chunks

                with open(dest, "wb") as f:
                    while True:
                        chunk = response.read(block_size)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_size > 0:
                            pct = min(int(downloaded * 100 / total_size), 100)
                            bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
                            print(f"\r     [{bar}] {pct}%", end="", flush=True)

            print()  # newline after progress bar
        except Exception as e:
            if dest.exists():
                dest.unlink()
            raise RuntimeError(f"Download failed: {e}\nURL: {url}") from e

    def _extract_pbs(self, tarball: Path, dest: Path) -> None:
        """
        Extract a python-build-standalone tarball.

        PBS tarballs have a top-level 'python/' directory — we strip that
        and place contents directly into dest/.
        """
        dest.mkdir(parents=True, exist_ok=True)
        with tarfile.open(tarball, "r:gz") as tf:
            members = tf.getmembers()
            # Strip the leading 'python/' component
            for member in members:
                parts = Path(member.name).parts
                if len(parts) > 1:
                    member.name = str(Path(*parts[1:]))
                elif len(parts) == 1 and parts[0] == "python":
                    continue
                tf.extract(member, dest, set_attrs=False)

        # Make binaries executable
        bin_dir = dest / "bin"
        if bin_dir.exists():
            for f in bin_dir.iterdir():
                if f.is_file():
                    f.chmod(f.stat().st_mode | 0o111)

    # ------------------------------------------------------------------
    # Info / listing
    # ------------------------------------------------------------------

    def list_installed(self) -> list[dict]:
        """Return list of {version, path, python_version} for managed installs."""
        results = []
        if not VERSIONS_DIR.exists():
            return results
        for d in sorted(VERSIONS_DIR.iterdir()):
            if not d.is_dir():
                continue
            python = d / "bin" / "python3"
            if not python.exists():
                python = d / "bin" / "python"
            actual = self._get_python_version(python) if python.exists() else None
            results.append({
                "label": d.name,
                "path": str(python),
                "actual_version": actual,
            })
        return results
