"""Build the two deliverables from src/: dist/diskmap.py (standalone) and dist/app/index.html (artifact page)."""
import json, os, sys
here = os.path.dirname(os.path.abspath(__file__))
def rd(*p): return open(os.path.join(here, *p), encoding='utf-8').read()
core, adv, ui = rd('src', 'core.py'), rd('src', 'advice.py'), rd('src', 'ui.html')
assert core.count('#__ADVICE__#') == 1 and core.count('#__UI__#') == 1
for mark in ('<!--__MANIFEST__-->\n', '#__ENGINE_SRC__#', '#__DEMO__#', "var TOKEN = '__TOKEN__';", "var IS_MAC = '__IS_MAC__' === '1';"):
    assert ui.count(mark) == 1, mark
py = core.replace('#__ADVICE__#', adv)

# 1. standalone script: python3 diskmap.py
web = ui.replace('<!--__MANIFEST__-->\n', '').replace('#__ENGINE_SRC__#', '').replace('#__DEMO__#', 'null')
assert "'''" not in web
out = py.replace('#__UI__#', web)
compile(out, 'diskmap.py', 'exec')
os.makedirs(os.path.join(here, 'dist', 'app'), exist_ok=True)
open(os.path.join(here, 'dist', 'diskmap.py'), 'w', encoding='utf-8').write(out)
print('built dist/diskmap.py', len(out))

# 2. artifact page: the same interface carrying the scanner as its engine
engine = py.replace('#__UI__#', '<!doctype html><title>Disk Map</title><p>This copy of diskmap is the engine of the Disk Map desktop app. It has no page of its own.</p>')
compile(engine, 'engine.py', 'exec')
low = engine.lower()
assert '</script' not in low and '<!--' not in low and '<script' not in low
demo = rd('src', 'demo.json').strip() if os.path.exists(os.path.join(here, 'src', 'demo.json')) else 'null'
json.loads(demo)
page = ui.replace("var TOKEN = '__TOKEN__';", "var TOKEN = '';").replace("var IS_MAC = '__IS_MAC__' === '1';", "var IS_MAC = true;")
page = page.replace('<!--__MANIFEST__-->\n', '<script type="application/json" id="claude-artifacts-manifest">{"permissions": ["full-access"]}</script>\n')
page = page.replace('#__DEMO__#', demo.replace('<', '\\u003c'))
page = page.replace('#__ENGINE_SRC__#', engine)
assert page.startswith('<!doctype html>')
page = '<!DOCTYPE html>' + page[len('<!doctype html>'):]
open(os.path.join(here, 'dist', 'app', 'index.html'), 'w', encoding='utf-8').write(page)
open(os.path.join(here, 'dist', 'app', 'engine.py'), 'w', encoding='utf-8').write(engine)   # for tests only
print('built dist/app/index.html', len(page))
