#!/usr/bin/env python3
"""Drive Instagram's web "Create new post" wizard via Playwright. Library + CLI.

Library:
    from post import post_media
    post_media(media, caption, storage_state_path, screenshot_path, headless=True)

CLI:
    python post.py <photo-or-video> <storage_state.json> <screenshot.png> [--caption "..."] [--no-headless]

Notes
-----
Instagram's New Post wizard varies: photos usually go crop→edit→share,
videos add a cover-frame step. Rather than hard-code step counts, this
script loops, clicking whichever primary button is visible at each step
(Next / Share), with modal sweeps in between.

Single image/video only. No carousels, no reels-tab-only posts. Modify
`HOME_URL` / selectors to target the Reels-only flow if needed.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import (
    Locator,
    Page,
    TimeoutError as PWTimeout,
    sync_playwright,
)

HOME_URL = "https://www.instagram.com/"
LOGIN_URL_FRAGMENT = "/accounts/login"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

NEXT_BUTTON_RE = re.compile(r"^\s*next\s*$", re.IGNORECASE)
SHARE_BUTTON_RE = re.compile(r"^\s*share\s*$", re.IGNORECASE)


def _log(msg: str) -> None:
    print(f"[post] {msg}", flush=True)


def _safe_screenshot(page: Page | None, dst: str | None) -> None:
    if page is None or dst is None:
        return
    try:
        page.screenshot(path=dst, full_page=True)
    except Exception as e:
        _log(f"screenshot failed: {e}")


def _dismiss_modals(page: Page) -> int:
    """Best-effort: dismiss Instagram nag dialogs ("Save login info?", "Turn
    on notifications", "Add to home screen") that overlay the page."""
    dismissed = 0
    button_texts = [
        "Not now", "Not Now", "Cancel",
        "Save info", "Save Info",  # avoid — these are positive actions, but listed for awareness
        "Maybe later", "Skip",
        "Got it", "OK", "Okay", "Continue",
        "Accept all", "Accept", "I agree", "Allow", "Close",
        "Decline optional cookies", "Allow all cookies", "Allow essential and optional cookies",
        "No thanks", "Dismiss",
    ]
    # Prefer "Not now" / "Cancel" / "Dismiss" type buttons over positive actions.
    safe_first = ["Not now", "Not Now", "Cancel", "No thanks", "Dismiss",
                  "Decline optional cookies", "Close", "Skip", "Maybe later"]
    rest = [t for t in button_texts if t not in safe_first]
    ordered = safe_first + rest
    for txt in ordered:
        btn = page.get_by_role("button", name=txt, exact=True)
        if btn.count() > 0 and btn.first.is_visible():
            try:
                btn.first.click(timeout=1500)
                dismissed += 1
                page.wait_for_timeout(400)
            except Exception:
                pass
    return dismissed


def _is_visible(loc: Locator) -> bool:
    try:
        return loc.count() > 0 and loc.first.is_visible()
    except Exception:
        return False


def _open_create_dialog(page: Page) -> None:
    """Open Instagram's "Create new post" dialog. Tries several selectors
    because IG ships layout variants across viewports."""
    candidates = [
        # Sidebar / nav button
        'a[href$="/create/select/"]',
        '[role="link"][aria-label="New post"]',
        '[role="button"][aria-label="New post"]',
        'svg[aria-label="New post"]',
        # Mobile-web "plus" icon
        '[aria-label="Create"]',
    ]
    for sel in candidates:
        loc = page.locator(sel).first
        if _is_visible(loc):
            _log(f"clicking new-post trigger: {sel}")
            try:
                # Some matches are SVGs — click the ancestor button
                loc.click(timeout=5_000)
                page.wait_for_timeout(800)
                return
            except Exception as e:
                _log(f"  trigger click failed: {e}")
                continue
    # Last resort: try the modal-open URL (works in some IG variants)
    _log("falling back to /create/select/ direct nav")
    page.goto("https://www.instagram.com/create/select/", wait_until="domcontentloaded")
    page.wait_for_timeout(1500)


def _find_file_input(page: Page) -> Locator:
    """Instagram's file input is hidden inside the modal; setInputFiles works
    on hidden inputs."""
    for sel in [
        'input[type="file"][accept*="image"]',
        'input[type="file"][accept*="video"]',
        'input[type="file"]',
    ]:
        loc = page.locator(sel).first
        try:
            loc.wait_for(state="attached", timeout=10_000)
            return loc
        except PWTimeout:
            continue
    raise RuntimeError("Could not locate file input inside the create dialog")


def _find_caption_editor(page: Page) -> Locator:
    """Instagram's caption is a contenteditable inside the modal. The placeholder
    is "Write a caption..."."""
    candidates = [
        'div[role="textbox"][contenteditable="true"][aria-label*="caption" i]',
        'div[role="textbox"][contenteditable="true"]',
        'div[contenteditable="true"][aria-label*="caption" i]',
        'textarea[aria-label*="caption" i]',
        'div[contenteditable="true"]',
    ]
    for sel in candidates:
        loc = page.locator(sel).first
        try:
            loc.wait_for(state="visible", timeout=10_000)
            return loc
        except PWTimeout:
            continue
    raise RuntimeError("Could not locate caption editor")


def _click_button_in_modal(page: Page, name_re: re.Pattern) -> bool:
    """Click a button matching the regex if visible. Returns True if clicked."""
    btn = page.get_by_role("button", name=name_re).first
    if not _is_visible(btn):
        # IG often uses role=button on a div, not <button>
        btn = page.locator(f'div[role="button"]:text-matches("{name_re.pattern}", "i")').first
    if _is_visible(btn):
        try:
            btn.click(timeout=5_000)
            return True
        except Exception as e:
            _log(f"  button click raced: {e}")
    return False


def _advance_wizard_and_post(page: Page, caption: str, max_steps: int = 8) -> None:
    """Loop: dismiss modals, then either click Next or (if Share is reachable)
    type caption + click Share."""
    typed_caption = False
    for step in range(1, max_steps + 1):
        _dismiss_modals(page)

        # If Share is visible AND we haven't typed yet, type caption first.
        share_btn = page.get_by_role("button", name=SHARE_BUTTON_RE).first
        if not _is_visible(share_btn):
            share_btn = page.locator(f'div[role="button"]:text-matches("{SHARE_BUTTON_RE.pattern}", "i")').first

        if _is_visible(share_btn):
            if not typed_caption:
                _log("share button visible — locating caption editor")
                editor = _find_caption_editor(page)
                _log("typing caption")
                try:
                    editor.click(timeout=5_000)
                except Exception:
                    editor.evaluate("(el) => el.focus()")
                page.keyboard.press("Control+A")
                page.keyboard.press("Delete")
                if caption:
                    editor.type(caption, delay=15)
                typed_caption = True
                page.wait_for_timeout(500)
            _log("clicking Share")
            if not _click_button_in_modal(page, SHARE_BUTTON_RE):
                raise RuntimeError("Share button became unclickable")
            return

        # Otherwise click Next.
        _log(f"step {step}: clicking Next")
        if not _click_button_in_modal(page, NEXT_BUTTON_RE):
            # No Next visible either — modal may not be in a wizard state yet.
            _log("  no Next button visible; sweeping modals and waiting")
            page.wait_for_timeout(1500)
            continue
        page.wait_for_timeout(1500)
    raise RuntimeError(f"wizard did not reach Share after {max_steps} steps")


def post_media(
    media_path: str,
    caption: str,
    storage_state_path: str,
    screenshot_path: str | None,
    headless: bool = True,
) -> dict:
    """Post a single image or video to Instagram. Returns {"post_url": ...}
    or {"error": ...}. Note: Instagram doesn't reliably return a permalink
    immediately after publish via the web UI, so post_url is best-effort
    (it's the URL the browser was on when the modal closed)."""
    result: dict = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=headless,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            storage_state=storage_state_path,
            user_agent=USER_AGENT,
            viewport={"width": 1440, "height": 900},
            locale="en-US",
        )
        page = context.new_page()
        try:
            _log(f"goto {HOME_URL}")
            page.goto(HOME_URL, wait_until="domcontentloaded", timeout=60_000)
            try:
                page.wait_for_load_state("networkidle", timeout=30_000)
            except PWTimeout:
                pass

            if LOGIN_URL_FRAGMENT in page.url:
                raise RuntimeError(
                    "Bounced to login — storage_state is stale or invalid. "
                    "Refresh cookies via import_from_chrome.py or auth.py."
                )

            n = _dismiss_modals(page)
            if n:
                _log(f"dismissed {n} nag dialog(s)")

            _log("opening Create new post dialog")
            _open_create_dialog(page)

            _log("attaching media to file input")
            file_input = _find_file_input(page)
            file_input.set_input_files(media_path)
            page.wait_for_timeout(2000)

            # Some accounts get an "OK" / "Continue" confirmation prompt for video format.
            _dismiss_modals(page)

            _advance_wizard_and_post(page, caption)

            _log("waiting for confirmation (modal close or success toast)")
            # IG returns either a "Your post has been shared" toast or just closes
            # the modal. We wait for the modal to disappear.
            try:
                page.wait_for_function(
                    "() => !document.querySelector('div[role=\"dialog\"]')",
                    timeout=180_000,
                )
                _log("modal closed — post likely succeeded")
            except PWTimeout:
                _log("modal still open after 180s; check the screenshot")

            page.wait_for_timeout(2000)
            result["post_url"] = page.url
            _safe_screenshot(page, screenshot_path)

        except Exception as e:
            _log(f"ERROR: {e}")
            result = {"error": str(e)}
            _safe_screenshot(page, screenshot_path)
        finally:
            try:
                browser.close()
            except Exception:
                pass

    return result


def main() -> None:
    p = argparse.ArgumentParser(description="Post a photo or video to Instagram via Playwright (local).")
    p.add_argument("media", help="Local path to the image or video to post")
    p.add_argument("storage_state")
    p.add_argument("screenshot", help="Where to save the final-page screenshot")
    p.add_argument("--caption", default="")
    p.add_argument("--no-headless", action="store_true")
    args = p.parse_args()

    result = post_media(
        media_path=args.media,
        caption=args.caption,
        storage_state_path=args.storage_state,
        screenshot_path=args.screenshot,
        headless=not args.no_headless,
    )
    print(json.dumps(result))
    if "error" in result:
        sys.exit(2)


if __name__ == "__main__":
    main()
