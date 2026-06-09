# Quant Desk

Monorepo for the Quant Desk stack. One shared Python venv at the root,
each module is its own folder with its own `pyproject.toml`, all of them
installed editably into that one venv.

**Ubuntu Linux only.** Windows support was dropped (the old `.bat`
launchers are gone). If Windows is ever needed again it's a separate
refactor.

## Layout

```
Quant Desk/
  .venv/                         shared Python virtual environment
                                 (created by first_install/install.sh)
  .vscode/settings.json          points VSCode at the shared venv
  requirements-dev.txt           shared research / scratch deps (matplotlib,
                                 scipy, jupyter, etc.) -- not owned by any
                                 specific module

  first_install/                 environment bootstrap (owns the venv)
    install.sh                   create venv + install all modules + research libs
    modules.txt                  manifest: which module folders to install
    README.md                    how the bootstrap works

  NSW/                           data loader            (done)
    pyproject.toml               -> installable as `nsw`
    start_nsw.sh                 launch the setup/data server (assumes venv exists)
    nsw/                         the package
    candles.db                   SQLite store (NSW-owned data)
    config.json                  Fyers credentials (NSW-owned, gitignored)

  TA/                            technical analysis    (next)
    pyproject.toml               -> installable as `ta`, depends on nsw

  quantdesk/                     backtester             (future)
    pyproject.toml               -> installable as `quantdesk`, depends on nsw

  viz/                           results & visualization (future)
  live/                          live deployment        (future)

  Project1 - Original/           legacy codebase, untouched, reference only
```

## How setup is split

There are exactly two kinds of script and they don't overlap:

| Concern | Owner |
|---|---|
| Create / upgrade the shared venv | `first_install/install.sh` |
| Install every module (editable) + research libs | `first_install/install.sh` |
| Run a module (e.g. NSW's data server) | that module's own launcher (`NSW/start_nsw.sh`) |

`first_install` is the **only** thing that creates or modifies the venv.
Module launchers assume the venv exists and just run. This keeps
"set up the environment" cleanly separate from "use a module".

Because modules are installed **editable** (`pip install -e`):

- pandas, numpy, flask, fyers-apiv3, etc. are installed ONCE in `.venv`.
- `from nsw.loader import load_data` works from any module's code.
- Editing a module's source is live immediately — no reinstall.
- Only **dependency** changes or a **new module** need a re-run of
  `first_install/install.sh`.

## First-time setup on a new machine

1. Install Python 3.12 and the bits matplotlib needs for chart windows:
   ```bash
   sudo apt update
   sudo apt install python3.12 python3.12-venv python3-tk git
   ```
2. Get the workspace onto the machine (clone module repos, copy the rest).
   Today the only module is `NSW/` (its own repo, see Backups below).
3. Bootstrap the environment — this builds `.venv` and installs everything:
   ```bash
   ./first_install/install.sh
   ```
   ~2–3 minutes the first time, seconds on re-runs.
4. Run NSW's setup/data server and authenticate with Fyers:
   ```bash
   cd NSW && ./start_nsw.sh
   ```
   Open `https://127.0.0.1:5001/`, accept the self-signed cert
   (Advanced → Proceed), paste your Fyers App ID + Secret Key, and
   authenticate. Tokens expire daily — re-auth here each trading day.
5. Open Quant Desk as a VSCode workspace. The Python extension picks up
   `.venv/` automatically (pinned in `.vscode/settings.json`). Use the
   play button or Ctrl+F5 to run scripts.

## Shared research libraries (matplotlib, scipy, jupyter, etc.)

Anything that doesn't belong to a specific module lives in
`requirements-dev.txt`. You don't install it separately — `first_install`
already does. If you add libraries to that file, just re-run:

```bash
./first_install/install.sh
```

> `python3-tk` (a system package, step 1 above) is what lets matplotlib
> actually open windows via `plt.show()`. Without it, matplotlib falls
> back to a non-interactive backend and charts silently never appear.

## Adding a new module later

1. Create `Quant Desk/<newmodule>/` with a `pyproject.toml`.
2. Add one line to `first_install/modules.txt`: the folder name.
3. Run `./first_install/install.sh`.

Now `from <newmodule> import ...` works from any script in the shared venv.
Give the module its own launcher (mirror `NSW/start_nsw.sh`) only if it
needs to start a long-running process; pure libraries don't need one.

## Backups

Each module has its own git repo (NSW backs up to
<https://github.com/ForeSight-Research-Unlimited/quant-desk-nsw>).
Run the module's own `backup.sh`.

## Why the import error you might hit: `from package.submodule import x` vs `import package`

These do different things in Python:

```python
from nsw.loader import load_data    # ONLY puts `load_data` in scope.
                                    # The name `nsw` is NOT available.

import nsw                          # Puts `nsw` (the package) in scope.
                                    # Now `nsw.__version__` works.
```

To use both `load_data(...)` and `nsw.<anything>` in the same script,
you need both lines.
