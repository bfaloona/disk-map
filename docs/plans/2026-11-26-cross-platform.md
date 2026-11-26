# Disk Map: cross-platform plan, Windows proof of concept first

Status: ready to implement (proof of concept, section 3); sections 4 to 9 stay a draft
Date: 2026-11-26 (revised the same day)
Scope: make the scanner and advice work on Windows, ship per-platform executables later, and keep a path open to iOS and Android. Section 3 is the part to build now.

**Verify** marks a claim that nobody has checked against documentation or a machine. Facts that documentation answers carry a source link. Nothing in this plan has run on Windows yet.

## Edit history

| Date | Type | Note |
|---|---|---|
| 2026-11-26 | drafted | First draft: platform layer, packaging options, mobile |
| 2026-11-26 | revised | Maintainer decisions recorded (section 2). Proof of concept section added. Documentation facts filled in with sources. Line numbers replaced by function names |
| 2026-11-26 | reviewed | Self-review by the drafting agent: code references checked against `src/` at 2627bf0, copy-review scanner pass. The maintainer has not reviewed it yet |

## Status

Proof of concept checklist (section 3.6). Tick each step when its "done when" holds.

- [ ] S1 Probe workflow on both Windows runners
- [ ] S2 Platform string and internal path helpers
- [ ] S3 Request path validation in one place
- [ ] S4 Drive list, free space and the network rule on Windows
- [ ] S5 Scan loop: size on disk, reparse points, cloud files
- [ ] S6 Details, breadcrumbs, folders for state, and features that refuse
- [ ] S7 Local server port binding on Windows
- [ ] S8 Page: platform string and wording
- [ ] S9 Unit tests on Windows
- [ ] S10 End-to-end check script and CI jobs

## 1. Summary

- Keep the Python scanner. Put the OS-specific code behind one platform layer. Add a Windows implementation that uses `ctypes` (standard library).
- First deliverable: a proof of concept that runs `dist/diskmap.py` from source on Windows, scans `C:`, and serves the page in HTTP mode. GitHub Actions runners are the only Windows machines, so every check in the proof of concept is a workflow assertion.
- Later: package with PyInstaller in folder mode ("onedir"), built separately for Windows and macOS. Linux ships the script first. The interface stays in the default browser for the first release.
- Fallback 1: the python.org embeddable package plus a launcher, if antivirus tools flag the PyInstaller build.
- Fallback 2: a Go or Rust scanner, only if scan time on a real Windows disk stays too slow after tuning.
- Mobile cannot scan a whole device. The realistic mobile product is a viewer for a scan exported from a desktop. A scan export format is the one thing to design now.
- The tool stays read-only on every platform.

## 2. Decisions

| ID | Question | Decision |
|---|---|---|
| Q1 | Windows machine for the first work | GitHub Actions runners only. No real PC or virtual machine for now |
| Q7 | Target | Windows 11. The only hosted Windows 11 runner is Arm64 (`windows-11-arm`), so the proof of concept also runs on `windows-latest` (Windows Server 2025, x64) to cover x64 and Python 3.8. See 3.3 |
| Q8 | Where the code lives | Public repository on GitHub. Standard hosted runners are free for public repositories ([GitHub docs](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)) |
| Q10 | Path model | OPT-P2: forward slashes inside (`C:/Users/name`), native form only where a Windows API needs it and on screen |
| Q11 | Must the real-Mac baseline (M0) finish first? | No. M0 runs in parallel. The identical-output checks in S9 guard macOS and Linux behavior |
| PoC scope | How far the proof of concept goes | Run from source in HTTP mode. Section 3.2 lists what waits until later |

Still open: Q2 to Q6 and Q9 in section 9. None of them blocks the proof of concept.

## 3. Proof of concept: Windows from source

### 3.1 Goal

On a hosted Windows runner, `python dist/diskmap.py --no-browser C:/` scans the system drive. The page and API work through the same token flow as on macOS. The scan never enters a junction, a symbolic link or a network location. A script asserts all of this and fails the job when one check fails.

### 3.2 Out of scope

| Feature | Behavior on Windows in the proof of concept |
|---|---|
| `--install-app` | Exits with a message. It already does this off macOS (`install_app`) |
| `--app` and `--parent` | Exit with a message before any other work. Today `--app` would fail on `import fcntl`, and `--parent` calls `os.kill(pid, 0)`. On Windows signal 0 is `CTRL_C_EVENT`, so that call sends Ctrl+C instead of testing whether the process is alive ([os.kill](https://docs.python.org/3/library/os.html#os.kill)) |
| `--stdio` (APP mode engine) | Not tested. The page still refuses to start APP mode on any platform but macOS (`startApp` in `src/ui.html`) |
| Reveal | `/api/reveal` keeps returning an error off macOS. The message names the platform instead of "macOS" |
| Last opened date (`mdls`) | Left out on Windows |
| Windows advice rules | Deferred to M3. The proof of concept only maps the home folder (S6) |
| Hard-link deduplication | Deferred. `DirEntry.stat()` gives `st_nlink` 0 on Windows, so hard links are counted once per link. S10 records the overcount |
| Cloud placeholders (OneDrive) | A folder or file with a recall attribute is treated as cloud-only and never listed (S5). Whether a normal process sees those attributes needs a real machine (3.5) |
| Paths over 260 characters on machines without `LongPathsEnabled` | Deferred. The runners set it to 1 ([Configure-BaseImage.ps1](https://github.com/actions/runner-images/blob/main/images/windows/scripts/build/Configure-BaseImage.ps1)) |
| Packaging, signing, installer | Sections 4 and 5, after the proof of concept |

### 3.3 Runners

| Runner label | OS and architecture | Python | Role |
|---|---|---|---|
| `windows-latest` | Windows Server 2025, x64 | 3.8.10 through `actions/setup-python` (the newest 3.8 build for Windows), and 3.13 | Python 3.8 floor on Windows, x64 `ctypes` calls |
| `windows-11-arm` | Windows 11, Arm64 | 3.13 (no Arm64 build of 3.8 to 3.10 exists) | The target OS. Client Windows, not Server |

Sources: [runner images](https://github.com/actions/runner-images), [Windows 11 Arm64 image](https://github.com/actions/runner-images/blob/main/images/windows/Windows11-VS2026-Arm64-Readme.md), [setup-python versions manifest](https://github.com/actions/python-versions/blob/main/versions-manifest.json).

Facts about both runners that change the tests:

- The job runs as administrator with UAC turned off. "Access denied" cases do not occur as they would for a normal user.
- Developer Mode is on, so `os.symlink` works without elevation.
- Chrome and Edge are installed, so a browser smoke test can run later.
- The workspace moves to `D:` on 2026-11-30, and `D:` becomes ReFS. Tests that need NTFS behavior (compression, sparse files, hard links) must make their files on `C:`. `tempfile` uses `TMP`, so set `TMP` and `TEMP` to a folder on `C:` in the job (**Verify** where `TMP` points after the move).
- The `C:` drive has no published size or file count. S1 measures both.

### 3.4 Facts from documentation

| Topic | Fact | Source |
|---|---|---|
| `st_blocks` | Does not exist on Windows | [os.stat_result](https://docs.python.org/3/library/os.html#os.stat_result) |
| `DirEntry.stat()` | Fills attributes, size, times and the reparse tag from the listing with no extra call. `st_ino`, `st_dev` and `st_nlink` are always 0. `DirEntry.inode()` costs a system call | [os.DirEntry](https://docs.python.org/3/library/os.html#os.DirEntry) |
| Junctions | `is_symlink()` is False and `is_dir()` is True, so a plain scan enters them. `stat(follow_symlinks=False).st_reparse_tag` comes from the listing (Python 3.8+) and equals `stat.IO_REPARSE_TAG_MOUNT_POINT` for a junction or a volume mounted on a folder. `is_junction()` needs 3.12 | [os.DirEntry](https://docs.python.org/3/library/os.html#os.DirEntry), CPython `Modules/posixmodule.c` |
| `O_NOFOLLOW` | Absent on Windows, so `scandir_nofollow` falls back to a plain `os.scandir` and gives no protection | `src/core.py` `scandir_nofollow` |
| `os.path.normpath` | On Windows it turns `/` into `\` | [os.path.normpath](https://docs.python.org/3/library/os.path.html#os.path.normpath) |
| `os.statvfs` | Unix only. `shutil.disk_usage` works on Windows | [shutil.disk_usage](https://docs.python.org/3/library/shutil.html#shutil.disk_usage) |
| `fcntl` | Unix only. `msvcrt.locking(fd, LK_NBLCK, n)` fails at once when locked | [msvcrt](https://docs.python.org/3/library/msvcrt.html) |
| `GetDriveTypeW` | 0 unknown, 1 no root folder, 2 removable, 3 fixed, 4 remote, 5 CD-ROM, 6 RAM disk. The root needs a trailing backslash. The page does not say whether it blocks on a disconnected mapped drive | [GetDriveTypeW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getdrivetypew) |
| `GetCompressedFileSizeW` | Compressed size for a compressed file, sparse size for a sparse file, otherwise the logical size. Nothing is documented about very small files stored in the file table or about Explorer's "Size on disk" | [GetCompressedFileSizeW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getcompressedfilesizew) |
| File attributes | SPARSE `0x200`, REPARSE_POINT `0x400`, COMPRESSED `0x800`, OFFLINE `0x1000`, RECALL_ON_OPEN `0x40000`, PINNED `0x80000`, UNPINNED `0x100000`, RECALL_ON_DATA_ACCESS `0x400000`. For a folder with RECALL_ON_DATA_ACCESS, listing it fetches at least some content | [File attribute constants](https://learn.microsoft.com/en-us/windows/win32/fileio/file-attribute-constants) |
| Cloud placeholders | Two Microsoft pages disagree on whether a normal process sees placeholder reparse points ("hidden" from processes outside the system folder, against "most applications see exposed placeholders") | [Build a cloud sync engine](https://learn.microsoft.com/en-us/windows/win32/cfapi/build-a-cloud-file-sync-engine), [RtlSetProcessPlaceholderCompatibilityMode](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/ntifs/nf-ntifs-rtlsetprocessplaceholdercompatibilitymode) |
| Long paths | Python declares itself long-path aware. It works when the `LongPathsEnabled` registry value is 1 | [Python on Windows](https://docs.python.org/3/using/windows.html#removing-the-max-path-limitation) |
| File names | Windows names cannot contain `"`, `*`, `:`, `<`, `>`, `?`, `\`, `/` or `|` | [Naming files](https://learn.microsoft.com/en-us/windows/win32/fileio/naming-a-file) |

### 3.5 What the proof of concept can and cannot answer

| Answered by | Items |
|---|---|
| Documentation (3.4) | `st_blocks`, `DirEntry.stat` fields, junction detection, `normpath`, `statvfs`, `fcntl`, drive types, attribute values, long-path setting, file name characters |
| The S1 probe on the runners | Junction and symlink behavior seen by `DirEntry`, `st_reparse_tag` values, `GetCompressedFileSizeW` against cluster-rounded size on `C:`, file count and scan time of `C:`, hard links and junctions on ReFS `D:`, whether a second socket can bind a port already in use (S7), `open_private` and `os.replace` round trip, where `TMP` points |
| A real Windows 11 PC as a normal user (deferred to M2b) | OneDrive placeholders and whether listing downloads anything, a disconnected mapped drive and whether `GetDriveTypeW` blocks, "access denied" as a standard user, Explorer's "Size on disk", SmartScreen and antivirus, `explorer.exe /select,` quoting |

### 3.6 Steps

Each step is one or two small commits with conventional messages. Steps S2 to S8 change `src/` and must keep the macOS and Linux CI jobs green. Run the unit tests after each step (AGENTS.md).

Code stays in `src/core.py` in a new "Platform" section near the top. A separate source file would need a third build placeholder for no gain, because the tests import the built `dist/diskmap.py`.

#### S1. Probe workflow on both Windows runners

Add `.github/workflows/windows-probe.yml`, started by `workflow_dispatch` only, with a matrix over the two runners in 3.3. It runs `tools/windows_probe.py` (standard library) and uploads its JSON output as an artifact. The probe does not import Disk Map.

The probe records:

1. `sys.version`, `platform.platform()`, `platform.machine()`, `TMP`, `GetLogicalDriveStringsW` with `GetDriveTypeW` and the file system name of each fixed drive.
2. For `C:/Documents and Settings` (a junction on every Windows install) and `C:/ProgramData/Application Data` (**Verify** it is a junction on Server 2025): `DirEntry.is_dir()`, `is_symlink()`, `stat(follow_symlinks=False)` mode, attributes and reparse tag.
3. In a new folder on `C:` and on `D:`: a file, a hard-linked pair (`os.link`), a directory symlink, a junction (`cmd /c mklink /J`), a sparse file (`fsutil sparse setflag` plus a seek), a compressed file (`compact /c`), and a 100-byte file. For each: the `DirEntry.stat` fields, `os.stat` fields, `GetCompressedFileSizeW`, and the cluster size from `GetDiskFreeSpaceW`.
4. A directory symlink to `\\diskmap-test.invalid\share`: how long `DirEntry.stat(follow_symlinks=False)` and `os.lstat` take on it. Both must return at once.
5. A walk of `C:/` with `os.scandir` that never enters a reparse point: file count, folder count, sum of cluster-rounded sizes, count of entries whose `GetCompressedFileSizeW` differs from that rounding (sampled under `C:/Windows`), time taken, and `shutil.disk_usage('C:/')`.
6. Port binding: bind a `socketserver.TCPServer` on `127.0.0.1:8765`, then try a second one on the same port. Record whether the second bind succeeds.
7. Create a file with `os.open(..., O_CREAT | O_EXCL, 0o600)`, write it, `os.replace` it over an existing file while a reader holds it open, and record the outcome.

Done when: the workflow runs green on both runners and its JSON is attached to the run. Copy the answers into 3.4 (with the run link) before S4 starts. The probe workflow and script are deleted at S10.

#### S2. Platform string and internal path helpers

- Add `PLATFORM = 'mac' | 'windows' | 'linux'` next to `IS_MAC`. Keep `IS_MAC` as `PLATFORM == 'mac'` so existing code does not change in this step.
- Add `IS_WIN`.
- Add `ipath = posixpath` and use it for every `dirname`, `basename`, `split` and `normpath` on an internal path, in `src/core.py` and `src/advice.py`. `os.path` stays only for paths that come from the OS (`expanduser`, `realpath`, `abspath`).
- Add `to_internal(native)`: on Windows, replace `\` with `/` and upper-case the drive letter. On macOS and Linux it returns its input.
- Add `system_root()`: `'/'` on macOS and Linux, `'C:/'` (from the `SystemDrive` environment variable, default `C:`) on Windows.
- Replace every hard-coded `'/'` root: `warm` and `main` (default scan), `volumes` (first entry), `request_scan` (empty path), `crumbs` (start), `tree_payload` (fallback scan target), the root checks in `_special_for` and `_container_of`, and the loop ends in `find_rule`, `_dir_rule` and `_governing_ancestor` in `src/advice.py`.
- `main`: pass pinned folders through `to_internal` after `realpath`.

Done when: all unit tests pass on Linux and macOS, and a new test runs the helpers with `PLATFORM` forced to `'windows'` (the helpers take the platform as a parameter with the module value as default, so the test needs no Windows machine).

#### S3. Request path validation in one place

Today three places check `startswith('/')` and call `clean_path`: `Handler._path_arg`, `Handler.do_POST`, and `serve_stdio.handle`.

- Add `valid_path(p)`: returns the cleaned internal path, or `None`.
  - macOS and Linux: today's rule (starts with `/`, no NUL, then `clean_path`).
  - Windows: must match `^[A-Za-z]:/`, no NUL, no `\`, then `ipath.normpath`, and the result must still start with the drive. Rejects `//server/share` and every UNC form.
- Call it from the three places.
- `ok_name`: also reject `\` and `:` on every platform. A cache file is data and may come from another machine later (section 6).

Done when: unit tests cover each accepted and rejected form on both platform values, including `C:/../..`, `c:/x` (normalized to `C:/x`), `//host/share`, `\\host\share`, `C:` with no slash, and `/` on Windows.

#### S4. Drive list, free space and the network rule on Windows

- `read_mounts` on Windows: build the `Mount` table from `GetLogicalDriveStringsW`. For each root call `GetDriveTypeW` first.
  - Remote (4): `Mount(path, device, 'remote', local=False, ro=False)`. Never call anything else on it.
  - No root folder (1) or unknown (0): skip.
  - CD-ROM (5): a volume entry with no size, because `disk_usage` waits for media. **Verify** on a real machine.
  - Fixed, removable, RAM disk: `GetVolumeInformationW` gives the file system name. Store it as `fstype`.
- `Mount.container`: the drive itself. There is no APFS-style container on Windows.
- `vol_space`: use `shutil.disk_usage` when `os.statvfs` does not exist. `disk_usage` gives total, used and free. Used is total minus free, so the `container_level` flag has no effect on Windows.
- `volumes()`: the Windows branch lists every non-skipped drive as a volume. `display_name` gives `"Local Disk (C:)"` style names only if `GetVolumeInformationW` returned a label. Otherwise `"C:"`. `display_name('')` returns `"This PC"`.
- `start_scan`: the refusal when the mount table is empty applies on Windows too, because the network rule depends on it.
- `_mac_root_name` becomes `root_name()` in the platform section, with the Windows branch returning the system drive's display name.

Done when: on both runners, `GET /api/tree?path=` lists `C:` (and `D:`) with total, used and free equal to `shutil.disk_usage` within 1 MB. A unit test feeds recorded `GetLogicalDriveStringsW` and `GetDriveTypeW` results (a remote drive included) through the parsing code and checks that the remote drive gets `net` and no space call.

#### S5. Scan loop: size on disk, reparse points, cloud files

All three changes sit in `_list_dir`, `list_files` and `info`, behind three platform functions so the loop stays one piece of code.

- `entry_size(st, path)`:
  - macOS and Linux: `st.st_blocks * 512` (unchanged).
  - Windows: if the attributes show COMPRESSED or SPARSE, call `GetCompressedFileSizeW` and round up to the cluster size. Otherwise round `st_size` up to the cluster size. Get the cluster size once per drive from `GetDiskFreeSpaceW`. If the S1 probe shows that small files report 0 clusters in Explorer terms, record the gap in RISK-8 and do not special-case it yet.
- `is_link_entry(st)`:
  - macOS and Linux: `stat.S_ISLNK(st.st_mode)` (unchanged).
  - Windows: `S_ISLNK`, or the REPARSE_POINT attribute with a tag that is a name surrogate (bit `0x20000000` set in the tag: symlinks, junctions, volumes mounted on folders). A folder with such a tag becomes a link tile with `F_LINK`. It is never listed and its size is 0.
  - A reparse point that is not a name surrogate (for example deduplication or cloud tags) is not a link. It falls through to the cloud check.
- `is_cloud_entry(st)`:
  - macOS: `st_flags & SF_DATALESS` (unchanged).
  - Windows: RECALL_ON_DATA_ACCESS, RECALL_ON_OPEN or OFFLINE set. A folder with one of them gets `F_CLOUD` and is never listed. That matches today's treatment of a dataless folder.
- `scandir_nofollow` on Windows: check `os.lstat(path)` with `is_link_entry` before listing, and refuse a link. This is a check-then-use gap, but it matches what the scan loop already decided from the listing, and the proof of concept accepts it. Record it in `SECURITY.md` terms only if S1 shows a cheaper handle-based check.
- Hard links: leave the `st_nlink > 1` branch unchanged. On Windows it never fires (`st_nlink` is 0), so hard links count once per link.

Done when: on both runners, the S10 check shows `C:/Documents and Settings` as a link tile of size 0, the symlink to `\\diskmap-test.invalid\share` as a link tile, and a fixture compressed file with a size below its logical size.

#### S6. Details, breadcrumbs, folders for state, and features that refuse

- `info`: use `entry_size`, `is_link_entry` and `is_cloud_entry`. Pick the denied, cloud and "adds up to more than the drive reports" notes from a small per-platform table. Keep the macOS text unchanged. Windows text for the proof of concept, plain and hedged:
  - Denied: "Windows did not allow Disk Map to read this folder, so its size is unknown. Some system folders are always private."
  - Cloud: "This item is in the cloud and not downloaded, so it likely uses little space on this PC."
  - Over total: "The items here add up to more than the drive reports as used. Hard links are counted once per link on Windows, so some files are counted more than once."
  - Network volume: replace "this Mac" with "this PC".
- `crumbs`: start at the drive root (`C:/`). The `/Volumes/` branch stays macOS only.
- `tree_payload`: the "missing" walk uses `ipath.dirname` and stops at the drive root.
- `state_dir`, cache folder in `main`, log folder: `%LOCALAPPDATA%\diskmap` on Windows (fall back to `~\AppData\Local\diskmap`). Pass the folder through as a native path, since it never reaches the page.
- `src/advice.py` `norm_path`: on Windows, map `C:/Users/<name>` to `~` (case-insensitive, `Public` and `Default` excluded), and look up rules with the path lower-cased. No Windows rules yet, so most items show "Not recognized". That is the expected result for the proof of concept.
- `main`: on Windows, `--app` and `--parent` exit with "diskmap: --app is only supported on macOS for now" before importing `fcntl`.
- `/api/reveal`: the error names the platform ("Reveal is not available on Windows yet").
- The startup message about Full Disk Access stays macOS only (it already checks `IS_MAC`).

Done when: unit tests cover `norm_path` for Windows home folders and `info` notes per platform, and the S10 check finds no HTTP 500 for any path it visits.

#### S7. Local server port binding on Windows

`HTTPServer` sets `allow_reuse_address`. On Windows `SO_REUSEADDR` likely lets a second socket bind a port that is already in use (**Verify** with the S1 probe, item 6). Then the port loop in `main` never moves to the next port, and another local program could bind the same port as Disk Map. `SECURITY.md` names "borrowing access" as a vulnerability class.

- On Windows, set `allow_reuse_address = False` on `Server` and set `SO_EXCLUSIVEADDRUSE` (`socket.SO_EXCLUSIVEADDRUSE`, Windows only) in `server_bind` before the bind.

Done when: a unit test that runs only on Windows starts two `Server` objects on one port and the second raises `OSError`. If the S1 probe shows the second bind already fails, record that and keep the explicit option anyway.

#### S8. Page: platform string and wording

- Add `var PLATFORM = '__PLATFORM__';` to `src/ui.html`, filled by `Handler.do_GET`, and set to `'mac'` in the artifact page by `build.py`. Add the marker to the `build.py` assertions. Keep `IS_MAC` as `PLATFORM === 'mac'`.
- APP mode handshake (`serve_stdio`): add `'platform': PLATFORM` and keep `'mac'`. The page reads `conn.platform` when present.
- Wording from a small table keyed by platform: "This Mac" or "This PC", "in Finder" or "in File Explorer". The Finder purgeable-space note shows on macOS only. The Reveal button shows on macOS only (already gated by `IS_MAC`).
- Display: paths stay forward-slash keys. Text shown to the user converts `/` to `\` on Windows in one function (`showPath`). `fitTail` splits the converted text on the platform separator.
- The demo stays macOS data with `PLATFORM = 'mac'`.

Done when: `tests/test_build.py` checks the new marker, and the S10 check finds `This PC` and `C:\` in the served page text for the root and a breadcrumb.

#### S9. Unit tests on Windows

- Run the existing suite on both runners. Expect failures in `tests/test_scanner.py` (it builds paths with `'/'` under `tempfile.mkdtemp`, uses `os.chmod` to make folders unreadable, and assumes `st_blocks`) and in `tests/test_server.py` (paths that start with `/`).
- For each failure, choose one fix and note it in the commit body:
  - The test checks a macOS or Linux behavior: `skipUnless(not IS_WIN, reason)`.
  - The test checks shared behavior: build the expected value with the platform helpers.
  - Permission tests: Windows needs a deny ACL (`icacls /deny`), and the runner is administrator, so mark them skipped on Windows with that reason.
- Add Windows-only tests for junctions and symlinks in the scan (S5), using a temporary folder on `C:`.
- Identical-output guard: before S2, save the `tree` and `info` output for the existing scanner fixture on Linux in a new `tests/data/` folder (`baseline-*.json`). Replace times, the temporary folder path and `gen` with fixed values before saving and before comparing. After each step S2 to S8, the Linux and macOS jobs compare against it. Update the baseline only in a commit that says why.

Done when: the unit tests pass on both Windows runners, with each skip giving a reason, and the baseline comparison passes on Linux and macOS.

#### S10. End-to-end check script and CI jobs

- Add `tests/windows_poc_check.py` (standard library only):
  1. Make a fixture folder on `C:` with a junction, a directory symlink to `\\diskmap-test.invalid\share`, a compressed file, a sparse file, a hard-linked pair and a name with a comma, an apostrophe and non-ASCII letters.
  2. Start `python dist/diskmap.py --no-browser --no-cache` with the fixture folder pinned. Read the link from its output. Fetch the page with the launch key and read the token from its `var TOKEN = '...'` line.
  3. Scan the fixture, then `C:/`. Poll `/api/status` until both are done. Fail after 30 minutes.
  4. Assert: no HTTP 500. The fixture tree has the expected link tiles, sizes and names. `C:/` totals are within an agreed band of `disk_usage` used (start at 25%, tighten after the first runs, and print the number every run). `info` works for the junction, the symlink, `C:/Windows`, `C:/Users` and one big file. `/api/reveal` returns the expected error. The port test from S7 passes.
  5. Print scan time, file count and the totals gap as a summary table in the job log.
- Add a `windows` job to `.github/workflows/ci.yml` with the matrix in 3.3. It runs the build, the unit tests and the check script. Set `TMP` and `TEMP` to a folder on `C:`.
- The job is not a required check until it has passed on main five runs in a row. Making it required is a branch protection change for the maintainer.
- Delete `windows-probe.yml` and `tools/windows_probe.py`.
- Add a "Not verified on Windows" list to `AGENTS.md` with the items in the last row of 3.5.

Done when: the `windows` job is green on both runners on a pull request, and the job summary shows scan time and the totals gap.

### 3.7 How to run the loop

- Work on a branch and open a pull request. `ci.yml` runs on every pull request, so each push runs the Windows jobs. Pushing is part of this work: the runners are the only Windows machines.
- Push after a step is green locally (Linux or macOS unit tests), not after every commit.
- Start the S1 probe by hand: `gh workflow run windows-probe.yml --ref <branch>`, then `gh run download` for the JSON.
- Main is branch-protected with four required checks. Merge through the pull request.

### 3.8 Done for the proof of concept

- The `windows` job is green on `windows-latest` (Python 3.8.10 and 3.13) and `windows-11-arm` (Python 3.13).
- The macOS and Linux jobs are still green, and the baseline output is unchanged.
- Section 3.4 holds the S1 probe answers with a run link.
- `AGENTS.md` has a "Not verified on Windows" list.
- `README.md` says Windows support is experimental and lists what is missing (3.2).

## 4. What is macOS-specific today

By function in `src/core.py` unless another file is named. Line numbers are left out because S2 to S8 move the code.

| Area | Today | Where |
|---|---|---|
| Volume list | Parses `/sbin/mount` output, or `/proc/mounts` on Linux | `read_mounts`, `parse_mac_mounts`, `parse_linux_mounts` |
| APFS volume group | Skips `/System/Volumes/Data` (firmlinks), counts helper volumes from `statvfs`, groups volumes by container | `_special_for`, `_container_of`, `Mount.container`, `_list_dir` |
| Free and used space | `os.statvfs` | `vol_space` |
| Size on disk | `st_blocks * 512` | `_list_dir`, `list_files`, `info` |
| Hard links | `st_dev` and `st_ino` from `DirEntry.stat()` | `_list_dir` |
| Cloud-only items | `st_flags & SF_DATALESS` | `_list_dir`, `list_files`, `info` |
| Network volumes | File system type from the mount table, checked by name before any stat | `NET_FS`, `net_mount_of`, `_special_for` |
| Last opened date, kind | `/usr/bin/mdls` | `_mdls` |
| Reveal | `/usr/bin/open -R` | `Handler.do_POST` |
| Launcher | `osacompile` AppleScript app | `install_app` |
| Single instance | `fcntl.flock` | `main` |
| Parent watch | `os.kill(pid, 0)` | `main`, `watch_parent` |
| Cache and log folders | `~/Library/Caches/diskmap`, `~/Library/Logs` | `state_dir`, `main` |
| Path shape | Paths start with `/` and split on `/` | `path_of`, `join`, `clean_path`, `lookup`, `crumbs`, `tree_payload`, `Handler._path_arg`, `Handler.do_POST`, `serve_stdio`; `src/ui.html` `fitTail`, `startDemo` |
| Platform flag | A two-valued `IS_MAC` in the page, the engine handshake and the build | `IS_MAC`, `Handler.do_GET`, `serve_stdio`; `src/ui.html` `IS_MAC`; `build.py` marker list |
| APP mode start | Mac-only Python locations, Mac-only support folder, a gate that refuses any platform but `darwin` | `src/ui.html` `launchEngine`, `startApp` |
| Advice rules | Mac locations, Mac package types, Mac wording ("Finder", "System Settings", "this Mac") | `src/advice.py`; `src/ui.html` detail panel |
| Home folder match | `/Users/<name>` or `/home/<name>` | `src/advice.py` `_HOME_RE`, `norm_path` |

## 5. Windows beyond the proof of concept

### 5.1 Hard links

File identity is the volume serial number plus the file index. `os.stat()` (not `DirEntry.stat()`) fills `st_dev`, `st_ino` and `st_nlink`. A full `os.stat` on every file likely slows the scan a lot. Proposal: do it only under `C:\Windows`, where most hard links likely live (WinSxS). Use the S10 totals gap and scan time to decide.

### 5.2 Network locations and links on a user's machine

- Classify each drive letter with `GetDriveTypeW` before any other call on it (S4). **Verify** on a real machine that it does not block on a disconnected mapped drive.
- `subst` drives and volumes mounted on folders can show the same files twice. Compare volume serial numbers to detect this. **Verify**
- Cloud placeholders may also be reparse points. The proof of concept never lists a folder with a recall attribute. M2b decides whether that is too strict for OneDrive users with Files On-Demand.

### 5.3 Reveal and launcher

| Feature | Windows approach | Notes |
|---|---|---|
| Reveal | `SHOpenFolderAndSelectItems` through `ctypes` | Takes item ID lists and needs `CoInitialize`. `explorer.exe /select,` has no current Microsoft documentation, so its quoting of commas and other characters is unknown. File names are untrusted |
| Launcher | A Start Menu shortcut to the packaged executable | Replaces `--install-app` on Windows. An installer creates it (section 6) |
| Window with no console | A console window is the simplest first version: it shows the link and stops the app when closed | A windowed build needs a way to quit. Proposal: stop when the page has not polled for a set time. See Q5 |
| Parent watch | `OpenProcess` plus `GetExitCodeProcess` through `ctypes` | Never `os.kill(pid, 0)` (3.2) |
| Single instance | `msvcrt.locking` on the lock file | |

### 5.4 Advice rules for Windows

Split `src/advice.py` into shared rules (folder names such as `node_modules`, file extensions, tool caches under the home folder) and one table per platform. The existing wording rules apply. Check every Windows rule against Microsoft documentation, and on a real machine where the rule depends on behavior, before writing its text.

Candidate locations, not yet verified:

| Location | Likely level | Likely proper way to free it |
|---|---|---|
| `C:\Windows`, `Program Files`, `Program Files (x86)`, `ProgramData` | Keep or Careful | Uninstall through Settings > Apps |
| `C:\Windows\WinSxS` | Keep | Never delete by hand. A DISM component cleanup command exists. Explorer likely overstates the size because of hard links |
| `C:\Windows\Installer` | Keep | Needed to repair and uninstall programs |
| `C:\Windows\SoftwareDistribution\Download` | Safe (likely) | Disk Cleanup or Storage Sense |
| `C:\Windows\Temp`, `%LOCALAPPDATA%\Temp` | Safe (likely) | Disk Cleanup or Storage Sense. Files in use cannot be removed |
| `pagefile.sys`, `swapfile.sys` | Keep | Managed by Windows. Size is set in system settings |
| `hiberfil.sys` | Keep | Turning hibernation off removes it. That also changes sleep and startup behavior |
| `C:\$Recycle.Bin` | Safe | Empty the Recycle Bin |
| `System Volume Information` | Keep | Restore point settings control its size |
| `C:\Windows.old` | Your call | Disk Cleanup, "Previous Windows installations" |
| `%APPDATA%`, `%LOCALAPPDATA%`, `LocalLow` | Careful | Same idea as `~/Library/Application Support` |
| `%LOCALAPPDATA%\Packages` | Careful | Store app data, same idea as Containers |
| Browser profiles under `%LOCALAPPDATA%` | Careful | The browser's own clear-data setting |
| WSL and Docker virtual disks (`.vhdx`) | Careful | Free space from inside, then compact |
| Memory dumps (`MEMORY.DMP`, `Minidump`) | Safe (likely) | Disk Cleanup |
| OneDrive folder | Careful | "Free up space" in Explorer keeps the file in the cloud |
| Installer types `.msi`, `.msix`, `.appx`, `.cab` | Safe or Your call | `.exe` is ambiguous: no installer rule for it |

Known Folder Move can place Documents, Desktop and Pictures inside the OneDrive folder. **Verify** how the home-folder rules should match in that case.

## 6. Packaging the Windows executable

### 6.1 Constraints that decide the choice

- APP mode embeds the Python source in the artifact page (`build.py`). A scanner in another language either splits the scanner in two or ends APP mode.
- The standard-library rule in `AGENTS.md` likely covers what runs at run time. A build tool such as PyInstaller would not break it. A webview library would, because it ships inside the app. See Q2.
- A packaged build carries its own Python. The Python 3.8 rule still applies to the source, because the script and APP mode use the system `python3`.
- A stock Windows install likely has no usable `python3`. **Verify**

### 6.2 Options

| Option | Size (measure, do not trust) | Antivirus and SmartScreen | Standard-library rule | Scanner count | Effort |
|---|---|---|---|---|---|
| OPT-K1 PyInstaller, folder mode | Likely the Python runtime plus the used modules | False positives are commonly reported for PyInstaller builds, more so for single-file mode. **Verify** with a spike | Kept (build tool only) | One | Low |
| OPT-K2 PyInstaller, single file | Similar, compressed | Likely worse: it unpacks to a temp folder at each start | Kept | One | Low |
| OPT-K3 Nuitka | Similar order | False positives also reported. **Verify** | Kept | One | Medium: needs a C compiler in the build |
| OPT-K4 python.org embeddable package plus launcher | Likely similar to K1 | Likely the cleanest: the interpreter files carry the Python project's own signature. **Verify** | Kept | One | Medium: Windows only, so macOS and Linux need another tool |
| OPT-K5 Go or Rust scanner | Likely a few MB, one file | Unsigned builds still meet SmartScreen | Not applicable to the new scanner. The Python scanner stays for APP mode, or APP mode ends | Two, or APP mode is dropped | High: scanner, advice and protocol rewritten |
| OPT-K6 Require the user to install Python | None | None | Kept | One | None, and a poor first experience |

Signing applies to every option:

- An unsigned download likely shows a SmartScreen warning. **Verify**
- Authenticode certificates now likely require the private key on hardware or in a cloud signing service, which affects CI. **Verify** current rules, prices and who is eligible for the managed services (Azure's signing service, SignPath and similar).
- A new certificate likely still shows warnings until it gains reputation. Whether an EV certificate skips that is uncertain. **Verify**

### 6.3 How the interface is shown

| Option | Dependency | Notes |
|---|---|---|
| OPT-U1 Default browser tab (today) | None | Works now. The token link and Host check carry over unchanged |
| OPT-U2 Browser in app-window mode (Edge or Chrome `--app=<link>`) | None shipped. Uses a browser that is likely already present on Windows | Own window with no extra code. **Verify** Edge is present on the supported Windows versions. Fall back to OPT-U1 (default browser tab) |
| OPT-U3 Webview library (pywebview or similar) | A third-party package at run time | Likely breaks the standard-library rule (Q2) |
| OPT-U4 Tauri or Electron shell | A second toolchain | Tauri likely targets iOS and Android too. **Verify** Only worth it if a native mobile app is decided (section 8) |

### 6.4 Recommendation

1. Build OPT-K1 (PyInstaller, folder mode) with OPT-U1 (default browser tab). Ship it as a zip first, then as an installer that adds a Start Menu shortcut.
2. Add OPT-U2 (browser in app-window mode) as an optional own-window mode after the first release.
3. Switch to OPT-K4 (python.org embeddable package plus launcher) if the unsigned spike build is flagged by Microsoft Defender, or by more than a few engines on a multi-engine scan.
4. Consider OPT-K5 (Go or Rust scanner) only if a full scan of a real Windows system drive stays slower than an agreed limit after the tuning in 5.1. Set the limit in Q6. The S10 scan time on the runner is a first data point, not the measure.

Reason: OPT-K1 (PyInstaller, folder mode) is the smallest change, keeps one scanner for all modes, and the same tool can build macOS and Linux.

An installer writes program files and a shortcut. That matches the existing exception for the `--install-app` launcher. It does not touch the user's own files.

## 7. Build, CI and tests after the proof of concept

### 7.1 Outputs per platform

| Platform | Output | Signing | Notes |
|---|---|---|---|
| Windows x64 and Arm64 | Folder build in a zip, later an installer | Authenticode on the executable and the installer | PyInstaller builds per architecture. `windows-11-arm` can build the Arm64 one |
| macOS | `.app` bundle in a zip or disk image | Developer ID signature, notarization, stapled ticket. Needs a paid Apple Developer membership | A signed app has a stable identity for Full Disk Access. This could replace the `osacompile` launcher. **Verify** the hardened-runtime settings a PyInstaller app needs |
| Linux | `diskmap.py` as today. A binary waits on Q7 (is Linux a real target) | None | Python is normally present, so the script is enough at first. A binary would likely be a PyInstaller build made on an old distribution, because it depends on the build machine's C library. **Verify** |

PyInstaller does not cross-compile. Each platform builds on its own runner.

### 7.2 CI

- `build.py` stays the single source step. A new packaging step consumes `dist/diskmap.py`.
- Run packaging only on a version tag or a manual trigger.
- Keep signing keys out of the repository. Use the CI secret store or a cloud signing service.
- Keep the `vermin -t=3.8-` check and the two embedding assertions in `build.py`.

### 7.3 Tests

| Need | Detail |
|---|---|
| Browser smoke tests | Playwright runs on Windows, macOS and Linux. Run `standalone_smoke.py` on the Windows runners once its test home can live under `C:/Users/<name>` |
| Fixture on Windows | The fixture reserves about 18 GB with `fallocate` or `mkfile`. Windows needs sparse or much smaller files, and the advice rules need a home folder under `C:/Users` |
| Packaged build test | Start the executable with `--no-browser`, read the link from its output, drive the page, check that the process exits cleanly |
| Manual checks on real machines | CI cannot simulate OneDrive placeholders, a disconnected mapped drive, SmartScreen, antivirus, or Full Disk Access. Keep a short checklist per platform, like "Not verified on macOS" in `AGENTS.md` |

## 8. iOS and Android

### 8.1 What the platforms allow

| Platform | Access | Limit |
|---|---|---|
| iOS | The app's own container. Folders the user picks in the Files picker. The photo library with permission. Total and free space of the device | No access to other apps' data or to system storage. An App Store app cannot produce a whole-device map. A File Provider extension lets an app offer files to others. It does not grant access to other apps' files |
| Android | Folders the user picks through the Storage Access Framework. Media through MediaStore with permission. Per-app sizes (app, data, cache) through the storage statistics service once the user grants usage access. **Verify** | Recent versions likely block picking the storage root, Downloads, and `Android/data`. The "all files access" permission is likely limited by Google Play policy to certain app types, and likely still excludes other apps' private folders. **Verify** all three |

Running the Python scanner on a phone is not a sound plan. iOS does not let an app start child processes. Recent CPython versions list iOS and Android as supported platforms at a low support tier, but packaging and store review would be new work. **Verify**

### 8.2 What a useful mobile product could be

| Option | Description | Verdict |
|---|---|---|
| OPT-V1 Scan viewer | Export a finished scan on the desktop. Open it on the phone in the same page. DEMO mode already works this way: it answers `tree` and `info` from a stored tree with a rule table (`src/ui.html` `demoCall`, `tools/gen_demo.py`) | Smallest step. May need no native app at all |
| OPT-V2 Folder scan | A native app that scans folders the user picks, plus per-app sizes on Android | Real but partial. Must state clearly that it is not the whole device |
| OPT-V3 Live remote view | The phone connects to the desktop scanner over the network | Not recommended. It ends the 127.0.0.1-only design that the token and Host check rely on |

An export holds every file and folder name on the drive. Keep the transfer local and started by the user (a file saved and opened). Do not add a hosted service.

### 8.3 Choices now that keep the door open

- Treat the four requests (`status`, `tree`, `info`, `scan`) as the contract. The proof of concept adds a platform string to the handshake (S8). Add a protocol version with the export format.
- The page treats paths as opaque keys (S8).
- Design one versioned export format. The scan cache (`save_cache`) and `demo.json` are the two precedents. Merge them if practical.
- Bake advice into the export. Advice runs in the scanner today, and some rule conditions read the file system (`_has_sibling`, `_is_venv`), so a viewer cannot recompute it.
- Hold advice rules as data tables per platform, so a native scanner could reuse them later.
- Add touch input to the page before any mobile work: tap, double tap, pinch. It uses click, double-click, scroll and Esc today.
- Keep platform wording out of fixed page text (S8 starts this).

## 9. Milestones

| ID | Step | Done when |
|---|---|---|
| M0 | Baseline on a real Mac. Work through "Not verified on macOS" in `AGENTS.md` and save reference outputs. Runs in parallel with M1 and M2a | The list is closed or each open item is recorded |
| M1 | Platform layer with no behavior change on macOS and Linux (S2, S3, S8 platform string) | The baseline comparison in S9 passes. The three smoke tests pass where they can run |
| M2a | Windows proof of concept on hosted runners (section 3) | Section 3.8 holds |
| M2b | Run from source on a real Windows 11 PC as a normal user | The last row of 3.5 is answered. Totals compared with Explorer. Scan time recorded |
| M3 | Windows advice rules and platform wording | Each rule is checked against documentation and on the machine from M2b |
| M4 | Packaging spike: unsigned PyInstaller folder build | Results recorded for Defender, a multi-engine scan and SmartScreen. Packaging choice confirmed or changed |
| M5 | CI packaging on tag, Windows signing, first Windows release | A signed build installs and runs on a second clean machine |
| M6 | macOS signed and notarized app. Linux script release | Gatekeeper accepts the app on a clean Mac |
| M7 | Scan export and viewer mode | A scan exported on a desktop opens on a phone browser |
| M8 | Decide on a native mobile folder scanner (OPT-V2) | Decision recorded |

First step: S1 in M2a. It needs nothing but the public repository.

## 10. Risks

| ID | Risk | Mitigation |
|---|---|---|
| RISK-1 | The refactor breaks macOS logic that was never verified on a Mac | The baseline comparison in S9 on the macOS and Linux runners. M0 in parallel |
| RISK-2 | The Windows scan is slow because size and hard-link data need extra calls per file | Call only when attributes require it (S5). Measure in S10 and M2b. OPT-K5 (Go or Rust scanner) is the fallback |
| RISK-3 | The scan triggers OneDrive downloads | Never list a folder with a recall attribute (S5). Test on a small OneDrive account in M2b first |
| RISK-4 | A link or mapped drive leads the scan to a network location and hangs | Name-surrogate reparse points are never entered (S5). Remote drives are never touched (S4). The S10 fixture has a symlink to an unreachable share |
| RISK-5 | Antivirus tools flag the packaged build | M4 spike before any release. OPT-K4 (python.org embeddable package plus launcher) is the fallback |
| RISK-6 | Signing costs or eligibility block CI signing | Research in M4, before M5 is scheduled |
| RISK-7 | Windows advice text contains wrong claims about Windows tools | Every rule verified in M3. Hedged wording, as today |
| RISK-8 | Totals differ from Explorer (hard links, compression, small files, shadow copies) and users distrust the map | An "unaccounted" tile exists today. The S6 note explains the overcount. S10 prints the gap on every run |
| RISK-9 | An exported scan leaks file names if shared carelessly | Local, user-started transfer only. Say what the file contains at export time |
| RISK-10 | APP mode cannot work on Windows | See Q3. The packaged build does not depend on it |
| RISK-11 | The runners are not a user's machine: administrator, UAC off, Developer Mode on, Server OS on x64, no OneDrive | Section 3.5 lists what they cannot answer. M2b covers it |
| RISK-12 | Another local program binds Disk Map's port on Windows | S7 |

## 11. Open questions for the maintainer

Answered questions are in section 2.

- Q2. Does the standard-library rule cover build tools, or only what runs at run time? The packaging recommendation assumes run time only.
- Q3. Should APP mode (the Claude desktop artifact) support Windows? It needs the artifacts server's `describe_capabilities` for `desktop` on Windows, and a way to find or ship a Python there.
- Q4. Is paying for signing acceptable (an Apple Developer membership and a Windows certificate or signing service)? If not, releases stay unsigned and show warnings.
- Q5. Console window or no console for the Windows build? No console needs an automatic stop rule.
- Q6. What full-scan time on a real Windows disk is acceptable? This sets the trigger for the Go or Rust fallback.
- Q9. Is the mobile goal a scan viewer (OPT-V1) or a folder scanner (OPT-V2)? The scan viewer is the recommendation.
- Q12. M2b needs a real Windows 11 PC. Who provides it, and when?
