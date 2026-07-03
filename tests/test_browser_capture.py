"""Tests for Playwright-backed manual capture (mocked)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from invendx.pipeline.browser_capture import (
    BrowserCaptureError,
    extract_visible_text,
    run_manual_fetch_subprocess,
)


def _sync_playwright_cm(playwright_instance: MagicMock):
    cm = MagicMock()
    cm.__enter__.return_value = playwright_instance
    cm.__exit__.return_value = None
    return cm


def test_extract_visible_text_strips_body() -> None:
    mock_page = MagicMock()
    mock_response = MagicMock()
    mock_response.status = 200
    mock_page.goto.return_value = mock_response
    mock_page.inner_text.return_value = "  hello world \n"

    mock_context = MagicMock()
    mock_context.new_page.return_value = mock_page
    mock_browser = MagicMock()
    mock_browser.new_context.return_value = mock_context
    pw = MagicMock()
    pw.chromium.launch.return_value = mock_browser

    with patch("invendx.pipeline.browser_capture._sync_playwright") as mock_sync:
        mock_sync.return_value = _sync_playwright_cm(pw)
        out = extract_visible_text("https://example.com/page")
    assert out == "hello world"
    mock_browser.new_context.assert_called_once()
    ctx_kw = mock_browser.new_context.call_args.kwargs
    assert "InVendX" in (ctx_kw.get("user_agent") or "")


def test_extract_visible_text_http_error() -> None:
    mock_page = MagicMock()
    mock_response = MagicMock()
    mock_response.status = 404
    mock_page.goto.return_value = mock_response
    mock_context = MagicMock()
    mock_context.new_page.return_value = mock_page
    mock_browser = MagicMock()
    mock_browser.new_context.return_value = mock_context
    pw = MagicMock()
    pw.chromium.launch.return_value = mock_browser

    with patch("invendx.pipeline.browser_capture._sync_playwright") as mock_sync:
        mock_sync.return_value = _sync_playwright_cm(pw)
        with pytest.raises(BrowserCaptureError, match="HTTP 404"):
            extract_visible_text("https://example.com/missing")


def test_extract_visible_text_empty_body() -> None:
    mock_page = MagicMock()
    mock_response = MagicMock()
    mock_response.status = 200
    mock_page.goto.return_value = mock_response
    mock_page.inner_text.return_value = "   \n"
    mock_context = MagicMock()
    mock_context.new_page.return_value = mock_page
    mock_browser = MagicMock()
    mock_browser.new_context.return_value = mock_context
    pw = MagicMock()
    pw.chromium.launch.return_value = mock_browser

    with patch("invendx.pipeline.browser_capture._sync_playwright") as mock_sync:
        mock_sync.return_value = _sync_playwright_cm(pw)
        with pytest.raises(BrowserCaptureError, match="empty page text"):
            extract_visible_text("https://example.com/blank")


def test_extract_visible_text_missing_playwright(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("invendx.pipeline.browser_capture._sync_playwright", None)
    with pytest.raises(BrowserCaptureError, match="Playwright is not installed"):
        extract_visible_text("https://example.com/")


def test_launch_falls_back_when_chrome_channel_fails() -> None:
    mock_page = MagicMock()
    mock_response = MagicMock()
    mock_response.status = 200
    mock_page.goto.return_value = mock_response
    mock_page.inner_text.return_value = "ok"
    mock_context = MagicMock()
    mock_context.new_page.return_value = mock_page
    mock_browser = MagicMock()
    mock_browser.new_context.return_value = mock_context
    chrome = MagicMock()
    chrome.launch.side_effect = [OSError("no chrome"), mock_browser]
    pw = MagicMock()
    pw.chromium = chrome

    with patch("invendx.pipeline.browser_capture._sync_playwright") as mock_sync:
        mock_sync.return_value = _sync_playwright_cm(pw)
        out = extract_visible_text("https://fallback.test/")
    assert out == "ok"
    assert chrome.launch.call_count == 2
    second_kw = chrome.launch.call_args_list[1].kwargs
    assert second_kw.get("headless") is True


def test_run_manual_fetch_subprocess_success() -> None:
    proc = MagicMock()
    proc.returncode = 0
    proc.stderr = ""
    proc.stdout = "Saved capture for x (10 characters).\n"
    with patch("invendx.pipeline.browser_capture.subprocess.run", return_value=proc) as run:
        ok, out = run_manual_fetch_subprocess(
            db_path=Path("/tmp/db.sqlite"),
            intake_id="abc-uuid",
            headed=True,
        )
    assert ok
    assert "Saved" in out
    cmd = run.call_args[0][0]
    assert cmd[1] == "-m" and cmd[2] == "invendx.cli"
    assert "--headed" in cmd


def test_run_manual_fetch_subprocess_connect_cdp_supersedes_headed() -> None:
    proc = MagicMock()
    proc.returncode = 0
    proc.stderr = ""
    proc.stdout = "ok\n"
    with patch("invendx.pipeline.browser_capture.subprocess.run", return_value=proc) as run:
        ok, _ = run_manual_fetch_subprocess(
            db_path=Path("/tmp/db.sqlite"),
            intake_id="id1",
            headed=True,
            connect_cdp_url="http://127.0.0.1:9222",
        )
    assert ok
    cmd = run.call_args[0][0]
    assert "--connect-cdp" in cmd
    assert "http://127.0.0.1:9222" in cmd
    assert "--headed" not in cmd


def test_extract_visible_text_connect_cdp() -> None:
    mock_page = MagicMock()
    mock_response = MagicMock()
    mock_response.status = 200
    mock_page.goto.return_value = mock_response
    mock_page.inner_text.return_value = "cdp body"

    mock_context = MagicMock()
    mock_context.new_page.return_value = mock_page
    mock_browser = MagicMock()
    mock_browser.new_context.return_value = mock_context
    pw = MagicMock()
    pw.chromium.connect_over_cdp.return_value = mock_browser

    with patch("invendx.pipeline.browser_capture._sync_playwright") as mock_sync:
        mock_sync.return_value = _sync_playwright_cm(pw)
        out = extract_visible_text("https://cdp.example/", connect_cdp_url="http://127.0.0.1:9222")
    assert out == "cdp body"
    pw.chromium.connect_over_cdp.assert_called_once()
    pw.chromium.launch.assert_not_called()


def test_run_manual_fetch_subprocess_failure() -> None:
    proc = MagicMock()
    proc.returncode = 1
    proc.stderr = "Playwright is not installed\n"
    proc.stdout = ""
    with patch("invendx.pipeline.browser_capture.subprocess.run", return_value=proc):
        ok, msg = run_manual_fetch_subprocess(db_path=Path("data/db.db"), intake_id="id1")
    assert not ok
    assert "Playwright" in msg
