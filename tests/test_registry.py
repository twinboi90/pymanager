"""
Tests for pymanager.registry — Registry CRUD and query logic.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from pymanager.registry import Registry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def reg(registry_path):
    """Return a Registry instance pointing at a temp file."""
    return Registry(path=registry_path)


@pytest.fixture
def existing_project(tmp_path):
    """Return a real directory that represents an existing project."""
    p = tmp_path / "my-project"
    p.mkdir()
    return p


@pytest.fixture
def another_project(tmp_path):
    p = tmp_path / "another-project"
    p.mkdir()
    return p


# ---------------------------------------------------------------------------
# register / basic read
# ---------------------------------------------------------------------------


def test_register_creates_entry(reg, existing_project):
    reg.register(existing_project, "3.11")
    projects = reg.all_projects()
    assert len(projects) == 1
    assert projects[0].python_version == "3.11"
    assert projects[0].path == str(existing_project.resolve())


def test_register_updates_last_seen(reg, existing_project):
    reg.register(existing_project, "3.11")
    first = reg.all_projects()[0].last_seen

    time.sleep(0.01)  # ensure timestamp advances
    reg.register(existing_project, "3.11")
    second = reg.all_projects()[0].last_seen

    assert second >= first


def test_register_updates_version(reg, existing_project):
    reg.register(existing_project, "3.11")
    reg.register(existing_project, "3.12")
    projects = reg.all_projects()
    assert len(projects) == 1
    assert projects[0].python_version == "3.12"


def test_multiple_projects(reg, existing_project, another_project):
    reg.register(existing_project, "3.11")
    reg.register(another_project, "3.12")
    assert len(reg.all_projects()) == 2


# ---------------------------------------------------------------------------
# unregister
# ---------------------------------------------------------------------------


def test_unregister_removes_entry(reg, existing_project):
    reg.register(existing_project, "3.11")
    reg.unregister(existing_project)
    assert reg.all_projects() == []


def test_unregister_nonexistent_is_safe(reg, existing_project):
    # Should not raise even if path was never registered
    reg.unregister(existing_project)
    assert reg.all_projects() == []


# ---------------------------------------------------------------------------
# projects_for_version
# ---------------------------------------------------------------------------


def test_projects_for_version_exact(reg, existing_project, another_project):
    reg.register(existing_project, "3.11")
    reg.register(another_project, "3.12")
    matches = reg.projects_for_version("3.11")
    assert len(matches) == 1
    assert matches[0].path == str(existing_project.resolve())


def test_projects_for_version_minor_matches_patch(reg, existing_project):
    """Querying '3.11' should find projects registered as '3.11.5'."""
    reg.register(existing_project, "3.11.5")
    matches = reg.projects_for_version("3.11")
    assert len(matches) == 1


def test_projects_for_version_patch_matches_minor(reg, existing_project):
    """Querying '3.11.5' should find projects registered as '3.11'."""
    reg.register(existing_project, "3.11")
    matches = reg.projects_for_version("3.11.5")
    assert len(matches) == 1


def test_projects_for_version_no_match(reg, existing_project):
    reg.register(existing_project, "3.10")
    matches = reg.projects_for_version("3.11")
    assert matches == []


# ---------------------------------------------------------------------------
# active_versions
# ---------------------------------------------------------------------------


def test_active_versions_existing_project(reg, existing_project):
    reg.register(existing_project, "3.11")
    assert "3.11" in reg.active_versions()


def test_active_versions_excludes_missing_project(reg, tmp_path):
    ghost = tmp_path / "ghost-project"
    # Don't create it — it won't exist
    reg.register(ghost, "3.11")
    assert "3.11" not in reg.active_versions()


def test_active_versions_mixed(reg, existing_project, tmp_path):
    ghost = tmp_path / "gone"
    reg.register(existing_project, "3.11")
    reg.register(ghost, "3.12")
    active = reg.active_versions()
    assert "3.11" in active
    assert "3.12" not in active


def test_active_versions_patch_normalised_to_minor(reg, existing_project):
    reg.register(existing_project, "3.11.5")
    active = reg.active_versions()
    assert "3.11" in active
    assert "3.11.5" not in active  # always stored as minor


# ---------------------------------------------------------------------------
# prune_stale
# ---------------------------------------------------------------------------


def test_prune_stale_removes_missing_paths(reg, existing_project, tmp_path):
    ghost = tmp_path / "gone"
    reg.register(existing_project, "3.11")
    reg.register(ghost, "3.12")

    pruned = reg.prune_stale()
    assert str(ghost.resolve()) in pruned
    assert len(reg.all_projects()) == 1
    assert reg.all_projects()[0].path == str(existing_project.resolve())


def test_prune_stale_no_stale_entries(reg, existing_project):
    reg.register(existing_project, "3.11")
    pruned = reg.prune_stale()
    assert pruned == []
    assert len(reg.all_projects()) == 1


def test_prune_stale_empty_registry(reg):
    pruned = reg.prune_stale()
    assert pruned == []


# ---------------------------------------------------------------------------
# ProjectEntry properties
# ---------------------------------------------------------------------------


def test_project_entry_exists_true(reg, existing_project):
    reg.register(existing_project, "3.11")
    entry = reg.all_projects()[0]
    assert entry.exists is True


def test_project_entry_exists_false(reg, tmp_path):
    ghost = tmp_path / "ghost"
    reg.register(ghost, "3.11")
    entry = reg.all_projects()[0]
    assert entry.exists is False


def test_project_entry_last_seen_dt(reg, existing_project):
    reg.register(existing_project, "3.11")
    entry = reg.all_projects()[0]
    dt = entry.last_seen_dt
    assert dt is not None


# ---------------------------------------------------------------------------
# Edge cases / resilience
# ---------------------------------------------------------------------------


def test_empty_registry_all_projects(reg):
    assert reg.all_projects() == []


def test_missing_registry_file_handled(registry_path):
    """Registry that has never been written should return empty, not crash."""
    reg = Registry(path=registry_path)
    assert reg.all_projects() == []
    assert reg.active_versions() == set()
    assert reg.prune_stale() == []


def test_corrupted_registry_file_handled(registry_path):
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text("this is not json {{{{")
    reg = Registry(path=registry_path)
    assert reg.all_projects() == []


def test_registry_persists_to_disk(registry_path, existing_project):
    reg1 = Registry(path=registry_path)
    reg1.register(existing_project, "3.11")

    reg2 = Registry(path=registry_path)
    projects = reg2.all_projects()
    assert len(projects) == 1
    assert projects[0].python_version == "3.11"
