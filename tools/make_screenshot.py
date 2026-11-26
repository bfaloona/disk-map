#!/usr/bin/env python3
"""Write docs/screenshot.png: the interface on the example data (src/demo.json).

Needs Playwright (requirements-dev.txt) and `python3 build.py` first. Set CHROME to use a
specific browser. Usage: python3 tools/make_screenshot.py [--dark]
"""
import functools
import http.server
import os
import subprocess
import sys
import threading

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, 'dist', 'app')


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def main():
    if not os.path.exists(os.path.join(APP, 'index.html')):
        sys.exit('Run python3 build.py first.')
    # A screenshot is an image, so the commit hooks cannot read it. Check the data it shows.
    check = subprocess.run([sys.executable, os.path.join(ROOT, 'tools', 'check_private.py'),
                            os.path.join(ROOT, 'src', 'demo.json')])
    if check.returncode:
        sys.exit('src/demo.json holds personal data; fix it before taking a screenshot.')
    dark = '--dark' in sys.argv
    out = os.path.join(ROOT, 'docs', 'screenshot-dark.png' if dark else 'screenshot.png')
    srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Quiet, directory=APP))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    chrome = os.environ.get('CHROME')
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=chrome) if chrome else p.chromium.launch()
        pg = b.new_page(viewport={'width': 1280, 'height': 800}, device_scale_factor=2,
                        color_scheme='dark' if dark else 'light')
        pg.goto('http://127.0.0.1:%d/index.html' % srv.server_address[1])
        pg.wait_for_timeout(900)
        # Select the largest folder so the detail panel shows advice.
        pg.locator('#contents .row').first.click()
        pg.wait_for_timeout(400)
        pg.screenshot(path=out)
        b.close()
    srv.shutdown()
    print(out)


if __name__ == '__main__':
    main()
