# first_install — Quant Desk environment bootstrap

This folder owns **one job**: building the shared Python environment that every
Quant Desk module runs in. It is the *only* place allowed to create or modify
the venv. Nothing else — not NSW, not future modules — touches the venv setup.

## Why this exists

Early on, `NSW/start_nsw.sh` did everything: find Python, create the venv,
install deps, copy config, launch the server. That tangled "set up the
environment" together with "run NSW", so setup felt fragmented (research libs
were a separate manual step, dependency conflicts surfaced at launch time,
etc.).

Now the split is clean:

| Concern | Owner |
|---|---|
| Create/upgrade the shared venv | `first_install/install.sh` |
| Install every module (editable) | `first_install/install.sh` |
| Install shared research libs | `first_install/install.sh` |
| Run NSW's data/setup server | `NSW/start_nsw.sh` |
| Run future modules | each module's own launcher |

Per-module launchers assume the venv exists and just run. If it doesn't, they
tell you to run this.

## What `install.sh` does

1. Finds a Python (prefers `python3.12` → `python3.11` → `python3`).
2. Creates the shared venv at `<workspace root>/.venv` if missing.
3. Upgrades pip.
4. Editable-installs every module listed in `modules.txt` (`pip install -e`).
5. Installs the shared research libs from `../requirements-dev.txt`
   (matplotlib, scipy, jupyter, etc.).
6. Pins `websocket-client==1.6.1` last — Fyers needs it exactly, the jupyter
   stack tries to bump it (see `KNOWN_BUGS.md` #11).
7. Smoke-checks that `nsw` and the research libs import.

It is **idempotent** — safe to run any time. Existing venv is reused, installs
are no-ops when already satisfied.

## How to run

```bash
# from the workspace root
./first_install/install.sh
```

First run: ~2–3 minutes (builds the venv, downloads wheels). Re-runs: seconds.

### Prerequisites (Ubuntu)

```bash
sudo apt update
sudo apt install python3.12 python3.12-venv python3-tk
```

`python3-tk` is what lets matplotlib actually open chart windows (`plt.show()`);
without it matplotlib falls back to a non-interactive backend.

## When to re-run

- You **added a module** → add its folder to `modules.txt`, then re-run.
- You **changed a module's dependencies** (`pyproject.toml`) → re-run.
- You **changed `requirements-dev.txt`** → re-run.

Editing a module's **code** does *not* require a re-run — modules are installed
editable, so source changes are live immediately.

## Adding a new module

1. Create the module folder with its own `pyproject.toml` (e.g. `TA/`).
2. Add one line to `modules.txt`: the folder name (`TA`).
3. Run `./first_install/install.sh`.

That's it — `from ta import ...` now works from any script in the shared venv.

## Files

```
first_install/
├── install.sh     the bootstrap orchestrator
├── modules.txt    list of module folders to editable-install
└── README.md      this file
```

Note: the venv itself lives at the **workspace root** (`../.venv`), not in this
folder. This folder only holds the logic that builds it.
