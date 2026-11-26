"""The two ways the page talks to the scanner: the local web server (token and Host checks)
and the stdio engine used by the desktop app (one ASCII JSON message per line).

Only temp folders are ever scanned. A request with an empty path means "/" (the whole disk),
so these tests never send one with a valid token.
"""
import hashlib
import http.client
import re
import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock
from urllib.parse import quote

from loader import ENGINE, PAGE, diskmap

dm = diskmap()
NAME = 'café ☃.bin'       # non-ASCII file name


def fixture():
    tmp = os.path.realpath(tempfile.mkdtemp(prefix='diskmap-test-'))    # diskmap pins folders by real path
    root = os.path.join(tmp, 'root')
    os.makedirs(os.path.join(root, 'sub'))
    with open(os.path.join(root, 'sub', NAME), 'wb') as fh:
        fh.write(b'x' * 50000)
    return tmp, root


class HttpTest(unittest.TestCase):
    TOKEN = 'test-token-123'

    @classmethod
    def setUpClass(cls):
        cls.tmp, cls.root = fixture()
        cls.patches = [mock.patch.object(dm, 'read_mounts', lambda: {'/': dm.Mount('/', '/dev/disk9s1', 'apfs', True, True)}),
                       mock.patch.object(dm.Scanner, '_mdls', staticmethod(lambda p: {}))]
        for p in cls.patches:
            p.start()
        cls.scanner = dm.Scanner(2, None, [cls.root])

        class H(dm.Handler):
            pass
        cls.server = dm.ThreadingHTTPServer(('127.0.0.1', 0), H)
        cls.server.daemon_threads = True
        cls.port = cls.server.server_address[1]
        H.scanner, H.token, H.port = cls.scanner, cls.TOKEN, cls.port
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.scanner.pool.shutdown(True)
        for p in cls.patches:
            p.stop()
        shutil.rmtree(cls.tmp)

    def request(self, method, path, body=None, token=TOKEN, host=None, headers=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10)     # new connection each time
        h = {'Host': host or '127.0.0.1:%d' % self.port}
        if token is not None:
            h['X-Diskmap-Token'] = token
        if body is not None:
            body = json.dumps(body)
            h['Content-Type'] = 'application/json'
        h.update(headers or {})
        conn.request(method, path, body=body, headers=h)
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        return resp, data

    def api(self, path, **kw):
        resp, data = self.request('GET', path, **kw)
        return resp.status, (json.loads(data.decode('ascii')) if data else None)

    def scan_root(self):
        resp, data = self.request('POST', '/api/scan', {'path': self.root})
        self.assertEqual(resp.status, 200, data)
        end = time.time() + 20
        while self.scanner.roots[self.root].state != 'done':
            self.assertLess(time.time(), end)
            time.sleep(0.02)

    # ----- the page -----

    def test_page_needs_the_key(self):
        for q in ('/', '/?t=', '/?t=wrong', '/index.html?t=test-token-12'):
            resp, data = self.request('GET', q, token=None)
            self.assertEqual(resp.status, 403, q)
            self.assertNotIn(self.TOKEN.encode(), data)

    def test_page_with_key_gets_token_filled_in(self):
        resp, data = self.request('GET', '/?t=' + self.TOKEN, token=None)
        self.assertEqual(resp.status, 200)
        html = data.decode('utf-8')
        self.assertIn("var TOKEN = '%s';" % self.TOKEN, html)
        self.assertNotIn('__TOKEN__', html)
        self.assertNotIn('__IS_MAC__', html)
        self.assertEqual(resp.getheader('Cache-Control'), 'no-store')

    def test_foreign_host_is_refused(self):
        # A page on another site that rebinds its DNS name to 127.0.0.1 sends its own Host header.
        for host in ('evil.example:%d' % self.port, '127.0.0.1', '127.0.0.1:1', 'localhost.evil.example:%d' % self.port):
            resp, _ = self.request('GET', '/?t=' + self.TOKEN, token=None, host=host)
            self.assertEqual(resp.status, 403, host)
            status, body = self.api('/api/status', host=host)
            self.assertEqual(status, 403, host)
            resp, _ = self.request('POST', '/api/scan', {'path': self.root}, host=host)
            self.assertEqual(resp.status, 403, host)
        resp, _ = self.request('GET', '/?t=' + self.TOKEN, token=None, host='localhost:%d' % self.port)
        self.assertEqual(resp.status, 200)

    # ----- the API -----

    def test_api_needs_the_token(self):
        for tok in (None, '', 'wrong', self.TOKEN + 'x', self.TOKEN.upper()):
            status, body = self.api('/api/status', token=tok)
            self.assertEqual(status, 403, tok)
            resp, _ = self.request('POST', '/api/scan', {'path': self.root}, token=tok)
            self.assertEqual(resp.status, 403, tok)
            resp, _ = self.request('POST', '/api/reveal', {'path': self.root}, token=tok)
            self.assertEqual(resp.status, 403, tok)
        status, body = self.api('/api/status')
        self.assertEqual(status, 200)
        self.assertIn('active', body)

    def test_bad_paths_are_rejected(self):
        for p in ('relative/path', 'x', quote('/tmp/\x00evil')):
            status, _ = self.api('/api/tree?path=' + p)
            self.assertEqual(status, 400, p)
            status, _ = self.api('/api/info?path=' + p)
            self.assertEqual(status, 400, p)
        for p in ('relative', '/a\x00b', 5, ['/']):
            resp, _ = self.request('POST', '/api/scan', {'path': p})
            self.assertEqual(resp.status, 400, p)

    def test_unknown_routes(self):
        self.assertEqual(self.api('/api/nope')[0], 404)
        self.assertEqual(self.api('/elsewhere')[0], 404)
        resp, _ = self.request('POST', '/api/nope', {'path': self.root})
        self.assertEqual(resp.status, 404)

    def test_scan_tree_and_info_are_ascii_json(self):
        self.scan_root()
        resp, data = self.request('GET', '/api/tree?path=' + quote(self.root + '/sub'))
        self.assertEqual(resp.status, 200)
        self.assertTrue(all(b < 128 for b in data))
        tree = json.loads(data.decode('ascii'))
        self.assertIn(NAME, [c['n'] for c in tree.get('c', [])])
        resp, data = self.request('GET', '/api/info?path=' + quote(self.root + '/sub/' + NAME))
        self.assertEqual(resp.status, 200)
        self.assertTrue(all(b < 128 for b in data))
        self.assertEqual(json.loads(data.decode('ascii'))['n'], NAME)

    def test_large_replies_are_gzipped_on_request(self):
        resp, data = self.request('GET', '/?t=' + self.TOKEN, token=None, headers={'Accept-Encoding': 'gzip'})
        self.assertEqual(resp.getheader('Content-Encoding'), 'gzip')
        self.assertEqual(int(resp.getheader('Content-Length')), len(data))

    def test_reveal(self):
        with mock.patch.object(dm.subprocess, 'Popen') as popen:
            resp, data = self.request('POST', '/api/reveal', {'path': self.root + '/sub/' + NAME})
            if dm.IS_MAC:
                self.assertEqual(resp.status, 200, data)
                self.assertEqual(popen.call_args[0][0], ['/usr/bin/open', '-R', self.root + '/sub/' + NAME])
                resp, _ = self.request('POST', '/api/reveal', {'path': self.root + '/missing'})
                self.assertEqual(resp.status, 404)
            else:
                self.assertEqual(resp.status, 400)
            self.assertEqual(popen.call_count, 1 if dm.IS_MAC else 0)


class StdioTest(unittest.TestCase):
    """Runs the desktop app's engine (dist/app/engine.py) as a child process."""

    def setUp(self):
        self.tmp, self.root = fixture()
        home = os.path.join(self.tmp, 'home')
        os.makedirs(home)
        env = dict(os.environ, HOME=home)
        # Started the way the desktop app starts it: isolated, through the hash-checking loader.
        with open(ENGINE, 'rb') as fh:
            digest = hashlib.sha256(fh.read()).hexdigest()
        self.proc = subprocess.Popen([sys.executable, '-I', '-u', '-c', dm.LOADER, ENGINE, digest,
                                      '--stdio', '--no-cache', '--no-autoscan', self.root],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        self.lines = queue.Queue()
        self.raw = []

        def reader():
            for line in iter(self.proc.stdout.readline, b''):
                self.raw.append(line)
                self.lines.put(line)
        threading.Thread(target=reader, daemon=True).start()
        self.seq = 0

    def tearDown(self):
        if self.proc.poll() is None:
            self.proc.kill()
        self.proc.wait()
        self.proc.stdout.close()
        self.proc.stderr.close()
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        shutil.rmtree(self.tmp)
        for line in self.raw:
            self.assertTrue(all(b < 128 for b in line), line)
            self.assertTrue(line.endswith(b'\n'))

    def next_msg(self, timeout=15):
        return json.loads(self.lines.get(timeout=timeout).decode('ascii'))

    def send_raw(self, data):
        self.proc.stdin.write(data)
        self.proc.stdin.flush()

    def call(self, m, path=''):
        self.seq += 1
        rid = self.seq
        self.send_raw((json.dumps({'id': rid, 'm': m, 'path': path}) + '\n').encode('ascii'))
        while True:
            msg = self.next_msg()
            if msg.get('id') == rid:
                return msg

    def test_protocol(self):
        ready = self.next_msg()
        self.assertEqual(ready.get('ready'), 1)
        self.assertIn('version', ready)

        # Garbage lines are skipped and the engine keeps answering.
        self.send_raw(b'not json\n[1,2]\n"str"\n\n')
        self.assertIn('active', self.call('status')['r'])

        self.assertEqual(self.call('nope', self.root)['e'], 'unknown request')
        self.assertEqual(self.call('info', 'relative')['e'], 'bad path')
        self.assertEqual(self.call('info', '/a\x00b')['e'], 'bad path')

        self.assertEqual(self.call('scan', self.root)['r'], {'ok': 1})
        end = time.time() + 20
        while self.call('status')['r']['active']:
            self.assertLess(time.time(), end)
            time.sleep(0.05)
        tree = self.call('tree', self.root + '/sub')['r']
        self.assertIn(NAME, [c['n'] for c in tree.get('c', [])])
        info = self.call('info', self.root + '/sub/' + NAME)['r']     # json.dumps escapes the name to ASCII
        self.assertEqual(info['n'], NAME)
        self.assertGreater(info['size'], 0)

    def test_replies_can_arrive_out_of_order_but_match_ids(self):
        self.next_msg()
        reqs = b''.join((json.dumps({'id': i, 'm': 'status'}) + '\n').encode('ascii') for i in range(1, 21))
        self.send_raw(reqs)
        ids = sorted(self.next_msg()['id'] for _ in range(20))
        self.assertEqual(ids, list(range(1, 21)))

    def test_engine_exits_when_stdin_closes(self):
        self.next_msg()
        self.proc.stdin.close()
        self.assertEqual(self.proc.wait(timeout=10), 0)



class LoaderTest(unittest.TestCase):
    def test_changed_engine_does_not_run(self):
        p = subprocess.run([sys.executable, '-I', '-c', dm.LOADER, ENGINE, '0' * 64, '--stdio'],
                           stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn(b'so it was not run', p.stderr)
        self.assertNotIn(b'ready', p.stdout)

    def test_page_and_script_use_the_same_loader(self):
        with open(PAGE, encoding='utf-8') as fh:
            page = fh.read()
        m = re.search(r'var LOADER = ((?:"[^"]*"\s*\+?\s*)+);', page)
        self.assertIsNotNone(m)
        js = ''.join(re.findall(r'"([^"]*)"', m.group(1)))
        self.assertEqual(js, dm.LOADER)


if __name__ == '__main__':
    unittest.main()
