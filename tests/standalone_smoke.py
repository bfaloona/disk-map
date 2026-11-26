"""End-to-end check of the standalone script: start it on the test home, drive the page in a browser."""
import os, re, subprocess, sys, time
from urllib.parse import quote
from playwright.sync_api import sync_playwright
from common import DIST, TEST_HOME, launch_args, require, watch

require()
proc = subprocess.Popen([sys.executable, os.path.join(DIST, 'diskmap.py'), TEST_HOME, '--no-browser', '--no-cache', '--port', '8791'],
                        stdout=subprocess.PIPE, universal_newlines=True)
try:
    url = re.search(r'http://127\S+', proc.stdout.readline()).group(0)
    time.sleep(1.5)
    with sync_playwright() as p:
        b = p.chromium.launch(**launch_args())
        pg = b.new_page(viewport={'width': 1440, 'height': 900}); errs = []; watch(pg, errs)
        pg.goto(url + '#' + quote(TEST_HOME, safe='')); pg.wait_for_timeout(1500)
        rows = pg.locator('#contents .row')
        assert rows.count() >= 10, rows.count()
        pg.locator('#contents .row', has_text='Library').first.click(); pg.wait_for_timeout(400)
        assert 'Mixed' in pg.inner_text('#detail .verdict'), pg.inner_text('#detail .verdict')
        pg.locator('#contents li', has_text='.npm').locator('.icon').click(); pg.wait_for_timeout(900)
        assert pg.evaluate('decodeURIComponent(location.hash)').endswith('/.npm')
        pg.locator('#contents .row').first.click(); pg.wait_for_timeout(400)
        assert 'Safe to clear' in pg.inner_text('#detail .verdict')
        pg.click('text=Add to shortlist'); pg.wait_for_timeout(200)
        assert 'Would free about' in pg.inner_text('#shortlist')
        pg.click('#rescan'); pg.wait_for_timeout(1500)
        pg.focus('#map'); pg.keyboard.press('Escape'); pg.wait_for_timeout(800)
        assert pg.evaluate('decodeURIComponent(location.hash)') == '#' + TEST_HOME, pg.evaluate('location.hash')
        pg.goto(url + '#' + quote(TEST_HOME + '/weird', safe='')); pg.wait_for_timeout(1200)
        assert pg.locator('#contents .row').count() >= 4
        assert pg.evaluate('window.__xss') is None, 'file name ran as markup'
        assert not errs, errs
        b.close()
    print('standalone smoke: OK')
finally:
    proc.kill()
