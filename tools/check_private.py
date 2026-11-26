#!/usr/bin/env python3
"""Block commits that carry personal data.

Usage: check_private.py FILE...   (pre-commit passes the staged files, or the
commit message file for the commit-msg stage)

Checks every line for email addresses, real home folder paths, IP and MAC
addresses, and for any regular expression listed in private/patterns.txt
(one per line, case-insensitive). That file is git-ignored so the terms it
protects are never published; without it only the built-in checks run.

A line that must keep a match can end with the comment "check-private: allow".
Standard library only, Python 3.8+.
"""
import os
import re
import sys

ALLOW_MARK = 'check-private: allow'
PATTERNS_FILE = os.path.join('private', 'patterns.txt')

EMAIL = re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}')
# Reserved test domains (RFC 2606) and no-reply addresses are not personal.
EMAIL_OK = re.compile(r'(@users\.noreply\.github\.com|^noreply@.*|@example\.(com|org|net)'
                      r'|\.(example|test|invalid|localhost))$', re.I)
HOME = re.compile(r'(?:/Users|/home)/([A-Za-z0-9._-]+)')
HOME_OK = {'you', 'tester', 'shared', 'guest', 'name', 'runner', 'user', 'username', 'me'}
IPV4 = re.compile(r'(?<![\d.])(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})(?![\d.])')
IPV4_OK = {'127.0.0.1', '0.0.0.0', '255.255.255.255'}
MAC = re.compile(r'(?<![0-9A-Fa-f:])(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}(?![0-9A-Fa-f:])')


def load_private_patterns():
    try:
        with open(PATTERNS_FILE, encoding='utf-8') as f:
            lines = [ln.strip() for ln in f]
    except OSError:
        return []
    return [re.compile(ln, re.I) for ln in lines if ln and not ln.startswith('#')]


def line_problems(line, private):
    if ALLOW_MARK in line:
        return []
    found = []
    for m in EMAIL.finditer(line):
        if not EMAIL_OK.search(m.group(0)):
            found.append('email address')
    for m in HOME.finditer(line):
        if m.group(1).lower() not in HOME_OK and not m.group(1).startswith('<'):
            found.append('home folder path')
    for m in IPV4.finditer(line):
        if m.group(0) not in IPV4_OK and all(int(g) <= 255 for g in m.groups()):
            found.append('IP address')
    if MAC.search(line):
        found.append('MAC address')
    for rx in private:
        if rx.search(line):
            found.append('term from ' + PATTERNS_FILE)
    return found


def main(paths):
    private = load_private_patterns()
    bad = 0
    for path in paths:
        if os.path.normpath(path) == PATTERNS_FILE:
            continue
        try:
            with open(path, encoding='utf-8') as f:
                lines = f.readlines()
        except (OSError, UnicodeDecodeError):
            continue  # binary or unreadable: gitleaks still covers secrets
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
