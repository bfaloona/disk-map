"""Advice rules: which level and title each kind of path gets.

All paths are made up and nothing is read from disk: the rules that look for a sibling file
(package.json, Cargo.toml, pyvenv.cfg, Podfile) see a fake file system through a patched
os.path.lexists.
"""
import os
import re
import unittest
from unittest import mock

from loader import diskmap

dm = diskmap()
H = '/Users/tester'


class AdviceCase(unittest.TestCase):
    existing = ()      # paths that the fake file system says exist

    def setUp(self):
        dm._rule_cache.clear()      # condition results are cached by path
        files = set(self.existing)
        p = mock.patch('os.path.lexists', side_effect=lambda q: q in files)
        p.start()
        self.addCleanup(p.stop)

    def rule(self, path, is_dir=True):
        return dm.find_rule(path, is_dir)

    def check(self, path, is_dir, lv, title=None):
        r, _anchor, _direct = self.rule(path, is_dir)
        msg = '%s -> %s %r' % (path, r.lv, r.title)
        self.assertEqual(r.lv, lv, msg)
        if title is not None:
            self.assertIn(title, r.title, msg)


class NormPathTest(unittest.TestCase):
    def test_home_folders_become_tilde(self):
        self.assertEqual(dm.norm_path('/Users/tester'), '~')
        self.assertEqual(dm.norm_path('/Users/tester/Library'), '~/Library')
        self.assertEqual(dm.norm_path('/home/tester/.npm'), '~/.npm')
        self.assertEqual(dm.norm_path('/root/.cache'), '~/.cache')

    def test_data_volume_prefix_is_removed(self):
        self.assertEqual(dm.norm_path('/System/Volumes/Data/Users/tester/Downloads'), '~/Downloads')
        self.assertEqual(dm.norm_path('/System/Volumes/Data/Applications'), '/Applications')

    def test_shared_and_guest_are_not_homes(self):
        self.assertEqual(dm.norm_path('/Users/Shared/x'), '/Users/Shared/x')
        self.assertEqual(dm.norm_path('/Users/Guest'), '/Users/Guest')

    def test_lookalikes_are_not_homes(self):
        self.assertEqual(dm.norm_path('/Users'), '/Users')
        self.assertEqual(dm.norm_path('/rootfs/x'), '/rootfs/x')
        self.assertEqual(dm.norm_path('/Volumes/Ext/Users/tester/x'), '/Volumes/Ext/Users/tester/x')


class LocationRulesTest(AdviceCase):
    def test_containers_describe_themselves(self):
        self.check('/', True, dm.LV_MIXED, 'Startup disk')
        self.check(H, True, dm.LV_MIXED, 'Home folder')
        self.check(H + '/Library', True, dm.LV_MIXED)
        self.check('/Users', True, dm.LV_MIXED)

    def test_mixed_self_rules_are_not_inherited(self):
        # A folder inside ~ gets the "your files" rule, not the home folder's own description.
        self.check(H + '/Projects', True, dm.LV_REVIEW, 'Your files')
        self.check(H + '/Library/SomeApp', True, dm.LV_CAUTION, 'App data and settings')

    def test_system_locations_are_kept(self):
        self.check('/System/Library/Frameworks', True, dm.LV_KEEP, 'macOS')
        self.check('/usr/lib', True, dm.LV_KEEP)
        self.check('/System/Volumes/VM', True, dm.LV_KEEP, 'Virtual memory')
        self.check('/System/Volumes/Data/private/var/vm', True, dm.LV_KEEP, 'Virtual memory')

    def test_safe_locations(self):
        for p in ('/.Trash', '/.npm', '/Library/Caches', '/Library/Caches/com.example.editor',
                  '/Library/Developer/Xcode/DerivedData/App-abc', '/Library/Logs',
                  '/Library/Caches/ms-playwright', '/.cache/pip', '/go/pkg/mod'):
            self.check(H + p, True, dm.LV_SAFE)
        self.check('/cores', True, dm.LV_SAFE, 'Crash dumps')

    def test_careful_and_keep_locations(self):
        self.check(H + '/Library/Mobile Documents/com~apple~CloudDocs', True, dm.LV_CAUTION, 'iCloud')
        self.check(H + '/Library/CloudStorage/Dropbox', True, dm.LV_CAUTION, 'Cloud storage')
        self.check(H + '/Library/Application Support/MobileSync/Backup', True, dm.LV_CAUTION, 'backups')
        self.check(H + '/Library/Keychains', True, dm.LV_KEEP)
        self.check(H + '/.ssh', True, dm.LV_KEEP, 'credentials')
        self.check(H + '/.aws', True, dm.LV_KEEP, 'credentials')
        self.check(H + '/Library/Mail/V10', True, dm.LV_CAUTION, 'Mail')

    def test_closer_rule_wins(self):
        self.check(H + '/.cache/huggingface/hub', True, dm.LV_REVIEW, 'Hugging Face')
        self.check(H + '/Library/Caches/Homebrew/downloads', True, dm.LV_SAFE, 'Homebrew')

    def test_dot_folder_at_home_top_only(self):
        self.check(H + '/.someTool', True, dm.LV_CAUTION, 'Hidden tool folder')
        self.check(H + '/.someTool/data', True, dm.LV_CAUTION, 'Hidden tool folder')

    def test_inherited_rule_reports_its_anchor(self):
        r, anchor, direct = self.rule(H + '/.npm/_cacache/content-v2', True)
        self.assertEqual(anchor, H + '/.npm')
        self.assertFalse(direct)
        r, anchor, direct = self.rule(H + '/.npm', True)
        self.assertTrue(direct)

    def test_unknown_outside_home(self):
        self.check('/srv/data', True, dm.LV_UNKNOWN, 'Not recognized')


class NameRulesTest(AdviceCase):
    existing = (
        H + '/dev/web/package.json',
        H + '/dev/rusty/Cargo.toml',
        H + '/dev/py/.venv/pyvenv.cfg',
        H + '/dev/ios/Podfile',
    )

    def test_name_rules_anywhere_in_home(self):
        self.check(H + '/dev/web/node_modules', True, dm.LV_SAFE, 'node_modules')
        self.check(H + '/dev/web/node_modules/react/index.js', False, dm.LV_SAFE, 'node_modules')
        self.check(H + '/dev/web/.git', True, dm.LV_CAUTION, 'Git')
        self.check(H + '/dev/web/.next', True, dm.LV_SAFE, 'Framework build cache')
        self.check(H + '/dev/py/src/__pycache__', True, dm.LV_SAFE, 'Python cache')

    def test_build_output_needs_a_project_marker(self):
        self.check(H + '/dev/web/dist', True, dm.LV_SAFE, 'Build output')
        self.check(H + '/Documents/dist', True, dm.LV_REVIEW, 'Documents')

    def test_target_needs_cargo_or_maven(self):
        self.check(H + '/dev/rusty/target', True, dm.LV_SAFE, 'Rust or Maven')
        self.check(H + '/dev/web/target', True, dm.LV_REVIEW)

    def test_venv_needs_pyvenv_cfg(self):
        self.check(H + '/dev/py/.venv', True, dm.LV_SAFE, 'virtual environment')
        self.check(H + '/dev/other/venv', True, dm.LV_REVIEW)

    def test_pods_needs_podfile(self):
        self.check(H + '/dev/ios/Pods', True, dm.LV_SAFE, 'CocoaPods')
        self.check(H + '/dev/web/Pods', True, dm.LV_REVIEW)

    def test_gradle_folder_in_project_but_not_home_top(self):
        self.check(H + '/dev/android/.gradle', True, dm.LV_SAFE, 'Gradle project cache')
        self.check(H + '/.gradle', True, dm.LV_CAUTION, 'Hidden tool folder')

    def test_cache_names_only_in_app_data_or_hidden_folders(self):
        self.check(H + '/Library/Application Support/Code/CachedData', True, dm.LV_SAFE, 'App cache')
        self.check(H + '/.config/someapp/cache', True, dm.LV_SAFE, 'App cache')
        self.check(H + '/Documents/cache', True, dm.LV_REVIEW, 'Documents')

    def test_render_cache(self):
        self.check(H + '/Movies/DaVinci/CacheClip', True, dm.LV_SAFE, 'render cache')

    def test_system_paths_skip_name_rules(self):
        # Global npm packages under /usr/local are not "safe to clear" like a project's node_modules.
        self.check('/usr/local/lib/node_modules', True, dm.LV_CAUTION, 'Manually installed tools')
        self.check('/private/var/folders/ab/xyz/T/node_modules', True, dm.LV_CAUTION, 'Temporary files')

    @unittest.expectedFailure
    def test_node_modules_inside_an_app_is_not_safe(self):
        # Electron apps ship their own node_modules; deleting it breaks the app.
        # The nearest rule wins, so the name rule overrides the strong ".app" package rule.
        r, _a, _d = self.rule('/Applications/Some.app/Contents/Resources/app/node_modules', True)
        self.assertNotEqual(r.lv, dm.LV_SAFE)

    @unittest.expectedFailure
    def test_global_homebrew_node_modules_is_not_safe(self):
        # Packages installed with `npm -g` under Homebrew are tools, not a project's re-creatable install.
        r, _a, _d = self.rule('/opt/homebrew/lib/node_modules', True)
        self.assertNotEqual(r.lv, dm.LV_SAFE)

    @unittest.expectedFailure
    def test_cache_named_folder_in_icloud_is_not_safe(self):
        # A user folder called "Cache" in iCloud Drive syncs: deleting it deletes it everywhere.
        r, _a, _d = self.rule(H + '/Library/Mobile Documents/com~apple~CloudDocs/Cache', True)
        self.assertNotEqual(r.lv, dm.LV_SAFE)

    @unittest.expectedFailure
    def test_global_nvm_node_modules_is_not_safe(self):
        # Global packages for one Node version are installed tools, not a project's re-creatable install.
        r, _a, _d = self.rule(H + '/.nvm/versions/node/v20.0.0/lib/node_modules', True)
        self.assertNotEqual(r.lv, dm.LV_SAFE)

    @unittest.expectedFailure
    def test_cache_named_folder_in_messages_is_not_safe(self):
        # ~/Library/Messages is a strong "careful" rule; a cache-named folder inside it outranks it.
        r, _a, _d = self.rule(H + '/Library/Messages/Attachments/Caches', True)
        self.assertNotEqual(r.lv, dm.LV_SAFE)

    @unittest.expectedFailure
    def test_cache_folder_named_like_an_app_is_still_a_cache(self):
        # Bundle-ID folder names can end in ".app"; the package rule then outranks ~/Library/Caches.
        # The error is on the cautious side (Your call instead of Safe to clear).
        self.check(H + '/Library/Caches/com.example.app', True, dm.LV_SAFE, 'App caches')


class PackageAndFileRulesTest(AdviceCase):
    def test_packages(self):
        self.check('/Applications/Some.app', True, dm.LV_REVIEW, 'Application')
        self.check(H + '/Pictures/Photos Library.photoslibrary', True, dm.LV_CAUTION, 'Photos library')
        self.check(H + '/VMs/Win.utm', True, dm.LV_CAUTION, 'Virtual machine')
        self.check(H + '/Music/Song.LOGICX', True, dm.LV_CAUTION)   # extensions ignore case

    def test_files_inside_a_package_follow_the_package(self):
        self.check(H + '/Pictures/Photos Library.photoslibrary/originals/0/a.heic', False,
                   dm.LV_CAUTION, 'Photos library')

    def test_extension_rules(self):
        self.check(H + '/Downloads/Xcode.xip', False, dm.LV_SAFE, 'Installer')
        self.check(H + '/Downloads/Setup.DMG', False, dm.LV_SAFE, 'Installer')
        self.check(H + '/Downloads/export.zip', False, dm.LV_REVIEW, 'Archive')
        self.check(H + '/Movies/a.mov', False, dm.LV_REVIEW, 'Video')
        self.check(H + '/models/w.safetensors', False, dm.LV_REVIEW, 'AI model')
        self.check(H + '/vm/disk.vmdk', False, dm.LV_CAUTION, 'Virtual disk')
        self.check(H + '/app/data.sqlite', False, dm.LV_CAUTION, 'database')

    def test_named_files(self):
        self.check(H + '/Library/Containers/com.docker.docker/Data/vms/0/data/Docker.raw', False,
                   dm.LV_CAUTION, 'Docker')
        self.check('/private/var/vm/sleepimage', False, dm.LV_KEEP)
        self.check('/System/Volumes/VM/swapfile0', False, dm.LV_KEEP)
        self.check(H + '/Documents/.DS_Store', False, dm.LV_SAFE, 'Finder')

    def test_strong_container_beats_file_type(self):
        # An installer in iCloud Drive is not "safe": deleting it deletes it from iCloud too.
        self.check(H + '/Library/Mobile Documents/com~apple~CloudDocs/old.dmg', False, dm.LV_CAUTION, 'iCloud')
        self.check(H + '/Library/Mail/V10/attachment.zip', False, dm.LV_CAUTION, 'Mail')
        # ...and a safe container beats a careful file type.
        self.check(H + '/Library/Caches/com.example/data.sqlite', False, dm.LV_SAFE, 'App caches')

    def test_weak_container_yields_to_file_type(self):
        self.check(H + '/Downloads/old.dmg', False, dm.LV_SAFE, 'Installer')
        self.check(H + '/Library/Application Support/Some/app.log', False, dm.LV_SAFE, 'Log')

    def test_plain_files_in_mixed_containers(self):
        self.check(H + '/notes.txt', False, dm.LV_REVIEW, 'Your files')
        self.check('/stray-file', False, dm.LV_UNKNOWN)
        self.check(H + '/Library/random.plist', False, dm.LV_CAUTION, 'App data and settings')

    def test_dotfiles_and_no_extension(self):
        self.check(H + '/dev/x/.env', False, dm.LV_REVIEW, 'Your files')
        self.check('/srv/README', False, dm.LV_UNKNOWN)


class KindLabelTest(unittest.TestCase):
    def test_labels(self):
        self.assertEqual(dm.kind_label('a.MOV', False), 'Video')
        self.assertEqual(dm.kind_label('x.app', True), 'Application')
        self.assertEqual(dm.kind_label('x.utm', True), 'Package')
        self.assertEqual(dm.kind_label('folder.with.dots', True), 'Folder')
        self.assertEqual(dm.kind_label('a.weird', False), 'WEIRD file')
        self.assertEqual(dm.kind_label('a.waytoolongext', False), 'File')
        self.assertEqual(dm.kind_label('.bashrc', False), 'File')
        self.assertEqual(dm.kind_label('a.mov', False, is_link=True), 'Symbolic link')

    def test_is_package(self):
        self.assertTrue(dm.is_package('Photos Library.photoslibrary'))
        self.assertTrue(dm.is_package('Thing.APP'))
        self.assertFalse(dm.is_package('.app'))
        self.assertFalse(dm.is_package('notes.txt'))


class RuleTableTest(unittest.TestCase):
    """Checks on the rule tables themselves, so a typo cannot silently disable a rule."""

    LEVELS = {dm.LV_SAFE, dm.LV_REVIEW, dm.LV_CAUTION, dm.LV_KEEP, dm.LV_MIXED, dm.LV_UNKNOWN}

    def all_rules(self):
        tables = (dm.SELF_RULES, dm.PATH_RULES, dm.NAME_RULES, dm.PKG_RULES, dm.EXT_RULES, dm.FILE_RULES)
        seen = {}
        for t in tables:
            for r in t.values():
                seen[id(r)] = r
        for r in (dm._SWAP, dm._DEFAULT_UNKNOWN, dm._DOT_RULE):
            seen[id(r)] = r
        return list(seen.values())

    def test_path_keys_are_normalized(self):
        for k in list(dm.PATH_RULES) + list(dm.SELF_RULES):
            self.assertTrue(k == '~' or k.startswith('~/') or k.startswith('/'), k)
            self.assertTrue(k == '/' or not k.endswith('/'), k)
            self.assertNotIn('//', k)
            if k != '/Users/Shared':
                self.assertFalse(k.startswith('/Users/') or k.startswith('/home/'), k)

    def test_name_keys_are_single_names(self):
        for k in dm.NAME_RULES:
            self.assertNotIn('/', k)
        for k in dm.FILE_RULES:
            self.assertNotIn('/', k)

    def test_extension_keys_are_lowercase_with_a_dot(self):
        # Lookups lowercase the extension, so an uppercase key could never match.
        for t in (dm.PKG_RULES, dm.EXT_RULES):
            for k in t:
                self.assertTrue(k.startswith('.') and k == k.lower() and '.' not in k[1:], k)

    def test_every_rule_is_complete(self):
        for r in self.all_rules():
            self.assertIn(r.lv, self.LEVELS, r.title)
            self.assertTrue(r.title.strip(), r)
            self.assertTrue(r.why.strip(), r.title)
            self.assertIsInstance(r.how, tuple)
            for line in r.how:
                self.assertIsInstance(line, str)
                self.assertTrue(line.strip(), r.title)

    def test_wording_rules(self):
        # Interface text: no em dashes, no British spellings that slip in easily.
        british = re.compile(r'\b(colour|behaviour|organis\w+|recognis\w+|licence|catalogue|favourite)\b', re.I)
        for r in self.all_rules():
            for text in (r.title, r.why) + r.how:
                self.assertNotIn('—', text, r.title)
                self.assertIsNone(british.search(text), text)

    def test_level_letters_match_the_interface(self):
        # ui.html colors tiles by these letters; a change here must change there too.
        self.assertEqual((dm.LV_SAFE, dm.LV_REVIEW, dm.LV_CAUTION, dm.LV_KEEP, dm.LV_MIXED, dm.LV_UNKNOWN),
                         ('s', 'r', 'c', 'k', 'm', 'u'))
        from loader import ROOT
        with open(os.path.join(ROOT, 'src', 'ui.html'), encoding='utf-8') as fh:
            self.assertIn("'srck'.indexOf(n.lv)", fh.read())


if __name__ == '__main__':
    unittest.main()
