# Quant Desk — Ubuntu migration checklist

Scan run 2026-05-25 across the live tree (NSW, TA, root). `Project1 - Original/` is reference-only and excluded — its Windows backslash paths and PyQt `app.exec_()` calls don't matter unless you decide to revive any of it later.

## TL;DR

**The codebase is already ~95% Ubuntu-ready.** The 2026-05-18 cross-platform pass did the heavy lifting: `.sh` launchers exist next to every `.bat`, all NSW Python is portable, no Windows-only deps (`pywin32`, `win32com`, `pythoncom`, `msvcrt`, `winreg`) are imported anywhere in your code (only in third-party packages inside `.venv/`, which get reinstalled with their Linux equivalents). TA is empty, so nothing to migrate there. The shell scripts are already LF-terminated and Ubuntu-aware (they specifically reference `apt install python3.12-venv`).

The only real residue is **cosmetic / config** — a few doc strings and one VSCode path that still say `\.venv\Scripts\python.exe`. None of it blocks the project from running.

## On Ubuntu, Claude Code is fine

Yes — everything we've been doing translates cleanly. Claude Code on Ubuntu uses the same file/edit/bash primitives we've been using here, runs natively (no WSL needed), and is actually the more common dev environment for it. You lose Cowork's GUI bits (live artifacts, the AskUserQuestion widget, scheduled-tasks UI), but the working pattern — you write goals, Claude proposes/edits, you run on your machine and paste output — is identical. The HANDOFF.md flow ("paste this whole document into a new conversation") works the same way.

## Migration steps, in order

### 1. Before wiping Windows

- **Push the NSW repo one last time.** `cd NSW; ./backup.sh` (or `.bat`) so GitHub has the latest commit.
- **Copy the whole `Quant Desk\` folder to external media or cloud** — Project1 isn't on GitHub anywhere (and shouldn't go on a public anywhere because of the committed Upstox creds; see [[project_quantdesk_security]] memory). Same for `Project1 - Original_OVERVIEW.md`, the audit docs, KNOWN_BUGS, and HANDOFF.
- **Note your live Fyers app_id / secret_key** from `NSW/config.json` somewhere safe before transferring. The file is gitignored so it's not in the GitHub backup.
- **Don't bother copying `.venv/`** — recreate fresh on Ubuntu. It's 600 MB+ of Windows wheels that won't run on Linux anyway.
- **Don't bother copying `candles.db`** unless you want to skip the 5-year backfill on Ubuntu. It's gitignored. SQLite is cross-platform, so copying it works — the file is portable. Your call.

### 2. On fresh Ubuntu (assuming Ubuntu 22.04+ or 24.04)

```bash
# Python 3.12 (or 3.11) — what start_nsw.sh wants
sudo apt update
sudo apt install python3.12 python3.12-venv python3-pip git

# git identity
git config --global user.name "ForeSight Research Unlimited"
git config --global user.email "foresightresearchunlimited@gmail.com"

# Line endings: LF for everything on Linux
git config --global core.autocrlf input

# Re-clone NSW from GitHub (cleaner than copying)
mkdir -p ~/quantdesk && cd ~/quantdesk
git clone https://github.com/ForeSight-Research-Unlimited/quant-desk-nsw.git NSW

# Copy the rest of the workspace from your backup:
#   HANDOFF.md, KNOWN_BUGS.md, CODE_AUDIT_2026-05-18.md, README.md,
#   NSW_CODE_REVIEW.md, Project1 - Original_OVERVIEW.md,
#   requirements-dev.txt, test1.py, Project1 - Original/, TA/
# (everything except .venv/ and NSW/, which you've already handled)

# First launch — creates the shared venv automatically
cd NSW
chmod +x *.sh
./start_nsw.sh
```

The launcher script will: detect Python, create `.venv/` at the workspace root, install NSW + deps, copy `config.example.json → config.json`, and start the setup server at `https://127.0.0.1:5001/`. From there you paste your Fyers app_id/secret and re-auth.

### 3. Things to fix on the new box (small, optional)

These are paper cuts, not blockers:

**`.vscode/settings.json`** still pins the interpreter at the Windows path:
```json
"python.defaultInterpreterPath": "${workspaceFolder}\\.venv\\Scripts\\python.exe"
```
On Linux this should be:
```json
"python.defaultInterpreterPath": "${workspaceFolder}/.venv/bin/python"
```
VSCode on Linux will fall back to the system Python if the pinned path is missing, so it won't break — but you'll want to fix it so VSCode actually uses the shared venv.

**`NSW/MANUAL.md:505`** has a doc example with `cd "D:\KCF Capital\...\NSW"` — purely documentation; update when you next touch the file.

**`NSW/examples/test_everything.py:4-7`** docstring says `"..\\.venv\\Scripts\\python.exe"` — same thing, just a comment.

**`requirements-dev.txt:8-10`** has a Windows-style install example in a comment. Trivial.

**NSW's local git config** carries Windows defaults from when the repo was created:
```
core.filemode=false
core.ignorecase=true
core.symlinks=false
```
On Linux you probably want `filemode=true` (so the +x bit on `.sh` files is tracked) and `ignorecase=false` (case-sensitive filesystem). Run from `NSW/`:
```bash
git config core.filemode true
git config core.ignorecase false
```
Then `chmod +x *.sh` and commit if the mode change is tracked.

**No `.gitattributes`** anywhere. Worth adding `NSW/.gitattributes` with:
```
* text=auto eol=lf
*.bat text eol=crlf
*.sh text eol=lf
```
This locks line endings per file type so the next time someone clones on Windows the `.sh` files stay LF and `.bat` files stay CRLF.

### 4. Things that go away on Linux (free wins)

From `KNOWN_BUGS.md`, four of the nine known footguns are Windows-flavoured and largely disappear:

- numpy bytecode-cache issues from anti-virus interference
- stale `.pyc` files holding old bytecode
- `.bat` encoding (cp1252 vs utf-8) breaking unicode output
- `debugpy` cold-start `KeyboardInterrupt` quirk

You also stop needing the `.bat` files — they can stay in the repo for any future Windows fallback, but you'll only use `.sh` going forward.

## What I did NOT find (also good news)

- **No `pywin32` / `win32com` / `pythoncom` / `comtypes`** imports in any of your code. (Lots of hits in `.venv/`, but those are third-party packages that get reinstalled with Linux equivalents.)
- **No `os.name == 'nt'` / `sys.platform == 'win32'`** branches in NSW or TA.
- **No COM / Excel automation** anywhere.
- **No hardcoded Windows paths in any actual Python source file** — only in docs, comments, and the VSCode settings file.
- **No `.exe` references** in NSW/TA source.

## Verdict

Migrate whenever — the project is ready. The 2026-05-18 cross-platform work was the load-bearing change, and it held up. Everything left is documentation polish you can do in a single 20-minute pass after the new box boots.

---

*Scan date: 2026-05-25*
