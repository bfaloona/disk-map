"""The artifact page outside the installed app: example data, install banner, no scanning."""
import functools, http.server, os, threading
from playwright.sync_api import sync_playwright
from common import DIST, launch_args, watch

class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


handler = functools.partial(Quiet, directory=os.path.join(DIST, 'app'))
srv = http.server.ThreadingHTTPServer(('127.0.0.1', 8792), handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
INSTALLABLE = "window.claude={use:async(n)=>n==='desktop'?{install:{state:async()=>'available',request:async()=>{window.__req=1;return 'installed'}}}:null};"
with sync_playwright() as p:
    b = p.chromium.launch(**launch_args())
    for init in ('', INSTALLABLE):
        pg = b.new_page(viewport={'width': 1100, 'height': 760}); errs = []; watch(pg, errs)
        if init:
            pg.add_init_script(init)
        pg.goto('http://127.0.0.1:8792/index.html'); pg.wait_for_timeout(900)
        assert 'example data' in pg.inner_text('#banner')
        assert pg.inner_text('#crumbs').strip() == 'Example home folder'
        assert pg.is_disabled('#rescan')
        if init:
            pg.click('text=Install as app'); assert pg.evaluate('window.__req') == 1
        pg.locator('#contents li', has_text='Library').locator('.icon').click(); pg.wait_for_timeout(800)
        pg.locator('#contents .row').first.click(); pg.wait_for_timeout(300)
        assert 'example data' in pg.inner_text('#detail')
        assert pg.locator('text=Reveal in Finder').count() == 0
        assert not errs, errs
        pg.close()
    b.close()
print('demo smoke: OK')
