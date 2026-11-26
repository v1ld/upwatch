#!/usr/bin/env python3
"""Tests for `upwatch fetch WANTS.json` (the fetch part of upwatch). No network: the browser opener is replaced by a
stub that records each address and the time it was handed over. upwatch runs under a pseudo-terminal (it fetches only
in a terminal). Everything happens in a scratch folder from tempfile (or argv[1]).

    python3 -I tests/test_fetch.py [SCRATCH]

Prints one PASS/FAIL line per case and exits 1 if any case failed.
"""
import hashlib, json, os, shutil, signal, subprocess, sys, tempfile, threading, time, traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / 'upwatch'
ROOT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp(prefix='upwatch-test-fetch-'))
SHM = Path('/dev/shm')
FAST = ['--settle', '1', '--poll', '0.2']
FMT = 'upwatch-wants'

STUB = """import sys, time
with open(sys.argv[1], 'a') as f:
    f.write(f"{time.time():.4f} {sys.argv[2]}\\n")
"""


def md5(p):
    return hashlib.md5(Path(p).read_bytes()).hexdigest()


def data(seed, size):
    return (seed.encode() * (size // max(1, len(seed)) + 1))[:size]


def pty_run(cmd, env, inp=None, actions=(), timeout=60):
    """Run cmd on a pseudo-terminal; actions = [(seconds after start, callable(proc, master fd))]. (code, output, errors)."""
    m, sl = os.openpty()
    p = subprocess.Popen(cmd, stdin=sl, stdout=sl, stderr=sl, env=env)
    os.close(sl)
    buf = []

    def reader():
        while True:
            try:
                b = os.read(m, 65536)
            except OSError:
                break
            if not b:
                break
            buf.append(b)
    th = threading.Thread(target=reader, daemon=True)
    th.start()
    CURRENT_MASTER[0] = m
    if inp is not None:
        os.write(m, inp.encode())
    t0, errors = time.time(), []
    for at, fn in sorted(actions, key=lambda x: x[0]):
        while time.time() - t0 < at:
            if p.poll() is not None:
                break
            time.sleep(0.02)
        try:
            fn(p, m)
        except Exception:
            errors.append(traceback.format_exc())
    try:
        p.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        p.kill()
        p.wait()
        th.join(2)
        raise AssertionError('upwatch did not end in time; output:\n' + b''.join(buf).decode(errors='replace')[-1500:])
    th.join(5)
    os.close(m)
    return p.returncode, b''.join(buf).decode(errors='replace').replace('\r\n', '\n'), errors


class Case:
    def __init__(self, name):
        self.name = name
        self.dir = ROOT / name
        if self.dir.exists():
            shutil.rmtree(self.dir)
        self.dl = self.dir / 'Downloads'
        self.arch = self.dir / 'store' / 'archives'
        self.inbox = self.dir / 'downloads'
        self.cfg = self.dir / 'cfg'
        for d in (self.dl, self.arch, self.inbox, self.cfg):
            d.mkdir(parents=True)
        self.log = self.dir / 'opened.log'
        (self.dir / 'stub.py').write_text(STUB)
        self.wants = self.dir / 'wants.json'
        self.files = []

    def want(self, mod, mid, fid, fname, content=None, size='auto', with_md5=False, dest='inbox', **extra):
        e = {'mod': mod, 'nexus_mod_id': mid, 'file_id': fid, 'file_name': fname, 'dest': dest,
             'url': f'https://www.nexusmods.com/witcher3/mods/{mid}?tab=files&file_id={fid}'}
        e['size'] = (len(content) if content is not None else None) if size == 'auto' else size
        e['md5'] = hashlib.md5(content).hexdigest() if with_md5 else None
        e.update(extra)
        self.files.append(e)
        return e

    def write_wants(self):
        self.wants.write_text(json.dumps({'format': FMT, 'version': 1, 'written_by': 'test', 'files': self.files}, indent=1))

    def env(self, extra=None):
        return dict(os.environ, XDG_CONFIG_HOME=str(self.cfg), XDG_STATE_HOME=str(self.dir / 'state'),
                    XDG_CACHE_HOME=str(self.dir / 'cache'), **(extra or {}))

    def opened(self):
        if not self.log.exists():
            return []
        return [(float(t), u) for t, u in (ln.split(' ', 1) for ln in self.log.read_text().split('\n') if ln)]

    def run(self, *extra, actions=(), timeout=60, env=None, inp=None, archive=None, dirs=True):
        """Run upwatch fetch; actions = [(seconds after start, callable(proc))]. Returns (code, output)."""
        self.write_wants()
        cmd = [sys.executable, '-I', str(SCRIPT), 'fetch', str(self.wants), '--downloads', str(self.dl),
               '--opener', f'{sys.executable} -I {self.dir / "stub.py"} {self.log}', '--report', str(self.dir / 'report.json')]
        if dirs:
            cmd += ['--archive-dir', str(archive or self.arch), '--inbox-dir', str(self.inbox)]
        cmd += FAST + list(extra)
        code, self.out, errors = pty_run(cmd, self.env(env), inp, [(at, lambda p, m, fn=fn: fn(p)) for at, fn in actions], timeout)
        if errors:
            raise AssertionError('action failed:\n' + '\n'.join(errors))
        return code, self.out

    def report(self):
        return json.loads((self.dir / 'report.json').read_text())


def enter(p):
    os.write(CURRENT_MASTER[0], b'\n')


def sigint(p):
    p.send_signal(signal.SIGINT)


def put(path, content):
    tmp = path.with_name('.' + path.name + '.writing')
    tmp.write_bytes(content)
    os.replace(tmp, path)


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


CASES = []
CURRENT_MASTER = [None]


def case(fn):
    CASES.append(fn)
    return fn


# ---------------------------------------------------------------- cases

@case
def by_md5():
    c = Case('by_md5')
    blob = data('combatstance', 50000)
    c.want('Combat Stance', 15825, 101, 'CombatStance 15825 0.9R 2026-11-19T13-11Z rIB9DsIoo.7z', blob, with_md5=True, dest='archive')
    code, out = c.run('-v', actions=[(1.0, lambda p: put(c.dl / 'saved under another name.7z', blob))])
    t = c.arch / 'CombatStance 15825 0.9R 2026-11-19T13-11Z rIB9DsIoo.7z'
    check(code == 0, f'exit {code}\n{out}')
    check(t.exists() and md5(t) == hashlib.md5(blob).hexdigest(), 'not moved to the archive store')
    check(not (c.dl / 'saved under another name.7z').exists(), 'source still in Downloads')
    check('by md5' in out and hashlib.md5(blob).hexdigest() in out, 'summary (-v) lacks how / md5')
    check('Combat Stance: fetched' in out and 'fetch: 1 fetched, 0 skipped, 0 failed' in out, out)
    check([u for _, u in c.opened()] == ['https://www.nexusmods.com/witcher3/mods/15825?tab=files&file_id=101'], c.opened())


@case
def by_name_and_size():
    c = Case('by_name_and_size')
    blob = data('gallop', 30000)
    c.want('Gallop', 15896, 201, 'Gallop 15896 0.9R 2026-11-23T11-46Z tCEwlQCNw.7z', blob)
    code, out = c.run('-v', actions=[(1.0, lambda p: put(c.dl / 'Gallop 15896 0.9R 2026-11-23T11-46Z tCEwlQCNw.7z', blob))])
    check(code == 0, out)
    check((c.inbox / 'Gallop 15896 0.9R 2026-11-23T11-46Z tCEwlQCNw.7z').exists(), 'not moved to the inbox')
    check('by name+size' in out, out)


@case
def renamed_copy():
    c = Case('renamed_copy')
    a, b = data('a', 1000), data('b', 2000)
    c.want('A', 11, 1, 'Alpha-11-1-0-1700000000.zip', a)
    c.want('B', 12, 2, 'Beta 12 1.0 2026-11-01T10-00Z abc.tar.gz', b)
    code, out = c.run(actions=[(1.0, lambda p: put(c.dl / 'Alpha-11-1-0-1700000000 (1).zip', a)),
                               (1.0, lambda p: put(c.dl / 'Beta 12 1.0 2026-11-01T10-00Z abc(2).tar.gz', b))])
    check(code == 0, out)
    check((c.inbox / 'Alpha-11-1-0-1700000000.zip').exists(), 'Chrome-style (1) copy not moved under the Nexus name')
    check((c.inbox / 'Beta 12 1.0 2026-11-01T10-00Z abc.tar.gz').exists(), 'Firefox-style (2) copy not moved')
    check(not list(c.dl.iterdir()), 'Downloads not empty')


@case
def partial_then_complete():
    c = Case('partial_then_complete')
    a, b = data('part', 40000), data('crdl', 40000)
    c.want('Firefox', 21, 1, 'Ff 21 1.0 x.7z', a)
    c.want('Chrome', 22, 2, 'Ch 22 1.0 y.zip', b)
    seen = {}

    def start(p):
        (c.dl / 'Ff 21 1.0 x.7z').write_bytes(b'')                   # Firefox's empty placeholder
        (c.dl / 'Ff 21 1.0 x.7z.part').write_bytes(a[:20000])
        (c.dl / 'Unconfirmed 81234.crdownload').write_bytes(b[:10000])

    def mid(p):
        seen['mid'] = sorted(x.name for x in c.inbox.iterdir())
        with open(c.dl / 'Ff 21 1.0 x.7z.part', 'ab') as f:
            f.write(a[20000:])

    def done(p):
        os.replace(c.dl / 'Ff 21 1.0 x.7z.part', c.dl / 'Ff 21 1.0 x.7z')
        (c.dl / 'Unconfirmed 81234.crdownload').write_bytes(b)
        os.replace(c.dl / 'Unconfirmed 81234.crdownload', c.dl / 'Ch 22 1.0 y.zip')
    code, out = c.run(actions=[(0.5, start), (3.5, mid), (4.0, done)])
    check(seen.get('mid') == [], f'something moved while partial: {seen}')
    check(code == 0, out)
    check(md5(c.inbox / 'Ff 21 1.0 x.7z') == hashlib.md5(a).hexdigest(), 'Firefox file wrong')
    check(md5(c.inbox / 'Ch 22 1.0 y.zip') == hashlib.md5(b).hexdigest(), 'Chrome file wrong')


@case
def still_growing():
    c = Case('still_growing')
    full = data('grow', 60000)
    c.want('Grow', 31, 1, 'Grow-31-1-0.zip', full)
    seen = {}
    actions = []
    step = 6000
    for i in range(10):          # 10 appends 0.4 s apart: never still for the 1 s settle time
        def app(p, i=i):
            with open(c.dl / 'Grow-31-1-0.zip', 'ab') as f:
                f.write(full[i * step:(i + 1) * step])
            if i == 9:
                seen['at_end'] = (c.inbox / 'Grow-31-1-0.zip').exists()
        actions.append((0.6 + 0.4 * i, app))
    code, out = c.run(actions=actions)
    check(seen.get('at_end') is False, 'moved while still growing')
    check(code == 0, out)
    check(md5(c.inbox / 'Grow-31-1-0.zip') == hashlib.md5(full).hexdigest(), 'moved file incomplete')


@case
def unknown_untouched():
    c = Case('unknown_untouched')
    blob = data('known', 1000)
    other = data('other', 777)
    c.want('Known', 41, 1, 'Known-41.zip', blob)
    code, out = c.run('-v', actions=[(0.8, lambda p: put(c.dl / 'holiday photo.jpg', other)),
                               (1.6, lambda p: put(c.dl / 'Known-41.zip', blob))])
    check(code == 0, out)
    check(md5(c.dl / 'holiday photo.jpg') == hashlib.md5(other).hexdigest(), 'unknown file touched')
    check('holiday photo.jpg: not on the list, left alone' in out, out)
    check('not on the list (left alone): holiday photo.jpg' in out, 'summary lacks the unknown file')


@case
def right_name_wrong_size():
    c = Case('right_name_wrong_size')
    blob = data('size', 5000)
    c.want('Sized', 51, 1, 'Sized 51 2.0 q.7z', blob)
    code, out = c.run(actions=[(1.0, lambda p: put(c.dl / 'Sized 51 2.0 q.7z', blob[:4000])), (3.5, enter)])
    check(code == 1, f'exit {code}')
    check((c.dl / 'Sized 51 2.0 q.7z').stat().st_size == 4000, 'file touched')
    check(not (c.inbox / 'Sized 51 2.0 q.7z').exists(), 'moved')
    r = c.report()
    check(any('right name, wrong size' in w for w in r['close'].get('Sized 51 2.0 q.7z', [])), r['close'])
    check('Sized: FAILED (in Downloads but not a match: right name, wrong size)' in out
          and 'fetch: 0 fetched, 0 skipped, 1 failed' in out, out)


@case
def right_name_wrong_md5():
    c = Case('right_name_wrong_md5')
    blob = data('real', 5000)
    fake = data('fake', 5000)
    c.want('Hashed', 61, 1, 'Hashed-61-1-0.7z', blob, with_md5=True, dest='archive')
    code, out = c.run(actions=[(1.0, lambda p: put(c.dl / 'Hashed-61-1-0.7z', fake)), (3.5, enter)])
    check(code == 1, f'exit {code}')
    check(md5(c.dl / 'Hashed-61-1-0.7z') == hashlib.md5(fake).hexdigest(), 'file touched')
    check(not any(c.arch.iterdir()), 'something moved')
    check(any('right name, wrong md5' in w for w in c.report()['close'].get('Hashed-61-1-0.7z', [])), out)


@case
def already_at_destination():
    c = Case('already_at_destination')
    have, need = data('have', 3000), data('need', 3000)
    c.want('Have', 71, 1, 'Have-71.7z', have, with_md5=True, dest='archive')
    c.want('Need', 72, 2, 'Need-72.7z', need, with_md5=True, dest='archive')
    (c.arch / 'Have-71.7z').write_bytes(have)
    code, out = c.run('-v', actions=[(1.0, lambda p: put(c.dl / 'Need-72.7z', need))])
    check(code == 0, out)
    urls = [u for _, u in c.opened()]
    check(urls == ['https://www.nexusmods.com/witcher3/mods/72?tab=files&file_id=2'], f'opened {urls}')
    check('= Have' in out and 'present (by md5)' in out and 'Have: skipped (already in place)' in out, out)


@case
def destination_conflict():
    c = Case('destination_conflict')
    new, old = data('new', 4000), data('old', 4100)
    c.want('Clash', 81, 1, 'Clash-81.zip', new)
    (c.inbox / 'Clash-81.zip').write_bytes(old)
    code, out = c.run(actions=[(1.0, lambda p: put(c.dl / 'Clash-81.zip', new))])
    check(code == 1, f'exit {code}\n{out}')
    check(md5(c.inbox / 'Clash-81.zip') == hashlib.md5(old).hexdigest(), 'destination overwritten')
    check(md5(c.dl / 'Clash-81.zip') == hashlib.md5(new).hexdigest(), 'download touched')
    check('Clash: FAILED (a different file of that name is in the destination' in out and 'will not be overwritten' in out, out)


@case
def batch_and_gap():
    c = Case('batch_and_gap')
    blobs = [data(f'm{i}', 1000 + i) for i in range(5)]
    for i, b in enumerate(blobs):
        c.want(f'M{i}', 900 + i, 10 + i, f'M{i}-90{i}.zip', b)
    seen = {}

    def first(p):
        seen['after_batch1'] = len(c.opened())
        for i in (0, 1):
            put(c.dl / f'M{i}-90{i}.zip', blobs[i])

    def second(p):
        seen['after_batch2'] = len(c.opened())
        enter(p)                   # skip the rest of batch 2: batch 3 opens
    code, out = c.run('--batch', '2', actions=[(4.0, first), (9.5, second), (13.0, enter)])
    t = c.opened()
    check(seen['after_batch1'] == 2, f'batch 1 opened {seen["after_batch1"]} pages')
    check(seen['after_batch2'] == 4, f'after batch 1 arrived: {seen["after_batch2"]} pages')
    check(len(t) == 5, f'{len(t)} pages in all')
    gaps = [b - a for (a, _), (b, _) in zip(t, t[1:])]
    check(all(0.95 <= g for g in gaps), f'a gap under 1 s: {gaps}')
    check(gaps[0] <= 2.3 and gaps[2] <= 2.3, f'gaps inside a batch above 2 s: {gaps}')
    check(len({round(g, 2) for g in gaps}) > 1, f'gaps not random: {gaps}')
    check(code == 1 and 'fetch: 2 fetched, 0 skipped, 3 failed' in out, out)
    seen['gaps'] = gaps
    return f'gaps {", ".join(f"{g:.2f}" for g in gaps)} s'


@case
def dry_run():
    c = Case('dry_run')
    a, b, x = data('a', 1000), data('b', 1000), data('x', 1000)
    c.want('A', 1, 1, 'A-1.zip', a, with_md5=True, dest='archive')
    c.want('B', 2, 2, 'B-2.zip', b)
    c.want('X', 3, 3, 'X-3.zip', x)
    (c.dl / 'A-1 (1).zip').write_bytes(a)
    (c.inbox / 'X-3.zip').write_bytes(x)
    before = {p.name: md5(p) for p in c.dir.rglob('*') if p.is_file() and p.name != 'wants.json'}
    code, out = c.run('--dry-run')
    after = {p.name: md5(p) for p in c.dir.rglob('*') if p.is_file() and p.name not in ('wants.json', 'report.json')}
    check(code == 0, out)
    check(not c.log.exists(), 'dry run opened a page')
    check(before == after, 'dry run changed files')
    check('1 click ahead' in out and '1 file(s) already in Downloads would be moved' in out, out)


@case
def ctrl_c_mid_copy():
    c = Case('ctrl_c_mid_copy')
    shm = SHM / 'upwatch-test-archives'
    if shm.exists():
        shutil.rmtree(shm)
    shm.mkdir()
    try:
        blob = os.urandom(30 << 20)
        c.want('Big', 91, 1, 'Big-91.7z', blob, with_md5=True, dest='archive')
        (c.dl / 'Big-91.7z').write_bytes(blob)
        seen = {}

        def interrupt(p):
            end = time.time() + 15
            while time.time() < end and not (shm / ('.Big-91.7z' + '.upwatch-partial')).exists():
                time.sleep(0.02)
            seen['tmp_seen'] = (shm / '.Big-91.7z.upwatch-partial').exists()
            time.sleep(0.3)
            sigint(p)
        code, out = c.run('--yes', archive=shm, env={'UPWATCH_TEST_COPY_DELAY': '0.1'}, actions=[(0.1, interrupt)])
        check(seen.get('tmp_seen'), 'the copy never started (filesystems not different?)')
        check(code == 130, f'exit {code}\n{out}')
        check(not any(shm.iterdir()), f'left in the destination: {list(shm.iterdir())}')
        check(md5(c.dl / 'Big-91.7z') == hashlib.md5(blob).hexdigest(), 'source damaged')
        check('(stopped by Ctrl-C)' in out and 'fetch: 0 fetched, 0 skipped, 1 failed' in out, out)
    finally:
        shutil.rmtree(shm, ignore_errors=True)


@case
def cross_filesystem_move():
    c = Case('cross_filesystem_move')
    shm = SHM / 'upwatch-test-archives2'
    if shm.exists():
        shutil.rmtree(shm)
    shm.mkdir()
    try:
        blob = os.urandom(3 << 20)
        c.want('Far', 92, 1, 'Far-92.7z', blob, with_md5=True, dest='archive')
        (c.dl / 'Far-92 (1).7z').write_bytes(blob)
        code, out = c.run('--yes', archive=shm)
        check(code == 0, out)
        check(md5(shm / 'Far-92.7z') == hashlib.md5(blob).hexdigest(), 'copy wrong')
        check(not (c.dl / 'Far-92 (1).7z').exists(), 'source not removed after a verified copy')
        check([p.name for p in shm.iterdir()] == ['Far-92.7z'], f'leftovers {list(shm.iterdir())}')
    finally:
        shutil.rmtree(shm, ignore_errors=True)


@case
def copy_path_same_filesystem():
    c = Case('copy_path_same_filesystem')
    blob = os.urandom(2 << 20)
    c.want('Copied', 89, 1, 'Copied-89.7z', blob, with_md5=True, dest='archive')
    (c.dl / 'Copied-89.7z').write_bytes(blob)
    code, out = c.run('--yes', env={'UPWATCH_TEST_FORCE_COPY': '1'})
    check(code == 0, out)
    t = c.arch / 'Copied-89.7z'
    check(md5(t) == hashlib.md5(blob).hexdigest() and os.stat(t).st_nlink == 1, 'copy wrong')
    check(not (c.dl / 'Copied-89.7z').exists() and [p.name for p in c.arch.iterdir()] == ['Copied-89.7z'], 'leftovers')


@case
def ctrl_c_idle():
    c = Case('ctrl_c_idle')
    c.want('Wait', 93, 1, 'Wait-93.zip', data('w', 100))
    code, out = c.run(actions=[(3.0, sigint)])
    check(code == 130 and 'Wait: FAILED (not downloaded; stopped by Ctrl-C)' in out
          and 'fetch: 0 fetched, 0 skipped, 1 failed (stopped by Ctrl-C)' in out, f'{code}\n{out}')
    check('Traceback' not in out, out)


@case
def preexisting_offered():
    c = Case('preexisting_offered')
    a, b = data('pa', 900), data('pb', 900)
    c.want('PA', 94, 1, 'PA-94.zip', a)
    c.want('PB', 95, 2, 'PB-95.zip', b)
    (c.dl / 'PA-94.zip').write_bytes(a)
    code, out = c.run(inp='y\n', actions=[(3.0, lambda p: put(c.dl / 'PB-95.zip', b))])
    check(code == 0, out)
    check((c.inbox / 'PA-94.zip').exists() and (c.inbox / 'PB-95.zip').exists(), 'not both moved')
    check([u for _, u in c.opened()] == ['https://www.nexusmods.com/witcher3/mods/95?tab=files&file_id=2'], c.opened())
    c2 = Case('preexisting_declined')
    c2.want('PA', 94, 1, 'PA-94.zip', a)
    (c2.dl / 'PA-94.zip').write_bytes(a)
    code, out = c2.run(inp='n\n')
    check(code == 1 and (c2.dl / 'PA-94.zip').exists() and not (c2.inbox / 'PA-94.zip').exists(), out)
    check('PA: skipped (left in Downloads, as you chose)' in out and not c2.opened(), out)


@case
def name_only():
    c = Case('name_only')
    c.want('Loose', 96, 1, 'Loose-96.zip', None)
    code, out = c.run('-v', actions=[(1.0, lambda p: put(c.dl / 'Loose-96.zip', b'whatever'))])
    check(code == 0 and 'matched by name only' in out and c.report()['items'][0]['how'] == 'name', out)


@case
def bad_list_refused():
    c = Case('bad_list_refused')
    e = c.want('Bad', 97, 1, 'Bad-97.zip', b'x')
    e['url'] = 'https://www.nexusmods.com/witcher3/mods/97?tab=files&file_id=2'
    c.want('Bad2', 98, 2, 'sub/dir.zip', b'x')
    c.files.append({'mod': 'Bad3', 'nexus_mod_id': 99, 'file_id': 3, 'file_name': 'B.zip', 'dest': 'elsewhere', 'md5': 'xyz'})
    code, out = c.run()
    check(code == 2 and not c.log.exists(), f'{code} {out}')
    for s in ('names file_id 2', '"file_name" must be a plain file name', '"dest" must be', '"md5" must be 32 hex'):
        check(s in out, f'missing complaint {s!r}:\n{out}')
    c.files = []
    c.run('--dry-run')
    c.wants.write_text(json.dumps({'format': FMT, 'version': 2, 'files': []}))
    code, out, _ = pty_run([sys.executable, '-I', str(SCRIPT), 'fetch', str(c.wants), '--dry-run', '--downloads', str(c.dl)], c.env())
    check(code == 2 and 'newer than this upwatch' in out, out)
    c.wants.write_text(json.dumps({'format': 'other-format', 'version': 1, 'files': []}))
    code, out, _ = pty_run([sys.executable, '-I', str(SCRIPT), 'fetch', str(c.wants), '--dry-run', '--downloads', str(c.dl)], c.env())
    check(code == 2 and '"format" must be "upwatch-wants"' in out, out)
    for bad in (['--gap', '0.5', '1'], ['--batch', '21'], ['--batch', '0']):
        code, out, _ = pty_run([sys.executable, '-I', str(SCRIPT), 'fetch', str(c.wants)] + bad, c.env())
        check(code == 2 and bad[0] in out, f'{bad} was accepted: {out}')


@case
def wants_dirs_from_config():
    """A rollback-style list ("archive" with size and md5, plus "inbox"): the folders come from [settings]."""
    c = Case('wants_dirs_from_config')
    a, b = data('roll', 7000), data('upd', 3000)
    c.want('Rolled', 15825, 301, 'Rolled 15825 0.9R x.7z', a, with_md5=True, dest='archive', note='rollback')
    c.want('Updated', 15826, 302, 'Updated 15826 1.0 y.7z', b, dest='inbox')
    (c.cfg / 'upwatch').mkdir()
    (c.cfg / 'upwatch' / 'config.toml').write_text(f'[settings]\ninbox_dir = "{c.inbox}"\narchive_dir = "{c.arch}"\n')
    (c.dl / 'whatever name.7z').write_bytes(a)
    (c.dl / 'Updated 15826 1.0 y.7z').write_bytes(b)
    code, out = c.run('--yes', dirs=False)
    check(code == 0, out)
    check(md5(c.arch / 'Rolled 15825 0.9R x.7z') == hashlib.md5(a).hexdigest(), 'archive entry not in archive_dir')
    check((c.inbox / 'Updated 15826 1.0 y.7z').exists() and not (c.arch / 'Updated 15826 1.0 y.7z').exists(), 'inbox entry misplaced')
    r = c.report()
    check({i['mod']: i['how'] for i in r['items']} == {'Rolled': 'md5', 'Updated': 'name+size'}, r['items'])
    (c.cfg / 'upwatch' / 'config.toml').write_text(f'[settings]\ninbox_dir = "{c.inbox}"\n')
    code, out = c.run('--dry-run', dirs=False)
    check(code == 2 and 'archive_dir is not set' in out, out)


@case
def no_network_no_nexus_contact():
    """Static check of the hard lines in the fetch part: no HTTP client, no socket, no API host, no key."""
    src = SCRIPT.read_text()
    part = src[src.index('# ---------------------------------------------------------------- fetch: begin'):
               src.index('# ---------------------------------------------------------------- fetch: end')]
    for bad in ('urlopen', 'urllib.request', 'http_json', 'http.client', 'socket', 'api.nexusmods', 'apikey',
                'Ctx', '.nexus(', '.gh(', 'nexus_key'):
        check(bad not in part, f'{bad!r} appears in the fetch part of upwatch')
    home = str(Path.home())
    check(home == '/' or home not in src, 'a home path is written into the code')


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    print(f'scratch: {ROOT}')
    failed = 0
    for fn in CASES:
        t0 = time.time()
        try:
            extra = fn()
            print(f'PASS {fn.__name__} ({time.time() - t0:.1f} s)' + (f' {extra}' if extra else ''), flush=True)
        except Exception as e:
            failed += 1
            print(f'FAIL {fn.__name__}: {e}', flush=True)
    print(f'{len(CASES) - failed} passed, {failed} failed')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
