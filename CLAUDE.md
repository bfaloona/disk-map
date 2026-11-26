# Disk Map: notes for Claude Code

Interactive storage treemap for macOS with rule-based advice on what is safe to delete.
Read-only by design. This file is the project memory; keep it current.

## Layout

- `src/core.py`: scanner, on-disk cache, local web server, stdio engine, `--install-app`. Has two
  placeholders filled by the build: `#__ADVICE__#` and `#__UI__#`.
- `src/advice.py`: the advice rules (by location, folder name, package type, file extension).
- `src/ui.html`: the whole interface (canvas treemap, detail panel, shortlist). One file, no libraries.
- `src/demo.json`: example data the artifact shows before it is installed. Regenerate with `tools/gen_demo.py`.
- `build.py`: writes `dist/diskmap.py` (standalone) and `dist/app/index.html` (artifact page, which
  embeds the scanner as its engine). `dist/` is not committed.
- `tests/`: Playwright smoke tests. Run all three after any change (see README).

## How the pieces talk

The interface runs in one of three modes, chosen in `ui.html` at startup:

- **HTTP**: served by `diskmap.py` on 127.0.0.1. The build leaves `__TOKEN__` for the server to fill in.
  Every API call carries the token; the page itself needs `?t=<token>`; the Host header is checked.
- **APP**: the artifact inside its installed desktop window. `claude.use("desktop")` gives `fs`,
  `childProcess`, `shell`. The page writes `engine.py` to `~/Library/Application Support/Disk Map/`,
  starts it with `python3 -u engine.py --stdio`, and exchanges one JSON message per line
  (`{"id","m","path"}` in, `{"id","r"}` or `{"id","e"}` out; first line is `{"ready":1,...}`).
  Messages are ASCII-only in both directions so chunk boundaries cannot split a character.
- **DEMO**: anywhere else (Claude side panel, browser, mobile). Runs on `demo.json` and shows an
  Install as app banner.

Scanner requests are the same in every mode: `status`, `tree`, `info`, `scan` (plus `reveal`, which is
`open -R` in HTTP mode and `desktop.shell.showItemInFolder` in APP mode).

## The artifact

- Slug `REDACTED`, title "Disk Map", private to the owner.
- Published from `dist/app/index.html` with the artifacts `publish_files` tool (pass the slug and the
  current version as `base_version`). It declares `capabilities: {desktop: {}}`; the page's manifest tag
  asks for `full-access` only. A newer published version makes the app ask for full access again.
- Read the artifacts server's `describe_capabilities` for `desktop` before changing APP-mode code.

## Rules to keep

- Never add code that deletes, moves or writes the user's files. The only writes are the scan cache,
  the engine script, and (for `--install-app`) the launcher app.
- Python: standard library only, must run on 3.8 (the python3 from Xcode Command Line Tools is 3.9).
  No `match`, no `X | Y` type syntax. Check with `vermin -t=3.8- dist/diskmap.py`.
- Never stat or list a network mount unless the user asked to scan it; a dead mount hangs the caller.
  Mount points are recognized by name from the mount table, before any stat.
- File names are untrusted: put them in the page with `textContent`, never as markup.
- `ui.html` must not contain three single quotes in a row (it is embedded in a Python raw string), and
  the Python source must not contain `</script`, `<script` or `<!--` (it is embedded in a script tag).
  `build.py` asserts both.
- Sizes are allocated bytes (`st_blocks * 512`), shown in decimal units like Finder. Hard links are
  counted once.
- Advice wording: plain language, hedged where it is a guess ("likely", "usually"), no invented facts
  about tools. Each rule says what the thing is, why it matters, and the proper way to free it.
- Interface text: US spelling, short sentences, no em dashes.
- Tile colors come from a palette validated for color-blind viewers: three hues (safe, your call,
  careful) plus two grays (keep, mixed). Do not add a fourth hue without re-validating.

## Not verified on macOS

Everything was built and tested on Linux. Still to confirm on a real Mac:

- The scan of `/` across the APFS volume group (firmlinks, skipping `/System/Volumes/Data`, helper
  volumes counted from `statvfs`).
- Cloud-only detection (`SF_DATALESS`) and that listing never triggers downloads.
- Which app name macOS shows in privacy prompts in APP mode, and where Full Disk Access must be granted.
- APP mode in the real Claude desktop app: install flow, permission prompt, Python discovery, window options.
- `--install-app` (osacompile launcher), Reveal in Finder, and the last-opened date from `mdls`.
- Scan time on a real disk with millions of files.

## Ideas not done

- Faster macOS scanning with `getattrlistbulk` instead of one `lstat` per file.
- Move to Trash from the detail panel (deliberately left out; the user chose read-only).
- A custom icon for the `--install-app` launcher.
