# Quant Desk — Known Bugs & Footguns

Things that have bitten us before, with the exact fix. If you hit a
weird error, scan this file first before deep-diving.

> **OS note (2026-05-18):** Most entries below are Windows-specific.
> Entries #1, #2, #3, and #5 should not occur on Linux / macOS at all
> (no .bat parsing, faster imports without Defender real-time scanning,
> prebuilt aiohttp wheels for every Python on PyPI). Entry #9 (debugpy
> cold-start) is much rarer on Linux but theoretically possible.
> Entries #4, #6, #7, #8 are cross-platform and still apply.

---

## 1. `KeyboardInterrupt` while importing numpy / pandas on first run

**Symptom**

```
File "D:\...\test1.py", line 1, in <module>
    import numpy as np
  ...
  File "<frozen importlib._bootstrap_external>", line 753, in _compile_bytecode
KeyboardInterrupt
```

The traceback ends in `_compile_bytecode` and `KeyboardInterrupt`. No code
fault — Python was compiling numpy's `.py` files into `.pyc` cache when
something interrupted it.

**Why it happens**

On the first import of a large package (numpy especially), Python compiles
hundreds of source files to bytecode. This takes 3-8 seconds. If you click
the red "Stop" button in VSCode's debug toolbar, press Ctrl+C in the
terminal, or close the terminal during that window, you'll see this.

Subsequent runs are instant because the `.pyc` files are cached. But if
the interrupt happened mid-write, you can end up with a half-written
`.pyc` that confuses Python on the next import too.

**Fix**

Clear the corrupted numpy bytecode cache. Run this exact one-liner in
CMD or PowerShell:

```cmd
"D:\KCF Capital\FRU\Claude\Claude Co-Work\Quant Desk\.venv\Scripts\python.exe" -c "import shutil, glob; [shutil.rmtree(p, ignore_errors=True) for p in glob.glob(r'D:\KCF Capital\FRU\Claude\Claude Co-Work\Quant Desk\.venv\Lib\site-packages\numpy\**\__pycache__', recursive=True)]"
```

What it does: walks the numpy site-packages tree under the shared venv,
deletes every `__pycache__` folder it finds. Next run regenerates them
cleanly.

Same pattern works for any other package that gets stuck — replace
`numpy` with `pandas`, `matplotlib`, etc.

**Prevention**

When you launch a script for the first time after installing fresh
packages, just wait. Don't touch the debug toolbar for 10 seconds.

---

## 2. Stale `.pyc` bytecode after code edits

**Symptom**

You edit a `.py` file, save it, re-run, and the OLD code's behaviour
shows up. Tracebacks point at line numbers that don't match the source
on disk (e.g. "RuntimeError at line 222" but line 222 is a docstring).

**Why it happens**

Python caches compiled bytecode in `__pycache__` folders. Normally it
detects when the `.py` is newer than the `.pyc` and recompiles. On
Windows / mounted filesystems / some editors, the mtime check
occasionally fails and Python keeps using the stale `.pyc`.

**Fix**

Delete the relevant `__pycache__` folder and re-run. For NSW:

```cmd
rmdir /s /q "D:\KCF Capital\FRU\Claude\Claude Co-Work\Quant Desk\NSW\nsw\__pycache__"
```

As of 2026-05-18 `start_nsw.bat` no longer wipes pyc on every launch
(see bug #9 for why that was removed). If you hit this, run the
`rmdir` manually.

---

## 3. `start_nsw.bat` / `backup.bat` window closes immediately on double-click

**Symptom**

You double-click a `.bat` file. A CMD window flashes open and shuts
before you can read anything. No error visible.

**Why it happens**

CMD reads `.bat` files as ANSI by default. If the file is saved as UTF-8
and contains non-ASCII characters (em-dashes `—`, smart quotes `""`,
etc.), CMD's parser misinterprets the multi-byte sequences as control
bytes and silently exits.

**Fix**

We rewrote both `.bat` files to be pure ASCII (`REM` instead of `::`,
`--` instead of `—`, plain `"` instead of `"`). If you edit them, keep
it ASCII-only.

**Diagnostic**

To see what's actually happening, open a CMD window manually (Win+R
→ `cmd`), `cd` to the folder, and run the .bat by name. The window stays
open even if the .bat exits, so you can read the error.

---

## 4. `NameError: name 'nsw' is not defined` vs `ModuleNotFoundError: No module named 'nsw'`

**These are different problems. Read the error type carefully.**

**`ModuleNotFoundError`** = the package isn't installed in the active
venv. Run `pip install -e .` from the package folder, or check which
Python interpreter your IDE is using.

**`NameError`** = the package IS installed, but your script never put
the name in scope. Common cause:

```python
from nsw.loader import load_data    # ONLY imports `load_data`, not `nsw`
print(nsw.__version__)               # NameError — `nsw` was never imported
```

**Fix**

```python
import nsw                           # adds `nsw` to scope
from nsw.loader import load_data     # adds `load_data` to scope
```

`from package.submodule import x` does NOT bring `package` itself into
your namespace. You need both imports.

---

## 5. `aiohttp` build fails on Python 3.13 — `Cannot open include file: 'io.h'`

**Symptom**

```
Building wheel for aiohttp (pyproject.toml) ... error
  C:\Python313\include\pyconfig.h(59): fatal error C1083:
    Cannot open include file: 'io.h': No such file or directory
```

**Why it happens**

`fyers-apiv3` pins `aiohttp==3.9.3` exactly. aiohttp 3.9.3 has no
prebuilt wheel for Python 3.13 on Windows, so pip falls back to building
it from source. The build needs the Windows SDK headers (`io.h`,
`windows.h`, etc.). If the SDK component isn't installed, the compile
fails.

**Two fixes — pick one**

**A. Use Python 3.12 instead** (~30 MB install, no SDK needed).
Python 3.12 has prebuilt wheels for aiohttp 3.9.3. Install from
<https://python.org/downloads/release/python-3127/>. `start_nsw.bat`
already prefers `py -3.12` if it's available.

**B. Install the Windows SDK** (~3-5 GB). Open Visual Studio Installer
→ Modify → Individual Components → tick "Windows 11 SDK
(10.0.26100.0)" → Modify. This lets cl.exe find `io.h` and any future
C-extension package builds from source successfully.

---

## 6. NSW server returns 500 / `config.json is not valid JSON: Expecting value: line 1 column 1 (char 0)`

**Symptom**

Visiting `https://127.0.0.1:5001/` returns 500. CMD shows
`ConfigError: ... config.json is not valid JSON`.

**Why it happens**

`config.json` is empty or has only whitespace. Usually because an
editor accidentally saved it blank, or a crash truncated it
mid-write.

**Fix**

`nsw/config.py::ensure_config_exists()` now auto-recovers: it detects
empty/invalid `config.json`, renames it to `config.json.corrupt-<ts>.bak`,
and recreates a fresh one from `config.example.json`. Just restart the
server. You'll need to re-paste your Fyers App ID + Secret Key on the
setup page.

If for some reason auto-recovery doesn't fire (very old build), force it:

```cmd
cd "D:\KCF Capital\FRU\Claude\Claude Co-Work\Quant Desk\NSW"
copy /y config.example.json config.json
```

Then restart `start_nsw.bat`.

---

## 7. Fyers history returns `{"s": "no_data"}` and the backfill keeps retrying

**Symptom**

```
WARNING [nsw.fyers_client] Fyers history attempt 1/3 for ... failed:
  {'candles': [], 'message': '', 's': 'no_data'}
... attempt 2/3 ...
... attempt 3/3 ...
ERROR Job backfill-... failed
RuntimeError: Fyers history failed after 3 attempts ...
```

**Why it happens**

`no_data` is Fyers' legitimate "you've gone past my earliest-available
history" signal — not an error. Older NSW builds treated any non-`ok`
status as retryable, which caused this loop.

**Fix**

Already patched in `nsw/fyers_client.py::fetch_history`. We now treat
`no_data` (and substring variants like "no data available") as a clean
empty result, return `[]`, and the backfill loop interprets that as
"floor reached, stop and record." If you still see this error,
your `.pyc` cache is stale — see bug #2.

---

## 8. Fyers access token has expired

**Symptom**

```
RuntimeError: No Fyers access_token. Authenticate via the setup page first.
```

or, when running an update:

```
WARNING ... Fyers history failed: {'s': 'error', 'message': 'invalid_token'}
```

**Why it happens**

Fyers access tokens expire **daily** (typically end of trading day,
around midnight IST). The token saved in `config.json` becomes invalid.

**Fix**

Open the setup page at `https://127.0.0.1:5001/` (run `start_nsw.bat`
if it isn't already up), click **Open Fyers Login**, approve in the
new tab, you'll bounce back to `/` showing **Connected**. Now updates /
backfills work again.

This is part of normal daily operation, not a bug.

---

## 9. `KeyboardInterrupt` in `database.get_candles` on a debugger run after `start_nsw.bat`

**Symptom**

```
File "...\test1.py", line 10, in <module>
    data1 = load_data("NIFTY", "1m")
  File "...\nsw\loader.py", line 143, in load_data
    rows = database.get_candles(...
  File "...\nsw\database.py", line 173, in get_candles
    return [dict(r) for r in conn.execute(query, params).fetchall()]
                             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
KeyboardInterrupt
```

The traceback ends in `dict(r)` inside the SQLite listcomp. You didn't
press Ctrl+C. Re-running immediately works.

**Why it happens**

This is the same family as bug #1 (deferred SIGINT lands at the first
Python-bytecode checkpoint after a long C-extension stretch) — but the
trigger isn't numpy bytecode compilation. The trigger is:

1. `start_nsw.bat` used to wipe `nsw\__pycache__` on every launch
   (removed 2026-05-18, see commit / `start_nsw.bat` history).
2. The next time test1.py imports `nsw`, all 10 nsw modules
   recompile to `.pyc`. Cold matplotlib font-cache build sometimes
   piles on. ~3–5s of cold-import time.
3. F5 in VSCode launches via `debugpy 2026.6.0`'s launcher, which
   does a handshake with the VSCode debug adapter during that cold
   window. Something in that handshake doesn't tolerate the delay
   and sends a SIGINT to the Python process.
4. Python can't service the signal while it's in C extensions
   (imports, sqlite3.fetchall). The signal queues. As soon as Python
   regains control at the first bytecode checkpoint — which happens
   to be the `dict(r)` listcomp — `KeyboardInterrupt` is raised.

The site that gets blamed has nothing to do with the cause. It's just
where Python first got a chance to look at the signal queue.

**Fixes — pick one or both**

**A. Use Ctrl+F5 (Run Without Debugging) instead of F5.** Ctrl+F5
invokes the "Python: Run Python File" command, which spawns
`python script.py` directly with no debugpy launcher in the chain.
Bug is impossible without debugpy. Use F5 only when you actually
need breakpoints, and pre-warm by running once with Ctrl+F5 first.

**B. (Already applied 2026-05-18)** Remove the unconditional pyc
wipe from `start_nsw.bat`. Closes the cold-import window that
debugpy reacts badly to. Python's `.py`-vs-`.pyc` mtime check handles
real staleness on local NTFS. If you ever do hit stale bytecode after
an nsw edit, use the manual `rmdir` from bug #2.

**Bonus speedup**

If your venv lives on a slow disk and Windows Defender real-time
scanning is enabled, add `D:\KCF Capital\FRU\Claude\Claude Co-Work\Quant Desk\.venv\`
to Defender exclusions. First-run imports get noticeably faster and
debug-launch races get less likely.

---

## 10. `ModuleNotFoundError: No module named 'matplotlib'` running a research script

**Symptom**

```
File ".../test1.py", line 3, in <module>
    import matplotlib.pyplot as plt
ModuleNotFoundError: No module named 'matplotlib'
```

**Why it happens**

The NSW launcher (`start_nsw.sh`) installs only NSW's own deps (pandas,
numpy, flask, fyers-apiv3). NSW does data, not plotting — matplotlib and
friends live in the **shared research libs** (`requirements-dev.txt`),
which is a separate, optional install. A fresh venv won't have them.

**Fix**

```bash
cd "<Quant Desk root>"
./.venv/bin/pip install -r requirements-dev.txt
```

---

## 11. `websocket-client` version conflict: fyers-apiv3 vs jupyter-server

**Symptom**

After installing `requirements-dev.txt`, pip prints:

```
fyers-apiv3 3.1.13 requires websocket-client==1.6.1, but you have
websocket-client 1.9.0 which is incompatible.
```

(or the inverse: `jupyter-server 2.19.0 requires websocket-client>=1.7`).

**Why it happens**

`fyers-apiv3` pins `websocket-client==1.6.1` **exactly**. The Jupyter
stack (`jupyter-server`) requires `>=1.7`. Both share the one venv, so
they can't both be satisfied. Whichever package pip installs last wins
and bumps the other out.

**Fix**

Fyers is load-bearing for the data layer, so we pin to **1.6.1**.
`requirements-dev.txt` now pins `websocket-client==1.6.1`, which lets
pip's resolver pick a *consistent* set on its own — it downgrades
`jupyter-server` to 2.13.0 (which is happy with 1.6.1), so there's no
conflict warning and the Jupyter notebook server works too. Plain `.py`
scripts, plotting, `ipython`, scipy, sklearn never import `websocket`
anyway. `first_install/install.sh` also re-pins 1.6.1 as its last step
(belt and suspenders).

This is handled automatically now — just run `./first_install/install.sh`.
Verify the data path after any dependency change:

```bash
./.venv/bin/python -c "from nsw import fyers_client; from nsw.loader import load_data; print(len(load_data('NIFTY','1m')))"
```

---

## How to add a new entry to this file

Hit a bug we haven't logged yet? Add a new section in the same shape:
**Symptom** (the exact error you saw, paste it verbatim) →
**Why it happens** → **Fix** (exact command or steps). Future-you and
future-me will thank you.
