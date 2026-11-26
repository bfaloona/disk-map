# Roadmap

A rough order, not a promise. Open an issue to discuss any item before you start on it.

## Now: confirm it works on a real Mac

Disk Map was built and tested on Linux, with macOS behavior simulated. These still need a real Mac:

- [ ] Scan of `/` across the APFS volume group (firmlinks, helper volumes)
- [ ] Cloud-only (iCloud) detection, and proof that listing never starts a download
- [ ] Which app name macOS shows in privacy prompts, and where to grant Full Disk Access
- [ ] Desktop app mode inside the Claude desktop app: install, permission prompt, Python discovery
- [ ] `--install-app` launcher, Reveal in Finder, and the last-opened date
- [ ] Scan time on a disk with millions of files

## Next

- [ ] Faster macOS scanning with `getattrlistbulk` instead of one `lstat` per file
- [ ] A custom icon for the `--install-app` launcher
- [ ] Run the two browser smoke tests that need a test home folder on macOS

## Later: other platforms

A draft plan is in [`docs/plans/2026-11-26-cross-platform.md`](docs/plans/2026-11-26-cross-platform.md).
In outline:

- [ ] A platform layer around the macOS-specific code, with no behavior change
- [ ] Windows support, then packaged Windows and macOS releases
- [ ] Export a scan from a desktop and view it in a phone browser

## Not planned

- Deleting or moving files from inside Disk Map. It stays read-only; you delete in Finder.
