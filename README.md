# pyversion

[![PyPI version](https://img.shields.io/pypi/v/pyversion-cli.svg)](https://pypi.org/project/pyversion-cli/)
[![Python versions](https://img.shields.io/pypi/pyversions/pyversion-cli.svg)](https://pypi.org/project/pyversion-cli/)
[![CI](https://github.com/twinboi90/pyversion/actions/workflows/ci.yml/badge.svg)](https://github.com/twinboi90/pyversion/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**One command. Any Python version. Zero configuration.**

```bash
pyversion pip install requests
```

That's it. pyversion figures out which Python your project needs, installs it if missing, creates and validates the virtual environment, and runs pip — all automatically, every time.

---

## The problem

You have three Python projects. Each needs a different Python version. Every time you switch between them, something breaks:

```bash
$ cd project-a
$ pip install -r requirements.txt
# Which pip is this? Which Python? Is my venv activated?
# Did I forget to source venv/bin/activate?
# Wait, this is installing into Python 3.13 but the project needs 3.11...
```

The actual workflow developers put up with today:

```bash
# project-a setup (Python 3.11)
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# switch to project-b (Python 3.12)
deactivate
cd ../project-b
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# forget to activate, install into wrong environment
# wonder why imports break
# start over
```

This is the state of Python development in 2025. It's a rite of passage — and it shouldn't be.

---

## The solution

```bash
$ cd project-a
$ pyversion pip install -r requirements.txt

🔍 Detecting Python requirement...
   → Project requires Python 3.11 (from pyproject.toml)

🐍 Ensuring Python 3.11 is available...
   ✅ Python 3.11 already installed

📦 Setting up virtual environment...
   ✅ Virtual environment ready: ./.venv

✔️  Validating environment...
   ✅ Environment synced with Python 3.11.10

⚙️  Running pip install -r requirements.txt...

Collecting requests...
Successfully installed requests-2.31.0 urllib3-2.0.0 certifi-2023.7.22

✅ Command completed successfully
```

```bash
$ cd ../project-b
$ pyversion pip install -r requirements.txt

🔍 Detecting Python requirement...
   → Project requires Python 3.12 (from .python-version)

🐍 Ensuring Python 3.12 is available...
   ✅ Python 3.12 already installed

📦 Setting up virtual environment...
   → Creating .venv with Python 3.12...
   ✅ Virtual environment ready: ./.venv

✔️  Validating environment...
   ✅ Environment synced with Python 3.12.7

⚙️  Running pip install -r requirements.txt...

✅ Command completed successfully
```

**No activation. No version flags. No thinking.** Just `cd` and run.

---

## Install

### Homebrew (recommended)

```bash
brew install twinboi90/tap/pyversion
```

That's it. No cloning, no PATH setup, no configuration. Homebrew handles everything.

### pip

```bash
pip install pyversion-cli
```

Then reload your shell (or open a new terminal window). The `pyversion` command will be available immediately.

> **Note:** If `pyversion` isn't found after install, run `pyversion setup-path` to add it to your PATH automatically, then `source ~/.zshrc`.

### install.sh (no Homebrew, no pip)

```bash
git clone https://github.com/twinboi90/pyversion.git
cd pyversion
./install.sh
```

The installer:
- Detects your Python and installs pyversion
- Finds where pip put the script
- Adds it to your shell's PATH automatically (`~/.zshrc`, `~/.bash_profile`, or `~/.config/fish/config.fish`)
- Tells you exactly what it changed

Then reload your shell:

```bash
source ~/.zshrc   # or ~/.bash_profile for bash
```

### pip (manual)

```bash
git clone https://github.com/twinboi90/pyversion.git
cd pyversion
pip install -e .
pyversion setup-path   # adds pyversion to your PATH
source ~/.zshrc
```

### Verify

```bash
pyversion --version
# pyversion 0.1.0
```

---

## Usage

### The main command

```bash
pyversion pip <any pip args>
```

Every pip subcommand works exactly as you'd expect:

```bash
pyversion pip install requests
pyversion pip install -r requirements.txt
pyversion pip install --upgrade requests
pyversion pip uninstall requests
pyversion pip list
pyversion pip freeze
pyversion pip freeze > requirements.txt
pyversion pip show requests
pyversion pip install "django>=4.2,<5.0"
```

### Project status

```bash
$ pyversion status

📊 pyversion status

  Project dir:    /Users/you/projects/myapp
  Required Python: 3.11 (from project config)
  Virtual env:    ./.venv [✅ synced]
  Venv Python:    3.11.10
  Packages:       42 installed
  Last used:      2025-04-20T18:30:00+00:00
```

### Health check

```bash
$ pyversion check

🔎 pyversion check

  ✅ Python requirement: 3.11
  ✅ Python 3.11 available at /usr/local/bin/python3.11
  ✅ Virtual environment exists at ./.venv
  ✅ Venv synced with Python 3.11.10
  ✅ pip functional (pip 24.x)

✅ Everything looks good!
```

### Manage Python versions

```bash
$ pyversion versions

🐍 Installed Python versions (pyversion-managed)

  ● Python 3.11 (3.11.10)  ~/.pyversion/versions/3.11/bin/python3
  ● Python 3.12 (3.12.7)   ~/.pyversion/versions/3.12/bin/python3

System Pythons (not managed by pyversion):
  ○ python3.13 → 3.13.0  (/usr/local/bin/python3.13)
  ○ python3    → 3.13.0  (/usr/local/bin/python3)
```

### Clean up orphaned versions

```bash
$ pyversion cleanup

🧹 pyversion cleanup

  Managed Python versions:

  Python 3.11  [✅ active (2 projects)]
    · /Users/you/projects/api-server
    · /Users/you/projects/data-pipeline

  Python 3.10  [⚠ orphaned (no registered projects)]  (312 MB)

  ⚠  Found 1 version with no active projects:
    · Python 3.10  (312 MB)

  Remove these 1 version(s)? [y/N] y

  ✅ Removed Python 3.10  (312 MB freed)
  ✅ Done. 312 MB freed.
```

Use `--dry-run` to preview without deleting anything:

```bash
pyversion cleanup --dry-run
```

### Initialize a new project

```bash
$ pyversion init

🚀 pyversion init

  Which Python version should this project use?
    1. Python 3.9
    2. Python 3.10
    3. Python 3.11
    4. Python 3.12
    5. Python 3.13

  Enter number or version: 4

  ✅ Created .python-version → 3.12

  Next: run pyversion pip install -r requirements.txt to set up your environment.
```

### Fix PATH (if needed)

```bash
pyversion setup-path
```

---

## How it works

Every time you run `pyversion pip <args>`, six things happen automatically:

```
1. DETECT   Read .python-version or pyproject.toml
            → "This project needs Python 3.11"

2. ENSURE   Check if Python 3.11 is installed
            → If not: download precompiled binary (~30 seconds)
            → If yes: skip

3. VALIDATE Check the virtual environment for 11 potential failure modes:
            · Missing python or pip binaries
            · Broken symlinks
            · Version mismatch between venv and requirement
            · pyvenv.cfg disagreement
            · The Python that built the venv has since been deleted
            · And more

4. REPAIR   If anything is wrong, rebuild automatically
            → Saves your installed packages first
            → Rebuilds with the correct Python
            → Reinstalls packages

5. RUN      Execute pip in the correct environment
            → .venv/bin/pip install requests

6. TRACK    Register this project in ~/.pyversion/registry.json
            → Powers cleanup's orphan detection
```

### Python version detection

pyversion reads from these files, in priority order:

| File | Format | Example |
|------|--------|---------|
| `.python-version` | Plain version string | `3.11` |
| `pyproject.toml` | `requires-python` field | `>=3.11` |
| `setup.cfg` | `python_requires` option | `>=3.11` |
| `setup.py` | `python_requires` keyword | `">=3.11"` |
| `.tool-versions` | asdf/mise format | `python 3.11.5` |

All common PEP 440 specifiers are supported: `>=3.11`, `~=3.11.0`, `==3.11.*`, `^3.11`.

### Python installation

When a required Python version isn't on your system, pyversion downloads a precompiled binary from [python-build-standalone](https://github.com/astral-sh/python-build-standalone) — the same source used by `uv` and `rye`.

- **No compilation** — prebuilt binaries, not source builds
- **Fast** — typically under 30 seconds
- **Cached** — subsequent installs of the same version skip the download
- **Stored in** `~/.pyversion/versions/<version>/`

Supports macOS on both Intel (`x86_64`) and Apple Silicon (`aarch64`).

### Venv sync detection

pyversion detects 11 ways a virtual environment can be broken or out of date:

| Issue | What it means |
|-------|--------------|
| `venv_missing` | `.venv` directory doesn't exist |
| `python_missing` | `bin/python` binary is gone |
| `python_broken_link` | `bin/python` is a symlink pointing to a deleted file |
| `python_not_executable` | Binary exists but isn't executable |
| `pip_missing` | `bin/pip` is gone |
| `pyvenv_cfg_missing` | `pyvenv.cfg` is absent |
| `version_mismatch` | Venv Python ≠ project requirement |
| `cfg_version_mismatch` | `pyvenv.cfg` disagrees with the actual binary |
| `home_python_gone` | The Python that created the venv no longer exists |
| `pip_outdated` | pip version is below 22.0 |
| `metadata_missing` | pyversion's tracking file is absent |

When any of the first nine are detected, pyversion automatically rebuilds the venv — saving your installed packages, recreating with the correct Python, and reinstalling. You never have to diagnose these manually.

---

## Real-world scenarios

### New developer, fresh clone

```bash
$ git clone github.com/yourcompany/api-server
$ cd api-server
$ pyversion pip install -r requirements.txt

🔍 Detecting Python requirement...
   → Project requires Python 3.11 (from pyproject.toml)

🐍 Ensuring Python 3.11 is available...
   → Python 3.11 not found locally. Installing...
   → Downloading Python 3.11.10...
     [████████████████████] 100%
   → Extracting to ~/.pyversion/versions/3.11...
   → Verified: Python 3.11.10
   ✅ Python 3.11 installed

📦 Setting up virtual environment...
   → Creating .venv with Python 3.11...
   ✅ Virtual environment ready: ./.venv

✔️  Validating environment...
   ✅ Environment synced with Python 3.11.10

⚙️  Running pip install -r requirements.txt...

Installing collected packages: django, requests, psycopg2...
Successfully installed django-4.2.7 requests-2.31.0 psycopg2-2.9.7

✅ Command completed successfully
```

**First run: ~45 seconds** (includes Python download). Every run after: under 2 seconds.

---

### Version mismatch auto-fix

```bash
# Someone ran `python3.12 -m venv .venv` by mistake
# but pyproject.toml says requires-python = ">=3.11,<3.12"

$ pyversion pip install flask

📦 Setting up virtual environment...
   ⚠  Venv has issues — rebuilding:
      · Venv Python version does not match project requirement

   → Saved 12 package(s) from old venv
   → Creating .venv with Python 3.11...
   → Reinstalling packages into new venv...
   ✅ Venv rebuilt with Python 3.11

✔️  Validating environment...
   ✅ Environment synced with Python 3.11.10

⚙️  Running pip install flask...

✅ Command completed successfully
```

---

### Switching between projects

```bash
$ cd ~/projects/api-server        # requires Python 3.11
$ pyversion pip list
✅ Environment synced with Python 3.11.10
...

$ cd ~/projects/ml-pipeline       # requires Python 3.12
$ pyversion pip list
✅ Environment synced with Python 3.12.7
...

$ cd ~/projects/legacy-app        # requires Python 3.9
$ pyversion pip install -r requirements.txt
✅ Environment synced with Python 3.9.20
...
```

Zero manual activation. Zero version flags. Just `cd` and work.

---

## Why not just use...

### pyenv + venv
pyenv is excellent at managing Python versions, but it doesn't manage virtual environments. You still have to create, activate, and maintain venvs manually. Forget to activate? Wrong packages. Switch projects? Re-activate. pyversion does all of this for you automatically.

### Poetry
Poetry is a full dependency manager with its own lock file format, its own CLI, and its own way of thinking about projects. It's powerful but requires adopting its entire workflow. pyversion wraps pip — no new concepts, no lock files, no configuration. If you know pip, you know pyversion.

### conda
conda is a complete package ecosystem designed for data science workloads. It's large, slow to solve environments, and installs a lot of infrastructure. pyversion is 500 lines of Python with zero dependencies beyond the stdlib.

### uv
uv is extremely fast and excellent at what it does. pyversion and uv aren't really competing — uv is a pip replacement, pyversion is an orchestration layer. They can coexist. That said, pyversion's goal is maximum simplicity: one command, no new mental model.

### Docker
Docker solves environment isolation across machines and teams. pyversion solves it on your local machine. Both have their place.

---

## Project layout

```
pyversion/
├── pyversion/
│   ├── __init__.py
│   ├── __main__.py          # CLI entry point and command orchestration
│   ├── version_manager.py   # Python version detection and installation
│   ├── environment_manager.py  # Virtual environment lifecycle
│   ├── pip_wrapper.py       # Routes pip to the correct venv
│   ├── sync.py              # SyncChecker — 11-issue venv health detection
│   └── registry.py          # Project→Python version tracking
├── tests/
│   ├── conftest.py          # Shared fixtures (fake_venv factory, etc.)
│   ├── test_sync.py         # 30+ tests for SyncChecker
│   ├── test_registry.py     # 24 tests for Registry
│   └── test_version_manager.py  # 40 tests for version detection/parsing
├── install.sh               # One-shot installer with PATH setup
└── pyproject.toml
```

---

## Development

```bash
git clone https://github.com/twinboi90/pyversion.git
cd pyversion
pip install -e ".[dev]"

# Run tests
pytest

# Run tests with coverage
pytest --cov=pyversion --cov-report=term-missing
```

94 tests, zero external dependencies beyond the stdlib.

---

## Roadmap

**Phase 1 ✅ — Core**
- `pyversion pip` with full auto-orchestration
- Config file detection (5 formats)
- Precompiled Python installation
- Virtual environment management
- macOS support (Intel + Apple Silicon)

**Phase 2 ✅ — Robustness**
- 11-mode venv sync detection and auto-repair
- Project registry for cleanup intelligence
- Interactive `pyversion cleanup` with disk usage
- 94-test suite

**Phase 3 — Expansion** *(in progress)*
- Windows PowerShell support
- Linux support
- IDE integration
- `pyversion init` improvements

---

## License

MIT
