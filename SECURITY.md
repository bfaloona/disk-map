# Security policy

## Report a vulnerability

Please report security problems privately through GitHub:
[Report a vulnerability](https://github.com/bfaloona/disk-map/security/advisories/new).
Do not open a public issue for them.

Include what you found, how to reproduce it, and the commit or version you tested. The maintainer
will reply in the advisory thread. This is a small volunteer project, so response times vary.

## Supported versions

Only the latest commit on `main` gets fixes.

## What Disk Map promises

Reports that break one of these promises are the most valuable:

- Disk Map never deletes, moves or changes your files. It writes only its own files: the scan
  cache, state, log and engine, and for `--install-app` the launcher and its script copy (the
  full list is in `AGENTS.md`, "Rules to keep").
- The local web server listens on 127.0.0.1 only. Every API call needs a per-run token, and the
  Host header is checked.
- File names are treated as untrusted text. A file name must never become markup or a shell command.
- Disk Map does not touch a network volume unless you ask it to scan that volume.
- The engine script, and the script the launcher starts, run only if their bytes match the
  expected SHA-256 hash.

Disk Map often runs with Full Disk Access, so a problem that lets another local process borrow that
access counts as a vulnerability.
