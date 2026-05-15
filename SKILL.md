---
name: instagram-upload-browser
description: Post a local photo or video to Instagram by driving a real Chromium browser via Playwright on the user's machine. Use when the user asks to upload/publish/post to Instagram and chooses the browser-automation path. NOTE: browser automation against Instagram violates their ToS — only use when explicitly chosen over the official Graph API. Requires a one-time Instagram session, either imported from the user's logged-in Chrome (import_from_chrome.py) or captured by a fresh Playwright login (auth.py).
---

Base directory for this skill: ~/.claude/skills/instagram-upload-browser

# Instagram Upload (local Playwright)

Drives the Instagram "Create new post" wizard from this machine: a
headless Chromium loads pre-saved session cookies, opens the create
dialog, attaches the file, advances through the wizard steps (Next →
Next → Share), types the caption, and submits.

## When to use

User wants to publish a photo or video to Instagram via browser
automation. Triggers:
- "post <path>.jpg to instagram"
- "publish <video> to my instagram"
- "upload this reel to instagram"
- "share to ig"

Do NOT use this skill when the user wants the ToS-compliant route — for
that, recommend the official **Instagram Graph API** (Business / Creator
accounts only, separate skill). Browser automation against Instagram
violates their ToS and risks account suspension; only use after the user
explicitly chose this path.

## Why no official API in this skill

The Instagram Graph API only works for Business / Creator accounts
linked to a Facebook Page, and requires a registered Meta app with
`instagram_content_publish`. It also requires a publicly-hosted media
URL because the Graph API has no binary-upload endpoint. For users on
personal accounts or who don't want to host their media publicly,
browser automation is the only path. This skill is that path.

## Layout

```
~/.claude/skills/instagram-upload-browser/
├── SKILL.md
└── reference/
    ├── upload.py              # CLI entry point
    ├── post.py                # Playwright posting library (also a CLI)
    ├── auth.py                # one-time: open headed Chromium → login → save cookies
    ├── import_from_chrome.py  # one-time: extract cookies from logged-in Chrome
    ├── requirements.txt
    ├── README.md
    └── .venv/                 # per-machine

~/.config/instagram-upload-browser/
└── storage_state.json         # cookies — DO NOT SHARE — mode 600
```

## How to invoke

```sh
SKILL="$HOME/.claude/skills/instagram-upload-browser/reference"
"$SKILL/.venv/bin/python" "$SKILL/upload.py" <photo-or-video> [--caption "..."] [flags]
```

Flags:
- `--caption "..."` — up to 2200 chars
- `--headless true|false` — default `true`. Use `false` to watch the
  browser do its thing; useful when selectors drift after an Instagram
  UI change.
- `--screenshot <path>` — override the final-state screenshot location
  (default: `instagram-result-<unix-ts>.png` in CWD).

The CLI prints stage markers prefixed with `[post]`. A photo typically
finishes in 20–40 s; a video / Reel in 60–120 s. The final line is
`Done. <url>` on success or `Upload failed: <reason>` on failure (the
screenshot will show what Instagram displayed at the moment of failure).

## First-time setup on a new machine

1. **Install Python deps + Chromium** (~250 MB):
   ```sh
   SKILL="$HOME/.claude/skills/instagram-upload-browser/reference"
   python3 -m venv "$SKILL/.venv"
   "$SKILL/.venv/bin/pip" install -r "$SKILL/requirements.txt"
   "$SKILL/.venv/bin/playwright" install chromium
   ```
2. **Provide an Instagram session.** Two paths — pick one:

   **a. Import from logged-in Chrome** (fastest, recommended on macOS):
   ```sh
   "$SKILL/.venv/bin/python" "$SKILL/import_from_chrome.py"
   ```
   macOS will pop a Keychain prompt — click **Always Allow** so the
   script can decrypt Chrome's cookie store. The script writes
   `~/.config/instagram-upload-browser/storage_state.json` (mode 600).

   **b. Fresh Playwright login** (use if Chrome import is unavailable):
   ```sh
   "$SKILL/.venv/bin/python" "$SKILL/auth.py"
   ```
   A Chromium window opens at `instagram.com/accounts/login/`. Log in
   (handle 2FA / captcha manually). When Instagram redirects you away
   from `/accounts/login`, the script saves cookies, then exits.

Surface to the user that `storage_state.json` IS their Instagram session.
Anyone with this file can post as them. It is mode-600 and gitignored.

## What the post flow does (in order)

1. Launch Chromium with `storage_state.json` and a desktop user-agent.
2. `goto https://www.instagram.com/` — landing page.
3. If Instagram redirected to `/accounts/login`, raise — cookies stale.
4. **Dismiss nag-dialog sweep** — Instagram pops up "Save your login
   info?", "Turn on notifications", cookie banners, etc. The sweep
   prefers negative buttons (Not now / Cancel / Decline) over positive
   ones to avoid accidental opt-ins.
5. **Open Create dialog** — tries several selectors (`a[href$="/create/select/"]`,
   `[aria-label="New post"]`, etc.), falls back to direct nav to
   `/create/select/`.
6. **`set_input_files`** on the hidden file input inside the modal.
7. **Wizard loop** (max 8 iterations):
   - Dismiss any modal
   - If a "Share" button is visible: locate caption editor, click +
     focus-fallback, `Ctrl+A` + `Delete`, type caption, click Share
   - Otherwise: click "Next" and wait
8. **Wait for confirmation** — modal closes (no `[role="dialog"]` in DOM)
   or 180 s timeout.
9. Capture a screenshot, return `{"post_url": final_url}`.

If any step fails, the screenshot is taken from inside the Playwright
context (not from the except block, which would race the teardown) and
the error string is returned.

## Failure modes

- **`Bounced to login`** — `storage_state.json` is stale (Instagram
  rotates session cookies and invalidates them on password change). Re-run
  `import_from_chrome.py` (or `auth.py`).
- **`Could not locate file input inside the create dialog`** — the
  Create dialog didn't open (likely a layout change broke the trigger
  selectors in `_open_create_dialog`). Run with `--headless false`.
- **`Could not locate caption editor`** — Instagram changed the caption
  field selector. Update `_find_caption_editor` candidates.
- **`wizard did not reach Share after 8 steps`** — Instagram inserted a
  new wizard step the loop didn't recognize. Inspect the page with
  `--headless false` and either extend the loop or add a new
  intermediate handler.
- **Captcha / 2FA prompt mid-flow** — Instagram suspects bot activity
  and demanded re-verification. This skill does NOT solve captchas.
  Surface the screenshot and have the user log in fresh.
- **Pointer-intercept errors** — a new nag-dialog pattern is blocking
  clicks. Add its dismiss-button text to `_dismiss_modals.button_texts`.

## Cost notes

- Zero monetary cost — runs locally.
- One full post run uses ~1 GB of network egress for typical videos
  (Instagram fetches the file from the browser to their CDN).
- Chromium runs headless, so no display is needed; CPU spike is brief
  during transcode-wait polling.
