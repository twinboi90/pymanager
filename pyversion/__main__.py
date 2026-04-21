"""
pyversion — entry point.

Usage:
    pyversion pip <pip-args>     # auto-sync env, then run pip
    pyversion status             # show current project state
    pyversion check              # validate everything is correct
    pyversion versions           # list installed Python versions
    pyversion cleanup            # find/remove orphaned venvs & Pythons
    pyversion init               # set up a new project
    pyversion --version          # print pyversion version
    pyversion --help             # show this help
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from .environment_manager import EnvironmentManager
from .pip_wrapper import PipWrapper
from .registry import Registry
from .sync import SyncChecker, SyncIssue
from .version_manager import VersionManager, VERSIONS_DIR
from . import __version__


# ---------------------------------------------------------------------------
# ANSI helpers (auto-disable if not a TTY)
# ---------------------------------------------------------------------------

_USE_COLOR = sys.stdout.isatty()


def _c(code: str, text: str) -> str:
    if not _USE_COLOR:
        return text
    return f"\033[{code}m{text}\033[0m"


def green(t: str) -> str:  return _c("32", t)
def yellow(t: str) -> str: return _c("33", t)
def red(t: str) -> str:    return _c("31", t)
def bold(t: str) -> str:   return _c("1", t)
def dim(t: str) -> str:    return _c("2", t)


# ---------------------------------------------------------------------------
# PyManager — orchestrates everything
# ---------------------------------------------------------------------------


class PyManager:
    def __init__(self) -> None:
        self.version_mgr = VersionManager()
        self.env_mgr = EnvironmentManager()
        self.pip = PipWrapper()

    # ------------------------------------------------------------------
    # pip subcommand
    # ------------------------------------------------------------------

    def pip_command(self, args: list[str]) -> int:
        """
        Main entry for: pyversion pip <args>

        1. Detect required Python version
        2. Ensure Python is installed
        3. Ensure venv exists and is synced
        4. Run pip
        5. Update tracking
        """

        # ── Step 1: Detect ──────────────────────────────────────────────
        print(bold("🔍 Detecting Python requirement..."))
        required_python = self.version_mgr.detect_project_requirement()

        if not required_python:
            required_python = self.version_mgr.get_system_python()
            print(f"   {yellow('⚠')}  No requirement found in project files. Using system Python {required_python}.")
            print(dim("   Tip: add .python-version or pyproject.toml requires-python to pin a version."))
        else:
            print(f"   → Project requires Python {bold(required_python)}")

        # ── Step 2: Ensure Python is installed ──────────────────────────
        print()
        print(bold(f"🐍 Ensuring Python {required_python} is available..."))

        if not self.version_mgr.is_installed(required_python):
            # Check if a compatible system Python exists before downloading
            try:
                sys_path = self.version_mgr.get_path(required_python)
                print(f"   {green('✅')} Found system Python at {dim(str(sys_path))}")
                python_path = sys_path
            except RuntimeError:
                # Need to download
                print(f"   → Python {required_python} not found locally. Installing...")
                python_path = self.version_mgr.install(required_python)
                print(f"   {green('✅')} Python {required_python} installed")
        else:
            python_path = self.version_mgr.get_path(required_python)
            print(f"   {green('✅')} Python {required_python} already installed")

        # ── Step 3: Sync check (before creating/touching venv) ──────────
        print()
        print(bold("📦 Setting up virtual environment..."))
        venv_path = Path.cwd() / ".venv"

        checker = SyncChecker()
        sync = checker.check(venv_path, required_python)

        if sync.is_missing:
            # Fresh create
            try:
                venv_path = self.env_mgr.get_or_create_venv(python_path, required_python, venv_path)
            except RuntimeError as e:
                print(f"   {red('❌')} Failed to create venv: {e}")
                return 1
            print(f"   {green('✅')} Virtual environment created: {dim(str(venv_path))}")

        elif not sync.is_healthy:
            # Detailed issue report before rebuilding
            print(f"   {yellow('⚠')}  Venv has issues — rebuilding:")
            for msg in sync.describe():
                if "[warning]" in msg:
                    print(f"      {yellow('·')} {msg.replace('[warning] ', '')}")
                else:
                    print(f"      {red('·')} {msg}")
            try:
                self.env_mgr.rebuild_venv(venv_path, python_path, required_python)
                print(f"   {green('✅')} Venv rebuilt with Python {required_python}")
            except RuntimeError as e:
                print(f"   {red('❌')} Rebuild failed: {e}")
                return 1

        else:
            # Healthy — surface any warnings non-blocking
            if sync.warnings:
                for msg in sync.describe():
                    if "[warning]" in msg:
                        print(f"   {yellow('·')} {msg.replace('[warning] ', '')}")
            print(f"   {green('✅')} Virtual environment ready: {dim(str(venv_path))}")

        # ── Step 4: Validate sync ────────────────────────────────────────
        print()
        print(bold("✔️  Validating environment..."))

        # Re-check after any repairs
        sync = checker.check(venv_path, required_python)
        if not sync.is_healthy:
            print(f"   {red('❌')} Environment still has unresolved issues:")
            for msg in sync.describe():
                print(f"      · {msg}")
            print(f"   Try removing .venv manually and re-running.")
            return 1

        print(f"   {green('✅')} Environment synced with Python {sync.actual_version or required_python}")

        # ── Step 5: Run pip ─────────────────────────────────────────────
        print()
        print(bold(f"⚙️  Running pip {' '.join(args)}..."))
        print()

        result = self.pip.run(venv_path, args)

        # ── Step 6: Post-command ─────────────────────────────────────────
        if result.returncode != 0:
            print()
            print(f"{red('❌')} pip command failed (exit {result.returncode})")
            return result.returncode

        print()
        print(f"{green('✅')} Command completed successfully")
        self.env_mgr.update_tracking(venv_path, required_python)
        Registry().register(Path.cwd(), required_python)

        return 0

    # ------------------------------------------------------------------
    # status
    # ------------------------------------------------------------------

    def cmd_status(self) -> int:
        """Show a summary of the current project's pyversion state."""
        cwd = Path.cwd()
        venv_path = cwd / ".venv"

        print(bold("📊 pyversion status"))
        print()

        # Project
        print(f"  {bold('Project dir:')}   {cwd}")

        # Python requirement
        required = self.version_mgr.detect_project_requirement()
        if required:
            print(f"  {bold('Required Python:')} {required} {dim('(from project config)')}")
        else:
            required = self.version_mgr.get_system_python()
            print(f"  {bold('Required Python:')} {required} {yellow('(no config — using system)')} ")

        # Venv info via SyncChecker
        info = self.env_mgr.get_venv_info(venv_path)
        if info["exists"]:
            sync = SyncChecker().check(venv_path, required)
            if sync.is_healthy:
                sync_icon = green("✅ synced")
            elif sync.warnings and not sync.issues:
                sync_icon = yellow("⚠ warnings")
            else:
                sync_icon = red("❌ issues")
            print(f"  {bold('Virtual env:')}    {venv_path} [{sync_icon}]")
            print(f"  {bold('Venv Python:')}    {sync.actual_version or info.get('python_version', 'unknown')}")
            print(f"  {bold('Packages:')}       {info.get('package_count', 0)} installed")
            if sync.issues or sync.warnings:
                for msg in sync.describe():
                    prefix = yellow("·") if "[warning]" in msg else red("·")
                    print(f"    {prefix} {msg.replace('[warning] ', '')}")
            if info.get("last_used"):
                print(f"  {bold('Last used:')}      {info['last_used']}")
        else:
            print(f"  {bold('Virtual env:')}    {yellow('not created')} — run `pyversion pip install` to create")

        print()
        return 0

    # ------------------------------------------------------------------
    # check
    # ------------------------------------------------------------------

    def cmd_check(self) -> int:
        """Validate everything is correct for the current project."""
        cwd = Path.cwd()
        venv_path = cwd / ".venv"
        fatal: list[str] = []
        warnings: list[str] = []
        ok: list[str] = []

        print(bold("🔎 pyversion check"))
        print()

        # Check 1: Python requirement
        required = self.version_mgr.detect_project_requirement()
        if required:
            ok.append(f"Python requirement: {required}")
        else:
            warnings.append("No Python version requirement found (add .python-version or pyproject.toml)")
            required = self.version_mgr.get_system_python()

        # Check 2: Python available
        try:
            python_path = self.version_mgr.get_path(required)
            ok.append(f"Python {required} available at {python_path}")
        except RuntimeError:
            fatal.append(f"Python {required} not installed — run `pyversion pip install` to trigger install")
            python_path = None

        # Check 3–6: Full venv sync check
        sync = SyncChecker().check(venv_path, required)

        if sync.is_missing:
            fatal.append(f"No virtual environment found at {venv_path}")
        else:
            ok.append(f"Virtual environment exists at {venv_path}")
            for issue in sync.issues:
                from .sync import _ISSUE_MESSAGES
                fatal.append(_ISSUE_MESSAGES.get(issue, str(issue)))
            for warn in sync.warnings:
                from .sync import _ISSUE_MESSAGES
                warnings.append(_ISSUE_MESSAGES.get(warn, str(warn)))
            if sync.is_healthy:
                ok.append(f"Venv synced with Python {sync.actual_version or required}")
            if sync.pip_version:
                ok.append(f"pip functional ({sync.pip_version})")

        # Print results
        for msg in ok:
            print(f"  {green('✅')} {msg}")
        for msg in warnings:
            print(f"  {yellow('⚠')}  {msg}")
        for msg in fatal:
            print(f"  {red('❌')} {msg}")

        print()
        if fatal:
            print(f"{red('❌')} {len(fatal)} issue(s) found. Run `pyversion pip install` to auto-fix.")
            return 1
        elif warnings:
            print(f"{yellow('⚠')}  {len(warnings)} warning(s). Run `pyversion pip install` to repair.")
            return 0
        else:
            print(f"{green('✅')} Everything looks good!")
            return 0

    # ------------------------------------------------------------------
    # versions
    # ------------------------------------------------------------------

    def cmd_versions(self) -> int:
        """List installed Python versions managed by pyversion."""
        print(bold("🐍 Installed Python versions (pyversion-managed)"))
        print()

        versions = self.version_mgr.list_installed()
        if not versions:
            print(f"  {dim('No pyversion-managed Python versions installed.')}")
            print(f"  {dim('Run `pyversion pip install` in a project to trigger an install.')}")
        else:
            for v in versions:
                label = v["label"]
                actual = v.get("actual_version") or "?"
                path = v["path"]
                print(f"  {green('●')} Python {bold(label)} ({actual})  {dim(path)}")

        print()
        # Also show system Pythons for reference
        print(dim("System Pythons (not managed by pyversion):"))
        for candidate in ("python3.13", "python3.12", "python3.11", "python3.10", "python3.9", "python3"):
            found = shutil.which(candidate)
            if found:
                try:
                    r = subprocess.run([found, "--version"], capture_output=True, text=True, timeout=3)
                    ver_str = (r.stdout.strip() or r.stderr.strip()).replace("Python ", "")
                    print(f"  {dim('○')} {dim(candidate)} → {dim(ver_str)}  ({dim(found)})")
                except Exception:
                    pass

        print()
        return 0

    # ------------------------------------------------------------------
    # cleanup
    # ------------------------------------------------------------------

    def cmd_cleanup(self) -> int:
        """Find orphaned venvs and unused Python versions."""
        dry_run = "--dry-run" in sys.argv

        print(bold("🧹 pyversion cleanup"))
        if dry_run:
            print(f"  {dim('(dry-run mode — nothing will be deleted)')}")
        print()

        registry = Registry()

        # ── Prune stale registry entries ─────────────────────────────
        stale = registry.prune_stale()
        if stale:
            print(f"  {dim(f'Pruned {len(stale)} stale registry entry/entries (projects no longer on disk)')}")
            print()

        # ── Scan managed Python versions ──────────────────────────────
        versions = self.version_mgr.list_installed()
        active_versions = registry.active_versions()

        if not versions:
            print(f"  {dim('No pyversion-managed Python versions installed.')}")
            print(f"  {dim('Nothing to clean up.')}")
            print()
            return 0

        print(f"  {bold('Managed Python versions:')}")
        print()

        to_remove: list[dict] = []

        for v in versions:
            label = v["label"]
            actual = v.get("actual_version") or label
            path = Path(v["path"]).parent.parent  # bin/python → version root
            size = self._dir_size_mb(path)
            projects = registry.projects_for_version(label)
            active_projects = [p for p in projects if p.exists]

            if active_projects:
                status = green(f"active ({len(active_projects)} project(s))")
            elif projects:
                status = yellow(f"stale ({len(projects)} project(s) no longer on disk)")
                to_remove.append(v)
            else:
                status = yellow("orphaned (no registered projects)")
                to_remove.append(v)

            print(f"  {bold('Python ' + actual)}  [{status}]  {dim(f'{size} MB  {path}')}")

            for p in active_projects[:3]:
                print(f"    {dim('·')} {dim(p.path)}")
            if len(active_projects) > 3:
                print(f"    {dim(f'  ... and {len(active_projects) - 3} more')}")

        print()

        # ── Offer to remove orphaned/stale versions ───────────────────
        if not to_remove:
            print(f"  {green('✅')} All managed Python versions are in active use.")
            print()
            return 0

        print(f"  {yellow('⚠')}  Found {len(to_remove)} version(s) with no active projects:")
        for v in to_remove:
            path = Path(v["path"]).parent.parent
            size = self._dir_size_mb(path)
            print(f"    {red('·')} Python {v['label']}  ({size} MB)  {dim(str(path))}")

        print()

        if dry_run:
            print(f"  {dim('[dry-run] Would prompt to remove the above version(s).')}")
            return 0

        try:
            answer = input(f"  Remove these {len(to_remove)} version(s)? [y/N] ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            print("\n  Aborted.")
            return 0

        if answer != "y":
            print(f"  {dim('Skipped. Nothing was removed.')}")
            return 0

        removed_mb = 0
        for v in to_remove:
            path = Path(v["path"]).parent.parent
            size = self._dir_size_mb(path)
            try:
                shutil.rmtree(path)
                removed_mb += size
                print(f"  {green('✅')} Removed Python {v['label']}  ({size} MB freed)")
            except Exception as e:
                print(f"  {red('❌')} Failed to remove {path}: {e}")

        print()
        print(f"  {green('✅')} Done. {removed_mb} MB freed.")
        return 0

    def _dir_size_mb(self, path: Path) -> int:
        """Return approximate directory size in MB."""
        total = 0
        try:
            for f in path.rglob("*"):
                if f.is_file() and not f.is_symlink():
                    total += f.stat().st_size
        except Exception:
            pass
        return total // (1024 * 1024)

    # ------------------------------------------------------------------
    # init
    # ------------------------------------------------------------------

    def cmd_init(self) -> int:
        """Interactively set up a new project."""
        cwd = Path.cwd()
        pv = cwd / ".python-version"

        print(bold("🚀 pyversion init"))
        print()

        if pv.exists():
            existing = pv.read_text().strip()
            print(f"  {yellow('⚠')}  .python-version already exists: {existing}")
            answer = input("  Overwrite? [y/N] ").strip().lower()
            if answer != "y":
                print("  Aborted.")
                return 0

        # List available versions
        supported = ["3.9", "3.10", "3.11", "3.12", "3.13"]
        print("  Which Python version should this project use?")
        for i, v in enumerate(supported, 1):
            print(f"    {i}. Python {v}")
        print()

        try:
            choice = input("  Enter number or version (e.g. '3' or '3.11'): ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n  Aborted.")
            return 0

        # Interpret choice
        version = None
        if choice.isdigit() and 1 <= int(choice) <= len(supported):
            version = supported[int(choice) - 1]
        elif choice in supported or (choice.count(".") >= 1 and all(p.isdigit() for p in choice.split("."))):
            version = choice
        else:
            print(f"  {red('❌')} Invalid choice: {choice}")
            return 1

        pv.write_text(version + "\n")
        print(f"  {green('✅')} Created .python-version → {version}")
        print()
        print(f"  Next: run {bold('pyversion pip install -r requirements.txt')} to set up your environment.")
        return 0

    # ------------------------------------------------------------------
    # setup-path
    # ------------------------------------------------------------------

    def cmd_setup_path(self) -> int:
        """Add pyversion's scripts directory to the user's shell PATH."""
        import sysconfig

        print(bold("🔧 pyversion setup-path"))
        print()

        # ── Detect scripts directory ──────────────────────────────────
        scripts_dir = self._find_scripts_dir()
        if not scripts_dir:
            print(f"  {red('❌')} Could not detect pip scripts directory.")
            print(f"  {dim('Try running: python -m sysconfig | grep scripts')}")
            return 1

        print(f"  Scripts dir: {bold(scripts_dir)}")

        # ── Already on PATH? ──────────────────────────────────────────
        current_path = os.environ.get("PATH", "").split(":")
        if scripts_dir in current_path:
            print(f"  {green('✅')} Already on PATH — nothing to do!")
            print()
            print(f"  Run {bold('pyversion --version')} to confirm.")
            return 0

        # ── Detect shell + RC file ────────────────────────────────────
        shell = Path(os.environ.get("SHELL", "/bin/zsh")).name
        rc_file, path_line = self._shell_config(shell, scripts_dir)

        print(f"  Shell:       {bold(shell)}")
        print(f"  Config file: {bold(rc_file)}")
        print()

        # ── Check if already written ──────────────────────────────────
        rc_path = Path(rc_file).expanduser()
        existing = rc_path.read_text() if rc_path.exists() else ""
        if scripts_dir in existing:
            print(f"  {green('✅')} PATH entry already present in {rc_file}")
            print(f"  {dim('Run: source ' + rc_file + '  (or open a new terminal)')}")
            return 0

        # ── Write it ──────────────────────────────────────────────────
        try:
            with rc_path.open("a") as f:
                f.write(f"\n# added by pyversion setup-path\n{path_line}\n")
        except OSError as e:
            print(f"  {red('❌')} Could not write to {rc_file}: {e}")
            print()
            print(f"  Add this line manually:")
            print(f"    {bold(path_line)}")
            return 1

        print(f"  {green('✅')} Added to {rc_file}:")
        print(f"      {bold(path_line)}")
        print()
        print(f"  Reload your shell to activate:")
        print(f"    {bold('source ' + rc_file)}")
        print()
        print(f"  Or open a new terminal, then run:")
        print(f"    {bold('pyversion --version')}")
        return 0

    def _find_scripts_dir(self) -> Optional[str]:
        """Return the pip --user scripts directory for this Python."""
        import sysconfig

        # Try common user schemes in order
        for scheme in ("posix_user", "osx_framework_user", "nt_user"):
            try:
                d = sysconfig.get_path("scripts", scheme)
                if d:
                    return d
            except KeyError:
                continue

        # Fallback: look at where this very script lives
        this_script = Path(sys.argv[0]).resolve()
        if this_script.parent != Path(sys.executable).parent:
            return str(this_script.parent)

        return None

    def _shell_config(self, shell: str, scripts_dir: str) -> tuple[str, str]:
        """Return (rc_file_path, line_to_add) for the given shell."""
        if shell == "fish":
            return ("~/.config/fish/config.fish", f'fish_add_path "{scripts_dir}"')
        elif shell == "bash":
            return ("~/.bash_profile", f'export PATH="{scripts_dir}:$PATH"')
        elif shell == "zsh":
            return ("~/.zshrc", f'export PATH="{scripts_dir}:$PATH"')
        else:
            return ("~/.profile", f'export PATH="{scripts_dir}:$PATH"')


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

HELP = f"""\
{bold('pyversion')} v{__version__} — automatic Python version & virtualenv manager

{bold('Usage:')}
  pyversion pip <args>     Run pip in the auto-synced environment
  pyversion status         Show project Python/venv state
  pyversion check          Validate environment is correct
  pyversion versions       List pyversion-managed Python versions
  pyversion cleanup        Show orphaned venvs / installed versions
  pyversion init           Set up Python version for a new project
  pyversion setup-path     Add pyversion to your shell PATH
  pyversion --version      Print version
  pyversion --help         Show this help

{bold('Examples:')}
  pyversion pip install requests
  pyversion pip install -r requirements.txt
  pyversion pip list
  pyversion pip freeze > requirements.txt
  pyversion pip install --upgrade mypackage

{bold('How it works:')}
  1. Reads .python-version / pyproject.toml to detect required Python
  2. Installs that Python if missing (precompiled, ~30 seconds)
  3. Creates / fixes .venv automatically
  4. Routes pip to the correct environment
  5. Reports what it did
"""


def main() -> None:
    # Force line-buffered stdout so pyversion prints appear before subprocess output.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)

    args = sys.argv[1:]

    if not args or args[0] in ("--help", "-h", "help"):
        print(HELP)
        sys.exit(0)

    if args[0] in ("--version", "-V"):
        print(f"pyversion {__version__}")
        sys.exit(0)

    manager = PyManager()

    subcommand = args[0]

    if subcommand == "pip":
        sys.exit(manager.pip_command(args[1:]))

    elif subcommand == "status":
        sys.exit(manager.cmd_status())

    elif subcommand == "check":
        sys.exit(manager.cmd_check())

    elif subcommand == "versions":
        sys.exit(manager.cmd_versions())

    elif subcommand == "cleanup":
        sys.exit(manager.cmd_cleanup())

    elif subcommand == "init":
        sys.exit(manager.cmd_init())

    elif subcommand == "setup-path":
        sys.exit(manager.cmd_setup_path())

    else:
        print(f"{red('❌')} Unknown command: {subcommand}")
        print()
        print(HELP)
        sys.exit(1)


if __name__ == "__main__":
    main()
