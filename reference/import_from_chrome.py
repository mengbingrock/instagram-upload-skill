#!/usr/bin/env python3
"""One-time: pull Instagram cookies out of the user's local Chrome and convert
them to a Playwright storage_state.json. macOS will prompt for Keychain
access on first run — click "Always Allow".

Note: Chrome's localStorage isn't exported. Instagram's web session lives in
cookies (sessionid, csrftoken, ds_user_id, ...), so cookies-only is sufficient
for the post flow.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import browser_cookie3


SAMESITE_MAP = {0: "None", 1: "Lax", 2: "Strict", None: "Lax"}


def default_config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "instagram-upload-browser"


def main() -> None:
    out = default_config_dir() / "storage_state.json"
    out.parent.mkdir(parents=True, exist_ok=True)

    print("Reading Instagram cookies from Chrome (may trigger a Keychain prompt) ...")
    try:
        jar = browser_cookie3.chrome(domain_name="instagram.com")
    except Exception as e:
        sys.exit(
            f"Could not read Chrome cookies: {e}\n"
            "If macOS prompted for Keychain access, approve it and re-run.\n"
            "If Chrome is open, the database may be locked — close Chrome and retry."
        )

    cookies = []
    for c in jar:
        if "instagram.com" not in (c.domain or ""):
            continue
        same_site = getattr(c, "_rest", {}).get("SameSite") or getattr(c, "_rest", {}).get("samesite")
        if isinstance(same_site, int):
            same_site = SAMESITE_MAP.get(same_site, "Lax")
        if not isinstance(same_site, str) or same_site not in ("Strict", "Lax", "None"):
            same_site = "Lax"

        cookies.append({
            "name": c.name,
            "value": c.value,
            "domain": c.domain,
            "path": c.path or "/",
            "expires": float(c.expires) if c.expires else -1,
            "httpOnly": bool(c._rest.get("HttpOnly") or c._rest.get("httponly")),
            "secure": bool(c.secure),
            "sameSite": same_site,
        })

    if not cookies:
        sys.exit("No Instagram cookies found in Chrome. Log into Instagram in Chrome first.")

    state = {"cookies": cookies, "origins": []}
    out.write_text(json.dumps(state, indent=2))
    try:
        os.chmod(out, 0o600)
    except OSError:
        pass

    have = {c["name"] for c in cookies}
    interesting = sorted(n for n in have if any(s in n.lower() for s in (
        "session", "sid", "csrf", "ds_user", "mid", "ig_did",
    )))
    print(f"Saved {len(cookies)} cookies to {out}")
    if interesting:
        print(f"  session-ish cookies detected: {', '.join(interesting[:12])}")
    else:
        print("  WARNING: no obvious session cookies — you may not be logged in.")


if __name__ == "__main__":
    main()
