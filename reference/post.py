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


def _dismiss_info_overlays(page: Page) -> int:
    """Dismiss one-time informational dialogs Instagram pops up ON TOP of the
    upload modal (e.g., "Video posts are now shared as reels"). Identifies
    them by distinctive text content + an OK-style primary button.

    Distinct from `_dismiss_modals`, which targets nag dialogs on the main
    page (login save / notifications / cookies) and skips itself when the
    upload modal is open.
    """
    dismissed = 0
    info_cases = [
        # (text fragment inside the dialog, primary button label)
        ("shared as reels", "OK"),
        ("Video posts are now", "OK"),
        ("Original audio", "OK"),
        ("New feature", "OK"),
        ("you can now", "OK"),
        ("New: Edit captions", "Got it"),
    ]
    for text_match, btn_label in info_cases:
        # Case-insensitive substring match
        dialog = page.locator(
            f'[role="dialog"]:has-text("{text_match}")'
        ).first
        try:
            if dialog.count() == 0 or not dialog.is_visible():
                continue
        except Exception:
            continue
        # Skip if this dialog is the upload modal itself (has a file input or
        # the canonical wizard step labels in the header).
        try:
            if dialog.locator('input[type="file"]').count() > 0:
                continue
            header_text = (dialog.inner_text(timeout=500) or "")[:200].lower()
            if any(s in header_text for s in ("crop", "edit", "create new post", "share")):
                # Still let through if the matching info-text is also present
                # (rare). Compare lengths: info dialogs are short.
                if len(header_text) > 500:
                    continue
        except Exception:
            pass

        btn = dialog.get_by_role("button", name=btn_label, exact=True).first
        if not _is_visible(btn):
            btn = dialog.locator(f'button:has-text("{btn_label}")').first
        if _is_visible(btn):
            try:
                btn.click(timeout=2000)
                dismissed += 1
                page.wait_for_timeout(600)
            except Exception:
                pass
    return dismissed


def _dismiss_modals(page: Page) -> int:
    """Best-effort: dismiss Instagram nag dialogs ("Save login info?", "Turn
    on notifications", "Add to home screen") that overlay the page.

    Does NOT touch the upload-flow dialog. The upload dialog has a file input
    or its title is the wizard step name — gate on that to skip dismissal.
    """
    # If the upload modal is in flight (dialog contains a file input OR has the
    # wizard title), do nothing.
    upload_dialog_open = (
        page.locator('[role="dialog"] input[type="file"]').count() > 0
        or page.locator('[role="dialog"]:has-text("Create new post")').count() > 0
        or page.locator('[role="dialog"]:has-text("Crop")').count() > 0
        or page.locator('[role="dialog"]:has-text("Edit")').count() > 0
    )
    if upload_dialog_open:
        return 0

    dismissed = 0
    # Negative-action buttons only — never click positive-confirmation text like "OK"
    # or "Allow" here, because those would opt the user into something. "Close" is
    # excluded because Instagram's upload modal close icon uses that label.
    safe_buttons = [
        "Not now", "Not Now",
        "No thanks", "Dismiss",
        "Decline optional cookies",
        "Skip", "Maybe later",
        "Cancel",
    ]
    for txt in safe_buttons:
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
    """Open Instagram's "Create new post" upload modal.

    Direct nav to /create/select/ FAILS because Instagram's SPA routing falls
    through to the user-profile lookup for "create" (there's a real user
    @create). The reliable path is to click the sidebar's Create button —
    which opens a sub-menu — then click the Post sub-option using its
    accessibility name (`href="#"`, SPA-only action).
    """
    # Step 1: click the sidebar Create button
    create_trigger = page.locator(
        'a:has(svg[aria-label="New post"]), '
        'div[role="link"]:has(svg[aria-label="New post"]), '
        'div[role="button"]:has(svg[aria-label="New post"])'
    ).first
    if not _is_visible(create_trigger):
        raise RuntimeError("Could not find Create button in sidebar")
    _log("clicking sidebar Create")
    create_trigger.click(timeout=5_000)

    # Step 2: wait for the Post sub-option to become visible, then click it.
    # The sub-menu is an `<a href="#">Post</a>` (SPA-only action). We iterate
    # over matches and pick the first VISIBLE one — get_by_role(exact=True)
    # sometimes misses if the computed accessible name has surrounding
    # whitespace or includes an icon's label.
    _log("waiting for Post sub-option to be visible")
    post_option = None
    candidates = page.locator('a[href="#"]:has-text("Post")')
    deadline = page.context.browser  # placeholder for type
    import time as _t
    end = _t.time() + 10
    while _t.time() < end:
        n = candidates.count()
        for i in range(n):
            c = candidates.nth(i)
            try:
                if c.is_visible() and (c.inner_text() or "").strip() == "Post":
                    post_option = c
                    break
            except Exception:
                continue
        if post_option is not None:
            break
        page.wait_for_timeout(300)
    if post_option is None:
        raise RuntimeError("Could not find Post sub-option after clicking Create")
    _log("clicking Post sub-option")
    post_option.click(timeout=5_000)

    # Wait for the upload dialog to appear (it contains a file input)
    _log("waiting for upload dialog to open")
    page.wait_for_selector(
        '[role="dialog"] input[type="file"]',
        state="attached",
        timeout=15_000,
    )


def _find_file_input(page: Page) -> Locator:
    """Instagram's file input is hidden inside the modal; setInputFiles works
    on hidden inputs. Scope inside [role="dialog"] to avoid matching stale
    inputs left on the home page."""
    for sel in [
        '[role="dialog"] input[type="file"][accept*="image"]',
        '[role="dialog"] input[type="file"][accept*="video"]',
        '[role="dialog"] input[type="file"]',
        'input[type="file"]',  # last-resort unscoped fallback
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


def _advance_wizard_and_post(page: Page, caption: str,
                              max_steps: int = 15, step_sleep_s: int = 5,
                              debug_screenshots_dir: str | None = None) -> None:
    """Loop: dismiss modals, then either click Next or (if Share is reachable)
    type caption + click Share. Waits step_sleep_s seconds between iterations
    to give Instagram time for upload + transcode (which can take ~60 s)."""
    typed_caption = False
    for step in range(1, max_steps + 1):
        _dismiss_modals(page)
        n_info = _dismiss_info_overlays(page)
        if n_info:
            _log(f"dismissed {n_info} info overlay(s) blocking the upload modal")

        if debug_screenshots_dir:
            try:
                page.screenshot(
                    path=f"{debug_screenshots_dir}/ig-wizard-{step:02d}.png",
                    full_page=False,
                )
            except Exception:
                pass

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
        if _click_button_in_modal(page, NEXT_BUTTON_RE):
            _log(f"step {step}: clicked Next, waiting {step_sleep_s}s for next view")
        else:
            _log(f"step {step}: no Next/Share visible (upload still processing?)")
        page.wait_for_timeout(step_sleep_s * 1000)
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

            import tempfile, os as _os
            dbg_dir = tempfile.mkdtemp(prefix="ig-wizard-")
            _log(f"per-step screenshots → {dbg_dir}")
            _advance_wizard_and_post(page, caption, debug_screenshots_dir=dbg_dir)

            _log("waiting for confirmation (success dialog or modal close)")
            # IG signals success either by closing the upload modal or by
            # popping a confirmation dialog containing "shared" text (e.g.,
            # "Reel shared", "Your post has been shared"). Treat either as success.
            try:
                page.wait_for_function(
                    """() => {
                      const dialogs = Array.from(document.querySelectorAll('div[role="dialog"]'));
                      // Success: any dialog confirms the share
                      const success = dialogs.some(d => /shared|posted/i.test(d.innerText || ""));
                      if (success) return true;
                      // Or: no upload-wizard dialog is open anymore
                      const wizardOpen = dialogs.some(d => {
                        const t = (d.innerText || "").toLowerCase();
                        return t.includes("create new post") || t.includes("crop")
                          || t.includes("edit") || d.querySelector("input[type='file']");
                      });
                      return !wizardOpen;
                    }""",
                    timeout=180_000,
                )
                _log("post confirmed (success dialog or modal closed)")
            except PWTimeout:
                _log("no confirmation after 180s; check the screenshot")

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
