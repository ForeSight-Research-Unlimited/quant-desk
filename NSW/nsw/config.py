"""Config + credential management.

`config.json` is the single source of truth for Fyers credentials and user
preferences. It lives alongside the package, is gitignored, and is shaped like
`config.example.json`. This module is the only place that reads/writes it.

Design notes
------------
- We deliberately do NOT cache the loaded config in module state. The setup
  server can rewrite `config.json` between two API calls, and any caller that
  held a stale dict would silently use old credentials. Reload on every read.
- `save_config` writes atomically (temp file + rename) so a crash mid-write
  cannot leave a half-written JSON that would lock the user out.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from typing import Any


# Project root = the NSW/ folder that contains this package.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(PROJECT_ROOT, "config.json")
CONFIG_EXAMPLE_PATH = os.path.join(PROJECT_ROOT, "config.example.json")


class ConfigError(RuntimeError):
    """Raised when config.json is missing, malformed, or missing required keys."""


def ensure_config_exists() -> None:
    """Make sure ``config.json`` exists and contains valid JSON.

    Called by the setup server on startup so a first-time user lands on a
    working setup page instead of a 500. Three cases:

    1. ``config.json`` is missing -> copy from the template.
    2. ``config.json`` exists but is empty / corrupt JSON -> rename the
       broken file to ``config.json.corrupt-<timestamp>.bak`` so the user
       can recover credentials from it if needed, then recreate from the
       template.
    3. ``config.json`` exists and parses cleanly -> leave it alone.

    Case (2) used to surface as a Flask 500 on the index route; auto-
    recovery turns it into a soft "you'll need to re-authenticate" reset.
    """
    needs_recreate = True

    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                content = f.read()
            stripped = content.strip()
            # Strip an accidental UTF-8 BOM at file start if present.
            if stripped.startswith("﻿"):
                stripped = stripped.lstrip("﻿").strip()
            if stripped:
                json.loads(stripped)
                needs_recreate = False
        except (json.JSONDecodeError, OSError):
            needs_recreate = True

        if needs_recreate:
            # Preserve whatever was there in case the user wants to recover
            # credentials from it. ``.corrupt-<unix>`` makes it easy to spot.
            try:
                ts = int(datetime.now(timezone.utc).timestamp())
                backup = f"{CONFIG_PATH}.corrupt-{ts}.bak"
                os.replace(CONFIG_PATH, backup)
            except OSError:
                # If we can't rename it, fall back to deleting it so we can
                # write a fresh one. Better than leaving the user stuck.
                try:
                    os.remove(CONFIG_PATH)
                except OSError:
                    pass

    if not needs_recreate:
        return

    if not os.path.exists(CONFIG_EXAMPLE_PATH):
        raise ConfigError(
            f"Neither a valid {CONFIG_PATH} nor {CONFIG_EXAMPLE_PATH} exists. "
            "Please create config.example.json or copy it from the repo."
        )
    with open(CONFIG_EXAMPLE_PATH, "r", encoding="utf-8") as src:
        template = json.load(src)
    save_config(template)


def load_config() -> dict[str, Any]:
    """Read config.json and return its parsed contents."""
    if not os.path.exists(CONFIG_PATH):
        raise ConfigError(
            f"{CONFIG_PATH} does not exist. Run the setup server "
            "(python -m nsw.server) or copy config.example.json to config.json."
        )
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        raise ConfigError(f"{CONFIG_PATH} is not valid JSON: {e}") from e


def save_config(config: dict[str, Any]) -> None:
    """Write config.json atomically (temp file + rename)."""
    fd, tmp_path = tempfile.mkstemp(
        prefix=".config.", suffix=".json.tmp", dir=PROJECT_ROOT
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
        os.replace(tmp_path, CONFIG_PATH)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def get_fyers_credentials() -> dict[str, str]:
    """Return the fyers section, with sensible defaults for missing keys."""
    cfg = load_config()
    fyers = cfg.get("fyers", {})
    return {
        "app_id": fyers.get("app_id", "").strip(),
        "secret_key": fyers.get("secret_key", "").strip(),
        "redirect_url": fyers.get(
            "redirect_url", "https://127.0.0.1:5001/callback"
        ).strip(),
        "access_token": fyers.get("access_token", "").strip(),
        "access_token_issued_at": fyers.get("access_token_issued_at", ""),
    }


def set_fyers_credentials(
    app_id: str | None = None,
    secret_key: str | None = None,
    redirect_url: str | None = None,
) -> None:
    """Update one or more credential fields. Leaves the rest untouched.

    Clearing the access_token (set to "") is intentional whenever app_id or
    secret_key changes — the old token won't work with new app keys.
    """
    cfg = load_config()
    cfg.setdefault("fyers", {})
    rotated = False

    if app_id is not None and app_id != cfg["fyers"].get("app_id"):
        cfg["fyers"]["app_id"] = app_id.strip()
        rotated = True
    if secret_key is not None and secret_key != cfg["fyers"].get("secret_key"):
        cfg["fyers"]["secret_key"] = secret_key.strip()
        rotated = True
    if redirect_url is not None:
        cfg["fyers"]["redirect_url"] = redirect_url.strip()

    if rotated:
        cfg["fyers"]["access_token"] = ""
        cfg["fyers"]["access_token_issued_at"] = ""

    save_config(cfg)


def set_access_token(access_token: str) -> None:
    """Persist a freshly-issued access token alongside the issue timestamp."""
    cfg = load_config()
    cfg.setdefault("fyers", {})
    cfg["fyers"]["access_token"] = access_token.strip()
    # tz-aware ISO 8601 with explicit UTC offset, e.g. "2026-05-16T18:30:00+00:00"
    cfg["fyers"]["access_token_issued_at"] = datetime.now(timezone.utc).isoformat()
    save_config(cfg)


# Anything in config.example.json that looks like a placeholder. We compare
# case-insensitively and require the field to NOT match any of these to count
# as "set" — otherwise a fresh template would look like valid credentials.
_PLACEHOLDER_VALUES: frozenset[str] = frozenset({
    "",
    "YOUR_FYERS_APP_ID_HERE",
    "YOUR_FYERS_SECRET_KEY_HERE",
})

# Precomputed upper-cased form so `_is_real_value` is a constant-time check.
_PLACEHOLDER_VALUES_UPPER: frozenset[str] = frozenset(
    p.upper() for p in _PLACEHOLDER_VALUES
)


def _is_real_value(v: str) -> bool:
    s = v.strip()
    return s != "" and s.upper() not in _PLACEHOLDER_VALUES_UPPER


def credentials_are_complete() -> bool:
    """True iff app_id and secret_key are filled in with real (non-placeholder) values."""
    creds = get_fyers_credentials()
    return _is_real_value(creds["app_id"]) and _is_real_value(creds["secret_key"])


def have_access_token() -> bool:
    """True iff an access token is recorded. Does not validate it."""
    return bool(get_fyers_credentials()["access_token"])


def get_preferences() -> dict[str, Any]:
    """Return user preferences (default symbols, default intervals, etc.)."""
    return load_config().get("preferences", {})
