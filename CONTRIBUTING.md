# Contributing to Disk Map

Bug reports from real Macs are the most useful help right now: see the "Now" section of [`ROADMAP.md`](ROADMAP.md).

## Before you start

- For anything larger than a small fix, open an issue first so we can agree on the approach.
- Security problems go through [`SECURITY.md`](SECURITY.md), not public issues.
- By contributing, you agree that your work is released under the [MIT License](LICENSE).

## Set up

You need Python 3.8 or newer. Disk Map itself uses only the standard library; the tools below are
for development.

```
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pre-commit install
python3 build.py
python3 -m unittest discover -s tests -t tests
```

The browser smoke tests need Playwright's Chromium (`.venv/bin/playwright install chromium`) and,
for two of them, a test home folder. The README's Tests section explains the setup.

## Rules the code must keep

The full list is in [`AGENTS.md`](AGENTS.md), "Rules to keep". The most important:

- Never add code that deletes, moves or writes the user's files.
- Standard library only, and it must run on Python 3.8. Check with `vermin -t=3.8- dist/diskmap.py`.
- Never touch a network mount unless the user asked to scan it.
- Put file names in the page with `textContent`, never as markup.
- Advice text: plain language, hedged where it is a guess, no invented facts about tools.

## Commit checks

`pre-commit install` adds two hooks that run on every commit:

- **gitleaks** blocks keys, tokens and passwords.
- **`tools/check_private.py`** blocks personal data: email addresses, real home folder paths,
  IP and MAC addresses. It also checks the commit message. If a value is not personal (a test
  fixture, for example), end the line with the comment `check-private: allow`.

To protect terms only you know about (your name, your host names), list them as regular
expressions in `private/patterns.txt`. That folder is git-ignored.

CI runs the same checks, a gitleaks scan of the full history, and the unit tests on every pull
request. A pull request from someone without the hooks gets the same checks there.

## Pull requests

- Keep each pull request to one change, with tests for new behavior.
- Use conventional commit messages: `fix(scanner): count hard links once`, `docs: ...`.
- Run the unit tests before you push. Say in the pull request whether you ran it on a real Mac.
