"""Shared setup for the unit tests: build once, then import the shipped dist/diskmap.py.

Testing the built file (not src/) means the tests see exactly what the build ships.
"""
import importlib.util
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, 'dist')
SCRIPT = os.path.join(DIST, 'diskmap.py')
ENGINE = os.path.join(DIST, 'app', 'engine.py')
PAGE = os.path.join(DIST, 'app', 'index.html')

_mod = None


def build():
    p = subprocess.run([sys.executable, os.path.join(ROOT, 'build.py')],
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
    if p.returncode != 0:
        raise RuntimeError('build.py failed:\n' + p.stdout)


def diskmap():
    """The built standalone script, imported as a module (built on first use)."""
    global _mod
    if _mod is None:
        build()
        spec = importlib.util.spec_from_file_location('diskmap_under_test', SCRIPT)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _mod = mod
    return _mod
