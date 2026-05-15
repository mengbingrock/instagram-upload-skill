# instagram-upload-browser (Claude Code skill)

Post a local photo or video to Instagram by driving a real Chromium
browser via Playwright on your machine. No cloud sandbox, no Graph API
— runs locally so Instagram sees your home IP (the one you normally log
in from). Works for personal accounts (the official Graph API doesn't).

This is the **browser-automation path**. It is NOT Instagram-ToS-
compliant. Prefer the official **Graph API** when your account is
Business / Creator and you can register a Meta app.

## Install as a Claude Code skill

```sh
git clone https://github.com/mengbingrock/instagram-upload-skill ~/.claude/skills/instagram-upload-browser
SKILL="$HOME/.claude/skills/instagram-upload-browser/reference"
python3 -m venv "$SKILL/.venv"
"$SKILL/.venv/bin/pip" install -r "$SKILL/requirements.txt"
"$SKILL/.venv/bin/playwright" install chromium
```

Then provide an Instagram session — either:

```sh
# (a) extract from a logged-in Chrome (macOS Keychain will prompt once)
"$SKILL/.venv/bin/python" "$SKILL/import_from_chrome.py"

# (b) fresh headed login
"$SKILL/.venv/bin/python" "$SKILL/auth.py"
```

Both write `~/.config/instagram-upload-browser/storage_state.json` (mode 600).
**Anyone with that file can post as you — keep it private.**

## Post

```sh
# Photo
"$SKILL/.venv/bin/python" "$SKILL/upload.py" path/to/image.jpg --caption "hello"

# Video / Reel (auto-detected from extension)
"$SKILL/.venv/bin/python" "$SKILL/upload.py" path/to/clip.mp4 --caption "world"
```

Flags: `--caption`, `--headless true|false`, `--screenshot <path>`.
See [`SKILL.md`](SKILL.md) for the full skill contract Claude reads and
[`reference/README.md`](reference/README.md) for the CLI details.

## Why no Graph API in this skill

The Instagram Graph API only works for Business / Creator accounts
linked to a Facebook Page, requires a Meta developer app with
`instagram_content_publish`, and has no binary-upload endpoint (media
must be hosted at a public HTTPS URL). For users on personal accounts
or who don't want to host their media publicly, browser automation is
the only path. This skill is that path.

## Known fragility

Instagram's web UI changes frequently. `post.py` keeps things working
by:
- Trying multiple selectors for the New-Post trigger, file input,
  caption editor (with role / contenteditable fallbacks)
- A `_dismiss_modals(page)` sweep that prefers negative buttons (Not
  now / Cancel / Decline) over positive ones, to avoid accidental
  opt-ins to login-saving / notifications
- A step-agnostic wizard loop that clicks whichever primary button
  (Next / Share) is visible, capped at 8 iterations

Expect to update selectors after a major Instagram front-end ship. Use
`--headless false` to see the page during a failed run.

The skill does NOT solve captchas or 2FA mid-flow. If Instagram suspects
bot activity, it'll demand re-verification and the run will fail.

## Companion skills

- [tiktok-upload-skill](https://github.com/mengbingrock/tiktok-upload-skill) — same mechanism for TikTok
- [youtube-upload-skill](https://github.com/mengbingrock/youtube-upload-skill) — official YouTube Data API
