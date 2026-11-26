"""The build: what it writes, and that its safety assertions stop a bad build.

Plus a static check of ui.html: file names must reach the page as text, never as markup.
"""
import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from loader import ENGINE, PAGE, ROOT, SCRIPT, build

build()


def read(path):
    with open(path, encoding='utf-8') as fh:
        return fh.read()


class OutputTest(unittest.TestCase):
    def test_python_parses_as_3_8(self):
        for path in (SCRIPT, ENGINE):
            ast.parse(read(path), path, feature_version=(3, 8))

    def test_no_match_statements_or_new_syntax(self):
        tree = ast.parse(read(SCRIPT))
        bad = [type(n).__name__ for n in ast.walk(tree)
               if type(n).__name__ in ('Match', 'TryStar', 'TypeAlias')]
        self.assertEqual(bad, [])

    def test_standalone_keeps_placeholders_for_the_server(self):
        src = read(SCRIPT)
        self.assertIn("var TOKEN = '__TOKEN__';", src)
        self.assertNotIn('#__ADVICE__#', src)
        self.assertNotIn('#__ENGINE_SRC__#', src)
        self.assertNotIn('#__DEMO__#', src)
        self.assertNotIn('__MANIFEST__', src)

    def test_artifact_page(self):
        page = read(PAGE)
        self.assertTrue(page.startswith('<!DOCTYPE html>'))
        self.assertIn("var TOKEN = '';", page)
        self.assertIn('var IS_MAC = true;', page)
        ui_only = page.replace(read(ENGINE), '')       # the engine itself mentions the placeholders
        for mark in ('__TOKEN__', '__IS_MAC__', '#__ENGINE_SRC__#', '#__DEMO__#', '__MANIFEST__'):
            self.assertFalse(mark in ui_only, mark)
        m = re.search(r'<script type="application/json" id="claude-artifacts-manifest">(.*?)</script>', page)
        self.assertEqual(json.loads(m.group(1)), {'permissions': ['full-access']})

    def test_engine_is_embedded_verbatim(self):
        engine = read(ENGINE)
        self.assertIn(engine, read(PAGE))
        low = engine.lower()
        for bad in ('</script', '<script', '<!--'):
            self.assertNotIn(bad, low)

    def test_demo_data_is_embedded_safely(self):
        raw = read(os.path.join(ROOT, 'src', 'demo.json')).strip()
        self.assertIsInstance(json.loads(raw), dict)
        # The demo is pasted into a script tag; "<" is escaped so a name cannot close the tag.
        embedded = raw.replace('<', '\\u003c')
        self.assertIn(embedded, read(PAGE))
        self.assertNotIn('<', embedded)


class AssertionTest(unittest.TestCase):
    """Copy the build to a temp folder, break one rule, and check the build refuses."""

    def run_broken(self, rel, append):
        tmp = tempfile.mkdtemp(prefix='diskmap-build-')
        self.addCleanup(shutil.rmtree, tmp)
        shutil.copy(os.path.join(ROOT, 'build.py'), tmp)
        shutil.copytree(os.path.join(ROOT, 'src'), os.path.join(tmp, 'src'))
        with open(os.path.join(tmp, rel), 'a', encoding='utf-8') as fh:
            fh.write(append)
        return subprocess.run([sys.executable, os.path.join(tmp, 'build.py')], stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, universal_newlines=True)

    def test_clean_copy_builds(self):
        self.assertEqual(self.run_broken('src/advice.py', '\n').returncode, 0)

    def test_triple_quote_in_ui_is_refused(self):
        p = self.run_broken('src/ui.html', "\n<!-- it'''s -->\n")
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('AssertionError', p.stdout)

    def test_script_tag_in_python_is_refused(self):
        for text in ("\n# </script> would end the page's script tag\n", '\n# <!-- comment\n', "\nX = '<SCRIPT'\n"):
            p = self.run_broken('src/advice.py', text)
            self.assertNotEqual(p.returncode, 0, text)
            self.assertIn('AssertionError', p.stdout)


class UiTextOnlyTest(unittest.TestCase):
    def test_no_html_sinks(self):
        ui = read(os.path.join(ROOT, 'src', 'ui.html'))
        self.assertGreater(ui.count('textContent'), 0)    # control: the scan sees the file
        for sink in ('innerHTML', 'outerHTML', 'insertAdjacentHTML', 'document.write', 'createContextualFragment',
                     'DOMParser', 'srcdoc'):
            self.assertNotIn(sink, ui)


if __name__ == '__main__':
    unittest.main()
