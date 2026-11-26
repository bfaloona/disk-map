# ---------------------------------------------------------------------------
# Advice engine: rule-based guidance on how important a file or folder is.
# Rules match by exact location, by folder name, by package type, or by file
# extension. They are heuristics, not guarantees.
# ---------------------------------------------------------------------------

LV_SAFE, LV_REVIEW, LV_CAUTION, LV_KEEP, LV_MIXED, LV_UNKNOWN = 's', 'r', 'c', 'k', 'm', 'u'


class Rule(object):
    __slots__ = ('lv', 'title', 'why', 'how', 'strong', 'cond')

    def __init__(self, lv, title, why, how=(), strong=False, cond=None):
        self.lv = lv
        self.title = title
        self.why = why
        self.how = tuple(how)
        self.strong = strong   # container rule wins over a file's own type
        self.cond = cond       # optional extra check: cond(norm_path, real_path)


def _in_library_or_hidden(np, real):
    return '/Library/' in np or '/.' in np


def _has_sibling(*names):
    def check(np, real):
        parent = os.path.dirname(real)
        for n in names:
            try:
                if os.path.lexists(os.path.join(parent, n)):
                    return True
            except OSError:
                pass
        return False
    return check


def _is_venv(np, real):
    try:
        return os.path.lexists(os.path.join(real, 'pyvenv.cfg'))
    except OSError:
        return False


def _not_home_top(np, real):
    return np.count('/') > 1


_BUILD_MARKERS = ('package.json', 'build.gradle', 'build.gradle.kts', 'CMakeLists.txt',
                  'setup.py', 'pyproject.toml', 'Makefile', 'pom.xml', 'Cargo.toml',
                  'pubspec.yaml', 'tsconfig.json')

# -- rules that describe a container itself but are NOT inherited by children --
SELF_RULES = {
    '/': Rule(LV_MIXED, 'Startup disk',
              'A mix of macOS itself, your apps and your own files. Zoom in: almost all '
              'the space you can recover is under Users and Applications.'),
    '/Users': Rule(LV_MIXED, 'User accounts',
                   'One folder per person who uses this Mac, plus Shared. Your own files, '
                   'app data and developer caches all live in your home folder.'),
    '~': Rule(LV_MIXED, 'Home folder',
              'Everything that belongs to this user: documents and media (your call), app '
              'data in Library (careful), and tool caches that are safe to clear.'),
    '~/Library': Rule(LV_MIXED, 'App data and settings (Library)',
                      'Mostly data and settings that apps rely on, mixed with parts that are '
                      'safe to clear such as Caches, Logs and Xcode DerivedData.'),
    '/Library': Rule(LV_MIXED, 'System-wide app support',
                     'Shared files for installed apps, drivers and fonts, plus system-wide '
                     'caches and logs.'),
    '/private': Rule(LV_MIXED, 'System working files',
                     'Temporary files, logs and databases that macOS manages.'),
    '/private/var': Rule(LV_MIXED, 'System working files',
                         'Temporary files, logs and databases that macOS manages.'),
    '/opt': Rule(LV_MIXED, 'Optional software',
                 'Tools installed outside the App Store, typically Homebrew on Apple silicon.'),
    '/System/Volumes': Rule(LV_KEEP, 'macOS support volumes',
                            'Small helper volumes macOS uses for booting, updates and virtual memory.'),
}

_KEEP_SYS = Rule(LV_KEEP, 'Core system files',
                 'Part of macOS or its Unix foundation. Removing anything here can stop the '
                 'Mac from working.',
                 ['Nothing to recover here. Look in your home folder and Applications instead.'],
                 strong=True)

_CRED = Rule(LV_KEEP, 'Keys and credentials',
             'Small, and important: keys or credentials that tools use to sign in. Losing '
             'them can lock you out of servers or services.', strong=True)

_BROWSER = Rule(LV_CAUTION, 'Browser profile',
                'Bookmarks, history, saved logins, extensions and site data for a browser.',
                ["Use the browser's own Clear Browsing Data setting to shrink it; choose cached "
                 "files and leave passwords alone."])

_LANG_VERSIONS = Rule(LV_REVIEW, 'Installed language versions or environments',
                      'Each version or environment can be hundreds of MB to several GB. Unused '
                      'ones can be removed and reinstalled later.',
                      ['Remove old versions with the tool that installed them (pyenv, nvm, conda, uv, rustup and so on) rather than deleting folders by hand.'],
                      strong=True)

_DEVICE_SUPPORT = Rule(LV_SAFE, 'Xcode device support files',
                       'Debug symbols copied from devices you have connected. Xcode copies them '
                       'again the next time you connect a device on that OS version.',
                       ['Delete folders for OS versions you no longer test on.'], strong=True)

_GARAGEBAND = Rule(LV_REVIEW, 'GarageBand / Logic sound library',
                   'Downloadable instruments and loops. Only useful if you make music with '
                   'GarageBand, Logic or MainStage, and they can be downloaded again.',
                   ['System Settings > General > Storage has a Music Creation entry that can remove the sound library.'])

# -- rules for an exact location; children inherit them unless a closer rule matches --
PATH_RULES = {
    # ---- macOS and Unix ----
    '/System': Rule(LV_KEEP, 'macOS',
                    'The operating system. It sits on a sealed, read-only volume: macOS will '
                    'not let you change it, and there is nothing here to clean up.',
                    ['Nothing to recover here. Look in your home folder and Applications instead.'],
                    strong=True),
    '/System/Volumes/VM': Rule(LV_KEEP, 'Virtual memory (swap and sleep image)',
                               'macOS uses this when apps need more memory than the Mac has. '
                               'It grows and shrinks on its own.',
                               ['Restarting the Mac usually shrinks it.',
                                'Quitting memory-hungry apps (browsers with many tabs, VMs) keeps it small.'],
                               strong=True),
    '/private/var/vm': Rule(LV_KEEP, 'Virtual memory (swap and sleep image)',
                            'macOS uses this when apps need more memory than the Mac has.',
                            ['Restarting the Mac usually shrinks it.'], strong=True),
    '/usr': _KEEP_SYS, '/bin': _KEEP_SYS, '/sbin': _KEEP_SYS,
    '/private': Rule(LV_KEEP, 'System working files',
                     'Files macOS manages for itself: settings, databases, logs and temporary data.',
                     ['Leave these to macOS. A restart clears most temporary data.'], strong=True),
    '/private/var/folders': Rule(LV_CAUTION, 'Temporary files and caches of running apps',
                                 'macOS and apps keep per-user temporary files and caches here '
                                 'and clean them up themselves. Deleting by hand while apps are '
                                 'running can break them.',
                                 ['Restart the Mac. macOS clears much of this at startup.'], strong=True),
    '/private/tmp': Rule(LV_CAUTION, 'Temporary files',
                         'Scratch space for apps and tools. macOS empties it at restart.',
                         ['Restart the Mac rather than deleting by hand.'], strong=True),
    '/private/var/log': Rule(LV_CAUTION, 'System logs',
                             'macOS rotates and trims these automatically. Normally small.',
                             ['If this is large, one misbehaving app is probably writing a huge log: find the big file and deal with that app.']),
    '/usr/local': Rule(LV_CAUTION, 'Manually installed tools',
                       'Software installed outside the App Store. On Intel Macs, Homebrew lives here.',
                       ['If you use Homebrew: `brew cleanup -s` and `brew autoremove`.']),
    '/opt/homebrew': Rule(LV_CAUTION, 'Homebrew packages',
                          'Command-line tools and libraries installed with Homebrew. Other tools '
                          'depend on them, so remove packages through Homebrew, not by deleting folders.',
                          ['`brew cleanup -s` removes old versions and cached downloads.',
                           '`brew autoremove` removes dependencies nothing needs any more.',
                           '`brew uninstall <name>` for tools you no longer use.'], strong=True),
    '~/.homebrew': Rule(LV_CAUTION, 'Homebrew packages (custom location)',
                        'Looks like a Homebrew installation in your home folder. Remove packages '
                        'through Homebrew, not by deleting folders.',
                        ['`brew cleanup -s` removes old versions and cached downloads.',
                         '`brew autoremove` removes dependencies nothing needs any more.'], strong=True),
    '/cores': Rule(LV_SAFE, 'Crash dumps',
                   'Memory dumps written when a program crashed. Only useful for debugging that crash.',
                   ['Safe to delete (needs an admin password).'], strong=True),
    '/Applications': Rule(LV_REVIEW, 'Applications',
                          'Apps can be downloaded again from the App Store or the vendor, so the app '
                          'itself is replaceable. For paid apps, check you still have the license or '
                          'installer first.',
                          ['Remove apps you no longer use.',
                           "Deleting an app leaves its data behind in your Library. That is usually small, but not always."]),
    '~/Applications': Rule(LV_REVIEW, 'Applications (this user only)',
                           'Apps installed just for your account. Replaceable if you can download them again.'),
    '/Users/Shared': Rule(LV_REVIEW, 'Shared folder',
                          'Files shared between user accounts. Some apps also store shared data '
                          'or licenses here, so check what a folder belongs to first.'),
    '/Library': Rule(LV_CAUTION, 'System-wide app support',
                     'Shared files that installed apps, drivers and fonts rely on.',
                     ["Uninstall the app that owns a folder rather than deleting the folder."]),
    '/Library/Caches': Rule(LV_SAFE, 'System-wide caches',
                            'Caches shared by all users. They are rebuilt when needed.',
                            ['Safe to clear (needs an admin password). Expect some slower first launches.'], strong=True),
    '/Library/Logs': Rule(LV_SAFE, 'System-wide logs',
                          'Diagnostic logs. Only useful when troubleshooting.',
                          ['Safe to delete (needs an admin password).'], strong=True),
    '/Library/Developer/CommandLineTools': Rule(LV_CAUTION, 'Xcode Command Line Tools',
                                                'Provides git, compilers and make. Homebrew and most developer tools need it.',
                                                ['Keep it if you develop on this Mac. It can be reinstalled with `xcode-select --install`.'], strong=True),
    '/Library/Developer/CoreSimulator': Rule(LV_REVIEW, 'Simulator runtimes (iOS, watchOS, tvOS)',
                                             'Each runtime is several GB. You only need the OS versions you actually test against.',
                                             ["Xcode's Settings has a Platforms (or Components) tab where runtimes can be deleted.",
                                              '`xcrun simctl runtime list` and `xcrun simctl runtime delete <id>` do the same in Terminal.'], strong=True),
    '/Library/Audio/Apple Loops': _GARAGEBAND,
    '/Library/Application Support/GarageBand': _GARAGEBAND,
    '/Library/Application Support/Logic': _GARAGEBAND,
    # ---- home folder: personal files ----
    '~': Rule(LV_REVIEW, 'Your files',
              'This is in your home folder, with no more specific rule. Treat it as personal '
              'data: how important it is depends on what it is and whether you have another copy.',
              ['Check that anything you cannot recreate is backed up before deleting it.']),
    '~/.Trash': Rule(LV_SAFE, 'Trash',
                     'Already thrown away, but it keeps using space until the Trash is emptied.',
                     ['Finder > Empty Trash.'], strong=True),
    '~/Downloads': Rule(LV_REVIEW, 'Downloads',
                        'Usually the easiest place to recover space: installers, archives and '
                        'files you have already used or saved elsewhere. Skim before deleting, '
                        'because some things only exist here.',
                        ['Sort by size or date. Old .dmg, .pkg and .zip files are the typical safe wins.']),
    '~/Desktop': Rule(LV_REVIEW, 'Desktop files',
                      'Personal files, often one of a kind. Importance depends on the content '
                      'and on whether you have a backup or synced copy.'),
    '~/Documents': Rule(LV_REVIEW, 'Documents',
                        'Personal files, often one of a kind. Importance depends on the content '
                        'and on whether you have a backup or synced copy.'),
    '~/Pictures': Rule(LV_REVIEW, 'Pictures',
                       'Photos are usually irreplaceable unless they are backed up or in a cloud library.',
                       ['Make sure a backup exists before deleting originals.']),
    '~/Movies': Rule(LV_REVIEW, 'Movies and video projects',
                     'Often the largest personal files. Camera originals and finished exports are '
                     'irreplaceable unless backed up. Render caches, proxies and screen recordings usually are not.',
                     ['Moving finished projects and raw footage to external or network storage frees the most space.']),
    '~/Music': Rule(LV_REVIEW, 'Music and audio projects',
                    'Purchased or streamed music can be downloaded again. Your own recordings and projects cannot.'),
    # ---- home folder: Library ----
    '~/Library': Rule(LV_CAUTION, 'App data and settings',
                      'Apps keep settings, databases and offline data here. Removing a folder '
                      'resets that app or loses its data.',
                      ['Free space from inside the app when you can.',
                       "If the app is long gone, its leftover folder is usually safe to remove."]),
    '~/Library/Caches': Rule(LV_SAFE, 'App caches',
                             'Apps rebuild caches when they need them. Clearing costs some '
                             're-downloading and slower first launches, not data.',
                             ["Quit the app first, then delete that app's folder inside Caches.",
                              'Some caches are large on purpose (downloaded browsers for test tools, package downloads) and will simply download again.'], strong=True),
    '~/Library/Caches/Homebrew': Rule(LV_SAFE, 'Homebrew download cache',
                                      'Downloaded packages kept in case you reinstall.',
                                      ['`brew cleanup -s` clears it.'], strong=True),
    '~/Library/Caches/ms-playwright': Rule(LV_SAFE, 'Playwright browsers',
                                           'Browser builds downloaded by Playwright for automated testing.',
                                           ['Safe to delete. `npx playwright install` downloads them again when a project needs them.'], strong=True),
    '~/Library/Logs': Rule(LV_SAFE, 'App logs',
                           'Diagnostic logs. Only useful when troubleshooting a specific problem.',
                           ['Safe to delete.'], strong=True),
    '~/Library/Saved Application State': Rule(LV_SAFE, 'Saved window state',
                                              'Lets apps reopen their windows after a restart. Small.',
                                              ['Safe to delete; apps just open fresh once.'], strong=True),
    '~/Library/Application Support': Rule(LV_CAUTION, 'App data',
                                          'Each folder belongs to one app and holds its data: projects, databases, '
                                          'downloaded content, sometimes caches.',
                                          ["Look for folders of apps you have uninstalled; those leftovers are usually safe to remove.",
                                           'For apps you use, free space from inside the app.']),
    '~/Library/Application Support/MobileSync': Rule(LV_CAUTION, 'iPhone and iPad backups',
                                                     'Device backups made through Finder. Each can be tens of GB. If one is the '
                                                     'only backup of a device, it is irreplaceable.',
                                                     ['Delete old backups through Finder: select the device, then Manage Backups.',
                                                      'Check the device also backs up to iCloud before removing its last local backup.'], strong=True),
    '~/Library/Application Support/Google/Chrome': _BROWSER,
    '~/Library/Application Support/Firefox': _BROWSER,
    '~/Library/Application Support/BraveSoftware': _BROWSER,
    '~/Library/Application Support/Microsoft Edge': _BROWSER,
    '~/Library/Application Support/Arc': _BROWSER,
    '~/Library/Safari': _BROWSER,
    '~/Library/Containers': Rule(LV_CAUTION, 'Sandboxed app data',
                                 "Each folder is one app's private data: documents, databases and caches. "
                                 'Deleting a folder resets that app.',
                                 ['Free space from inside the app (clear downloads or offline content).',
                                  'Folders of apps you have uninstalled are usually safe to remove.']),
    '~/Library/Group Containers': Rule(LV_CAUTION, 'Shared app data',
                                       'Data shared between an app and its extensions. Office, messaging and '
                                       'note-taking apps keep real content here.',
                                       ['Free space from inside the app.']),
    '~/Library/Containers/com.docker.docker': Rule(LV_CAUTION, 'Docker Desktop data',
                                                   "Holds Docker's virtual disk (Docker.raw) with every image, container and "
                                                   'volume. Deleting the file wipes all of them.',
                                                   ['`docker system df` shows what is using the space.',
                                                    '`docker system prune` removes stopped containers and dangling images. Adding `-a` removes all unused images; adding `--volumes` also deletes unused volumes and their data.',
                                                    "Docker Desktop's Resources settings let you lower the disk image size limit."], strong=True),
    '~/Library/Mail': Rule(LV_CAUTION, 'Mail (downloaded messages and attachments)',
                           'Local copies of your mailboxes. Removing files here by hand can corrupt them.',
                           ['Delete large messages or attachments inside Mail instead.'], strong=True),
    '~/Library/Messages': Rule(LV_CAUTION, 'Messages history and attachments',
                               'Your iMessage and SMS history, including every photo and video sent or received.',
                               ['System Settings > General > Storage > Messages lists large attachments you can delete.',
                                "Messages' settings can limit how long history is kept."], strong=True),
    '~/Library/Mobile Documents': Rule(LV_CAUTION, 'iCloud Drive (local copies)',
                                       'These files sync with iCloud. Deleting one here deletes it from iCloud and '
                                       'from your other devices too.',
                                       ['To free space but keep the file in iCloud, right-click it in Finder and choose Remove Download.'], strong=True),
    '~/Library/CloudStorage': Rule(LV_CAUTION, 'Cloud storage (Dropbox, Google Drive, OneDrive and similar)',
                                   'These files sync with a cloud service. Deleting one here normally deletes '
                                   'it from the cloud and your other devices.',
                                   ["Use the service's online-only or free-up-space option instead of deleting."], strong=True),
    '~/Library/Keychains': Rule(LV_KEEP, 'Keychains (saved passwords and certificates)',
                                'Deleting these loses saved passwords, keys and certificates.', strong=True),
    '~/Library/Preferences': Rule(LV_CAUTION, 'App settings',
                                  'Small settings files. Deleting one resets that app to defaults.'),
    '~/Library/Developer': Rule(LV_CAUTION, 'Xcode and developer data',
                                'Build output, simulators and device support files. Several parts are safe to clear; zoom in.'),
    '~/Library/Developer/Xcode/DerivedData': Rule(LV_SAFE, 'Xcode DerivedData (build output and indexes)',
                                                  'Xcode recreates this on the next build. The cost is one slow rebuild per project.',
                                                  ['Quit Xcode, then delete the contents.'], strong=True),
    '~/Library/Developer/Xcode/Archives': Rule(LV_REVIEW, 'Xcode archives',
                                               'Builds you archived for distribution, with the debug symbols needed to read '
                                               'crash reports from shipped versions. Archives of versions nobody runs any more can go.',
                                               ["Manage them in Xcode's Organizer window (Archives)."]),
    '~/Library/Developer/Xcode/iOS DeviceSupport': _DEVICE_SUPPORT,
    '~/Library/Developer/Xcode/watchOS DeviceSupport': _DEVICE_SUPPORT,
    '~/Library/Developer/Xcode/tvOS DeviceSupport': _DEVICE_SUPPORT,
    '~/Library/Developer/Xcode/visionOS DeviceSupport': _DEVICE_SUPPORT,
    '~/Library/Developer/CoreSimulator/Devices': Rule(LV_REVIEW, 'Simulator devices and their data',
                                                      'Each simulated device has its own disk with installed apps and data.',
                                                      ['`xcrun simctl delete unavailable` removes simulators whose runtime is gone.',
                                                       '`xcrun simctl erase all` wipes the data in every simulator but keeps the devices.'], strong=True),
    '~/Library/Developer/CoreSimulator/Caches': Rule(LV_SAFE, 'Simulator caches',
                                                     'Rebuilt by the simulator when needed.', ['Safe to delete with Simulator closed.'], strong=True),
    '~/Library/Android/sdk': Rule(LV_REVIEW, 'Android SDK',
                                  'System images and old platform versions are the bulky parts, and they can be downloaded again.',
                                  ["Use Android Studio's SDK Manager to remove system images and platforms you do not use."], strong=True),
    '~/.android/avd': Rule(LV_REVIEW, 'Android emulator devices',
                           'Each virtual device holds its own disk image, often several GB.',
                           ["Delete unused ones in Android Studio's Device Manager."], strong=True),
    '~/Library/pnpm': Rule(LV_SAFE, 'pnpm package store',
                           'Shared store of downloaded packages. Projects link to it, so prune it rather than deleting it outright.',
                           ['`pnpm store prune` removes packages no project uses.'], strong=True),
    # ---- home folder: developer tools ----
    '~/.npm': Rule(LV_SAFE, 'npm cache',
                   'Downloaded packages kept to speed up installs. npm refills it as needed.',
                   ['`npm cache clean --force`, or delete the folder.'], strong=True),
    '~/.cache': Rule(LV_SAFE, 'Tool caches',
                     'Command-line tools keep downloads and caches here that they can recreate.',
                     ['Generally safe to delete; tools download again what they need.',
                      'Look before clearing very large folders: some hold big downloads that are slow to fetch again.'], strong=True),
    '~/.cache/huggingface': Rule(LV_REVIEW, 'Hugging Face downloads (models and datasets)',
                                 'AI models and datasets, often many GB each. They can be downloaded again, but that can be slow.',
                                 ['The Hugging Face command-line tool has a cache command for picking what to remove.'], strong=True),
    '~/.gradle/caches': Rule(LV_SAFE, 'Gradle caches',
                             'Downloaded dependencies and build cache. The next build downloads what it needs.',
                             ['Stop Gradle first (`./gradlew --stop`), then delete.'], strong=True),
    '~/.gradle/wrapper': Rule(LV_SAFE, 'Gradle wrapper downloads',
                              'Gradle versions downloaded by projects. Each is re-downloaded on demand.',
                              ['Safe to delete old versions.'], strong=True),
    '~/.m2/repository': Rule(LV_SAFE, 'Maven dependency cache',
                             'Downloaded libraries. Maven fetches them again when a build needs them.',
                             ['Safe to delete.'], strong=True),
    '~/.cargo/registry': Rule(LV_SAFE, 'Cargo registry cache',
                              'Downloaded Rust crates. Cargo fetches them again when needed.', ['Safe to delete.'], strong=True),
    '~/.cargo/git': Rule(LV_SAFE, 'Cargo git cache',
                         'Git checkouts of Rust dependencies. Fetched again when needed.', ['Safe to delete.'], strong=True),
    '~/.rustup': Rule(LV_CAUTION, 'Rust toolchains',
                      'Installed Rust compilers. Each toolchain is roughly a GB or more.',
                      ['`rustup toolchain list`, then `rustup toolchain uninstall <name>` for ones you do not use.'], strong=True),
    '~/.ollama/models': Rule(LV_REVIEW, 'Ollama models',
                             'Local AI model files, usually several GB each. They can be downloaded again.',
                             ['`ollama list` shows models and sizes.', '`ollama rm <model>` removes one.'], strong=True),
    '~/.bun/install/cache': Rule(LV_SAFE, 'Bun package cache',
                                 'Downloaded packages. Bun refills it as needed.', ['`bun pm cache rm`, or delete the folder.'], strong=True),
    '~/.vscode/extensions': Rule(LV_REVIEW, 'VS Code extensions',
                                 'Installed editor extensions. They can be reinstalled from the marketplace.',
                                 ["Uninstall unused ones from VS Code's Extensions view."]),
    '~/.cocoapods': Rule(LV_SAFE, 'CocoaPods cache', 'Downloaded pod specs and sources. Fetched again when needed.', ['Safe to delete.'], strong=True),
    '~/.pub-cache': Rule(LV_SAFE, 'Dart / Flutter package cache', 'Downloaded packages. Fetched again when needed.', ['Safe to delete.'], strong=True),
    '~/go/pkg/mod': Rule(LV_SAFE, 'Go module cache', 'Downloaded Go modules. Fetched again when needed.', ['`go clean -modcache`.'], strong=True),
    '~/.yarn/cache': Rule(LV_SAFE, 'Yarn cache', 'Downloaded packages. Fetched again when needed.', ['`yarn cache clean`.'], strong=True),
    '~/.nuget/packages': Rule(LV_SAFE, 'NuGet package cache', 'Downloaded packages. Restored again when needed.', ['Safe to delete.'], strong=True),
    '~/.terraform.d/plugin-cache': Rule(LV_SAFE, 'Terraform plugin cache', 'Downloaded providers. Fetched again by `terraform init`.', ['Safe to delete.'], strong=True),
    '~/.pyenv/versions': _LANG_VERSIONS, '~/.nvm/versions': _LANG_VERSIONS, '~/.conda': _LANG_VERSIONS,
    '~/miniconda3': _LANG_VERSIONS, '~/anaconda3': _LANG_VERSIONS, '~/miniforge3': _LANG_VERSIONS,
    '~/.local/share/uv': _LANG_VERSIONS, '~/.rustup/toolchains': _LANG_VERSIONS, '~/.volta': _LANG_VERSIONS,
    '~/.sdkman': _LANG_VERSIONS,
    '~/.claude-worktrees': Rule(LV_REVIEW, 'Git worktrees (Claude Code, going by the folder name)',
                                'Each folder looks like a separate checked-out copy of a repository. '
                                'A worktree can hold work that was never committed or merged.',
                                ['In the main repository run `git worktree list`, then `git worktree remove <path>` for the ones you are done with.',
                                 'Check `git status` inside a worktree before removing it.']),
    '~/.ssh': _CRED, '~/.gnupg': _CRED, '~/.aws': _CRED, '~/.kube': _CRED,
}

_DOT_RULE = Rule(LV_CAUTION, 'Hidden tool folder',
                 'Settings, history or data for a command-line or developer tool. Tools often '
                 'keep both irreplaceable settings and re-creatable caches in the same folder.',
                 ['Zoom in: folders named cache, logs or tmp inside are usually safe to clear.',
                  "If you no longer use the tool, the whole folder can usually go."])

_APP_CACHE = Rule(LV_SAFE, 'App cache folder',
                  'A cache inside an app\'s data folder. The app rebuilds it when needed.',
                  ['Quit the app first, then delete the contents.'], strong=True, cond=_in_library_or_hidden)

_PY_CACHE = Rule(LV_SAFE, 'Python cache',
                 'Generated by Python tools and recreated automatically.', ['Safe to delete.'], strong=True)

_FW_BUILD = Rule(LV_SAFE, 'Framework build cache',
                 'Generated by a web framework or build tool. Recreated the next time you build or run the project.',
                 ['Safe to delete when the dev server is not running.'], strong=True)

_BUILD_OUT = Rule(LV_SAFE, 'Build output (likely)',
                  'Looks like generated output for the project next to it, so it can probably be '
                  'rebuilt. Check that it does not hold the only copy of something you shipped.',
                  ['Delete it, or use the project\'s clean command.'], strong=True, cond=_has_sibling(*_BUILD_MARKERS))

_RENDER_CACHE = Rule(LV_SAFE, 'Video render cache or generated media (likely)',
                     'The folder name matches what video editors such as DaVinci Resolve use for render '
                     'cache, proxy or optimized media. These are generated from your source footage and '
                     'can be rebuilt, at the cost of render time.',
                     ['In DaVinci Resolve, Playback > Delete Render Cache removes cache safely.',
                      'Make sure the folder holds only generated files, not your originals.'], strong=True)

_VOL_BOOKKEEPING = Rule(LV_KEEP, 'macOS volume bookkeeping',
                        'Index or journal data that macOS maintains for this volume.', strong=True)

# -- rules by folder name, anywhere --
NAME_RULES = {
    'node_modules': Rule(LV_SAFE, 'node_modules (installed JavaScript packages)',
                         "Fully re-creatable from the project's package.json and lockfile.",
                         ["Restore later with the project's install command (npm, pnpm, yarn or bun install).",
                          'Old projects you are not working on are the best candidates.'], strong=True),
    '.git': Rule(LV_CAUTION, 'Git repository history',
                 'Everything committed in this repository. If it is fully pushed to a remote you '
                 'could clone it again; anything unpushed (commits, branches, stashes) exists only here.',
                 ['`git gc --prune=now` can shrink it without losing history.',
                  'Before deleting a repository, check `git status` and `git log --branches --not --remotes`.'], strong=True),
    '.venv': Rule(LV_SAFE, 'Python virtual environment',
                  "Installed Python packages for one project. Re-creatable from the project's requirements or lockfile.",
                  ['Delete it and recreate with your usual tool (uv, pip, poetry) when you return to the project.'], strong=True, cond=_is_venv),
    'venv': Rule(LV_SAFE, 'Python virtual environment',
                 "Installed Python packages for one project. Re-creatable from the project's requirements or lockfile.",
                 ['Delete it and recreate with your usual tool (uv, pip, poetry) when you return to the project.'], strong=True, cond=_is_venv),
    '__pycache__': _PY_CACHE, '.pytest_cache': _PY_CACHE, '.mypy_cache': _PY_CACHE,
    '.ruff_cache': _PY_CACHE, '.tox': _PY_CACHE, '.nox': _PY_CACHE, '.ipynb_checkpoints': _PY_CACHE,
    '.next': _FW_BUILD, '.nuxt': _FW_BUILD, '.turbo': _FW_BUILD, '.parcel-cache': _FW_BUILD,
    '.svelte-kit': _FW_BUILD, '.angular': _FW_BUILD, '.vite': _FW_BUILD, '.astro': _FW_BUILD,
    '.expo': _FW_BUILD, '.docusaurus': _FW_BUILD, '.wrangler': _FW_BUILD, '.dart_tool': _FW_BUILD,
    'DerivedData': Rule(LV_SAFE, 'Xcode build output', 'Xcode recreates this on the next build.', ['Safe to delete with Xcode closed.'], strong=True),
    'Pods': Rule(LV_SAFE, 'CocoaPods dependencies', 'Downloaded libraries for an Xcode project.',
                 ['`pod install` restores them.'], strong=True, cond=_has_sibling('Podfile')),
    '.gradle': Rule(LV_SAFE, 'Gradle project cache', 'Per-project Gradle cache. Recreated on the next build.',
                    ['Safe to delete.'], strong=True, cond=_not_home_top),
    '.terraform': Rule(LV_SAFE, 'Terraform providers and modules', 'Downloaded by `terraform init`.',
                       ['Safe to delete; run `terraform init` again when needed.'], strong=True),
    'target': Rule(LV_SAFE, 'Build output (Rust or Maven)',
                   'Compiled output for the project next to it. Rebuilt on the next build.',
                   ['`cargo clean` (Rust) or `mvn clean` (Maven), or delete the folder.'], strong=True,
                   cond=_has_sibling('Cargo.toml', 'pom.xml')),
    'build': _BUILD_OUT, 'dist': _BUILD_OUT, 'out': _BUILD_OUT,
    'Cache': _APP_CACHE, 'Caches': _APP_CACHE, 'cache': _APP_CACHE, 'Code Cache': _APP_CACHE,
    'GPUCache': _APP_CACHE, 'CachedData': _APP_CACHE, 'CacheStorage': _APP_CACHE,
    'ShaderCache': _APP_CACHE, 'GrShaderCache': _APP_CACHE, 'DawnCache': _APP_CACHE,
    'CacheClip': _RENDER_CACHE, 'ProxyMedia': _RENDER_CACHE, 'OptimizedMedia': _RENDER_CACHE,
    '.Trashes': Rule(LV_SAFE, 'Trash on this volume', 'Deleted files waiting for the Trash to be emptied.',
                     ['Finder > Empty Trash while the volume is connected.'], strong=True),
    '.Spotlight-V100': _VOL_BOOKKEEPING, '.fseventsd': _VOL_BOOKKEEPING,
    '.DocumentRevisions-V100': _VOL_BOOKKEEPING, '.TemporaryItems': _VOL_BOOKKEEPING,
    'Backups.backupdb': Rule(LV_CAUTION, 'Time Machine backups',
                             'Your backup history. Deleting it by hand can damage the backup set.',
                             ['Remove old backups through Time Machine instead.'], strong=True),
}

_APP_LIBRARY = Rule(LV_CAUTION, 'App library or project package',
                    'A library or project stored as one package. It looks like a single file in Finder but holds '
                    'many pieces that depend on each other.',
                    ['Manage the contents from inside the app. Never delete pieces from inside the package.',
                     'The whole package can be moved to external storage and opened from there.'], strong=True)

_VM = Rule(LV_CAUTION, 'Virtual machine',
           'An entire virtual computer, including everything stored inside it.',
           ['If you still use the VM, free space from inside it, then compact the disk in the VM app.',
            'If not, deleting the whole VM frees all of it.'], strong=True)

# -- rules for folders that macOS shows as a single item (packages), by extension --
PKG_RULES = {
    '.app': Rule(LV_REVIEW, 'Application',
                 'Replaceable if you can download it again from the App Store or the vendor. '
                 'For paid apps, check you still have the license or installer first.',
                 ["Deleting the app leaves its data in your Library, usually small.",
                  'Treat the app as one unit; do not delete pieces from inside it.'], strong=True),
    '.photoslibrary': Rule(LV_CAUTION, 'Photos library',
                           'Your photo collection in a single package. Deleting pieces from inside it corrupts the library.',
                           ['Delete photos inside the Photos app, then empty Recently Deleted.',
                            'With iCloud Photos on, the Optimize Mac Storage setting in Photos keeps smaller versions locally.',
                            'The whole library can be moved to an external drive.'], strong=True),
    '.fcpbundle': _APP_LIBRARY, '.imovielibrary': _APP_LIBRARY, '.tvlibrary': _APP_LIBRARY,
    '.musiclibrary': _APP_LIBRARY, '.logicx': _APP_LIBRARY, '.band': _APP_LIBRARY,
    '.aplibrary': _APP_LIBRARY, '.lrdata': _APP_LIBRARY, '.theater': _APP_LIBRARY,
    '.xcarchive': Rule(LV_REVIEW, 'Xcode archive',
                       'An archived build with debug symbols. Needed to read crash reports for that released version.',
                       ['Archives of versions nobody runs any more can be deleted.'], strong=True),
    '.vmwarevm': _VM, '.pvm': _VM, '.utm': _VM, '.parallels': _VM,
    '.sparsebundle': Rule(LV_CAUTION, 'Disk image bundle',
                          'A growable disk image. It may be a backup or an encrypted store of files.',
                          ['Mount it and check what is inside before deciding.'], strong=True),
    '.backupbundle': Rule(LV_CAUTION, 'Time Machine backup bundle',
                          'A Time Machine backup set.', ['Remove old backups through Time Machine instead.'], strong=True),
    '.mlpackage': Rule(LV_REVIEW, 'AI model package',
                       'A machine learning model. Downloaded models can be fetched again; ones you trained yourself cannot.', strong=True),
}

_INSTALLER = Rule(LV_SAFE, 'Installer or disk image',
                  'Once the software is installed, the installer is no longer needed and can normally be '
                  'downloaded again. Exception: installers for paid or discontinued software you could not get again.',
                  ['Check the app is installed and working, then delete.'])
_ARCHIVE = Rule(LV_REVIEW, 'Archive',
                'If you have already extracted it, the contents probably exist twice. If the archive is '
                'itself a backup or export, it may be the only copy.',
                ['Check whether an extracted folder with the same name sits next to it.'])
_VIDEO = Rule(LV_REVIEW, 'Video',
              'Large by nature. Camera originals and finished exports are irreplaceable unless backed up; '
              'screen recordings and downloaded videos usually are not.',
              ['Move footage you want to keep to external or network storage.'])
_AUDIO = Rule(LV_REVIEW, 'Audio',
              'Your own recordings are irreplaceable unless backed up; purchased or downloaded audio usually is not.')
_IMAGE = Rule(LV_REVIEW, 'Image',
              'Photos you took are irreplaceable unless backed up or in a cloud library. Screenshots and '
              'downloaded images usually matter less.')
_VDISK = Rule(LV_CAUTION, 'Virtual disk',
              'The disk of a virtual machine or container system. It holds everything stored inside that system.',
              ['Free space from inside the VM or tool that owns it rather than deleting the file.'])
_MODEL = Rule(LV_REVIEW, 'AI model weights',
              'Usually downloaded, and downloadable again (if slowly). Checkpoints you trained or fine-tuned yourself are not replaceable.',
              ['If a tool such as Ollama or LM Studio manages this file, remove it through that tool.'])
_LOG = Rule(LV_SAFE, 'Log file', 'Diagnostic output. Only useful for troubleshooting.',
            ['Safe to delete. If the app is running it may simply create a new one.'])
_DB = Rule(LV_CAUTION, 'App database', "Holds an app's data. Deleting it loses that data or resets the app.",
           ['Free space from inside the app that owns it.'])

# -- rules for plain files, by extension --
EXT_RULES = {}
for _e in ('.dmg', '.pkg', '.mpkg', '.xip'):
    EXT_RULES[_e] = _INSTALLER
EXT_RULES['.ipsw'] = Rule(LV_SAFE, 'Device firmware image',
                          'A downloaded iOS, iPadOS or macOS restore image. Apple serves it again when needed.',
                          ['Safe to delete.'])
EXT_RULES['.iso'] = Rule(LV_REVIEW, 'Disk image (ISO)',
                         'Usually an operating system installer or a disc copy. OS installers can be downloaded again; disc copies you made may be one of a kind.')
for _e in ('.zip', '.tar', '.gz', '.tgz', '.bz2', '.xz', '.7z', '.rar', '.zst'):
    EXT_RULES[_e] = _ARCHIVE
for _e in ('.mov', '.mp4', '.m4v', '.mkv', '.avi', '.mxf', '.braw', '.r3d', '.mts', '.webm', '.wmv'):
    EXT_RULES[_e] = _VIDEO
for _e in ('.wav', '.aiff', '.aif', '.flac', '.mp3', '.m4a', '.aac'):
    EXT_RULES[_e] = _AUDIO
for _e in ('.jpg', '.jpeg', '.png', '.heic', '.tif', '.tiff', '.psd', '.psb', '.cr2', '.cr3',
           '.nef', '.arw', '.dng', '.raf', '.orf', '.rw2', '.gif', '.webp'):
    EXT_RULES[_e] = _IMAGE
for _e in ('.vmdk', '.vdi', '.qcow2', '.vhd', '.vhdx', '.hdd'):
    EXT_RULES[_e] = _VDISK
for _e in ('.gguf', '.safetensors', '.ckpt', '.pt', '.pth', '.onnx', '.mlmodel'):
    EXT_RULES[_e] = _MODEL
EXT_RULES['.log'] = _LOG
for _e in ('.sqlite', '.sqlite3', '.db', '.sqlite-wal', '.db-wal'):
    EXT_RULES[_e] = _DB

FILE_RULES = {
    'sleepimage': Rule(LV_KEEP, 'Sleep image', 'macOS writes memory here when the Mac sleeps deeply. Managed by macOS.', strong=True),
    'Docker.raw': Rule(LV_CAUTION, 'Docker virtual disk',
                       'Holds every Docker image, container and volume. Deleting the file wipes all of them.',
                       ['`docker system df` shows what is using the space.',
                        '`docker system prune` removes stopped containers and dangling images. Adding `-a` removes all unused images; adding `--volumes` also deletes unused volumes and their data.',
                        "Docker Desktop's Resources settings let you lower the disk image size limit."]),
    '.DS_Store': Rule(LV_SAFE, 'Finder view settings', 'Remembers how Finder displays this folder. Tiny, and recreated automatically.'),
}
_SWAP = Rule(LV_KEEP, 'Swap file', 'Virtual memory in use by macOS. Managed by macOS; a restart clears it.', strong=True)

_DEFAULT_UNKNOWN = Rule(LV_UNKNOWN, 'Not recognized',
                        'No specific knowledge about this location. Judge it by what is inside, what created it and when it last changed.',
                        ['If you cannot tell what it belongs to, leave it.'])

_SYSTEM_PREFIXES = ('/System/', '/usr/', '/bin/', '/sbin/', '/private/')

_HOME_RE = re.compile(r'^/(?:Users|home)/([^/]+)(?=/|$)')


def norm_path(p):
    """Location-independent form of a path: the user's home becomes '~'."""
    if p.startswith('/System/Volumes/Data/'):
        p = p[20:]
    m = _HOME_RE.match(p)
    if m:
        if m.group(1) not in ('Shared', 'Guest'):
            p = '~' + p[m.end():]
    elif p == '/root' or p.startswith('/root/'):
        p = '~' + p[5:]
    return p


_rule_cache = {}
_STRICTNESS = {LV_SAFE: 0, LV_REVIEW: 1, LV_CAUTION: 2, LV_KEEP: 3}


def _governing_ancestor(np, real, system):
    """Nearest strong path or package rule above np, as (rule, real_path), or None."""
    while np not in ('/', '~', '') and '/' in np:
        np = np.rsplit('/', 1)[0] or '/'
        real = os.path.dirname(real) or '/'
        r = PATH_RULES.get(np)
        if r is None and not system:
            base = np.rsplit('/', 1)[-1]
            dot = base.rfind('.')
            if dot > 0:
                r = PKG_RULES.get(base[dot:].lower())
        if r is not None and r.strong and r.lv in _STRICTNESS:
            return r, real
    return None


def _dir_rule(path):
    """(rule, anchor_path, direct) for a directory."""
    hit = _rule_cache.get(path)
    if hit is not None:
        return hit
    np = norm_path(path)
    system = np.startswith(_SYSTEM_PREFIXES) or np == '/System'
    cur_np, cur_real, first = np, path, True
    res = None
    while True:
        r = None
        by_name = False
        if first:
            r = SELF_RULES.get(cur_np)
        if r is None:
            r = PATH_RULES.get(cur_np)
        if r is None and not system:
            by_name = True
            base = cur_np.rsplit('/', 1)[-1]
            r = NAME_RULES.get(base)
            if r is not None and r.cond is not None and not r.cond(cur_np, cur_real):
                r = None
            if r is None:
                dot = base.rfind('.')
                if dot > 0:
                    r = PKG_RULES.get(base[dot:].lower())
            if r is None and cur_np.startswith('~/.') and cur_np.count('/') == 1:
                r = _DOT_RULE
        if r is not None:
            res = (r, cur_real, first)
            if by_name:
                # A name or package match is a guess from the folder name alone. It must not
                # loosen a strong rule above it (node_modules inside an app, a "Cache" folder in
                # iCloud Drive), and inside a strong safe area such as Caches the area's rule is
                # the better description than a package type.
                anc = _governing_ancestor(cur_np, cur_real, system)
                if anc is not None and r.lv in _STRICTNESS and (
                        _STRICTNESS[anc[0].lv] > _STRICTNESS[r.lv]
                        or (anc[0].lv == LV_SAFE and r in PKG_RULES.values())):
                    res = (anc[0], anc[1], False)
            break
        if cur_np in ('/', '~', '') or '/' not in cur_np:
            break
        cur_np = cur_np.rsplit('/', 1)[0] or '/'
        cur_real = os.path.dirname(cur_real) or '/'
        first = False
    if res is None:
        res = (_DEFAULT_UNKNOWN, path, True)
    if len(_rule_cache) > 300000:
        _rule_cache.clear()
    _rule_cache[path] = res
    return res


def find_rule(path, is_dir):
    """(rule, anchor_path, direct). 'direct' is False when the rule comes from a containing folder."""
    if is_dir:
        return _dir_rule(path)
    parent = os.path.dirname(path) or '/'
    base = os.path.basename(path)
    crule, canchor, _ = _dir_rule(parent)
    if crule.lv == LV_MIXED:   # a container's self-description does not apply to files in it
        np = norm_path(parent)
        crule = PATH_RULES.get(np)
        canchor = parent
        if crule is None and (np == '~' or np.startswith('~/')):
            crule = PATH_RULES['~']
    if crule is not None and crule.strong:
        return (crule, canchor, False)
    frule = FILE_RULES.get(base)
    if frule is None and base.startswith('swapfile'):
        frule = _SWAP
    if frule is None:
        dot = base.rfind('.')
        if dot > 0:
            frule = EXT_RULES.get(base[dot:].lower())
    if frule is not None:
        return (frule, path, True)
    if crule is not None and crule is not _DEFAULT_UNKNOWN:
        return (crule, canchor, False)
    return (_DEFAULT_UNKNOWN, path, True)


def level_of(path, is_dir):
    return find_rule(path, is_dir)[0].lv


_KIND_BY_EXT = {}
for _exts, _label in (
        (('.dmg', '.pkg', '.mpkg', '.xip', '.iso', '.ipsw'), 'Installer or disk image'),
        (('.zip', '.tar', '.gz', '.tgz', '.bz2', '.xz', '.7z', '.rar', '.zst'), 'Archive'),
        (('.mov', '.mp4', '.m4v', '.mkv', '.avi', '.mxf', '.braw', '.r3d', '.mts', '.webm', '.wmv'), 'Video'),
        (('.wav', '.aiff', '.aif', '.flac', '.mp3', '.m4a', '.aac'), 'Audio'),
        (('.jpg', '.jpeg', '.png', '.heic', '.tif', '.tiff', '.psd', '.psb', '.cr2', '.cr3', '.nef',
          '.arw', '.dng', '.raf', '.orf', '.rw2', '.gif', '.webp'), 'Image'),
        (('.vmdk', '.vdi', '.qcow2', '.vhd', '.vhdx', '.hdd', '.raw'), 'Virtual disk'),
        (('.gguf', '.safetensors', '.ckpt', '.pt', '.pth', '.onnx', '.mlmodel'), 'AI model'),
        (('.log',), 'Log file'),
        (('.sqlite', '.sqlite3', '.db'), 'Database'),
        (('.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.key', '.pages', '.numbers',
          '.txt', '.md', '.rtf', '.csv'), 'Document'),
        (('.app',), 'Application'),
        (('.photoslibrary',), 'Photos library'),
):
    for _e in _exts:
        _KIND_BY_EXT[_e] = _label


def kind_label(name, is_dir, is_link=False):
    if is_link:
        return 'Symbolic link'
    dot = name.rfind('.')
    ext = name[dot:].lower() if dot > 0 else ''
    if is_dir:
        if ext in PKG_RULES:
            return _KIND_BY_EXT.get(ext, 'Package')
        return 'Folder'
    lab = _KIND_BY_EXT.get(ext)
    if lab:
        return lab
    if ext and len(ext) <= 8:
        return ext[1:].upper() + ' file'
    return 'File'


def is_package(name):
    dot = name.rfind('.')
    return dot > 0 and name[dot:].lower() in PKG_RULES
