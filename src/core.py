#!/usr/bin/env python3
"""
diskmap: an interactive map of where your Mac's storage goes.

    python3 diskmap.py            # scan the startup disk and open the map
    python3 diskmap.py ~/dev      # scan just this folder first (drives stay one click away)
    python3 diskmap.py --install-app   # macOS: add a "Disk Map" app you can open like any other
    python3 diskmap.py --help

Runs entirely on this computer. It starts a small web server on 127.0.0.1,
opens the map in your browser, and never deletes or changes any file.
The page only opens through the private link printed at startup.
Finished scans are saved in ~/Library/Caches/diskmap so the next start is instant.
Needs only Python 3.8+ (the python3 that ships with Xcode Command Line Tools works).
"""
from __future__ import print_function

import argparse
import gzip
import hashlib
import heapq
import itertools
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
import threading
import time
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
from urllib.request import ProxyHandler, Request, build_opener

VERSION = '1.2'
APP_NAME = 'Disk Map'
IS_MAC = sys.platform == 'darwin'

#__ADVICE__#

# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------

F_DENIED, F_MOUNT, F_NET, F_CLOUD, F_PKG, F_LINK, F_ERR = 1, 2, 4, 8, 16, 32, 64
F_PRUNED = 256                      # internal: children dropped to save memory, reloaded on demand
NEW, SCANNING, DONE = 0, 1, 2

PRUNE_BYTES = 4 * 1024 * 1024       # folders smaller than this keep only their totals in memory
BIG_FILE = 8 * 1024 * 1024          # files at least this big are remembered individually
PAR_DEPTH = 4                       # folder levels that fan out to parallel workers
EXPAND_FRAC = 0.004                 # nested folders below this share of the view are not expanded
ITEM_DIV = 6000.0                   # nested items below 1/ITEM_DIV of the view are grouped
CACHE_V = 3
SF_DATALESS = 0x40000000            # macOS: file or folder is in the cloud, not downloaded

SKIP = object()
SKIP_FS = frozenset(['devfs', 'autofs', 'proc', 'sysfs', 'devtmpfs', 'devpts', 'cgroup', 'cgroup2',
                     'securityfs', 'debugfs', 'tracefs', 'mqueue', 'hugetlbfs', 'pstore', 'bpf',
                     'configfs', 'fusectl', 'binfmt_misc', 'nsfs', 'ramfs', 'tmpfs', 'rpc_pipefs',
                     'efivarfs'])
NET_FS = frozenset(['smbfs', 'nfs', 'nfs4', 'afpfs', 'webdav', 'cifs', 'ftp', 'fuse.sshfs', '9p'])
ROOT_SKIP_NAMES = ('.nofollow', '.resolve', '.vol', '.file')   # macOS path-lookup magic at /


class Node(object):
    __slots__ = ('name', 'parent', 'state', 'flags', 'size', 'files', 'dirs', 'mtime',
                 'fsize', 'fcount', 'big', 'children', 'pending')

    def __init__(self, name, parent):
        self.name = name
        self.parent = parent
        self.state = NEW
        self.flags = 0
        self.size = 0        # bytes on disk in this whole subtree (final once state == DONE)
        self.files = 0       # files in this whole subtree
        self.dirs = 0        # folders in this whole subtree
        self.mtime = 0       # newest file modification time in the subtree
        self.fsize = 0       # bytes on disk of files directly in this folder
        self.fcount = 0      # files directly in this folder
        self.big = None      # [(name, bytes, mtime)] for large files directly in this folder
        self.children = None  # {name: Node} for subfolders; replaced wholesale, never mutated
        self.pending = 0


def path_of(node):
    parts = []
    while node.parent is not None:
        parts.append(node.name)
        node = node.parent
    root = node.name
    if not parts:
        return root
    parts.reverse()
    return (root if root.endswith('/') else root + '/') + '/'.join(parts)


def join(path, name):
    return path + name if path.endswith('/') else path + '/' + name


class Mount(object):
    __slots__ = ('path', 'device', 'fstype', 'local', 'ro', 'container')

    def __init__(self, path, device, fstype, local, ro):
        self.path = path
        self.device = device
        self.fstype = fstype
        self.local = local
        self.ro = ro
        m = re.match(r'^/dev/(disk\d+)s\d+', device)
        self.container = m.group(1) if m else device


def parse_mac_mounts(text):
    mounts = {}
    for line in text.splitlines():
        m = re.match(r'^(.*?) on (/.*) \(([^()]*)\)\s*$', line)
        if not m:
            continue
        flags = [f.strip() for f in m.group(3).split(',')]
        mounts[m.group(2)] = Mount(m.group(2), m.group(1), flags[0], 'local' in flags, 'read-only' in flags)
    return mounts


def parse_linux_mounts(text):
    mounts = {}
    for line in text.splitlines():
        f = line.split()
        if len(f) < 4:
            continue
        mp = re.sub(r'\\([0-7]{3})', lambda m: chr(int(m.group(1), 8)), f[1])
        mounts[mp] = Mount(mp, f[0], f[2], f[2] not in NET_FS, 'ro' in f[3].split(','))
    return mounts


def read_mounts():
    try:
        if IS_MAC:
            out = subprocess.run(['/sbin/mount'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                 universal_newlines=True, timeout=10).stdout
            return parse_mac_mounts(out)
        with open('/proc/mounts') as fh:
            return parse_linux_mounts(fh.read())
    except Exception:
        return {}


def vol_space(path, container_level=False):
    """(total, used, available) in bytes, or None. On APFS several volumes share one
    container: container_level=True reports everything used in the container."""
    try:
        sv = os.statvfs(path)
    except OSError:
        return None
    total = sv.f_blocks * sv.f_frsize
    avail = sv.f_bavail * sv.f_frsize
    free = sv.f_bfree * sv.f_frsize
    used = total - avail if container_level else total - free
    return (total, max(used, 0), avail)


class Job(object):
    def __init__(self, root, path, prune, on_done, special, container, limit=0, follow_top=False):
        self.root = root
        self.follow_top = follow_top   # only a full scan may start at a link (for example /tmp)
        self.path = path
        self.prune = prune
        self.on_done = on_done
        self.special = special
        self.container = container
        self.seen = {}          # device+inode of hard-linked files already counted -> folder that counted it
        self.limit = limit      # bytes used in the whole container, for sanity checks


class Root(object):
    def __init__(self, path, kind):
        self.path = path
        self.kind = kind            # 'volume' or 'folder'
        self.node = None
        self.state = 'none'         # none | scanning | done
        self.started = 0.0
        self.scanned_at = 0
        self.duration = 0.0
        self.from_cache = False
        self.job = None
        self.limit = 0
        self.links = {}             # the full scan's hard-link record (Job.seen); empty after a cache load


def scandir_nofollow(path):
    """os.scandir that refuses a link. A folder seen in a scan can be swapped for a link
    later; following it would list another folder's files under this path and its advice."""
    flags = getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_DIRECTORY', 0)
    if not flags or os.scandir not in os.supports_fd:
        return os.scandir(path)
    fd = os.open(path, os.O_RDONLY | flags)
    try:
        return _FdScandir(fd)
    except BaseException:
        os.close(fd)
        raise


class _FdScandir(object):
    """Keeps the folder's descriptor open for as long as the listing is in use."""
    def __init__(self, fd):
        self.it = os.scandir(fd)
        self.fd = fd

    def __iter__(self):
        return iter(self.it)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        self.it.close()
        if self.fd >= 0:
            os.close(self.fd)
            self.fd = -1


def ok_name(name):
    """A plausible single file name: a cache file edited by another program must not turn a
    name into a path."""
    return isinstance(name, str) and name not in ('', '.', '..') and '/' not in name and '\x00' not in name


def private_dir(path):
    """Make path a folder only this user can read, even if it already existed."""
    os.makedirs(path, mode=0o700, exist_ok=True)
    os.chmod(path, 0o700)


def open_private(path):
    """Create a new file that is 0600 from the first byte (no window with umask permissions)."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    return os.fdopen(fd, 'wb')


def drop_stale(path):
    """Remove a temp file of ours left by a crash, so open_private can create it again."""
    try:
        os.unlink(path)
    except OSError:
        pass


def clean_path(p):
    """normpath that also folds a leading '//', which POSIX normpath keeps and which would
    otherwise slip past the mount table and loop forever in parent walks."""
    return os.path.normpath('/' + p.lstrip('/'))


class Scanner(object):
    def __init__(self, workers, cache_dir, pinned=()):
        self.lock = threading.Lock()
        self.pool = ThreadPoolExecutor(max_workers=workers)
        self.roots = {}
        self.gen = 1
        self.cache_dir = cache_dir
        self.pinned = list(pinned)
        self.mounts = {}
        self.mounts_at = 0.0
        self.sub_jobs = {}
        self.loading = False
        self._lf = {}
        self._vols = None
        self._vols_at = 0.0
        self.refresh_mounts(True)
        self.root_name = self._mac_root_name()

    # ----- mounts and volumes -----

    def _mac_root_name(self):
        if not IS_MAC:
            return 'Root filesystem'
        try:
            for name in os.listdir('/Volumes'):
                p = '/Volumes/' + name
                if p in self.mounts:    # a real mount (maybe a dead share): never stat it
                    continue
                if os.path.islink(p) and os.path.realpath(p) == '/':
                    return name
        except OSError:
            pass
        return 'Macintosh HD'

    def refresh_mounts(self, force=False):
        now = time.time()
        if force or now - self.mounts_at > 5:
            m = read_mounts()
            if m:
                self.mounts = m
            self.mounts_at = now
            self._vols = None
        return self.mounts

    def net_mount_of(self, path):
        """The network mount that holds path, or None. Uses only the mount table, never a stat."""
        best = None
        for mp, m in list(self.mounts.items()):
            if path == mp or path.startswith(mp.rstrip('/') + '/'):
                if best is None or len(mp) > len(best.path):
                    best = m
        return best if best is not None and not best.local else None

    def display_name(self, path):
        if path == '':
            return 'This Mac' if IS_MAC else 'This computer'
        if path == '/':
            return self.root_name
        return os.path.basename(path) or path

    def is_drive(self, path):
        for v in self.volumes():
            if v['p'] == path:
                return v
        return None

    def volumes(self):
        """Entries shown at the top (drives) level."""
        now = time.time()
        if self._vols is not None and now - self._vols_at < 3:
            return self._vols
        mounts = self.refresh_mounts()
        vols = []
        seen = set()

        def add(path, name, m, kind):
            if path in seen:
                return
            seen.add(path)
            v = {'p': path, 'n': name, 'kind': kind}
            if m is not None:
                v['fstype'] = m.fstype
                if m.ro:
                    v['ro'] = 1
            if m is not None and not m.local:
                v['net'] = 1
            elif kind == 'volume':
                sp = vol_space(path, container_level=(IS_MAC and path == '/'))
                if sp:
                    v['total'], v['used'], v['free'] = sp
            vols.append(v)

        add('/', self.root_name, mounts.get('/'), 'volume')
        for mp in sorted(mounts):
            m = mounts[mp]
            if mp == '/' or m.fstype in SKIP_FS:
                continue
            parent, base = os.path.split(mp)
            if IS_MAC:
                if parent == '/Volumes' and not base.startswith('.'):
                    add(mp, base, m, 'volume')
                elif not m.local and not mp.startswith('/System/'):
                    add(mp, base, m, 'volume')
            else:
                if not m.local or parent in ('/mnt', '/media') or mp.startswith('/media/'):
                    add(mp, base, m, 'volume')
        for p in self.pinned:
            add(p, os.path.basename(p) or p, None, 'folder')
        self._vols = vols
        self._vols_at = now
        return vols

    def _special_for(self, root_path):
        """Per-folder table of child names that need special handling during a scan:
        mount points (never crossed) and names to skip outright."""
        special = {}
        for mp, m in self.mounts.items():
            if mp == root_path or mp == '/':
                continue
            paths = [mp]
            if mp.startswith('/System/Volumes/Data/'):
                paths.append(mp[20:])
            for p in paths:
                parent, base = os.path.split(p)
                special.setdefault(parent, {})[base] = m
        if root_path == '/':
            top = special.setdefault('/', {})
            for n in ROOT_SKIP_NAMES:
                top[n] = SKIP
            if IS_MAC:
                # The Data volume's contents already appear under / through firmlinks.
                special.setdefault('/System/Volumes', {})['Data'] = SKIP
        return special

    def _container_of(self, path):
        best = None
        for mp, m in self.mounts.items():
            if path == mp or path.startswith(mp if mp.endswith('/') else mp + '/'):
                if best is None or len(mp) > len(best.path):
                    best = m
        if best is None:
            return None
        if IS_MAC and best.path == '/':
            data = self.mounts.get('/System/Volumes/Data')
            if data is not None:
                return data.container
        return best.container

    # ----- scanning -----

    def start_scan(self, path):
        """Scan a volume or pinned folder from scratch, in the background.
        Raises ValueError when the mount table cannot be read, since the scan could then
        walk into network shares."""
        r = self.roots.get(path)
        if r is not None and r.state == 'scanning':
            return r
        # Outside the lock: both can block on a slow drive, and every request needs the lock.
        self.refresh_mounts(True)
        if IS_MAC and not self.mounts:
            raise ValueError('Could not read the list of mounted drives, so the scan did not start. Try again.')
        sp = vol_space(path, container_level=True) if path in self.mounts else None
        with self.lock:
            r = self.roots.get(path)
            if r is not None and r.state == 'scanning':
                return r
            kind = 'folder' if path in self.pinned and path not in self.mounts else 'volume'
            r = Root(path, kind)
            r.node = Node(path, None)
            r.state = 'scanning'
            r.started = time.time()
            job = Job(r.node, path, PRUNE_BYTES, None, self._special_for(path), self._container_of(path),
                      follow_top=True)
            job.on_done = lambda: self._root_done(r)
            r.limit = job.limit = sp[1] if sp else 0
            r.job = job
            r.links = job.seen
            self.roots[path] = r
            self.gen += 1
        self.pool.submit(self._run, job, r.node, path, 0)
        return r

    def _root_done(self, r):
        r.duration = time.time() - r.started
        r.scanned_at = int(time.time())
        r.from_cache = False
        r.job = None
        r.state = 'done'
        self.gen += 1
        threading.Thread(target=self.save_cache, args=(r,), daemon=True).start()

    def rescan_subtree(self, path):
        """Rescan one folder inside an already scanned tree and fold the change into its parents."""
        r, node = self.lookup(path)
        if r is None:
            return 'not scanned'
        if node is None:
            return 'not found'
        if node is r.node:
            self.start_scan(r.path)
            return 'ok'
        if node.flags & F_CLOUD:
            return 'not downloaded from iCloud'
        if r.state != 'done':
            return 'busy'
        with self.lock:
            if path in self.sub_jobs:
                return 'ok'
            self.sub_jobs[path] = time.time()
        parent = node.parent
        new = Node(node.name, parent)

        def done():
            with self.lock:
                cur = (parent.children or {}).get(node.name, node)
                ch = dict(parent.children or {})
                if os.path.lexists(path) and not new.flags & F_ERR:
                    ch[new.name] = new
                    delta = (new.size - cur.size, new.files - cur.files, new.dirs - cur.dirs)
                else:   # the folder is gone (for example, you deleted it in Finder)
                    ch.pop(node.name, None)
                    delta = (-cur.size, -cur.files, -cur.dirs - 1)
                parent.children = ch
                self._apply_delta(parent, delta, new.mtime)
                self._merge_links(r, path, job.seen if path in ch else {})
                self.sub_jobs.pop(path, None)
                self.gen += 1
            threading.Thread(target=self.save_cache, args=(r,), daemon=True).start()

        job = Job(new, path, PRUNE_BYTES, done, self._special_for(r.path), self._container_of(path), r.limit)
        job.seen = self._links_outside(r, path)
        self.pool.submit(self._run, job, new, path, 1)
        return 'ok'

    @staticmethod
    def _links_outside(r, path):
        """Hard links counted by folders outside path. A rescan of path starts from these, so a
        file whose other link lives elsewhere is not counted twice, and one counted inside path
        is counted again."""
        pre = path.rstrip('/') + '/'
        return {k: v for k, v in list(r.links.items()) if v != path and not v.startswith(pre)}

    def _merge_links(self, r, path, seen):
        pre = path.rstrip('/') + '/'
        links = self._links_outside(r, path)
        for k, v in seen.items():
            if v == path or v.startswith(pre):
                links[k] = v
        r.links = links

    @staticmethod
    def _apply_delta(node, delta, mtime=0):
        while node is not None:
            node.size = max(node.size + delta[0], 0)
            node.files = max(node.files + delta[1], 0)
            node.dirs = max(node.dirs + delta[2], 0)
            if mtime > node.mtime:
                node.mtime = mtime
            node = node.parent

    def _run(self, job, node, path, depth):
        """Pool task: list one folder, then either fan its subfolders out to the pool
        (near the top of the tree) or scan them in this thread."""
        try:
            subdirs = self._list_dir(job, node, path)
        except Exception:
            node.flags |= F_ERR
            subdirs = []
        if depth < PAR_DEPTH and subdirs:
            with self.lock:
                node.pending = len(subdirs)
            for child, cpath in subdirs:
                try:
                    self.pool.submit(self._run, job, child, cpath, depth + 1)
                except RuntimeError:     # pool is shutting down
                    child.state = DONE
                    self._child_finished(job, child)
            return
        for child, cpath in subdirs:
            self._scan_seq(job, child, cpath)
        self._finish(job, node)

    def _scan_seq(self, job, node, path):
        try:
            for child, cpath in self._list_dir(job, node, path):
                self._scan_seq(job, child, cpath)
        except Exception:
            node.flags |= F_ERR
        self._finalize(job, node)

    def _list_dir(self, job, node, path):
        """Read one folder: total its files, create nodes for its subfolders.
        Returns the subfolders that still need scanning as [(node, path)]."""
        node.state = SCANNING
        fsize = 0
        fcount = 0
        newest = 0
        big = None
        kids = None
        todo = []
        special = job.special.get(path)
        seen = job.seen
        prefix = path if path.endswith('/') else path + '/'
        try:
            it = os.scandir(path) if job.follow_top and path == job.path else scandir_nofollow(path)
        except PermissionError:
            node.flags |= F_DENIED
            return todo
        except OSError:
            node.flags |= F_ERR
            return todo
        try:
            with it:
                for e in it:
                    name = e.name
                    if special is not None and name in special:
                        m = special[name]
                        if m is SKIP or m.fstype in SKIP_FS:
                            continue
                        child = Node(name, node)   # a mount point: never crossed, never touched
                        child.flags |= F_MOUNT
                        if not m.local:
                            child.flags |= F_NET
                        elif job.container is not None and m.container == job.container:
                            # A sibling volume in the same APFS container (swap, preboot, updates):
                            # it uses real space on this drive, so count what it reports.
                            sp = vol_space(prefix + name)
                            if sp and job.limit and sp[1] < job.limit * 0.5:
                                child.size = sp[1]
                        child.state = DONE
                        if kids is None:
                            kids = {}
                        kids[name] = child
                        continue
                    try:
                        st = e.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    mode = st.st_mode
                    if mode & 0o170000 == 0o040000:      # directory
                        child = Node(name, node)
                        if kids is None:
                            kids = {}
                        kids[name] = child
                        if IS_MAC and st.st_flags & SF_DATALESS:
                            child.flags |= F_CLOUD        # not downloaded: listing it would fetch it
                            child.state = DONE
                            continue
                        todo.append((child, prefix + name))
                    else:
                        b = st.st_blocks * 512
                        if st.st_nlink > 1 and mode & 0o170000 == 0o100000:
                            key = (st.st_dev << 64) | st.st_ino
                            if key in seen:
                                b = 0
                            else:
                                seen[key] = path
                        fsize += b
                        fcount += 1
                        mt = int(st.st_mtime)
                        if mt > newest:
                            newest = mt
                        if b >= BIG_FILE:
                            if big is None:
                                big = []
                            big.append((name, b, mt))
        except PermissionError:
            node.flags |= F_DENIED
        except OSError:
            node.flags |= F_ERR
        node.fsize = fsize
        node.fcount = fcount
        node.mtime = newest
        node.big = big
        node.children = kids
        return todo

    def _finalize(self, job, node):
        size = node.fsize
        files = node.fcount
        dirs = 0
        mt = node.mtime
        ch = node.children
        if ch:
            for c in ch.values():
                size += c.size
                files += c.files
                dirs += c.dirs + 1
                if c.mtime > mt:
                    mt = c.mtime
        node.size = size
        node.files = files
        node.dirs = dirs
        node.mtime = mt
        if size < job.prune and node is not job.root and (ch or node.big):
            node.children = None
            node.big = None
            node.flags |= F_PRUNED
        node.state = DONE

    def _finish(self, job, node):
        """A fanned-out folder is complete; walk up while parents become complete too."""
        while True:
            self._finalize(job, node)
            if node is job.root:
                try:
                    job.on_done()
                except Exception as exc:     # never leave a scan hanging
                    sys.stderr.write('diskmap: scan completion failed: %r\n' % (exc,))
                return
            parent = node.parent
            with self.lock:
                parent.pending -= 1
                ready = parent.pending == 0
            if not ready:
                return
            node = parent

    def _child_finished(self, job, child):
        parent = child.parent
        with self.lock:
            parent.pending -= 1
            ready = parent.pending == 0
        if ready:
            self._finish(job, parent)

    def _ensure_loaded(self, r, node, path):
        """Reload the children of a folder whose details were dropped to save memory."""
        if not node.flags & F_PRUNED or node.children is not None:
            return
        tmp = Node(node.name, None)
        job = Job(tmp, path, 0, None, self._special_for(r.path), self._container_of(path), r.limit)
        job.seen = self._links_outside(r, path)
        self._scan_seq(job, tmp, path)
        with self.lock:
            self._merge_links(r, path, job.seen)
            for c in (tmp.children or {}).values():
                c.parent = node
            delta = (tmp.size - node.size, tmp.files - node.files, tmp.dirs - node.dirs)
            node.fsize = tmp.fsize
            node.fcount = tmp.fcount
            node.big = tmp.big
            node.children = tmp.children
            node.flags &= ~F_PRUNED
            if r.state == 'done' and delta != (0, 0, 0):
                self._apply_delta(node, delta, tmp.mtime)

    # ----- reading the tree -----

    def lookup(self, path):
        best = None
        for rp, r in list(self.roots.items()):
            if path == rp or path.startswith(rp if rp.endswith('/') else rp + '/'):
                if best is None or len(rp) > len(best.path):
                    best = r
        if best is None:
            return None, None
        node = best.node
        if path != best.path:
            cur = best.path
            for part in path[len(best.path):].strip('/').split('/'):
                if node.flags & F_PRUNED and node.children is None:
                    self._ensure_loaded(best, node, cur)
                ch = node.children
                node = ch.get(part) if ch else None
                if node is None:
                    return best, None
                cur = join(cur, part)
        return best, node

    def snap(self, node, memo):
        """(bytes, files, folders, newest mtime, complete) for a node, including partial
        totals for folders that are still being scanned."""
        if node.state == DONE:
            return (node.size, node.files, node.dirs, node.mtime, True)
        k = id(node)
        v = memo.get(k)
        if v is not None:
            return v
        size = node.fsize
        files = node.fcount
        dirs = 0
        mt = node.mtime
        ch = node.children
        if ch:
            for c in ch.values():
                s = self.snap(c, memo)
                size += s[0]
                files += s[1]
                dirs += s[2] + 1
                if s[3] > mt:
                    mt = s[3]
        v = (size, files, dirs, mt, False)
        memo[k] = v
        return v

    def list_files(self, path):
        """Live listing of the plain files directly in a folder: [(name, bytes, mtime, flags)]."""
        ent = self._lf.get(path)
        now = time.time()
        if ent is not None and ent[0] == self.gen and now - ent[1] < 20:
            return ent[2]
        out = []
        try:
            with scandir_nofollow(path) as it:
                for e in it:
                    try:
                        if e.is_dir(follow_symlinks=False):
                            continue
                        st = e.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    fl = 0
                    if stat.S_ISLNK(st.st_mode):
                        fl |= F_LINK
                    if IS_MAC and st.st_flags & SF_DATALESS:
                        fl |= F_CLOUD
                    out.append((e.name, st.st_blocks * 512, int(st.st_mtime), fl))
        except OSError:
            pass
        if len(self._lf) > 64:
            self._lf.clear()
        self._lf[path] = (self.gen, now, out)
        return out

    def _ndict(self, node, name, path, memo):
        s = self.snap(node, memo)
        d = {'n': name, 's': s[0], 'k': 'd', 'lv': level_of(path, True)}
        if s[3]:
            d['mt'] = s[3]
        if s[1]:
            d['fc'] = s[1]
        if s[2]:
            d['dc'] = s[2]
        fl = node.flags & 0xFF
        if is_package(name):
            fl |= F_PKG
        if fl:
            d['fl'] = fl
        if not s[4]:
            d['st'] = 1
        if node.flags & F_MOUNT:
            d['k'] = 'v'
        return d

    def _kids(self, node, path, live, root_size, lv, memo):
        items = []
        prefix = path if path.endswith('/') else path + '/'
        ch = node.children
        if ch:
            for name, c in ch.items():
                cp = prefix + name
                d = self._ndict(c, name, cp, memo)
                items.append((d['s'], d, c, cp))
        osize = 0
        ocnt = 0
        if live:
            for name, size, mt, fl in self.list_files(path):
                d = {'n': name, 's': size, 'k': 'f', 'lv': level_of(prefix + name, False)}
                if mt:
                    d['mt'] = mt
                if fl:
                    d['fl'] = fl
                items.append((size, d, None, None))
            cap = 800
            min_item = 0
        else:
            bsum = 0
            for name, size, mt in (node.big or ()):
                items.append((size, {'n': name, 's': size, 'k': 'f', 'mt': mt,
                                     'lv': level_of(prefix + name, False)}, None, None))
                bsum += size
            osize = max(node.fsize - bsum, 0)
            ocnt = max(node.fcount - len(node.big or ()), 0)
            cap = 60
            min_item = root_size / ITEM_DIV
        items.sort(key=lambda t: -t[0])
        out = []
        for i, it in enumerate(items):
            if i < cap and it[0] >= min_item:
                out.append(it)
            else:
                osize += it[0]
                ocnt += 1
        if ocnt > 0 and (osize > 0 or live):
            out.append((osize, {'n': '', 's': osize, 'k': 'o', 'cnt': ocnt, 'lv': lv}, None, None))
        if not live and len(out) == 1 and out[0][1]['k'] == 'o':
            return []
        return [(d, n, p) for (_s, d, n, p) in out]

    def _expand(self, r, node, path, budget, live_top, used=None):
        """Build the nested description of a folder that the map draws: largest items
        first, expanding deeper only where tiles would be big enough to see."""
        memo = {}
        top = self._ndict(node, self.display_name(path) if node.parent is None else node.name, path, memo)
        root_size = max(top['s'], 1)
        if used:
            root_size = max(root_size, used)
        counter = itertools.count()
        heap = [(-root_size, next(counter), node, top, path, 0)]
        while heap and budget > 0:
            negs, _c, nd, d, p, depth = heapq.heappop(heap)
            if depth > 0 and -negs < root_size * EXPAND_FRAC:
                break
            if nd.flags & F_PRUNED and nd.children is None:
                if depth > 0:
                    continue
                self._ensure_loaded(r, nd, p)
            kids = self._kids(nd, p, depth == 0 and live_top, root_size, d['lv'], memo)
            if depth == 0 and used is not None and node is r.node:
                resid = used - top['s']
                if r.state == 'scanning':
                    if resid > 0:
                        kids.append(({'n': '', 's': resid, 'k': 'u', 'sc': 1, 'lv': 'm'}, None, None))
                        top['s'] = used
                elif resid > max(200 * 1000 * 1000, used * 0.01):
                    kids.append(({'n': '', 's': resid, 'k': 'u', 'lv': 'm'}, None, None))
                    top['s'] = used
            if not kids:
                continue
            d['c'] = [k[0] for k in kids]
            budget -= len(kids)
            for kd, kn, kp in kids:
                if kn is None or kn.flags & (F_MOUNT | F_DENIED | F_CLOUD):
                    continue
                if kd.get('fl', 0) & F_PKG:
                    continue     # packages (apps, libraries) stay one tile until you zoom in
                if kn.children or kn.fcount or kn.flags & F_PRUNED:
                    heapq.heappush(heap, (-kd['s'], next(counter), kn, kd, kp, depth + 1))
        return top

    def crumbs(self, path):
        out = [{'p': '', 'n': self.display_name('')}]
        if path == '':
            return out
        start = '/'
        if IS_MAC and path.startswith('/Volumes/'):
            for v in self.volumes():
                vp = v['p']
                if vp.startswith('/Volumes/') and (path == vp or path.startswith(vp + '/')):
                    if len(vp) > len(start):
                        start = vp
        out.append({'p': start, 'n': self.display_name(start)})
        if path != start:
            cur = start
            for part in path[len(start):].strip('/').split('/'):
                cur = join(cur, part)
                out.append({'p': cur, 'n': part})
        return out

    def _root_used(self, r):
        v = self.is_drive(r.path)
        if v is not None and 'used' in v:
            return v
        return None

    def tree_payload(self, path):
        if path == '':
            return self.mac_payload()
        r, node = self.lookup(path)
        base = {'p': path, 'crumbs': self.crumbs(path), 'gen': self.gen}
        m = self.mounts.get(path)
        drive = self.is_drive(path)
        if r is not None and node is not None and node is not r.node and node.flags & F_CLOUD:
            # Not downloaded: listing it would make macOS fetch it from iCloud.
            d = dict(base)
            d.update({'n': node.name, 's': 0, 'stub': 1, 'cloud': 1, 'lv': level_of(path, True),
                      'k': 'd', 'fl': F_CLOUD})
            return d
        if r is None or (node is not None and node is not r.node and node.flags & F_MOUNT):
            # Not scanned: an unscanned drive, a volume mounted inside another tree, or a
            # folder on a drive that has not been scanned yet.
            d = dict(base)
            d.update({'n': self.display_name(path), 's': 0, 'stub': 1, 'lv': 'm',
                      'k': 'v' if (m is not None or drive) else 'd'})
            if m is not None or drive:
                d['scan'] = path
                if drive:
                    d['vol'] = drive
                elif m is not None:
                    d['vol'] = {'p': path, 'n': d['n'], 'fstype': m.fstype, 'kind': 'volume'}
                    if not m.local:
                        d['vol']['net'] = 1
            else:
                d['scan'] = base['crumbs'][1]['p'] if len(base['crumbs']) > 1 else '/'
            return d
        if node is None:
            near = os.path.dirname(path)
            while near and near != '/' and self.lookup(near)[1] is None:
                up = os.path.dirname(near)
                if up == near:
                    break
                near = up
            d = dict(base)
            d.update({'missing': 1, 'near': near})
            return d
        v = self._root_used(r) if node is r.node else None
        top = self._expand(r, node, path, 3500, True, v['used'] if v else None)
        top.update(base)
        top['root'] = r.path
        top['rstate'] = r.state
        if r.scanned_at:
            top['at'] = r.scanned_at
        if r.from_cache:
            top['cached'] = 1
        if node is r.node:
            if r.kind == 'volume':
                top['k'] = 'v'
            if drive:
                top['vol'] = drive
        if path in self.sub_jobs:
            top['st'] = 1
        return top

    def mac_payload(self):
        kids = []
        for v in self.volumes():
            r = self.roots.get(v['p'])
            if r is not None and r.node is not None and r.state in ('scanning', 'done'):
                d = self._expand(r, r.node, v['p'], 1200, False, v.get('used'))
                d['rstate'] = r.state
                if r.scanned_at:
                    d['at'] = r.scanned_at
            else:
                d = {'n': v['n'], 's': v.get('used', 0), 'lv': 'm', 'rstate': 'none'}
            d['n'] = v['n']
            d['k'] = 'v' if v['kind'] == 'volume' else 'd'
            d['p'] = v['p']
            d['vol'] = v
            if v.get('used') and d['s'] < v['used']:
                d['s'] = v['used']
            kids.append(d)
        return {'p': '', 'n': self.display_name(''), 'k': 'r', 'lv': 'm',
                's': sum(k['s'] for k in kids if not k['vol'].get('net')),
                'c': kids, 'crumbs': self.crumbs(''), 'gen': self.gen}

    def request_scan(self, path):
        """Scan a drive, or rescan one folder of a scanned drive. Raises ValueError if it cannot."""
        p = clean_path(path) if path else '/'
        m = self.mounts.get(p)
        if m is not None and m.fstype in SKIP_FS:
            raise ValueError('not a storage volume')
        if p in self.roots or m is not None or self.is_drive(p):
            self.start_scan(p)
            return {'ok': 1}
        res = self.rescan_subtree(p)
        if res != 'ok':
            raise ValueError(res)
        return {'ok': 1}

    def status(self):
        act = []
        now = time.time()
        for r in list(self.roots.values()):
            if r.state == 'scanning':
                s = self.snap(r.node, {})
                a = {'p': r.path, 'n': self.display_name(r.path), 'bytes': s[0], 'files': s[1],
                     'dirs': s[2], 'secs': round(now - r.started, 1)}
                v = self._root_used(r)
                if v:
                    a['used'] = v['used']
                act.append(a)
        for p, t in list(self.sub_jobs.items()):
            act.append({'p': p, 'n': os.path.basename(p), 'sub': 1, 'secs': round(now - t, 1)})
        return {'gen': self.gen, 'active': act, 'loading': 1 if self.loading else 0}

    # ----- details for one item -----

    def info(self, path):
        name = os.path.basename(path) or path
        out = {'p': path, 'n': self.display_name(path) if path == '/' else name}
        m = self.mounts.get(path)
        net = self.net_mount_of(path) is not None
        st = None
        if not net:
            try:
                st = os.lstat(path)
            except OSError:
                out['missing'] = 1
        r, node = self.lookup(path)
        if st is not None:
            is_dir = stat.S_ISDIR(st.st_mode)
        else:
            is_dir = node is not None or net
        is_link = st is not None and stat.S_ISLNK(st.st_mode)
        notes = []
        if is_dir:
            if node is not None:
                s = self.snap(node, {})
                out['size'] = s[0]
                out['files'] = s[1]
                out['dirs'] = s[2]
                if s[3]:
                    out['mt'] = s[3]
                if not s[4]:
                    out['partial'] = 1
                if node.flags & F_DENIED:
                    out['denied'] = 1
                    notes.append('macOS blocked access to this folder, so its size is unknown. To include it, '
                                 'open System Settings > Privacy & Security > Full Disk Access and turn it on for '
                                 'the app that runs Disk Map (the Disk Map app itself, Claude, or your terminal '
                                 'app). Then quit, start it again and rescan.')
                if node.flags & F_CLOUD:
                    notes.append('This folder is in the cloud and not downloaded, so it uses almost no space on this Mac.')
                if node.flags & F_ERR:
                    notes.append('This folder could not be read completely, so its size may be understated.')
        elif st is not None:
            out['size'] = st.st_blocks * 512
            out['lsize'] = st.st_size
            out['mt'] = int(st.st_mtime)
            out['atime'] = int(st.st_atime)
            if IS_MAC and st.st_flags & SF_DATALESS:
                notes.append('This file is in the cloud and not downloaded, so it uses almost no space on this Mac.')
            if st.st_nlink > 1 and stat.S_ISREG(st.st_mode):
                notes.append('This file has %d hard links. The space is only freed when every link is deleted.' % st.st_nlink)
        if st is not None:
            bt = getattr(st, 'st_birthtime', None)
            if bt:
                out['bt'] = int(bt)
        if is_link:
            try:
                target = os.readlink(path)
            except OSError:
                target = '?'
            notes.append('This is a symbolic link pointing to %s. Deleting it removes only the link and frees almost nothing.' % target)
        out['kind'] = kind_label(name, is_dir, is_link)
        if m is not None:
            out['kind'] = ('Network volume' if net else 'Volume') + ' (%s)' % m.fstype
        rule, anchor, direct = find_rule(path, is_dir)
        out['lv'] = rule.lv
        out['title'] = rule.title
        out['why'] = rule.why
        out['how'] = list(rule.how)
        if not direct:
            out['via'] = anchor
            out['via_n'] = self.display_name(anchor) if anchor == '/' else (os.path.basename(anchor) or anchor)
            if rule.strong and rule.lv in (LV_CAUTION, LV_KEEP, LV_REVIEW):
                notes.append('This item is part of "%s". Treat that whole folder as one unit instead of deleting pieces of it.' % out['via_n'])
            elif rule.strong and rule.lv == LV_SAFE:
                notes.append('This item is inside "%s", which can be cleared as a whole.' % out['via_n'])
        if r is not None and node is r.node and not net:
            v = self._root_used(r)
            if v and out.get('size', 0) > v['used'] * 1.02:
                notes.append('The items here add up to more than the drive reports as used. APFS lets copies of a file '
                             'share storage, so some files are counted more than once. Deleting one such copy frees less than its size.')
        if net:
            out['lv'] = LV_MIXED
            out['title'] = 'Network volume'
            out['why'] = ('Files here live on another machine and take no space on this Mac. '
                          'It is not scanned unless you ask, and it never counts toward this Mac\'s totals.')
            out['how'] = []
            out.pop('via', None)
            out.pop('via_n', None)
        mt = out.get('mt')
        if mt and not net and not is_link and rule.lv in (LV_REVIEW, LV_UNKNOWN, LV_CAUTION):
            age = time.time() - mt
            when = datetime.fromtimestamp(mt).strftime('%B %Y')
            what = 'Nothing in here has been modified' if is_dir else 'Not modified'
            if age > 2 * 365 * 86400:
                notes.append('%s since %s. If you have not needed it in that time, it is a strong candidate to archive elsewhere or delete.' % (what, when))
            elif age > 365 * 86400:
                notes.append('%s since %s. Possibly a candidate to archive elsewhere.' % (what, when))
            elif age < 7 * 86400:
                notes.append('Changed within the last week, so it is probably in active use.')
        if IS_MAC and st is not None and (name.lower().endswith('.app') or not is_dir):
            md = self._mdls(path)
            if md.get('used'):
                out['used'] = md['used']
                if name.lower().endswith('.app') and time.time() - md['used'] > 365 * 86400:
                    notes.append('macOS last recorded this app being opened in %s.' % datetime.fromtimestamp(md['used']).strftime('%B %Y'))
            elif name.lower().endswith('.app') and md.get('ok'):
                notes.append('macOS has no record of this app being opened (that record is not always complete).')
            if md.get('kind'):
                out['kind'] = md['kind']
        out['notes'] = notes
        return out

    @staticmethod
    def _mdls(path):
        res = {}
        try:
            p = subprocess.run(['/usr/bin/mdls', '-name', 'kMDItemLastUsedDate', '-name', 'kMDItemKind', path],
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, universal_newlines=True, timeout=2)
        except Exception:
            return res
        if p.returncode != 0:
            return res
        res['ok'] = True
        for line in p.stdout.splitlines():
            m = re.match(r'^(kMDItem\w+)\s*=\s*(.*)$', line.strip())
            if not m or m.group(2) == '(null)':
                continue
            if m.group(1) == 'kMDItemKind':
                res['kind'] = m.group(2).strip('"')
            elif m.group(1) == 'kMDItemLastUsedDate':
                try:
                    res['used'] = int(datetime.strptime(m.group(2), '%Y-%m-%d %H:%M:%S %z').timestamp())
                except ValueError:
                    pass
        return res

    # ----- cache on disk -----

    def _cache_file(self, path):
        return os.path.join(self.cache_dir, hashlib.sha1(path.encode('utf-8', 'surrogateescape')).hexdigest()[:16] + '.json.gz')

    def save_cache(self, r):
        if not self.cache_dir or r.state != 'done':
            return
        def dump(n):
            ch = n.children
            return [n.name, n.flags, n.size, n.files, n.dirs, n.mtime, n.fsize, n.fcount,
                    n.big or 0, [dump(c) for c in ch.values()] if ch else 0]
        try:
            private_dir(self.cache_dir)
            data = {'v': CACHE_V, 'path': r.path, 'kind': r.kind, 'scanned_at': r.scanned_at,
                    'duration': r.duration, 'tree': dump(r.node)}
            raw = json.dumps(data, separators=(',', ':')).encode('ascii')
            fn = self._cache_file(r.path)
            tmp = fn + '.tmp%d' % threading.get_ident()
            drop_stale(tmp)
            with open_private(tmp) as raw_fh, gzip.GzipFile(fileobj=raw_fh, mode='wb', compresslevel=3) as fh:
                fh.write(raw)
            os.replace(tmp, fn)
        except Exception as exc:
            sys.stderr.write('diskmap: could not save cache: %r\n' % (exc,))

    def load_caches(self, wanted):
        """Load saved scans for the given paths. Returns the set of paths loaded."""
        loaded = set()

        def build(a, parent):
            if parent is not None and not ok_name(a[0]):
                raise ValueError('bad name in cache')
            n = Node(a[0], parent)
            n.flags, n.size, n.files, n.dirs, n.mtime, n.fsize, n.fcount = a[1:8]
            n.big = [tuple(b) for b in a[8]] if a[8] else None
            if n.big and not all(ok_name(b[0]) for b in n.big):
                raise ValueError('bad name in cache')
            if a[9]:
                n.children = dict((c[0], build(c, n)) for c in a[9])
            n.state = DONE
            return n

        self.loading = True
        try:
            for path in wanted:
                fn = self._cache_file(path)
                if not os.path.exists(fn):
                    continue
                try:
                    with gzip.open(fn, 'rb') as fh:
                        data = json.loads(fh.read().decode('ascii'))
                    if data.get('v') != CACHE_V or data.get('path') != path:
                        continue
                    r = Root(path, data.get('kind', 'volume'))
                    r.node = build(data['tree'], None)
                    r.scanned_at = data.get('scanned_at', 0)
                    r.duration = data.get('duration', 0)
                    r.from_cache = True
                    sp = vol_space(path, container_level=True) if path in self.mounts else None
                    r.limit = sp[1] if sp else 0
                    r.state = 'done'
                    with self.lock:
                        if path not in self.roots:
                            self.roots[path] = r
                            self.gen += 1
                            loaded.add(path)
                except Exception as exc:
                    sys.stderr.write('diskmap: ignoring unreadable cache for %s: %r\n' % (path, exc))
        finally:
            self.loading = False
        return loaded


# ---------------------------------------------------------------------------
# Local web server
# ---------------------------------------------------------------------------

INDEX_HTML = r'''#__UI__#'''


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    scanner = None
    token = ''
    port = 0

    def log_message(self, fmt, *args):
        pass

    def _token_ok(self):
        try:
            return secrets.compare_digest(self.headers.get('X-Diskmap-Token', '').encode('utf-8'), self.token.encode('utf-8'))
        except Exception:
            return False

    def _host_ok(self):
        host = self.headers.get('Host', '')
        return host in ('127.0.0.1:%d' % self.port, 'localhost:%d' % self.port)

    def _send(self, code, body, ctype='application/json'):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, separators=(',', ':')).encode('ascii')
        elif isinstance(body, str):
            body = body.encode('utf-8')
        headers = [('Content-Type', ctype), ('Cache-Control', 'no-store'),
                   ('X-Content-Type-Options', 'nosniff')]
        if len(body) > 1500 and 'gzip' in self.headers.get('Accept-Encoding', ''):
            body = gzip.compress(body, 1)
            headers.append(('Content-Encoding', 'gzip'))
        self.send_response(code)
        for k, v in headers:
            self.send_header(k, v)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _path_arg(self, q):
        p = q.get('path', [''])[0]
        if p == '':
            return ''
        if not p.startswith('/') or '\x00' in p:
            return None
        return clean_path(p)

    def do_GET(self):
        if not self._host_ok():
            return self._send(403, {'error': 'bad host'})
        u = urlparse(self.path)
        if u.path in ('/', '/index.html'):
            key = parse_qs(u.query).get('t', [''])[0]
            try:
                key_ok = secrets.compare_digest(key.encode('utf-8'), self.token.encode('utf-8'))
            except Exception:
                key_ok = False
            if not key_ok:
                return self._send(403, '<!doctype html><meta charset="utf-8"><title>Disk Map</title>'
                                       '<p style="font:15px system-ui;margin:3em">Open Disk Map with the full link '
                                       'that diskmap printed in your terminal (it includes a private key).</p>',
                                  'text/html; charset=utf-8')
            html = INDEX_HTML
            dev = os.environ.get('DISKMAP_UI')
            if dev:
                with open(dev, encoding='utf-8') as fh:
                    html = fh.read()
            html = html.replace('__TOKEN__', self.token).replace('__IS_MAC__', '1' if IS_MAC else '0')
            return self._send(200, html, 'text/html; charset=utf-8')
        if not u.path.startswith('/api/'):
            return self._send(404, {'error': 'not found'})
        if not self._token_ok():
            return self._send(403, {'error': 'bad token'})
        q = parse_qs(u.query, keep_blank_values=True, errors='surrogatepass')
        sc = self.scanner
        try:
            if u.path == '/api/status':
                return self._send(200, sc.status())
            path = self._path_arg(q)
            if path is None:
                return self._send(400, {'error': 'bad path'})
            if u.path == '/api/tree':
                return self._send(200, sc.tree_payload(path))
            if u.path == '/api/info':
                return self._send(200, sc.info(path))
        except Exception as exc:
            return self._send(500, {'error': repr(exc)})
        return self._send(404, {'error': 'not found'})

    def do_POST(self):
        if not self._host_ok():
            return self._send(403, {'error': 'bad host'})
        if not self._token_ok():
            return self._send(403, {'error': 'bad token'})
        try:
            n = int(self.headers.get('Content-Length', '0'))
            body = json.loads(self.rfile.read(n).decode('utf-8')) if 0 < n < 65536 else {}
            p = body.get('path', '')
            if not isinstance(p, str) or (p != '' and not p.startswith('/')) or '\x00' in p:
                return self._send(400, {'error': 'bad path'})
            p = clean_path(p) if p else '/'
            sc = self.scanner
            if self.path == '/api/scan':
                try:
                    return self._send(200, sc.request_scan(p))
                except ValueError as exc:
                    return self._send(409, {'error': str(exc)})
            if self.path == '/api/reveal':
                if not IS_MAC:
                    return self._send(400, {'error': 'Reveal in Finder only works on macOS'})
                if self.scanner.net_mount_of(p) is None and not os.path.lexists(p):
                    return self._send(404, {'error': 'That item no longer exists'})
                subprocess.Popen(['/usr/bin/open', '-R', p], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return self._send(200, {'ok': 1})
        except Exception as exc:
            return self._send(500, {'error': repr(exc)})
        return self._send(404, {'error': 'not found'})


def serve_stdio(scanner):
    """Serve the scanner over stdin/stdout, one JSON message per line. Used when another
    program (the Disk Map desktop app) runs this script as its engine. Ends when stdin closes."""
    out = sys.stdout.buffer
    sys.stdout = sys.stderr      # stray prints must not corrupt the message stream
    wlock = threading.Lock()

    def send(obj):
        data = (json.dumps(obj, separators=(',', ':')) + '\n').encode('ascii')
        with wlock:
            try:
                out.write(data)
                out.flush()
            except (OSError, ValueError):
                os._exit(0)      # the reader is gone

    def handle(req):
        rid = req.get('id')
        try:
            method = req.get('m')
            p = req.get('path', '')
            if not isinstance(p, str) or (p != '' and not p.startswith('/')) or '\x00' in p:
                raise ValueError('bad path')
            if p:
                p = clean_path(p)
            if method == 'status':
                res = scanner.status()
            elif method == 'tree':
                res = scanner.tree_payload(p)
            elif method == 'info':
                res = scanner.info(p)
            elif method == 'scan':
                res = scanner.request_scan(p)
            else:
                raise ValueError('unknown request')
            send({'id': rid, 'r': res})
        except Exception as exc:
            send({'id': rid, 'e': str(exc) or repr(exc)})

    pool = ThreadPoolExecutor(max_workers=4)
    send({'ready': 1, 'version': VERSION, 'mac': 1 if IS_MAC else 0})
    stdin = sys.stdin.buffer
    while True:
        line = stdin.readline()
        if not line:
            break
        try:
            req = json.loads(line.decode('ascii', 'replace'))
        except ValueError:
            continue
        if isinstance(req, dict):
            pool.submit(handle, req)


def state_dir():
    home = os.path.expanduser('~')
    return os.path.join(home, 'Library', 'Caches', 'diskmap') if IS_MAC else os.path.join(home, '.cache', 'diskmap')


def running_instance(state_file):
    """Link to a copy already running in app mode, or None."""
    try:
        with open(state_file) as fh:
            st = json.load(fh)
        req = Request('http://127.0.0.1:%d/api/status' % int(st['port']), headers={'X-Diskmap-Token': st['token']})
        with build_opener(ProxyHandler({})).open(req, timeout=2) as resp:
            if resp.getcode() == 200:
                return st['url']
    except Exception:
        pass
    return None


INSTALL_MARKER = 'diskmap-installed'

# Runs a script only if its bytes still match the SHA-256 taken when it was written, reading the
# file once so it cannot be swapped between the check and the run. The page has a copy (ui.html).
LOADER = ("import hashlib,sys;p,h=sys.argv[1:3];s=open(p,'rb').read();"
          "hashlib.sha256(s).hexdigest()==h or sys.exit('diskmap: '+p+' changed after Disk Map wrote it, so it was not run.');"
          "sys.argv=[p]+sys.argv[3:];exec(compile(s,p,'exec'),{'__name__':'__main__','__file__':p})")


def applescript_string(text):
    return '"' + text.replace('\\', '\\\\').replace('"', '\\"') + '"'


def install_app(dest_arg):
    """Build a small macOS app that starts diskmap, shows in the Dock and quits like any app."""
    if not IS_MAC:
        sys.exit('diskmap: --install-app only works on macOS')
    home = os.path.expanduser('~')
    support = os.path.join(home, 'Library', 'Application Support', APP_NAME)
    private_dir(support)
    src = os.path.abspath(__file__)
    script = os.path.join(support, 'diskmap.py')
    with open(src, 'rb') as fh:
        code = fh.read()
    if os.path.realpath(src) != os.path.realpath(script):
        drop_stale(script)      # also removes a link planted there, rather than writing through it
        with open_private(script) as fh:
            fh.write(code)
    digest = hashlib.sha256(code).hexdigest()
    if dest_arg:
        dest_dir = os.path.abspath(os.path.expanduser(dest_arg))
    elif os.access('/Applications', os.W_OK):
        dest_dir = '/Applications'
    else:
        dest_dir = os.path.join(home, 'Applications')
    os.makedirs(dest_dir, exist_ok=True)
    app = os.path.join(dest_dir, APP_NAME + '.app')
    record = os.path.join(support, 'installed.json')
    try:
        with open(record) as fh:
            mine = json.load(fh)
    except Exception:
        mine = []
    marker = os.path.join(app, 'Contents', 'Resources', INSTALL_MARKER)
    if os.path.lexists(app):
        # installed.json can be edited by any program, so also require the marker inside the app.
        if app not in mine or os.path.islink(app) or not os.path.isfile(marker) or os.path.islink(marker):
            sys.exit('diskmap: %s already exists and was not made by diskmap. Move it away first, '
                     'or pass another folder: --install-app ~/SomeFolder' % app)
        shutil.rmtree(app)      # replace the app this command built earlier
    # Apple's python3 lives where only an admin can write; a Homebrew one does not.
    apple_py = any(os.path.exists(p) for p in (
        '/Library/Developer/CommandLineTools/usr/bin/python3',
        '/Applications/Xcode.app/Contents/Developer/usr/bin/python3'))
    py_path = '/usr/bin/python3' if apple_py else (sys.executable or '/usr/bin/python3')
    lines = [
        'property pyPath : ' + applescript_string(py_path),
        'property mapScript : ' + applescript_string(script),
        'property mapHash : ' + applescript_string(digest),
        'property loader : ' + applescript_string(LOADER),
        'on launchMap()',
        'set py to pyPath',
        'try',
        'do shell script "test -x " & quoted form of py',
        'on error',
        'set py to "/usr/bin/python3"',
        'end try',
        'do shell script (quoted form of py) & " -I -c " & (quoted form of loader) & " " & (quoted form of mapScript) & " " & mapHash & " --app --parent $PPID > /dev/null 2>&1 &"',
        'end launchMap',
        'on run',
        'launchMap()',
        'end run',
        'on reopen',
        'launchMap()',
        'end reopen',
    ]
    cmd = ['/usr/bin/osacompile', '-s', '-o', app]
    for line in lines:
        cmd += ['-e', line]
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
    except OSError as exc:
        sys.exit('diskmap: could not run osacompile: %s' % exc)
    if p.returncode != 0 or not os.path.isdir(app):
        sys.exit('diskmap: could not build the app:\n%s' % (p.stderr or p.stdout))
    drop_stale(marker)
    with open_private(marker) as fh:
        fh.write(app.encode('utf-8', 'surrogateescape'))
    if app not in mine:
        mine.append(app)
    tmp = record + '.tmp'
    drop_stale(tmp)
    with open_private(tmp) as fh:
        fh.write(json.dumps(mine).encode('ascii'))
    os.replace(tmp, record)
    print('Installed %s' % app)
    print('Open it from Spotlight, Launchpad or the Applications folder. It stays in the Dock while it')
    print('runs. Click the Dock icon to bring the map back, and quit it like any other app.')
    print('macOS will ask for folder access under the name "%s". For a complete scan, add it under' % APP_NAME)
    print('System Settings > Privacy & Security > Full Disk Access.')
    print('The app runs its own copy of this script (%s).' % script)
    print('To update it, run --install-app again from the newer diskmap.py.')


def main():
    ap = argparse.ArgumentParser(description='Interactive map of where your storage goes. Read-only: it never deletes or changes files.')
    ap.add_argument('folders', nargs='*', help='extra folders to show as their own entries next to the drives')
    ap.add_argument('--port', type=int, default=8765, help='port for the local page (default 8765)')
    ap.add_argument('--no-browser', action='store_true', help='do not open the browser automatically')
    ap.add_argument('--no-autoscan', action='store_true', help='do not start scanning until you click a drive')
    ap.add_argument('--fresh', action='store_true', help='ignore saved scans and start over')
    ap.add_argument('--no-cache', action='store_true', help='do not read or write saved scans')
    ap.add_argument('--workers', type=int, default=0, help='scan threads (default: based on CPU count)')
    ap.add_argument('--install-app', nargs='?', const='', default=None, metavar='FOLDER',
                    help='macOS: create a "Disk Map" app (in /Applications unless a folder is given), then exit')
    ap.add_argument('--stdio', action='store_true', help=argparse.SUPPRESS)     # engine for the desktop app
    ap.add_argument('--app', action='store_true', help=argparse.SUPPRESS)       # started by the Disk Map app
    ap.add_argument('--parent', type=int, default=0, help=argparse.SUPPRESS)    # stop when this process ends
    args = ap.parse_args()

    if args.install_app is not None:
        install_app(args.install_app)
        return

    state_file = None
    lock_fh = None
    if args.app:
        # Started by the app: log to a file, and never run two copies at once. A second
        # start (clicking the Dock icon again) just shows the map that is already running.
        import fcntl
        sdir = state_dir()
        private_dir(sdir)
        state_file = os.path.join(sdir, 'app.json')
        log_dir = os.path.join(os.path.expanduser('~'), 'Library', 'Logs') if IS_MAC else sdir
        try:
            os.makedirs(log_dir, exist_ok=True)
            sys.stdout = sys.stderr = open(os.path.join(log_dir, 'diskmap.log'), 'a', buffering=1)
        except OSError:
            pass
        lock_fh = open(os.path.join(sdir, 'app.lock'), 'w')
        try:
            fcntl.flock(lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            for _ in range(40):
                url = running_instance(state_file)
                if url:
                    webbrowser.open(url)
                    break
                time.sleep(0.25)
            return

    sys.setrecursionlimit(20000)
    try:
        threading.stack_size(32 * 1024 * 1024)
    except (ValueError, RuntimeError):
        pass

    pinned = []
    for f in args.folders:
        p = os.path.realpath(os.path.expanduser(f))
        if not os.path.isdir(p):
            ap.error('not a folder: %s' % f)
        pinned.append(p)

    home = os.path.expanduser('~')
    cache_dir = None
    if not args.no_cache:
        cache_dir = os.path.join(home, 'Library', 'Caches', 'diskmap') if IS_MAC else os.path.join(home, '.cache', 'diskmap')
    workers = args.workers or max(2, min(6, os.cpu_count() or 4))
    scanner = Scanner(workers, cache_dir, pinned)

    def warm():
        wanted = ['/'] + pinned + [v['p'] for v in scanner.volumes() if v['p'] != '/' and not v.get('net')]
        loaded = set()
        if cache_dir and not args.fresh:
            loaded = scanner.load_caches(wanted)
        if not args.no_autoscan:
            for p in (pinned or ['/']):
                if p not in loaded:
                    try:
                        scanner.start_scan(p)
                    except ValueError as exc:
                        sys.stderr.write('diskmap: %s\n' % exc)

    if args.stdio:
        threading.Thread(target=warm, daemon=True).start()
        try:
            serve_stdio(scanner)
        finally:
            os._exit(0)

    token = secrets.token_urlsafe(24)
    server = None
    for port in [args.port] + list(range(args.port + 1, args.port + 20)) + [0]:
        try:
            server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
            break
        except OSError:
            continue
    if server is None:
        sys.exit('diskmap: could not open a local port')
    server.daemon_threads = True
    port = server.server_address[1]
    Handler.scanner = scanner
    Handler.token = token
    Handler.port = port

    threading.Thread(target=warm, daemon=True).start()
    url = 'http://127.0.0.1:%d/?t=%s' % (port, token)

    def forget_state():
        if state_file:
            try:
                os.remove(state_file)
            except OSError:
                pass

    if state_file:
        tmp = state_file + '.tmp'
        drop_stale(tmp)
        with open_private(tmp) as fh:
            fh.write(json.dumps({'port': port, 'token': token, 'url': url, 'pid': os.getpid()}).encode('ascii'))
        os.replace(tmp, state_file)
    if args.parent:
        def watch_parent():      # the app that started us has quit: stop too
            while True:
                time.sleep(2)
                try:
                    os.kill(args.parent, 0)
                except ProcessLookupError:
                    break
                except OSError:
                    pass
            forget_state()
            os._exit(0)
        threading.Thread(target=watch_parent, daemon=True).start()

    if args.app:
        print('%s diskmap %s started on port %d' % (time.strftime('%Y-%m-%d %H:%M:%S'), VERSION, port))
    else:
        print('diskmap %s is running at %s' % (VERSION, url))
        print('Read-only: nothing is deleted or changed. Press Ctrl+C here to stop.')
    if IS_MAC and not args.app:
        print('If macOS asks whether your terminal may access folders such as Documents or Downloads,')
        print('choose Allow so they are included. For a complete picture, give your terminal app')
        print('Full Disk Access in System Settings > Privacy & Security.')
    if not args.no_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nStopped.')
    finally:
        forget_state()
        server.server_close()
        os._exit(0)


if __name__ == '__main__':
    main()
