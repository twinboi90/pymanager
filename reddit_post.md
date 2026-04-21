# Title: I built pymanager — one command that handles Python versions, venvs, and pip automatically

---

**The problem:** You have three Python projects. Each needs a different Python version. Every time you switch between them, something breaks.

The actual workflow most of us put up with today:

```bash
# project-a setup
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# switch to project-b
deactivate
cd ../project-b
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# forget to activate, install into wrong environment
# wonder why imports break
# start over
```

This is a rite of passage in Python development — and it shouldn't be.

---

**The solution:**

```bash
pip install pymanager-cli
```

Then replace `pip` with `pymanager pip`:

```bash
pymanager pip install -r requirements.txt
```

That's it. Here's what happens automatically every time:

```
🔍 Detecting Python requirement...
   → Project requires Python 3.11 (from pyproject.toml)

🐍 Ensuring Python 3.11 is available...
   ✅ Python 3.11 already installed

📦 Setting up virtual environment...
   ✅ Virtual environment ready: ./.venv

✔️  Validating environment...
   ✅ Environment synced with Python 3.11.10

⚙️  Running pip install -r requirements.txt...

Successfully installed django-4.2.7 requests-2.31.0
✅ Command completed successfully
```

Switch to another project? Just `cd` and run again. No activation, no version flags, no thinking.

---

**How it works (the non-magic version):**

1. **Detects** Python version from `.python-version`, `pyproject.toml`, `setup.cfg`, `setup.py`, or `.tool-versions`
2. **Installs** that Python version if it's missing — downloads precompiled binaries from python-build-standalone (same source as uv/rye), typically under 30 seconds
3. **Validates** the virtual environment against 11 failure modes: missing binaries, broken symlinks, version mismatches, deleted home Python, outdated pip, and more
4. **Auto-repairs** if anything is wrong — saves your installed packages, rebuilds with the correct Python, reinstalls
5. **Runs** pip in the correct environment
6. **Registers** the project in `~/.pymanager/registry.json` for cleanup intelligence

---

**Other commands:**

```bash
pymanager status     # Show current Python, venv state, package count
pymanager check      # Validate everything, list any issues
pymanager versions   # List pymanager-managed Python versions
pymanager cleanup    # Find and remove orphaned Python versions (with disk usage)
pymanager init       # Set Python version for a new project
```

---

**Why not just use...?**

- **pyenv + venv**: pyenv is great at version management, but you still create and activate venvs manually. Forget once? Wrong packages. pymanager does it for you.
- **Poetry**: Full dependency manager with its own lock file format and CLI. Powerful, but requires adopting an entirely different workflow. pymanager just wraps pip — if you know pip, you know pymanager.
- **uv**: uv is extremely fast at what it does (pip replacement). pymanager is an orchestration layer — they can actually coexist.
- **conda**: Bloated, slow to solve, designed for data science. pymanager is ~500 lines of Python with zero dependencies beyond the stdlib.

---

**Install:**

```bash
# Homebrew (macOS)
brew install twinboi90/tap/pymanager

# pip
pip install pymanager-cli
```

GitHub: https://github.com/twinboi90/pymanager

94 tests. Zero external dependencies. macOS (Intel + Apple Silicon). Linux and Windows on the roadmap.

Would love feedback — especially from anyone who's dealt with the venv activation dance on a daily basis.
