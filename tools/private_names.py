#!/usr/bin/env python3
"""Add the folder names from your own drive to private/patterns.txt.

Usage: python3 tools/private_names.py [FOLDER...]   (default: ~/dev, ~/dev/*, ~/Projects)

Fixtures, example data and screenshots must use invented names. This script lists the
folders you keep projects in and writes their names to a marked section of the git-ignored
private/patterns.txt, so tools/check_private.py blocks a commit that copies one of them.
Run it again when you start new projects; it replaces only its own section.

Names shorter than 4 characters and common folder words are skipped, because they would
block ordinary text. Standard library only, Python 3.8+.
"""
import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATTERNS = os.path.join(ROOT, 'private', 'patterns.txt')
BEGIN = '# BEGIN folder names from this drive (tools/private_names.py)'
END = '# END folder names from this drive'
DEFAULTS = ['~/dev', '~/dev/*', '~/Projects', '~/.claude-worktrees']
# Generic words a fixture may use on purpose; they say nothing about the owner.
GENERIC = {'test', 'tests', 'docs', 'site', 'src', 'build', 'dist', 'tools', 'scripts', 'data',
           'notes', 'backup', 'archive', 'temp', 'tmp', 'misc', 'old', 'new', 'demo', 'example',
           'examples', 'sandbox', 'secrets', 'private', 'public', 'model', 'models', 'openai',
           'dotfiles', 'handoff', 'plans', 'assets', 'images', 'web-app', 'api-server', 'brew',
           'claude', 'config', 'downloads', 'shell', 'venv', 'vscode'}
# This repository's own folder name is public by definition.
GENERIC.add(os.path.basename(ROOT).lower())


def folder_names(roots):
    names = set()
    for pattern in roots:
        for base in glob.glob(os.path.expanduser(pattern)):
            if not os.path.isdir(base):
                continue
            for name in os.listdir(base):
                if name.startswith('.') or not os.path.isdir(os.path.join(base, name)):
                    continue
                if len(name) >= 4 and name.lower() not in GENERIC:
                    names.add(name)
    return sorted(names, key=str.lower)


def main(args):
    try:
        with open(PATTERNS, encoding='utf-8') as f:
            text = f.read()
    except OSError:
        text = '# One case-insensitive regex per line. Git-ignored: never commit this file.\n'
    text = re.sub(r'\n?' + re.escape(BEGIN) + r'.*?' + re.escape(END) + r'\n?', '\n', text, flags=re.S)
    # Skip names a hand-written pattern already covers; that pattern may be more careful.
    own = []
    for ln in text.splitlines():
        ln = ln.strip()
        if ln and not ln.startswith('#'):
            try:
                own.append(re.compile(ln, re.I))
            except re.error:
                pass
    names = [n for n in folder_names(args or DEFAULTS) if not any(rx.search(n) for rx in own)]
    block = [BEGIN] + [r'(?<![\w-])' + re.escape(n) + r'(?![\w-])' for n in names] + [END]
    os.makedirs(os.path.dirname(PATTERNS), exist_ok=True)
    with open(PATTERNS, 'w', encoding='utf-8') as f:
        f.write(text.rstrip('\n') + '\n' + '\n'.join(block) + '\n')
    # Print the count, not the names: the output may land in a shared log.
    print('%d folder names written to %s' % (len(names), os.path.relpath(PATTERNS, ROOT)))


if __name__ == '__main__':
    main(sys.argv[1:])
