#!/usr/bin/env python3
"""Block commits that carry personal data.

Usage: check_private.py FILE...   (pre-commit passes the staged files, or the
commit message file for the commit-msg stage)

Checks every line for email addresses, real home folder paths, IP and MAC
addresses, and for any regular expression listed in private/patterns.txt
(one per line, case-insensitive). That file is git-ignored so the terms it
protects are never published; without it only the built-in checks run.

A line that must keep a match can end with the comment "check-private: allow". The marker
turns off the built-in checks for that line, never the private terms.
Standard library only, Python 3.8+.
"""
import os
import re
import sys
from urllib.parse import unquote

ALLOW_MARK = 'check-private: allow'
ALLOW_RX = re.compile(r'(#|//|<!--)\s*' + re.escape(ALLOW_MARK) + r'\b.*$')
PATTERNS_FILE = os.path.join('private', 'patterns.txt')
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

EMAIL = re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}')
# Reserved test domains (RFC 2606) and no-reply addresses are not personal.
EMAIL_OK = re.compile(r'(@users\.noreply\.github\.com|^no-?reply@.*|^git@.*|@example\.(com|org|net)'
                      r'|\.(example|test|invalid|localhost))$', re.I)
HOME = re.compile(r'(?:[/\\](?:users|home)[/\\]|(?<![\w~])~(?=[A-Za-z][\w.-]*/))([A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*)', re.I)
HOME_OK = {'you', 'your-name', 'yourname', 'tester', 'shared', 'guest', 'name', 'runner', 'user',
           'username', 'me', 'public', 'default'}
# Computer names as macOS shows them on a local network (Jane-MacBook-Pro.local).  # check-private: allow
HOSTNAME = re.compile(r'\b[A-Za-z0-9]+(?:-[A-Za-z0-9]+)+\.local\b')
IPV4 = re.compile(r'(?<![\d.])(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})(?![\d.])')
IPV4_OK = {'127.0.0.1', '0.0.0.0', '255.255.255.255'}
# Documentation ranges (RFC 5737) and the documentation MAC block (RFC 7042).
IPV4_DOC = ('192.0.2.', '198.51.100.', '203.0.113.')
MAC_DOC = '00:00:5e:00:53:'
MAC = re.compile(r'(?<![0-9A-Fa-f:])(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}(?![0-9A-Fa-f:])')


def load_private_patterns():
    path = os.path.join(ROOT, PATTERNS_FILE)
    try:
        with open(path, encoding='utf-8') as f:
            lines = [ln.strip() for ln in f]
    except OSError:
        return []
    out = []
    for no, ln in enumerate(lines, 1):
        if not ln or ln.startswith('#'):
            continue
        try:
            out.append(re.compile(ln, re.I))
        except re.error as e:
            # Name the line, not the pattern: the pattern is the private term.
            sys.exit('%s:%d: bad regular expression (%s)' % (PATTERNS_FILE, no, e.msg))
    return out


def line_problems(line, private):
    found = []
    # Also check the URL-decoded form, so %40 and %2F do not hide a match.
    variants = {line, unquote(line)}
    for rx in private:
        if any(rx.search(v) for v in variants):
            found.append('term from ' + PATTERNS_FILE)
    if ALLOW_RX.search(line):
        return found
    for v in variants:
        found.extend(_builtin_problems(v))
    return found


def _builtin_problems(line):
    found = []
    for m in EMAIL.finditer(line):
        if not EMAIL_OK.search(m.group(0)):
            found.append('email address')
    for m in HOME.finditer(line):
        if m.group(1).lower() not in HOME_OK and not m.group(1).startswith('<'):
            found.append('home folder path')
    for m in IPV4.finditer(line):
        ip = m.group(0)
        if ip not in IPV4_OK and not ip.startswith(IPV4_DOC) and all(int(g) <= 255 for g in m.groups()):
            found.append('IP address')
    for m in MAC.finditer(line):
        if not m.group(0).lower().replace('-', ':').startswith(MAC_DOC):
            found.append('MAC address')
    if HOSTNAME.search(line):
        found.append('computer name')
    return found


def main(paths):
    private = load_private_patterns()
    bad = 0
    for path in paths:
        if os.path.abspath(path) == os.path.join(ROOT, PATTERNS_FILE):
            continue
        try:
            with open(path, 'rb') as f:
                data = f.read()
        except OSError:
            continue
        if b'\0' in data[:8192]:
            continue  # binary: gitleaks still covers secrets
        # Latin-1 never fails, so a file in another encoding is still checked.
        try:
            lines = data.decode('utf-8').splitlines()
        except UnicodeDecodeError:
            lines = data.decode('latin-1').splitlines()
        for no, line in enumerate(lines, 1):
            for what in sorted(set(line_problems(line, private))):
                # Print the kind of data, never the matched value.
                print('%s:%d: possible %s' % (path, no, what))
                bad += 1
    if bad:
        print('\n%d possible personal data finding(s). Remove them, or end the line with '
              '"# %s" if the value is not personal.' % (bad, ALLOW_MARK))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
