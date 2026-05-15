# instagram-upload-browser

Post a local photo or video to Instagram by driving a real Chromium
browser via Playwright on the user's machine. No cloud sandbox, no
official Graph API — runs locally so Instagram sees the user's home
IP (the one they normally log in from).

This is the **browser-automation path**. It is NOT Instagram-ToS-
compliant. Prefer the official **Graph API** (Business / Creator
accounts only) when that's available.

## Setup

```sh
SKILL="$HOME/.claude/skills/instagram-upload-browser/reference"

# Install Python deps + Chromium (~250 MB on first run)
python3 -m venv "$SKILL/.venv"
"$SKILL/.venv/bin/pip" install -r "$SKILL/requirements.txt"
"$SKILL/.venv/bin/playwright" install chromium

# Provide an Instagram session — EITHER ...
# (a) extract from a logged-in Chrome (macOS Keychain will prompt)
"$SKILL/.venv/bin/python" "$SKILL/import_from_chrome.py"

# (b) fresh login in a managed Chromium window
"$SKILL/.venv/bin/python" "$SKILL/auth.py"
```

Both helpers write `~/.config/instagram-upload-browser/storage_state.json`
(mode 600). Anyone with that file can post as you — keep it private.

## Post

```sh
# Photo
"$SKILL/.venv/bin/python" "$SKILL/upload.py" path/to/image.jpg --caption "hello"

# Video / Reel (auto-detected from extension)
"$SKILL/.venv/bin/python" "$SKILL/upload.py" path/to/clip.mp4 --caption "world"
```

Flags:

- `--caption "..."` — ≤2200 chars
- `--headless true|false` — default `true`; set `false` to watch
- `--screenshot <path>` — override final-state screenshot location

A typical photo finishes in 20–40 s. Video / Reel uploads take 60–120 s
depending on size and Instagram's transcode. The CLI prints `[post]`
stage markers and ends with either:

- `Done. <url>` on success (best-effort — Instagram's web UI doesn't
  reliably surface a permalink immediately), or
- `Upload failed: <reason>` plus a screenshot showing what Instagram
  displayed at the moment of failure.

## Files

| File | What it does |
|---|---|
| `upload.py` | thin CLI wrapper |
| `post.py` | the actual Playwright posting logic — also runnable as a CLI |
| `auth.py` | one-time headed login → save `storage_state.json` |
| `import_from_chrome.py` | one-time pull cookies out of macOS Chrome |
| `requirements.txt` | `playwright`, `browser-cookie3` |

## How it handles Instagram's wizard

Instagram's "Create new post" wizard has variable step counts (photos
typically go crop → edit → caption → share; videos add a cover-frame
step). `post.py` doesn't hard-code step counts — it loops, clicking
whichever primary action button is currently visible (Next / Share),
with modal sweeps in between. The Share-button click happens only after
the caption is typed.

A `_dismiss_modals(page)` sweep handles Instagram's nag dialogs ("Save
your login info?", "Turn on notifications", cookie-consent banners, etc.)
by preferring negative buttons (Not now / Cancel / Decline) over
positive ones.

## Failure recovery

- **`Bounced to login`** — cookies are stale. Re-run
  `import_from_chrome.py` or `auth.py`.
- **`Could not locate caption editor`** / **`Could not locate file input`** —
  Instagram shipped a UI change. Run with `--headless false` to see the
  current layout and update the relevant selector list in `post.py`.
- **`wizard did not reach Share after 8 steps`** — Instagram inserted a
  step the loop didn't recognize (e.g., a new "Choose format" gate).
  Inspect with `--headless false`.
- **Captcha or 2FA mid-flow** — not handled. If Instagram suspects bot
  activity it may demand re-verification; the error screenshot will
  show it.

## Limits

- Single media per call (no carousel posts)
- Caption: 2200 chars max (Instagram-side)
- No story support (Stories use a different flow)
- No first-party Reels-tab control (modern IG often forces video posts
  through the Reels pipeline anyway)
