import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
import check_private as cp  # noqa: E402


class LineChecks(unittest.TestCase):
    def kinds(self, line, private=()):
        return set(cp.line_problems(line, list(private)))

    def test_flags_personal_values(self):
        # check-private: allow (the fixtures below are fake on purpose)
        self.assertEqual(self.kinds('mail jane.doe@gmail.com'), {'email address'})  # check-private: allow
        self.assertEqual(self.kinds('cd /Users/jane/dev'), {'home folder path'})  # check-private: allow
        self.assertEqual(self.kinds('nas at 192.168.1.20'), {'IP address'})  # check-private: allow
        self.assertEqual(self.kinds('mac a4:83:e7:12:34:56'), {'MAC address'})  # check-private: allow

    def test_allows_placeholders(self):
        for line in ['/Users/you/Library', '/home/tester', '/Users/Shared', '127.0.0.1:8080',
                     'Co-Authored-By: Claude <noreply@anthropic.com>',
                     '1+someone@users.noreply.github.com', '//tester@nas.example/share',
                     'version 1.2.3', 'x 300.1.1.1']:
            self.assertEqual(self.kinds(line), set(), line)

    def test_allow_marker(self):
        self.assertEqual(self.kinds('jane.doe@gmail.com # ' + cp.ALLOW_MARK), set())  # check-private: allow

    def test_private_patterns(self):
        import re
        self.assertEqual(self.kinds('Hello Zorblax', [re.compile('zorblax', re.I)]),
                         {'term from ' + cp.PATTERNS_FILE})


class CommandLine(unittest.TestCase):
    def test_exit_codes_and_no_value_echo(self):
        with tempfile.TemporaryDirectory() as d:
            bad = os.path.join(d, 'bad.txt')
            good = os.path.join(d, 'good.txt')
            with open(bad, 'w') as f:
                f.write('ping jane.doe@gmail.com\n')  # check-private: allow
            with open(good, 'w') as f:
                f.write('nothing here\n')
            script = os.path.join(ROOT, 'tools', 'check_private.py')
            r = subprocess.run([sys.executable, script, bad], cwd=d, capture_output=True, text=True)
            self.assertEqual(r.returncode, 1)
            self.assertIn('bad.txt:1: possible email address', r.stdout)
            self.assertNotIn('jane.doe', r.stdout)
            r = subprocess.run([sys.executable, script, good], cwd=d, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0)


if __name__ == '__main__':
    unittest.main()
