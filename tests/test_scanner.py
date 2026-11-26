"""Scanner: sizes, hard links, symlinks, permission errors, mount points, cloud-only folders,
pruning, rescans and the scan cache. Every fixture lives in a fresh temp folder.

The mount table is always synthetic (read_mounts is patched), so results do not depend on
the machine running the tests.
"""
import os
import shutil
import stat
import sys
import tempfile
import time
import unittest
from unittest import mock

from loader import diskmap

dm = diskmap()
KB = 1024


def fake_mounts(*extra):
    mounts = {'/': dm.Mount('/', '/dev/disk9s1s1', 'apfs', True, True)}
    for m in extra:
        mounts[m.path] = m
    return mounts


def write(path, size):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as fh:
        fh.write(b'x' * size)


def allocated(root):
    """Independent expected total: allocated bytes of every non-folder, hard links once."""
    total, seen = 0, set()
    for dirpath, dirnames, filenames in os.walk(root):
        for n in filenames + [d for d in dirnames if os.path.islink(os.path.join(dirpath, d))]:
            st = os.lstat(os.path.join(dirpath, n))
            if st.st_nlink > 1 and stat.S_ISREG(st.st_mode):
                if (st.st_dev, st.st_ino) in seen:
                    continue
                seen.add((st.st_dev, st.st_ino))
            total += st.st_blocks * 512
    return total


class Recorder(object):
    """Wraps os functions and records every path they were called with."""

    NAMES = ('scandir', 'lstat', 'stat', 'statvfs', 'listdir')

    def __init__(self, testcase):
        self.paths = []
        for name in self.NAMES:
            real = getattr(os, name)
            p = mock.patch('os.' + name, side_effect=self._wrap(real))
            p.start()
            testcase.addCleanup(p.stop)

    def _wrap(self, real):
        def f(*args, **kw):
            if args:
                self.paths.append(os.fspath(args[0]) if not isinstance(args[0], int) else args[0])
            return real(*args, **kw)
        return f

    def touched(self, path):
        return [p for p in self.paths if isinstance(p, str) and (p == path or p.startswith(path + '/'))]


class FakeEntry(object):
    """A directory entry that counts stat() and is_dir() calls by name, and can report extra
    st_flags (for example SF_DATALESS)."""

    def __init__(self, real, flags, calls):
        self._real = real
        self._flags = flags
        self._calls = calls
        self.name = real.name
        self.path = real.path

    def is_dir(self, follow_symlinks=True):
        self._calls[self.name] = self._calls.get(self.name, 0) + 1
        return self._real.is_dir(follow_symlinks=follow_symlinks)

    def stat(self, follow_symlinks=True):
        self._calls[self.name] = self._calls.get(self.name, 0) + 1
        st = self._real.stat(follow_symlinks=follow_symlinks)
        flags = self._flags

        class St(object):
            def __getattr__(self, k):
                return flags | getattr(st, 'st_flags', 0) if k == 'st_flags' else getattr(st, k)
        return St()


class ScandirSpy(object):
    """Stands in for os.scandir: records listed folders and per-entry stat calls (the scanner
    stats entries through DirEntry.stat, which never calls os.stat or os.lstat)."""

    def __init__(self, flags_by_name=None):
        self.flags = flags_by_name or {}
        self.listed = []
        self.calls = {}
        self.real = os.scandir

    def __call__(self, path):
        spy = self
        spy.listed.append(path)
        it = spy.real(path)

        class Wrapped(object):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                it.close()

            def __iter__(self):
                for e in it:
                    yield FakeEntry(e, spy.flags.get(e.name, 0), spy.calls)
        return Wrapped()


class ScannerCase(unittest.TestCase):
    mounts = ()

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='diskmap-test-')
        self.addCleanup(self._cleanup)
        self.root = os.path.join(self.tmp, 'root')
        os.makedirs(self.root)
        dm._rule_cache.clear()
        for target, value in ((dm, ('read_mounts', lambda: fake_mounts(*self.mounts))),
                              (dm.Scanner, ('_mdls', staticmethod(lambda p: {})))):
            p = mock.patch.object(target, value[0], value[1])
            p.start()
            self.addCleanup(p.stop)

    def _cleanup(self):
        for dirpath, dirnames, _f in os.walk(self.tmp):
            for d in dirnames:
                p = os.path.join(dirpath, d)
                if not os.path.islink(p):
                    os.chmod(p, 0o755)
        shutil.rmtree(self.tmp)

    def scanner(self, cache_dir=None):
        sc = dm.Scanner(2, cache_dir, [self.root])
        self.addCleanup(sc.pool.shutdown, True)
        return sc

    def scan(self, sc=None, path=None):
        sc = sc or self.scanner()
        r = sc.start_scan(path or self.root)
        self.wait(lambda: r.state == 'done')
        return sc, r

    def wait(self, cond, timeout=20):
        end = time.time() + timeout
        while not cond():
            if time.time() > end:
                self.fail('timed out waiting for the scan')
            time.sleep(0.02)


class SizeTest(ScannerCase):
    def test_total_is_allocated_bytes(self):
        write(self.root + '/a/one.bin', 100 * KB)
        write(self.root + '/a/b/two.bin', 3 * KB)
        write(self.root + '/c/three.bin', 1)
        write(self.root + '/top.txt', 10)
        sc, r = self.scan()
        self.assertEqual(r.node.size, allocated(self.root))
        self.assertEqual(r.node.files, 4)
        self.assertEqual(r.node.dirs, 3)

    def test_sparse_file_counts_allocated_not_logical_size(self):
        with open(self.root + '/sparse.img', 'wb') as fh:
            fh.truncate(200 * 1024 * KB)
        sc, r = self.scan()
        self.assertLess(r.node.size, 1024 * KB)
        info = sc.info(self.root + '/sparse.img')
        self.assertEqual(info['lsize'], 200 * 1024 * KB)
        self.assertEqual(info['size'], os.lstat(self.root + '/sparse.img').st_blocks * 512)

    def test_hard_links_are_counted_once(self):
        write(self.root + '/a/f.bin', 256 * KB)
        os.makedirs(self.root + '/b')
        os.link(self.root + '/a/f.bin', self.root + '/b/f.bin')
        os.link(self.root + '/a/f.bin', self.root + '/a/g.bin')
        one = os.lstat(self.root + '/a/f.bin').st_blocks * 512
        sc, r = self.scan()
        self.assertEqual(r.node.size, one)
        self.assertEqual(r.node.files, 3)
        notes = ' '.join(sc.info(self.root + '/b/f.bin')['notes'])
        self.assertIn('3 hard links', notes)

    def test_rescan_keeps_hard_links_counted_once(self):
        # A link whose twin lives outside the rescanned folder must not be counted again.
        write(self.root + '/a/f.bin', 256 * KB)
        os.makedirs(self.root + '/b')
        os.link(self.root + '/a/f.bin', self.root + '/b/f.bin')
        sc, r = self.scan()
        before = r.node.size
        ch = r.node.children
        uncounted = 'a' if ch['a'].size < ch['b'].size else 'b'
        self.assertEqual(sc.rescan_subtree(self.root + '/' + uncounted), 'ok')
        self.wait(lambda: not sc.sub_jobs)
        self.assertEqual(r.node.size, before)
        counted = 'b' if uncounted == 'a' else 'a'
        self.assertEqual(sc.rescan_subtree(self.root + '/' + counted), 'ok')
        self.wait(lambda: not sc.sub_jobs)
        self.assertEqual(r.node.size, before)


class SymlinkTest(ScannerCase):
    def test_symlinks_are_not_followed(self):
        outside = os.path.join(self.tmp, 'outside')
        write(outside + '/big.bin', 512 * KB)
        os.symlink(outside, self.root + '/link-to-dir')
        os.symlink(outside + '/big.bin', self.root + '/link-to-file')
        os.symlink(self.root, self.root + '/loop')
        os.symlink('/nonexistent/target', self.root + '/dangling')
        sc, r = self.scan()
        self.assertLess(r.node.size, 512 * KB)
        self.assertIsNone(r.node.children)          # no symlink became a folder node
        self.assertEqual(r.node.files, 4)

    def test_symlink_info(self):
        os.symlink('/nonexistent/target', self.root + '/dangling')
        sc, r = self.scan()
        info = sc.info(self.root + '/dangling')
        self.assertEqual(info['kind'], 'Symbolic link')
        self.assertTrue(any('/nonexistent/target' in n for n in info['notes']))
        names = {f[0]: f for f in sc.list_files(self.root)}
        self.assertTrue(names['dangling'][3] & dm.F_LINK)


@unittest.skipIf(hasattr(os, 'geteuid') and os.geteuid() == 0, 'root ignores folder permissions')
class PermissionTest(ScannerCase):
    def test_unreadable_folder_is_flagged_not_fatal(self):
        write(self.root + '/locked/secret.bin', 64 * KB)
        write(self.root + '/open/fine.bin', 64 * KB)
        os.chmod(self.root + '/locked', 0)
        sc, r = self.scan()
        locked = r.node.children['locked']
        self.assertTrue(locked.flags & dm.F_DENIED)
        self.assertEqual(locked.size, 0)
        self.assertGreater(r.node.children['open'].size, 0)
        info = sc.info(self.root + '/locked')
        self.assertEqual(info.get('denied'), 1)
        self.assertTrue(any('Full Disk Access' in n for n in info['notes']))


class MountTest(ScannerCase):
    def setUp(self):
        super(MountTest, self).setUp()
        self.net = self.root + '/nas'
        self.usb = self.root + '/usb'
        self.mounts = (dm.Mount(self.net, '//tester@nas.example/share', 'smbfs', False, False),
                       dm.Mount(self.usb, '/dev/disk20s1', 'exfat', True, False))
        write(self.net + '/should-not-count.bin', 256 * KB)
        write(self.usb + '/should-not-count.bin', 256 * KB)
        write(self.root + '/real.bin', 8 * KB)

    def test_mount_points_are_never_crossed_or_stated(self):
        rec = Recorder(self)
        spy = ScandirSpy()
        with mock.patch('os.scandir', side_effect=spy):
            sc, r = self.scan()
        self.assertGreater(spy.calls.get('real.bin', 0), 0)     # control: entries are seen
        self.assertEqual(spy.calls.get('nas', 0), 0)
        self.assertEqual(spy.calls.get('usb', 0), 0)
        self.assertIn(self.root, spy.listed)
        self.assertEqual([p for p in spy.listed if p.startswith((self.net, self.usb))], [])
        self.assertEqual(rec.touched(self.net), [])
        self.assertEqual(rec.touched(self.usb), [])
        nas, usb = r.node.children['nas'], r.node.children['usb']
        self.assertTrue(nas.flags & dm.F_MOUNT and nas.flags & dm.F_NET)
        self.assertTrue(usb.flags & dm.F_MOUNT and not usb.flags & dm.F_NET)
        self.assertEqual((nas.size, usb.size), (0, 0))
        self.assertEqual(r.node.size, os.lstat(self.root + '/real.bin').st_blocks * 512)

    def test_network_mount_info_and_tree_do_not_touch_it(self):
        sc, r = self.scan()
        rec = Recorder(self)
        info = sc.info(self.net)
        tree = sc.tree_payload(self.net)
        self.assertEqual(rec.touched(self.net), [])
        self.assertEqual(info['title'], 'Network volume')
        self.assertTrue(tree.get('stub'))
        self.assertEqual(tree['vol'].get('net'), 1)

    def test_info_below_a_network_mount_does_not_touch_it(self):
        sc, r = self.scan()
        rec = Recorder(self)
        sc.info(self.net + '/should-not-count.bin')
        self.assertEqual(rec.touched(self.net), [])
        self.assertIsNotNone(sc.net_mount_of(self.net + '/deep/x'))
        self.assertIsNone(sc.net_mount_of(self.usb + '/x'))
        self.assertIsNone(sc.net_mount_of(self.root + '/nasty'))

    def test_scan_refuses_without_a_mount_table(self):
        sc = self.scanner()
        with mock.patch.object(dm, 'IS_MAC', True), mock.patch.object(sc, 'mounts', {}), \
                mock.patch.object(dm, 'read_mounts', lambda: {}):
            with self.assertRaises(ValueError):
                sc.start_scan(self.root)


class VolumeListTest(ScannerCase):
    MAC = ('/Volumes/Backup', '/Volumes/.timemachine', '/Volumes/Share', '/System/Volumes/Data',
           '/System/Volumes/Data/home', '/Users/tester/mnt/nas', '/dev')
    LINUX = ('/mnt/disk', '/media/tester/usb', '/srv/nfs', '/proc', '/boot')

    def table(self):
        return (dm.Mount('/Volumes/Backup', '/dev/disk20s1', 'apfs', True, False),
                dm.Mount('/Volumes/.timemachine', '/dev/disk21s1', 'apfs', True, False),
                dm.Mount('/Volumes/Share', '//tester@nas.example/share', 'smbfs', False, False),
                dm.Mount('/System/Volumes/Data', '/dev/disk9s5', 'apfs', True, False),
                dm.Mount('/System/Volumes/Data/home', 'map auto_home', 'autofs', True, False),
                dm.Mount('/Users/tester/mnt/nas', 'nas.example:/export', 'nfs', False, False),
                dm.Mount('/dev', 'devfs', 'devfs', True, False),
                dm.Mount('/mnt/disk', '/dev/sdb1', 'ext4', True, False),
                dm.Mount('/media/tester/usb', '/dev/sdc1', 'vfat', True, False),
                dm.Mount('/srv/nfs', 'server:/export', 'nfs4', False, False),
                dm.Mount('/proc', 'proc', 'proc', True, False),
                dm.Mount('/boot', '/dev/sda1', 'ext4', True, False))

    def volumes(self, is_mac):
        self.mounts = self.table()
        statvfs_calls = []
        fake = os.statvfs_result((4096, 4096, 1000, 400, 300, 0, 0, 0, 0, 255))
        with mock.patch.object(dm, 'IS_MAC', is_mac), \
                mock.patch('os.statvfs', side_effect=lambda p: statvfs_calls.append(p) or fake):
            sc = self.scanner()
            vols = {v['p']: v for v in sc.volumes()}
            payload = sc.mac_payload()
        return vols, statvfs_calls, payload

    def test_mac_drive_list(self):
        vols, calls, payload = self.volumes(True)
        for p in ('/', '/Volumes/Backup', '/Volumes/Share', '/Users/tester/mnt/nas', self.root):
            self.assertIn(p, vols)
        for p in ('/Volumes/.timemachine', '/System/Volumes/Data', '/System/Volumes/Data/home', '/dev'):
            self.assertNotIn(p, vols)
        self.assertEqual(vols['/Volumes/Share'].get('net'), 1)
        self.assertNotIn('/Volumes/Share', calls)
        self.assertNotIn('/Users/tester/mnt/nas', calls)
        # Network volumes never count toward this Mac's total.
        local = sum(k['s'] for k in payload['c'] if not k['vol'].get('net'))
        self.assertEqual(payload['s'], local)

    def test_linux_drive_list(self):
        vols, calls, _payload = self.volumes(False)
        for p in ('/', '/mnt/disk', '/media/tester/usb', '/srv/nfs'):
            self.assertIn(p, vols)
        for p in ('/proc', '/boot'):
            self.assertNotIn(p, vols)
        self.assertNotIn('/srv/nfs', calls)


class MountTableTest(unittest.TestCase):
    def test_parse_mac_mount_output(self):
        text = '\n'.join([
            '/dev/disk9s1s1 on / (apfs, sealed, local, read-only, journaled)',
            '/dev/disk9s5 on /System/Volumes/Data (apfs, local, journaled, nobrowse, protect)',
            '//tester@nas.example/share on /Volumes/share (smbfs, nodev, nosuid, mounted by tester)',
            '/dev/disk12s1 on /Volumes/My Disk (2) (apfs, local, nodev, nosuid, journaled)',
            'not a mount line',
        ])
        m = dm.parse_mac_mounts(text)
        self.assertEqual(sorted(m), ['/', '/System/Volumes/Data', '/Volumes/My Disk (2)', '/Volumes/share'])
        self.assertTrue(m['/'].ro and m['/'].local)
        self.assertEqual(m['/'].container, 'disk9')
        self.assertEqual(m['/System/Volumes/Data'].container, 'disk9')
        self.assertFalse(m['/Volumes/share'].local)
        self.assertEqual(m['/Volumes/share'].fstype, 'smbfs')
        self.assertEqual(m['/Volumes/My Disk (2)'].container, 'disk12')

    def test_parse_linux_proc_mounts(self):
        text = '\n'.join([
            '/dev/sda2 / ext4 rw,relatime 0 0',
            'server:/export /mnt/nfs nfs4 rw,relatime 0 0',
            '/dev/sdb1 /media/tester/USB\\040Stick vfat ro,nosuid 0 0',
            'short line',
        ])
        m = dm.parse_linux_mounts(text)
        self.assertEqual(sorted(m), ['/', '/media/tester/USB Stick', '/mnt/nfs'])
        self.assertFalse(m['/mnt/nfs'].local)
        self.assertTrue(m['/media/tester/USB Stick'].ro)


class CloudTest(ScannerCase):
    def test_cloud_only_folder_is_never_listed(self):
        write(self.root + '/local/a.bin', 8 * KB)
        write(self.root + '/icloud/inside.bin', 256 * KB)
        write(self.root + '/cloud.bin', 1)
        spy = ScandirSpy({'icloud': dm.SF_DATALESS, 'cloud.bin': dm.SF_DATALESS})
        listed = spy.listed
        with mock.patch.object(dm, 'IS_MAC', True), mock.patch('os.scandir', side_effect=spy):
            sc, r = self.scan()
            files = {f[0]: f for f in sc.list_files(self.root)}
        cloud = r.node.children['icloud']
        self.assertTrue(cloud.flags & dm.F_CLOUD)
        self.assertEqual(cloud.size, 0)
        self.assertIn(self.root + '/local', listed)    # the wrapper was used
        self.assertNotIn(self.root + '/icloud', listed)
        self.assertTrue(files['cloud.bin'][3] & dm.F_CLOUD)

    def test_cloud_only_folder_is_not_opened_or_rescanned(self):
        write(self.root + '/icloud/inside.bin', 256 * KB)
        spy = ScandirSpy({'icloud': dm.SF_DATALESS})
        with mock.patch.object(dm, 'IS_MAC', True), mock.patch('os.scandir', side_effect=spy):
            sc, r = self.scan()
            t = sc.tree_payload(self.root + '/icloud')
            self.assertEqual((t.get('stub'), t.get('cloud')), (1, 1))
            self.assertNotEqual(sc.rescan_subtree(self.root + '/icloud'), 'ok')
        self.assertNotIn(self.root + '/icloud', spy.listed)


class TreeTest(ScannerCase):
    def test_pruned_folders_reload_on_demand(self):
        write(self.root + '/big/huge.bin', 64 * KB)
        write(self.root + '/small/deep/er/leaf.bin', 4 * KB)
        with mock.patch.object(dm, 'PRUNE_BYTES', 32 * KB), mock.patch.object(dm, 'BIG_FILE', 16 * KB):
            sc, r = self.scan()
            small = r.node.children['small']
            self.assertTrue(small.flags & dm.F_PRUNED)
            self.assertIsNone(small.children)
            _r, leaf_dir = sc.lookup(self.root + '/small/deep/er')
            self.assertIsNotNone(leaf_dir)
            self.assertEqual(leaf_dir.size, os.lstat(self.root + '/small/deep/er/leaf.bin').st_blocks * 512)
            self.assertEqual(r.node.size, allocated(self.root))
            tree = sc.tree_payload(self.root + '/small/deep')
            self.assertEqual(tree['p'], self.root + '/small/deep')
            big = sc.tree_payload(self.root + '/big')
            self.assertIn('huge.bin', [c['n'] for c in big['c']])

    def test_missing_path_points_to_nearest_folder(self):
        write(self.root + '/a/x.bin', 1)
        sc, r = self.scan()
        t = sc.tree_payload(self.root + '/a/gone/deeper')
        self.assertEqual(t.get('missing'), 1)
        self.assertEqual(t['near'], self.root + '/a')

    def test_rescan_folds_changes_into_parents(self):
        write(self.root + '/a/x.bin', 8 * KB)
        write(self.root + '/b/y.bin', 8 * KB)
        sc, r = self.scan()
        write(self.root + '/a/new.bin', 128 * KB)
        self.assertEqual(sc.rescan_subtree(self.root + '/a'), 'ok')
        self.wait(lambda: not sc.sub_jobs)
        self.assertEqual(r.node.size, allocated(self.root))
        shutil.rmtree(self.root + '/b')          # our own fixture, removed to simulate a delete in Finder
        self.assertEqual(sc.rescan_subtree(self.root + '/b'), 'ok')
        self.wait(lambda: not sc.sub_jobs)
        self.assertNotIn('b', r.node.children)
        self.assertEqual(r.node.size, allocated(self.root))
        self.assertEqual(r.node.dirs, 1)

    def test_double_slash_paths_are_folded_and_do_not_hang(self):
        import threading
        self.assertEqual(dm.clean_path('//Volumes//x/'), '/Volumes/x')
        self.assertEqual(dm.clean_path('/'), '/')
        sc, r = self.scan()
        out = []
        t = threading.Thread(target=lambda: out.append(sc.tree_payload('//nope/deeper')))
        t.daemon = True
        t.start()
        t.join(5)
        self.assertFalse(t.is_alive(), 'tree_payload looped on a // path')

    def test_live_listing_refuses_a_folder_swapped_for_a_link(self):
        write(self.root + '/a/mine.bin', 8 * KB)
        write(self.root + '/other/theirs.bin', 8 * KB)
        sc, r = self.scan()
        shutil.rmtree(self.root + '/a')          # our own fixture
        os.symlink(self.root + '/other', self.root + '/a')
        self.assertNotIn('theirs.bin', [f[0] for f in sc.list_files(self.root + '/a')])
        self.assertEqual(sc.rescan_subtree(self.root + '/a'), 'ok')
        self.wait(lambda: not sc.sub_jobs)
        a = r.node.children.get('a')
        self.assertTrue(a is None or 'theirs.bin' not in str(sc.tree_payload(self.root + '/a')))

    def test_request_scan_rejects_unknown_paths(self):
        sc = self.scanner()
        with self.assertRaises(ValueError):
            sc.request_scan(self.tmp + '/not-a-root')


class CacheTest(ScannerCase):
    def test_cache_round_trip(self):
        write(self.root + '/café/☃ snow.bin', 24 * KB)
        write(self.root + '/plain/a.bin', 4 * KB)
        cache = os.path.join(self.tmp, 'cache')
        sc, r = self.scan(self.scanner(cache))
        sc.save_cache(r)
        fn = sc._cache_file(self.root)
        self.assertEqual(stat.S_IMODE(os.stat(fn).st_mode), 0o600)
        sc2 = self.scanner(cache)
        self.assertEqual(sc2.load_caches([self.root]), {self.root})
        r2 = sc2.roots[self.root]
        self.assertTrue(r2.from_cache)
        self.assertEqual((r2.node.size, r2.node.files, r2.node.dirs), (r.node.size, r.node.files, r.node.dirs))
        self.assertIn('café', r2.node.children)

    def test_unreadable_cache_is_ignored(self):
        cache = os.path.join(self.tmp, 'cache')
        sc = self.scanner(cache)
        os.makedirs(cache)
        with open(sc._cache_file(self.root), 'wb') as fh:
            fh.write(b'not gzip')
        with mock.patch.object(sys, 'stderr'):
            self.assertEqual(sc.load_caches([self.root]), set())


    def test_cache_folder_is_made_private_and_bad_names_are_rejected(self):
        import gzip, json
        write(self.root + '/a/x.bin', 4 * KB)
        cache = os.path.join(self.tmp, 'cache')
        os.makedirs(cache, mode=0o755)
        os.chmod(cache, 0o755)
        sc, r = self.scan(self.scanner(cache))
        sc.save_cache(r)
        self.assertEqual(stat.S_IMODE(os.stat(cache).st_mode), 0o700)
        fn = sc._cache_file(self.root)
        with gzip.open(fn, 'rb') as fh:
            data = json.loads(fh.read().decode('ascii'))
        data['tree'][9][0][0] = '/nope'          # a child name that is really a path
        with gzip.open(fn, 'wb') as fh:
            fh.write(json.dumps(data).encode('ascii'))
        with mock.patch.object(sys, 'stderr'):
            self.assertEqual(self.scanner(cache).load_caches([self.root]), set())


if __name__ == '__main__':
    unittest.main()
