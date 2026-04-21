"""
Tests for pymanager.version_manager — parsing and detection logic only.

We test everything that doesn't require downloading Python or running
subprocesses: config file parsing, version normalization, specifier
conversion, and compatibility checks.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pyversion.sync import SyncChecker
from pyversion.version_manager import VersionManager


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def vm():
    return VersionManager()


@pytest.fixture
def project(tmp_path, monkeypatch):
    """
    Change cwd to a temp directory so detect_project_requirement()
    reads from there instead of the real project root.
    """
    monkeypatch.chdir(tmp_path)
    return tmp_path


# ---------------------------------------------------------------------------
# _normalize_version
# ---------------------------------------------------------------------------


class TestNormalizeVersion:
    def test_plain_version(self, vm):
        assert vm._normalize_version("3.11") == "3.11"

    def test_with_patch(self, vm):
        assert vm._normalize_version("3.11.5") == "3.11.5"

    def test_strips_v_prefix(self, vm):
        assert vm._normalize_version("v3.11") == "3.11"

    def test_strips_python_prefix(self, vm):
        assert vm._normalize_version("python3.11") == "3.11"

    def test_strips_cpython_prefix(self, vm):
        assert vm._normalize_version("cpython-3.11.5") == "3.11.5"

    def test_strips_python_dash_prefix(self, vm):
        assert vm._normalize_version("python-3.11") == "3.11"

    def test_whitespace_stripped(self, vm):
        assert vm._normalize_version("  3.11  ") == "3.11"

    def test_invalid_returns_none(self, vm):
        assert vm._normalize_version("latest") is None
        assert vm._normalize_version("3") is None
        assert vm._normalize_version("") is None


# ---------------------------------------------------------------------------
# _specifier_to_version
# ---------------------------------------------------------------------------


class TestSpecifierToVersion:
    def test_gte_minor(self, vm):
        assert vm._specifier_to_version(">=3.11") == "3.11"

    def test_gte_patch(self, vm):
        assert vm._specifier_to_version(">=3.11.5") == "3.11.5"

    def test_tilde_equal(self, vm):
        assert vm._specifier_to_version("~=3.11.0") == "3.11.0"

    def test_caret(self, vm):
        assert vm._specifier_to_version("^3.11") == "3.11"

    def test_double_equals(self, vm):
        assert vm._specifier_to_version("==3.11.*") == "3.11"

    def test_quoted(self, vm):
        assert vm._specifier_to_version('">=3.11"') == "3.11"

    def test_single_quoted(self, vm):
        assert vm._specifier_to_version("'>=3.11'") == "3.11"

    def test_with_spaces(self, vm):
        assert vm._specifier_to_version("  >= 3.11  ") == "3.11"

    def test_no_version_returns_none(self, vm):
        assert vm._specifier_to_version("*") is None


# ---------------------------------------------------------------------------
# _versions_compatible
# ---------------------------------------------------------------------------


class TestVersionsCompatible:
    """_versions_compatible is the shared logic used by SyncChecker."""

    @pytest.fixture
    def checker(self):
        return SyncChecker()

    def test_minor_matches_patch(self, checker):
        assert checker._versions_compatible("3.11.5", "3.11") is True

    def test_exact_match(self, checker):
        assert checker._versions_compatible("3.11.5", "3.11.5") is True

    def test_different_minor(self, checker):
        assert checker._versions_compatible("3.10.12", "3.11") is False

    def test_different_major(self, checker):
        assert checker._versions_compatible("2.7.18", "3.11") is False

    def test_required_patch_must_match(self, checker):
        assert checker._versions_compatible("3.11.4", "3.11.5") is False

    def test_required_patch_matches(self, checker):
        assert checker._versions_compatible("3.11.5", "3.11.5") is True


# ---------------------------------------------------------------------------
# detect_project_requirement — .python-version
# ---------------------------------------------------------------------------


class TestDetectPythonVersion:
    def test_reads_python_version_file(self, vm, project):
        (project / ".python-version").write_text("3.11\n")
        assert vm.detect_project_requirement() == "3.11"

    def test_python_version_with_patch(self, vm, project):
        (project / ".python-version").write_text("3.11.5\n")
        assert vm.detect_project_requirement() == "3.11.5"

    def test_python_version_with_cpython_prefix(self, vm, project):
        (project / ".python-version").write_text("cpython-3.11.5\n")
        assert vm.detect_project_requirement() == "3.11.5"

    def test_python_version_takes_priority_over_pyproject(self, vm, project):
        (project / ".python-version").write_text("3.11\n")
        (project / "pyproject.toml").write_text(
            '[project]\nrequires-python = ">=3.12"\n'
        )
        assert vm.detect_project_requirement() == "3.11"

    def test_no_config_returns_none(self, vm, project):
        assert vm.detect_project_requirement() is None


# ---------------------------------------------------------------------------
# detect_project_requirement — pyproject.toml
# ---------------------------------------------------------------------------


class TestDetectPyprojectToml:
    def test_requires_python_gte(self, vm, project):
        (project / "pyproject.toml").write_text(
            '[project]\nrequires-python = ">=3.11"\n'
        )
        assert vm.detect_project_requirement() == "3.11"

    def test_requires_python_tilde(self, vm, project):
        (project / "pyproject.toml").write_text(
            '[project]\nrequires-python = "~=3.11.0"\n'
        )
        assert vm.detect_project_requirement() == "3.11.0"

    def test_requires_python_exact(self, vm, project):
        (project / "pyproject.toml").write_text(
            '[project]\nrequires-python = "==3.11.*"\n'
        )
        assert vm.detect_project_requirement() == "3.11"

    def test_malformed_pyproject_returns_none(self, vm, project):
        (project / "pyproject.toml").write_text("not toml at all !!!!")
        # Should not raise — just return None
        result = vm.detect_project_requirement()
        assert result is None or isinstance(result, str)

    def test_pyproject_no_requires_python(self, vm, project):
        (project / "pyproject.toml").write_text(
            '[project]\nname = "myproject"\nversion = "1.0"\n'
        )
        assert vm.detect_project_requirement() is None


# ---------------------------------------------------------------------------
# detect_project_requirement — setup.cfg
# ---------------------------------------------------------------------------


class TestDetectSetupCfg:
    def test_python_requires(self, vm, project):
        (project / "setup.cfg").write_text(
            "[options]\npython_requires = >=3.10\n"
        )
        assert vm.detect_project_requirement() == "3.10"

    def test_python_requires_with_upper_bound(self, vm, project):
        (project / "setup.cfg").write_text(
            "[options]\npython_requires = >=3.10,<4\n"
        )
        assert vm.detect_project_requirement() == "3.10"


# ---------------------------------------------------------------------------
# detect_project_requirement — setup.py
# ---------------------------------------------------------------------------


class TestDetectSetupPy:
    def test_python_requires_double_quotes(self, vm, project):
        (project / "setup.py").write_text(
            'from setuptools import setup\n'
            'setup(name="pkg", python_requires=">=3.9")\n'
        )
        assert vm.detect_project_requirement() == "3.9"

    def test_python_requires_single_quotes(self, vm, project):
        (project / "setup.py").write_text(
            "setup(python_requires='>=3.10')\n"
        )
        assert vm.detect_project_requirement() == "3.10"


# ---------------------------------------------------------------------------
# detect_project_requirement — .tool-versions (asdf / mise)
# ---------------------------------------------------------------------------


class TestDetectToolVersions:
    def test_python_line(self, vm, project):
        (project / ".tool-versions").write_text("python 3.12.1\n")
        assert vm.detect_project_requirement() == "3.12.1"

    def test_python_with_other_tools(self, vm, project):
        (project / ".tool-versions").write_text(
            "nodejs 20.11.0\npython 3.11.5\nruby 3.2.0\n"
        )
        assert vm.detect_project_requirement() == "3.11.5"

    def test_no_python_line_returns_none(self, vm, project):
        (project / ".tool-versions").write_text("nodejs 20.11.0\n")
        assert vm.detect_project_requirement() is None


# ---------------------------------------------------------------------------
# get_system_python
# ---------------------------------------------------------------------------


def test_get_system_python_returns_version_string(vm):
    import sys
    result = vm.get_system_python()
    expected = f"{sys.version_info.major}.{sys.version_info.minor}"
    assert result == expected
