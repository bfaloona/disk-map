"""The artifact page inside a simulated desktop app: a mock of the `desktop` capability lets the page
write and start the real engine, and bridges the engine's stdin/stdout to the page."""
import asyncio, base64, functools, http.server, json, os, sys, tempfile, threading
from playwright.async_api import async_playwright
from common import DIST, TEST_HOME, launch_args, require

require()
class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


handler = functools.partial(Quiet, directory=os.path.join(DIST, 'app'))
srv = http.server.ThreadingHTTPServer(('127.0.0.1', 8793), handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
HOME = tempfile.mkdtemp()
MOCK = r"""
(() => {
  const procs = {}; let seq = 0;
  window.__onProc = (id, kind, data) => { const p = procs[id]; if (!p) return; (p.l[kind] || []).forEach(f => f(data)); };
  let perm = window.__PERM || 'prompt';
  const log = (window.__calls = []);
  const desktop = {
    install: { state: async () => 'installed', request: async () => 'installed' },
    permissions: {
      state: async (n) => n ? perm : { 'full-access': perm },
      request: async () => { perm = 'granted'; log.push('perm.request'); return { 'full-access': perm }; },
      manage: async () => {} },
    window: { getOptions: async () => ({ options: window.__WOPT || {}, applied: {} }),
              setOptions: async (o) => { log.push('setOptions ' + JSON.stringify(o)); window.__WOPT = o; return { applied: 'now', reloading: false, options: o }; } },
    app: { dock: { setIcon: async (u) => { window.__icon = u; return { written: true }; } } },
    os: { platform: async () => 'darwin', homedir: async () => window.__HOME },
    fs: { mkdir: (p, o) => window.__fs('mkdir', p, ''), writeFile: (p, d) => window.__fs('write', p, d), exists: (p) => window.__fs('exists', p, '') },
    shell: { showItemInFolder: async (p) => { log.push('reveal ' + p); } },
    childProcess: { spawn: (cmd, args) => {
      const id = ++seq; const l = { out: [], err: [], exit: [], error: [] }; procs[id] = { l };
      log.push('spawn ' + cmd + ' ' + args.join(' '));
      const started = window.__spawn(id, cmd, args);
      return { pid: started, stdout: { on: (e, f) => l.out.push(f) }, stderr: { on: (e, f) => l.err.push(f) },
               stdin: { write: (d) => started.then(() => window.__stdin(id, d)), end: async () => {} },
               on: (e, f) => l[e === 'close' ? 'exit' : e].push(f), kill: () => window.__kill(id) };
    } }
  };
  window.claude = { use: async (name) => name === 'desktop' ? desktop : null };
})();
"""
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(**launch_args())
        ctx = await b.new_context(viewport={'width': 1280, 'height': 820})
        pg = await ctx.new_page(); errs = []; procs = {}
        pg.on('console', lambda m: errs.append(m.type + ': ' + m.text) if m.type in ('error', 'warning') else None)
        pg.on('pageerror', lambda e: errs.append('pageerror: ' + str(e)))
        async def fs(op, path, data):
            if op == 'mkdir': os.makedirs(path, exist_ok=True); return None
            if op == 'write': open(path, 'w', encoding='utf-8').write(data); return None
            if op == 'exists': return path == '/usr/bin/python3' and os.path.exists('/usr/bin/python3') or path == FAKEPY
        async def pump(id, stream, kind):
            while True:
                chunk = await stream.read(777)          # odd chunk size: messages arrive split
                if not chunk: break
                await pg.evaluate('([i,k,d]) => window.__onProc(i,k,d)', [id, kind, chunk.decode('utf-8', 'replace')])
        async def spawn(id, cmd, args):
            real = sys.executable if cmd == FAKEPY else cmd
            pr = await asyncio.create_subprocess_exec(real, *args, *EXTRA, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            procs[id] = pr
            asyncio.ensure_future(pump(id, pr.stdout, 'out')); asyncio.ensure_future(pump(id, pr.stderr, 'err'))
            async def waiter():
                code = await pr.wait(); await asyncio.sleep(0.2)
                try: await pg.evaluate('([i,c]) => window.__onProc(i,"exit",c)', [id, code])
                except Exception: pass
            asyncio.ensure_future(waiter()); return pr.pid
        async def stdin(id, data): procs[id].stdin.write(data.encode()); await procs[id].stdin.drain()
        async def kill(id): procs[id].terminate()
        for name, fn in (('__fs', fs), ('__spawn', spawn), ('__stdin', stdin), ('__kill', kill)): await pg.expose_function(name, fn)
        await pg.add_init_script('window.__HOME = %s;' % json.dumps(HOME) + MOCK)
        await pg.goto('http://127.0.0.1:8793/index.html'); await pg.wait_for_timeout(800)
        assert await pg.inner_text('#gate-title') == 'Let Disk Map read your drives'
        await pg.click('#gate-actions button'); await pg.wait_for_timeout(3500)
        assert await pg.evaluate("getComputedStyle(document.getElementById('gate')).display") == 'none'
        assert os.listdir(os.path.join(HOME, 'Library/Application Support/Disk Map')) == ['engine.py']
        calls = await pg.evaluate('window.__calls')
        assert any(c.startswith('spawn ' + FAKEPY + ' -u ') and c.endswith('--stdio') for c in calls), calls
        name = os.path.basename(TEST_HOME)
        await pg.locator('#contents li', has_text=name).locator('.icon').click(); await pg.wait_for_timeout(1200)
        if await pg.locator('#ov-actions button').count():      # not scanned yet: start the scan
            await pg.click('#ov-actions button'); await pg.wait_for_timeout(2500)
        assert await pg.locator('#contents .row').count() >= 10
        await pg.locator('#contents .row', has_text='.npm').first.click(); await pg.wait_for_timeout(500)
        assert 'Safe to clear' in await pg.inner_text('#detail .verdict')
        await pg.click('#rescan'); await pg.wait_for_timeout(1500)
        icon = await pg.evaluate('window.__icon'); assert len(base64.b64decode(icon.split(',')[1])) > 1000
        list(procs.values())[-1].kill(); await pg.wait_for_timeout(1200)       # the engine dies
        assert await pg.inner_text('#gate-title') == 'The scanner stopped'
        await pg.click('#gate-actions button'); await pg.wait_for_timeout(2500)  # and is restarted
        assert await pg.evaluate("getComputedStyle(document.getElementById('gate')).display") == 'none'
        assert not errs, errs
        print('app mode smoke: OK')
        for pr in procs.values():
            try: pr.kill()
            except Exception: pass
        await b.close()
FAKEPY = '/opt/homebrew/bin/python3'
EXTRA = ['--no-cache', TEST_HOME]
asyncio.run(main())
