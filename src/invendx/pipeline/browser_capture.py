"""Operator-triggered rendered-page capture via Playwright (manual intake helper)."""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

from invendx.http.client import DEFAULT_UA

logger = logging.getLogger(__name__)

CAPTURE_METHOD_CHROME_FETCH = "chrome_fetch"

# Default when attaching to a Chrome instance the operator started with --remote-debugging-port
DEFAULT_CDP_URL = "http://127.0.0.1:9222"

try:
    from playwright.sync_api import sync_playwright as _sync_playwright
except ImportError:  # optional dependency [browser]
    _sync_playwright = None


class BrowserCaptureError(Exception):
    """Missing Playwright, browser launch failure, navigation, HTTP error, or empty body."""


def _launch_chromium(playwright: object, *, headed: bool):
    """Prefer system Chrome when available; fall back to bundled Chromium."""
    chrome = playwright.chromium
    try:
        return chrome.launch(channel="chrome", headless=not headed)
    except Exception:
        logger.info("Chrome channel launch failed; using bundled Chromium")
        return chrome.launch(headless=not headed)


def extract_visible_text(
    url: str,
    *,
    headed: bool = False,
    timeout_ms: int = 60_000,
    wait_until: str = "domcontentloaded",
    user_agent: str | None = None,
    connect_cdp_url: str | None = None,
) -> str:
    """Load ``url`` in a browser context and return visible text from ``body``.

    Uses the same default User-Agent as :class:`HttpClient` unless overridden.

    If ``connect_cdp_url`` is set (e.g. ``http://127.0.0.1:9222``), Playwright attaches
    to **Chrome you started** with ``--remote-debugging-port=`` instead of launching a
    new browser. ``headed`` is ignored in that mode.
    """
    if _sync_playwright is None:
        raise BrowserCaptureError(
            "Playwright is not installed. Install with: pip install '.[browser]' "
            "then run: playwright install chrome"
        )

    ua = user_agent if user_agent is not None else DEFAULT_UA
    text = ""
    try:
        with _sync_playwright() as p:
            if connect_cdp_url and connect_cdp_url.strip():
                cu = connect_cdp_url.strip()
                try:
                    browser = p.chromium.connect_over_cdp(cu)
                except Exception as exc:
                    raise BrowserCaptureError(
                        f"Could not attach to Chrome at {cu}. Fully quit Chrome, then start it with "
                        "remote debugging, for example:\n\n"
                        '"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" '
                        "--remote-debugging-port=9222\n\n"
                        "Leave that window open and try again.\n"
                        f"Detail: {exc}"
                    ) from exc
            else:
                browser = _launch_chromium(p, headed=headed)
            context = None
            try:
                context = browser.new_context(user_agent=ua)
                page = context.new_page()
                try:
                    response = page.goto(url, wait_until=wait_until, timeout=timeout_ms)
                except Exception as exc:
                    raise BrowserCaptureError(f"navigation failed: {exc}") from exc
                if response is not None and response.status >= 400:
                    raise BrowserCaptureError(f"HTTP {response.status} for {url}")
                try:
                    text = page.inner_text("body")
                except Exception as exc:
                    raise BrowserCaptureError(f"could not read page text: {exc}") from exc
            finally:
                if context is not None:
                    context.close()
                browser.close()
    except BrowserCaptureError:
        raise
    except Exception as exc:
        raise BrowserCaptureError(str(exc)) from exc

    cleaned = (text or "").strip()
    if not cleaned:
        raise BrowserCaptureError("empty page text after render")
    return cleaned


def run_manual_fetch_subprocess(
    *,
    db_path: Path,
    intake_id: str,
    headed: bool = False,
    connect_cdp_url: str | None = None,
    wait_until: str = "domcontentloaded",
    timeout_ms: int = 60_000,
    process_timeout_s: float = 300.0,
) -> tuple[bool, str]:
    """Run ``python -m invendx.cli manual fetch`` in a **child process**.

    Streamlit uses an asyncio loop that cannot spawn subprocesses on Windows
    (``NotImplementedError`` in ``create_subprocess_exec``). Delegating to the
    CLI keeps Playwright in a normal process context.
    """
    cmd = [
        sys.executable,
        "-m",
        "invendx.cli",
        "manual",
        "fetch",
        intake_id,
        "--db",
        str(db_path.resolve()),
        "--wait-until",
        wait_until,
        "--timeout-ms",
        str(timeout_ms),
    ]
    if connect_cdp_url:
        cmd.extend(["--connect-cdp", connect_cdp_url])
    elif headed:
        cmd.append("--headed")
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=process_timeout_s,
        )
    except subprocess.TimeoutExpired:
        return False, f"Timed out after {int(process_timeout_s)}s"
    if r.returncode != 0:
        msg = (r.stderr or r.stdout or "").strip() or f"exit code {r.returncode}"
        return False, msg
    return True, (r.stdout or "").strip()
