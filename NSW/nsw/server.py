"""Flask setup/status server.

Run with:
    python -m nsw.server

What it does:
  * Serves a single page at ``/`` that shows credential status, token status,
    coverage per (symbol, base-interval), and lets you trigger updates and
    backfills with one click.
  * Hosts the OAuth callback at ``/callback`` so Fyers can redirect back.
  * Auto-creates a self-signed cert pair on first run for HTTPS (Fyers
    requires HTTPS callbacks).

Why a separate server, not the trading-dashboard's:
  * Distinct port (5001) so both can run side by side.
  * Smaller surface — credentials + DB ops only, no charting.
  * Isolated config: each project keeps its own ``config.json``.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import uuid
import webbrowser
from collections import OrderedDict
from datetime import datetime, timezone

from flask import Flask, jsonify, redirect, render_template, request, url_for

from . import (
    backfill,
    config,
    database,
    fyers_client,
    loader,
    symbols,
    update,
)

logger = logging.getLogger(__name__)

# Ports differ from trading-dashboard (5000) so both can coexist.
DEFAULT_PORT = 5001
DEFAULT_HOST = "127.0.0.1"

CERT_PATH = os.path.join(config.PROJECT_ROOT, "cert.pem")
KEY_PATH  = os.path.join(config.PROJECT_ROOT, "key.pem")

app = Flask(
    __name__,
    template_folder=os.path.join(config.PROJECT_ROOT, "templates"),
    static_folder=os.path.join(config.PROJECT_ROOT, "static"),
)


# ------------------------------------------------------------------
# Self-signed cert generation (for the HTTPS OAuth callback)
# ------------------------------------------------------------------


def _ensure_cert():
    """Generate a self-signed cert pair if one isn't already on disk."""
    if os.path.exists(CERT_PATH) and os.path.exists(KEY_PATH):
        return
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
        import datetime as _dt
    except ImportError:
        logger.warning(
            "cryptography is not installed; HTTPS will not be available. "
            "Run `pip install cryptography` to enable the OAuth callback."
        )
        return

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1"),
    ])
    _now_utc = _dt.datetime.now(_dt.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(_now_utc - _dt.timedelta(days=1))
        .not_valid_after(_now_utc + _dt.timedelta(days=3650))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName("localhost"),
                                         x509.IPAddress(__import__("ipaddress").IPv4Address("127.0.0.1"))]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    with open(KEY_PATH, "wb") as f:
        f.write(key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        ))
    with open(CERT_PATH, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    logger.info("Generated self-signed cert at %s", CERT_PATH)


# ------------------------------------------------------------------
# Background job tracking — so the UI can show backfill progress
# ------------------------------------------------------------------
#
# When the user hits "Update tail" or "Run full backfill" on the setup page,
# we spawn a background thread to do the work and record its live state in
# `_jobs[job_id]`. The browser polls `/api/job/<job_id>` every 1.5 s and
# renders the latest state into the log box on the page.
#
# `_jobs` is an OrderedDict capped at `_JOBS_MAX` entries. Once we exceed
# the cap we evict the oldest entry. This keeps the dict from growing
# without bound across a long server session.
#
# Job IDs use uuid4 hex so two clicks in the same second can't collide.

_JOBS_MAX: int = 100
_jobs: "OrderedDict[str, dict]" = OrderedDict()
_jobs_lock = threading.Lock()


def _new_job_id(prefix: str) -> str:
    """Return a guaranteed-unique job id like ``update-3f9c.....``."""
    return f"{prefix}-{uuid.uuid4().hex}"


def _job_set(job_id: str, **fields):
    """Create-or-update a job's recorded state. Evicts the oldest if we hit the cap."""
    with _jobs_lock:
        if job_id in _jobs:
            _jobs[job_id].update(fields)
            _jobs[job_id]["updated_at"] = datetime.now(tz=timezone.utc).isoformat()
            # Move-to-end so this job is now the most recently touched.
            _jobs.move_to_end(job_id)
        else:
            new_state = dict(fields)
            new_state["updated_at"] = datetime.now(tz=timezone.utc).isoformat()
            _jobs[job_id] = new_state
            # Evict the oldest entry/entries while we exceed the cap.
            while len(_jobs) > _JOBS_MAX:
                _jobs.popitem(last=False)


def _job_get(job_id: str) -> dict | None:
    with _jobs_lock:
        return dict(_jobs[job_id]) if job_id in _jobs else None


# ------------------------------------------------------------------
# Routes
# ------------------------------------------------------------------


@app.route("/")
def index():
    """Combined status + controls page."""
    config.ensure_config_exists()
    creds = config.get_fyers_credentials()
    token_ok, token_msg = (False, "Not checked")
    if creds["access_token"]:
        token_ok, token_msg = fyers_client.check_token()
    coverage = loader.get_coverage()
    return render_template(
        "setup.html",
        creds=creds,
        token_ok=token_ok,
        token_msg=token_msg,
        coverage=coverage,
        all_symbols=symbols.all_aliases(),
        base_intervals=database.BASE_INTERVALS,
    )


@app.route("/api/credentials", methods=["POST"])
def api_save_credentials():
    """Save app_id / secret_key / redirect_url from the setup form."""
    data = request.get_json(silent=True) or request.form
    app_id = data.get("app_id")
    secret_key = data.get("secret_key")
    redirect_url = data.get("redirect_url")
    config.set_fyers_credentials(
        app_id=app_id, secret_key=secret_key, redirect_url=redirect_url,
    )
    return jsonify({"ok": True})


@app.route("/api/auth/url")
def api_auth_url():
    """Return the Fyers consent URL the front-end should open in a new tab."""
    try:
        return jsonify({"ok": True, "url": fyers_client.get_auth_url()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/callback")
def callback():
    """Receive Fyers' redirect with ?auth_code=... and swap for a token."""
    auth_code = request.args.get("auth_code") or request.args.get("code")
    if not auth_code:
        return "Missing auth_code in callback", 400
    try:
        fyers_client.exchange_auth_code(auth_code)
    except Exception as e:
        return f"Token exchange failed: {e}", 500
    return redirect(url_for("index"))


@app.route("/api/token/check")
def api_token_check():
    """Validate the saved token via Fyers profile endpoint."""
    ok, msg = fyers_client.check_token()
    return jsonify({"ok": ok, "message": msg})


@app.route("/api/coverage")
def api_coverage():
    return jsonify({"ok": True, "coverage": loader.get_coverage()})


def _run_in_thread(job_id: str, fn, *args, **kwargs):
    """Run a job in the background and record its completion in _jobs."""
    def runner():
        try:
            _job_set(job_id, status="running", progress=None)
            result = fn(*args, **kwargs)
            _job_set(job_id, status="done", result=result)
        except Exception as e:
            logger.exception("Job %s failed", job_id)
            _job_set(job_id, status="error", error=str(e))
    threading.Thread(target=runner, daemon=True).start()


@app.route("/api/update", methods=["POST"])
def api_update():
    """Incremental tail update for selected symbols × base intervals."""
    data = request.get_json(silent=True) or {}
    syms = data.get("symbols") or symbols.all_aliases()
    intervals = data.get("intervals") or list(database.BASE_INTERVALS)
    job_id = _new_job_id("update")
    _job_set(job_id, status="queued", kind="update",
             symbols=syms, intervals=intervals)
    _run_in_thread(job_id, update.update_many, syms, intervals)
    return jsonify({"ok": True, "job_id": job_id})


@app.route("/api/backfill", methods=["POST"])
def api_backfill():
    """Full backfill (chunked) for selected symbols × base intervals."""
    data = request.get_json(silent=True) or {}
    syms = data.get("symbols") or symbols.all_aliases()
    intervals = data.get("intervals") or list(database.BASE_INTERVALS)
    job_id = _new_job_id("backfill")
    _job_set(job_id, status="queued", kind="backfill",
             symbols=syms, intervals=intervals)

    def _progress(state):
        _job_set(job_id, progress=state)

    _run_in_thread(
        job_id, backfill.backfill_many,
        syms, intervals, progress_cb=_progress,
    )
    return jsonify({"ok": True, "job_id": job_id})


@app.route("/api/job/<job_id>")
def api_job(job_id: str):
    job = _job_get(job_id)
    if not job:
        return jsonify({"ok": False, "error": "unknown job"}), 404
    return jsonify({"ok": True, "job": job})


# ------------------------------------------------------------------
# Boot
# ------------------------------------------------------------------


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    config.ensure_config_exists()
    database.init_db()
    _ensure_cert()

    has_cert = os.path.exists(CERT_PATH) and os.path.exists(KEY_PATH)
    ssl_context = (CERT_PATH, KEY_PATH) if has_cert else None
    scheme = "https" if has_cert else "http"
    url = f"{scheme}://{DEFAULT_HOST}:{DEFAULT_PORT}/"

    print()
    print("=" * 60)
    print(f" NSW setup server — {url}")
    if not has_cert:
        print(" [warn] no HTTPS cert — Fyers OAuth callback will fail.")
        print("        Run `pip install cryptography` and restart.")
    print("=" * 60)
    print()

    # Open the browser for the user automatically (best-effort).
    try:
        webbrowser.open(url)
    except Exception:
        pass

    app.run(
        host=DEFAULT_HOST,
        port=DEFAULT_PORT,
        ssl_context=ssl_context,
        debug=False,
    )


if __name__ == "__main__":
    main()
