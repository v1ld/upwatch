#!/usr/bin/env python3
"""Tests for upwatch's check (--json, latest_size, text output) and `upwatch --fetch`, with GitHub, Nexus and the
browser stubbed (no network). A runner loads upwatch as a module, replaces Ctx.gh / Ctx.nexus with answers from a
fixture and calls main(); --fetch cases run under a pseudo-terminal (os.openpty), or with no terminal at all.
The browser is a stub that "downloads" a prepared file into the test's Downloads folder, as your click would.

    python3 -I tests/test_upwatch.py [OLD_UPWATCH] [SCRATCH]

OLD_UPWATCH (optional): an earlier upwatch, to show the old --json crash (a0) and that the check output is unchanged
(n0). SCRATCH defaults to a new folder from tempfile."""
import hashlib, json, os, shutil, subprocess, sys, tempfile, textwrap

HERE = os.path.dirname(os.path.abspath(__file__))
UP = os.path.join(os.path.dirname(HERE), 'upwatch')
ORIG = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1] else None
T = os.path.abspath(sys.argv[2]) if len(sys.argv) > 2 else tempfile.mkdtemp(prefix='upwatch-test-')
print(f'scratch: {T}')
PY = sys.executable
RESULTS = []
FAST = ['--settle', '1', '--poll', '0.2']


def ok(name, cond, info=''):
    RESULTS.append(bool(cond))
    print(f"{'PASS' if cond else 'FAIL'} {name}" + (f'  [{info}]' if info and not cond else ''), flush=True)


def fresh():
    for d in ('dl', 'w3inbox', 'oinbox', 'files'):
        shutil.rmtree(f'{T}/{d}', ignore_errors=True)
        os.makedirs(f'{T}/{d}')
    for f in ('opened.log', 'report.json'):
        if os.path.exists(f'{T}/{f}'):
            os.remove(f'{T}/{f}')


shutil.rmtree(T, ignore_errors=True)
for d in ('cfg/upwatch', 'state', 'cache', 'list', 'other'):
    os.makedirs(f'{T}/{d}')
fresh()

# ---- fixture: a Witcher-style list (A update with size, B current, C held, a GitHub member), a second list for
# another game (X update, no size), single sources (GitHub tool; Nexus solo, curr, and osolo for the other game)
json.dump({'mods': [{'id': 'modA', 'label': 'Mod A', 'nexus_id': 100, 'version': '1.0'},
                    {'id': 'modB', 'label': 'Mod B', 'nexus_id': 200, 'version': '2.0'},
                    {'id': 'modC', 'label': 'Mod C', 'nexus_id': 300, 'version': '3.0', 'hold': 'breaks X', 'hold_declined': '3.1'}],
           'github': [{'id': 'ghOne', 'label': 'GH One', 'repo': 'o/ghone', 'version': '1.0'}]},
          open(f'{T}/list/nexus-check.json', 'w'))
json.dump({'mods': [{'id': 'modX', 'label': 'X Mod', 'nexus_id': 600, 'version': '6.0'}], 'github': []},
          open(f'{T}/other/nexus-check.json', 'w'))


def files(fid, ver, fname, **extra):
    return {'files': [dict({'file_id': fid, 'version': ver, 'file_name': fname, 'name': 'Main', 'category_name': 'MAIN',
                            'uploaded_timestamp': 1000 + fid, 'uploaded_time': '2026-11-20T10:00:00.000+00:00'}, **extra)]}


A_NAME, X_NAME, S_NAME, O_NAME = ('Mod A 100 1.1 2026-11-20T10-00Z abcdefghi.7z', 'X Mod 600 6.1.zip', 'Solo 400 4.2.zip',
                                  'Other Solo 700 7.1.zip')
nexus = {'mods/100/files.json': files(1001, '1.1', A_NAME, size_in_bytes=12345, size_kb=12, size=12),
         'mods/200/files.json': files(2001, '2.0', 'Mod B 200 2.0.zip', size_in_bytes=999),
         'mods/300/files.json': files(3001, '3.1', 'Mod C 300 3.1.zip', size_in_bytes=777),
         'mods/400/files.json': files(4001, '4.2', S_NAME, size_kb=40, size=40),   # no size_in_bytes
         'mods/500/files.json': files(5001, '5.0', 'Curr 500 5.0.zip', size_in_bytes=5),
         'mods/600/files.json': files(6001, '6.1', X_NAME),                          # no size_in_bytes
         'mods/700/files.json': files(7001, '7.1', O_NAME, size_in_bytes=50),
         'mods/100/changelogs.json': {'1.1': ['fixes']}, 'mods/300/changelogs.json': {}, 'mods/400/changelogs.json': {},
         'mods/600/changelogs.json': {}}
for i in (100, 200, 300, 600):
    nexus[f'mods/{i}.json'] = {'name': f'Nexus page title {i}', 'version': '9', 'author': 'someone'}
gh = {'o/ghone/releases/latest': {'tag_name': 'v1.0', 'html_url': 'https://github.com/o/ghone/releases/tag/v1.0'},
      'o/tool/releases/latest': {'tag_name': 'v2.0', 'html_url': 'https://github.com/o/tool/releases/tag/v2.0', 'published_at': '2026-11-01'}}
json.dump({'nexus': nexus, 'gh': gh}, open(f'{T}/fixture.json', 'w'))

A_DATA, X_DATA, S_DATA, O_DATA = b'a' * 12345, b'x' * 600, b's' * 400, b'o' * 50
CLICKER = f'{T}/clicker.py'      # the browser: logs the address, then "downloads" the prepared file for that file_id
open(CLICKER, 'w').write(textwrap.dedent('''\
    import json, os, re, sys, time
    log, table, url = sys.argv[1], sys.argv[2], sys.argv[3]
    open(log, "a").write(f"{time.time():.4f} {url}\\n")
    fid = re.search(r"file_id=(\\d+)", url).group(1)
    t = json.load(open(table)) if os.path.exists(table) else {}
    if fid in t:
        src, dest = t[fid]
        tmp = os.path.join(os.path.dirname(dest), "." + os.path.basename(dest) + ".writing")
        open(tmp, "wb").write(open(src, "rb").read())
        os.replace(tmp, dest)
    '''))
RUNNER = f'{T}/runner.py'
open(RUNNER, 'w').write(textwrap.dedent('''\
    import importlib.machinery, importlib.util, io, json, os, sys, urllib.error
    sys.dont_write_bytecode = True
    path = os.environ['UPWATCH']
    spec = importlib.util.spec_from_loader('upwatch', importlib.machinery.SourceFileLoader('upwatch', path))
    up = importlib.util.module_from_spec(spec); spec.loader.exec_module(up)
    fx = json.load(open(os.environ['FIXTURE']))
    def answer(table, key):
        if key not in table:
            raise urllib.error.HTTPError(key, 404, 'Not Found', {}, io.BytesIO())
        return table[key]
    up.Ctx.gh = lambda self, p: answer(fx['gh'], p)
    up.Ctx.nexus = lambda self, game, p: answer(fx['nexus'], p)
    sys.exit(up.main(sys.argv[1:]))
    '''))


def config(settings='', tw3=f'{T}/w3inbox', cp=f'{T}/oinbox', solo=None):
    d = lambda v: f'fetch_dir = "{v}"\n' if v else ''
    open(f'{T}/cfg/upwatch/config.toml', 'w').write(f'''[settings]
{settings}
[[source]]
name = "tool"
type = "github-release"
repo = "o/tool"
installed = "1.0"

[[source]]
name = "solo"
type = "nexus"
mod_id = 400
installed = "4.0"
{d(solo)}
[[source]]
name = "curr"
type = "nexus"
mod_id = 500
installed = "5.0"

[[source]]
name = "osolo"
type = "nexus"
game = "othergame"
mod_id = 700
installed = "7.0"

[[source]]
name = "tw3"
type = "list"
format = "nexus-check"
file = "{T}/list/nexus-check.json"
tags = ["game"]
{d(tw3)}
[[source]]
name = "cp"
type = "list"
format = "nexus-check"
file = "{T}/other/nexus-check.json"
game = "othergame"
{d(cp)}''')


ENV = dict(os.environ, XDG_CONFIG_HOME=f'{T}/cfg', XDG_STATE_HOME=f'{T}/state', XDG_CACHE_HOME=f'{T}/cache',
           FIXTURE=f'{T}/fixture.json', UPWATCH=UP)
OPENER = ['--opener', f'{PY} -I {CLICKER} {T}/opened.log {T}/clicks.json', '--downloads', f'{T}/dl']


def run(args, tty=False, up=UP):
    env = dict(ENV, UPWATCH=up)
    argv = [PY, '-I', RUNNER] + args
    if not tty:
        p = subprocess.run(argv, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120)
        return p.returncode, p.stdout + p.stderr
    m, s = os.openpty()
    p = subprocess.Popen(argv, env=env, stdin=s, stdout=s, stderr=s)
    os.close(s)
    out = b''
    while True:
        try:
            b = os.read(m, 65536)
        except OSError:
            break
        if not b:
            break
        out += b
    os.close(m)
    return p.wait(timeout=120), out.decode(errors='replace').replace('\r\n', '\n')


def opened():
    return [ln.split(' ', 1)[1] for ln in open(f'{T}/opened.log').read().split('\n') if ln] if os.path.exists(f'{T}/opened.log') else []


def clicks(table):
    """file_id -> the file the "browser" saves into Downloads when that page opens."""
    out = {}
    for fid, name, blob in table:
        src = f'{T}/files/{fid}'
        open(src, 'wb').write(blob)
        out[str(fid)] = [src, f'{T}/dl/{name}']
    json.dump(out, open(f'{T}/clicks.json', 'w'))


def fetch_part(out):
    """The lines after the check output (the fetch section starts after the first blank line following the check)."""
    i = out.find('\n\n')
    return out[i + 2:] if i >= 0 else ''


md5 = lambda b: hashlib.md5(b).hexdigest()

# ---- (a) --json
config()
if ORIG:
    rc, out = run(['--json'], up=ORIG)
    ok('a0 old upwatch --json crashes as reported', rc != 0 and "multiple values for keyword argument 'name'" in out, out[-300:])
else:
    print('SKIP a0 (no OLD_UPWATCH given)')
rc, out = run(['--json'])
try:
    rows = {r['path']: r for r in json.loads(out)}
except ValueError:
    rows = {}
ok('a1 --json exits 0 and parses', rc == 0 and rows, out[-400:])
a = rows.get('tw3/modA', {})
ok('a2 member keeps shown name and Nexus title', a.get('name') == 'Mod A' and a.get('nexus_name') == 'Nexus page title 100'
   and a.get('label') == 'Mod A', a)
ok('a3 standalone rows keep name = source name', rows.get('tool', {}).get('name') == 'tool' and 'nexus_name' not in rows.get('tool', {}))
# ---- (b) size
ok('b1 latest_size from size_in_bytes (list member)', a.get('latest_size') == 12345, a.get('latest_size'))
s = rows.get('solo', {})
ok('b2 no size_in_bytes: no latest_size (not guessed from kB)', 'latest_size' not in s and s.get('latest_file') == S_NAME
   and s.get('latest_file_id') == 4001 and s.get('nexus_id') == 400, s)
st = {r['id']: r for r in json.load(open(f'{T}/list/nexus-status.json'))['mods']}
ok('b3 nexus-status.json has latest_size, its name unchanged', st['modA'].get('latest_size') == 12345
   and st['modA'].get('name') == 'Nexus page title 100')
rc, out = run([])
ok('b4 text output unchanged in form', rc == 0 and 'U Mod A (1.0 -> 1.1)' in out and 'U solo (4.0 -> 4.2)' in out, out)
if ORIG:
    strip = lambda o: '\n'.join(x for x in o.split('\n') if not x.startswith('TIME '))
    r1, o1 = run(['-v'], up=ORIG)
    r2, o2 = run(['-v'])
    ok('n0 check output identical to the old upwatch (-v, TIME line aside)', r1 == r2 == 0 and strip(o1) == strip(o2), f'{o1}\n---\n{o2}')
else:
    print('SKIP n0 (no OLD_UPWATCH given)')

# ---- (c) --fetch: what is fetched, refusals
rc, out = run(['--fetch', '--dry-run'] + OPENER + FAST, tty=True)
f = fetch_part(out)
ok('c1 dry run: Nexus updates with a fetch_dir would open, nothing opened', rc == 0 and 'Mod A 1.1: would open its page' in f
   and 'X Mod 6.1: would open its page' in f and 'Nothing opened, nothing moved' in f and opened() == [], out)
ok('c2 only Nexus file updates: not held C, GitHub tool skipped in one line', 'Mod C' not in f
   and 'tool v2.0: skipped (not a Nexus file)' in f and 'GH One' not in f, f)
ok('c3 normal output shown first', 'U Mod A' in out and 'U tool' in out and out.index('U tool') < out.index('Mod A 1.1: would'), out)
rc, out = run(['curr', 'tw3/modB', '--fetch'] + OPENER, tty=True)
ok('c4 no updates: says so, opens nothing', rc == 0 and opened() == [] and 'no Nexus file updates' in out, out)
rc, out = run(['tool', '--fetch'] + OPENER, tty=True)
ok('c5 only a non-Nexus update: opens nothing', rc == 0 and opened() == [] and 'no Nexus file updates' in out
   and 'tool v2.0: skipped (not a Nexus file)' in out, out)
rc, out = run(['tw3/modA', '--fetch', '--dry-run'] + OPENER + FAST, tty=True)
f = fetch_part(out)
ok('c6 selection narrows the fetch', rc == 0 and 'Mod A 1.1: would open its page' in f and 'X Mod' not in f and 'solo' not in f, out)
rc, out = run(['--fetch'] + OPENER)
ok('c7 no terminal: refused, nothing run', rc == 2 and opened() == [] and 'only in a terminal' in out and 'U ' not in out, out)
for fl in ('--notify', '--quiet', '-q', '--json'):
    rc, out = run(['--fetch', fl] + OPENER, tty=True)
    ok(f'c8 refused with {fl}', rc == 2 and opened() == [] and 'nothing fetched' in out and 'U ' not in out, out)
rc, out = run(['list', '--fetch'], tty=True)
ok('c9 refused with list', rc == 2 and 'only with check' in out, out)
rc, out = run(['--dry-run'], tty=True)
ok('c10 a fetch option without --fetch refused', rc == 2 and 'is a fetch option' in out and 'U ' not in out, out)
config(tw3=None, cp=None)
rc, out = run(['--fetch'] + OPENER + FAST, tty=True)
f = fetch_part(out)
ok('c11 no fetch_dir anywhere: check shown, each Nexus update skipped in one line, nothing opened', rc == 0 and 'U Mod A' in out
   and 'Mod A 1.1: skipped (no fetch_dir for tw3)' in f and 'X Mod 6.1: skipped (no fetch_dir for cp)' in f
   and 'solo 4.2: skipped (no fetch_dir for solo)' in f and 'no Nexus file updates to fetch' in f and opened() == [], out)
config(settings=f'fetch_dir = "{T}/oinbox"', tw3=f'{T}/w3inbox', cp=None)
rc, out = run(['--fetch', '--dry-run', '-v'] + OPENER + FAST, tty=True)
ok('c12 [settings] fetch_dir is the default for sources without one; a list keeps its own', rc == 0
   and 'solo 4.2: would open its page' in out and f'[{T}/oinbox]  {S_NAME}' in out and f'[{T}/w3inbox]  {A_NAME}' in out, out)

# ---- (d) real runs (the "browser" stub saves the file as a click would)
config()
fresh()
open(f'{T}/dl/{A_NAME}', 'wb').write(A_DATA)        # already in Downloads before the run
open(f'{T}/dl/{O_NAME}', 'wb').write(O_DATA)        # osolo's file: its source has no fetch_dir
clicks([(6001, X_NAME, X_DATA), (4001, S_NAME, S_DATA)])
rc, out = run(['--fetch', '--yes', '--report', f'{T}/report.json'] + OPENER + FAST, tty=True)
f = fetch_part(out)
ok('d1 end to end: Mod A (already in Downloads) and X Mod (clicked) fetched, exit 0', rc == 0
   and open(f'{T}/w3inbox/{A_NAME}', 'rb').read() == A_DATA and open(f'{T}/oinbox/{X_NAME}', 'rb').read() == X_DATA, out)
ok('d2 a page is opened only for the file not yet downloaded',
   opened() == ['https://www.nexusmods.com/othergame/mods/600?tab=files&file_id=6001'], opened())
ok('d3 Downloads keeps only what was not fetched', sorted(os.listdir(f'{T}/dl')) == [O_NAME], os.listdir(f'{T}/dl'))
ok('n1 a source without a destination is not fetched: one line, its file stays in Downloads',
   'osolo 7.1: skipped (no fetch_dir for osolo)' in f and sum(1 for x in f.split('\n') if 'osolo' in x) == 1 and not os.path.exists(f'{T}/w3inbox/{O_NAME}'), f)
ok('n2 two lists, two destinations: the other game\'s file never lands in the Witcher folder',
   os.listdir(f'{T}/w3inbox') == [A_NAME] and os.listdir(f'{T}/oinbox') == [X_NAME], (os.listdir(f'{T}/w3inbox'), os.listdir(f'{T}/oinbox')))
summary = f[f.rindex('\n\n') + 2:].strip().split('\n') if '\n\n' in f else []
want = ['tool v2.0: skipped (not a Nexus file)', 'solo 4.2: skipped (no fetch_dir for solo)',
        'osolo 7.1: skipped (no fetch_dir for osolo)', 'Mod A 1.1: fetched', 'X Mod 6.1: fetched', 'fetch: 2 fetched, 3 skipped, 0 failed']
ok('n3 short output: one line per mod, then one count line; no path, match kind or md5',
   sorted(summary) == sorted(want) and summary[-1] == want[-1] and md5(A_DATA) not in out and f'{T}/w3inbox' not in out
   and 'by name' not in out, summary)
rep = json.load(open(f'{T}/report.json')) if os.path.exists(f'{T}/report.json') else {}
items = {i['mod']: i for i in rep.get('items', [])}
ok('n4 --report: status, path, match kind and md5 per file; skipped and counts',
   rep.get('format') == 'upwatch-fetch-report' and items.get('Mod A', {}).get('status') == 'fetched'
   and items['Mod A'].get('path') == f'{T}/w3inbox/{A_NAME}' and items['Mod A'].get('how') == 'name+size'
   and items['Mod A'].get('md5') == md5(A_DATA) and items.get('X Mod', {}).get('how') == 'name'
   and items['X Mod'].get('dest') == f'{T}/oinbox' and rep.get('counts') == {'fetched': 2, 'skipped': 3, 'failed': 0}
   and {x['mod'] for x in rep.get('skipped', [])} == {'tool v2.0', 'solo 4.2', 'osolo 7.1'}, json.dumps(rep)[:1500])
fresh()
clicks([(1001, A_NAME, A_DATA), (6001, X_NAME, X_DATA)])
rc, out = run(['--fetch', '-v'] + OPENER + FAST, tty=True)
ok('n5 -v output: path, match kind and md5 per fetched file', rc == 0 and f'{T}/w3inbox/{A_NAME}' in out
   and f'by name+size; md5 {md5(A_DATA)}' in out and f'matched by name only; md5 {md5(X_DATA)}' in out
   and 'Mod A 1.1: fetched' in out and 'fetch: 2 fetched, 3 skipped, 0 failed' in out, out)
ok('n6 pages opened with a gap of at least 1 s, in one batch', len(opened()) == 2, opened())
fresh()
config(cp=f'{T}/does-not-exist')
rc, out = run(['--fetch'] + OPENER + FAST, tty=True)
ok('n7 a missing destination folder: refused, nothing opened or moved', rc == 2 and 'destination folder missing' in out
   and opened() == [] and os.listdir(f'{T}/w3inbox') == [], out)
config()
fresh()
open(f'{T}/w3inbox/{A_NAME}', 'wb').write(b'an older, different file')
clicks([(1001, A_NAME, A_DATA)])
rc, out = run(['tw3', '--fetch'] + OPENER + FAST, tty=True)
ok('n8 never overwrites: destination holds a different file of that name -> FAILED, both kept, exit 1', rc == 1
   and open(f'{T}/w3inbox/{A_NAME}', 'rb').read() == b'an older, different file' and open(f'{T}/dl/{A_NAME}', 'rb').read() == A_DATA
   and 'Mod A 1.1: FAILED (a different file of that name is in the destination' in out, out)
print(f'{sum(RESULTS)} passed, {len(RESULTS) - sum(RESULTS)} failed')
sys.exit(0 if all(RESULTS) else 1)
