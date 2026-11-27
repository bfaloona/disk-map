# Disk Map: Windows installable app

Status: draft, parked. Pick it up when a Windows app becomes a priority.
Date: 2026-11-26
Scope: options and effort to make Disk Map on Windows 11 an installed app (Start menu entry, own window, uninstall), not a script that serves a page to the browser. Builds on `docs/plans/2026-11-26-cross-platform.md` (the cross-platform plan). All step counts are on top of milestone M2a in that plan (proof of concept steps S1 to S10).

**Verify** marks a claim that nobody has checked against documentation or a machine. Facts that documentation answers carry a source link. Nothing here has run on Windows.

## Edit history

| Date | Type | Note |
|---|---|---|
| 2026-11-26 | drafted | From a research pass by a second agent (web sources, `src/` and the cross-platform plan). No code changed. The maintainer has not reviewed it |

## 1. When to pick this up

- After M2a (the proof of concept runs from source on the GitHub Actions runners).
- When the maintainer answers W1 to W8 (section 7).
- If stage 1 goes ahead, add its steps to the cross-platform plan as a new milestone between M2b and M3.

## 2. Recommendation

One sequence, two stages:

1. Port `--install-app` to Windows with the standard library (OPT-I1), and add an Edge app window (OPT-I2). This reaches people who have Python or will install it.
2. For people without Python, ship the python.org embeddable package plus `diskmap.py` as an MSIX package through the Microsoft Store (OPT-I5). This replaces the unsigned PyInstaller zip in section 6.4 step 1 of the cross-platform plan.

Reason: neither stage ships an unsigned executable built by the maintainer. Smart App Control blocks unsigned executables with no override, and the Store signs packages for free. Both stages keep the standard-library rule for the shipped code.

APP mode in the Claude desktop app on Windows (OPT-I7) is cheap, but it reaches only people in the maintainer's Claude organization. Do it only if W6 is yes.

## 3. Findings that change the cross-platform plan

| Plan item | Finding | Source |
|---|---|---|
| 6.4 step 1 and M4 (unsigned PyInstaller build; measure Defender and SmartScreen) | Smart App Control in enforcement mode blocks unknown, unsigned executables. The dialog has no override. Recent updates let people turn it on without a clean install. An M4 spike that measures only SmartScreen misses this | [Smart App Control overview](https://learn.microsoft.com/en-us/windows/apps/develop/smart-app-control/overview), [FAQ](https://support.microsoft.com/en-us/topic/what-is-smart-app-control-285ea03d-fa88-4d56-882e-6698afdb7003) |
| 6.2 whether an EV certificate skips SmartScreen | It does not. A new OV or EV signature still shows "unrecognized" until reputation builds | [SmartScreen reputation](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/smartscreen-reputation) |
| 6.2 signing services, Q4 (paid signing) | Artifact Signing (formerly Trusted Signing): from $9.99 a month, no hardware token, works from GitHub Actions, needs a paid Azure subscription. For individuals: likely US and Canada only (**Verify**, community answers only) | [Artifact Signing FAQ](https://learn.microsoft.com/en-us/azure/artifact-signing/faq), [Q&A](https://learn.microsoft.com/en-us/answers/questions/2243504/trusted-signing-for-other-countries) |
| Q4 | Microsoft Store: free registration for individuals in some markets. The Store signs MSIX packages for free. Store installs get no SmartScreen warning | [Windows blog](https://blogs.windows.com/windowsdeveloper/2025/09/10/free-developer-registration-for-individual-developers-on-microsoft-store/), [SmartScreen reputation](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/smartscreen-reputation) |
| Q3, RISK-10 (APP mode on Windows) | The Claude desktop capability documents Windows: `os.platform()` reads `"win32"`, the tray replaces the menu bar, `exec` runs in cmd.exe | Claude desktop capability type definitions, runtime contract 0.2.99 |
| 6.1 no usable `python3` | The classic python.org installer is deprecated since 3.14 and ends at 3.16. The Python install manager replaces it: per-user installs, with `py`, `python`, `pythonw` and `pyw` aliases. A stock Windows has a `python` alias that opens the Store | [Using Python on Windows](https://docs.python.org/3/using/windows.html), [Microsoft Python FAQ](https://learn.microsoft.com/windows/python/faqs) |
| 6.3 OPT-U3 (WebView2) | The WebView2 runtime is part of Windows 11 | [WebView2 distribution](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/distribution) |

## 4. Options

Option IDs use the prefix OPT-I (installable). The cross-platform plan uses OPT-K, U, V and P.

| ID | What it is | Needs Python on the PC | First file the user runs, and its signer | Standard-library rule |
|---|---|---|---|---|
| OPT-I1 | `diskmap.py --install-app` on Windows: Start menu shortcut to `pythonw.exe`, per-user uninstall entry, browser tab | Yes | `python.exe` (Python Software Foundation) | Kept |
| OPT-I2 | Own window through `msedge --app=<link>`. An add-on to I1, I3 or I5 | No extra | None new | Kept (Edge is part of Windows) |
| OPT-I3 | Embeddable Python plus `diskmap.py` in an Inno Setup per-user installer | No | `setup.exe`, built by the maintainer, unsigned unless Q4 | Kept for the Python code. The installer is a build tool output (Q2) |
| OPT-I4 | PyInstaller folder build plus Inno Setup (the cross-platform plan's OPT-K1, for comparison) | No | `setup.exe`, then `diskmap.exe`, both built by the maintainer | Kept (Q2) |
| OPT-I5 | Embeddable Python plus `diskmap.py` in an MSIX package through the Microsoft Store | No | The Store, then `pythonw.exe` inside the Store-signed package | Kept (Q2) |
| OPT-I6 | Own window through WebView2 | Depends | Depends | Broken by pywebview. Kept only with hand-written `ctypes` COM, which is large |
| OPT-I7 | APP mode in the Claude desktop app on Windows | Yes | The Claude desktop app, then the user's `python.exe` | Kept |

### 4.1 Warnings, antivirus, and what a runner can prove

| ID | SmartScreen | Smart App Control | Defender | Runner can prove | Only a real PC can show |
|---|---|---|---|---|---|
| OPT-I1 | None: no maintainer executable (**Verify**: Python ignores the Mark of the Web on a `.py` file) | Allowed (**Verify**): `python.exe` is signed | Low risk (**Verify**) | Shortcut file and target, registry entry, launch, server answers, clean uninstall | Start menu entry and icon, Settings > Apps entry, no console flash, standard user |
| OPT-I2 | None | None | None | Edge starts with `--app`, server logs the page request | The window, and that closing it stops Disk Map |
| OPT-I3 | Unsigned: "Windows protected your PC", then "Run anyway" | Unsigned `setup.exe` is blocked, no override | Lower risk than PyInstaller (**Verify**) | Silent install and uninstall, file and registry state | Every prompt |
| OPT-I4 | As I3, for two files | Both files blocked unless signed | False positives are widely reported for the PyInstaller bootloader ([discussion](https://discuss.python.org/t/pyinstaller-false-positive/43171), [issue 5579](https://github.com/pyinstaller/pyinstaller/issues/5579)) | As I3 | Every prompt, Defender verdict |
| OPT-I5 | None for Store installs | Passes: Store-signed | Low risk (**Verify**) | Build, unsigned install with `Add-AppxPackage -AllowUnsigned` ([unsigned packages](https://learn.microsoft.com/en-us/windows/msix/package/unsigned-package)), Start menu entry through `Get-StartApps`, launch, remove | Store certification, Store install, where cache and log writes land |
| OPT-I6 | Depends | Depends | Depends | Little: the window needs a desktop session | The window |
| OPT-I7 | None | Allowed (**Verify**) | Low risk | `--stdio` engine through pipes: ready line, `tree` of `C:/` | Install as app, full-access prompt, Python discovery, the window |

Defender is likely off on the runners (**Verify**). Add `Get-MpComputerStatus` to the S1 probe before planning any Defender check there.

## 5. Work per option

### 5.1 OPT-I1 Standard-library launcher (Medium, about 6 steps)

- Split `install_app` in `src/core.py` into a macOS branch (today's `osacompile`) and a Windows branch.
  - Copy the script to `%LOCALAPPDATA%\Disk Map\diskmap.py`. Keep the `INSTALL_MARKER` check and `installed.json`.
  - Make a `.lnk` file in the per-user Start menu folder ([known folders](https://learn.microsoft.com/en-us/windows/win32/shell/knownfolderid)). The standard library has no shortcut API. Start with PowerShell's `WScript.Shell` COM object through `subprocess`. The fallbacks are the [MS-SHLLINK](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-shllink/16cb4ca1-9339-4d0c-a68d-bf1d6cc0f943) bytes or `IShellLinkW` through `ctypes`.
  - Point the shortcut at `pythonw.exe` next to `sys.executable`, with `-I -c LOADER <script> <sha256> --app`. **Verify**: `LOADER` fits the argument length limit.
  - Write the uninstall entry under `HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\DiskMap` with `winreg` (**Verify**: the per-user key comes from NSIS docs, not Microsoft docs; [NSIS](https://nsis.sourceforge.io/Add_uninstall_information_to_Add/Remove_Programs)).
- Add `--uninstall-app`. It removes the shortcut, the registry key and the script copy, each only if the marker shows Disk Map made it (W1).
- In the `--app` branch of `main`, replace `fcntl.flock` with `msvcrt.locking`, and put the log in `%LOCALAPPDATA%\diskmap` (cross-platform plan S6).
- Pick a quit rule (W4). `watch_parent` needs `OpenProcess` instead of `os.kill(pid, 0)`.
- No change to `src/ui.html` or `build.py`.
- Tests: unit tests for the shortcut arguments and registry values with a fake `winreg`. A runner job: install, read the shortcut back, `reg query`, run the target, poll `/api/status`, uninstall, assert nothing is left.
- Docs: README, the AGENTS.md write list, SECURITY.md.

### 5.2 OPT-I2 Edge app window (Small, about 3 steps)

- Find `msedge.exe` (**Verify**: App Paths registry key or the default install folder). Start it with `--app=<link>` and `--user-data-dir` under Disk Map's state folder. Fall back to `webbrowser.open`.
- Edge's command-line flags have no official documentation ([community list](https://textslashplain.com/2022/01/05/edge-command-line-arguments)). **Verify**: a separate profile folder gives a separate Edge process, so Disk Map can stop when the window closes.
- New write: an Edge profile folder (W1). The token flow does not change.

### 5.3 OPT-I3 Embeddable Python plus Inno Setup (Medium to Large, about 7 steps)

- Build job: download the embeddable zip per architecture and check its hash. It has no pip or tkinter. **Verify**: an Arm64 embeddable zip exists.
- Inno Setup script: per user (`PrivilegesRequired=lowest`), Start menu entry to `pythonw.exe`, uninstaller. Install Inno Setup in the job (**Verify**: likely not on the runner image, [runner-images issue 11644](https://github.com/actions/runner-images/issues/11644)).
- Runner: silent install, launch, silent uninstall, state checks. Release on tag. Optional signing (Q4).

### 5.4 OPT-I4 PyInstaller plus Inno Setup

The same work as I3, plus PyInstaller, and two unsigned files. Smart App Control blocks both. Kept here only as the baseline.

### 5.5 OPT-I5 Microsoft Store MSIX (Large, about 9 steps plus Store review)

- Open a Partner Center individual account and reserve the app name ([sign up](https://learn.microsoft.com/en-us/windows/apps/get-started/sign-up)).
- Write `AppxManifest.xml`: identity, `runFullTrust`, entry point `pythonw.exe` with arguments (**Verify**: `uap10:Parameters`), icons.
- Build with `makeappx` per architecture or as a bundle (**Verify**: the runner's Windows SDK has it).
- Runner: unsigned install, `Get-StartApps`, launch, remove.
- Check where `%LOCALAPPDATA%` writes go inside a package (**Verify**: redirected to the package folder), and that the scan still reads the real folders.
- Store listing: privacy policy page, screenshots, description. Submission and certification. A release workflow. Optional winget entry that points at the Store app (**Verify**).
- MSIX gives the Start menu entry, uninstall and updates.

### 5.6 OPT-I6 WebView2 (Large, not recommended)

Python reaches WebView2 only through pywebview (third-party, breaks the rule) or hand-written COM through `ctypes` with its own window and message loop.

### 5.7 OPT-I7 APP mode on Windows (Small to Medium, about 4 steps)

Needs cross-platform plan S3 (`valid_path` in `serve_stdio`) and S8 (`platform` in the handshake) first.

- `startApp` in `src/ui.html`: accept `"win32"` as well as `"darwin"`.
- `launchEngine`: engine at `~/AppData/Local/Disk Map/engine.py`. Python candidates: the install manager's folder, python.org per-user folders, `C:\Windows\py.exe`. Skip the Store alias in `%LOCALAPPDATA%\Microsoft\WindowsApps`. **Verify**: whether a spawned `python.exe` flashes a console window.
- Gate text uses "this PC" from the S8 wording table. Reveal works through `desktop.shell.showItemInFolder`.
- Runner: drive `--stdio` through pipes in the S10 script. The page side needs the real PC.
- Reach: full access works only on an artifact from the person's own organization, or one that Anthropic approved. The PC also needs Python.

## 6. Size summary

| ID | Size | Steps after M2a | Needs signing (Q4) |
|---|---|---|---|
| OPT-I1 | Medium | about 6 | No |
| OPT-I2 | Small | about 3 | No |
| OPT-I3 | Medium to Large | about 7 | Yes, for Smart App Control users |
| OPT-I4 | Medium to Large | about 8 | Yes, for two files |
| OPT-I5 | Large | about 9, plus Store review | No (the Store signs) |
| OPT-I6 | Large | not estimated | Depends |
| OPT-I7 | Small to Medium | about 4 | No |

## 7. Questions for the maintainer

- W1. May the AGENTS.md write list grow to cover a Start menu shortcut, a per-user uninstall registry entry, an Edge profile folder, and an uninstall that deletes Disk Map's own files (marker-checked, like `--install-app` today)?
- W2. Who is the Windows audience: people who already have Python (stage 1 is enough), or anyone (stage 2 is needed)?
- W3. Is a Microsoft Store listing acceptable: a public listing under the maintainer's name, Store policies, a privacy policy page and review time?
- W4. What is the quit rule for the launcher: close with the Edge window, stop after the page goes quiet, or keep a console window? This ties to Q5 in the cross-platform plan.
- W5. Is an Edge app window acceptable when it relies on Edge flags with no official documentation?
- W6. Is APP mode on Windows worth about 4 steps when only the maintainer's organization gets full access?
- W7. Which Python installs should the launcher and APP mode support: the install manager only, or also Store Python and older python.org installs?
- W8. Ship Arm64 builds for I3 or I5, or x64 only? Windows on Arm runs x64 programs through emulation.

## 8. Sources

- [Smart App Control overview](https://learn.microsoft.com/en-us/windows/apps/develop/smart-app-control/overview)
- [Smart App Control FAQ](https://support.microsoft.com/en-us/topic/what-is-smart-app-control-285ea03d-fa88-4d56-882e-6698afdb7003)
- [SmartScreen reputation for Windows app developers](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/smartscreen-reputation)
- [Artifact Signing FAQ](https://learn.microsoft.com/en-us/azure/artifact-signing/faq)
- [Free Store registration for individuals](https://blogs.windows.com/windowsdeveloper/2025/09/10/free-developer-registration-for-individual-developers-on-microsoft-store/)
- [Unsigned MSIX packages](https://learn.microsoft.com/en-us/windows/msix/package/unsigned-package)
- [Using Python on Windows](https://docs.python.org/3/using/windows.html)
- [WebView2 distribution](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/distribution)
- [winget manifest](https://learn.microsoft.com/windows/package-manager/package/manifest)
