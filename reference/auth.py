#!/usr/bin/env python3
"""One-time local Instagram login.

Launches a headed Chromium on this machine, navigates to instagram.com/accounts/
login, and waits for the user to complete login (including 2FA / captcha).
When Instagram navigates away from /accounts/login, the script saves the
resulting cookies + local storage to
~/.config/instagram-upload-browser/storage_state.json.

Requires Playwright + Chromium locally.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def default_config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "instagram-upload-browser"


def main() -> None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        skill_venv = Path(__file__).resolve().parent / ".venv"
        sys.exit(
            "Playwright is not installed in this venv.\n"
            "Install it (one-time, ~250 MB for Chromium):\n"
            f"  {skill_venv}/bin/pip install playwright\n"
            f"  {skill_venv}/bin/playwright install chromium"
        )

    out = default_config_dir() / "storage_state.json"
    out.parent.mkdir(parents=True, exist_ok=True)

    print("Opening Chromium. Log into Instagram in the window.")
    print("When you're logged in (you see your feed or profile), the script")
    print(f"will auto-save cookies to {out} and exit.\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            locale="en-US",
        )
        page = context.new_page()
        page.goto("https://www.instagram.com/accounts/login/")

        try:
            page.wait_for_url(
                lambda u: ("/accounts/login" not in u) and ("instagram.com" in u),
                timeout=600_000,
            )
            print(f"Login detected at {page.url}")
        except Exception as e:
            print(f"Did not auto-detect login: {e}", file=sys.stderr)
            print("Saving cookies anyway. Press Enter to confirm, or Ctrl+C to abort.")
            input()

        page.wait_for_timeout(2000)
        context.storage_state(path=str(out))
        try:
            os.chmod(out, 0o600)
        except OSError:
            pass
        print(f"Saved storage_state to {out}")
        browser.close()


if __name__ == "__main__":
    main()
