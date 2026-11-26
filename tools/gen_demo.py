"""Regenerate src/demo.json, the example data the artifact shows before it is installed.

Usage: python3 build.py && python3 tools/gen_demo.py /home/tester && python3 build.py
The folder (see tests/make_test_home.py) must sit under /home/<name> or /Users/<name> so the
advice rules treat it as a home folder.
"""
import importlib.util, json, os, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location('dm', os.path.join(ROOT, 'dist', 'diskmap.py')); dm = importlib.util.module_from_spec(spec); spec.loader.exec_module(dm)
REAL, FAKE = os.path.realpath(sys.argv[1]), '/Users/you'
sc = dm.Scanner(2, None, [REAL]); r = sc.start_scan(REAL)
while r.state != 'done': time.sleep(0.1)
rules = {}; order = []
def rid(rule):
    if rule.title not in rules:
        rules[rule.title] = len(order); order.append({'t': rule.title, 'w': rule.why, 'h': list(rule.how)})
    return rules[rule.title]
SKIP = {'weird', 'secret', 'Movies-link', 'A002_hardlink.mov', 'empty'}
def fake(p): return FAKE + p[len(REAL):]
def conv(real, top=False):
    _, node = sc.lookup(real)
    name = 'Example home folder' if top else node.name
    rule, anchor, direct = dm.find_rule(real, True)
    d = {'n': name, 'k': 'd', 'lv': rule.lv, 'ri': rid(rule), 'kind': dm.kind_label(node.name, True)}
    if not direct: d['via'] = fake(anchor)
    if dm.is_package(node.name): d['fl'] = dm.F_PKG
    kids = []
    for cname in sorted(node.children or {}):
        if cname in SKIP: continue
        kids.append(conv(dm.join(real, cname)))
    for fname, size, mt, fl in sc.list_files(real):
        if fname in SKIP: continue
        frule, fanchor, fdirect = dm.find_rule(dm.join(real, fname), False)
        f = {'n': fname, 's': size, 'k': 'f', 'lv': frule.lv, 'mt': mt, 'ri': rid(frule), 'kind': dm.kind_label(fname, False)}
        if not fdirect: f['via'] = fake(fanchor)
        kids.append(f)
    kids.sort(key=lambda k: -k['s'])
    total = sum(k['s'] for k in kids)
    keep, osize, ocnt = [], 0, 0
    for i, k in enumerate(kids):
        if i < 14 and k['s'] >= total / 300.0: keep.append(k)
        else: osize += k['s']; ocnt += 1
    if ocnt: keep.append({'n': '', 's': osize, 'k': 'o', 'cnt': ocnt, 'lv': d['lv']})
    d['s'] = total
    d['fc'] = sum(k.get('fc', 1 if k['k'] == 'f' else k.get('cnt', 0)) for k in kids)
    d['dc'] = sum(1 + k.get('dc', 0) for k in kids if k['k'] == 'd')
    d['mt'] = max([k.get('mt', 0) for k in kids] or [0])
    if keep: d['c'] = keep
    return d
tree = conv(REAL, True)
out = {'root': FAKE, 'rules': order, 'tree': tree}
s = json.dumps(out, separators=(',', ':'))
open(os.path.join(ROOT, 'src', 'demo.json'), 'w').write(s)
def cnt(n): return 1 + sum(cnt(c) for c in n.get('c', []))
print('demo nodes', cnt(tree), 'bytes', len(s), 'rules', len(order), 'total', tree['s'])
os._exit(0)
