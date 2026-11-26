"""Shared helpers for the smoke tests (Playwright + a Chromium-family browser)."""
import os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, 'dist')
TEST_HOME = os.environ.get('DISKMAP_TEST_HOME', '/home/tester')


def require():
    if not os.path.exists(os.path.join(DIST, 'diskmap.py')):
        sys.exit('Run python3 build.py first.')
    if not os.path.isdir(os.path.join(TEST_HOME, 'Library')):
        sys.exit('No test home at %s. Create one: python3 tests/make_test_home.py %s' % (TEST_HOME, TEST_HOME))


def launch_args():
    chrome = os.environ.get('CHROME')
    if not chrome and os.path.exists('/usr/bin/google-chrome'):
        chrome = '/usr/bin/google-chrome'
    return {'executable_path': chrome, 'args': ['--no-sandbox']} if chrome else {}


def watch(page, errs):
    page.on('console', lambda m: errs.append(m.type + ': ' + m.text) if m.type in ('error', 'warning') else None)
    page.on('pageerror', lambda e: errs.append('pageerror: ' + str(e)))
