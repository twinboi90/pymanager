"""
pymanager — entry point.

Usage:
    pymanager pip <pip-args>     # auto-sync env, then run pip
    pymanager status             # show current project state
    pymanager check              # validate everything is correct
    pymanager versions           # list installed Python versions
    pymanager cleanup            # find/remove orphaned venvs & Pythons
    pymanager init               # set up a new project
    pymanager --version          # print pymanager version
    pymanager --help             # show this help
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
        Main entry for: pymanager pip <args>

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

        # ── Step 3: Ensure venv ─────────────────────────────────────────
        print()
        print(bold("📦 Setting up virtual environment..."))
        venv_path = Path.cwd() / ".venv"

        try:
            venv_path = self.env_mgr.get_or_create_venv(python_path, required_python, venv_path)
        except RuntimeError as e:
            print(f"   {red('❌')} Failed to create venv: {e}")
            return 1

        print(f"   {green('✅')} Virtual environment ready: {dim(str(venv_path))}")

        # ── Step 4: Validate sync ────────────────────────────────────────
        print()
        print(bold("✔️  Validating environment..."))

        if not self.env_mgr.is_synced(venv_path, required_python):
            print(f"   {yellow('⚠')}  Venv is out of sync with Python {required_python}. Rebuilding...")
            try:
                self.env_mgr.rebuild_venv(venv_path, python_path, required_python)
                print(f"   {green('✅')} Venv rebuilt successfully")
            except RuntimeError as e:
                print(f"   {red('❌')} Rebuild failed: {e}")
                return 1
        else:
            print(f"   {green('✅')} Environment is synced with Python {required_python}")

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

        return 0

    # ------------------------------------------------------------------
    # status
    # ------------------------------------------------------------------

    def cmd_status(self) -> int:
        """Show a summary of the current project's pymanager state."""
        cwd = Path.cwd()
        venv_path = cwd / ".venv"

        print(bold("📊 pymanager status"))
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

        # Venv info
        info = self.env_mgr.get_venv_info(venv_path)
        if info["exists"]:
            synced = self.env_mgr.is_synced(venv_path, required)
            sync_icon = green("✅ synced") if synced else yellow("⚠ out of sync")
            print(f"  {bold('Virtual env:')}    {venv_path} [{sync_icon}]")
            print(f"  {bold('Venv Python:')}    {info.get('python_version', 'unknown')}")
            print(f"  {bold('Packages:')}       {info.get('package_count', 0)} installed")
            if info.get("last_used"):
                print(f"  {bold('Last used:')}      {info['last_used']}")
        else:
            print(f"  {bold('Virtual env:')}    {yellow('not created')} — run `pymanager pip install` to create")

        print()
        return 0

    # ------------------------------------------------------------------
    # check
    # ------------------------------------------------------------------

    def cmd_check(self) -> int:
        """Validate everything is correct for the current project."""
        cwd = Path.cwd()
        venv_path = cwd / ".venv"
        issues: list[str] = []
        ok: list[str] = []

        print(bold("🔎 pymanager check"))
        print()

        # Check 1: Python requirement
        required = self.version_mgr.detect_project_requirement()
        if required:
            ok.append(f"Python requirement: {required}")
        else:
            issues.append("No Python version requirement found (add .python-version or pyproject.toml)")
            required = self.version_mgr.get_system_python()

        # Check 2: Python available
        try:
            python_path = self.version_mgr.get_path(required)
            ok.append(f"Python {required} available at {python_path}")
        except RuntimeError:
            issues.append(f"Python {required} not installed (run `pymanager pip install` to trigger install)")
            python_path = None

        # Check 3: Venv exists
        if venv_path.exists():
            ok.append(f"Virtual environment exists at {venv_path}")
        else:
            issues.append(f"No virtual environment found at {venv_path}")

        # Check 4: Venv synced
        if venv_path.exists():
            if self.env_mgr.is_synced(venv_path, required):
                ok.append(f"Venv is synced with Python {required}")
            else:
                issues.append(f"Venv is out of sync — was built with a different Python version")

        # Check 5: pip functional
        if venv_path.exists():
            result = self.pip.run_captured(venv_path, ["--version"])
            if result.returncode == 0:
                ok.append(f"pip is functional ({result.stdout.strip()[:60]})")
            else:
                issues.append("pip is not functional inside venv")

        # Print results
        for msg in ok:
            print(f"  {green('✅')} {msg}")
        for msg in issues:
            print(f"  {red('❌')} {msg}")

        print()
        if issues:
            print(f"{yellow('⚠')}  {len(issues)} issue(s) found. Run `pymanager pip install` to auto-fix.")
            return 1
        else:
            print(f"{green('✅')} Everything looks good!")
            return 0

    # ------------------------------------------------------------------
    # versions
    # ------------------------------------------------------------------

    def cmd_versions(self) -> int:
        """List installed Python versions managed by pymanager."""
        print(bold("🐍 Installed Python versions (pymanager-managed)"))
        print()

        versions = self.version_mgr.list_installed()
        if not versions:
            print(f"  {dim('No pymanager-managed Python versions installed.')}")
            print(f"  {dim('Run `pymanager pip install` in a project to trigger an install.')}")
        else:
            for v in versions:
                label = v["label"]
                actual = v.get("actual_version") or "?"
                path = v["path"]
                print(f"  {green('●')} Python {bold(label)} ({actual})  {dim(path)}")

        print()
        # Also show system Pythons for reference
        print(dim("System Pythons (not managed by pymanager):"))
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
        print(bold("🧹 pymanager cleanup"))
        print()
        print(dim("  Scanning ~/.pymanager/versions/..."))
        versions = self.version_mgr.list_installed()
        if not versions:
            print(f"  {dim('No managed versions found.')}")
        else:
            print(f"  Found {len(versions)} managed Python version(s):")
            for v in versions:
                print(f"    {green('●')} Python {v['label']} — {v['path']}")

        print()
        print(dim("  To remove a specific version:"))
        print(dim(f"    rm -rf ~/.pymanager/versions/<version>"))
        print()
        print(dim("  To remove a project's venv:"))
        print(dim(f"    rm -rf .venv"))
        print()
        print(f"{yellow('Note:')} Interactive cleanup (auto-remove unused) is coming in Phase 2.")
        return 0

    # ------------------------------------------------------------------
    # init
    # ------------------------------------------------------------------

    def cmd_init(self) -> int:
        """Interactively set up a new project."""
        cwd = Path.cwd()
        pv = cwd / ".python-version"

        print(bold("🚀 pymanager init"))
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
        print(f"  Next: run {bold('pymanager pip install -r requirements.txt')} to set up your environment.")
        return 0

    # ------------------------------------------------------------------
    # setup-path
    # ------------------------------------------------------------------

    def cmd_setup_path(self) -> int:
        """Add pymanager's scripts directory to the user's shell PATH."""
        import sysconfig

        print(bold("🔧 pymanager setup-path"))
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
            print(f"  Run {bold('pymanager --version')} to confirm.")
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
                f.write(f"\n# added by pymanager setup-path\n{path_line}\n")
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
        print(f"    {bold('pymanager --version')}")
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
{bold('pymanager')} v{__version__} — automatic Python version & virtualenv manager

{bold('Usage:')}
  pymanager pip <args>     Run pip in the auto-synced environment
  pymanager status         Show project Python/venv state
  pymanager check          Validate environment is correct
  pymanager versions       List pymanager-managed Python versions
  pymanager cleanup        Show orphaned venvs / installed versions
  pymanager init           Set up Python version for a new project
  pymanager setup-path     Add pymanager to your shell PATH
  pymanager --version      Print version
  pymanager --help         Show this help

{bold('Examples:')}
  pymanager pip install requests
  pymanager pip install -r requirements.txt
  pymanager pip list
  pymanager pip freeze > requirements.txt
  pymanager pip install --upgrade mypackage

{bold('How it works:')}
  1. Reads .python-version / pyproject.toml to detect required Python
  2. Installs that Python if missing (precompiled, ~30 seconds)
  3. Creates / fixes .venv automatically
  4. Routes pip to the correct environment
  5. Reports what it did
"""


def main() -> None:
    # Force line-buffered stdout so pymanager prints appear before subprocess output.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)

    args = sys.argv[1:]

    if not args or args[0] in ("--help", "-h", "help"):
        print(HELP)
        sys.exit(0)

    if args[0] in ("--version", "-V"):
        print(f"pymanager {__version__}")
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
