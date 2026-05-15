#!/usr/bin/env python3
"""Local Instagram upload CLI. Uses Playwright + Chromium on this machine to
drive the Instagram "Create new post" wizard.

Reads session cookies from ~/.config/instagram-upload-browser/storage_state.json
(populated once via import_from_chrome.py or auth.py).
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from post import post_media


def default_config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "instagram-upload-browser"


def storage_state_path() -> Path:
    return default_config_dir() / "storage_state.json"


def main() -> None:
    p = argparse.ArgumentParser(
        description="Post a photo or video to Instagram via local Playwright + Chromium."
    )
    p.add_argument("media", help="Local path to the image or video file")
    p.add_argument("--caption", default="", help="Caption text (≤2200 chars)")
    p.add_argument(
        "--headless",
        default="true",
        choices=["true", "false"],
        help="Run Chromium headless (default: true). 'false' opens a visible window — useful for selector debugging.",
    )
    p.add_argument(
        "--screenshot",
        default=None,
        help="Where to save the final-page screenshot (default: instagram-result-<ts>.png in CWD)",
    )
    args = p.parse_args()

    media = Path(args.media).expanduser().resolve()
    if not media.is_file():
        sys.exit(f"Media not found: {media}")

    storage = storage_state_path()
    if not storage.is_file():
        skill_dir = Path(__file__).resolve().parent
        sys.exit(
            f"No Instagram session cookies at {storage}.\n"
            "Run one of:\n"
            f"  {skill_dir}/.venv/bin/python {skill_dir}/import_from_chrome.py   "
            "(if you're already logged into Instagram in Chrome)\n"
            f"  {skill_dir}/.venv/bin/python {skill_dir}/auth.py                 "
            "(opens a fresh Chromium window for login)"
        )

    screenshot = args.screenshot or str(
        Path.cwd() / f"instagram-result-{int(time.time())}.png"
    )

    print(f"  posting {media.name} ({media.stat().st_size // (1024 * 1024)} MB) ...", flush=True)
    t0 = time.time()
    result = post_media(
        media_path=str(media),
        caption=args.caption,
        storage_state_path=str(storage),
        screenshot_path=screenshot,
        headless=args.headless != "false",
    )
    elapsed = int(time.time() - t0)
    print(f"  finished in {elapsed}s", flush=True)
    if Path(screenshot).exists():
        print(f"  screenshot: {screenshot}")
    if "error" in result:
        sys.exit(f"Upload failed: {result['error']}")
    print(f"Done. {result.get('post_url', '<no url returned>')}")


if __name__ == "__main__":
    main()
