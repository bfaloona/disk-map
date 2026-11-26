# Disk Map: cross-platform executables, Windows first

Status: draft, not reviewed
Date: 2026-11-26
Scope: make the scanner and advice work on Windows, ship per-platform executables, and keep a path open to iOS and Android.

Items marked **Verify** are from memory or from reading the code. Nothing in this plan was run on Windows. Check each one against current documentation or a real machine before you build on it.

## 1. Summary

- Keep the Python scanner. Put the OS-specific code behind one platform layer. Add a Windows implementation that uses `ctypes` (standard library).
- Package with PyInstaller in folder mode ("onedir"), built separately for Windows and macOS. Linux ships the script first. The interface stays in the default browser for the first release.
- Fallback 1: the python.org embeddable package plus a launcher, if antivirus tools flag the PyInstaller build.
- Fallback 2: a Go or Rust scanner, only if scan time on a real Windows disk stays too slow after tuning.
- Mobile cannot scan a whole device. The realistic mobile product is a viewer for a scan exported from a desktop. A scan export format is the one thing to design now.
- The tool stays read-only on every platform.

## 2. What is macOS-specific today

Line numbers refer to `src/core.py` unless another file is named.

| Area | Today | Where |
|---|---|---|
| Volume list | Parses `/sbin/mount` output, or `/proc/mounts` on Linux | 120-151 |
| APFS volume group | Skips `/System/Volumes/Data` (firmlinks), counts helper volumes from `statvfs`, groups volumes by container | 295-329, 476-481 |
| Free and used space | `os.statvfs` | 154-165 |
| Size on disk | `st_blocks * 512` | 503, 668, 949 |
| Hard links | `st_dev` and `st_ino` from `DirEntry.stat()` | 504-509 |
| Cloud-only items | `st_flags & SF_DATALESS` | 497, 666, 953 |
| Network volumes | File system type from the mount table, checked by name before any stat | 67, 468-486 |
| Last opened date, kind | `/usr/bin/mdls` | 1020-1041 |
| Reveal | `/usr/bin/open -R` | 1229 |
| Launcher | `osacompile` AppleScript app | 1313-1381 |
| Single instance | `fcntl.flock` | 1409-1429 |
| Parent watch | `os.kill(pid, 0)` | 1505 |
| Cache and log folders | `~/Library/Caches/diskmap`, `~/Library/Logs` | 1292, 1413, 1447 |
| Path shape | Paths start with `/` and split on `/` | 100, 104, 611, 796, 1160, 1215, 1257; `src/ui.html` 637 |
| Platform flag | A two-valued `IS_MAC` in the page, the engine handshake and the build | 42, 1184, 1276; `src/ui.html` 215, 334; `build.py` 7, 27 |
| APP mode start | Mac-only Python locations, Mac-only support folder, a gate that refuses any platform but `darwin` | `src/ui.html` 1412, 1418, 1505 |
| Advice rules | Mac locations, Mac package types, Mac wording ("Finder", "System Settings", "this Mac") | `src/advice.py`; `src/ui.html` 909-1088 |
| Home folder match | `/Users/<name>` or `/home/<name>` | `src/advice.py` 561 |

## 3. Windows equivalents

### 3.1 Code that fails or misbehaves on Windows as written

| Item | Likely behavior on Windows | Proposed change |
|---|---|---|
| `st_blocks` | The attribute does not exist. **Verify** | Platform function for size on disk (see 3.2) |
| `os.statvfs` | Not available. **Verify** | `shutil.disk_usage` |
| `fcntl` | The module does not exist | `msvcrt.locking`, or a named mutex through `ctypes` |
| `os.kill(pid, 0)` | Likely terminates the target process: any signal other than the two console events calls `TerminateProcess`. The watcher would kill the parent. **Verify** | `OpenProcess` plus `WaitForSingleObject` through `ctypes` |
| `DirEntry.stat()` | Returns zero for `st_ino`, `st_dev` and `st_nlink`. Hard-link detection then needs a second call per file. **Verify** | See 3.2 |
| Junctions | With `follow_symlinks=False` a junction likely looks like a plain folder, so the scan would enter it. **Verify** | See 3.3 |
| `os.path.normpath` (880, 1162, 1217, 1260) | Rewrites separators to backslashes | One platform function for path cleanup |
| `os.chmod(..., 0o600)` on the cache | Mostly has no effect | Rely on the user profile's default permissions. **Verify** they limit access to the user |

### 3.2 Scanner facts to map

| Topic | Windows approach | Notes |
|---|---|---|
| Size on disk (NTFS) | `GetCompressedFileSizeW`, or the allocation size from `GetFileInformationByHandleEx`, through `ctypes` | Either is one extra call per file. Proposal: call it only when the attributes show compressed, sparse or offline, and otherwise round the logical size up to the cluster size. **Verify** the result against Explorer's "Size on disk" |
| Very small files | NTFS likely stores them inside its file table, so they use no clusters | Rounding up would overstate them slightly. Decide whether that matters after measuring |
| Hard links | File identity is the volume serial number plus the file index. `os.stat()` (not `DirEntry.stat()`) fills `st_dev`, `st_ino`, `st_nlink` | Full `os.stat` on every file likely slows the scan a lot. Proposal: do it only under `C:\Windows`, where most hard links likely live (WinSxS). Measure first |
| Volumes | `GetLogicalDriveStringsW` and `GetDriveTypeW` through `ctypes` (`os.listdrives` needs Python 3.12) | Volume label from `GetVolumeInformationW`, local drives only |
| Free and used space | `shutil.disk_usage` | Free space likely reflects the calling user's quota |
| Cloud-only files | File attributes `RECALL_ON_DATA_ACCESS`, `RECALL_ON_OPEN`, `OFFLINE`, read from `st_file_attributes` | **Verify** the attribute values in Microsoft's documentation. **Verify** that OneDrive placeholders show these attributes to an ordinary process, and that listing a not-yet-downloaded folder downloads nothing. Until verified, treat a folder with `RECALL_ON_OPEN` the way a dataless folder is treated today: do not list it |
| Last opened date | No `mdls` equivalent found | Leave it out on Windows. Last-access times are often not updated. **Verify** |
| Access denied | No Full Disk Access switch. A standard user cannot read other profiles or some system folders | Do not ask for administrator rights by default. Reword the "no access" note per platform |
| Long paths | Paths over 260 characters can fail | Prefix `\\?\` at the OS boundary. **Verify** with `os.scandir` |
| File names | Unpaired surrogates are possible | The ASCII-only message rule already covers this. Test it |

### 3.3 Junctions, symbolic links and network locations

The rule "never stat or list a network mount unless the user asked" needs a new mechanism on Windows. There is no mount table of paths.

Proposed rules:

- Classify each drive letter with `GetDriveTypeW` before any other call on it. A drive of type remote is shown and never scanned unless the user asks. **Verify** that `GetDriveTypeW` does not block on a disconnected mapped drive.
- Reject UNC paths (`\\server\share`) in every request unless the user asked to scan that location.
- Never enter a reparse point: junctions, symbolic links and volumes mounted on a folder. Show it as a link tile. This prevents double counts, loops and reaching a network target through a link.
- Detect a reparse point from the attribute bit in `DirEntry.stat()`. This likely needs no extra call per entry. **Verify**
- Cloud placeholders may also be reparse points, and Windows may hide that from an ordinary process. **Verify** which case applies. If the scan sees them as reparse points, the rule above would skip the whole OneDrive tree, so placeholders need the cloud handling from 3.2 first. If Windows hides them, only the attribute bits from 3.2 can detect them.
- `subst` drives and volumes mounted on folders can show the same files twice. Compare volume serial numbers to detect this. **Verify**

### 3.4 Path model

| Option | Description | Cost | Risk |
|---|---|---|---|
| OPT-P1 | Native paths everywhere (`C:\Users\name`) | Touches every place that joins, splits or validates a path, in Python and in the page | Largest change to code that is not yet verified on a Mac |
| OPT-P2 | Forward slashes inside (`C:/Users/name`), native form only at the OS boundary and on screen | `join`, `path_of` and `lookup` likely work unchanged, because a root named `C:/` ends in `/`. Validators, `crumbs`, `norm_path` and display need changes | A missed conversion shows an odd path to the user |
| OPT-P3 | `pathlib` objects everywhere | Rewrite of the scan loop | Likely slower in the hot loop |

Recommendation: OPT-P2. In all options the page must treat a path as an opaque key and take breadcrumbs and display text from the scanner. Today `fitTail` (`src/ui.html` 637) and the demo breadcrumbs split on `/`.

Advice lookups must ignore case on Windows.

### 3.5 Reveal and launcher

| Feature | Windows approach | Notes |
|---|---|---|
| Reveal | `explorer.exe /select,<path>` | File names are untrusted. **Verify** quoting for names with commas, quotes and spaces. If quoting cannot be made safe, use `SHOpenFolderAndSelectItems` through `ctypes` |
| Launcher | A Start Menu shortcut to the packaged executable | Replaces `--install-app` on Windows. An installer creates it (section 4) |
| Window with no console | A console window is the simplest first version: it shows the link and closes the app when closed | A windowed build needs a way to quit. Proposal: stop when the page has not polled for a set time. See Q5 |
| Interface text | "Reveal in Finder", "this Mac", "System Settings" | The scanner supplies platform wording, or the page selects it from a platform string |

### 3.6 Advice rules for Windows

Split `src/advice.py` into shared rules (folder names such as `node_modules`, file extensions, tool caches under the home folder) and one table per platform. The existing wording rules apply. **Verify** every Windows rule on a real machine and against Microsoft documentation before writing its text.

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

## 4. Packaging the Windows executable

### 4.1 Constraints that decide the choice

- APP mode embeds the Python source in the artifact page (`build.py`). A scanner in another language either splits the scanner in two or ends APP mode.
- My reading of the standard-library rule: it covers what runs at run time. A build tool such as PyInstaller does not break it. A webview library does, because it ships inside the app. See Q2.
- A packaged build carries its own Python. The Python 3.8 rule still applies to the source, because the script and APP mode use the system `python3`.
- A stock Windows install likely has no usable `python3`. **Verify**

### 4.2 Options

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

### 4.3 How the interface is shown

| Option | Dependency | Notes |
|---|---|---|
| OPT-U1 Default browser tab (today) | None | Works now. The token link and Host check carry over unchanged |
| OPT-U2 Browser in app-window mode (Edge or Chrome `--app=<link>`) | None shipped. Uses a browser that is likely already present on Windows | Own window with no extra code. **Verify** Edge is present on the supported Windows versions. Fall back to OPT-U1 (default browser tab) |
| OPT-U3 Webview library (pywebview or similar) | A third-party package at run time | Breaks the standard-library rule as I read it |
| OPT-U4 Tauri or Electron shell | A second toolchain | Tauri likely targets iOS and Android too. **Verify** Only worth it if a native mobile app is decided (section 6) |

### 4.4 Recommendation

1. Build OPT-K1 (PyInstaller, folder mode) with OPT-U1 (default browser tab). Ship it as a zip first, then as an installer that adds a Start Menu shortcut.
2. Add OPT-U2 (browser in app-window mode) as an optional own-window mode after the first release.
3. Switch to OPT-K4 (python.org embeddable package plus launcher) if the unsigned spike build is flagged by Microsoft Defender, or by more than a few engines on a multi-engine scan.
4. Consider OPT-K5 (Go or Rust scanner) only if a full scan of a real Windows system drive stays slower than an agreed limit after the tuning in 3.2. Set the limit in Q6.

Reason: OPT-K1 (PyInstaller, folder mode) is the smallest change, keeps one scanner for all modes, and the same tool can build macOS and Linux.

An installer writes program files and a shortcut. That matches the existing exception for the `--install-app` launcher. It does not touch the user's own files.

## 5. Build, CI and tests

### 5.1 Outputs per platform

| Platform | Output | Signing | Notes |
|---|---|---|---|
| Windows x64 | Folder build in a zip, later an installer | Authenticode on the executable and the installer | ARM64: see Q7 |
| macOS | `.app` bundle in a zip or disk image | Developer ID signature, notarization, stapled ticket. Needs a paid Apple Developer membership | A signed app has a stable identity for Full Disk Access. This could replace the `osacompile` launcher. **Verify** the hardened-runtime settings a PyInstaller app needs |
| Linux | `diskmap.py` as today. A binary waits on Q7 (is Linux a real target) | None | Python is normally present, so the script is enough at first. A binary would likely be a PyInstaller build made on an old distribution, because it depends on the build machine's C library. **Verify** |

PyInstaller does not cross-compile. Each platform builds on its own runner.

### 5.2 CI

- `build.py` stays the single source step. A new packaging step consumes `dist/diskmap.py`.
- Each push spends Actions minutes, and Windows and macOS runners likely cost more per minute than Linux on private repositories. **Verify** current rates. Proposal: run packaging only on a version tag or a manual trigger. Run the Linux checks on demand.
- The repository has no remote configured today. See Q8.
- Keep signing keys out of the repository. Use the CI secret store or a cloud signing service.
- Keep the `vermin -t=3.8-` check and the two embedding assertions in `build.py`.

### 5.3 Tests

Another session is reworking the tests on its own branch. This section lists needs, not file edits.

| Need | Detail |
|---|---|
| Unit tests for the platform layer | Path cleanup, drive classification, link handling, size math and rule lookup, fed with recorded data. These run on any OS |
| Fixture on Windows | The fixture today reserves about 18 GB with `fallocate` or `mkfile`, and must sit under `/home` or `/Users`. Windows needs sparse or much smaller files and a way to tell the advice rules where the home folder is |
| Fixture cases to add | A junction, a symbolic link, a hard-linked pair, a compressed file, a sparse file, a path over 260 characters, a name with a comma and a quote |
| Browser smoke tests | Playwright runs on Windows, macOS and Linux. Run the standalone test on each runner |
| Packaged build test | Start the executable with `--no-browser`, read the link from its output, drive the page, check that the process exits cleanly |
| Manual checks on real machines | CI cannot simulate OneDrive placeholders, a disconnected mapped drive, SmartScreen, antivirus, or Full Disk Access. Keep a short checklist per platform, like "Not verified on macOS" in `CLAUDE.md` |

CI runners likely run as administrator, so "no access" cases differ from a normal user's machine. **Verify**

## 6. iOS and Android

### 6.1 What the platforms allow

| Platform | Access | Limit |
|---|---|---|
| iOS | The app's own container. Folders the user picks in the Files picker. The photo library with permission. Total and free space of the device | No access to other apps' data or to system storage. An App Store app cannot produce a whole-device map. A File Provider extension lets an app offer files to others. It does not grant access to other apps' files |
| Android | Folders the user picks through the Storage Access Framework. Media through MediaStore with permission. Per-app sizes (app, data, cache) through the storage statistics service once the user grants usage access. **Verify** | Recent versions likely block picking the storage root, Downloads, and `Android/data`. The "all files access" permission is likely limited by Google Play policy to certain app types, and likely still excludes other apps' private folders. **Verify** all three |

Running the Python scanner on a phone is not a sound plan. iOS does not let an app start child processes. Recent CPython versions list iOS and Android as supported platforms at a low support tier, but packaging and store review would be new work. **Verify**

### 6.2 What a useful mobile product could be

| Option | Description | Verdict |
|---|---|---|
| OPT-V1 Scan viewer | Export a finished scan on the desktop. Open it on the phone in the same page. DEMO mode already works this way: it answers `tree` and `info` from a stored tree with a rule table (`src/ui.html` `demoCall`, `tools/gen_demo.py`) | Smallest step. May need no native app at all |
| OPT-V2 Folder scan | A native app that scans folders the user picks, plus per-app sizes on Android | Real but partial. Must state clearly that it is not the whole device |
| OPT-V3 Live remote view | The phone connects to the desktop scanner over the network | Not recommended. It ends the 127.0.0.1-only design that the token and Host check rely on |

An export holds every file and folder name on the drive. Keep the transfer local and started by the user (a file saved and opened). Do not add a hosted service.

### 6.3 Choices now that keep the door open

- Treat the four requests (`status`, `tree`, `info`, `scan`) as the contract. Add a protocol version and a platform string to the handshake.
- The page treats paths as opaque keys (section 3.4).
- Design one versioned export format. The scan cache (`save_cache`) and `demo.json` are the two precedents. Merge them if practical.
- Bake advice into the export. Advice runs in the scanner today, and some rule conditions read the file system (`_has_sibling`, `_is_venv`), so a viewer cannot recompute it.
- Hold advice rules as data tables per platform, so a native scanner could reuse them later.
- Add touch input to the page before any mobile work: tap, double tap, pinch. It uses click, double-click, scroll and Esc today.
- Keep platform wording out of fixed page text.

## 7. Milestones

| ID | Step | Done when |
|---|---|---|
| M0 | Baseline on a real Mac. Work through "Not verified on macOS" in `CLAUDE.md` and save reference outputs | The list is closed or each open item is recorded |
| M1 | Platform layer with no behavior change. Move the OS-specific code from section 2 behind one set of functions. Replace the two-valued flag with a platform string and keep the old field for now | The three smoke tests pass. Tree and info output for the fixture is identical before and after |
| M2 | Run from source on one real Windows machine. Path model, drive list, link rules, size on disk, cache folder, Reveal | A full scan of `C:` finishes. Totals are close to what Windows reports. Scan time is recorded. The **Verify** items in section 3 are answered |
| M3 | Windows advice rules and platform wording | Each rule is checked on the machine from M2 |
| M4 | Packaging spike: unsigned PyInstaller folder build | Results recorded for Defender, a multi-engine scan and SmartScreen. Packaging choice confirmed or changed |
| M5 | CI packaging on tag, Windows signing, first Windows release | A signed build installs and runs on a second clean machine |
| M6 | macOS signed and notarized app. Linux script release | Gatekeeper accepts the app on a clean Mac |
| M7 | Scan export and viewer mode | A scan exported on a desktop opens on a phone browser |
| M8 | Decide on a native mobile folder scanner (OPT-V2) | Decision recorded |

First step: M1. It needs no Windows machine and no decision. M0 needs the maintainer at a Mac and can run in parallel. Q11 asks whether M0 must finish first, because M1 changes code that has never run on a real Mac.

## 8. Risks

| ID | Risk | Mitigation |
|---|---|---|
| RISK-1 | The refactor in M1 breaks macOS logic that was never verified on a Mac | M0 baseline, and the identical-output check in M1 |
| RISK-2 | The Windows scan is slow because size and hard-link data need extra calls per file | Call only when attributes require it. Measure in M2. OPT-K5 (Go or Rust scanner) is the fallback |
| RISK-3 | The scan triggers OneDrive downloads | Do not list placeholder folders until M2 proves it is safe. Test on a small OneDrive account first |
| RISK-4 | A link or mapped drive leads the scan to a network location and hangs | The rules in 3.3. Fixture cases for junctions. Manual check with a disconnected drive |
| RISK-5 | Antivirus tools flag the packaged build | M4 spike before any release. OPT-K4 (python.org embeddable package plus launcher) is the fallback |
| RISK-6 | Signing costs or eligibility block CI signing | Research in M4, before M5 is scheduled |
| RISK-7 | Windows advice text contains wrong claims about Windows tools | Every rule verified in M3. Hedged wording, as today |
| RISK-8 | Totals differ from Explorer (hard links, compression, small files, shadow copies) and users distrust the map | An "unaccounted" tile exists today. Add a Windows note that explains the gap |
| RISK-9 | An exported scan leaks file names if shared carelessly | Local, user-started transfer only. Say what the file contains at export time |
| RISK-10 | APP mode cannot work on Windows | See Q3. The packaged build does not depend on it |

## 9. Open questions for the maintainer

- Q1. Is there a real Windows machine (not only a virtual machine) for M2 and M4? OneDrive, SmartScreen and scan time need one.
- Q2. Does the standard-library rule cover build tools, or only what runs at run time? The recommendation assumes run time only.
- Q3. Should APP mode (the Claude desktop artifact) support Windows? I could not read the artifacts server's `describe_capabilities` for `desktop` from this session, so I do not know what it offers on Windows. Windows also likely lacks a system `python3`.
- Q4. Is paying for signing acceptable (an Apple Developer membership and a Windows certificate or signing service)? If not, releases stay unsigned and show warnings.
- Q5. Console window or no console for the Windows build? No console needs an automatic stop rule.
- Q6. What full-scan time on a real Windows disk is acceptable? This sets the trigger for the Go or Rust fallback.
- Q7. Which targets: Windows 10 and 11, x64 only, or ARM64 too? Is Linux a real target or a courtesy?
- Q8. Where do releases live? The repository has no remote today. Public or private changes CI cost.
- Q9. Is the mobile goal a scan viewer (OPT-V1) or a folder scanner (OPT-V2)? The scan viewer is the recommendation.
- Q10. Path model: accept OPT-P2 (forward slashes inside)?
- Q11. Should M0 (real Mac baseline) block M1?
