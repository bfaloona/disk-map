# Disk Map

An interactive treemap of where a Mac's storage goes. Zoom from drives down to single files,
click anything for details and plain advice on how safe it is to remove. It only reads: it never
deletes, moves or changes a file. The one action it takes is Reveal in Finder.

## Two ways to run it

| | Standalone script | Desktop app (Claude artifact) |
|---|---|---|
| What | `dist/diskmap.py`, one file, Python standard library only | `dist/app/index.html`, published as a Claude artifact and installed with "Install as app" |
| Start | `python3 dist/diskmap.py` | Open Disk Map from its own icon |
| Window | A tab in your browser | Its own window |
| Scanner | The script itself, over a local web server on 127.0.0.1 | The same scanner, run by the app as a child process |

Both use the same interface (`src/ui.html`) and the same scanner (`src/core.py` + `src/advice.py`).

```
python3 build.py                     # writes dist/
python3 dist/diskmap.py              # scan the startup disk
python3 dist/diskmap.py ~/dev        # scan one folder first
python3 dist/diskmap.py --install-app   # macOS: build a small launcher app with osacompile
python3 dist/diskmap.py --help
```

Requires Python 3.8 or newer. Finished scans are saved in `~/Library/Caches/diskmap`.

## Using it

- Click selects, double-click opens that folder, scroll zooms one level, Esc zooms out.
- Colors show importance: Safe to clear, Your call, Careful, Keep. The Age toggle recolors by last change.
- The shortlist totals what you are considering deleting. Deleting itself is up to you, in Finder.
- Rescan this folder refreshes one folder after you delete things.
- Network volumes are shown but not scanned unless you ask, and never count toward the Mac's totals.

For a complete scan on macOS, give the app that runs Disk Map Full Disk Access
(System Settings > Privacy & Security). Without it, protected folders show as "no access".

## Tests

Unit tests use only the standard library. They build `dist/` first, work in temp folders, and
take a few seconds:

```
python3 -m unittest discover -s tests -t tests
```

| File | Covers |
|---|---|
| `test_advice.py` | Advice rules by location, name, package and extension; the rule tables themselves |
| `test_scanner.py` | Allocated sizes, hard links, symlinks, unreadable folders, mount points, cloud-only folders, rescans, cache |
| `test_server.py` | Web server token and Host checks; the stdio engine's message format |
| `test_build.py` | Build outputs, the build's own safety checks, no HTML-parsing calls in `ui.html` |

Tests marked as expected failures record known problems in the app. When one starts passing, the
problem is fixed: remove the marker.

Smoke tests drive the real page in a browser with Playwright:

```
pip install playwright && playwright install chromium
python3 tests/make_test_home.py /home/tester     # fake home folder, reserves about 18 GB
python3 build.py
cd tests && python3 standalone_smoke.py && python3 demo_smoke.py && python3 app_mode_smoke.py
```

Set `DISKMAP_TEST_HOME` to use another location (it must be under `/home/<name>` or `/Users/<name>`),
and `CHROME` to point at a specific browser.

On macOS, `/home` cannot hold folders and a new folder in `/Users` needs an admin password, so
`standalone_smoke.py` and `app_mode_smoke.py` need that setup first. `demo_smoke.py` needs no test
home. `make_test_home.py` uses `mkfile -n` on macOS, which makes sparse files: they take almost no
disk space, so the map shows them as tiny.

## Status

Built and tested on Linux, including the macOS-specific logic against a simulated mount table and a
simulated desktop app. Not yet verified on a real Mac: see "Not verified on macOS" in `CLAUDE.md`.
