"""Fyers v3 API client.

Two halves:

1. **Auth** — `get_auth_url()` builds the consent URL the user opens in a
   browser. After Fyers redirects back to our `/callback` with an auth code,
   `exchange_auth_code(code)` swaps it for an access token and persists both.

2. **History** — `fetch_history(symbol, resolution, from_dt, to_dt)` makes a
   single Fyers history call. The backfill module is responsible for chunking
   ranges to fit Fyers' per-call limits; this function just makes the call and
   returns rows in their native ``[ts, o, h, l, c, v]`` shape.

Resolution map and per-call limits live here too — they're a fact about Fyers,
not about our storage, so any caller who wants to bypass our SQLite layer can
import them from this one module.
"""

from __future__ import annotations

import logging
import time
from datetime import date, datetime
from typing import Any

from . import config

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Resolution map and per-call limits
# ------------------------------------------------------------------

# Our base intervals -> Fyers resolution strings.
# We only support the bases. The loader resamples for everything else.
RESOLUTION: dict[str, str] = {
    "1m": "1",
    "1d": "1D",
}

# Per-call window (days) Fyers allows for each base interval.
# Sub-day intervals are capped at 100 days per call; daily-and-up at 366 days.
MAX_DAYS_PER_CALL: dict[str, int] = {
    "1m": 100,
    "1d": 366,
}

# ------------------------------------------------------------------
# Lazy-import the SDK so unit tests / linting don't need it installed.
# ------------------------------------------------------------------


def _fyers_module():
    """Import fyers_apiv3.fyersModel lazily so import-time errors are local."""
    try:
        from fyers_apiv3 import fyersModel  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "fyers_apiv3 is not installed. Run: pip install -r requirements.txt"
        ) from e
    return fyersModel


# ------------------------------------------------------------------
# Auth
# ------------------------------------------------------------------


def _new_session():
    """Build a SessionModel. Raises if credentials aren't configured yet."""
    fyersModel = _fyers_module()
    creds = config.get_fyers_credentials()
    if not config.credentials_are_complete():
        raise RuntimeError(
            "Fyers app_id / secret_key not set (or still on placeholder values). "
            "Open the setup page (python -m nsw.server) and fill them in."
        )
    return fyersModel.SessionModel(
        client_id=creds["app_id"],
        secret_key=creds["secret_key"],
        redirect_uri=creds["redirect_url"],
        response_type="code",
        grant_type="authorization_code",
    )


def get_auth_url() -> str:
    """Return the Fyers consent URL the user should open in a browser."""
    return _new_session().generate_authcode()


def exchange_auth_code(auth_code: str) -> str:
    """Swap an auth_code for an access_token and persist it. Returns the token."""
    session = _new_session()
    session.set_token(auth_code.strip())
    response = session.generate_token()
    if response.get("s") != "ok" and "access_token" not in response:
        raise RuntimeError(f"Token exchange failed: {response}")
    token = response["access_token"]
    config.set_access_token(token)
    return token


def _get_model():
    """Build a FyersModel with the saved token. Raises if no token saved."""
    fyersModel = _fyers_module()
    creds = config.get_fyers_credentials()
    if not creds["access_token"]:
        raise RuntimeError(
            "No Fyers access_token. Authenticate via the setup page first."
        )
    return fyersModel.FyersModel(
        client_id=creds["app_id"],
        token=creds["access_token"],
        is_async=False,
        log_path="",
    )


def check_token() -> tuple[bool, str]:
    """Validate the saved token by hitting a cheap endpoint.

    Returns ``(ok, message)``. ``message`` is a human-readable status line —
    used by the setup page to show "Connected" / "Token expired" / etc.
    """
    if not config.credentials_are_complete():
        return False, "App ID / Secret Key not set (or still on placeholder values)."
    creds = config.get_fyers_credentials()
    if not creds["access_token"]:
        return False, "No access token saved — please authenticate."
    try:
        model = _get_model()
        # `get_profile` is the canonical "is the token alive?" endpoint.
        resp = model.get_profile()
        if resp.get("s") == "ok":
            name = (resp.get("data", {}) or {}).get("name", "")
            return True, f"Connected{(' as ' + name) if name else ''}."
        return False, f"Token rejected: {resp}"
    except Exception as e:
        return False, f"Error contacting Fyers: {e}"


# ------------------------------------------------------------------
# History
# ------------------------------------------------------------------


def _fmt_date(d: date | datetime | str) -> str:
    """Coerce date inputs to Fyers' expected ``YYYY-MM-DD``."""
    if isinstance(d, str):
        # accept already-formatted strings unchanged
        datetime.strptime(d, "%Y-%m-%d")  # validate
        return d
    if isinstance(d, datetime):
        d = d.date()
    return d.strftime("%Y-%m-%d")


def fetch_history(
    symbol: str,
    interval: str,
    from_date: date | datetime | str,
    to_date: date | datetime | str,
    *,
    retries: int = 3,
    backoff_seconds: float = 2.0,
) -> list[list]:
    """One history call. Returns rows in Fyers' native ``[ts, o, h, l, c, v]`` shape.

    Args:
        symbol: Fyers symbol string, e.g. ``"NSE:NIFTY50-INDEX"``.
        interval: ``"1m"`` or ``"1d"`` — the only intervals NSW stores.
        from_date / to_date: inclusive date range. Strings, ``date``, or
            ``datetime`` accepted; all coerced to ``YYYY-MM-DD``.
        retries: total attempts including the first. Fyers' history endpoint
            occasionally 429s or returns transient errors — three tries with
            backoff is enough in practice.
        backoff_seconds: linear backoff between retries (1×, 2×, 3× ...).

    Returns:
        List of rows. Empty list if Fyers reports no data for the window.
    """
    if interval not in RESOLUTION:
        raise ValueError(
            f"Unsupported base interval {interval!r}. "
            f"Supported: {tuple(RESOLUTION.keys())}"
        )

    payload = {
        "symbol": symbol,
        "resolution": RESOLUTION[interval],
        "date_format": "1",
        "range_from": _fmt_date(from_date),
        "range_to":   _fmt_date(to_date),
        "cont_flag":  "1",
    }

    last_error: Any = None
    for attempt in range(1, retries + 1):
        try:
            response = _get_model().history(data=payload)
            status = (response.get("s") or "").strip().lower()

            if status == "ok":
                return response.get("candles", []) or []

            # "no_data" is Fyers' polite "I have nothing for this range" signal —
            # the API floor for this symbol/interval. NOT an error: return an
            # empty list and let the caller decide whether that means "stop
            # walking backwards" (backfill) or "nothing new today" (update).
            # We've also seen "no data" / "no data available" in the wild,
            # hence the substring check.
            if status in ("no_data", "no data") or "no data" in status:
                logger.info(
                    "Fyers reports no_data for %s %s [%s..%s] — treating as "
                    "exhausted for this range.",
                    symbol, interval,
                    payload["range_from"], payload["range_to"],
                )
                return []

            last_error = response
            logger.warning(
                "Fyers history attempt %d/%d for %s %s [%s..%s] failed: %s",
                attempt, retries, symbol, interval,
                payload["range_from"], payload["range_to"], response,
            )
        except Exception as e:
            last_error = e
            logger.warning(
                "Fyers history attempt %d/%d for %s %s [%s..%s] raised: %s",
                attempt, retries, symbol, interval,
                payload["range_from"], payload["range_to"], e,
            )
        if attempt < retries:
            time.sleep(backoff_seconds * attempt)

    raise RuntimeError(
        f"Fyers history failed after {retries} attempts for "
        f"{symbol} {interval} [{payload['range_from']}..{payload['range_to']}]: "
        f"{last_error}"
    )
